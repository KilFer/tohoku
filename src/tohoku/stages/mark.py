from tohoku.clients.karakeep import KarakeepClient
from tohoku.models import MarkResult, Outcome

OUTCOME_TAGS: dict[Outcome, str] = {
    Outcome.PROCESADO: "jr:procesado",
    Outcome.REVISAR: "jr:revisar",
    Outcome.NO_JAPON: "jr:no-japon",
    Outcome.ERROR: "jr:error",
}


class MarkStage:
    """Etapa 8: etiqueta el bookmark con el resultado y lo archiva (salvo error)."""

    name = "mark"

    def __init__(self, karakeep: KarakeepClient) -> None:
        self._karakeep = karakeep

    def run(self, bookmark_id: str, outcome: Outcome) -> MarkResult:
        tag = OUTCOME_TAGS[outcome]
        bookmark = self._karakeep.get_bookmark(bookmark_id)
        stale = [t for t in bookmark.tags if t.startswith("jr:") and t != tag]
        if stale:
            self._karakeep.detach_tags(bookmark_id, stale)
        self._karakeep.attach_tags(bookmark_id, [tag])
        archive = outcome != Outcome.ERROR
        if archive:
            self._karakeep.set_archived(bookmark_id, True)
        return MarkResult(tag=tag, archived=archive)
