import logging
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from japan_reader.clients.ntfy import Notifier
from japan_reader.context import JobContext
from japan_reader.errors import ConfigError, JapanReaderError, PermanentError, QuotaExceeded
from japan_reader.models import Outcome, PublishResult
from japan_reader.stages.mark import MarkStage
from japan_reader.state import Job, StateStore, utcnow

log = logging.getLogger(__name__)

STAGE_ORDER = ("fetch", "transcribe", "extract", "geocode", "resolve", "publish")
BACKOFF = (
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=30),
    timedelta(hours=2),
    timedelta(hours=2),
)


class Stage(Protocol):
    name: str
    result_model: type[BaseModel]

    def run(self, ctx: JobContext) -> BaseModel: ...


class Pipeline:
    """Ejecuta las etapas de cada job en orden, persistiendo cada resultado y aplicando la política de errores."""

    def __init__(
        self,
        state: StateStore,
        stages: Sequence[Stage],
        mark: MarkStage,
        notifier: Notifier,
        data_dir: Path,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._state = state
        self._stages = list(stages)
        self._mark = mark
        self._notifier = notifier
        self._data_dir = data_dir
        self._clock = clock

    def run_due(self) -> int:
        jobs = self._state.due_jobs()
        for job in jobs:
            self.run_job(job)
        return len(jobs)

    def run_job(self, job: Job) -> None:
        if job.platform is None:
            self.mark_failed(job.bookmark_id, "fuente no soportada")
            return
        ctx = JobContext(job=job, workdir=self._data_dir / "jobs" / job.bookmark_id)
        ctx.workdir.mkdir(parents=True, exist_ok=True)
        try:
            for stage in self._stages:
                result = self._state.load_stage(job.bookmark_id, stage.name, stage.result_model)
                if result is None:
                    log.info("bookmark=%s etapa=%s", job.bookmark_id, stage.name)
                    result = stage.run(ctx)
                    self._state.save_stage(job.bookmark_id, stage.name, result)
                ctx.results[stage.name] = result
            outcome = ctx.result("publish", PublishResult).outcome
            self._mark.run(job.bookmark_id, outcome)
            self._state.finish(job.bookmark_id, outcome)
            log.info("bookmark=%s terminado resultado=%s", job.bookmark_id, outcome)
        except ConfigError:
            raise
        except QuotaExceeded as exc:
            self._state.schedule_retry(job.bookmark_id, self._tomorrow(), str(exc), count_attempt=False)
            self.notify_once(f"quota:{exc}", "japan-reader: límite diario alcanzado", f"{exc}. Se reanuda mañana.")
        except PermanentError as exc:
            self.mark_failed(job.bookmark_id, str(exc))
        except Exception as exc:
            log.exception("bookmark=%s fallo en el intento %d", job.bookmark_id, job.attempts + 1)
            attempt = job.attempts + 1
            if attempt > len(BACKOFF):
                self.mark_failed(job.bookmark_id, f"agotados los reintentos: {exc}")
            else:
                self._state.schedule_retry(job.bookmark_id, self._clock() + BACKOFF[attempt - 1], str(exc))

    def mark_failed(self, bookmark_id: str, reason: str) -> None:
        job = self._state.get_job(bookmark_id)
        try:
            self._mark.run(bookmark_id, Outcome.ERROR)
        except JapanReaderError as exc:
            log.warning("bookmark=%s no se pudo etiquetar jr:error: %s", bookmark_id, exc)
        self._state.finish(bookmark_id, Outcome.ERROR, reason)
        url = job.url if job else bookmark_id
        log.warning("bookmark=%s error definitivo: %s", bookmark_id, reason)
        self._notifier.send("japan-reader: error", f"{url}\n{reason}", priority=4, tags=["warning"])

    def notify_once(self, key: str, title: str, message: str) -> None:
        """Un aviso por clave y día."""
        counter = f"alert:{key}"
        if self._state.get_counter(counter) == 0:
            self._state.add_counter(counter, 1)
            self._notifier.send(title, message, priority=4, tags=["warning"])

    def _tomorrow(self) -> datetime:
        return (self._clock() + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
