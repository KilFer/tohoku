import json
import re
import sqlite3
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, time, timedelta
from enum import StrEnum
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import BaseModel, field_validator

from tohoku.models import Outcome, PublishedNote
from tohoku.sources import ContentHint, Platform


def utcnow() -> datetime:
    return datetime.now(UTC)


# Google renueva las cuotas diarias (y mide el mes) a medianoche del Pacífico. Los contadores de
# cuota usan ese mismo día para no llamar a Google cuando su cuota del día ya está agotada.
QUOTA_TZ = ZoneInfo("America/Los_Angeles")


def next_quota_reset(now: datetime) -> datetime:
    """Siguiente medianoche del Pacífico + 5 min, en UTC."""
    tomorrow = now.astimezone(QUOTA_TZ).date() + timedelta(days=1)
    return datetime.combine(tomorrow, time(0, 5), tzinfo=QUOTA_TZ).astimezone(UTC)


def _cache_key(query: str) -> str:
    return re.sub(r"\s+", " ", query.casefold()).strip()


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds")


class JobStatus(StrEnum):
    PENDING = "pending"
    DONE = "done"
    ERROR = "error"


class Job(BaseModel):
    bookmark_id: str
    url: str
    platform: Platform | None
    hint: ContentHint | None
    status: JobStatus
    attempts: int
    next_attempt_at: datetime | None
    last_error: str | None
    outcome: Outcome | None
    created_at: datetime
    updated_at: datetime
    candidates: list[str] | None = None  # None = job sin candidatos registrados
    destination: str | None = None

    @field_validator("candidates", mode="before")
    @classmethod
    def _decode_candidates(cls, value):
        return json.loads(value) if isinstance(value, str) else value


