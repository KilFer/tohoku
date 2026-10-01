import pytest
from types import SimpleNamespace

from builders import make_ctx, make_fetch, make_job, make_meta
from fakes import FakeTrilium
from helpers import make_image
from tohoku.clients.trilium import image_src
from tohoku.errors import TransientError
from tohoku.flows.receta.models import CoverResult, Ingrediente, RecetaData, RecetaExtraction, load_data
from tohoku.flows.receta.extract import RecetaExtractResult
from tohoku.flows.receta.layout import init_receta_layout
from tohoku.flows.receta.params import RecetaParams
from tohoku.flows.receta.publish import RecetaPublishStage
from tohoku.flows.receta.render import render_receta
from tohoku.flows.receta.resolve import RecetaResolveStage
from tohoku.models import Classification, ItemKind, Outcome, ResolveResult, Transcript
from tohoku.notes import DATA_ATTACHMENT_TITLE, SourceEntry, name_key
from tohoku.state import StateStore

ROOT = "jrRootRecetas"


def make_receta(**overrides) -> RecetaExtraction:
    base = {
        "relacionado_destino": True, "confianza_destino": 0.95, "titulo": "Tortilla de patatas", "resumen": "Tortilla jugosa",
        "raciones": 4, "tiempo_min": 40, "dificultad": "facil", "tipo_plato": "principal", "cocina": "espanola",
        "ingredientes": [
            Ingrediente(cantidad="6", ingrediente="huevos", grupo=None),
            Ingrediente(cantidad="500", unidad="g", ingrediente="patatas", nota="peladas", grupo="Base"),
            Ingrediente(ingrediente="sal", grupo="Final"),
            Ingrediente(cantidad="1", ingrediente="cebolla", grupo="Base"),
        ],
        "pasos": ["Pelar patatas", "Cuajar"], "consejos": ["Dar la vuelta con plato"], "confianza": 0.9,
    }
    return RecetaExtraction(**(base | overrides))


@pytest.fixture
def env(tmp_path, settings):
    trilium = FakeTrilium()
    trilium.add_note("root", "Recetas", labels={ROOT: ""})
    layout = init_receta_layout(trilium, ROOT, RecetaParams())
    return SimpleNamespace(trilium=trilium, layout=layout, state=StateStore(tmp_path / "state.db"), settings=settings, tmp=tmp_path)


def _ctx(env, bookmark_id="b1", extraction=None, error=None, cover=None, classify=None, resolve=None):
    job = make_job(bookmark_id=bookmark_id, url=f"https://youtu.be/{bookmark_id}")
    ctx = make_ctx(
        env.tmp, job=job, fetch=make_fetch(meta=make_meta(url=job.url)),
        transcribe=Transcript(text="texto", origin="whisper"),
        extract=RecetaExtractResult(extraction=extraction, error=error),
        cover=CoverResult(path=cover),
    )
    if classify:
        ctx.results["classify"] = classify
    ctx.results["resolve"] = resolve or _resolve(env, ctx)
    return ctx


def _resolve(env, ctx):
    return RecetaResolveStage(env.trilium, lambda: env.layout, env.settings.thresholds).run(ctx)


def _publish(env, ctx, trilium=None):
    stage = RecetaPublishStage(trilium or env.trilium, lambda: env.layout, env.settings, env.state)
    return stage.run(ctx)


def _cover(ctx, name="cover.jpg"):
    make_image(ctx.workdir / name, size=(300, 200))
    return name


# --- resolve ---

def test_resolve_failure_and_discard(env):
    ctx = _ctx(env, extraction=None, error="x", resolve=ResolveResult())
    plan = _resolve(env, ctx)
    assert [(i.kind, i.review_reasons) for i in plan.items] == [(ItemKind.FALLO, ["extraccion-fallida"])]
    ctx = _ctx(env, extraction=make_receta(confianza_destino=0.1), resolve=ResolveResult())
    assert _resolve(env, ctx).items == []


def test_resolve_reasons(env):
    ctx = _ctx(env, extraction=make_receta(confianza_destino=0.6, confianza=0.1), classify=Classification(destino="recetas", dudosa=True), resolve=ResolveResult())
    (item,) = _resolve(env, ctx).items
    assert item.kind == ItemKind.RECETA and item.action == "create"
    assert set(item.review_reasons) == {"clasificacion-incierta", "clasificacion-dudosa", "baja-confianza"}


def test_resolve_possible_duplicate_ignores_own_note(env):
    ctx = _ctx(env, "b1", extraction=make_receta())
    _publish(env, ctx)
    again = _ctx(env, "b1", extraction=make_receta(), resolve=ResolveResult())
    assert _resolve(env, again).items[0].review_reasons == []
    other = _ctx(env, "b2", extraction=make_receta(titulo="Tortilla de patata"), resolve=ResolveResult())
    assert "posible-duplicado" in _resolve(env, other).items[0].review_reasons


