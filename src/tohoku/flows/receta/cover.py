import logging

from tohoku.config import Settings
from tohoku.context import JobContext
from tohoku.flows.receta.extract import RecetaExtractResult
from tohoku.flows.receta.models import CoverResult
from tohoku.media.images import resize_image
from tohoku.models import ContentType, FetchResult

log = logging.getLogger(__name__)

COVER_NAME = "cover.jpg"


class CoverStage:
    """Elige la imagen de portada de la receta y la guarda redimensionada como `cover.jpg`."""

    name = "cover"
    needs_files = True
    result_model = CoverResult

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def run(self, ctx: JobContext) -> CoverResult:
        fetch = ctx.result("fetch", FetchResult)
        extraction = ctx.result("extract", RecetaExtractResult).extraction
        if extraction is None:
            return CoverResult()
        candidates = fetch.images + fetch.keyframes  # mismo orden que se envió al LLM
        index = extraction.portada
        if index is None:
            # sin portada indicada: un post usa su primera imagen; un vídeo, su último fotograma
            # (en los Reels de cocina suele ser el plato terminado)
            if fetch.meta.content_type != ContentType.VIDEO and fetch.images:
                index = 0
            elif fetch.keyframes:
                index = len(candidates) - 1
            else:
                return CoverResult()
        if not 0 <= index < len(candidates):
            log.info("bookmark=%s portada %s fuera de rango (%d imágenes)", ctx.job.bookmark_id, index, len(candidates))
            return CoverResult()
        resize_image(ctx.workdir / candidates[index], ctx.workdir / COVER_NAME, self._settings.image_max_side)
        return CoverResult(path=COVER_NAME)
