import logging
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from tohoku.cleanup import Cleaner
from tohoku.clients.ntfy import Notifier
from tohoku.context import JobContext
from tohoku.errors import ConfigError, TohokuError, PermanentError, QuotaExceeded
from tohoku.models import Classification, FetchResult, Outcome, PublishResult
from tohoku.stages.mark import MarkStage
from tohoku.state import Job, StateStore, next_quota_reset, utcnow

log = logging.getLogger(__name__)

STAGE_ORDER = ("fetch", "transcribe", "classify", "extract", "geocode", "cover", "resolve", "publish")
COMMON_STAGES = ("fetch", "transcribe", "classify")  # common stretch; the rest comes from the destination's flow
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
    """Runs each job's stages in order, persisting every result and applying the error policy.

    Without `flows`, `stages` is the full list. With `flows`, `stages` is the common stretch (ending at `classify`) and
    then the stages of the chosen destination (`flows[destino]`) run.
    """

    def __init__(
        self,
        state: StateStore,
        stages: Sequence[Stage],
        mark: MarkStage,
        notifier: Notifier,
        data_dir: Path,
        clock: Callable[[], datetime] = utcnow,
        flows: Mapping[str, Sequence[Stage]] | None = None,
        cleaner: Cleaner | None = None,
    ) -> None:
        self._state = state
        self._stages = list(stages)
        self._mark = mark
        self._notifier = notifier
        self._data_dir = data_dir
        self._clock = clock
        self._flows = {name: list(stages) for name, stages in flows.items()} if flows is not None else None
        self._cleaner = cleaner
        self._fetch = next((stage for stage in self._stages if stage.name == "fetch"), None)

    def run_due(self) -> int:
        """Processes the pending jobs. A job that exhausts a daily quota waits for it to renew; the others carry on.

        `DailyQuota.check()` only reads a local counter: jobs that later reach a stage with the
        quota exhausted are parked without calling the API, and those that do not need it (cache, stages without quota) move on.
        """
        jobs = self._state.due_jobs()
        for job in jobs:
            self.run_job(job)
        return len(jobs)

    def run_job(self, job: Job) -> None:
        """Runs a job to the end or to the first error, applying the error policy."""
        if job.platform is None:
            self.mark_failed(job.bookmark_id, "fuente no soportada")
            return
        ctx = JobContext(job=job, workdir=self._data_dir / "jobs" / job.bookmark_id)
        try:
            ctx.workdir.mkdir(parents=True, exist_ok=True)
            self._run_stages(ctx, self._stages)
            destination = None
            if self._flows is not None:
                decision = ctx.result("classify", Classification)
                if decision.destino is None:
                    self._finish(job.bookmark_id, Outcome.DESCARTADO, None)
                    return
                if decision.destino not in self._flows:
                    # Only this job: a destination removed from the YAML must not stop the whole queue.
                    raise PermanentError(
                        f"El destino '{decision.destino}' del job {job.bookmark_id} ya no existe en config/destinos.yaml"
                    )
                destination = decision.destino
                self._state.set_destination(job.bookmark_id, destination)
                self._run_stages(ctx, self._flows[destination])
            outcome = ctx.result("publish", PublishResult).outcome
            # A DESCARTADO (discarded) job never carries jr:destino:<d> (the flow discarded it: it does not belong to that destination).
            self._finish(job.bookmark_id, outcome, None if outcome == Outcome.DESCARTADO else destination)
        except ConfigError:
            raise
        except QuotaExceeded as exc:
            resume_at = self._tomorrow()
            self._state.schedule_retry(job.bookmark_id, resume_at, str(exc), count_attempt=False)
            log.info("bookmark=%s aparcado por cuota %s hasta %s", job.bookmark_id, exc.key, resume_at.isoformat())
            self.notify_once(f"quota:{exc.key}", "tohoku: límite diario alcanzado", f"{exc}. Se reanuda mañana.")
        except PermanentError as exc:
            self.mark_failed(job.bookmark_id, str(exc))
        except Exception as exc:
            log.exception("bookmark=%s fallo en el intento %d", job.bookmark_id, job.attempts + 1)
            attempt = job.attempts + 1
            if attempt > len(BACKOFF):
                self.mark_failed(job.bookmark_id, f"agotados los reintentos: {exc}")
            else:
                self._state.schedule_retry(job.bookmark_id, self._clock() + BACKOFF[attempt - 1], str(exc))

    def _run_stages(self, ctx: JobContext, stages: Sequence[Stage]) -> None:
        """Loads each stage's saved result, or runs it and saves the result."""
        bookmark_id = ctx.job.bookmark_id
        for stage in stages:
            result = self._state.load_stage(bookmark_id, stage.name, stage.result_model)
            if result is None:
                if self._needs_files(stage, ctx):
                    self._refetch_if_purged(ctx)
                log.info("bookmark=%s etapa=%s", bookmark_id, stage.name)
                result = stage.run(ctx)
                self._state.save_stage(bookmark_id, stage.name, result)
            ctx.results[stage.name] = result

    @staticmethod
    def _needs_files(stage: Stage, ctx: JobContext) -> bool:
        """`needs_files_for(ctx)` if the stage has it (depends on the job, e.g. classify); otherwise `needs_files`."""
        needs_files_for = getattr(stage, "needs_files_for", None)
        if callable(needs_files_for):
            return bool(needs_files_for(ctx))
        return bool(getattr(stage, "needs_files", False))

    def _refetch_if_purged(self, ctx: JobContext) -> None:
        """If cleanup deleted the fetch files, downloads again before a stage that needs them.

        The new result no longer has `files_purged`, so within the same job it downloads at most once.
        """
        fetched = ctx.results.get("fetch")
        if self._fetch is None or not isinstance(fetched, FetchResult) or not fetched.files_purged:
            return
        bookmark_id = ctx.job.bookmark_id
        log.info("bookmark=%s re-descarga: los ficheros se limpiaron", bookmark_id)
        result = self._fetch.run(ctx)
        self._state.save_stage(bookmark_id, self._fetch.name, result)
        ctx.results[self._fetch.name] = result

    def _mark_run(self, bookmark_id: str, outcome: Outcome, destination: str | None) -> None:
        if destination is None:
            self._mark.run(bookmark_id, outcome)
        else:
            self._mark.run(bookmark_id, outcome, destination)

    def _finish(self, bookmark_id: str, outcome: Outcome, destination: str | None) -> None:
        self._mark_run(bookmark_id, outcome, destination)
        self._state.finish(bookmark_id, outcome)
        log.info("bookmark=%s terminado resultado=%s destino=%s", bookmark_id, outcome, destination)
        self._cleanup(bookmark_id, outcome)

    def _cleanup(self, bookmark_id: str, outcome: Outcome) -> None:
        """Cleanup never changes the job's result: a disk failure is only logged."""
        if self._cleaner is None:
            return
        try:
            self._cleaner.job_finished(bookmark_id, outcome)
        except OSError as exc:
            log.warning("bookmark=%s no se pudo limpiar: %s", bookmark_id, exc)

    def mark_failed(self, bookmark_id: str, reason: str) -> None:
        job = self._state.get_job(bookmark_id)
        try:
            self._mark_run(bookmark_id, Outcome.ERROR, job.destination if job else None)
        except TohokuError as exc:
            log.warning("bookmark=%s no se pudo etiquetar jr:error: %s", bookmark_id, exc)
        self._state.finish(bookmark_id, Outcome.ERROR, reason)
        self._cleanup(bookmark_id, Outcome.ERROR)  # deletes nothing: the files are useful for diagnosis
        url = job.url if job else bookmark_id
        log.warning("bookmark=%s error definitivo: %s", bookmark_id, reason)
        self._notifier.send("tohoku: error", f"{url}\n{reason}", priority=4, tags=["warning"])

    def notify_once(self, key: str, title: str, message: str) -> None:
        """One notification per key and day."""
        counter = f"alert:{key}"
        if self._state.get_counter(counter) == 0:
            self._state.add_counter(counter, 1)
            self._notifier.send(title, message, priority=4, tags=["warning"])

    def _tomorrow(self) -> datetime:
        """When the quotas renew (Pacific midnight, like Google)."""
        return next_quota_reset(self._clock())
