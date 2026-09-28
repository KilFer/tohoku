from types import SimpleNamespace

import pytest
from pydantic import BaseModel
from typer.testing import CliRunner

from fakes import FakeKarakeep, FakeLLM, FakeTrilium
from japan_reader import cli
from japan_reader.errors import ConfigError
from japan_reader.models import Outcome
from japan_reader.sources import ContentHint, Platform
from japan_reader.pipeline import STAGE_ORDER
from japan_reader.state import JobStatus, StateStore
from japan_reader.trilium_layout import LayoutCache, init_layout, resolve_layout
from japan_reader.lock import AlreadyRunning, single_instance
from japan_reader.wiring import build_app, preflight


class SimpleModel(BaseModel):
    value: int = 1


def test_build_app_orders_stages(settings):
    app = build_app(settings)
    assert [stage.name for stage in app.stages] == list(STAGE_ORDER)


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
    app = SimpleNamespace(settings=settings, state=StateStore(tmp_path / "state.db"), karakeep=FakeKarakeep())
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
    assert (tmp_path / "data" / "japan-reader.lock").exists()


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
