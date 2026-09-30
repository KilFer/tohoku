import logging
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from datetime import datetime

from tohoku.cleanup import Cleaner
from tohoku.clients.karakeep import KarakeepClient
from tohoku.clients.ntfy import Notifier
from tohoku.config import Settings
from tohoku.errors import ConfigError
from tohoku.ingest import ingest
from tohoku.pipeline import STAGE_ORDER, Pipeline
from tohoku.sources import classify_url
from tohoku.state import Job, JobStatus, StateStore

log = logging.getLogger(__name__)

REPROCESS_FROM = ("fetch", "classify", "extract", "geocode", "resolve", "publish")
SUMMARY_HOUR = 21


def _local_now() -> datetime:
    return datetime.now().astimezone()


class Service:
    """Bucle principal: preflight, ingest, procesar la cola y resumen diario opcional."""

    def __init__(
        self,
        karakeep: KarakeepClient,
        state: StateStore,
        pipeline: Pipeline,
        notifier: Notifier,
        settings: Settings,
        preflight: Callable[[], None],
        lists: Mapping[str, Sequence[str]],
        clock: Callable[[], datetime] = _local_now,
        cleaner: Cleaner | None = None,
    ) -> None:
        self._karakeep = karakeep
        self._state = state
        self._pipeline = pipeline
        self._notifier = notifier
        self._settings = settings
        self._preflight = preflight
        self._lists = {list_id: list(names) for list_id, names in lists.items()}
        self._clock = clock
        self._cleaner = cleaner
        self._ready = False

    def tick(self) -> None:
        if not self._ready:
            self._preflight()
            self._ready = True
        new: list[str] = []
        unsupported: list[str] = []
        for list_id, candidates in self._lists.items():
            report = ingest(self._karakeep, self._state, list_id, candidates)
            new += report.new
            unsupported += report.unsupported
        processed = self._pipeline.run_due()
        if new or unsupported or processed:
            log.info("sondeo nuevos=%d no_soportados=%d procesados=%d", len(new), len(unsupported), processed)
        if self._cleaner is not None:
            purged = self._cleaner.purge()
            if purged:
                log.info("limpieza jobs=%d (directorios y resultados de etapa caducados)", purged)
        self._maybe_daily_summary()

    def run_forever(self, sleep: Callable[[float], None] = time.sleep) -> None:
        log.info("tohoku en marcha; sondeo cada %d min", self._settings.poll_interval_minutes)
        while True:
            try:
                self.tick()
            except ConfigError as exc:
                self._ready = False
                log.error("error de configuración: %s", exc)
                self._pipeline.notify_once(f"config:{exc}", "tohoku: error de configuración", str(exc))
            except Exception as exc:
                log.exception("error inesperado en el ciclo")
                self._pipeline.notify_once(
                    f"loop:{type(exc).__name__}", "tohoku: error en el ciclo", str(exc)
                )
            sleep(self._settings.poll_interval_minutes * 60)

    def _maybe_daily_summary(self) -> None:
        if not self._settings.ntfy_daily_summary or self._clock().hour < SUMMARY_HOUR:
            return
        if self._state.get_counter("summary_sent") > 0:
            return
        self._state.add_counter("summary_sent", 1)
        counts = self._state.finished_today()
        if counts:
            message = ", ".join(f"{key}: {value}" for key, value in sorted(counts.items()))
            self._notifier.send("tohoku: resumen del día", message, priority=2)


def reprocess(
    state: StateStore, karakeep: KarakeepClient, bookmark_id: str, from_stage: str,
    destination: str | None = None, known: Collection[str] = (),
) -> Job:
    """Vuelve a poner un bookmark en la cola desde la etapa indicada.

    Con `destination` fuerza ese destino y repite desde `classify` (o antes, si `from_stage` es anterior).
    Sin él, reprocesar desde fetch/classify olvida el destino para que se vuelva a clasificar.
    """
    if from_stage not in REPROCESS_FROM:
        raise ValueError(f"etapa no válida: {from_stage}. Opciones: {', '.join(REPROCESS_FROM)}")
    if destination is not None and destination not in known:
        raise ValueError(f"destino desconocido: {destination}. Opciones: {', '.join(sorted(known))}")
    clear_from = from_stage
    if destination is not None and STAGE_ORDER.index(from_stage) > STAGE_ORDER.index("classify"):
        clear_from = "classify"
    if not state.has_job(bookmark_id):
        bookmark = karakeep.get_bookmark(bookmark_id)
        classified = classify_url(bookmark.url) if bookmark.url else None
        platform, hint = classified if classified else (None, None)
        state.add_job(bookmark_id, bookmark.url or "", platform, hint)
    state.reset(bookmark_id)
    state.clear_stages_from(bookmark_id, clear_from, STAGE_ORDER)
    if destination is not None:
        state.set_destination(bookmark_id, destination)
    elif from_stage in ("fetch", "transcribe", "classify"):
        state.set_destination(bookmark_id, None)
    job = state.get_job(bookmark_id)
    assert job is not None
    return job


def format_status(state: StateStore) -> str:
    lines = ["Trabajos:"]
    lines += [f"  {key}: {value}" for key, value in sorted(state.status_counts().items())]
    lines.append(
        f"Consumo de hoy: OpenRouter {state.get_counter('openrouter_usd'):.4f} USD · "
        f"Places {int(state.get_counter('places_calls'))} llamadas"
    )
    retrying = [j for j in state.list_jobs(JobStatus.PENDING, limit=10) if j.last_error]
    if retrying:
        lines.append("Reintentando:")
        lines += [f"  {j.bookmark_id} {j.url} — intento {j.attempts}: {j.last_error}" for j in retrying]
    errors = state.list_jobs(JobStatus.ERROR, limit=10)
    if errors:
        lines.append("Últimos errores:")
        lines += [f"  {j.bookmark_id} {j.url} — {j.last_error}" for j in errors]
    return "\n".join(lines)
