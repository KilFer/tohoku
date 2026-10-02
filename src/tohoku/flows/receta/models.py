"""Models for the `extract` and `cover` stages of the `receta` flow."""

from typing import Literal

from pydantic import BaseModel

from tohoku.notes import SourceEntry


class Ingrediente(BaseModel):
    cantidad: str | None = None
    unidad: str | None = None
    ingrediente: str
    nota: str | None = None
    grupo: str | None = None


class RecetaExtraction(BaseModel):
    relacionado_destino: bool
    confianza_destino: float
    titulo: str
    resumen: str
    raciones: int | None = None
    tiempo_min: int | None = None
    dificultad: str | None = None
    tipo_plato: str | None = None
    cocina: str | None = None
    ingredientes: list[Ingrediente] = []
    pasos: list[str] = []
    consejos: list[str] = []
    portada: int | None = None  # index into images + keyframes sent to the LLM
    confianza: float


class CoverResult(BaseModel):
    path: str | None = None  # relative to the workdir


class RecetaData(BaseModel):
    """Datos de una nota de receta; se guardan en el adjunto `tohoku.json`."""

    kind: Literal["receta"] = "receta"
    titulo: str
    resumen: str
    raciones: int | None = None
    tiempo_min: int | None = None
    dificultad: str | None = None
    tipo_plato: str | None = None
    cocina: str | None = None
    ingredientes: list[Ingrediente] = []
    pasos: list[str] = []
    consejos: list[str] = []
    fuentes: list[SourceEntry] = []
    portada_adjunto: str | None = None  # attachmentId de `portada.jpg`


def dump_data(data: RecetaData) -> str:
    return data.model_dump_json(indent=2)


def load_data(raw: str) -> RecetaData:
    return RecetaData.model_validate_json(raw)
