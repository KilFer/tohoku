import logging

from pydantic import ValidationError

from tohoku.clients.openrouter import OpenRouterClient, image_part
from tohoku.config import Settings
from tohoku.context import JobContext
from tohoku.flows.viaje.params import ViajeParams
from tohoku.flows.viaje.prompt import extraction_schema, invalid_categories
from tohoku.models import Extraction, ExtractResult, FetchResult, Transcript
from tohoku.quota import DailyQuota
from tohoku.text import strip_fences

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
        cost = 0.0
        error = ""
        for _ in range(2):
            self._budget.check()
            result = self._llm.chat_json(model, messages, schema, "extraction")
            self._budget.add(result.cost_usd)
            cost += result.cost_usd
            try:
                extraction = Extraction.model_validate_json(strip_fences(result.content))
                problems = invalid_categories(extraction, self._params)
            except ValidationError as exc:
                problems = [str(exc)]
            if problems:
                error = "\n".join(problems)
                messages = [
                    *messages,
                    {"role": "assistant", "content": result.content},
                    {"role": "user", "content": f"La respuesta no cumple el esquema:\n{error}\nDevuelve únicamente el JSON corregido."},
                ]
                continue
            log.info(
                "bookmark=%s extraccion relevancia=%.2f lugares=%d cosas=%d otros=%d coste=%.4f",
                ctx.job.bookmark_id, extraction.confianza_destino, len(extraction.lugares),
                len(extraction.cosas), len(extraction.otros), cost,
            )
            return ExtractResult(extraction=extraction, cost_usd=cost)
        log.warning("bookmark=%s extraccion fallida: %s", ctx.job.bookmark_id, error[:200])
        return ExtractResult(extraction=None, error=error, cost_usd=cost)
