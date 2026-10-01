from pathlib import Path

import pytest

from fakes import FakeLLM, FakeTrilium
from tohoku.clients.places import PlacesClient
from tohoku.destinations import Destination
from tohoku.errors import ConfigError
from tohoku.flows.base import FlowDeps
from tohoku.flows.registry import FLOWS
from tohoku.flows.viaje.params import ViajeParams
from tohoku.pipeline import COMMON_STAGES, STAGE_ORDER
from tohoku.quota import DailyQuota
from tohoku.state import StateStore


def _dest(**params):
    return Destination(nombre="nz", flujo="viaje", raiz="jrRootNZ", descripcion="NZ", prompt="PROMPT NZ", params=ViajeParams(**params))


def _deps(settings, tmp_path, trilium):
    state = StateStore(tmp_path / "state.db")
    return FlowDeps(settings=settings, state=state, trilium=trilium, llm=FakeLLM([]), places=PlacesClient("k"),
                    llm_budget=DailyQuota(state, "openrouter_usd", 1), places_quota=DailyQuota(state, "places_calls", 1))


def test_viaje_is_registered():
    assert FLOWS["viaje"].params_model is ViajeParams


def test_build_gives_the_flow_stages_in_order(settings, tmp_path):
    runtime = FLOWS["viaje"].build(_dest(), _deps(settings, tmp_path, FakeTrilium()))
    assert [s.name for s in runtime.stages] == ["extract", "geocode", "resolve", "publish"]


def test_init_trilium_uses_the_destination_root_and_categories(settings, tmp_path):
    trilium = FakeTrilium()
    trilium.add_note("root", "Viaje a Nueva Zelanda", labels={"jrRootNZ": ""})
    dest = _dest(categorias_cosa={"artesania": "Artesanía", "comida": "Comida"})

    summary = FLOWS["viaje"].init_trilium(trilium, dest)

    runtime = FLOWS["viaje"].build(dest, _deps(settings, tmp_path, trilium))
    layout = runtime.refresh()
    assert set(layout.categorias) == {"artesania", "comida"}
    assert "Mapa=" in summary


def test_refresh_fails_until_init(settings, tmp_path):
    trilium = FakeTrilium()
    trilium.add_note("root", "Viaje a Nueva Zelanda", labels={"jrRootNZ": ""})
    runtime = FLOWS["viaje"].build(_dest(), _deps(settings, tmp_path, trilium))
    with pytest.raises(ConfigError, match="init-trilium"):
        runtime.refresh()


def test_extract_stage_gets_the_destination_prompt(settings, tmp_path):
    runtime = FLOWS["viaje"].build(_dest(), _deps(settings, tmp_path, FakeTrilium()))
    extract = next(s for s in runtime.stages if s.name == "extract")
    assert extract.system_prompt == "PROMPT NZ"


def test_extract_prompt_is_rendered_with_destination_categories(settings, tmp_path):
    dest = Destination(nombre="nz", flujo="viaje", raiz="jrRootNZ", descripcion="NZ",
                       prompt="Lugar: {{categorias_lugar}} · Cosa: {{categorias_cosa}}",
                       params=ViajeParams(categorias_lugar=["naturaleza", "otro"], categorias_cosa={"a": "A", "b": "B"}))
    extract = next(s for s in FLOWS["viaje"].build(dest, _deps(settings, tmp_path, FakeTrilium())).stages if s.name == "extract")
    assert extract.system_prompt == "Lugar: naturaleza, otro · Cosa: a | b"
