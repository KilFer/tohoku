import json
import re
from pathlib import Path

from pydantic import BaseModel, ValidationError

from tohoku.classify.base import Candidate, ClassifierError, Verdict
from tohoku.clients.openrouter import OpenRouterClient, image_part
from tohoku.prompts import load_prompt
from tohoku.text import strip_fences, fold

NINGUNO = "ninguno"
_LABEL_SUFFIX = "Responde únicamente con el nombre del destino (o `ninguno`), sin nada más."


def _key(text: str) -> str:
    """Clave de comparación: sin acentos/mayúsculas, espacios, guiones y guiones bajos equivalentes."""
    cleaned = fold(text).strip().strip("\"'`«»“”").strip().rstrip(".").strip().strip("\"'`«»“”").strip()
    return re.sub(r"[\s_-]+", "_", cleaned).strip("_")


def _resolve(raw: str, candidates: list[Candidate]) -> tuple[str | None, bool]:
    """(nombre exacto o None, reconocido). `ninguno` -> (None, True); desconocido -> (None, False)."""
    key = _key(raw)
    if key == NINGUNO:
        return None, True
    for candidate in candidates:
        if _key(candidate.nombre) == key:
            return candidate.nombre, True
    return None, False


class _Reply(BaseModel):
    destino: str
    confianza: float = 1.0
    alternativa: str | None = None
    confianza_alternativa: float = 0.0


def _messages(system: str, text: str, images: list[Path], candidates: list[Candidate], feedback: str | None) -> list[dict]:
    listing = "\n".join(f"- {c.nombre}: {c.descripcion}" for c in candidates)
    body = f"Destinos posibles:\n{listing}\n\nContenido:\n{text}"
    content = [{"type": "text", "text": body}, *(image_part(path) for path in images)]
    messages = [{"role": "system", "content": system}, {"role": "user", "content": content}]
    if feedback is not None:
        messages.append({"role": "user", "content": f"Tu respuesta anterior no es válida: {feedback}"})
    return messages


class JsonSchemaClassifier:
    def __init__(self, llm: OpenRouterClient, model: str) -> None:
        self._llm = llm
        self._model = model

    def classify(self, text: str, images: list[Path], candidates: list[Candidate], feedback: str | None = None) -> Verdict:
        names = [c.nombre for c in candidates]
        schema = {
            "type": "object",
            "properties": {
                "destino": {"type": "string", "enum": [*names, NINGUNO]},
                "confianza": {"type": "number"},
                "alternativa": {"enum": [*names, None]},
                "confianza_alternativa": {"type": "number"},
            },
            "required": ["destino", "confianza", "alternativa", "confianza_alternativa"],
        }
        messages = _messages(load_prompt("classify"), text, images, candidates, feedback)
        result = self._llm.chat_json(self._model, messages, schema, "clasificacion")
        try:
            reply = _Reply.model_validate(json.loads(strip_fences(result.content)))
        except (ValueError, ValidationError) as exc:
            raise ClassifierError(f"respuesta no válida: {exc}", result.content, result.cost_usd) from exc
        destino, known = _resolve(reply.destino, candidates)
        if not known:
            destino = reply.destino  # ClassifyStage lo rechaza y reintenta
        alternativa = _resolve(reply.alternativa, candidates)[0] if reply.alternativa is not None else None
        return Verdict(
            destino=destino,
            confianza=reply.confianza,
            alternativa=alternativa,
            confianza_alternativa=reply.confianza_alternativa,
            cost_usd=result.cost_usd,
        )


class LabelClassifier:
    def __init__(self, llm: OpenRouterClient, model: str) -> None:
        self._llm = llm
        self._model = model

    def classify(self, text: str, images: list[Path], candidates: list[Candidate], feedback: str | None = None) -> Verdict:
        system = f"{load_prompt('classify').rstrip()}\n\n{_LABEL_SUFFIX}"
        result = self._llm.chat_text(self._model, _messages(system, text, images, candidates, feedback))
        destino, known = _resolve(result.content, candidates)
        if known:
            return Verdict(destino=destino, cost_usd=result.cost_usd)
        raise ClassifierError(f"destino desconocido: {result.content!r}", result.content, result.cost_usd)
