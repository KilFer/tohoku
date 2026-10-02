from pathlib import Path
from types import SimpleNamespace

import pytest
from builders import JAPAN_PARAMS
from pydantic import ValidationError

from tohoku.destinations import ClassifierConfig, CleanupConfig, load_destinations
from tohoku.errors import ConfigError
from tohoku.flows.viaje.params import ViajeParams

REPO = Path(__file__).parents[2]
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
    pais: JP
    nombres_pais: [japon, japan, 日本]
    latitud: [20.0, 46.0]
    longitud: [122.0, 154.0]
    categorias_lugar: [templo, otro]
    categorias_cosa: {souvenirs: Souvenirs, otros: Otros}
"""


def _write(tmp_path, text=JAPON, prompt="PROMPT DE JAPÓN"):
    (tmp_path / "prompts").mkdir(exist_ok=True)
    (tmp_path / "prompts" / "japon.md").write_text(prompt, encoding="utf-8")
    path = tmp_path / "destinos.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_minimal_config_with_explicit_country_data(tmp_path):
    config = load_destinations(_write(tmp_path), FLOWS)

    dest = config.destinos["japon"]
    assert (dest.nombre, dest.flujo, dest.raiz, dest.descripcion) == ("japon", "viaje", "jrRoot", "Viaje a Japón")
    assert dest.prompt == "PROMPT DE JAPÓN"
    assert dest.params.pais == "JP" and dest.params.categorias_lugar == ["templo", "otro"]
    assert dest.params.alias_ciudad == {}
    assert config.candidates_for("L1") == ["japon"]
    assert config.candidates_for("otra") == []


def test_viaje_params_have_no_country_defaults():
    # Sin valores por defecto: un destino que solo declara `pais` no hereda la caja ni los nombres de Japón.
    with pytest.raises(ValidationError) as exc:
        ViajeParams(pais="NZ")
    missing = {e["loc"][0] for e in exc.value.errors() if e["type"] == "missing"}
    assert missing == {"nombres_pais", "latitud", "longitud", "categorias_lugar", "categorias_cosa"}


def test_viaje_alias_ciudad_is_optional_and_empty_by_default():
    assert JAPAN_PARAMS.model_copy(update={"alias_ciudad": {}}).alias_ciudad == {}
    p = ViajeParams(pais="NZ", nombres_pais=["new zealand"], latitud=(-48.0, -34.0), longitud=(166.0, 179.0),
                    categorias_lugar=["otro"], categorias_cosa={"otros": "Otros"})
    assert p.alias_ciudad == {}


def test_viaje_destination_that_only_declares_the_country_is_a_config_error(tmp_path):
    text = "destino_por_defecto: japon\n" + JAPON + """
  nz:
    flujo: viaje
    raiz: jrRootNZ
    descripcion: "Viaje a Nueva Zelanda"
    prompt: prompts/japon.md
    pais: NZ
"""
    with pytest.raises(ConfigError) as exc:
        load_destinations(_write(tmp_path, text), FLOWS)
    message = str(exc.value)
    assert "nz" in message and all(k in message for k in ("nombres_pais", "latitud", "longitud", "categorias_lugar", "categorias_cosa"))


def test_example_config_japan_block_is_the_reference_japan_params():
    # El destino de referencia vive en la configuración de ejemplo, no en el código.
    config = load_destinations(REPO / "config" / "destinos.example.yaml", FLOWS)
    assert config.destinos["japon"].params == JAPAN_PARAMS


def test_new_zealand_params(tmp_path):
    text = "destino_por_defecto: japon\n" + JAPON + """
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
    categorias_cosa: {souvenirs: Souvenirs}
"""
    config = load_destinations(_write(tmp_path, text), FLOWS)

    nz = config.destinos["nz"].params
    assert (nz.pais, nz.latitud, nz.categorias_lugar) == ("NZ", (-48.0, -34.0), ["naturaleza", "pueblo", "otro"])
    assert nz.categorias_cosa == {"souvenirs": "Souvenirs"}
    assert nz.alias_ciudad == {}  # único parámetro opcional


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
    text = JAPON.replace("    nombres_pais: [japon, japan, 日本]\n", '    nombres_pais: [""]\n')
    with pytest.raises(ConfigError, match="nombres_pais"):
        load_destinations(_write(tmp_path, text), FLOWS)


TWO = JAPON.replace("  L1: [japon]\n", "  L1: [japon]\n  INBOX: [japon, recetas]\n") + """
  recetas:
    flujo: viaje
    raiz: jrRootRecetas
    descripcion: "Recetas"
    prompt: prompts/japon.md
    pais: NZ
    nombres_pais: [new zealand]
    latitud: [-48.0, -34.0]
    longitud: [166.0, 179.0]
    categorias_lugar: [otro]
    categorias_cosa: {otros: Otros}
