import dataclasses

import pytest
from pydantic import BaseModel

from builders import make_ctx, make_fetch, make_job
from helpers import make_image
from tohoku.classify.base import ClassifierError, Verdict
from tohoku.destinations import ClassifierConfig, Destination, DestinationsConfig
from tohoku.errors import ConfigError, QuotaExceeded, TransientError
from tohoku.models import Classification, Transcript
from tohoku.quota import DailyQuota
from tohoku.stages.classify import ClassifyStage
from tohoku.state import StateStore


class FakeClassifier:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def classify(self, text, images, candidates, feedback=None):
        self.calls.append({"text": text, "images": images, "candidates": candidates, "feedback": feedback})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class _P(BaseModel):
    pass


def _config():
    dest = {
        n: Destination(nombre=n, flujo="viaje", raiz="r", descripcion=f"desc {n}", prompt="p", params=_P())
        for n in ("japon", "cocina", "otro")
    }
    return DestinationsConfig(
        listas={}, destinos=dest, clasificador=ClassifierConfig(confianza_minima=0.5, margen_revision=0.15),
        destino_legado="japon",
    )


@pytest.fixture
def state(tmp_path):
    return StateStore(tmp_path / "state.db")


def _run(tmp_path, state, replies, candidates=("japon", "cocina"), destination=None, caption="Un caption",
         text="Hablan de ramen", limit=10.0, images=2, vision="same"):
    job = make_job(candidates=list(candidates) if candidates is not None else None, destination=destination)
    ctx = make_ctx(tmp_path, job)
    rels = [f"images/{i:02}.jpg" for i in range(images)]
    for rel in rels:
        make_image(ctx.workdir / rel, size=(10, 10))
    ctx.results["fetch"] = make_fetch(images=rels, meta=make_fetch().meta.model_copy(update={"description": caption}))
    ctx.results["transcribe"] = Transcript(text=text, origin="whisper")
    fake = FakeClassifier(replies)
    quota = DailyQuota(state, "openrouter_usd", limit)
    # Por defecto el mismo falso hace de clasificador de texto y de imágenes.
    stage = ClassifyStage(_config(), fake, quota, vision_classifier=fake if vision == "same" else vision)
    return stage, ctx, fake, quota


def test_candidato_unico_omite(tmp_path, state):
    stage, ctx, fake, _ = _run(tmp_path, state, [], candidates=("cocina",))
    r = stage.run(ctx)
    assert r == Classification(destino="cocina", omitido=True)
    assert fake.calls == [] and r.cost_usd == 0


def test_job_anterior_usa_legado(tmp_path, state):
    stage, ctx, fake, _ = _run(tmp_path, state, [], candidates=None)
    r = stage.run(ctx)
    assert (r.destino, r.omitido, fake.calls) == ("japon", True, [])


def test_destino_forzado(tmp_path, state):
    stage, ctx, fake, _ = _run(tmp_path, state, [], destination="cocina")
    r = stage.run(ctx)
    assert (r.destino, r.omitido, fake.calls) == ("cocina", True, [])


def test_veredicto_valido_suma_coste(tmp_path, state):
    stage, ctx, fake, _ = _run(tmp_path, state, [Verdict(destino="cocina", confianza=0.9, cost_usd=0.002)])
    r = stage.run(ctx)
    assert (r.destino, r.confianza, r.cost_usd, r.omitido, r.dudosa) == ("cocina", 0.9, 0.002, False, False)
    assert state.get_counter("openrouter_usd") == pytest.approx(0.002)
    assert [c.nombre for c in fake.calls[0]["candidates"]] == ["japon", "cocina"]
    assert fake.calls[0]["candidates"][1].descripcion == "desc cocina"


def test_ninguno_es_descartado(tmp_path, state):
    stage, ctx, _, _ = _run(tmp_path, state, [Verdict(destino=None, confianza=0.9)])
    assert stage.run(ctx).destino is None


def test_confianza_bajo_minimo(tmp_path, state):
    stage, ctx, _, _ = _run(tmp_path, state, [Verdict(destino="japon", confianza=0.4)])
    r = stage.run(ctx)
    assert r.destino is None and r.confianza == 0.4


def test_alternativa_dudosa_segun_margen(tmp_path, state):
    v = Verdict(destino="japon", confianza=0.8, alternativa="cocina", confianza_alternativa=0.7)
    assert _run(tmp_path, state, [v])[0].run(_run(tmp_path, state, [v])[1]).dudosa is True
    v2 = Verdict(destino="japon", confianza=0.8, alternativa="cocina", confianza_alternativa=0.5)
    stage, ctx, _, _ = _run(tmp_path, state, [v2])
    assert stage.run(ctx).dudosa is False
    v3 = Verdict(destino="japon", confianza=0.8, alternativa="ninguno", confianza_alternativa=0.79)
    stage, ctx, _, _ = _run(tmp_path, state, [v3])
    assert stage.run(ctx).dudosa is False


def test_destino_invalido_reintenta_una_vez(tmp_path, state):
    stage, ctx, fake, _ = _run(tmp_path, state, [
        Verdict(destino="inventado", cost_usd=0.001), Verdict(destino="cocina", confianza=0.9, cost_usd=0.002),
    ])
    r = stage.run(ctx)
    assert r.destino == "cocina" and len(fake.calls) == 2
    assert fake.calls[0]["feedback"] is None
    assert "japon" in fake.calls[1]["feedback"] and "cocina" in fake.calls[1]["feedback"]
    assert r.cost_usd == pytest.approx(0.003)
    assert state.get_counter("openrouter_usd") == pytest.approx(0.003)


