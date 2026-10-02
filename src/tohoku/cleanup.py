"""Two-level cleanup: job files when it finishes, and stage results once the retention period has passed.

Never touches the `jobs` or `published` tables (needed for the review tray and for reprocessing without duplicates).
Only deletes directories inside `data_dir/jobs` whose name is the id of a finished (`done`) job.
"""
import logging
import shutil
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from tohoku.models import Outcome
from tohoku.state import StateStore, utcnow

log = logging.getLogger(__name__)


class Cleaner:
    def __init__(
        self, state: StateStore, data_dir: Path, retencion_dias: int, clock: Callable[[], datetime] = utcnow
    ) -> None:
        self._state = state
        self._jobs_dir = data_dir / "jobs"
        self._retention = timedelta(days=retencion_dias)
        self._clock = clock

    def job_finished(self, bookmark_id: str, outcome: Outcome) -> None:
        """After finishing: unless it is ERROR, deletes data/jobs/<id>/ and flags fetch with `files_purged`; with retention 0, deletes all results."""
        if outcome == Outcome.ERROR:
            return
        self._remove_dir(bookmark_id)
        # Without the directory the fetch files no longer exist, but their metadata is still useful (publish). Only the stages
        # that need files (`needs_files`) download again.
        if self._retention:
            self._state.mark_fetch_purged(bookmark_id)
        else:
            self._state.delete_stages(bookmark_id)

    def purge(self) -> int:
        """Once per pass: stage results of DONE jobs older than the retention period, and directories of DONE jobs still on disk. Returns how many jobs it touched."""
        touched = set(self._state.purge_stage_results(self._clock() - self._retention))
        if self._jobs_dir.is_dir():
            done = self._state.done_job_ids()
            for entry in self._jobs_dir.iterdir():
                if entry.name in done and entry.is_dir() and not entry.is_symlink():
                    if self._remove_dir(entry.name):
                        self._state.mark_fetch_purged(entry.name)  # as in job_finished: its files no longer exist
                        touched.add(entry.name)
        return len(touched)

    def _remove_dir(self, bookmark_id: str) -> bool:
        """Deletes data/jobs/<id>/ if it exists and it is safe. Returns whether it deleted it."""
        path = self._safe_job_dir(bookmark_id)
        if path is None or not path.is_dir():
            return False
        try:
            shutil.rmtree(path, ignore_errors=False)
        except OSError as exc:
            log.warning("bookmark=%s no se pudo borrar %s: %s", bookmark_id, path, exc)
            return False
        return True

    def _safe_job_dir(self, bookmark_id: str) -> Path | None:
        """The job path, only if the id is a plain name and it stays inside data/jobs (no symlinks)."""
        if not bookmark_id or bookmark_id in (".", "..") or "/" in bookmark_id or "\\" in bookmark_id or "\0" in bookmark_id:
            log.warning("bookmark=%r id no seguro para borrar su directorio; se omite", bookmark_id)
            return None
        path = self._jobs_dir / bookmark_id
        if path.is_symlink():
            log.warning("bookmark=%s %s es un enlace simbólico; no se borra", bookmark_id, path)
            return None
        try:
            if path.resolve().parent != self._jobs_dir.resolve():
                log.warning("bookmark=%s %s queda fuera de %s; no se borra", bookmark_id, path, self._jobs_dir)
                return None
        except OSError as exc:
            log.warning("bookmark=%s no se pudo resolver %s: %s", bookmark_id, path, exc)
            return None
        return path
