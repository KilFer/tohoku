import pytest

from builders import make_ctx, make_extraction, make_geo, make_lugar
from japan_reader.config import Thresholds
from japan_reader.errors import QuotaExceeded
from japan_reader.geo import name_score
from japan_reader.models import ExtractResult
from japan_reader.quota import DailyQuota
from japan_reader.stages.geocode import GeocodeStage
from japan_reader.state import StateStore

SHIBUYA = make_geo("P1", "Ichiran Shibuya", "Jinnan, Shibuya, Tokio 150-0041, Japón")
OSAKA = make_geo("P2", "Ichiran Dotonbori", "Chuo Ward, Osaka, 542-0084, Japón", lat=34.66, lng=135.50)
OTHER_TOKYO = make_geo("P3", "Ramen Nagi", "Shinjuku, Tokio, Japón")
PARIS = make_geo("P4", "Ichiran Paris", "Rue X, 75001 Paris, Francia", lat=48.85, lng=2.35)
# Formato real con regionCode=JP: sin país en la dirección, país y prefectura en postalAddress.
FUSHIMI_REAL = make_geo(
    "F1", "Fushimi Inari-taisha", "68 Fukakusa Yabunouchichō, Fushimi Ward, Kyoto, 612-0882", lat=34.97, lng=135.78,
    country_code="JP", area="Prefectura de Kioto 68 Fukakusa Yabunouchicho Fushimi-ku, Kioto",
)
SEOUL = make_geo("K9", "Myeongdong", "Jung-gu, Seúl", lat=37.56, lng=126.98, country_code="KR", area="Seúl")


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
    return GeocodeStage(places, DailyQuota(state, "places_calls", limit), Thresholds(), cache=state).run(ctx)


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


def test_real_address_without_country_is_accepted(tmp_path, state):
    places = FakePlaces({"Fushimi Inari Kyoto": [FUSHIMI_REAL]})
    lugar = make_lugar("Fushimi Inari", consulta_busqueda="Fushimi Inari Kyoto", ciudad="Kioto")
    outcome = _run(tmp_path, state, places, [lugar]).outcomes[0]
    assert outcome.match.place_id == "F1"
    assert outcome.review_reason is None


def test_country_code_outside_japan_is_rejected_even_inside_bbox(tmp_path, state):
    places = FakePlaces({"Myeongdong Tokyo": [SEOUL]})
    lugar = make_lugar("Myeongdong", consulta_busqueda="Myeongdong Tokyo")
    outcome = _run(tmp_path, state, places, [lugar]).outcomes[0]
    assert outcome.match is None
    assert outcome.review_reason == "geocodificacion-fallida"


# Caso real (Short "This Hidden Gem in Japan has CRAZY Ramen"): el local correcto sale en tercera posición.
JINSEI = make_geo("J1", "Ramen Jinsei JET", "7-chōme-12-2 Fukushima, Fukushima Ward, Osaka, 553-0003", lat=34.69, lng=135.49, country_code="JP", area="Osaka")
JINSEI_600 = make_geo("J2", "Ramen Jinsei JET 600", "1-chōme-3-2 Higashiobase, Higashinari Ward, Osaka, 537-0024", lat=34.67, lng=135.54, country_code="JP", area="Osaka")
MIKI_JET = make_geo("M1", "Miki Jet", "4-chōme-1-5 Nadaminamidōri, Nada Ward, Kobe, Hyogo 657-0841", lat=34.71, lng=135.22, country_code="JP", area="Hyogo Kobe")


def test_best_name_match_wins_over_first_result(tmp_path, state):
    places = FakePlaces({"Miki Jet ramen": [JINSEI, JINSEI_600, MIKI_JET]})
    lugar = make_lugar("Miki Jet", consulta_busqueda="Miki Jet ramen", ciudad=None)
    outcome = _run(tmp_path, state, places, [lugar]).outcomes[0]
    assert outcome.match.place_id == "M1"
    assert outcome.review_reason is None


def test_equally_good_name_matches_are_ambiguous(tmp_path, state):
    # Dos sucursales de verdad, a ~3 km: sigue siendo ambiguo.
    shinjuku = make_geo("P5", "Ichiran Shinjuku", "Shinjuku, Tokio", lat=35.69, lng=139.70, country_code="JP", area="Tokio")
    places = FakePlaces({"Ichiran Tokyo": [SHIBUYA, shinjuku]})
    lugar = make_lugar("Ichiran", consulta_busqueda="Ichiran Tokyo")
    outcome = _run(tmp_path, state, places, [lugar]).outcomes[0]
    assert outcome.match.place_id == "P1"
    assert outcome.review_reason == "geocodificacion-ambigua"


# Caso real: barrio sin postalAddress; el país y la ciudad vienen de addressComponents.
KABUKICHO = make_geo("A1", "Kabukichō", "Kabukichō, Shinjuku, Tokio 160-0021", lat=35.6955, lng=139.7031, country_code="JP", area="Kabukichō Shinjuku Tokio")
KYOTO_CITY = make_geo("A2", "Kioto", "Kioto, Prefectura de Kioto", lat=35.01, lng=135.77, country_code="JP", area="Kioto Prefectura de Kioto")


