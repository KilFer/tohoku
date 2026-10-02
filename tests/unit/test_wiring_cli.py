from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import BaseModel
from typer.testing import CliRunner

from fakes import FakeKarakeep, FakeLLM, FakeTrilium
from tohoku import cli
from tohoku.errors import ConfigError
from tohoku.models import Outcome
from tohoku.sources import ContentHint, Platform
from tohoku.pipeline import COMMON_STAGES, STAGE_ORDER
from tohoku.state import JobStatus, StateStore
from tohoku.trilium_layout import LayoutCache, init_layout, resolve_layout
from tohoku.lock import AlreadyRunning, single_instance
from tohoku.wiring import build_app, preflight


class SimpleModel(BaseModel):
    value: int = 1


def test_build_app_orders_stages(settings):
    app = build_app(settings)
    assert [stage.name for stage in app.stages] == list(COMMON_STAGES) + ["extract", "geocode", "resolve", "publish"]


def test_build_app_wires_one_cleaner_into_pipeline_and_service(settings):
    app = build_app(settings)
    cleaner = app.pipeline._cleaner
    assert cleaner is not None and app.service._cleaner is cleaner
    assert cleaner._retention.days == 30
    assert cleaner._jobs_dir == settings.data_dir / "jobs"


@pytest.fixture
def trilium():
    fake = FakeTrilium()
    fake.add_note("root", "Ideas de Japón", labels={"jrRoot": ""})
    return fake


def test_preflight_ok(settings, trilium):
    init_layout(trilium)
    preflight(settings, trilium, FakeLLM([]), LayoutCache(lambda: resolve_layout(trilium)))


def test_preflight_requires_multimodal_model(settings, trilium):
    init_layout(trilium)
    with pytest.raises(ConfigError, match="multimodal"):
        preflight(settings, trilium, FakeLLM([], images=False), LayoutCache(lambda: resolve_layout(trilium)))


def test_preflight_requires_layout(settings, trilium):
    with pytest.raises(ConfigError, match="init-trilium"):
        preflight(settings, trilium, FakeLLM([]), LayoutCache(lambda: resolve_layout(trilium)))


def test_preflight_requires_existing_cookies(settings, trilium, tmp_path):
    init_layout(trilium)
    s = settings.model_copy(update={"instagram_cookies_file": tmp_path / "nope.txt"})
    with pytest.raises(ConfigError, match="cookies"):
        preflight(s, trilium, FakeLLM([]), LayoutCache(lambda: resolve_layout(trilium)))


@pytest.fixture
def fake_app(monkeypatch, tmp_path, settings):
    app = SimpleNamespace(settings=settings, state=StateStore(tmp_path / "state.db"), karakeep=FakeKarakeep(),
                          destinations=SimpleNamespace(destinos={"japon": object()}))
    monkeypatch.setattr(cli, "_load", lambda: app)
    return app


def test_cli_help_lists_commands():
    result = CliRunner().invoke(cli.app, ["--help"])
    assert result.exit_code == 0
    for command in ("run", "run-once", "init-trilium", "status", "reprocess"):
        assert command in result.output


def test_cli_status(fake_app):
    result = CliRunner().invoke(cli.app, ["status"])
    assert result.exit_code == 0 and "Consumo de hoy" in result.output


def test_cli_reprocess_rejects_invalid_stage(fake_app):
    result = CliRunner().invoke(cli.app, ["reprocess", "b1", "--from", "transcribe"])
    assert result.exit_code == 1 and "etapa no válida" in result.output


def test_cli_reprocess_unknown_destino(fake_app):
    result = CliRunner().invoke(cli.app, ["reprocess", "b1", "--destino", "nz"])
    assert result.exit_code == 1 and "nz" in result.output


def _info(model, modalities=("text", "image"), params=("response_format",)):
    return {"id": model, "architecture": {"input_modalities": list(modalities)}, "supported_parameters": list(params)}


def test_preflight_requires_existing_text_model(settings, trilium):
    """Final review 4: un modelo mal escrito pausa el servicio en vez de llenar la cola de jr:error."""
    init_layout(trilium)
    llm = FakeLLM([], models={"vision/model": _info("vision/model")})
    with pytest.raises(ConfigError, match="OPENROUTER_TEXT_MODEL=text/model no existe"):
        preflight(settings, trilium, llm, LayoutCache(lambda: resolve_layout(trilium)))


