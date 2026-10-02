from typing import Literal, Protocol

from tohoku.config import Thresholds
from tohoku.models import Outcome, PublishedNote

DestinationDecision = Literal["no", "uncertain", "yes"]


class HasDestinationConfidence(Protocol):
    """Cualquier extracción (viaje, receta…) que informe de `confianza_destino`."""

    confianza_destino: float


def destination_decision(extraction: HasDestinationConfidence, th: Thresholds) -> DestinationDecision:
    """Clasifica con `confianza_destino`: ¿trata el contenido sobre el destino?"""
    if extraction.confianza_destino < th.japan_min:
        return "no"
    if extraction.confianza_destino < th.japan_review:
        return "uncertain"
    return "yes"


def decide_outcome(decision: DestinationDecision, notes: list[PublishedNote]) -> Outcome:
    if decision == "no":
        return Outcome.DESCARTADO
    if any(note.review_reasons for note in notes):
        return Outcome.REVISAR
    return Outcome.PROCESADO
