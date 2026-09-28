import sqlite3
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel

from japan_reader.models import Outcome, PublishedNote
from japan_reader.sources import ContentHint, Platform


def utcnow() -> datetime:
    return datetime.now(UTC)


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
    updated_at TEXT NOT NULL
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

    # --- jobs -------------------------------------------------------------

    def add_job(self, bookmark_id: str, url: str, platform: Platform | None, hint: ContentHint | None) -> bool:
        now = self._now()
        cursor = self._db.execute(
            "INSERT OR IGNORE INTO jobs (bookmark_id, url, platform, hint, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (bookmark_id, url, platform.value if platform else None, hint.value if hint else None, now, now),
        )
        return cursor.rowcount == 1

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

    # --- contadores diarios -------------------------------------------------

    def add_counter(self, key: str, amount: float) -> float:
        self._db.execute(
            "INSERT INTO counters (day, key, value) VALUES (?, ?, ?)"
            " ON CONFLICT(day, key) DO UPDATE SET value = value + excluded.value",
            (self.today(), key, amount),
        )
        return self.get_counter(key)

    def get_counter(self, key: str) -> float:
        row = self._db.execute("SELECT value FROM counters WHERE day = ? AND key = ?", (self.today(), key)).fetchone()
        return float(row["value"]) if row else 0.0

    # --- informes -----------------------------------------------------------

    def status_counts(self) -> dict[str, int]:
        rows = self._db.execute("SELECT status, outcome, COUNT(*) AS n FROM jobs GROUP BY status, outcome").fetchall()
        counts: dict[str, int] = {}
        for row in rows:
            key = "pendiente" if row["status"] == JobStatus.PENDING else row["outcome"]
            counts[key] = counts.get(key, 0) + row["n"]
        return counts

    def finished_today(self) -> dict[str, int]:
        rows = self._db.execute(
            "SELECT outcome, COUNT(*) AS n FROM jobs WHERE status != 'pending' AND substr(updated_at, 1, 10) = ?"
            " GROUP BY outcome",
            (self.today(),),
        ).fetchall()
        return {row["outcome"]: row["n"] for row in rows}
