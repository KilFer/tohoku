import logging
from collections.abc import Callable

from tohoku.clients.trilium import TriliumClient
from tohoku.config import Thresholds
from tohoku.context import JobContext
from tohoku.flows.receta.extract import RecetaExtractResult
from tohoku.flows.receta.layout import RecetaLayout
from tohoku.models import Classification, ItemKind, PlannedItem, ResolveResult
from tohoku.notes import name_key
from tohoku.rules import destination_decision
from tohoku.text import similarity

log = logging.getLogger(__name__)


class RecetaResolveStage:
    """Decides whether the recipe is created and which review reasons it carries. No merging across sources."""

    name = "resolve"
    result_model = ResolveResult

    def __init__(self, trilium: TriliumClient, layout: Callable[[], RecetaLayout], thresholds: Thresholds) -> None:
        self._t = trilium
        self._layout = layout
        self._th = thresholds

    def run(self, ctx: JobContext) -> ResolveResult:
        extraction = ctx.result("extract", RecetaExtractResult).extraction
        if extraction is None:
            return ResolveResult(items=[PlannedItem(key="fallo", kind=ItemKind.FALLO, index=0, action="create", review_reasons=["extraccion-fallida"])])
        decision = destination_decision(extraction, self._th)
        if decision == "no":
            return ResolveResult()
        reasons = ["clasificacion-incierta"] if decision == "uncertain" else []
        classification = ctx.results.get("classify")
        if isinstance(classification, Classification) and classification.dudosa:
            reasons.append("clasificacion-dudosa")
        if extraction.confianza < self._th.item_review:
            reasons.append("baja-confianza")
        if self._possible_duplicate(extraction.titulo, ctx.job.bookmark_id):
            reasons.append("posible-duplicado")
        log.info("bookmark=%s resolve receta revision=%s", ctx.job.bookmark_id, bool(reasons))
        return ResolveResult(items=[PlannedItem(key="receta", kind=ItemKind.RECETA, index=0, action="create", review_reasons=list(dict.fromkeys(reasons)))])

    def _possible_duplicate(self, titulo: str, bookmark_id: str) -> bool:
        norm = name_key(titulo)
        for note in self._t.search("#jrTipo=receta", ancestor=self._layout().root):
            if (note.label("jrItem") or "").startswith(f"{bookmark_id}:"):
                continue  # this same link's recipe (reprocessing)
            known = note.label("jrNombreNorm") or ""
            if known and similarity(norm, known) >= self._th.cosa_duplicate:
                return True
        return False
