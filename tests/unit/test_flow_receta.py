from pathlib import Path

import pytest

from builders import make_ctx, make_fetch, make_job, make_meta
from fakes import FakeKarakeep, FakeLLM, FakeTrilium
from tohoku.clients.karakeep import Bookmark
from tohoku.clients.places import PlacesClient
from tohoku.destinations import Destination
from tohoku.errors import ConfigError
from tohoku.flows.base import FlowDeps
from tohoku.flows.receta.extract import RecetaExtractResult
from tohoku.flows.receta.models import CoverResult
from tohoku.flows.receta.params import RecetaParams
from tohoku.flows.registry import FLOWS
from tohoku.ingest import ingest
from tohoku.models import Classification, Outcome, PublishResult, Transcript
from tohoku.pipeline import STAGE_ORDER, Pipeline
from tohoku.quota import DailyQuota
from tohoku.sources import ContentHint, Platform
from tohoku.state import JobStatus, StateStore
from tohoku.wiring import build_app

from test_pipeline import FakeMark, FakeNotifier, Step, NOW
from test_receta_publish import make_receta

ROOT = "jrRootRecetas"
REPO = Path(__file__).parents[2]


def _dest(**params):
    return Destination(nombre="recetas", flujo="receta", raiz=ROOT, descripcion="Recetas", prompt="PROMPT RECETAS",
                       params=RecetaParams(**params))


def _deps(settings, tmp_path, trilium):
    state = StateStore(tmp_path / "state.db")
    return FlowDeps(settings=settings, state=state, trilium=trilium, llm=FakeLLM([]), places=PlacesClient("k"),
                    llm_budget=DailyQuota(state, "openrouter_usd", 1), places_quota=DailyQuota(state, "places_calls", 1))


def _trilium():
    trilium = FakeTrilium()
    trilium.add_note("root", "Recetas", labels={ROOT: ""})
    return trilium


def test_receta_is_registered():
    assert FLOWS["receta"].params_model is RecetaParams
    assert FLOWS["receta"].name == "receta"


def test_build_gives_the_flow_stages_in_order(settings, tmp_path):
    runtime = FLOWS["receta"].build(_dest(), _deps(settings, tmp_path, _trilium()))
    assert [s.name for s in runtime.stages] == ["extract", "cover", "resolve", "publish"]


def test_extract_stage_gets_the_prompt_as_is(settings, tmp_path):
    runtime = FLOWS["receta"].build(_dest(), _deps(settings, tmp_path, _trilium()))
    assert next(s for s in runtime.stages if s.name == "extract").system_prompt == "PROMPT RECETAS"


def test_init_trilium_creates_the_structure_and_refresh_resolves_it(settings, tmp_path):
    trilium = _trilium()
    runtime = FLOWS["receta"].build(_dest(), _deps(settings, tmp_path, trilium))
    with pytest.raises(ConfigError, match="init-trilium"):
        runtime.refresh()

    summary = FLOWS["receta"].init_trilium(trilium, _dest())

    layout = runtime.refresh()
    assert "Recetario=" in summary and "Revisión=" in summary
    assert layout.recetario in summary


def test_custom_attributes_reach_the_template_and_publish(settings, tmp_path):
    trilium = _trilium()
    dest = _dest(atributos={"tipo_plato": "text", "probada": "boolean"}, atributos_usuario=["probada"])
    FLOWS["receta"].init_trilium(trilium, dest)
    publish = next(s for s in FLOWS["receta"].build(dest, _deps(settings, tmp_path, trilium)).stages if s.name == "publish")
    assert publish._params == dest.params


# --- Review Focus 5: YAML with japon and recetas --------------------------------------------


def _japon_y_recetas(settings, tmp_path):
    text = (REPO / "tests/fixtures/destinos.yaml").read_text(encoding="utf-8").replace("../../config", str(REPO / "config"))
    text = text.replace("L1: [japon]", "L1: [japon]\n  L2: [recetas]")
    text += f"  recetas:\n    flujo: receta\n    raiz: {ROOT}\n    descripcion: Recetas\n    prompt: {REPO / 'config/prompts/recetas.md'}\n"
    text += "destino_por_defecto: japon\n"
    path = tmp_path / "destinos.yaml"
    path.write_text(text, encoding="utf-8")
    return settings.model_copy(update={"destinos_file": path})


def test_build_app_with_japon_and_recetas_uses_each_flow(settings, tmp_path):
    app = build_app(_japon_y_recetas(settings, tmp_path))
    assert set(app.runtimes) == {"japon", "recetas"}
    assert [s.name for s in app.runtimes["japon"].stages] == ["extract", "geocode", "resolve", "publish"]
    assert [s.name for s in app.runtimes["recetas"].stages] == ["extract", "cover", "resolve", "publish"]
    assert "receta" in next(s for s in app.runtimes["recetas"].stages if s.name == "extract").system_prompt.lower()
    assert app.destinations.needs_classifier()
    assert app.classifier is not None and app.classifier._model == "text/model"  # the one the preflight checks


