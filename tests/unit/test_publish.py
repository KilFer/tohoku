import json
from types import SimpleNamespace

import pytest

from builders import make_cosa, make_ctx, make_extraction, make_fetch, make_geo, make_job, make_lugar, make_meta
from fakes import FakeLLM, FakeTrilium
from tohoku.errors import ApiError, TransientError
from tohoku.models import (
    ExtractResult,
    GeocodeResult,
    GeoOutcome,
    ItemKind,
    Outcome,
    PlannedItem,
    PublishedNote,
    ResolveResult,
    Transcript,
)
from tohoku.quota import DailyQuota
from tohoku.stages.publish import PublishStage
from tohoku.state import StateStore
from tohoku.trilium_layout import init_layout

MERGED = json.dumps({"resumen": "Resumen fusionado", "que_hacer": "Pedir extra de cerdo", "consejos": ["Ir pronto", "Pagar en la máquina"]})
GEO = [GeoOutcome(lugar_index=0, match=make_geo())]


@pytest.fixture
def env(tmp_path, settings):
    trilium = FakeTrilium()
    viajes = trilium.add_note("root", "Viajes")
    trilium.add_note(viajes, "Ideas de Japón", labels={"jrRoot": ""})
    return SimpleNamespace(trilium=trilium, layout=init_layout(trilium), state=StateStore(tmp_path / "state.db"), settings=settings, tmp=tmp_path)


def _stage(env, llm=None):
    return PublishStage(env.trilium, lambda: env.layout, llm or FakeLLM([]), env.settings, DailyQuota(env.state, "openrouter_usd", 10), env.state)


def _ctx(env, bookmark_id, extraction, outcomes, items):
    job = make_job(bookmark_id=bookmark_id, url=f"https://youtu.be/{bookmark_id}")
    return make_ctx(
        env.tmp, job=job,
        fetch=make_fetch(meta=make_meta(url=job.url)),
        transcribe=Transcript(text="texto hablado", origin="whisper"),
        extract=ExtractResult(extraction=extraction),
        geocode=GeocodeResult(outcomes=list(outcomes)),
        resolve=ResolveResult(items=list(items)),
    )


def _item(kind=ItemKind.LUGAR, index=0, action="create", existing=None, reasons=(), key=None, alias_of=None):
    return PlannedItem(
        key=key or f"{kind.value}:{index}", kind=kind, index=index, action=action,
        existing_note_id=existing, alias_of=alias_of, review_reasons=list(reasons),
    )


def test_create_lugar(env):
    result = _stage(env).run(_ctx(env, "b1", make_extraction(lugares=[make_lugar()]), GEO, [_item()]))

    note_id = result.notes[0].note_id
    note = env.trilium.get_note(note_id)
    labels = env.trilium.labels(note_id)
    assert note.parent_note_ids == [env.layout.mapa]
    assert note.relations("template") == [env.layout.plantilla_lugar]
    assert labels["geolocation"] == "35.66,139.7"
    assert labels["googlePlaceId"] == "P1" and labels["fuentes"] == "1" and labels["jrTipo"] == "lugar"
    content = env.trilium.get_content(note_id)
    assert "Ramen en Ichiran Shibuya" in content and "https://youtu.be/b1" in content and "Mis notas" in content
    assert [a.title for a in env.trilium.list_attachments(note_id)] == ["japan-reader.json"]
    assert result.outcome == Outcome.PROCESADO
    assert env.state.published("b1")["lugar:0"].note_id == note_id


def test_merge_adds_source_rewrites_summary_and_keeps_user_notes(env):
    extraction = make_extraction(lugares=[make_lugar()])
    note_id = _stage(env).run(_ctx(env, "b1", extraction, GEO, [_item()])).notes[0].note_id
    content = env.trilium.get_content(note_id)
    env.trilium.set_content(note_id, content.replace("<h2>Mis notas</h2><p></p>", "<h2><strong>Mis notas</strong></h2><p>Reservar el martes</p>"))
    llm = FakeLLM([MERGED])

    result = _stage(env, llm).run(_ctx(env, "b2", extraction, GEO, [_item(action="merge", existing=note_id)]))

    assert result.notes[0].note_id == note_id
    assert env.trilium.labels(note_id)["fuentes"] == "2"
    content = env.trilium.get_content(note_id)
    assert "Resumen fusionado" in content and "Pagar en la máquina" in content
    assert "Reservar el martes" in content
    assert "https://youtu.be/b1" in content and "https://youtu.be/b2" in content
    assert llm.calls[0]["model"] == "text/model"
    assert len(env.trilium.children(env.layout.mapa)) == 1


