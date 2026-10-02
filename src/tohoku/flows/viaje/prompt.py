import copy

from tohoku.flows.viaje.params import ViajeParams
from tohoku.models import Extraction


def render_extract_prompt(template: str, params: ViajeParams) -> str:
    """Fills the destination's categories into the prompt (`{{categorias_lugar}}`, `{{categorias_cosa}}`)."""
    return template.replace("{{categorias_lugar}}", ", ".join(params.categorias_lugar)).replace(
        "{{categorias_cosa}}", " | ".join(params.categorias_cosa)
    )


def extraction_schema(params: ViajeParams) -> dict:
    """JSON schema of `Extraction` with the destination's categories as `enum`."""
    schema = copy.deepcopy(Extraction.model_json_schema())
    schema["$defs"]["Lugar"]["properties"]["categoria"]["enum"] = list(params.categorias_lugar)
    schema["$defs"]["Cosa"]["properties"]["categoria"]["enum"] = list(params.categorias_cosa)
    return schema


def invalid_categories(extraction: Extraction, params: ViajeParams) -> list[str]:
    """Categories not belonging to the destination, as messages asking the LLM to correct them."""
    lugares = ", ".join(params.categorias_lugar)
    cosas = ", ".join(params.categorias_cosa)
    return [
        *(f"lugares[{i}].categoria '{l.categoria}' no es una de: {lugares}"
          for i, l in enumerate(extraction.lugares) if l.categoria not in params.categorias_lugar),
        *(f"cosas[{i}].categoria '{c.categoria}' no es una de: {cosas}"
          for i, c in enumerate(extraction.cosas) if c.categoria not in params.categorias_cosa),
    ]
