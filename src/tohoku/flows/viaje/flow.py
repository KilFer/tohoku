from dataclasses import dataclass

from tohoku.clients.trilium import TriliumClient
from tohoku.destinations import Destination
from tohoku.flows.base import FlowDeps
from tohoku.flows.viaje.params import ViajeParams
from tohoku.flows.viaje.prompt import render_extract_prompt
from tohoku.pipeline import Stage
from tohoku.stages.extract import ExtractStage
from tohoku.stages.geocode import GeocodeStage
from tohoku.stages.publish import PublishStage
from tohoku.stages.resolve import ResolveStage
from tohoku.trilium_layout import Layout, LayoutCache, init_layout, resolve_layout


@dataclass
class ViajeRuntime:
    stages: list[Stage]
    layout: LayoutCache

    def refresh(self) -> Layout:
        return self.layout.refresh()


class ViajeFlow:
    """Lugares go to the Geo Map, cosas to "Comprar y comer", the rest to "Cultura" (docs/trilium-model.md)."""

    name = "viaje"
    params_model = ViajeParams

    def build(self, dest: Destination, deps: FlowDeps) -> ViajeRuntime:
        params: ViajeParams = dest.params  # type: ignore[assignment]
        layout = LayoutCache(lambda: resolve_layout(deps.trilium, dest.raiz, params.categorias_cosa))
        th = deps.settings.thresholds
        stages: list[Stage] = [
            ExtractStage(deps.settings, deps.llm, deps.llm_budget, render_extract_prompt(dest.prompt, params), params),
            GeocodeStage(deps.places, deps.places_quota, th, cache=deps.state, params=params),
            ResolveStage(deps.trilium, layout, th),
            PublishStage(deps.trilium, layout, deps.llm, deps.settings, deps.llm_budget, deps.state),
        ]
        return ViajeRuntime(stages=stages, layout=layout)

    def init_trilium(self, trilium: TriliumClient, dest: Destination) -> str:
        params: ViajeParams = dest.params  # type: ignore[assignment]
        layout = init_layout(trilium, dest.raiz, params.categorias_cosa)
        return f"Estructura lista. Mapa={layout.mapa} Comprar={layout.comprar} Revisión={layout.revision}"