def test_republishing_same_bookmark_does_not_duplicate(env):
    """Review Focus 3."""
    extraction = make_extraction(lugares=[make_lugar()])
    note_id = _stage(env).run(_ctx(env, "b1", extraction, GEO, [_item()])).notes[0].note_id
    env.state.clear_stages_from("b1", "publish", ["publish"])
    llm = FakeLLM([])

    _stage(env, llm).run(_ctx(env, "b1", extraction, GEO, [_item(action="merge", existing=note_id)]))

    assert llm.calls == []
    assert env.trilium.labels(note_id)["fuentes"] == "1"
    assert env.trilium.get_content(note_id).count("https://youtu.be/b1") == 1


def test_review_items_are_cloned_to_inbox(env):
    items = [_item(reasons=["geocodificacion-ambigua"])]

    result = _stage(env).run(_ctx(env, "b1", make_extraction(lugares=[make_lugar()]), GEO, items))

    note = env.trilium.get_note(result.notes[0].note_id)
    assert set(note.parent_note_ids) == {env.layout.mapa, env.layout.revision}
    assert note.label("revisar") == "geocodificacion-ambigua"
    assert result.outcome == Outcome.REVISAR


def test_reprocessed_item_without_reasons_leaves_the_inbox(env):
    extraction = make_extraction(lugares=[make_lugar()])
    note_id = _stage(env).run(_ctx(env, "b1", extraction, GEO, [_item(reasons=["geocodificacion-ambigua"])])).notes[0].note_id
    env.state.clear_stages_from("b1", "publish", ["publish"])

    result = _stage(env).run(_ctx(env, "b1", extraction, GEO, [_item()]))

    note = env.trilium.get_note(note_id)
    assert result.notes[0].note_id == note_id
    assert note.parent_note_ids == [env.layout.mapa]
    assert note.label("revisar") is None
    assert result.outcome == Outcome.PROCESADO


def test_inbox_keeps_note_while_another_source_has_reasons(env):
    extraction = make_extraction(lugares=[make_lugar()])
    note_id = _stage(env).run(_ctx(env, "b1", extraction, GEO, [_item(reasons=["baja-confianza"])])).notes[0].note_id
    _stage(env, FakeLLM([MERGED])).run(_ctx(env, "b2", extraction, GEO, [_item(action="merge", existing=note_id, reasons=["geocodificacion-ambigua"])]))
    env.state.clear_stages_from("b2", "publish", ["publish"])

    _stage(env).run(_ctx(env, "b2", extraction, GEO, [_item(action="merge", existing=note_id)]))

    note = env.trilium.get_note(note_id)
    assert env.layout.revision in note.parent_note_ids
    assert note.label("revisar") == "baja-confianza"


def test_note_dismissed_by_user_is_not_sent_back_by_a_clean_source(env):
    extraction = make_extraction(lugares=[make_lugar()])
    note_id = _stage(env).run(_ctx(env, "b1", extraction, GEO, [_item(reasons=["baja-confianza"])])).notes[0].note_id
    env.trilium.remove_from_parent(note_id, env.layout.revision)  # el usuario la revisa y la saca

    _stage(env, FakeLLM([MERGED])).run(_ctx(env, "b2", extraction, GEO, [_item(action="merge", existing=note_id)]))

    assert env.trilium.get_note(note_id).parent_note_ids == [env.layout.mapa]


