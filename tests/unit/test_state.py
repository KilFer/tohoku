import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import BaseModel

from builders import make_fetch
from tohoku.errors import QuotaExceeded
from tohoku.models import FetchResult, Outcome, PublishedNote
from tohoku.quota import DailyQuota
from tohoku.sources import ContentHint, Platform
from tohoku.state import JobStatus, StateStore, next_quota_reset


class Clock:
    def __init__(self):
        self.now = datetime(2026, 9, 28, 10, 0, tzinfo=UTC)

    def __call__(self):
        return self.now


class Dummy(BaseModel):
    value: int


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def state(tmp_path, clock):
    return StateStore(tmp_path / "state.db", clock=clock)


def test_add_job_is_idempotent(state):
    assert state.add_job("b1", "https://youtu.be/x", Platform.YOUTUBE, ContentHint.VIDEO) is True
    assert state.add_job("b1", "https://youtu.be/x", Platform.YOUTUBE, ContentHint.VIDEO) is False
    job = state.get_job("b1")
    assert job.status == JobStatus.PENDING
    assert job.platform == Platform.YOUTUBE and job.hint == ContentHint.VIDEO
    assert state.has_job("b1") and not state.has_job("nope")


def test_unsupported_job_has_no_platform(state):
    state.add_job("b2", "https://tiktok.com/x", None, None)
    assert state.get_job("b2").platform is None


def test_due_jobs_respects_next_attempt(state, clock):
    state.add_job("b1", "u1", Platform.YOUTUBE, ContentHint.VIDEO)
    state.add_job("b2", "u2", Platform.YOUTUBE, ContentHint.VIDEO)
    state.schedule_retry("b2", clock.now + timedelta(minutes=5), "timeout")
    assert [j.bookmark_id for j in state.due_jobs()] == ["b1"]
    clock.now += timedelta(minutes=6)
    assert [j.bookmark_id for j in state.due_jobs()] == ["b1", "b2"]
    job = state.get_job("b2")
    assert job.attempts == 1 and job.last_error == "timeout"


def test_retry_without_counting_attempt(state, clock):
    state.add_job("b1", "u1", Platform.YOUTUBE, ContentHint.VIDEO)
    state.schedule_retry("b1", clock.now, "quota", count_attempt=False)
    assert state.get_job("b1").attempts == 0


def test_stage_results_roundtrip_and_clear(state):
    state.add_job("b1", "u1", Platform.YOUTUBE, ContentHint.VIDEO)
    for name in ("fetch", "transcribe", "extract"):
        state.save_stage("b1", name, Dummy(value=1))
    state.record_publish("b1", PublishedNote(key="lugar:0", note_id="n1", action="create"))
    assert state.load_stage("b1", "fetch", Dummy) == Dummy(value=1)

    state.clear_stages_from("b1", "transcribe", ["fetch", "transcribe", "extract", "publish"])

    assert state.load_stage("b1", "fetch", Dummy) is not None
    assert state.load_stage("b1", "transcribe", Dummy) is None
    assert state.load_stage("b1", "extract", Dummy) is None
    assert state.published("b1") == {}


def test_mark_fetch_purged_sets_flag_and_keeps_the_rest(state):
    state.add_job("b1", "u1", Platform.YOUTUBE, ContentHint.VIDEO)
    fetch = make_fetch(audio_files=["audio.m4a"], keyframes=["frames/f1.jpg"], subtitles="subs.vtt")
    state.save_stage("b1", "fetch", fetch)
    state.save_stage("b1", "transcribe", Dummy(value=7))

    state.mark_fetch_purged("b1")

    loaded = state.load_stage("b1", "fetch", FetchResult)
    assert loaded.files_purged is True
    assert loaded.model_dump(exclude={"files_purged"}) == fetch.model_dump(exclude={"files_purged"})
    assert state.load_stage("b1", "transcribe", Dummy) == Dummy(value=7)


def test_mark_fetch_purged_without_fetch_result_does_nothing(state):
    state.add_job("b1", "u1", Platform.YOUTUBE, ContentHint.VIDEO)
    state.save_stage("b1", "transcribe", Dummy(value=7))

    state.mark_fetch_purged("b1")

    assert state.load_stage("b1", "fetch", FetchResult) is None
    assert state.load_stage("b1", "transcribe", Dummy) == Dummy(value=7)


