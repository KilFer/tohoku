from typing import Literal, Protocol

from tohoku.config import Thresholds
from tohoku.models import Outcome, PublishedNote

DestinationDecision = Literal["no", "uncertain", "yes"]


class HasDestinationConfidence(Protocol):
    """Any extraction (viaje, receta...) that reports `confianza_destino`."""

    confianza_destino: float


def destination_decision(extraction: HasDestinationConfidence, th: Thresholds) -> DestinationDecision:
    """Classifies using `confianza_destino`: is the content about the destination?"""
    if extraction.confianza_destino < th.destination_min:
        return "no"
    if extraction.confianza_destino < th.destination_review:
        return "uncertain"
    return "yes"


def decide_outcome(decision: DestinationDecision, notes: list[PublishedNote]) -> Outcome:
    if decision == "no":
        return Outcome.DESCARTADO
    if any(note.review_reasons for note in notes):
        return Outcome.REVISAR
    return Outcome.PROCESADO
