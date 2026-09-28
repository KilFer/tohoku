from datetime import UTC, datetime

import pytest
from pydantic import BaseModel

from fakes import FakeKarakeep
from japan_reader.clients.karakeep import Bookmark
from japan_reader.errors import ConfigError
from japan_reader.models import Outcome
from japan_reader.pipeline import STAGE_ORDER
from japan_reader.service import Service, format_status, reprocess
from japan_reader.sources import ContentHint, Platform
from japan_reader.state import JobStatus, StateStore


class FakePipeline:
    def __init__(self, error=None):
        self.error = error
        self.runs = 0
        self.alerts = []

    def run_due(self):
        self.runs += 1
        if self.error:
            raise self.error
        return 0

    def notify_once(self, key, title, message):
        self.alerts.append(key)


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def send(self, title, message, priority=3, tags=()):
        self.sent.append((title, message))


class Stop(Exception):
    pass


class Saved(BaseModel):
    value: int = 1


@pytest.fixture
def state(tmp_path):
    return StateStore(tmp_path / "state.db")


def _service(state, settings, pipeline, preflight=lambda: None, clock=None, notifier=None):
    karakeep = FakeKarakeep([Bookmark(id="b1", url="https://youtu.be/a")])
    return Service(karakeep, state, pipeline, notifier or FakeNotifier(), settings, preflight,
                   clock=clock or (lambda: datetime(2026, 9, 28, 10, tzinfo=UTC)))


def test_tick_runs_preflight_once_ingests_and_processes(state, settings):
    calls = []
    pipeline = FakePipeline()
    service = _service(state, settings, pipeline, preflight=lambda: calls.append(1))

    service.tick()
    service.tick()

    assert calls == [1]
    assert state.has_job("b1")
    assert pipeline.runs == 2


def test_run_forever_survives_config_errors(state, settings):
    pipeline = FakePipeline(ConfigError("Trilium sin #jrRoot"))
    service = _service(state, settings, pipeline)
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise Stop

    with pytest.raises(Stop):
        service.run_forever(sleep=sleep)

    assert sleeps == [600, 600]
    assert pipeline.alerts == ["config:Trilium sin #jrRoot", "config:Trilium sin #jrRoot"]


def test_daily_summary_sent_once_after_hour(state, settings):
    s = settings.model_copy(update={"ntfy_daily_summary": True})
    notifier = FakeNotifier()
    state.add_job("b9", "u", Platform.YOUTUBE, ContentHint.VIDEO)
    state.finish("b9", Outcome.PROCESADO)
    service = _service(state, s, FakePipeline(), clock=lambda: datetime(2026, 9, 28, 21, 30, tzinfo=UTC), notifier=notifier)

    service.tick()
    service.tick()

    assert notifier.sent == [("japan-reader: resumen del día", "procesado: 1")]


def test_reprocess_existing_job(state):
    state.add_job("b1", "https://youtu.be/a", Platform.YOUTUBE, ContentHint.VIDEO)
    for stage in STAGE_ORDER:
        state.save_stage("b1", stage, Saved())
    state.finish("b1", Outcome.PROCESADO)

    job = reprocess(state, FakeKarakeep(), "b1", "extract")

    assert job.status == JobStatus.PENDING
    assert state.load_stage("b1", "transcribe", Saved) is not None
    assert state.load_stage("b1", "extract", Saved) is None


def test_reprocess_unknown_job_is_created_from_karakeep(state):
    job = reprocess(state, FakeKarakeep([Bookmark(id="b7", url="https://www.instagram.com/p/X/")]), "b7", "fetch")
    assert job.platform == Platform.INSTAGRAM and job.hint == ContentHint.POST


def test_reprocess_rejects_invalid_stage(state):
    with pytest.raises(ValueError):
        reprocess(state, FakeKarakeep(), "b1", "transcribe")


def test_format_status(state):
    state.add_job("b1", "https://youtu.be/a", Platform.YOUTUBE, ContentHint.VIDEO)
    state.add_job("b2", "https://youtu.be/b", Platform.YOUTUBE, ContentHint.VIDEO)
    state.finish("b2", Outcome.ERROR, "Private video")
    state.add_counter("openrouter_usd", 0.1234)
    state.add_counter("places_calls", 3)

    text = format_status(state)

    assert "pendiente: 1" in text and "error: 1" in text
    assert "OpenRouter 0.1234 USD" in text and "Places 3 llamadas" in text
    assert "b2 https://youtu.be/b — Private video" in text
