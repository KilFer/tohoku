"""Limpieza en dos niveles: ficheros del job al terminar y resultados de etapa pasada la retención.

Nunca toca la tabla `jobs` ni `published` (hacen falta para la Bandeja y para reprocesar sin duplicar).
Solo borra directorios dentro de `data_dir/jobs` cuyo nombre sea el id de un job terminado (`done`).
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
        """Tras terminar: si no es ERROR, borra data/jobs/<id>/ y marca fetch con `files_purged`; con retención 0, borra todos los resultados."""
        if outcome == Outcome.ERROR:
            return
        self._remove_dir(bookmark_id)
        # Sin el directorio, los ficheros de fetch ya no existen; sus metadatos sí sirven (publish). Solo las etapas
        # que necesitan ficheros (`needs_files`) vuelven a descargar.
        if self._retention:
            self._state.mark_fetch_purged(bookmark_id)
        else:
            self._state.delete_stages(bookmark_id)

    def purge(self) -> int:
        """Una vez por pasada: resultados de etapa de jobs DONE más antiguos que la retención, y directorios de jobs DONE que sigan en disco. Devuelve cuántos jobs ha tocado."""
        touched = set(self._state.purge_stage_results(self._clock() - self._retention))
        if self._jobs_dir.is_dir():
            done = self._state.done_job_ids()
            for entry in self._jobs_dir.iterdir():
                if entry.name in done and entry.is_dir() and not entry.is_symlink():
                    if self._remove_dir(entry.name):
                        self._state.mark_fetch_purged(entry.name)  # como en job_finished: sus ficheros ya no existen
                        touched.add(entry.name)
        return len(touched)

    def _remove_dir(self, bookmark_id: str) -> bool:
        """Borra data/jobs/<id>/ si existe y es seguro. Devuelve si lo ha borrado."""
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
        """La ruta del job solo si el id es un nombre simple y queda dentro de data/jobs (sin enlaces simbólicos)."""
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
