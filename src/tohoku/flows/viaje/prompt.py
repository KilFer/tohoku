import copy

from tohoku.flows.viaje.params import ViajeParams
from tohoku.models import Extraction


def render_extract_prompt(template: str, params: ViajeParams) -> str:
    """Rellena las categorías del destino en el prompt (`{{categorias_lugar}}`, `{{categorias_cosa}}`)."""
    return template.replace("{{categorias_lugar}}", ", ".join(params.categorias_lugar)).replace(
        "{{categorias_cosa}}", " | ".join(params.categorias_cosa)
    )


def extraction_schema(params: ViajeParams) -> dict:
    """Esquema JSON de `Extraction` con las categorías del destino como `enum`."""
    schema = copy.deepcopy(Extraction.model_json_schema())
    schema["$defs"]["Lugar"]["properties"]["categoria"]["enum"] = list(params.categorias_lugar)
    schema["$defs"]["Cosa"]["properties"]["categoria"]["enum"] = list(params.categorias_cosa)
    return schema


def invalid_categories(extraction: Extraction, params: ViajeParams) -> list[str]:
    """Categorías que no son del destino, como mensajes para pedir al LLM que corrija."""
    lugares = ", ".join(params.categorias_lugar)
    cosas = ", ".join(params.categorias_cosa)
    return [
        *(f"lugares[{i}].categoria '{l.categoria}' no es una de: {lugares}"
          for i, l in enumerate(extraction.lugares) if l.categoria not in params.categorias_lugar),
        *(f"cosas[{i}].categoria '{c.categoria}' no es una de: {cosas}"
          for i, c in enumerate(extraction.cosas) if c.categoria not in params.categorias_cosa),
    ]
