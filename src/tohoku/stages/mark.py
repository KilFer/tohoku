from tohoku.clients.karakeep import KarakeepClient
from tohoku.models import MarkResult, Outcome

OUTCOME_TAGS: dict[Outcome, str] = {
    Outcome.PROCESADO: "jr:procesado",
    Outcome.REVISAR: "jr:revisar",
    Outcome.DESCARTADO: "jr:descartado",
    Outcome.ERROR: "jr:error",
}
DESTINATION_TAG_PREFIX = "jr:destino:"


class MarkStage:
    """Etapa 8: etiqueta el bookmark con el resultado y lo archiva (salvo error)."""

    name = "mark"

    def __init__(self, karakeep: KarakeepClient) -> None:
        self._karakeep = karakeep

    def run(self, bookmark_id: str, outcome: Outcome, destination: str | None = None) -> MarkResult:
        tag = OUTCOME_TAGS[outcome]
        destination_tag = f"{DESTINATION_TAG_PREFIX}{destination}" if destination else None
        wanted = [tag] + ([destination_tag] if destination_tag else [])
        bookmark = self._karakeep.get_bookmark(bookmark_id)
        stale = [t for t in bookmark.tags if t.startswith("jr:") and t not in wanted]
        if stale:
            self._karakeep.detach_tags(bookmark_id, stale)
        self._karakeep.attach_tags(bookmark_id, wanted)
        archive = outcome != Outcome.ERROR
        if archive:
            self._karakeep.set_archived(bookmark_id, True)
        return MarkResult(tag=tag, archived=archive, destination_tag=destination_tag)
