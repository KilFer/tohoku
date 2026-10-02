import logging
from collections.abc import Sequence
from dataclasses import dataclass, field

from tohoku.clients.karakeep import KarakeepClient
from tohoku.errors import ApiError, ConfigError
from tohoku.sources import classify_url
from tohoku.state import JobStatus, StateStore

log = logging.getLogger(__name__)

JR_TAG_PREFIX = "jr:"


@dataclass
class IngestReport:
    new: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)


def ingest(karakeep: KarakeepClient, state: StateStore, list_id: str, candidates: Sequence[str]) -> IngestReport:
    """Creates a job for each new bookmark in the list. Pipeline stage 1."""
    try:
        bookmarks = list(karakeep.list_bookmarks(list_id))
    except ApiError as exc:
        if exc.status == 404:
            raise ConfigError(f"No existe la lista de Karakeep {list_id} (config/destinos.yaml)") from exc
        raise

    report = IngestReport()
    for bookmark in bookmarks:
        existing = state.get_job(bookmark.id)
        if existing is not None:
            # Same bookmark in another list: candidates accumulate while the destination is undecided.
            if existing.status == JobStatus.PENDING and existing.destination is None:
                state.add_candidates(bookmark.id, candidates)
            continue
        if any(tag.startswith(JR_TAG_PREFIX) for tag in bookmark.tags):
            continue
        if not bookmark.url:
            # Not a link (text note, standalone image...): nothing to process.
            log.debug("bookmark=%s no es un enlace; se ignora", bookmark.id)
            continue
        classified = classify_url(bookmark.url)
        if classified is None:
            state.add_job(bookmark.id, bookmark.url, None, None, candidates=candidates)
            report.unsupported.append(bookmark.id)
            log.info("bookmark=%s fuente no soportada url=%s", bookmark.id, bookmark.url)
            continue
        state.add_job(bookmark.id, bookmark.url, *classified, candidates=candidates)
        report.new.append(bookmark.id)
        log.info("bookmark=%s nuevo job url=%s", bookmark.id, bookmark.url)
    return report