# --- render ---

def _data(**overrides):
    ex = make_receta()
    base = dict(
        titulo=ex.titulo, resumen=ex.resumen, ingredientes=ex.ingredientes, pasos=ex.pasos, consejos=ex.consejos,
        fuentes=[SourceEntry(bookmark_id="b1", url="https://youtu.be/b1", platform="youtube", content_type="video", title="T")],
    )
    return RecetaData(**(base | overrides))


def test_render_sections_order_and_groups():
    html = render_receta(_data(), image_src("a1", "portada.jpg"))
    assert html.startswith('<p><img src="api/attachments/a1/image/portada.jpg"')
    order = [html.index(h) for h in ("<h2>Resumen", "<h2>Ingredientes", "<h2>Preparación", "<h2>Consejos", "<h2>Fuentes")]
    assert order == sorted(order)
    assert "<ol><li>Pelar patatas</li><li>Cuajar</li></ol>" in html
    # grupos en orden de aparición: sin grupo, Base (huevos/patatas/cebolla agrupadas), Final
    assert html.index("6 huevos") < html.index("Base</h3>") < html.index("500 g patatas (peladas)") < html.index("1 cebolla") < html.index("Final</h3>") < html.index("sal</li>")
    assert html.count("<ul>") == 3 + 2  # tres listas de ingredientes + consejos + fuentes


def test_render_without_cover():
    assert "<img" not in render_receta(_data(), None)


def test_data_roundtrip():
    data = _data(portada_adjunto="x1")
    from tohoku.flows.receta.models import dump_data
    assert load_data(dump_data(data)) == data


# --- publish ---

def test_create_with_cover(env):
    ctx = _ctx(env, extraction=make_receta())
    ctx.results["cover"] = CoverResult(path=_cover(ctx))
    result = _publish(env, ctx)
    assert result.outcome == Outcome.PROCESADO
    (published,) = result.notes
    note = env.trilium.get_note(published.note_id)
    assert note.parent_note_ids == [env.layout.recetario] and note.title == "Tortilla de patatas"
    assert note.relations("template") == [env.layout.plantilla_receta]
    labels = env.trilium.labels(note.note_id)
    assert labels["jrItem"] == "b1:receta:" + labels["jrNombreNorm"]
    assert labels["jrTipo"] == "receta" and labels["fuentes"] == "1" and labels["iconClass"] == "bx bx-bowl-rice"
    assert (labels["tipo_plato"], labels["cocina"], labels["tiempo_min"], labels["raciones"], labels["dificultad"]) == ("principal", "espanola", "40", "4", "facil")
    assert "probada" not in labels and "valoracion" not in labels
    attachments = {a.title: a for a in env.trilium.list_attachments(note.note_id)}
    assert set(attachments) == {"portada.jpg", DATA_ATTACHMENT_TITLE}
    assert env.trilium.attachments[attachments["portada.jpg"].attachment_id]["content"]
    content = env.trilium.get_content(note.note_id)
    assert content.startswith(f'<p><img src="{image_src(attachments["portada.jpg"].attachment_id, "portada.jpg")}"')
    assert content.endswith("<h2>Mis notas</h2><p></p>")
    stored = load_data(env.trilium.get_attachment_content(attachments[DATA_ATTACHMENT_TITLE].attachment_id))
    assert stored.portada_adjunto == attachments["portada.jpg"].attachment_id and stored.kind == "receta"


def test_create_without_cover(env):
    ctx = _ctx(env, extraction=make_receta())
    (published,) = _publish(env, ctx).notes
    titles = [a.title for a in env.trilium.list_attachments(published.note_id)]
    assert titles == [DATA_ATTACHMENT_TITLE]
    assert "<img" not in env.trilium.get_content(published.note_id)


