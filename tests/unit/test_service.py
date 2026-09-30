from datetime import UTC, datetime

import pytest
from pydantic import BaseModel

from fakes import FakeKarakeep
from tohoku.clients.karakeep import Bookmark
from tohoku.errors import ConfigError, TransientError
from tohoku.models import Outcome, PublishedNote
from tohoku.pipeline import STAGE_ORDER
from tohoku.service import Service, format_status, reprocess
from tohoku.sources import ContentHint, Platform
from tohoku.state import JobStatus, StateStore


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
                   lists={"L1": ["japon"]}, clock=clock or (lambda: datetime(2026, 9, 28, 10, tzinfo=UTC)))


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


def test_run_forever_survives_transient_errors(state, settings):
    pipeline = FakePipeline(TransientError("karakeep caído"))
    service = _service(state, settings, pipeline)
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise Stop

    with pytest.raises(Stop):
        service.run_forever(sleep=sleep)

    assert sleeps == [600, 600]
    assert pipeline.alerts == ["loop:TransientError", "loop:TransientError"]


def test_daily_summary_sent_once_after_hour(state, settings):
    s = settings.model_copy(update={"ntfy_daily_summary": True})
    notifier = FakeNotifier()
    state.add_job("b9", "u", Platform.YOUTUBE, ContentHint.VIDEO)
    state.finish("b9", Outcome.PROCESADO)
    service = _service(state, s, FakePipeline(), clock=lambda: datetime(2026, 9, 28, 21, 30, tzinfo=UTC), notifier=notifier)

    service.tick()
    service.tick()

    assert notifier.sent == [("tohoku: resumen del día", "procesado: 1")]


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


def _done_job_with_stages(state, destination="japon"):
    state.add_job("b1", "https://youtu.be/a", Platform.YOUTUBE, ContentHint.VIDEO)
    state.set_destination("b1", destination)
    for stage in STAGE_ORDER:
        state.save_stage("b1", stage, Saved())
    state.record_publish("b1", PublishedNote(key="lugar:0", note_id="n1", action="create"))
    state.finish("b1", Outcome.PROCESADO)


def test_reprocess_with_destination_saves_it_and_clears_from_classify(state):
    _done_job_with_stages(state)

    job = reprocess(state, FakeKarakeep(), "b1", "geocode", destination="recetas", known={"japon", "recetas"})

    assert job.destination == "recetas"
    assert state.load_stage("b1", "transcribe", Saved) is not None
    for stage in ("classify", "extract", "geocode", "resolve", "publish"):
        assert state.load_stage("b1", stage, Saved) is None


def test_reprocess_with_unknown_destination_raises_with_name(state):
    _done_job_with_stages(state)
    with pytest.raises(ValueError, match="nz"):
        reprocess(state, FakeKarakeep(), "b1", "geocode", destination="nz", known={"japon"})


def test_reprocess_from_fetch_without_destination_resets_it(state):
    _done_job_with_stages(state)
    job = reprocess(state, FakeKarakeep(), "b1", "fetch", known={"japon"})
    assert job.destination is None


def test_reprocess_from_geocode_without_destination_keeps_destination_and_classify(state):
    _done_job_with_stages(state)
    job = reprocess(state, FakeKarakeep(), "b1", "geocode", known={"japon"})
    assert job.destination == "japon"
    assert state.load_stage("b1", "classify", Saved) is not None


def test_reprocess_destination_on_done_job_goes_pending_and_drops_published(state):
    """Review Focus 4: se borra desde `classify` (incluye `publish`). Las notas antiguas en Trilium NO se borran."""
    _done_job_with_stages(state)
    assert state.published("b1")

    job = reprocess(state, FakeKarakeep(), "b1", "publish", destination="recetas", known={"japon", "recetas"})

    assert job.status == JobStatus.PENDING and job.destination == "recetas"
    assert state.published("b1") == {}


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


def test_tick_ingests_every_configured_list(state, settings):
    karakeep = FakeKarakeep([Bookmark(id="a1", url="https://youtu.be/a1"), Bookmark(id="b1", url="https://youtu.be/b1")])
    karakeep.lists["L1"] = ["a1"]
    karakeep.add_to_list("L2", "b1")
    service = Service(karakeep, state, FakePipeline(), FakeNotifier(), settings, lambda: None, lists={"L1": ["japon"], "L2": ["recetas"]})

    service.tick()

    assert state.has_job("a1") and state.has_job("b1")
    assert state.get_job("b1").candidates == ["recetas"]
