import logging

from pydantic import BaseModel

from tohoku.clients.openrouter import OpenRouterClient, image_part
from tohoku.config import Settings
from tohoku.context import JobContext
from tohoku.flows.receta.models import RecetaExtraction
from tohoku.llm_json import structured_call
from tohoku.models import FetchResult, Transcript
from tohoku.quota import DailyQuota
from tohoku.stages.extract import build_user_text

log = logging.getLogger(__name__)


class RecetaExtractResult(BaseModel):
    extraction: RecetaExtraction | None = None
    error: str | None = None
    cost_usd: float = 0.0


class RecetaExtractStage:
    """Extracción estructurada de una receta con un LLM multimodal."""

    name = "extract"
    needs_files = True  # usa los ficheros del job: si la limpieza los borró, el pipeline vuelve a descargar
    result_model = RecetaExtractResult

    def __init__(self, settings: Settings, llm: OpenRouterClient, budget: DailyQuota, system_prompt: str) -> None:
        self._settings = settings
        self._llm = llm
        self._budget = budget
        self.system_prompt = system_prompt

    def run(self, ctx: JobContext) -> RecetaExtractResult:
        fetch = ctx.result("fetch", FetchResult)
        transcript = ctx.result("transcribe", Transcript)
        # `portada` indexa esta lista: imágenes del post primero, después los fotogramas
        image_paths = [ctx.workdir / rel for rel in fetch.images + fetch.keyframes]
        model = self._settings.openrouter_model if image_paths else self._settings.text_model
        content = [{"type": "text", "text": build_user_text(fetch, transcript)}] + [image_part(p) for p in image_paths]
        messages: list[dict] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": content},
        ]
        outcome = structured_call(
            self._llm, self._budget, model, messages, RecetaExtraction.model_json_schema(), "receta",
            parse=RecetaExtraction.model_validate_json,
        )
        extraction = outcome.value
        if extraction is None:
            log.warning("bookmark=%s extraccion de receta fallida: %s", ctx.job.bookmark_id, outcome.error[:200])
            return RecetaExtractResult(extraction=None, error=outcome.error, cost_usd=outcome.cost_usd)
        log.info(
            "bookmark=%s receta relevancia=%.2f ingredientes=%d pasos=%d coste=%.4f",
            ctx.job.bookmark_id, extraction.confianza_destino, len(extraction.ingredientes),
            len(extraction.pasos), outcome.cost_usd,
        )
        return RecetaExtractResult(extraction=extraction, cost_usd=outcome.cost_usd)