def test_cosa_goes_to_category_and_links_store(env):
    extraction = make_extraction(
        lugares=[make_lugar("Don Quijote Shibuya", categoria="tienda")],
        cosas=[make_cosa("Kit Kat matcha", categoria="souvenirs", donde_lugares=["Don Quijote Shibuya"])],
    )
    items = [_item(), _item(kind=ItemKind.COSA)]

    result = _stage(env).run(_ctx(env, "b1", extraction, GEO, items))

    lugar_id, cosa_id = (n.note_id for n in result.notes)
    cosa = env.trilium.get_note(cosa_id)
    assert cosa.parent_note_ids == [env.layout.categorias["souvenirs"]]
    assert cosa.relations("dondeComprar") == [lugar_id]
    assert cosa.relations("template") == [env.layout.plantilla_cosa]
    assert env.trilium.labels(cosa_id)["jrNombreNorm"] == "kit kat matcha"


def test_failed_extraction_creates_review_note(env):
    items = [PlannedItem(key="fallo", kind=ItemKind.FALLO, index=0, action="create", review_reasons=["extraccion-fallida"])]

    result = _stage(env).run(_ctx(env, "b1", None, [], items))

    note_id = result.notes[0].note_id
    assert env.trilium.get_note(note_id).parent_note_ids == [env.layout.revision]
    assert env.trilium.labels(note_id)["revisar"] == "extraccion-fallida"
    assert "texto hablado" in env.trilium.get_content(note_id)
    assert result.outcome == Outcome.REVISAR


def test_not_japan(env):
    result = _stage(env).run(_ctx(env, "b1", make_extraction(0.1), [], []))
    assert result.notes == [] and result.outcome == Outcome.DESCARTADO


def test_resume_skips_already_published_items(env):
    env.state.record_publish("b1", PublishedNote(key="lugar:0", note_id="nX", action="create"))
    before = len(env.trilium.notes)

    result = _stage(env).run(_ctx(env, "b1", make_extraction(lugares=[make_lugar()]), GEO, [_item()]))

    assert len(env.trilium.notes) == before
    assert result.notes[0].note_id == "nX"


def test_synthetic_summary_note_and_alias(env):
    items = [_item(kind=ItemKind.OTRO, index=-1, key="otro:resumen")]
    result = _stage(env).run(_ctx(env, "b1", make_extraction(), [], items))
    note_id = result.notes[0].note_id
    assert env.trilium.get_note(note_id).parent_note_ids == [env.layout.cultura]
    assert env.trilium.get_note(note_id).title == "Ramen en Tokio"
    assert "Un vídeo sobre Tokio" in env.trilium.get_content(note_id)

    items = [_item(), _item(index=1, action="alias", alias_of="lugar:0")]
    result = _stage(env).run(_ctx(env, "b2", make_extraction(lugares=[make_lugar(), make_lugar("伏見")]), GEO, items))
    assert len(result.notes) == 1


class _FlakyAttachmentTrilium(FakeTrilium):
    """Falla la primera vez que se intenta crear el adjunto `japan-reader.json`."""

    def __init__(self) -> None:
        super().__init__()
        self._attachment_failed = False

    def create_attachment(self, owner_id, title, mime, content, role="file"):
        if not self._attachment_failed:
            self._attachment_failed = True
            raise TransientError("timeout creando el adjunto")
        return super().create_attachment(owner_id, title, mime, content, role)


class _MissingNoteTrilium(FakeTrilium):
    """`get_note` devuelve 404 para una nota que el usuario borró."""

    def get_note(self, note_id):
        if note_id == "gone":
            raise ApiError("trilium", 404, "not found")
        return super().get_note(note_id)


def test_create_is_crash_safe_and_resumes_without_duplicating(tmp_path, settings):
    trilium = _FlakyAttachmentTrilium()
    viajes = trilium.add_note("root", "Viajes")
    trilium.add_note(viajes, "Ideas de Japón", labels={"jrRoot": ""})
    layout = init_layout(trilium)
    state = StateStore(tmp_path / "state.db")
    stage = PublishStage(trilium, lambda: layout, FakeLLM([]), settings, DailyQuota(state, "openrouter_usd", 10), state)
    env = SimpleNamespace(tmp=tmp_path)
    ctx = _ctx(env, "b1", make_extraction(lugares=[make_lugar()]), GEO, [_item()])

    with pytest.raises(TransientError):
        stage.run(ctx)

    result = stage.run(ctx)

    children = trilium.children(layout.mapa)
    assert len(children) == 1
    note_id = children[0]
    assert result.notes[0].note_id == note_id
    assert [a.title for a in trilium.list_attachments(note_id)] == ["japan-reader.json"]
    labels = trilium.labels(note_id)
    assert labels["googlePlaceId"] == "P1"
    assert labels["jrItem"] == "b1:lugar:P1"