def test_preflight_requires_existing_vision_model(settings, trilium):
    init_layout(trilium)
    llm = FakeLLM([], models={"text/model": _info("text/model")})
    with pytest.raises(ConfigError, match="OPENROUTER_MODEL=vision/model no existe"):
        preflight(settings, trilium, llm, LayoutCache(lambda: resolve_layout(trilium)))


@pytest.mark.parametrize("bad", ["vision/model", "text/model"])
def test_preflight_requires_structured_outputs(settings, trilium, bad):
    init_layout(trilium)
    models = {m: _info(m, params=("structured_outputs",) if m != bad else ("temperature",)) for m in ("vision/model", "text/model")}
    with pytest.raises(ConfigError, match=f"{bad}.*salida JSON estructurada"):
        preflight(settings, trilium, FakeLLM([], models=models), LayoutCache(lambda: resolve_layout(trilium)))


def test_preflight_ok_with_real_like_model_list(settings, trilium):
    init_layout(trilium)
    models = {"vision/model": _info("vision/model"), "text/model": _info("text/model", modalities=("text",), params=("structured_outputs",))}
    preflight(settings, trilium, FakeLLM([], models=models), LayoutCache(lambda: resolve_layout(trilium)))


def test_cli_reprocess_several_ids(fake_app):
    for bid in ("b1", "b2"):
        fake_app.state.add_job(bid, f"https://youtu.be/{bid}", Platform.YOUTUBE, ContentHint.VIDEO)
        fake_app.state.finish(bid, Outcome.ERROR, "x")

    result = CliRunner().invoke(cli.app, ["reprocess", "b1", "b2", "--from", "extract"])

    assert result.exit_code == 0, result.output
    assert all(fake_app.state.get_job(b).status == JobStatus.PENDING for b in ("b1", "b2"))
    assert "b1" in result.output and "b2" in result.output


def test_cli_reprocess_all_errors(fake_app):
    for i in range(12):
        bid = f"e{i}"
        fake_app.state.add_job(bid, f"https://youtu.be/{bid}", Platform.YOUTUBE, ContentHint.VIDEO)
        fake_app.state.save_stage(bid, "fetch", SimpleModel())
        fake_app.state.finish(bid, Outcome.ERROR, "x")
    fake_app.state.add_job("ok", "https://youtu.be/ok", Platform.YOUTUBE, ContentHint.VIDEO)
    fake_app.state.finish("ok", Outcome.PROCESADO)

    result = CliRunner().invoke(cli.app, ["reprocess", "--all-errors"])

    assert result.exit_code == 0, result.output
    assert all(fake_app.state.get_job(f"e{i}").status == JobStatus.PENDING for i in range(12))
    assert fake_app.state.load_stage("e0", "fetch", SimpleModel) is None  # --from fetch por defecto
    assert fake_app.state.get_job("ok").status == JobStatus.DONE
    assert "12" in result.output


def test_cli_reprocess_requires_ids_or_all_errors(fake_app):
    result = CliRunner().invoke(cli.app, ["reprocess"])
    assert result.exit_code == 1


def test_state_error_job_ids(tmp_path):
    state = StateStore(tmp_path / "s.db")
    for bid, outcome in (("a", Outcome.ERROR), ("b", Outcome.PROCESADO), ("c", Outcome.ERROR)):
        state.add_job(bid, f"u{bid}", Platform.YOUTUBE, ContentHint.VIDEO)
        state.finish(bid, outcome)
    assert sorted(state.error_job_ids()) == ["a", "c"]


def test_single_instance_lock(tmp_path):
    """Final review minor b: un solo proceso `run`/`run-once` a la vez por DATA_DIR."""
    with single_instance(tmp_path / "data"):
        with pytest.raises(AlreadyRunning):
            with single_instance(tmp_path / "data"):
                pass
    with single_instance(tmp_path / "data"):  # liberado al salir
        pass
    assert (tmp_path / "data" / "tohoku.lock").exists()


def test_cli_run_once_exits_3_when_another_instance_runs(fake_app):
    ticks = []
    fake_app.service = SimpleNamespace(tick=lambda: ticks.append(1))

    with single_instance(fake_app.settings.data_dir):
        result = CliRunner().invoke(cli.app, ["run-once"])
    assert result.exit_code == 3 and "Ya hay otra instancia" in result.output
    assert ticks == []

    result = CliRunner().invoke(cli.app, ["run-once"])
    assert result.exit_code == 0 and ticks == [1]