def test_single_candidate_jobs_skip_the_classifier(settings, tmp_path):
    app = build_app(_japon_y_recetas(settings, tmp_path))
    state = StateStore(tmp_path / "ingest.db")
    karakeep = FakeKarakeep([Bookmark(id="r1", url="https://www.instagram.com/reel/AAA/")])
    karakeep.lists = {"L2": ["r1"]}
    ingest(karakeep, state, "L2", app.destinations.candidates_for("L2"))
    job = state.get_job("r1")
    assert job.candidates == ["recetas"]
    classify = next(s for s in app.stages if s.name == "classify")
    ctx = make_ctx(tmp_path, job=job, fetch=make_fetch(), transcribe=Transcript(text="", origin="whisper"))
    result = classify.run(ctx)  # a single candidate: does not call the LLM (the app's FakeLLM has no responses)
    assert result.destino == "recetas"


# --- Review Focus 1: reprocess --from extract clears cover ---------------------------------


def test_reprocess_from_extract_reruns_cover(tmp_path):
    state = StateStore(tmp_path / "state.db", clock=lambda: NOW)
    state.add_job("b1", "https://youtu.be/b1", Platform.YOUTUBE, ContentHint.VIDEO)
    steps = {n: Step(n) for n in ("fetch", "transcribe")}
    flow_steps = {n: Step(n) for n in ("extract", "cover", "resolve")}
    publish = Step("publish", result=PublishResult(outcome=Outcome.PROCESADO))
    classify = Step("classify", result=Classification(destino="recetas"))
    pipeline = Pipeline(state, [steps["fetch"], steps["transcribe"], classify], FakeMark(), FakeNotifier(),
                        tmp_path / "data", clock=lambda: NOW,
                        flows={"recetas": [*flow_steps.values(), publish]})
    pipeline.run_due()
    assert flow_steps["cover"].calls == 1

    state.reset("b1")
    state.clear_stages_from("b1", "extract", STAGE_ORDER)
    pipeline.run_due()

    assert flow_steps["extract"].calls == 2 and flow_steps["cover"].calls == 2
    assert steps["fetch"].calls == 1  # without cleanup it is not downloaded again
    assert state.get_job("b1").status == JobStatus.DONE


def test_reprocess_from_extract_after_cleanup_downloads_again(tmp_path):
    from builders import make_fetch as mf
    from tohoku.cleanup import Cleaner
    from test_pipeline import WritingStep

    state = StateStore(tmp_path / "state.db", clock=lambda: NOW)
    state.add_job("b1", "https://youtu.be/b1", Platform.YOUTUBE, ContentHint.VIDEO)
    data_dir = tmp_path / "data"
    fetch = WritingStep("fetch", result=mf())
    transcribe = Step("transcribe")
    extract = Step("extract")
    extract.needs_files = True
    cover = Step("cover")
    cover.needs_files = True
    publish = Step("publish", result=PublishResult(outcome=Outcome.PROCESADO))
    classify = Step("classify", result=Classification(destino="recetas"))
    cleaner = Cleaner(state, data_dir, 30, clock=lambda: NOW)
    pipeline = Pipeline(state, [fetch, transcribe, classify], FakeMark(), FakeNotifier(), data_dir, clock=lambda: NOW,
                        flows={"recetas": [extract, cover, publish]}, cleaner=cleaner)
    pipeline.run_due()
    state.reset("b1")
    state.clear_stages_from("b1", "extract", STAGE_ORDER)

    pipeline.run_due()

    assert fetch.calls == 2 and extract.calls == 2 and cover.calls == 2


# --- Review Focus 4: a recipe that is not one --------------------------------------------


def test_not_a_recipe_is_discarded_without_note_and_without_destination(settings, tmp_path):
    trilium = _trilium()
    dest = _dest()
    FLOWS["receta"].init_trilium(trilium, dest)
    runtime = FLOWS["receta"].build(dest, _deps(settings, tmp_path, trilium))
    resolve = next(s for s in runtime.stages if s.name == "resolve")
    publish = next(s for s in runtime.stages if s.name == "publish")
    job = make_job(bookmark_id="b9", url="https://youtu.be/b9")
    ctx = make_ctx(tmp_path, job=job, fetch=make_fetch(meta=make_meta(url=job.url)),
                   transcribe=Transcript(text="un baile", origin="whisper"),
                   extract=RecetaExtractResult(extraction=make_receta(relacionado_destino=False, confianza_destino=0.02)),
                   cover=CoverResult())
    ctx.results["resolve"] = resolve.run(ctx)
    result = publish.run(ctx)
    assert result.outcome == Outcome.DESCARTADO and result.notes == []
    assert trilium.children(runtime.refresh().recetario) == []

    state = StateStore(tmp_path / "p.db", clock=lambda: NOW)
    state.add_job("b9", job.url, Platform.YOUTUBE, ContentHint.VIDEO)
    mark = FakeMark()
    pipeline = Pipeline(state, [Step("classify", result=Classification(destino="recetas"))], mark, FakeNotifier(),
                        tmp_path / "data", clock=lambda: NOW,
                        flows={"recetas": [Step("publish", result=result)]})
    pipeline.run_due()
    assert mark.calls == [("b9", Outcome.DESCARTADO)]