def test_merge_target_deleted_falls_back_to_create(tmp_path, settings):
    trilium = _MissingNoteTrilium()
    viajes = trilium.add_note("root", "Viajes")
    trilium.add_note(viajes, "Ideas de Japón", labels={"jrRoot": ""})
    layout = init_layout(trilium)
    state = StateStore(tmp_path / "state.db")
    stage = PublishStage(trilium, lambda: layout, FakeLLM([]), settings, DailyQuota(state, "openrouter_usd", 10), state)
    env = SimpleNamespace(tmp=tmp_path)

    result = stage.run(_ctx(env, "b1", make_extraction(lugares=[make_lugar()]), GEO, [_item(action="merge", existing="gone")]))

    note_id = result.notes[0].note_id
    assert note_id != "gone"
    assert trilium.get_note(note_id).parent_note_ids == [layout.mapa]
    assert trilium.labels(note_id)["jrItem"] == "b1:lugar:P1"


def test_recreating_after_state_reset_reuses_jritem_note_via_merge(env):
    """Review Focus (fix round 2): reprocesar tras `clear_stages_from` no debe borrar "Mis notas"."""
    extraction = make_extraction(lugares=[make_lugar()])
    note_id = _stage(env).run(_ctx(env, "b1", extraction, GEO, [_item()])).notes[0].note_id
    content = env.trilium.get_content(note_id)
    env.trilium.set_content(note_id, content.replace("<h2>Mis notas</h2><p></p>", "<h2><strong>Mis notas</strong></h2><p>Reservar el martes</p>"))
    env.state.clear_stages_from("b1", "publish", ["publish"])
    llm = FakeLLM([])

    result = _stage(env, llm).run(_ctx(env, "b1", extraction, GEO, [_item()]))

    assert result.notes[0].note_id == note_id
    assert len(env.trilium.children(env.layout.mapa)) == 1
    content = env.trilium.get_content(note_id)
    assert "Reservar el martes" in content
    assert env.trilium.labels(note_id)["fuentes"] == "1"
    assert llm.calls == []


def test_reordered_reextraction_keeps_each_place_in_its_own_note(env):
    """Final review 1: la identidad `#jrItem` es por contenido, no por posición."""
    ichiran = make_lugar()
    run1 = _stage(env).run(_ctx(env, "b1", make_extraction(lugares=[ichiran]), GEO, [_item()]))
    ichiran_id = run1.notes[0].note_id
    env.state.clear_stages_from("b1", "publish", ["publish"])
    extraction = make_extraction(lugares=[make_lugar("Fushimi Inari", categoria="santuario"), ichiran])
    geo = [GeoOutcome(lugar_index=0, match=make_geo("PB", "Fushimi Inari")), GeoOutcome(lugar_index=1, match=make_geo("P1"))]
    llm = FakeLLM([])

    result = _stage(env, llm).run(_ctx(env, "b1", extraction, geo, [_item(), _item(index=1)]))

    fushimi_id, second_id = (n.note_id for n in result.notes)
    assert second_id == ichiran_id and fushimi_id != ichiran_id
    assert len(env.trilium.children(env.layout.mapa)) == 2
    assert env.trilium.labels(fushimi_id)["googlePlaceId"] == "PB"
    assert "Ramen en Fushimi Inari" in env.trilium.get_content(fushimi_id)
    assert "Ramen en Ichiran Shibuya" in env.trilium.get_content(ichiran_id)
    assert "Fushimi" not in env.trilium.get_content(ichiran_id)
    assert env.trilium.labels(fushimi_id)["jrItem"] == "b1:lugar:PB"
    assert llm.calls == []


