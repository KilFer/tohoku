import logging

from tohoku.clients.openrouter import OpenRouterClient, image_part
from tohoku.config import Settings
from tohoku.context import JobContext
from tohoku.flows.viaje.params import ViajeParams
from tohoku.flows.viaje.prompt import extraction_schema, invalid_categories
from tohoku.llm_json import structured_call
from tohoku.models import Extraction, ExtractResult, FetchResult, Transcript
from tohoku.quota import DailyQuota

log = logging.getLogger(__name__)


def build_user_text(fetch: FetchResult, transcript: Transcript) -> str:
    meta = fetch.meta
    lines = [f"Plataforma: {meta.platform}", f"Tipo de contenido: {meta.content_type}"]
    if meta.title:
        lines.append(f"Título: {meta.title}")
    if meta.author:
        lines.append(f"Autor: {meta.author}")
    if meta.published:
        lines.append(f"Fecha: {meta.published}")
    if meta.hashtags:
        lines.append("Hashtags: " + " ".join(f"#{tag}" for tag in meta.hashtags))
    lines.append("Descripción / caption:\n" + (meta.description or "(vacía)"))
    lines.append("Transcripción del audio:\n" + (transcript.text or "(sin audio o sin transcripción)"))
    if fetch.images or fetch.keyframes:
        lines.append(
            f"Se adjuntan {len(fetch.images)} imágenes del post y {len(fetch.keyframes)} fotogramas clave del vídeo. "
            "Lee el texto que aparezca en ellas."
        )
    return "\n\n".join(lines)


class ExtractStage:
    """Etapa 4: clasificación y extracción estructurada con un LLM multimodal."""

    name = "extract"
    needs_files = True  # usa los ficheros del job: si la limpieza los borró, el pipeline vuelve a descargar
    result_model = ExtractResult

    def __init__(
        self, settings: Settings, llm: OpenRouterClient, budget: DailyQuota, system_prompt: str,
        params: ViajeParams | None = None,
    ) -> None:
        self._settings = settings
        self._llm = llm
        self._budget = budget
        self.system_prompt = system_prompt
        self._params = params or ViajeParams()

    def run(self, ctx: JobContext) -> ExtractResult:
        fetch = ctx.result("fetch", FetchResult)
        transcript = ctx.result("transcribe", Transcript)
        image_paths = [ctx.workdir / rel for rel in fetch.images + fetch.keyframes]
        model = self._settings.openrouter_model if image_paths else self._settings.text_model
        content = [{"type": "text", "text": build_user_text(fetch, transcript)}] + [image_part(p) for p in image_paths]
        messages: list[dict] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": content},
        ]
        schema = extraction_schema(self._params)
        outcome = structured_call(
            self._llm, self._budget, model, messages, schema, "extraction",
            parse=Extraction.model_validate_json, check=lambda e: invalid_categories(e, self._params),
        )
        extraction = outcome.value
        if extraction is None:
            log.warning("bookmark=%s extraccion fallida: %s", ctx.job.bookmark_id, outcome.error[:200])
            return ExtractResult(extraction=None, error=outcome.error, cost_usd=outcome.cost_usd)
        log.info(
            "bookmark=%s extraccion relevancia=%.2f lugares=%d cosas=%d otros=%d coste=%.4f",
            ctx.job.bookmark_id, extraction.confianza_destino, len(extraction.lugares),
            len(extraction.cosas), len(extraction.otros), outcome.cost_usd,
        )
        return ExtractResult(extraction=extraction, cost_usd=outcome.cost_usd)
