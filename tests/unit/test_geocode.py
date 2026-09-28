import pytest

from builders import make_ctx, make_extraction, make_geo, make_lugar
from japan_reader.config import Thresholds
from japan_reader.errors import QuotaExceeded
from japan_reader.models import ExtractResult
from japan_reader.quota import DailyQuota
from japan_reader.stages.geocode import GeocodeStage
from japan_reader.state import StateStore

SHIBUYA = make_geo("P1", "Ichiran Shibuya", "Jinnan, Shibuya, Tokio 150-0041, Japón")
OSAKA = make_geo("P2", "Ichiran Dotonbori", "Chuo Ward, Osaka, 542-0084, Japón", lat=34.66, lng=135.50)
OTHER_TOKYO = make_geo("P3", "Ramen Nagi", "Shinjuku, Tokio, Japón")
PARIS = make_geo("P4", "Ichiran Paris", "Rue X, 75001 Paris, Francia", lat=48.85, lng=2.35)


class FakePlaces:
    def __init__(self, answers: dict[str, list]):
        self.answers = answers
        self.queries: list[str] = []

    def search(self, query):
        self.queries.append(query)
        return self.answers.get(query, [])


@pytest.fixture
def state(tmp_path):
    return StateStore(tmp_path / "state.db")


def _run(tmp_path, state, places, lugares, confianza=0.95, limit=150):
    ctx = make_ctx(tmp_path, extract=ExtractResult(extraction=make_extraction(confianza, lugares=lugares)))
    return GeocodeStage(places, DailyQuota(state, "places_calls", limit), Thresholds()).run(ctx)


def test_direct_match(tmp_path, state):
    places = FakePlaces({"Ichiran Shibuya Tokyo": [SHIBUYA]})
    result = _run(tmp_path, state, places, [make_lugar()])
    assert result.outcomes[0].match.place_id == "P1"
    assert result.outcomes[0].review_reason is None
    assert state.get_counter("places_calls") == 1


def test_filters_by_country_and_city(tmp_path, state):
    places = FakePlaces({"Ichiran Shibuya Tokyo": [PARIS, OSAKA, SHIBUYA]})
    result = _run(tmp_path, state, places, [make_lugar()])
    assert result.outcomes[0].match.place_id == "P1"


def test_city_aliases(tmp_path, state):
    kyoto = make_geo("K1", "Fushimi Inari Taisha", "68 Fukakusa Yabunouchicho, Fushimi Ward, Kyoto, 612-0882, Japan")
    places = FakePlaces({"Fushimi Inari Kyoto": [kyoto]})
    lugar = make_lugar("Fushimi Inari", consulta_busqueda="Fushimi Inari Kyoto", ciudad="Kioto")
    assert _run(tmp_path, state, places, [lugar]).outcomes[0].match.place_id == "K1"


def test_falls_back_to_local_name(tmp_path, state):
    places = FakePlaces({"一蘭 渋谷店": [SHIBUYA]})
    lugar = make_lugar(nombre_local="一蘭 渋谷店")
    result = _run(tmp_path, state, places, [lugar])
    assert places.queries == ["Ichiran Shibuya Tokyo", "一蘭 渋谷店"]
    assert result.outcomes[0].match.place_id == "P1"
    assert state.get_counter("places_calls") == 2


def test_ambiguous_when_several_unrelated_names(tmp_path, state):
    places = FakePlaces({"Tonkotsu oculto Tokyo": [OTHER_TOKYO, SHIBUYA]})
    lugar = make_lugar("Tonkotsu oculto", consulta_busqueda="Tonkotsu oculto Tokyo")
    outcome = _run(tmp_path, state, places, [lugar]).outcomes[0]
    assert outcome.match.place_id == "P3"
    assert outcome.review_reason == "geocodificacion-ambigua"


def test_japan_but_other_city_is_ambiguous(tmp_path, state):
    places = FakePlaces({"Ichiran Shibuya Tokyo": [OSAKA]})
    outcome = _run(tmp_path, state, places, [make_lugar()]).outcomes[0]
    assert outcome.match.place_id == "P2"
    assert outcome.review_reason == "geocodificacion-ambigua"


def test_nothing_in_japan_fails(tmp_path, state):
    places = FakePlaces({"Ichiran Shibuya Tokyo": [PARIS]})
    outcome = _run(tmp_path, state, places, [make_lugar()]).outcomes[0]
    assert outcome.match is None
    assert outcome.review_reason == "geocodificacion-fallida"


def test_not_japan_skips_geocoding(tmp_path, state):
    places = FakePlaces({})
    assert _run(tmp_path, state, places, [make_lugar()], confianza=0.1).outcomes == []
    assert places.queries == []


def test_quota_exceeded(tmp_path, state):
    state.add_counter("places_calls", 150)
    with pytest.raises(QuotaExceeded):
        _run(tmp_path, state, FakePlaces({}), [make_lugar()])