def test_reprocess_single_source_note_refreshes_text_without_llm(env):
    """Final review 1: reprocesar una nota con una sola fuente regenera su texto."""
    note_id = _stage(env).run(_ctx(env, "b1", make_extraction(lugares=[make_lugar()]), GEO, [_item()])).notes[0].note_id
    content = env.trilium.get_content(note_id)
    env.trilium.set_content(note_id, content.replace("<h2>Mis notas</h2><p></p>", "<h2>Mis notas</h2><p>Reservar el martes</p>"))
    env.state.clear_stages_from("b1", "publish", ["publish"])
    changed = make_extraction(lugares=[make_lugar(que_es="Ramen de cerdo muy famoso", consejos=["Ir de noche"])])
    llm = FakeLLM([])

    _stage(env, llm).run(_ctx(env, "b1", changed, GEO, [_item(action="merge", existing=note_id)]))

    content = env.trilium.get_content(note_id)
    assert "Ramen de cerdo muy famoso" in content and "Ir de noche" in content
    assert "Ramen en Ichiran Shibuya" not in content
    assert "Reservar el martes" in content
    assert env.trilium.labels(note_id)["fuentes"] == "1"
    assert llm.calls == []
    data = json.loads(env.trilium.get_attachment_content(env.trilium.list_attachments(note_id)[0].attachment_id))
    assert data["resumen"] == "Ramen de cerdo muy famoso" and data["place"]["place_id"] == "P1"


def test_reprocess_multi_source_note_only_replaces_its_source(env):
    extraction = make_extraction(lugares=[make_lugar()])
    note_id = _stage(env).run(_ctx(env, "b1", extraction, GEO, [_item()])).notes[0].note_id
    _stage(env, FakeLLM([MERGED])).run(_ctx(env, "b2", extraction, GEO, [_item(action="merge", existing=note_id)]))
    env.state.clear_stages_from("b2", "publish", ["publish"])
    llm = FakeLLM([])

    changed = make_extraction(lugares=[make_lugar(que_es="Otro texto")])
    _stage(env, llm).run(_ctx(env, "b2", changed, GEO, [_item(action="merge", existing=note_id)]))

    content = env.trilium.get_content(note_id)
    assert "Resumen fusionado" in content and "Otro texto" in content  # aporte de la fuente b2
    assert env.trilium.labels(note_id)["fuentes"] == "2"
    assert llm.calls == []


def test_create_merges_into_existing_note_with_same_natural_key(env):
    """Plan de resolve obsoleto: dice `create` pero ya hay una nota con el mismo googlePlaceId."""
    extraction = make_extraction(lugares=[make_lugar()])
    note_id = _stage(env).run(_ctx(env, "b1", extraction, GEO, [_item()])).notes[0].note_id

    result = _stage(env, FakeLLM([MERGED])).run(_ctx(env, "b2", extraction, GEO, [_item()]))

    assert result.notes[0].note_id == note_id
    assert len(env.trilium.children(env.layout.mapa)) == 1
    assert env.trilium.labels(note_id)["fuentes"] == "2"


def test_create_ungeocoded_lugar_merges_into_existing_note_with_same_name(env):
    extraction = make_extraction(lugares=[make_lugar("Línea Yamanote")])
    failed = [GeoOutcome(lugar_index=0, review_reason="geocodificacion-fallida")]
    note_id = _stage(env).run(_ctx(env, "b1", extraction, failed, [_item(reasons=["geocodificacion-fallida"])])).notes[0].note_id

    result = _stage(env, FakeLLM([MERGED])).run(_ctx(env, "b2", extraction, failed, [_item(reasons=["geocodificacion-fallida"])]))

    assert result.notes[0].note_id == note_id
    assert env.trilium.labels(note_id)["fuentes"] == "2"