def test_reprocess_keeps_user_edits(env):
    ctx = _ctx(env, extraction=make_receta())
    (published,) = _publish(env, ctx).notes
    nid = published.note_id
    env.trilium.set_content(nid, env.trilium.get_content(nid).replace("<h2>Mis notas</h2><p></p>", "<h2>Mis notas</h2><p>Me salió genial</p>"))
    env.trilium.add_label(nid, "probada", "true")
    env.trilium.add_label(nid, "valoracion", "5")
    cocina = next(a for a in env.trilium.attrs.values() if a["note"] == nid and a["name"] == "cocina")
    cocina["value"] = "vasca"

    ctx2 = _ctx(env, extraction=make_receta(cocina="gallega", tiempo_min=55, pasos=["Nuevo paso"], resumen="Otro resumen"))
    env.state.clear_stages_from("b1", "publish", ("publish",))  # reprocesado: se olvida lo publicado
    result = _publish(env, ctx2)

    assert [n.note_id for n in result.notes] == [nid]
    assert len(env.trilium.children(env.layout.recetario)) == 1
    labels = env.trilium.labels(nid)
    assert labels["cocina"] == "vasca" and labels["probada"] == "true" and labels["valoracion"] == "5"
    assert labels["tiempo_min"] == "55"
    content = env.trilium.get_content(nid)
    assert "Me salió genial" in content and "Nuevo paso" in content and "Otro resumen" in content


def test_reprocess_with_new_title_reuses_note(env):
    (published,) = _publish(env, _ctx(env, extraction=make_receta())).notes
    nid = published.note_id
    env.trilium.set_content(nid, env.trilium.get_content(nid).replace("<h2>Mis notas</h2><p></p>", "<h2>Mis notas</h2><p>Mis apuntes</p>"))
    env.trilium.add_label(nid, "probada", "true")

    env.state.clear_stages_from("b1", "publish", ("publish",))
    ctx2 = _ctx(env, extraction=make_receta(titulo="Tortilla española"))
    assert ctx2.results["resolve"].items[0].review_reasons == []
    result = _publish(env, ctx2)

    assert [n.note_id for n in result.notes] == [nid] and result.outcome == Outcome.PROCESADO
    assert env.trilium.children(env.layout.recetario) == [nid]
    note = env.trilium.get_note(nid)
    assert note.title == "Tortilla española"
    labels = env.trilium.labels(nid)
    assert labels["jrItem"] == "b1:receta:" + labels["jrNombreNorm"] and "espanola" in labels["jrItem"]
    assert labels["probada"] == "true" and labels["jrNombreNorm"] == name_key("Tortilla española")
    assert "Mis apuntes" in env.trilium.get_content(nid)


def test_possible_duplicate_goes_to_inbox(env):
    _publish(env, _ctx(env, "b1", extraction=make_receta()))
    result = _publish(env, _ctx(env, "b2", extraction=make_receta(titulo="Tortilla de patata")))
    assert result.outcome == Outcome.REVISAR
    nid = result.notes[0].note_id
    assert env.layout.revision in env.trilium.get_note(nid).parent_note_ids
    assert "posible-duplicado" in env.trilium.labels(nid)["revisar"]


class FlakyUpload(FakeTrilium):
    """Como Trilium real: el POST del adjunto sale bien y la subida binaria falla."""

    def __init__(self, source: FakeTrilium) -> None:
        self.__dict__ = source.__dict__
        self.fail = True

    def create_image_attachment(self, owner_id, title, data, mime="image/jpeg"):
        attachment_id = self.create_attachment(owner_id, title, mime, "", role="image")
        self.attachments[attachment_id]["content"] = b""
        if self.fail:
            self.fail = False
            raise TransientError("fallo de subida")
        self.set_attachment_data(attachment_id, data)
        return attachment_id


def test_cover_upload_failure_then_retry_no_duplicates(env):
    flaky = FlakyUpload(env.trilium)
    ctx = _ctx(env, extraction=make_receta())
    ctx.results["cover"] = CoverResult(path=_cover(ctx))
    with pytest.raises(TransientError):
        _publish(env, ctx, trilium=flaky)
    result = _publish(env, ctx, trilium=flaky)
    (published,) = result.notes
    assert len(env.trilium.children(env.layout.recetario)) == 1
    portadas = [a for a in env.trilium.list_attachments(published.note_id) if a.title == "portada.jpg"]
    assert len(portadas) == 1
    assert env.trilium.attachments[portadas[0].attachment_id]["content"] not in (b"", None)
    assert f"api/attachments/{portadas[0].attachment_id}/image/portada.jpg" in env.trilium.get_content(published.note_id)


def test_failure_note_in_inbox(env):
    ctx = _ctx(env, extraction=None, error="LLM roto")
    result = _publish(env, ctx)
    assert result.outcome == Outcome.REVISAR
    nid = result.notes[0].note_id
    assert env.trilium.get_note(nid).parent_note_ids == [env.layout.revision]
    assert env.trilium.labels(nid)["jrTipo"] == "fallo"


def test_not_relevant_is_discarded(env):
    ctx = _ctx(env, extraction=make_receta(confianza_destino=0.05))
    result = _publish(env, ctx)
    assert result.outcome == Outcome.DESCARTADO and result.notes == []
    assert env.trilium.children(env.layout.recetario) == []
