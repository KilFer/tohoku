from types import SimpleNamespace

import pytest

from tohoku.destinations import ClassifierConfig, load_destinations
from tohoku.errors import ConfigError
from tohoku.flows.viaje.params import ViajeParams
from tohoku.geo import CITY_ALIASES
from tohoku.models import LUGAR_CATEGORIAS
from tohoku.trilium_layout import CATEGORIES

FLOWS = {"viaje": SimpleNamespace(params_model=ViajeParams)}

JAPON = """
listas:
  L1: [japon]
destinos:
  japon:
    flujo: viaje
    raiz: jrRoot
    descripcion: "Viaje a Japón"
    prompt: prompts/japon.md
"""


def _write(tmp_path, text=JAPON, prompt="PROMPT DE JAPÓN"):
    (tmp_path / "prompts").mkdir(exist_ok=True)
    (tmp_path / "prompts" / "japon.md").write_text(prompt, encoding="utf-8")
    path = tmp_path / "destinos.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_minimal_japan_config(tmp_path):
    config = load_destinations(_write(tmp_path), FLOWS)

    dest = config.destinos["japon"]
    assert (dest.nombre, dest.flujo, dest.raiz, dest.descripcion) == ("japon", "viaje", "jrRoot", "Viaje a Japón")
    assert dest.prompt == "PROMPT DE JAPÓN"
    assert dest.params == ViajeParams()
    assert config.candidates_for("L1") == ["japon"]
    assert config.candidates_for("otra") == []


def test_viaje_defaults_are_the_japan_constants():
    p = ViajeParams()
    assert p.pais == "JP"
    assert p.nombres_pais == ["japon", "japan", "日本"]
    assert (p.latitud, p.longitud) == ((20.0, 46.0), (122.0, 154.0))
    assert p.categorias_lugar == list(LUGAR_CATEGORIAS)
    assert p.categorias_cosa == CATEGORIES
    assert p.alias_ciudad == CITY_ALIASES


def test_new_zealand_params(tmp_path):
    text = "destino_legado: japon\n" + JAPON + """
  nz:
    flujo: viaje
    raiz: jrRootNZ
    descripcion: "Viaje a Nueva Zelanda"
    prompt: prompts/japon.md
    pais: NZ
    nombres_pais: [new zealand, nueva zelanda]
    latitud: [-48.0, -34.0]
    longitud: [166.0, 179.0]
    categorias_lugar: [naturaleza, pueblo, otro]
"""
    config = load_destinations(_write(tmp_path, text), FLOWS)

    nz = config.destinos["nz"].params
    assert (nz.pais, nz.latitud, nz.categorias_lugar) == ("NZ", (-48.0, -34.0), ["naturaleza", "pueblo", "otro"])
    assert nz.categorias_cosa == CATEGORIES  # lo no indicado toma el valor por defecto


def test_single_list_value_can_be_a_string(tmp_path):
    config = load_destinations(_write(tmp_path, JAPON.replace("[japon]", "japon")), FLOWS)
    assert config.candidates_for("L1") == ["japon"]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (JAPON + "otra: 1\n", "claves desconocidas: otra"),
        (JAPON.replace("flujo: viaje", "flujo: receta"), "flujo desconocido 'receta'"),
        (JAPON.replace("[japon]", "[japon, nz]"), "no existen: nz"),
        (JAPON.replace("prompts/japon.md", "prompts/nz.md"), "no existe el prompt"),
        (JAPON.replace("raiz: jrRoot", "raiz: '#jrRoot'"), "'raiz'"),
        (JAPON.replace("    prompt:", "    paiss: NZ\n    prompt:"), "paiss"),
        (JAPON.replace("    raiz: jrRoot\n", ""), "faltan claves: raiz"),
        ("listas:\n  L1: [japon]\ndestinos: {}\n", "ningún destino"),
        (JAPON.replace("  L1: [japon]\n", ""), "ninguna lista"),
        ("listas: [\n", "YAML inválido"),
        (JAPON.replace("raiz: jrRoot", "raiz: #jrRoot"), "'raiz' está vacío"),
        (JAPON.replace("flujo: viaje", "flujo:"), "'flujo' está vacío"),
        (JAPON.replace("prompt: prompts/japon.md", "prompt:"), "'prompt' está vacío"),
        (JAPON.replace('descripcion: "Viaje a Japón"', "descripcion:"), "'descripcion' está vacío"),
        ("listas:\n  L1: [japon]\ndestinos:\n  - japon\n", "'destinos' debe ser un mapa"),
        (JAPON.replace("listas:\n  L1: [japon]\n", "listas:\n  - L1\n"), "'listas' debe ser un mapa"),
        (JAPON.replace("[japon]", "5"), "la lista 'L1' debe ser un destino o una lista de destinos"),
    ],
)
def test_config_errors_name_the_culprit(tmp_path, text, message):
    with pytest.raises(ConfigError, match=message):
        load_destinations(_write(tmp_path, text), FLOWS)


def test_missing_file_mentions_the_setting(tmp_path):
    with pytest.raises(ConfigError, match="DESTINOS_FILE"):
        load_destinations(tmp_path / "no.yaml", FLOWS)


def test_empty_nombres_pais_entry_is_rejected(tmp_path):
    text = JAPON.replace("    prompt: prompts/japon.md\n", '    prompt: prompts/japon.md\n    nombres_pais: [""]\n')
    with pytest.raises(ConfigError, match="nombres_pais"):
        load_destinations(_write(tmp_path, text), FLOWS)


TWO = JAPON.replace("  L1: [japon]\n", "  L1: [japon]\n  INBOX: [japon, recetas]\n") + """
  recetas:
    flujo: viaje
    raiz: jrRootRecetas
    descripcion: "Recetas"
    prompt: prompts/japon.md
"""


def test_classifier_defaults_and_legacy_with_single_destination(tmp_path):
    config = load_destinations(_write(tmp_path), FLOWS)
    assert config.clasificador == ClassifierConfig()
    assert config.destino_legado == "japon"
    assert not config.needs_classifier()


def test_several_destinations_require_destino_legado(tmp_path):
    with pytest.raises(ConfigError, match="destino_legado"):
        load_destinations(_write(tmp_path, TWO), FLOWS)


def test_several_destinations_with_classifier(tmp_path):
    text = "destino_legado: japon\nclasificador:\n  modelo: cheap/model\n  modo: etiqueta\n  margen_revision: 0.2\n" + TWO
    config = load_destinations(_write(tmp_path, text), FLOWS)
    assert config.needs_classifier() and config.candidates_for("INBOX") == ["japon", "recetas"]
    assert (config.clasificador.modelo, config.clasificador.modo, config.clasificador.margen_revision) == ("cheap/model", "etiqueta", 0.2)


@pytest.mark.parametrize(
    ("prefix", "message"),
    [
        ("destino_legado: nz\n", "destino_legado"),
        ("clasificador:\n  modello: x\n", "clasificador"),
        ("clasificador: 3\n", "clasificador"),
    ],
)
def test_classifier_and_legacy_errors(tmp_path, prefix, message):
    with pytest.raises(ConfigError, match=message):
        load_destinations(_write(tmp_path, prefix + JAPON), FLOWS)