_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    bookmark_id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    platform TEXT,
    hint TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    last_error TEXT,
    outcome TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    candidates TEXT,  -- JSON; NULL = sin candidatos registrados
    destination TEXT
);
CREATE TABLE IF NOT EXISTS stage_results (
    bookmark_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (bookmark_id, stage)
);
CREATE TABLE IF NOT EXISTS published (
    bookmark_id TEXT NOT NULL,
    item_key TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (bookmark_id, item_key)
);
CREATE TABLE IF NOT EXISTS counters (
    day TEXT NOT NULL,
    key TEXT NOT NULL,
    value REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (day, key)
);
CREATE TABLE IF NOT EXISTS places_cache (
    query TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class StateStore:
    """Estado del servicio: jobs, resultados por etapa, publicaciones y contadores diarios."""

    def __init__(self, path: Path, clock: Callable[[], datetime] = utcnow) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_SCHEMA)
        self._clock = clock

    def _now(self) -> str:
        return _iso(self._clock())

    def today(self) -> str:
        return self._clock().astimezone(UTC).date().isoformat()

    def quota_day(self) -> str:
        """Día de las cuotas (hora del Pacífico, como Google)."""
        return self._clock().astimezone(QUOTA_TZ).date().isoformat()

    # --- jobs -------------------------------------------------------------

    def add_job(
        self,
        bookmark_id: str,
        url: str,
        platform: Platform | None,
        hint: ContentHint | None,
        candidates: Sequence[str] | None = None,
    ) -> bool:
        now = self._now()
        cursor = self._db.execute(
            "INSERT OR IGNORE INTO jobs (bookmark_id, url, platform, hint, candidates, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                bookmark_id, url, platform.value if platform else None, hint.value if hint else None,
                json.dumps(list(candidates)) if candidates is not None else None, now, now,
            ),
        )
        return cursor.rowcount == 1

    def add_candidates(self, bookmark_id: str, names: Sequence[str]) -> None:
        """Une destinos candidatos sin duplicar y conservando el orden."""
        row = self._db.execute("SELECT candidates FROM jobs WHERE bookmark_id = ?", (bookmark_id,)).fetchone()
        if row is None:
            return
        old = json.loads(row["candidates"]) if row["candidates"] else []
        merged = list(dict.fromkeys(old + list(names)))
        if merged == old:
            return  # nada nuevo: no se toca `updated_at`
        self._db.execute(
            "UPDATE jobs SET candidates = ?, updated_at = ? WHERE bookmark_id = ?",
            (json.dumps(merged), self._now(), bookmark_id),
        )

    def set_destination(self, bookmark_id: str, destination: str | None) -> None:
        self._db.execute(
            "UPDATE jobs SET destination = ?, updated_at = ? WHERE bookmark_id = ?",
            (destination, self._now(), bookmark_id),
        )

    def has_job(self, bookmark_id: str) -> bool:
        return self._db.execute("SELECT 1 FROM jobs WHERE bookmark_id = ?", (bookmark_id,)).fetchone() is not None

    def get_job(self, bookmark_id: str) -> Job | None:
        row = self._db.execute("SELECT * FROM jobs WHERE bookmark_id = ?", (bookmark_id,)).fetchone()
        return Job.model_validate(dict(row)) if row else None

    def due_jobs(self) -> list[Job]:
        rows = self._db.execute(
            "SELECT * FROM jobs WHERE status = 'pending'"
            " AND (next_attempt_at IS NULL OR next_attempt_at <= ?)"
            " ORDER BY created_at, bookmark_id",
            (self._now(),),
        ).fetchall()
        return [Job.model_validate(dict(row)) for row in rows]

    def list_jobs(self, status: JobStatus | None = None, limit: int = 20) -> list[Job]:
        if status is None:
            rows = self._db.execute("SELECT * FROM jobs ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
        else:
            rows = self._db.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY updated_at DESC LIMIT ?", (status.value, limit)
            ).fetchall()
        return [Job.model_validate(dict(row)) for row in rows]

    def error_job_ids(self) -> list[str]:
        """Todos los jobs en error (sin límite), del más antiguo al más reciente."""
        rows = self._db.execute("SELECT bookmark_id FROM jobs WHERE status = 'error' ORDER BY updated_at, bookmark_id").fetchall()
        return [row["bookmark_id"] for row in rows]

    def schedule_retry(self, bookmark_id: str, when: datetime, error: str, count_attempt: bool = True) -> None:
        self._db.execute(
            "UPDATE jobs SET attempts = attempts + ?, next_attempt_at = ?, last_error = ?, updated_at = ?"
            " WHERE bookmark_id = ?",
            (1 if count_attempt else 0, _iso(when), error, self._now(), bookmark_id),
        )

    def finish(self, bookmark_id: str, outcome: Outcome, error: str | None = None) -> None:
        status = JobStatus.ERROR if outcome == Outcome.ERROR else JobStatus.DONE
        self._db.execute(
            "UPDATE jobs SET status = ?, outcome = ?, last_error = ?, next_attempt_at = NULL, updated_at = ?"
            " WHERE bookmark_id = ?",
            (status.value, outcome.value, error, self._now(), bookmark_id),
        )

    def reset(self, bookmark_id: str) -> None:
        self._db.execute(
            "UPDATE jobs SET status = 'pending', attempts = 0, next_attempt_at = NULL, last_error = NULL,"
            " outcome = NULL, updated_at = ? WHERE bookmark_id = ?",
            (self._now(), bookmark_id),
        )

    # --- resultados por etapa ------------------------------------------------

    def save_stage(self, bookmark_id: str, stage: str, result: BaseModel) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO stage_results (bookmark_id, stage, data, created_at) VALUES (?, ?, ?, ?)",
            (bookmark_id, stage, result.model_dump_json(), self._now()),
        )

    def load_stage[T: BaseModel](self, bookmark_id: str, stage: str, model: type[T]) -> T | None:
        row = self._db.execute(
            "SELECT data FROM stage_results WHERE bookmark_id = ? AND stage = ?", (bookmark_id, stage)
        ).fetchone()
        return model.model_validate_json(row["data"]) if row else None

    def clear_stages_from(self, bookmark_id: str, from_stage: str, order: Sequence[str]) -> None:
        names = list(order[list(order).index(from_stage):])
        placeholders = ",".join("?" for _ in names)
        self._db.execute(
            f"DELETE FROM stage_results WHERE bookmark_id = ? AND stage IN ({placeholders})",
            (bookmark_id, *names),
        )
        if "publish" in names:
            self._db.execute("DELETE FROM published WHERE bookmark_id = ?", (bookmark_id,))

    # --- limpieza (nunca toca `jobs` ni `published`) ----------------------------

    def delete_stage(self, bookmark_id: str, stage: str) -> None:
        self._db.execute("DELETE FROM stage_results WHERE bookmark_id = ? AND stage = ?", (bookmark_id, stage))

    def mark_fetch_purged(self, bookmark_id: str) -> None:
        """Marca el resultado de fetch con `files_purged` (sus ficheros se borraron); conserva el resto. Sin fetch, no hace nada."""
        self._db.execute(
            "UPDATE stage_results SET data = json_set(data, '$.files_purged', json('true'))"
            " WHERE bookmark_id = ? AND stage = 'fetch'",
            (bookmark_id,),
        )

    def delete_stages(self, bookmark_id: str) -> None:
        """Todos los resultados de etapa del job."""
        self._db.execute("DELETE FROM stage_results WHERE bookmark_id = ?", (bookmark_id,))

    def purge_stage_results(self, older_than: datetime) -> list[str]:
        """Borra los resultados de etapa de los jobs `done` terminados antes de `older_than`; devuelve sus ids."""
        # Una sola sentencia: un `reprocess` concurrente (pasa el job a pending) no puede colarse entre medias.
        rows = self._db.execute(
            "DELETE FROM stage_results WHERE bookmark_id IN"
            " (SELECT bookmark_id FROM jobs WHERE status = 'done' AND updated_at < ?)"
            " RETURNING bookmark_id",
            (_iso(older_than),),
        ).fetchall()
        return sorted({row["bookmark_id"] for row in rows})

    def done_job_ids(self) -> set[str]:
        rows = self._db.execute("SELECT bookmark_id FROM jobs WHERE status = 'done'").fetchall()
        return {row["bookmark_id"] for row in rows}

    # --- publicaciones (idempotencia de publish) ------------------------------

    def record_publish(self, bookmark_id: str, note: PublishedNote) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO published (bookmark_id, item_key, data) VALUES (?, ?, ?)",
            (bookmark_id, note.key, note.model_dump_json()),
        )

    def published(self, bookmark_id: str) -> dict[str, PublishedNote]:
        rows = self._db.execute("SELECT data FROM published WHERE bookmark_id = ?", (bookmark_id,)).fetchall()
        notes = [PublishedNote.model_validate_json(row["data"]) for row in rows]
        return {note.key: note for note in notes}

    def review_reasons_for_note(self, note_id: str, exclude: tuple[str, str] | None = None) -> list[str]:
        """Motivos de revisión vigentes de todas las fuentes publicadas en `note_id` (salvo `exclude`)."""
        rows = self._db.execute(
            "SELECT bookmark_id, item_key, data FROM published WHERE json_extract(data, '$.note_id') = ?", (note_id,)
        ).fetchall()
        reasons: list[str] = []
        for row in rows:
            if exclude and (row["bookmark_id"], row["item_key"]) == exclude:
                continue
            reasons += PublishedNote.model_validate_json(row["data"]).review_reasons
        return list(dict.fromkeys(reasons))

    # --- contadores diarios -------------------------------------------------

    def add_counter(self, key: str, amount: float) -> float:
        self._db.execute(
            "INSERT INTO counters (day, key, value) VALUES (?, ?, ?)"
            " ON CONFLICT(day, key) DO UPDATE SET value = value + excluded.value",
            (self.quota_day(), key, amount),
        )
        return self.get_counter(key)

    def get_counter(self, key: str) -> float:
        row = self._db.execute("SELECT value FROM counters WHERE day = ? AND key = ?", (self.quota_day(), key)).fetchone()
        return float(row["value"]) if row else 0.0

    # --- caché de Google Places -------------------------------------------

    def get_places_cache(self, query: str, max_age: timedelta) -> list[dict] | None:
        row = self._db.execute("SELECT data, created_at FROM places_cache WHERE query = ?", (_cache_key(query),)).fetchone()
        if row is None or self._clock() - datetime.fromisoformat(row["created_at"]) > max_age:
            return None
        return json.loads(row["data"])

    def put_places_cache(self, query: str, results: list[dict]) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO places_cache (query, data, created_at) VALUES (?, ?, ?)",
            (_cache_key(query), json.dumps(results, ensure_ascii=False), self._now()),
        )

    # --- informes -----------------------------------------------------------

    def status_counts(self) -> dict[str, int]:
        rows = self._db.execute("SELECT status, outcome, COUNT(*) AS n FROM jobs GROUP BY status, outcome").fetchall()
        counts: dict[str, int] = {}
        for row in rows:
            if row["status"] == JobStatus.PENDING:
                key = "pendiente"
            else:
                key = Outcome(row["outcome"]).value if row["outcome"] else row["outcome"]
            counts[key] = counts.get(key, 0) + row["n"]
        return counts

    def finished_today(self) -> dict[str, int]:
        rows = self._db.execute(
            "SELECT outcome, COUNT(*) AS n FROM jobs WHERE status != 'pending' AND substr(updated_at, 1, 10) = ?"
            " GROUP BY outcome",
            (self.today(),),
        ).fetchall()
        counts: dict[str, int] = {}
        for row in rows:
            key = Outcome(row["outcome"]).value if row["outcome"] else row["outcome"]
            counts[key] = counts.get(key, 0) + row["n"]
        return counts