"""


def test_classifier_defaults_and_default_destination_with_single_destination(tmp_path):
    config = load_destinations(_write(tmp_path), FLOWS)
    assert config.clasificador == ClassifierConfig()
    assert config.destino_por_defecto == "japon"
    assert not config.needs_classifier()


def test_several_destinations_require_destino_por_defecto(tmp_path):
    with pytest.raises(ConfigError, match="destino_por_defecto"):
        load_destinations(_write(tmp_path, TWO), FLOWS)


def test_several_destinations_with_classifier(tmp_path):
    text = "destino_por_defecto: japon\nclasificador:\n  modelo: cheap/model\n  modo: etiqueta\n  margen_revision: 0.2\n" + TWO
    config = load_destinations(_write(tmp_path, text), FLOWS)
    assert config.needs_classifier() and config.candidates_for("INBOX") == ["japon", "recetas"]
    assert (config.clasificador.modelo, config.clasificador.modo, config.clasificador.margen_revision) == ("cheap/model", "etiqueta", 0.2)


@pytest.mark.parametrize(
    ("prefix", "message"),
    [
        ("destino_por_defecto: nz\n", "destino_por_defecto"),
        ("clasificador:\n  modello: x\n", "clasificador"),
        ("clasificador: 3\n", "clasificador"),
    ],
)
def test_classifier_and_default_destination_errors(tmp_path, prefix, message):
    with pytest.raises(ConfigError, match=message):
        load_destinations(_write(tmp_path, prefix + JAPON), FLOWS)


def test_cleanup_defaults_to_30_days(tmp_path):
    config = load_destinations(_write(tmp_path), FLOWS)
    assert config.limpieza == CleanupConfig()
    assert config.limpieza.retencion_dias == 30


def test_cleanup_retention_is_read(tmp_path):
    config = load_destinations(_write(tmp_path, "limpieza:\n  retencion_dias: 7\n" + JAPON), FLOWS)
    assert config.limpieza.retencion_dias == 7


@pytest.mark.parametrize(
    "prefix",
    ["limpieza:\n  retencion_dias: -1\n", "limpieza:\n  dias: 3\n", "limpieza: 3\n"],
)
def test_cleanup_errors_name_limpieza(tmp_path, prefix):
    with pytest.raises(ConfigError, match="limpieza"):
        load_destinations(_write(tmp_path, prefix + JAPON), FLOWS)


SPLIT = JAPON.replace("  L1: [japon]\n", "  L1: [japon]\n  L2: [recetas]\n") + """
  recetas:
    flujo: viaje
    raiz: jrRootRecetas
    descripcion: "Recetas"
    prompt: prompts/japon.md
    pais: NZ
    nombres_pais: [new zealand]
    latitud: [-48.0, -34.0]
    longitud: [166.0, 179.0]
    categorias_lugar: [otro]
    categorias_cosa: {otros: Otros}
destino_por_defecto: japon
"""


def test_classifier_needed_when_lists_point_to_different_destinations(tmp_path):
    """Un bookmark en L1 y L2 recibe los dos candidatos (la ingesta los une): hace falta clasificador."""
    config = load_destinations(_write(tmp_path, SPLIT), FLOWS)
    assert config.needs_classifier()


def test_classifier_not_needed_when_every_list_points_to_the_same_destination(tmp_path):
    config = load_destinations(_write(tmp_path, JAPON.replace("  L1: [japon]\n", "  L1: [japon]\n  L2: japon\n")), FLOWS)
    assert not config.needs_classifier()


def test_destination_names_equivalent_for_the_classifier_are_rejected(tmp_path):
    text = TWO.replace("  recetas:\n", "  Japón:\n").replace("[japon, recetas]", "[japon, Japón]")
    with pytest.raises(ConfigError, match="'Japón'.*'japon'|'japon'.*'Japón'"):
        load_destinations(_write(tmp_path, "destino_por_defecto: japon\n" + text), FLOWS)
