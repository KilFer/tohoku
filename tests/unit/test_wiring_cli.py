from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from fakes import FakeKarakeep, FakeLLM, FakeTrilium
from japan_reader import cli
from japan_reader.errors import ConfigError
from japan_reader.pipeline import STAGE_ORDER
from japan_reader.state import StateStore
from japan_reader.trilium_layout import LayoutCache, init_layout, resolve_layout
from japan_reader.wiring import build_app, preflight


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
