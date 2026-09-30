import pytest

from builders import make_ctx, make_cosa, make_extraction, make_geo, make_lugar
from fakes import FakeTrilium
from tohoku.config import Thresholds
from tohoku.models import Classification, ExtractResult, GeocodeResult, GeoOutcome, ItemKind
from tohoku.stages.resolve import ResolveStage
from tohoku.trilium_layout import init_layout


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


def test_same_name_nearby_note_with_other_place_id_is_merged(tmp_path, env):
    """Google tiene dos fichas para el mismo sitio (caso real: Omoide Yokocho, a 45 m)."""
    trilium, layout = env
    near = trilium.add_note(layout.mapa, "Omoide Yokocho", labels={"jrTipo": "lugar", "jrNombreNorm": "omoide yokocho", "googlePlaceId": "OLD", "geolocation": "35.6930,139.6995"})
    trilium.add_note(layout.mapa, "Omoide Yokocho", labels={"jrTipo": "lugar", "jrNombreNorm": "omoide yokocho", "googlePlaceId": "FAR", "geolocation": "34.6930,135.5000"})
    extraction = make_extraction(lugares=[make_lugar("Omoide Yokocho")])
    outcomes = [GeoOutcome(lugar_index=0, match=make_geo("NEW", "Omoide Yokochō", lat=35.6933, lng=139.6997))]

    items = _run(tmp_path, env, extraction, outcomes)

    assert (items[0].action, items[0].existing_note_id) == ("merge", near)


def test_same_name_far_away_is_a_different_place(tmp_path, env):
    trilium, layout = env
    trilium.add_note(layout.mapa, "Ichiran", labels={"jrTipo": "lugar", "jrNombreNorm": "ichiran", "googlePlaceId": "P1", "geolocation": "35.6614,139.7005"})
    extraction = make_extraction(lugares=[make_lugar("Ichiran")])
    outcomes = [GeoOutcome(lugar_index=0, match=make_geo("P2", "Ichiran", lat=34.6687, lng=135.5013))]

    items = _run(tmp_path, env, extraction, outcomes)

    assert (items[0].action, items[0].existing_note_id) == ("create", None)


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


def _run_classified(tmp_path, env, classification):
    trilium, layout = env
    results = {"classify": classification} if classification else {}
    ctx = make_ctx(
        tmp_path, extract=ExtractResult(extraction=make_extraction(lugares=[make_lugar()], cosas=[make_cosa()], otros=[{"titulo": "Dato", "contenido": "algo"}])),
        geocode=GeocodeResult(outcomes=[GeoOutcome(lugar_index=0, match=make_geo())]), **results,
    )
    return ResolveStage(trilium, lambda: layout, Thresholds()).run(ctx).items


def test_dudosa_classification_marks_every_item(tmp_path, env):
    items = _run_classified(tmp_path, env, Classification(destino="japon", dudosa=True))
    assert len(items) == 3
    assert all("clasificacion-dudosa" in i.review_reasons for i in items)


@pytest.mark.parametrize("classification", [Classification(destino="japon", dudosa=False), None])
def test_not_dudosa_or_missing_classification_adds_no_reason(tmp_path, env, classification):
    items = _run_classified(tmp_path, env, classification)
    assert all("clasificacion-dudosa" not in i.review_reasons for i in items)
