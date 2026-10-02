import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Label name accepted by Trilium: letters (unicode), digits, "_" and ":", no spaces.
_LABEL_NAME = re.compile(r"^[^\W\d][\w:]*$")


def _default_atributos() -> dict[str, Literal["text", "number", "boolean"]]:
    return {
        "tipo_plato": "text", "cocina": "text", "tiempo_min": "number", "raciones": "number",
        "dificultad": "text", "probada": "boolean", "valoracion": "number",
    }


class RecetaParams(BaseModel):
    """Parameters of a destination of the `receta` flow."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    vista: Literal["table", "grid", "list"] = "table"
    # Promoted attributes of the `Receta` template (name -> type).
    atributos: dict[str, Literal["text", "number", "boolean"]] = Field(default_factory=_default_atributos)
    # Attributes the user fills in by hand: the service never writes them.
    atributos_usuario: list[str] = Field(default_factory=lambda: ["probada", "valoracion"])

    @field_validator("atributos")
    @classmethod
    def _nombres_validos(cls, value: dict[str, str]) -> dict[str, str]:
        for nombre in value:
            if not _LABEL_NAME.match(nombre):
                raise ValueError(f"'{nombre}' no es un nombre de etiqueta válido de Trilium (letras, dígitos, '_' y ':', sin espacios)")
        return value

    @model_validator(mode="after")
    def _usuario_declarados(self) -> "RecetaParams":
        faltan = [a for a in self.atributos_usuario if a not in self.atributos]
        if faltan:
            raise ValueError(f"atributos_usuario contiene atributos que no están en atributos: {', '.join(faltan)}")
        return self