def test_cli_run_exits_3_when_another_instance_runs(fake_app):
    fake_app.service = SimpleNamespace(run_forever=lambda: pytest.fail("no debería arrancar"))
    with single_instance(fake_app.settings.data_dir):
        result = CliRunner().invoke(cli.app, ["run"])
    assert result.exit_code == 3


def test_build_app_uses_the_destination_from_config(settings):
    app = build_app(settings)
    assert app.destination.nombre == "japon" and app.destination.raiz == "jrRoot"
    assert "Japón" in next(s for s in app.stages if s.name == "extract").system_prompt


def _several_destinations(settings, tmp_path, shared_list=False):
    """La fixture de destinos más `nz` (con `destino_por_defecto: japon`); con `shared_list`, L1 lleva los dos."""
    text = (Path(__file__).parents[1] / "fixtures" / "destinos.yaml").read_text(encoding="utf-8")
    text = text.replace("../../config", str(Path(__file__).parents[2] / "config"))
    text += "  nz:\n    flujo: viaje\n    raiz: jrRootNZ\n    descripcion: NZ\n    prompt: " + str(Path(__file__).parents[2] / "config/prompts/japon.md") + "\n    pais: NZ\n    nombres_pais: [new zealand]\n    latitud: [-48.0, -34.0]\n    longitud: [166.0, 179.0]\n    categorias_lugar: [otro]\n    categorias_cosa: {otros: Otros}\n"
    text += "destino_por_defecto: japon\n"
    if shared_list:
        text = text.replace("L1: [japon]", "L1: [japon, nz]")
    path = tmp_path / "destinos.yaml"
    path.write_text(text, encoding="utf-8")
    return settings.model_copy(update={"destinos_file": path})


def test_build_app_accepts_several_destinations(settings, tmp_path):
    app = build_app(_several_destinations(settings, tmp_path))
    assert set(app.runtimes) == {"japon", "nz"}
    assert app.destination.nombre == "japon"
    assert [stage.name for stage in app.stages] == list(COMMON_STAGES) + ["extract", "geocode", "resolve", "publish"]


def test_build_app_single_destination_needs_no_classifier(settings):
    app = build_app(settings)
    assert set(app.runtimes) == {"japon"}
    assert app.classifier is None


def test_build_app_builds_the_classifier_when_a_list_has_several_destinations(settings, tmp_path):
    app = build_app(_several_destinations(settings, tmp_path, shared_list=True))
    assert app.classifier is not None


class _Layout:
    def __init__(self):
        self.refreshed = 0

    def refresh(self):
        self.refreshed += 1


def test_preflight_refreshes_every_layout(settings, trilium):
    layouts = [_Layout(), _Layout()]
    preflight(settings, trilium, FakeLLM([]), *layouts)
    assert [layout.refreshed for layout in layouts] == [1, 1]


def test_preflight_checks_the_classifier_model(settings, trilium):
    models = {m: _info(m) for m in ("vision/model", "text/model")}
    with pytest.raises(ConfigError, match="clasificador.modelo=clf/model no existe"):
        preflight(settings, trilium, FakeLLM([], models=models), _Layout(), classifier_model="clf/model")


def test_preflight_classifier_json_schema_needs_structured_outputs(settings, trilium):
    models = {m: _info(m) for m in ("vision/model", "text/model")} | {"clf/model": _info("clf/model", params=("temperature",))}
    with pytest.raises(ConfigError, match="clasificador.modelo=clf/model.*salida JSON estructurada"):
        preflight(settings, trilium, FakeLLM([], models=models), _Layout(), classifier_model="clf/model")
    preflight(settings, trilium, FakeLLM([], models=models), _Layout(), classifier_model="clf/model", classifier_mode="etiqueta")


def test_cli_init_trilium_requires_destino_with_several(monkeypatch, settings, tmp_path):
    app = build_app(_several_destinations(settings, tmp_path))
    monkeypatch.setattr(cli, "_load", lambda: app)
    result = CliRunner().invoke(cli.app, ["init-trilium"])
    assert result.exit_code == 2
    assert "indica --destino" in result.output and "nz" in result.output


def test_cli_eval_rejects_unknown_destination(monkeypatch, settings):
    app = build_app(settings)
    monkeypatch.setattr(cli, "_load", lambda: app)
    result = CliRunner().invoke(cli.app, ["eval", "--destino", "nz"])
    assert result.exit_code == 2
    assert "nz" in result.output


