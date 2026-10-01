import pytest

from fakes import FakeTrilium
from tohoku.errors import ConfigError
from tohoku.trilium_layout import CATEGORIES, GEO_MAP_TEMPLATE, LayoutCache, init_layout, resolve_layout


@pytest.fixture
def trilium():
    fake = FakeTrilium()
    viajes = fake.add_note("root", "Viajes")
    fake.add_note(viajes, "Ideas de Japón", labels={"jrRoot": ""})
    return fake


def test_init_creates_structure(trilium):
    layout = init_layout(trilium)

    mapa = trilium.get_note(layout.mapa)
    assert mapa.type == "book"
    assert mapa.relations("template") == [GEO_MAP_TEMPLATE]
    assert trilium.get_note(layout.comprar).parent_note_ids == [layout.root]
    assert set(layout.categorias) == set(CATEGORIES)
    assert all(trilium.get_note(nid).parent_note_ids == [layout.comprar] for nid in layout.categorias.values())
    lugar = trilium.get_note(layout.plantilla_lugar)
    assert lugar.title == "Lugar" and lugar.label("template") == ""
    assert lugar.label("label:visitado") == "promoted,single,boolean"
    assert trilium.get_note(layout.plantilla_cosa).title == "Cosa"


def test_init_is_idempotent(trilium):
    first = init_layout(trilium)
    count = len(trilium.notes)
    second = init_layout(trilium)
    assert first == second
    assert len(trilium.notes) == count


def test_resolve_requires_init(trilium):
    with pytest.raises(ConfigError, match="init-trilium"):
        resolve_layout(trilium)


def test_missing_root(trilium):
    with pytest.raises(ConfigError, match="#jrRoot"):
        resolve_layout(FakeTrilium())


def test_duplicate_root(trilium):
    trilium.add_note("root", "Otra", labels={"jrRoot": ""})
    with pytest.raises(ConfigError, match="solo una"):
        init_layout(trilium)


def test_custom_root_label(trilium):
    trilium.add_note("root", "Pruebas", labels={"jrRootTest": ""})
    layout = init_layout(trilium, "jrRootTest")
    assert trilium.get_note(layout.root).title == "Pruebas"


def test_layout_cache(trilium):
    init_layout(trilium)
    calls = []

    def loader():
        calls.append(1)
        return resolve_layout(trilium)

    cache = LayoutCache(loader)
    assert cache() == cache()
    assert len(calls) == 1
    cache.refresh()
    assert len(calls) == 2


def test_nested_destination_root_does_not_clash(trilium):
    from tohoku.flows.receta.layout import init_receta_layout
    from tohoku.flows.receta.params import RecetaParams

    layout = init_layout(trilium)
    trilium.add_note(layout.root, "Recetas (test)", labels={"jrRootRecetasTest": ""})
    anidado = init_receta_layout(trilium, "jrRootRecetasTest", RecetaParams())

    assert resolve_layout(trilium).revision == layout.revision != anidado.revision
    assert resolve_layout(trilium).plantillas == layout.plantillas != anidado.plantillas
    count = len(trilium.notes)
    assert init_layout(trilium) == layout
    assert len(trilium.notes) == count


def test_outer_init_after_nested_creates_own_sections(trilium):
    from tohoku.flows.receta.layout import init_receta_layout
    from tohoku.flows.receta.params import RecetaParams

    raiz = trilium.search("#jrRoot")[0].note_id
    trilium.add_note(raiz, "Recetas (test)", labels={"jrRootRecetasTest": ""})
    anidado = init_receta_layout(trilium, "jrRootRecetasTest", RecetaParams())
    layout = init_layout(trilium)
    assert layout.revision != anidado.revision
    assert trilium.get_note(layout.revision).parent_note_ids == [layout.root]
