from typing import Literal

from tohoku.config import Thresholds
from tohoku.models import Extraction, Outcome, PublishedNote

DestinationDecision = Literal["no", "uncertain", "yes"]


def destination_decision(extraction: Extraction, th: Thresholds) -> DestinationDecision:
    """Clasifica con `confianza_destino` (spec §7): ¿trata el contenido sobre el destino?"""
    if extraction.confianza_destino < th.japan_min:
        return "no"
    if extraction.confianza_destino < th.japan_review:
        return "uncertain"
    return "yes"


def decide_outcome(decision: DestinationDecision, notes: list[PublishedNote]) -> Outcome:
    if decision == "no":
        return Outcome.NO_JAPON
    if any(note.review_reasons for note in notes):
        return Outcome.REVISAR
    return Outcome.PROCESADO
