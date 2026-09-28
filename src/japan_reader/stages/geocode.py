import logging

from japan_reader.clients.places import PlacesClient
from japan_reader.config import Thresholds
from japan_reader.context import JobContext
from japan_reader.geo import NAME_SIMILARITY, city_matches, in_japan, name_score
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
                match, clear = _choose(valid, lugar)
                return GeoOutcome(lugar_index=index, match=match, review_reason=None if clear else "geocodificacion-ambigua")
            if in_jp and japan_only is None:
                japan_only = in_jp[0]
        if japan_only:
            return GeoOutcome(lugar_index=index, match=japan_only, review_reason="geocodificacion-ambigua")
        return GeoOutcome(lugar_index=index, review_reason="geocodificacion-fallida")


def _choose(valid: list[GeoMatch], lugar: Lugar) -> tuple[GeoMatch, bool]:
    """Elige el resultado cuyo nombre mejor coincide (no necesariamente el primero).

    Es claro si solo hay uno, o si el mejor supera el umbral de nombre y no empata con otro.
    Si ninguno se parece, se devuelve el primero (el más relevante para Google) como ambiguo.
    """
    if len(valid) == 1:
        return valid[0], True
    scores = [name_score(r, lugar) for r in valid]
    best = max(range(len(valid)), key=lambda i: scores[i])  # max devuelve el primero en caso de empate
    if scores[best] < NAME_SIMILARITY:
        return valid[0], False
    tied = sum(1 for sc in scores if sc == scores[best]) > 1
    return valid[best], not tied
