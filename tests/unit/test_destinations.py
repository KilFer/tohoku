from types import SimpleNamespace

import pytest

from tohoku.destinations import load_destinations
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

    dest = config.single_destination()
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
    text = JAPON + """
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
    ],
)
def test_config_errors_name_the_culprit(tmp_path, text, message):
    with pytest.raises(ConfigError, match=message):
        load_destinations(_write(tmp_path, text), FLOWS)


def test_missing_file_mentions_the_setting(tmp_path):
    with pytest.raises(ConfigError, match="DESTINOS_FILE"):
        load_destinations(tmp_path / "no.yaml", FLOWS)


def test_more_than_one_destination_is_not_supported_yet(tmp_path):
    text = JAPON + "  nz:\n    flujo: viaje\n    raiz: jrRootNZ\n    descripcion: NZ\n    prompt: prompts/japon.md\n    pais: NZ\n"
    config = load_destinations(_write(tmp_path, text), FLOWS)
    with pytest.raises(ConfigError, match="fase 3"):
        config.single_destination()