def test_old_fetch_result_without_flag_loads_as_not_purged(state):
    state.add_job("b1", "u1", Platform.YOUTUBE, ContentHint.VIDEO)
    state.save_stage("b1", "fetch", make_fetch())
    state._db.execute("UPDATE stage_results SET data = json_remove(data, '$.files_purged')")

    assert "files_purged" not in state._db.execute("SELECT data FROM stage_results").fetchone()["data"]
    assert state.load_stage("b1", "fetch", FetchResult).files_purged is False


def test_finish_and_reset(state):
    state.add_job("b1", "u1", Platform.YOUTUBE, ContentHint.VIDEO)
    state.finish("b1", Outcome.ERROR, "privado")
    job = state.get_job("b1")
    assert job.status == JobStatus.ERROR and job.outcome == Outcome.ERROR and job.last_error == "privado"
    state.finish("b1", Outcome.PROCESADO)
    assert state.get_job("b1").status == JobStatus.DONE
    state.reset("b1")
    job = state.get_job("b1")
    assert job.status == JobStatus.PENDING and job.attempts == 0 and job.outcome is None


def test_counters_are_daily(state, clock):
    assert state.add_counter("places_calls", 1) == 1
    assert state.add_counter("places_calls", 2) == 3
    clock.now += timedelta(days=1)
    assert state.get_counter("places_calls") == 0


def test_counters_follow_the_google_quota_day_in_pacific_time(state, clock):
    """Google renueva las cuotas a medianoche del Pacífico (07:00 UTC en verano), no a medianoche UTC."""
    clock.now = datetime(2026, 9, 29, 23, 0, tzinfo=UTC)  # 16:00 PDT del día 29
    state.add_counter("places_calls", 2000)
    clock.now = datetime(2026, 9, 30, 2, 0, tzinfo=UTC)  # ya es día 30 en UTC, pero sigue siendo 29 en PDT
    assert state.get_counter("places_calls") == 2000
    clock.now = datetime(2026, 9, 30, 7, 1, tzinfo=UTC)  # 00:01 PDT del día 30
    assert state.get_counter("places_calls") == 0


def test_next_quota_reset_is_pacific_midnight(state, clock):
    clock.now = datetime(2026, 9, 29, 21, 0, tzinfo=UTC)
    assert next_quota_reset(clock.now) == datetime(2026, 9, 30, 7, 5, tzinfo=UTC)
    clock.now = datetime(2026, 12, 1, 3, 0, tzinfo=UTC)  # horario de invierno (PST, UTC-8)
    assert next_quota_reset(clock.now) == datetime(2026, 12, 1, 8, 5, tzinfo=UTC)


def test_places_cache_roundtrip_and_expiry(state, clock):
    assert state.get_places_cache("Dotonbori Osaka", timedelta(days=30)) is None
    state.put_places_cache("Dotonbori Osaka", [{"place_id": "D1"}])
    state.put_places_cache("Nada en Japón", [])

    assert state.get_places_cache("  dotonbori   OSAKA ", timedelta(days=30)) == [{"place_id": "D1"}]
    assert state.get_places_cache("nada en japón", timedelta(days=30)) == []
    clock.now += timedelta(days=31)
    assert state.get_places_cache("Dotonbori Osaka", timedelta(days=30)) is None


def test_status_counts(state):
    state.add_job("b1", "u1", Platform.YOUTUBE, ContentHint.VIDEO)
    state.add_job("b2", "u2", Platform.YOUTUBE, ContentHint.VIDEO)
    state.finish("b2", Outcome.REVISAR)
    assert state.status_counts() == {"pendiente": 1, "revisar": 1}
    assert state.finished_today() == {"revisar": 1}


def test_daily_quota(state):
    quota = DailyQuota(state, "places_calls", limit=2)
    quota.check()
    quota.add(2)
    with pytest.raises(QuotaExceeded) as info:
        quota.check()
    assert info.value.key == "places_calls"
    assert str(info.value) == "límite diario alcanzado: places_calls (2)"