def test_dos_respuestas_invalidas_es_transitorio(tmp_path, state):
    stage, ctx, fake, _ = _run(tmp_path, state, [
        ClassifierError("json roto", "xx", 0.001), Verdict(destino="inventado", cost_usd=0.002),
    ])
    with pytest.raises(TransientError, match="clasificador: respuesta no válida"):
        stage.run(ctx)
    assert len(fake.calls) == 2
    assert state.get_counter("openrouter_usd") == pytest.approx(0.003)


def test_imagenes_solo_sin_texto(tmp_path, state):
    v = Verdict(destino="japon", confianza=0.9)
    stage, ctx, fake, _ = _run(tmp_path, state, [v], caption=" ", text="", images=3)
    stage.run(ctx)
    assert fake.calls[0]["images"] == [ctx.workdir / "images/00.jpg", ctx.workdir / "images/01.jpg"]
    stage, ctx, fake, _ = _run(tmp_path, state, [v], caption="", text="hola", images=3)
    stage.run(ctx)
    assert fake.calls[0]["images"] == []


def test_presupuesto_agotado(tmp_path, state):
    stage, ctx, fake, _ = _run(tmp_path, state, [Verdict(destino="japon")], limit=0.0)
    with pytest.raises(QuotaExceeded):
        stage.run(ctx)
    assert fake.calls == []


def test_sin_clasificador_es_config_error(tmp_path, state):
    stage, ctx, _, quota = _run(tmp_path, state, [])
    with pytest.raises(ConfigError):
        ClassifyStage(_config(), None, quota).run(ctx)


def test_stale_candidates_are_dropped_before_deciding(tmp_path, state):
    """Un candidato borrado de destinos.yaml no cuenta: queda uno solo y no se llama al LLM."""
    config = _config()
    config = dataclasses.replace(config, destinos={"japon": config.destinos["japon"]})
    ctx = make_ctx(tmp_path, make_job(candidates=["japon", "borrado"]))
    fake = FakeClassifier([])
    result = ClassifyStage(config, fake, DailyQuota(state, "openrouter_usd", 10.0)).run(ctx)
    assert result.destino == "japon" and result.omitido
    assert fake.calls == []


def test_all_candidates_stale_falls_back_to_destino_legado(tmp_path, state):
    ctx = make_ctx(tmp_path, make_job(candidates=["borrado", "otro_borrado"]))
    fake = FakeClassifier([])
    result = ClassifyStage(_config(), fake, DailyQuota(state, "openrouter_usd", 10.0)).run(ctx)
    assert result.destino == "japon" and result.omitido
    assert fake.calls == []


def test_forced_destination_missing_from_config_passes_through(tmp_path, state):
    """El pipeline se encarga de él (PermanentError solo para ese job)."""
    ctx = make_ctx(tmp_path, make_job(candidates=["japon"], destination="borrado"))
    result = ClassifyStage(_config(), FakeClassifier([]), DailyQuota(state, "openrouter_usd", 10.0)).run(ctx)
    assert result.destino == "borrado" and result.omitido


# --- I3: con imágenes, el clasificador multimodal ---------------------------------


def test_images_go_to_the_vision_classifier(tmp_path, state):
    vision = FakeClassifier([Verdict(destino="japon", confianza=0.9, cost_usd=0.003)])
    stage, ctx, fake, _ = _run(tmp_path, state, [], caption="", text="", vision=vision)
    r = stage.run(ctx)
    assert r.destino == "japon" and r.cost_usd == 0.003
    assert fake.calls == []
    assert vision.calls[0]["images"] == [ctx.workdir / "images/00.jpg", ctx.workdir / "images/01.jpg"]


def test_text_goes_to_the_text_classifier(tmp_path, state):
    vision = FakeClassifier([])
    stage, ctx, fake, _ = _run(tmp_path, state, [Verdict(destino="japon", confianza=0.9)], vision=vision)
    stage.run(ctx)
    assert vision.calls == [] and len(fake.calls) == 1 and fake.calls[0]["images"] == []


def test_without_vision_classifier_no_images_are_sent(tmp_path, state):
    stage, ctx, fake, _ = _run(tmp_path, state, [Verdict(destino="japon", confianza=0.9)], caption="", text="", vision=None)
    stage.run(ctx)
    assert fake.calls[0]["images"] == []


# --- C1: la etapa solo necesita los ficheros si va a mandar imágenes ------------------


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({}, False),  # hay texto
        ({"caption": "", "text": ""}, True),  # sin texto: manda imágenes
        ({"caption": "", "text": "", "vision": None}, False),  # sin clasificador multimodal no manda imágenes
        ({"caption": "", "text": "", "candidates": ("cocina",)}, False),  # un solo candidato
        ({"caption": "", "text": "", "candidates": ("cocina", "borrado")}, False),  # queda uno tras quitar el borrado
        ({"caption": "", "text": "", "candidates": None}, False),  # job sin candidatos → destino de reserva
        ({"caption": "", "text": "", "destination": "cocina"}, False),  # destino forzado
    ],
)
def test_needs_files_only_when_images_will_be_sent(tmp_path, state, kwargs, expected):
    stage, ctx, _, _ = _run(tmp_path, state, [], **kwargs)
    assert stage.needs_files_for(ctx) is expected
