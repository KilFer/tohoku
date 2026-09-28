import logging

from japan_reader.clients.places import PlacesClient
from japan_reader.config import Thresholds
from japan_reader.context import JobContext
from japan_reader.geo import city_matches, in_japan, name_matches
from japan_reader.models import ExtractResult, GeocodeResult, GeoMatch, GeoOutcome, Lugar
from japan_reader.quota import DailyQuota
from japan_reader.rules import japan_decision

log = logging.getLogger(__name__)


class GeocodeStage:
    """Etapa 5: coordenadas y ficha de Google para cada lugar."""

    name = "geocode"
    result_model = GeocodeResult

    def __init__(self, places: PlacesClient, quota: DailyQuota, thresholds: Thresholds) -> None:
        self._places = places
        self._quota = quota
        self._th = thresholds

    def run(self, ctx: JobContext) -> GeocodeResult:
        extraction = ctx.result("extract", ExtractResult).extraction
        if extraction is None or japan_decision(extraction, self._th) == "no":
            return GeocodeResult()
        outcomes = [self._geocode(i, lugar) for i, lugar in enumerate(extraction.lugares)]
        for outcome in outcomes:
            log.info(
                "bookmark=%s geocode lugar=%d place=%s revision=%s", ctx.job.bookmark_id, outcome.lugar_index,
                outcome.match.place_id if outcome.match else None, outcome.review_reason,
            )
        return GeocodeResult(outcomes=outcomes)

    def _geocode(self, index: int, lugar: Lugar) -> GeoOutcome:
        queries = list(dict.fromkeys(q for q in (lugar.consulta_busqueda, lugar.nombre_local) if q))
        japan_only: GeoMatch | None = None
        for query in queries:
            self._quota.check()
            results = self._places.search(query)
            self._quota.add(1)
            in_jp = [r for r in results if in_japan(r)]
            valid = [r for r in in_jp if city_matches(r, lugar.ciudad)]
            if valid:
                top = valid[0]
                if len(valid) == 1 or name_matches(top, lugar):
                    return GeoOutcome(lugar_index=index, match=top)
                return GeoOutcome(lugar_index=index, match=top, review_reason="geocodificacion-ambigua")
            if in_jp and japan_only is None:
                japan_only = in_jp[0]
        if japan_only:
            return GeoOutcome(lugar_index=index, match=japan_only, review_reason="geocodificacion-ambigua")
        return GeoOutcome(lugar_index=index, review_reason="geocodificacion-fallida")
