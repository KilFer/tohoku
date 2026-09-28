import logging
from collections.abc import Callable

from japan_reader.clients.trilium import TriliumClient
from japan_reader.config import Thresholds
from japan_reader.context import JobContext
from japan_reader.models import (
    Extraction,
    ExtractResult,
    GeocodeResult,
    GeoOutcome,
    ItemKind,
    PlannedItem,
    ResolveResult,
)
from japan_reader.rules import japan_decision
from japan_reader.text import normalize_name, similarity
from japan_reader.trilium_layout import Layout

log = logging.getLogger(__name__)


class ResolveStage:
    """Etapa 6: decide qué se crea, qué se fusiona con notas existentes y qué va a revisión."""

    name = "resolve"
    result_model = ResolveResult

    def __init__(self, trilium: TriliumClient, layout: Callable[[], Layout], thresholds: Thresholds) -> None:
        self._t = trilium
        self._layout = layout
        self._th = thresholds

    def run(self, ctx: JobContext) -> ResolveResult:
        extraction = ctx.result("extract", ExtractResult).extraction
        if extraction is None:
            item = PlannedItem(key="fallo", kind=ItemKind.FALLO, index=0, action="create", review_reasons=["extraccion-fallida"])
            return ResolveResult(items=[item])
        decision = japan_decision(extraction, self._th)
        if decision == "no":
            return ResolveResult()
        layout = self._layout()
        common = ["clasificacion-incierta"] if decision == "uncertain" else []
        items = [
            *self._lugares(extraction, ctx.result("geocode", GeocodeResult), layout, common),
            *self._cosas(extraction, layout, common),
            *(
                PlannedItem(key=f"otro:{i}", kind=ItemKind.OTRO, index=i, action="create", review_reasons=list(common))
                for i in range(len(extraction.otros))
            ),
        ]
        if not items:
            items.append(PlannedItem(key="otro:resumen", kind=ItemKind.OTRO, index=-1, action="create", review_reasons=list(common)))
        log.info(
            "bookmark=%s resolve crear=%d fusionar=%d revision=%d", ctx.job.bookmark_id,
            sum(i.action == "create" for i in items), sum(i.action == "merge" for i in items),
            sum(bool(i.review_reasons) for i in items),
        )
        return ResolveResult(items=items)

    def _reasons(self, common: list[str], confianza: float, *extra: str | None) -> list[str]:
        reasons = list(common)
        if confianza < self._th.item_review:
            reasons.append("baja-confianza")
        reasons += [reason for reason in extra if reason]
        return list(dict.fromkeys(reasons))

    def _lugares(self, extraction: Extraction, geo: GeocodeResult, layout: Layout, common: list[str]) -> list[PlannedItem]:
        outcomes = {o.lugar_index: o for o in geo.outcomes}
        seen: dict[str, str] = {}
        items: list[PlannedItem] = []
        for i, lugar in enumerate(extraction.lugares):
            key = f"lugar:{i}"
            outcome = outcomes.get(i) or GeoOutcome(lugar_index=i, review_reason="geocodificacion-fallida")
            match = outcome.match
            if match and match.place_id in seen:
                items.append(PlannedItem(key=key, kind=ItemKind.LUGAR, index=i, action="alias", alias_of=seen[match.place_id]))
                continue
            existing = self._t.search(f'#googlePlaceId="{match.place_id}"', ancestor=layout.root) if match else []
            if match:
                seen[match.place_id] = key
            items.append(
                PlannedItem(
                    key=key, kind=ItemKind.LUGAR, index=i,
                    action="merge" if existing else "create",
                    existing_note_id=existing[0].note_id if existing else None,
                    review_reasons=self._reasons(common, lugar.confianza, outcome.review_reason),
                )
            )
        return items

    def _cosas(self, extraction: Extraction, layout: Layout, common: list[str]) -> list[PlannedItem]:
        seen: dict[str, str] = {}
        known: list[str] | None = None
        items: list[PlannedItem] = []
        for i, cosa in enumerate(extraction.cosas):
            key = f"cosa:{i}"
            norm = normalize_name(cosa.nombre) or cosa.nombre.casefold().replace('"', "").strip()
            if norm in seen:
                items.append(PlannedItem(key=key, kind=ItemKind.COSA, index=i, action="alias", alias_of=seen[norm]))
                continue
            seen[norm] = key
            reasons = self._reasons(common, cosa.confianza)
            exact = self._t.search(f'#jrTipo=cosa #jrNombreNorm="{norm}"', ancestor=layout.comprar)
            if exact:
                items.append(PlannedItem(key=key, kind=ItemKind.COSA, index=i, action="merge", existing_note_id=exact[0].note_id, review_reasons=reasons))
                continue
            if known is None:
                known = [n.label("jrNombreNorm") or "" for n in self._t.search("#jrTipo=cosa", ancestor=layout.comprar)]
            if any(k and similarity(norm, k) >= self._th.cosa_duplicate for k in known):
                reasons.append("posible-duplicado")
            items.append(PlannedItem(key=key, kind=ItemKind.COSA, index=i, action="create", review_reasons=reasons))
        return items