def test_review_reasons_for_note_joins_other_sources(state):
    state.record_publish("b1", PublishedNote(key="lugar:0", note_id="n1", action="create", review_reasons=["baja-confianza"]))
    state.record_publish("b2", PublishedNote(key="lugar:3", note_id="n1", action="merge", review_reasons=["geocodificacion-ambigua"]))
    state.record_publish("b3", PublishedNote(key="lugar:0", note_id="n2", action="create", review_reasons=["posible-duplicado"]))

    assert state.review_reasons_for_note("n1", exclude=("b2", "lugar:3")) == ["baja-confianza"]
    assert sorted(state.review_reasons_for_note("n1")) == ["baja-confianza", "geocodificacion-ambigua"]
    assert state.review_reasons_for_note("n9") == []


def test_legacy_no_japon_jobs_are_counted_as_descartado(state):
    state.add_job("b1", "u1", Platform.YOUTUBE, ContentHint.VIDEO)
    state.finish("b1", Outcome.DESCARTADO)
    state._db.execute("UPDATE jobs SET outcome = 'no-japon' WHERE bookmark_id = 'b1'")  # fila de antes de la fase 3
    state.add_job("b2", "u2", Platform.YOUTUBE, ContentHint.VIDEO)
    state.finish("b2", Outcome.DESCARTADO)

    assert state.status_counts() == {"descartado": 2}
    assert state.get_job("b1").outcome is Outcome.DESCARTADO


OLD_JOBS_SCHEMA = """CREATE TABLE jobs (bookmark_id TEXT PRIMARY KEY, url TEXT NOT NULL, platform TEXT, hint TEXT,
    status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at TEXT, last_error TEXT,
    outcome TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"""


def test_old_database_is_migrated_and_old_jobs_have_no_candidates(tmp_path, clock):
    path = tmp_path / "state.db"
    db = sqlite3.connect(path)
    db.execute(OLD_JOBS_SCHEMA)
    db.execute("INSERT INTO jobs (bookmark_id, url, platform, hint, created_at, updated_at) VALUES ('old', 'u', 'youtube', 'video', '2026-09-01T00:00:00+00:00', '2026-09-01T00:00:00+00:00')")
    db.commit(); db.close()

    state = StateStore(path, clock=clock)
    StateStore(path, clock=clock)  # la migración es idempotente

    job = state.get_job("old")
    assert job.candidates is None and job.destination is None


def test_candidates_and_destination_roundtrip(state):
    state.add_job("b1", "u1", Platform.YOUTUBE, ContentHint.VIDEO, candidates=["japon", "recetas"])
    state.add_candidates("b1", ["recetas", "nueva_zelanda"])
    state.set_destination("b1", "recetas")

    job = state.get_job("b1")
    assert job.candidates == ["japon", "recetas", "nueva_zelanda"]
    assert job.destination == "recetas"
    state.set_destination("b1", None)
    assert state.get_job("b1").destination is None


def test_legacy_no_japon_jobs_finished_today_count_as_descartado(state):
    state.add_job("b1", "u1", Platform.YOUTUBE, ContentHint.VIDEO)
    state.finish("b1", Outcome.DESCARTADO)
    state._db.execute("UPDATE jobs SET outcome = 'no-japon' WHERE bookmark_id = 'b1'")  # fila de antes de la fase 3
    state.add_job("b2", "u2", Platform.YOUTUBE, ContentHint.VIDEO)
    state.finish("b2", Outcome.DESCARTADO)

    assert state.finished_today() == {"descartado": 2}


def test_add_candidates_without_new_names_does_not_touch_the_job(state, clock):
    state.add_job("b1", "u1", Platform.YOUTUBE, ContentHint.VIDEO, candidates=["japon", "recetas"])
    before = state.get_job("b1").updated_at
    clock.now += timedelta(minutes=5)

    state.add_candidates("b1", ["recetas", "japon"])

    job = state.get_job("b1")
    assert job.candidates == ["japon", "recetas"] and job.updated_at == before


class _NoColumnsYet:
    """Conexión que no ve las columnas nuevas en PRAGMA: como otro proceso que migró entre medias."""

    def __init__(self, db):
        self._db = db

    def execute(self, sql, *args):
        if sql.startswith("PRAGMA table_info"):
            return iter([])
        return self._db.execute(sql, *args)


def test_migration_tolerates_a_concurrent_migration(state):
    state._db = _NoColumnsYet(state._db)
    state._migrate()  # las columnas ya existen: "duplicate column name" no es un error
