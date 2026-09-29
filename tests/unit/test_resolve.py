import pytest

from builders import make_ctx, make_cosa, make_extraction, make_geo, make_lugar
from fakes import FakeTrilium
from japan_reader.config import Thresholds
from japan_reader.models import ExtractResult, GeocodeResult, GeoOutcome, ItemKind
from japan_reader.stages.resolve import ResolveStage
from japan_reader.trilium_layout import init_layout


@pytest.fixture
def env():
    trilium = FakeTrilium()
    trilium.add_note("root", "Ideas de Japón", labels={"jrRoot": ""})
    return trilium, init_layout(trilium)


def _run(tmp_path, env, extraction, outcomes=()):
    trilium, layout = env
    ctx = make_ctx(tmp_path, extract=ExtractResult(extraction=extraction), geocode=GeocodeResult(outcomes=list(outcomes)))
    return ResolveStage(trilium, lambda: layout, Thresholds()).run(ctx).items


def test_failed_extraction_becomes_review_item(tmp_path, env):
    trilium, layout = env
    ctx = make_ctx(tmp_path, extract=ExtractResult(extraction=None, error="x"))
    items = ResolveStage(trilium, lambda: layout, Thresholds()).run(ctx).items
    assert [(i.key, i.kind, i.review_reasons) for i in items] == [("fallo", ItemKind.FALLO, ["extraccion-fallida"])]


def test_not_japan_has_no_items(tmp_path, env):
    assert _run(tmp_path, env, make_extraction(0.1, lugares=[make_lugar()])) == []


def test_new_and_existing_places(tmp_path, env):
    trilium, layout = env
    existing = trilium.add_note(layout.mapa, "Ichiran", labels={"jrTipo": "lugar", "googlePlaceId": "P1"})
    extraction = make_extraction(lugares=[make_lugar(), make_lugar("Nuevo sitio")])
    outcomes = [GeoOutcome(lugar_index=0, match=make_geo("P1")), GeoOutcome(lugar_index=1, match=make_geo("P2", "Nuevo sitio"))]

    items = _run(tmp_path, env, extraction, outcomes)

    assert (items[0].action, items[0].existing_note_id) == ("merge", existing)
    assert (items[1].action, items[1].existing_note_id) == ("create", None)
    assert items[0].review_reasons == [] and items[1].review_reasons == []


def test_same_place_twice_in_one_source_is_aliased(tmp_path, env):
    """Review Focus 2."""
    extraction = make_extraction(lugares=[make_lugar("Fushimi Inari"), make_lugar("伏見稲荷大社")])
    outcomes = [GeoOutcome(lugar_index=0, match=make_geo("F1")), GeoOutcome(lugar_index=1, match=make_geo("F1"))]

    items = _run(tmp_path, env, extraction, outcomes)

    assert [(i.key, i.action, i.alias_of) for i in items] == [("lugar:0", "create", None), ("lugar:1", "alias", "lugar:0")]


def test_ungeocoded_place_merges_with_same_name_note(tmp_path, env):
    trilium, layout = env
    existing = trilium.add_note(layout.mapa, "Línea Yamanote", labels={"jrTipo": "lugar", "jrNombreNorm": "linea yamanote"})
    extraction = make_extraction(lugares=[make_lugar("Línea Yamanote"), make_lugar("Linea yamanote"), make_lugar("Otro sitio")])
    outcomes = [GeoOutcome(lugar_index=i, review_reason="geocodificacion-fallida") for i in range(3)]

    items = _run(tmp_path, env, extraction, outcomes)

    assert (items[0].action, items[0].existing_note_id) == ("merge", existing)
    assert (items[1].action, items[1].alias_of) == ("alias", "lugar:0")
    assert (items[2].action, items[2].existing_note_id) == ("create", None)
    assert items[0].review_reasons == ["geocodificacion-fallida"]


def test_review_reasons(tmp_path, env):
    extraction = make_extraction(0.5, lugares=[make_lugar(confianza=0.5), make_lugar("Otro")])
    outcomes = [GeoOutcome(lugar_index=0, review_reason="geocodificacion-fallida"), GeoOutcome(lugar_index=1, match=make_geo("P9"), review_reason="geocodificacion-ambigua")]

    items = _run(tmp_path, env, extraction, outcomes)

    assert items[0].review_reasons == ["clasificacion-incierta", "baja-confianza", "geocodificacion-fallida"]
    assert items[1].review_reasons == ["clasificacion-incierta", "geocodificacion-ambigua"]
    assert items[0].action == "create"


def test_cosas_merge_duplicate_and_alias(tmp_path, env):
    trilium, layout = env
    existing = trilium.add_note(layout.categorias["cadenas"], "CoCo", labels={"jrTipo": "cosa", "jrNombreNorm": "coco ichibanya"})
    extraction = make_extraction(cosas=[
        make_cosa("CoCo Ichibanya"),
        make_cosa("CoCo Ichiban-ya"),
        make_cosa("Kit Kat matcha", categoria="souvenirs"),
        make_cosa("kit-kat MATCHA", categoria="souvenirs"),
    ])

    items = _run(tmp_path, env, extraction)

    assert (items[0].action, items[0].existing_note_id) == ("merge", existing)
    assert items[1].action == "create" and items[1].review_reasons == ["posible-duplicado"]
    assert items[2].action == "create" and items[2].review_reasons == []
    assert (items[3].action, items[3].alias_of) == ("alias", "cosa:2")


def test_otros_and_synthetic_summary(tmp_path, env):
    items = _run(tmp_path, env, make_extraction(otros=[{"titulo": "Propinas", "contenido": "No se dan"}]))
    assert [(i.key, i.kind, i.index) for i in items] == [("otro:0", ItemKind.OTRO, 0)]

    items = _run(tmp_path, env, make_extraction())
    assert [(i.key, i.kind, i.index) for i in items] == [("otro:resumen", ItemKind.OTRO, -1)]
