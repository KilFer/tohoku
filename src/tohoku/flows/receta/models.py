"""Modelos de las etapas `extract` y `cover` del flujo `receta`."""

from pydantic import BaseModel


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
    portada: int | None = None  # índice en imágenes + fotogramas enviados al LLM
    confianza: float


class CoverResult(BaseModel):
    path: str | None = None  # relativa al workdir
