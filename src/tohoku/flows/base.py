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
    """Shared clients and quotas a flow needs to assemble its stages."""

    settings: Settings
    state: StateStore
    trilium: TriliumClient
    llm: OpenRouterClient
    places: PlacesClient
    llm_budget: DailyQuota
    places_quota: DailyQuota


class FlowRuntime(Protocol):
    """A flow assembled for a destination."""

    stages: list[Stage]  # the flow's own stages (after fetch and transcribe)

    def refresh(self) -> object:
        """Re-resolves the destination's structure in Trilium. ConfigError if it is incomplete."""
        ...


class Flow(Protocol):
    name: str
    params_model: type[BaseModel]

    def build(self, dest: Destination, deps: FlowDeps) -> FlowRuntime: ...

    def init_trilium(self, trilium: TriliumClient, dest: Destination) -> str:
        """Creates whatever is missing under the destination root (idempotent) and returns a summary for the CLI."""
        ...
