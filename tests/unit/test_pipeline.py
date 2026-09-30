from datetime import UTC, datetime, timedelta

import pytest
from pydantic import BaseModel

from tohoku.errors import ConfigError, PermanentError, QuotaExceeded, TransientError
from tohoku.models import MarkResult, Outcome, PublishResult
from tohoku.pipeline import BACKOFF, Pipeline
from tohoku.sources import ContentHint, Platform
from tohoku.state import JobStatus, StateStore

NOW = datetime(2026, 9, 28, 10, 0, tzinfo=UTC)


class Dummy(BaseModel):
    value: int = 1


class Step:
    def __init__(self, name, error=None, result=None):
        self.name = name
        self.error = error
        self.result = result or Dummy()
        self.result_model = type(self.result)
        self.calls = 0

    def run(self, ctx):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


class FakeMark:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def run(self, bookmark_id, outcome):
        self.calls.append((bookmark_id, outcome))
        if self.error:
            raise self.error
        return MarkResult(tag=f"jr:{outcome.value}", archived=outcome != Outcome.ERROR)


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def send(self, title, message, priority=3, tags=()):
        self.sent.append((title, message))


@pytest.fixture
def state(tmp_path):
    return StateStore(tmp_path / "state.db", clock=lambda: NOW)


def _pipeline(tmp_path, state, fetch_error=None, mark=None):
    fetch = Step("fetch", fetch_error)
    publish = Step("publish", result=PublishResult(outcome=Outcome.PROCESADO))
    notifier = FakeNotifier()
    mark = mark or FakeMark()
    pipeline = Pipeline(state, [fetch, publish], mark, notifier, tmp_path / "data", clock=lambda: NOW)
    return pipeline, fetch, publish, mark, notifier


def _add(state, bid="b1", platform=Platform.YOUTUBE):
    state.add_job(bid, f"https://youtu.be/{bid}", platform, ContentHint.VIDEO if platform else None)


def test_success_runs_all_stages_and_marks(tmp_path, state):
    _add(state)
    pipeline, fetch, publish, mark, _ = _pipeline(tmp_path, state)

    assert pipeline.run_due() == 1

    job = state.get_job("b1")
    assert job.status == JobStatus.DONE and job.outcome == Outcome.PROCESADO
    assert mark.calls == [("b1", Outcome.PROCESADO)]
    assert state.load_stage("b1", "fetch", Dummy) == Dummy()


def test_resume_skips_saved_stages(tmp_path, state):
    _add(state)
    state.save_stage("b1", "fetch", Dummy(value=7))
    pipeline, fetch, *_ = _pipeline(tmp_path, state)
    pipeline.run_due()
    assert fetch.calls == 0


def test_transient_error_schedules_retry(tmp_path, state):
    _add(state)
    pipeline, _, _, mark, _ = _pipeline(tmp_path, state, TransientError("timeout"))

    pipeline.run_due()

    job = state.get_job("b1")
    assert job.status == JobStatus.PENDING and job.attempts == 1
    assert job.next_attempt_at == NOW + BACKOFF[0]
    assert mark.calls == []


def test_unexpected_exception_is_retried(tmp_path, state):
    _add(state)
    pipeline, *_ = _pipeline(tmp_path, state, ValueError("bug"))
    pipeline.run_due()
    assert state.get_job("b1").attempts == 1


def test_retries_exhausted_marks_error_and_notifies(tmp_path, state):
    _add(state)
    for _ in range(len(BACKOFF)):
        state.schedule_retry("b1", NOW - timedelta(minutes=1), "timeout")
    pipeline, _, _, mark, notifier = _pipeline(tmp_path, state, TransientError("timeout"))

    pipeline.run_due()

    job = state.get_job("b1")
    assert job.status == JobStatus.ERROR and "agotados los reintentos" in job.last_error
    assert mark.calls == [("b1", Outcome.ERROR)]
    assert len(notifier.sent) == 1


def test_permanent_error(tmp_path, state):
    _add(state)
    pipeline, _, _, mark, notifier = _pipeline(tmp_path, state, PermanentError("Private video"))

    pipeline.run_due()

    assert state.get_job("b1").last_error == "Private video"
    assert mark.calls == [("b1", Outcome.ERROR)]
    assert "Private video" in notifier.sent[0][1]


def test_quota_waits_until_tomorrow_and_notifies_once(tmp_path, state):
    _add(state, "b1")
    _add(state, "b2")
    pipeline, _, _, _, notifier = _pipeline(tmp_path, state, QuotaExceeded("places_calls", "límite diario alcanzado: places_calls (150)"))

    pipeline.run_due()

    job = state.get_job("b1")
    assert job.attempts == 0
    # Medianoche del Pacífico (cuando Google renueva la cuota) + 5 min: 28/09 10:00 UTC → 29/09 07:05 UTC.
    assert job.next_attempt_at == datetime(2026, 9, 29, 7, 5, tzinfo=UTC)
    assert len(notifier.sent) == 1


def test_config_error_propagates_without_touching_job(tmp_path, state):
    _add(state)
    pipeline, *_ = _pipeline(tmp_path, state, ConfigError("API key"))
    with pytest.raises(ConfigError):
        pipeline.run_due()
    job = state.get_job("b1")
    assert job.status == JobStatus.PENDING and job.attempts == 0


def test_unsupported_source_is_failed_without_stages(tmp_path, state):
    _add(state, platform=None)
    pipeline, fetch, _, mark, _ = _pipeline(tmp_path, state)

    pipeline.run_due()

    assert fetch.calls == 0
    assert state.get_job("b1").last_error == "fuente no soportada"
    assert mark.calls == [("b1", Outcome.ERROR)]


def test_failing_to_mark_error_still_finishes_job(tmp_path, state):
    _add(state)
    pipeline, *_ = _pipeline(tmp_path, state, PermanentError("borrado"), mark=FakeMark(TransientError("karakeep caído")))
    pipeline.run_due()
    assert state.get_job("b1").status == JobStatus.ERROR


def test_quota_exceeded_stops_the_pass(tmp_path, state):
    """Final review 3: tras un QuotaExceeded no se procesan más jobs en esta pasada."""
    _add(state, "b1")
    _add(state, "b2")
    pipeline, fetch, publish, mark, notifier = _pipeline(tmp_path, state, fetch_error=QuotaExceeded("openrouter_usd", "presupuesto agotado"))

    pipeline.run_due()

    assert fetch.calls == 1
    assert state.get_job("b2").status == JobStatus.PENDING and state.get_job("b2").attempts == 0
    assert state.get_job("b2").last_error is None