def test_areas_are_geocoded_like_any_place(tmp_path, state):
    places = FakePlaces({"Kabukicho Shinjuku Tokyo": [KABUKICHO], "Kyoto Japan": [KYOTO_CITY]})
    lugares = [
        make_lugar("Kabukicho", consulta_busqueda="Kabukicho Shinjuku Tokyo", ciudad="Tokio"),
        make_lugar("Kioto", consulta_busqueda="Kyoto Japan", ciudad="Kioto"),
    ]
    outcomes = _run(tmp_path, state, places, lugares).outcomes
    assert [(o.match.place_id, o.review_reason) for o in outcomes] == [("A1", None), ("A2", None)]


# Casos reales (tanda 4): empates entre resultados que son el mismo sitio.
DOTONBORI_SPOT = make_geo("D1", "Dōtonbori", "1 Chome Dotonbori, Chūō-ku, Osaka", lat=34.66868, lng=135.50128, country_code="JP", area="Prefectura de Osaka")
DOTONBORI_AREA = make_geo("D2", "Dotonbori", "Dotonbori, Chūō-ku, Osaka", lat=34.66890, lng=135.49950, country_code="JP", area="Prefectura de Osaka")


def test_tie_between_nearby_results_is_clear(tmp_path, state):
    places = FakePlaces({"Dotonbori Osaka": [DOTONBORI_SPOT, DOTONBORI_AREA]})
    lugar = make_lugar("Dotonbori", consulta_busqueda="Dotonbori Osaka", ciudad="Osaka")
    outcome = _run(tmp_path, state, places, [lugar]).outcomes[0]
    assert outcome.match.place_id == "D1"
    assert outcome.review_reason is None


def test_exact_name_in_japan_but_other_city_is_accepted(tmp_path, state):
    disneysea = make_geo("S1", "Tokyo DisneySea", "1-13 Maihama, Urayasu, Chiba", lat=35.6267, lng=139.8851, country_code="JP", area="Prefectura de Chiba Urayasu")
    places = FakePlaces({"Tokyo DisneySea": [disneysea]})
    lugar = make_lugar("Tokyo DisneySea", consulta_busqueda="Tokyo DisneySea", ciudad="Tokio")
    outcome = _run(tmp_path, state, places, [lugar]).outcomes[0]
    assert outcome.match.place_id == "S1"
    assert outcome.review_reason is None


def test_translated_generic_words_and_city_aliases_match(tmp_path, state):
    torre = make_geo("T1", "Torre de Kioto", "721-1 Higashishiokojicho, Kioto", lat=34.98755, lng=135.75945, country_code="JP", area="Prefectura de Kioto")
    building = make_geo("T2", "Kyoto Tower Building", "721-1 Higashishiokojicho, Kioto", lat=34.98770, lng=135.75960, country_code="JP", area="Prefectura de Kioto")
    hotel = make_geo("T3", "Kyoto Tower Hotel", "721-1 Higashishiokojicho, Kioto", lat=34.98760, lng=135.75950, country_code="JP", area="Prefectura de Kioto")
    places = FakePlaces({"Kyoto Tower Kyoto Station": [torre, building, hotel]})
    lugar = make_lugar("Kyoto Tower", consulta_busqueda="Kyoto Tower Kyoto Station", ciudad="Kioto")
    outcome = _run(tmp_path, state, places, [lugar]).outcomes[0]
    assert outcome.match.place_id == "T1"
    assert outcome.review_reason is None


@pytest.mark.parametrize(
    ("google", "extracted", "expected"),
    [
        ("Santuario Meiji", "Meiji Shrine", 2.0),
        ("Torre de Kioto", "Kyoto Tower", 2.0),
        ("Lago Shinji", "Lake Shinji", 2.0),
        ("Estación de Umeda", "Umeda Station", 2.0),
        ("Ichiran Shibuya", "Ichiran Shibuya", 2.0),
        ("Kyoto Tower Hotel", "Kyoto Tower", 1.0),
    ],
)
def test_name_score_translations(google, extracted, expected):
    assert name_score(make_geo(name=google), make_lugar(extracted)) == expected


def test_repeated_queries_use_the_cache(tmp_path, state):
    places = FakePlaces({"Ichiran Shibuya Tokyo": [SHIBUYA]})
    _run(tmp_path, state, places, [make_lugar()])

    outcome = _run(tmp_path, state, places, [make_lugar()]).outcomes[0]

    assert outcome.match.place_id == "P1"
    assert places.queries == ["Ichiran Shibuya Tokyo"]
    assert state.get_counter("places_calls") == 1


def test_empty_results_are_cached_too(tmp_path, state):
    places = FakePlaces({})
    lugar = make_lugar("Nada", consulta_busqueda="Nada Tokyo", nombre_local=None)
    _run(tmp_path, state, places, [lugar])
    _run(tmp_path, state, places, [lugar])
    assert places.queries == ["Nada Tokyo"]


def test_cache_hit_needs_no_quota(tmp_path, state):
    places = FakePlaces({"Ichiran Shibuya Tokyo": [SHIBUYA]})
    _run(tmp_path, state, places, [make_lugar()])
    state.add_counter("places_calls", 500)

    outcome = _run(tmp_path, state, places, [make_lugar()], limit=150).outcomes[0]

    assert outcome.match.place_id == "P1"
