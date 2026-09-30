import logging
from dataclasses import dataclass, field

from tohoku.clients.karakeep import KarakeepClient
from tohoku.errors import ApiError, ConfigError
from tohoku.sources import classify_url
from tohoku.state import StateStore

log = logging.getLogger(__name__)

JR_TAG_PREFIX = "jr:"


@dataclass
class IngestReport:
    new: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)


def ingest(karakeep: KarakeepClient, state: StateStore, list_id: str) -> IngestReport:
    """Crea un job por cada bookmark nuevo de la lista. Etapa 1 del pipeline."""
    try:
        bookmarks = list(karakeep.list_bookmarks(list_id))
    except ApiError as exc:
        if exc.status == 404:
            raise ConfigError(f"No existe la lista de Karakeep {list_id} (config/destinos.yaml)") from exc
        raise

    report = IngestReport()
    for bookmark in bookmarks:
        if state.has_job(bookmark.id) or any(tag.startswith(JR_TAG_PREFIX) for tag in bookmark.tags):
            continue
        if not bookmark.url:
            # No es un enlace (nota de texto, imagen suelta...): no hay nada que procesar.
            log.debug("bookmark=%s no es un enlace; se ignora", bookmark.id)
            continue
        classified = classify_url(bookmark.url)
        if classified is None:
            state.add_job(bookmark.id, bookmark.url, None, None)
            report.unsupported.append(bookmark.id)
            log.info("bookmark=%s fuente no soportada url=%s", bookmark.id, bookmark.url)
            continue
        state.add_job(bookmark.id, bookmark.url, *classified)
        report.new.append(bookmark.id)
        log.info("bookmark=%s nuevo job url=%s", bookmark.id, bookmark.url)
    return report
