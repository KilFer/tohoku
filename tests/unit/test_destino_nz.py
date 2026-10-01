"""Nueva Zelanda es solo configuración: YAML + prompt, sin tocar `src/` (spec multi-destino, criterio de éxito 1)."""
from datetime import timedelta
from pathlib import Path

from builders import make_ctx, make_extraction, make_fetch, make_geo, make_lugar
from fakes import FakeKarakeep, FakeLLM, FakeTrilium
from tohoku.clients.karakeep import Bookmark
from tohoku.clients.places import PlacesClient
from tohoku.config import Thresholds
from tohoku.flows.base import FlowDeps
from tohoku.flows.registry import FLOWS
from tohoku.geo import in_country
from tohoku.ingest import ingest
from tohoku.models import ExtractResult, Transcript
from tohoku.quota import DailyQuota
from tohoku.stages.geocode import GeocodeStage
from tohoku.state import StateStore
from tohoku.wiring import build_app

REPO = Path(__file__).parents[2]
SKY_TOWER = make_geo("NZ1", "Sky Tower", "Victoria St W, Auckland CBD, Auckland 1010, Nueva Zelanda", lat=-36.8485, lng=174.7622,
                     country_code="NZ", area="Auckland")
TOKYO_TOWER = make_geo("JP1", "Tokyo Tower", "4 Chome-2-8 Shibakoen, Minato City, Tokyo", lat=35.6586, lng=139.7454,
                       country_code="JP", area="Tokio")


def _app(settings):
    return build_app(settings.model_copy(update={"destinos_file": REPO / "tests/fixtures/destinos_tres.yaml"}))


def test_nz_parameters_come_from_the_yaml(settings):
    config = _app(settings).destinations
    nz = config.destinos["nueva_zelanda"]
    assert (nz.flujo, nz.raiz) == ("viaje", "jrRootNZ")
    assert nz.params.pais == "NZ"
    assert nz.params.latitud == (-47.5, -34.0) and nz.params.longitud == (166.0, 179.0)
    assert "aotearoa" in nz.params.nombres_pais
    assert nz.params.categorias_cosa == {"souvenirs": "Souvenirs", "comida": "Comida", "otros": "Otros"}
    assert "naturaleza" in nz.params.categorias_lugar
    assert nz.params.alias_ciudad["auckland"] == ["tamaki makaurau"]
    assert set(config.destinos) == {"japon", "recetas", "nueva_zelanda"}


def test_nz_prompt_renders_its_categories(settings):
    app = _app(settings)
    prompt = next(s for s in app.runtimes["nueva_zelanda"].stages if s.name == "extract").system_prompt
    assert "Nueva Zelanda" in prompt
    assert "{{" not in prompt
    assert "naturaleza, ruta, mirador, pueblo" in prompt
    assert "souvenirs | comida | otros" in prompt
    assert "Japón" not in prompt


def test_in_country_accepts_nz_and_rejects_japan(settings):
    p = _app(settings).destinations.destinos["nueva_zelanda"].params
    assert in_country(SKY_TOWER, "NZ", p.nombres_pais, p.latitud, p.longitud)
    assert not in_country(TOKYO_TOWER, "NZ", p.nombres_pais, p.latitud, p.longitud)


def test_places_cache_key_for_nz_is_prefixed(settings, tmp_path):
    class Places:
        def __init__(self):
            self.regions = []

        def search(self, query, region="JP"):
            self.regions.append(region)
            return [SKY_TOWER]

    state = StateStore(tmp_path / "state.db")
    app = _app(settings)
    params = app.destinations.destinos["nueva_zelanda"].params
    lugar = make_lugar(nombre="Sky Tower", consulta_busqueda="Sky Tower Auckland", ciudad="Auckland")
    ctx = make_ctx(tmp_path, extract=ExtractResult(extraction=make_extraction(0.95, lugares=[lugar])))
    places = Places()
    result = GeocodeStage(places, DailyQuota(state, "places_calls", 10), Thresholds(), cache=state, params=params).run(ctx)

    assert result.outcomes[0].match.place_id == "NZ1"
    assert places.regions == ["NZ"]
    assert state.get_places_cache("NZ|Sky Tower Auckland", timedelta(days=1)) is not None
    assert state.get_places_cache("Sky Tower Auckland", timedelta(days=1)) is None


def test_init_trilium_for_nz_creates_the_structure_under_its_root(settings, tmp_path):
    nz = _app(settings).destinations.destinos["nueva_zelanda"]
    trilium = FakeTrilium()
    trilium.add_note("root", "Viaje a Nueva Zelanda", labels={"jrRootNZ": ""})
    state = StateStore(tmp_path / "flow.db")
    deps = FlowDeps(settings=settings, state=state, trilium=trilium, llm=FakeLLM([]), places=PlacesClient("k"),
                    llm_budget=DailyQuota(state, "openrouter_usd", 1), places_quota=DailyQuota(state, "places_calls", 1))

    summary = FLOWS["viaje"].init_trilium(trilium, nz)

    layout = FLOWS["viaje"].build(nz, deps).refresh()
    assert "Mapa=" in summary
    assert set(layout.categorias) == {"souvenirs", "comida", "otros"}


def test_nz_job_with_a_single_candidate_skips_the_classifier(settings, tmp_path):
    app = _app(settings)
    state = StateStore(tmp_path / "ingest.db")
    karakeep = FakeKarakeep([Bookmark(id="n1", url="https://www.instagram.com/reel/NZNZ/")])
    karakeep.lists = {"L3": ["n1"]}
    ingest(karakeep, state, "L3", app.destinations.candidates_for("L3"))
    job = state.get_job("n1")
    assert job.candidates == ["nueva_zelanda"]
    classify = next(s for s in app.stages if s.name == "classify")
    ctx = make_ctx(tmp_path, job=job, fetch=make_fetch(), transcribe=Transcript(text="", origin="whisper"))
    assert classify.run(ctx).destino == "nueva_zelanda"
