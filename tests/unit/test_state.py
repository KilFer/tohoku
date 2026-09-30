from datetime import UTC, datetime, timedelta

import pytest
from pydantic import BaseModel

from tohoku.errors import QuotaExceeded
from tohoku.models import Outcome, PublishedNote
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
    with pytest.raises(QuotaExceeded):
        quota.check()


def test_review_reasons_for_note_joins_other_sources(state):
    state.record_publish("b1", PublishedNote(key="lugar:0", note_id="n1", action="create", review_reasons=["baja-confianza"]))
    state.record_publish("b2", PublishedNote(key="lugar:3", note_id="n1", action="merge", review_reasons=["geocodificacion-ambigua"]))
    state.record_publish("b3", PublishedNote(key="lugar:0", note_id="n2", action="create", review_reasons=["posible-duplicado"]))

    assert state.review_reasons_for_note("n1", exclude=("b2", "lugar:3")) == ["baja-confianza"]
    assert sorted(state.review_reasons_for_note("n1")) == ["baja-confianza", "geocodificacion-ambigua"]
    assert state.review_reasons_for_note("n9") == []
