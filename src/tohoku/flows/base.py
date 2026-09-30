from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel

from tohoku.clients.openrouter import OpenRouterClient
from tohoku.clients.places import PlacesClient
from tohoku.clients.trilium import TriliumClient
from tohoku.config import Settings
from tohoku.destinations import Destination
from tohoku.pipeline import Stage
from tohoku.quota import DailyQuota
from tohoku.state import StateStore


@dataclass(frozen=True)
class FlowDeps:
    """Clientes y cuotas compartidos que un flujo necesita para montar sus etapas."""

    settings: Settings
    state: StateStore
    trilium: TriliumClient
    llm: OpenRouterClient
    places: PlacesClient
    llm_budget: DailyQuota
    places_quota: DailyQuota


class FlowRuntime(Protocol):
    """Un flujo montado para un destino."""

    stages: list[Stage]  # etapas propias del flujo (después de fetch y transcribe)

    def refresh(self) -> object:
        """Vuelve a resolver la estructura del destino en Trilium. ConfigError si está incompleta."""
        ...


class Flow(Protocol):
    name: str
    params_model: type[BaseModel]

    def build(self, dest: Destination, deps: FlowDeps) -> FlowRuntime: ...

    def init_trilium(self, trilium: TriliumClient, dest: Destination) -> str:
        """Crea lo que falte bajo la raíz del destino (idempotente) y devuelve un resumen para la CLI."""
        ...
