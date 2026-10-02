from pathlib import Path
from typing import Protocol

from pydantic import BaseModel


class Candidate(BaseModel):
    nombre: str
    descripcion: str


class Verdict(BaseModel):
    """Respuesta ya interpretada de un clasificador (sin validar contra los candidatos)."""

    destino: str | None  # None = "ninguno"
    confianza: float = 1.0
    alternativa: str | None = None
    confianza_alternativa: float = 0.0
    cost_usd: float = 0.0


class ClassifierError(Exception):
    """The response could not be interpreted; `raw` is the text received and `cost_usd` the cost spent."""

    def __init__(self, message: str, raw: str, cost_usd: float) -> None:
        super().__init__(message)
        self.raw = raw
        self.cost_usd = cost_usd


class Classifier(Protocol):
    def classify(self, text: str, images: list[Path], candidates: list[Candidate], feedback: str | None = None) -> Verdict: ...
