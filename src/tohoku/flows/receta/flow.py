from dataclasses import dataclass

from tohoku.clients.trilium import TriliumClient
from tohoku.destinations import Destination
from tohoku.flows.base import FlowDeps
from tohoku.flows.receta.cover import CoverStage
from tohoku.flows.receta.extract import RecetaExtractStage
from tohoku.flows.receta.layout import RecetaLayout, init_receta_layout, resolve_receta_layout
from tohoku.flows.receta.params import RecetaParams
from tohoku.flows.receta.publish import RecetaPublishStage
from tohoku.flows.receta.resolve import RecetaResolveStage
from tohoku.pipeline import Stage
from tohoku.trilium_layout import LayoutCache


@dataclass
class RecetaRuntime:
    stages: list[Stage]
    layout: LayoutCache

    def refresh(self) -> RecetaLayout:
        return self.layout.refresh()


class RecetaFlow:
    """Una receta por enlace, en el Recetario de Trilium (docs/flujos/receta.md)."""

    name = "receta"
    params_model = RecetaParams

    def build(self, dest: Destination, deps: FlowDeps) -> RecetaRuntime:
        params: RecetaParams = dest.params  # type: ignore[assignment]
        layout = LayoutCache(lambda: resolve_receta_layout(deps.trilium, dest.raiz))
        stages: list[Stage] = [
            RecetaExtractStage(deps.settings, deps.llm, deps.llm_budget, dest.prompt),
            CoverStage(deps.settings),
            RecetaResolveStage(deps.trilium, layout, deps.settings.thresholds),
            RecetaPublishStage(deps.trilium, layout, deps.settings, deps.state, params=params),
        ]
        return RecetaRuntime(stages=stages, layout=layout)

    def init_trilium(self, trilium: TriliumClient, dest: Destination) -> str:
        params: RecetaParams = dest.params  # type: ignore[assignment]
        layout = init_receta_layout(trilium, dest.raiz, params)
        return f"Estructura lista. Recetario={layout.recetario} Revisión={layout.revision}"
