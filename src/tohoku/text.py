import re
import unicodedata
from collections.abc import Sequence
from difflib import SequenceMatcher

_BASE_GENERIC_WORDS = frozenset({"tienda", "store", "shop", "the"})
_generic_words = _BASE_GENERIC_WORDS
_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.S)


def fold(text: str) -> str:
    """Lowercase and accent-free, keeping all words and punctuation."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def configure_generic_words(extra: Sequence[str]) -> None:
    """Words that `normalize_name` ignores in addition to the base ones (e.g. the country name). Global: set by the
    loading of `destinos.yaml` (key `palabras_genericas`), because dedup keys do not depend on the destination."""
    global _generic_words
    _generic_words = _BASE_GENERIC_WORDS | {fold(word).strip() for word in extra if word.strip()}


def label_key(text: str) -> str:
    """Key of a destination name: accent- and case-insensitive, with spaces, hyphens and underscores treated as equivalent.

    Used by the classifier (to recognize the LLM's answer) and by the loading of destinos.yaml (names that
    collide).
    """
    cleaned = fold(text).strip().strip("\"'`«»“”").strip().rstrip(".").strip().strip("\"'`«»“”").strip()
    return re.sub(r"[\s_-]+", "_", cleaned).strip("_")


def normalize_name(text: str) -> str:
    """Lowercase, without accents, punctuation or generic words (dedup key)."""
    cleaned = re.sub(r"[^\w\s]", " ", fold(text))
    return " ".join(word for word in cleaned.split() if word not in _generic_words)


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def strip_fences(text: str) -> str:
    """Strips a ```json ... ``` block if the model wraps the JSON in one."""
    stripped = text.strip()
    match = _FENCE.match(stripped)
    return match.group(1) if match else stripped