def test_cli_eval_rejects_non_viaje_destination(monkeypatch, settings):
    from dataclasses import replace
    from types import SimpleNamespace

    app = build_app(settings)
    recetas = replace(app.destination, nombre="recetas", flujo="receta")
    fake = SimpleNamespace(settings=app.settings, destination=app.destination, destinations=SimpleNamespace(destinos={"recetas": recetas}))
    monkeypatch.setattr(cli, "_load", lambda: fake)
    result = CliRunner().invoke(cli.app, ["eval", "--destino", "recetas"])
    assert result.exit_code == 2
    assert "eval solo admite destinos de flujo viaje" in result.output


def test_cli_reprocess_accepts_classify(fake_app):
    fake_app.state.add_job("b1", "https://youtu.be/b1", Platform.YOUTUBE, ContentHint.VIDEO)
    for stage in ("transcribe", "classify", "extract"):
        fake_app.state.save_stage("b1", stage, SimpleModel())
    result = CliRunner().invoke(cli.app, ["reprocess", "b1", "--from", "classify"])
    assert result.exit_code == 0, result.output
    assert fake_app.state.load_stage("b1", "transcribe", SimpleModel) is not None
    assert fake_app.state.load_stage("b1", "classify", SimpleModel) is None
    assert fake_app.state.load_stage("b1", "extract", SimpleModel) is None


def test_cli_init_trilium_uses_the_configured_destination(monkeypatch, settings):
    trilium = FakeTrilium()
    trilium.add_note("root", "Ideas de Japón", labels={"jrRoot": ""})
    app = build_app(settings)
    monkeypatch.setattr(cli, "_load", lambda: SimpleNamespace(**{**app.__dict__, "trilium": trilium}))

    result = CliRunner().invoke(cli.app, ["init-trilium"])

    assert result.exit_code == 0, result.output
    assert "Estructura lista" in result.output
    assert trilium.search("#jrMapa")


def test_cli_init_trilium_rejects_unknown_destination(monkeypatch, settings):
    app = build_app(settings)
    monkeypatch.setattr(cli, "_load", lambda: app)
    result = CliRunner().invoke(cli.app, ["init-trilium", "--destino", "nz"])
    assert result.exit_code == 2
    assert "nz" in result.output


def test_cli_import_uses_the_only_configured_list(monkeypatch, settings, tmp_path):
    app = build_app(settings)
    seen = {}
    monkeypatch.setattr(cli, "_load", lambda: app)
    monkeypatch.setattr(cli, "parse_export", lambda path: [])
    monkeypatch.setattr(cli, "import_items", lambda items, karakeep, list_id, dry_run, limit: seen.setdefault("list", list_id) and None)
    monkeypatch.setattr(cli, "format_import_report", lambda report, dry_run: "ok")

    result = CliRunner().invoke(cli.app, ["import-instagram", str(tmp_path / "x.json"), "--dry-run"])

    assert result.exit_code == 0, result.output
    assert seen["list"] == "L1"


def test_build_app_builds_the_classifier_when_lists_point_to_different_destinations(settings, tmp_path):
    """L1: [japon] y L2: [nz]: un bookmark en las dos tiene dos candidatos (I1)."""
    split = _several_destinations(settings, tmp_path)
    path = split.destinos_file
    path.write_text(path.read_text(encoding="utf-8").replace("L1: [japon]", "L1: [japon]\n  L2: [nz]"), encoding="utf-8")
    app = build_app(split)
    assert app.destinations.listas == {"L1": ["japon"], "L2": ["nz"]}
    assert app.classifier is not None


def test_build_app_builds_a_vision_classifier_with_the_multimodal_model(settings, tmp_path):
    """Las imágenes van a OPENROUTER_MODEL (multimodal comprobado en preflight), no al modelo de texto (I3)."""
    app = build_app(_several_destinations(settings, tmp_path, shared_list=True))
    classify = next(s for s in app.stages if s.name == "classify")
    assert app.classifier._model == "text/model"
    assert app.vision_classifier is not None and app.vision_classifier._model == "vision/model"
    assert classify._vision_classifier is app.vision_classifier


def test_build_app_single_destination_has_no_vision_classifier(settings):
    assert build_app(settings).vision_classifier is None


def test_build_app_applies_the_configured_generic_words(settings):
    from tohoku.text import normalize_name

    assert normalize_name("Verano en Japón") == "verano en japon"
    build_app(settings)  # la fixture de destinos declara palabras_genericas: [japan, japon]
    assert normalize_name("Verano en Japón") == "verano en"
