import pytest
from pydantic import ValidationError

from fakes import FakeTrilium
from tohoku.errors import ConfigError
from tohoku.flows.receta.layout import init_receta_layout, resolve_receta_layout
from tohoku.flows.receta.params import RecetaParams

ROOT = "jrRootRecetas"


@pytest.fixture
def trilium():
    fake = FakeTrilium()
    fake.add_note("root", "Recetas", labels={ROOT: ""})
    return fake


def test_init_creates_structure(trilium):
    params = RecetaParams()
    layout = init_receta_layout(trilium, ROOT, params)

    recetario = trilium.get_note(layout.recetario)
    assert recetario.type == "book"
    assert recetario.label("jrColeccion") == "" and recetario.label("viewType") == "table"
    assert recetario.parent_note_ids == [layout.root]
    assert trilium.get_note(layout.revision).label("jrRevision") == ""
    assert trilium.get_note(layout.plantillas).label("jrPlantillas") == ""
    plantilla = trilium.get_note(layout.plantilla_receta)
    assert plantilla.title == "Receta" and plantilla.label("template") == ""
    assert plantilla.parent_note_ids == [layout.plantillas]
    for nombre, tipo in params.atributos.items():
        assert plantilla.label(f"label:{nombre}") == f"promoted,single,{tipo}"
    assert plantilla.label("label:tiempo_min") == "promoted,single,number"
    assert resolve_receta_layout(trilium, ROOT) == layout


def test_init_twice_does_not_duplicate(trilium):
    params = RecetaParams()
    first = init_receta_layout(trilium, ROOT, params)
    notas = len(trilium.notes)
    attrs = len(trilium.attrs)
    assert init_receta_layout(trilium, ROOT, params) == first
    assert len(trilium.notes) == notas and len(trilium.attrs) == attrs


def test_resolve_before_init_fails(trilium):
    with pytest.raises(ConfigError, match="init-trilium"):
        resolve_receta_layout(trilium, ROOT)


def test_resolve_without_root_fails():
    with pytest.raises(ConfigError, match=ROOT):
        resolve_receta_layout(FakeTrilium(), ROOT)


def test_grid_view(trilium):
    layout = init_receta_layout(trilium, ROOT, RecetaParams(vista="grid"))
    assert trilium.get_note(layout.recetario).label("viewType") == "grid"


def test_invalid_attribute_name_rejected():
    with pytest.raises(ValidationError):
        RecetaParams(atributos={"tiempo min": "number"}, atributos_usuario=[])


def test_user_attributes_must_be_declared():
    with pytest.raises(ValidationError):
        RecetaParams(atributos={"cocina": "text"}, atributos_usuario=["probada"])


def test_params_forbid_extra_and_are_frozen():
    with pytest.raises(ValidationError):
        RecetaParams(otra=1)
    with pytest.raises(ValidationError):
        RecetaParams().vista = "list"


def test_nested_roots_do_not_clash(trilium):
    from tohoku.trilium_layout import init_layout

    params = RecetaParams()
    externo = init_receta_layout(trilium, ROOT, params)
    trilium.add_note(externo.root, "Japón", labels={"jrRoot": ""})
    viaje = init_layout(trilium)
    assert resolve_receta_layout(trilium, ROOT) == externo
    assert viaje.revision != externo.revision
    notas = len(trilium.notes)
    assert init_receta_layout(trilium, ROOT, params) == externo
    assert len(trilium.notes) == notas


def test_receta_inside_receta(trilium):
    params = RecetaParams()
    externo = init_receta_layout(trilium, ROOT, params)
    trilium.add_note(externo.root, "Anidado", labels={"jrRootOtra": ""})
    interno = init_receta_layout(trilium, "jrRootOtra", params)
    assert resolve_receta_layout(trilium, ROOT) == externo
    assert interno.revision != externo.revision
