from typing import Literal

from japan_reader.config import Thresholds
from japan_reader.models import Extraction, Outcome, PublishedNote

JapanDecision = Literal["no", "uncertain", "yes"]


def japan_decision(extraction: Extraction, th: Thresholds) -> JapanDecision:
    """Clasifica con `confianza_japon` (spec §7)."""
    if extraction.confianza_japon < th.japan_min:
        return "no"
    if extraction.confianza_japon < th.japan_review:
        return "uncertain"
    return "yes"


def decide_outcome(decision: JapanDecision, notes: list[PublishedNote]) -> Outcome:
    if decision == "no":
        return Outcome.NO_JAPON
    if any(note.review_reasons for note in notes):
        return Outcome.REVISAR
    return Outcome.PROCESADO
