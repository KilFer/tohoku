import logging
from collections.abc import Mapping, Sequence
from datetime import timedelta

from tohoku.clients.places import PlacesClient
from tohoku.config import Thresholds
from tohoku.context import JobContext
from tohoku.flows.viaje.params import ViajeParams
from tohoku.geo import NAME_SIMILARITY, SAME_PLACE_RADIUS_M, city_matches, distance_m, in_country, name_score
from tohoku.models import ExtractResult, GeocodeResult, GeoMatch, GeoOutcome, Lugar
from tohoku.quota import DailyQuota
from tohoku.rules import destination_decision
from tohoku.state import StateStore

log = logging.getLogger(__name__)
# Los mismos sitios aparecen en muchos vídeos ("dotonbori osaka" ×18): se reutiliza la búsqueda.
CACHE_MAX_AGE = timedelta(days=30)


class GeocodeStage:
    """Etapa 5: coordenadas y ficha de Google para cada lugar."""

    name = "geocode"
    result_model = GeocodeResult

    def __init__(self, places: PlacesClient, quota: DailyQuota, thresholds: Thresholds, cache: StateStore | None = None,
                 *, params: ViajeParams) -> None:
        self._places = places
        self._quota = quota
        self._th = thresholds
        self._cache = cache
        self._params = params
        # Japón (el destino de referencia) no lleva prefijo; el resto, sí, para no mezclar búsquedas de países distintos.
        self._cache_prefix = "" if self._params.pais == "JP" else f"{self._params.pais}|"

    def _in_country(self, match: GeoMatch) -> bool:
        p = self._params
        return in_country(match, p.pais, p.nombres_pais, p.latitud, p.longitud)

    def run(self, ctx: JobContext) -> GeocodeResult:
        extraction = ctx.result("extract", ExtractResult).extraction
        if extraction is None or destination_decision(extraction, self._th) == "no":
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
        aliases = self._params.alias_ciudad
        japan_only: GeoMatch | None = None
        for query in queries:
            results = self._search(query)
            in_dest = [r for r in results if self._in_country(r)]
            valid = [r for r in in_dest if city_matches(r, lugar.ciudad, aliases)]
            # Nombre exacto en Japón aunque la ciudad no cuadre: el LLM suele equivocar la ciudad
            # de sitios de las afueras (Tokyo DisneySea está en Chiba), no el nombre.
            candidates = valid or [r for r in in_dest if name_score(r, lugar, aliases) >= 2]
            if candidates:
                match, clear = _choose(candidates, lugar, aliases)
                return GeoOutcome(lugar_index=index, match=match, review_reason=None if clear else "geocodificacion-ambigua")
            if in_dest and japan_only is None:
                japan_only = in_dest[0]
        if japan_only:
            return GeoOutcome(lugar_index=index, match=japan_only, review_reason="geocodificacion-ambigua")
        return GeoOutcome(lugar_index=index, review_reason="geocodificacion-fallida")


    def _search(self, query: str) -> list[GeoMatch]:
        key = self._cache_prefix + query
        if self._cache is not None:
            cached = self._cache.get_places_cache(key, CACHE_MAX_AGE)
            if cached is not None:
                return [GeoMatch.model_validate(r) for r in cached]
        self._quota.check()
        results = self._places.search(query, region=self._params.pais)
        self._quota.add(1)
        if self._cache is not None:
            self._cache.put_places_cache(key, [r.model_dump() for r in results])
        return results


def _choose(valid: list[GeoMatch], lugar: Lugar, aliases: Mapping[str, Sequence[str]]) -> tuple[GeoMatch, bool]:
    """Elige el resultado cuyo nombre mejor coincide (no necesariamente el primero).

    Es claro si solo hay uno, o si el mejor supera el umbral de nombre y no empata con otro
    (o los empatados están a menos de SAME_PLACE_RADIUS_M: son el mismo sitio).
    Si ninguno se parece, se devuelve el primero (el más relevante para Google) como ambiguo.
    """
    if len(valid) == 1:
        return valid[0], True
    scores = [name_score(r, lugar, aliases) for r in valid]
    best = max(range(len(valid)), key=lambda i: scores[i])  # max devuelve el primero en caso de empate
    if scores[best] < NAME_SIMILARITY:
        return valid[0], False
    tied = [r for r, sc in zip(valid, scores) if sc == scores[best]]
    same_place = all(distance_m(valid[best], r) <= SAME_PLACE_RADIUS_M for r in tied)
    return valid[best], same_place