def test_create_merges_into_same_name_note_nearby_with_other_place_id(env):
    """Plan obsoleto: otra fuente creó la misma nota con otra ficha de Google a pocos metros."""
    extraction = make_extraction(lugares=[make_lugar("Omoide Yokocho")])
    first = [GeoOutcome(lugar_index=0, match=make_geo("OLD", "Omoide Yokocho", lat=35.6930, lng=139.6995))]
    note_id = _stage(env).run(_ctx(env, "b1", extraction, first, [_item()])).notes[0].note_id

    second = [GeoOutcome(lugar_index=0, match=make_geo("NEW", "Omoide Yokochō", lat=35.6933, lng=139.6997))]
    result = _stage(env, FakeLLM([MERGED])).run(_ctx(env, "b2", extraction, second, [_item()]))

    assert result.notes[0].note_id == note_id
    assert env.trilium.labels(note_id)["googlePlaceId"] == "OLD"
    assert env.trilium.labels(note_id)["fuentes"] == "2"


def test_create_cosa_merges_into_existing_note_with_same_name(env):
    extraction = make_extraction(cosas=[make_cosa("Kit Kat matcha", categoria="souvenirs")])
    item = _item(kind=ItemKind.COSA)
    note_id = _stage(env).run(_ctx(env, "b1", extraction, [], [item])).notes[0].note_id
    assert env.trilium.labels(note_id)["jrItem"] == "b1:cosa:kit kat matcha"

    result = _stage(env, FakeLLM([MERGED])).run(_ctx(env, "b2", extraction, [], [item]))

    assert result.notes[0].note_id == note_id
    assert len(env.trilium.children(env.layout.categorias["souvenirs"])) == 1


def test_merge_keeps_user_corrected_managed_labels(env):
    """Final review 2: no se deshacen las correcciones del usuario en atributos gestionados."""
    extraction = make_extraction(lugares=[make_lugar()])
    note_id = _stage(env).run(_ctx(env, "b1", extraction, GEO, [_item()])).notes[0].note_id
    geo_attr = env.trilium.get_note(note_id).attr("label", "geolocation")
    env.trilium.update_attribute(geo_attr.attribute_id, "35.0,135.0")
    icon_attr = env.trilium.get_note(note_id).attr("label", "iconClass")
    env.trilium.delete_attribute(icon_attr.attribute_id)

    _stage(env, FakeLLM([MERGED])).run(_ctx(env, "b2", extraction, GEO, [_item(action="merge", existing=note_id)]))

    labels = env.trilium.labels(note_id)
    assert labels["geolocation"] == "35.0,135.0"
    assert labels["fuentes"] == "2"
    assert labels["iconClass"] == "bx bx-bowl-hot"  # ausente → se vuelve a escribir
    assert labels["googlePlaceId"] == "P1"


def test_merge_updates_managed_labels_the_user_did_not_touch(env):
    extraction = make_extraction(lugares=[make_lugar(ciudad=None)])
    note_id = _stage(env).run(_ctx(env, "b1", extraction, GEO, [_item()])).notes[0].note_id
    categoria = env.trilium.labels(note_id)["categoria"]
    assert categoria == "comida"
    env.state.clear_stages_from("b1", "publish", ["publish"])

    changed = make_extraction(lugares=[make_lugar(categoria="bar", ciudad="Tokio")])
    _stage(env).run(_ctx(env, "b1", changed, GEO, [_item(action="merge", existing=note_id)]))

    labels = env.trilium.labels(note_id)
    assert labels["categoria"] == "bar" and labels["ciudad"] == "Tokio"


def test_synthetic_note_title_falls_back_to_description(env):
    """Final review minor f."""
    items = [_item(kind=ItemKind.OTRO, index=-1, key="otro:resumen")]
    ctx = _ctx(env, "b1", make_extraction(), [], items)
    long_line = "Consejos para viajar a Japón " * 5
    ctx.results["fetch"] = make_fetch(meta=make_meta(url="https://youtu.be/b1", title="", description=f"{long_line}\nsegunda línea"))

    note_id = _stage(env).run(ctx).notes[0].note_id

    assert env.trilium.get_note(note_id).title == long_line.strip()[:80]

    ctx2 = _ctx(env, "b2", make_extraction(), [], items)
    ctx2.results["fetch"] = make_fetch(meta=make_meta(url="https://youtu.be/b2", title=None, description=None))
    note_id = _stage(env).run(ctx2).notes[0].note_id
    assert env.trilium.get_note(note_id).title == "Sin título"
