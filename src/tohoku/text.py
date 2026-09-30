import re
import unicodedata
from difflib import SequenceMatcher

_GENERIC_WORDS = {"japan", "japon", "tienda", "store", "shop", "the"}
_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.S)


def fold(text: str) -> str:
    """Minúsculas y sin acentos, conservando todas las palabras y la puntuación."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def label_key(text: str) -> str:
    """Clave de un nombre de destino: sin acentos/mayúsculas, espacios, guiones y guiones bajos equivalentes.

    La usan el clasificador (para reconocer la respuesta del LLM) y la carga de destinos.yaml (nombres que
    colisionan).
    """
    cleaned = fold(text).strip().strip("\"'`«»“”").strip().rstrip(".").strip().strip("\"'`«»“”").strip()
    return re.sub(r"[\s_-]+", "_", cleaned).strip("_")


def normalize_name(text: str) -> str:
    """Minúsculas, sin acentos ni puntuación y sin palabras genéricas (clave de deduplicación)."""
    cleaned = re.sub(r"[^\w\s]", " ", fold(text))
    return " ".join(word for word in cleaned.split() if word not in _GENERIC_WORDS)


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def strip_fences(text: str) -> str:
    """Quita un bloque ```json ... ``` si el modelo lo añade alrededor del JSON."""
    stripped = text.strip()
    match = _FENCE.match(stripped)
    return match.group(1) if match else stripped
