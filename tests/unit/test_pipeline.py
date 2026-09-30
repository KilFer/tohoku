from datetime import UTC, datetime, timedelta

import pytest
from pydantic import BaseModel

from builders import make_fetch
from tohoku.errors import ConfigError, PermanentError, QuotaExceeded, TransientError
from tohoku.models import Classification, FetchResult, MarkResult, Outcome, PublishResult
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


class QuotaStep(Step):
    """Agota la cuota solo para los bookmarks indicados (los demás no la necesitan: p. ej. todo en caché)."""

    def __init__(self, name, key, for_bookmarks):
        super().__init__(name)
        self.key = key
        self.for_bookmarks = set(for_bookmarks)

    def run(self, ctx):
        self.calls += 1
        if ctx.job.bookmark_id in self.for_bookmarks:
            raise QuotaExceeded(self.key, f"límite diario alcanzado: {self.key} (150)")
        return self.result


class FakeMark:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def run(self, bookmark_id, outcome, destination=None):
        self.calls.append((bookmark_id, outcome) if destination is None else (bookmark_id, outcome, destination))
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
    assert state.get_job("b2").next_attempt_at == datetime(2026, 9, 29, 7, 5, tzinfo=UTC)


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


def test_quota_exceeded_parks_job_and_pass_continues(tmp_path, state):
    """Con la cuota agotada solo espera el job que la necesita; el resto de la cola sigue."""
    _add(state, "b1")
    _add(state, "b2")
    fetch = Step("fetch")
    geocode = QuotaStep("geocode", "places_calls", for_bookmarks={"b1"})
    publish = Step("publish", result=PublishResult(outcome=Outcome.PROCESADO))
    notifier = FakeNotifier()
    pipeline = Pipeline(state, [fetch, geocode, publish], FakeMark(), notifier, tmp_path / "data", clock=lambda: NOW)

    assert pipeline.run_due() == 2

    b1, b2 = state.get_job("b1"), state.get_job("b2")
    assert b1.status == JobStatus.PENDING and b1.attempts == 0
    assert b1.next_attempt_at == datetime(2026, 9, 29, 7, 5, tzinfo=UTC)
    assert b2.status == JobStatus.DONE and b2.outcome == Outcome.PROCESADO
    assert state.load_stage("b1", "fetch", Dummy) == Dummy()  # lo hecho antes de la cuota queda guardado
    assert len(notifier.sent) == 1


def test_parked_job_resumes_at_the_quota_stage(tmp_path, state):
    _add(state, "b1")
    fetch = Step("fetch")
    geocode = QuotaStep("geocode", "places_calls", for_bookmarks={"b1"})
    publish = Step("publish", result=PublishResult(outcome=Outcome.PROCESADO))
    pipeline = Pipeline(state, [fetch, geocode, publish], FakeMark(), FakeNotifier(), tmp_path / "data", clock=lambda: NOW)
    pipeline.run_due()

    geocode.for_bookmarks.clear()  # vuelve la cuota
    pipeline.run_job(state.get_job("b1"))

    assert fetch.calls == 1 and geocode.calls == 2 and publish.calls == 1
    assert state.get_job("b1").status == JobStatus.DONE


def test_quota_notifies_once_per_key_even_if_every_job_hits_it(tmp_path, state):
    for bid in ("b1", "b2", "b3"):
        _add(state, bid)
    geocode = QuotaStep("geocode", "places_calls", for_bookmarks={"b1", "b2", "b3"})
    notifier = FakeNotifier()
    pipeline = Pipeline(state, [geocode], FakeMark(), notifier, tmp_path / "data", clock=lambda: NOW)

    pipeline.run_due()

    assert all(state.get_job(b).status == JobStatus.PENDING for b in ("b1", "b2", "b3"))
    assert [title for title, _ in notifier.sent] == ["tohoku: límite diario alcanzado"]


def test_parked_job_is_logged(tmp_path, state, caplog):
    _add(state, "b1")
    geocode = QuotaStep("geocode", "places_calls", for_bookmarks={"b1"})
    pipeline = Pipeline(state, [geocode], FakeMark(), FakeNotifier(), tmp_path / "data", clock=lambda: NOW)

    with caplog.at_level("INFO", logger="tohoku.pipeline"):
        pipeline.run_due()

    assert "bookmark=b1 aparcado por cuota places_calls hasta 2026-09-29T07:05:00+00:00" in caplog.text


def _multi(tmp_path, state, verdict_destino):
    fetch = Step("fetch")
    classify = Step("classify", result=Classification(destino=verdict_destino))
    japon_publish = Step("publish", result=PublishResult(outcome=Outcome.PROCESADO))
    recetas_publish = Step("publish", result=PublishResult(outcome=Outcome.REVISAR))
    mark = FakeMark()
    pipeline = Pipeline(state, [fetch, classify], mark, FakeNotifier(), tmp_path / "data", clock=lambda: NOW,
                        flows={"japon": [japon_publish], "recetas": [recetas_publish]})
    return pipeline, mark, japon_publish, recetas_publish


def test_job_runs_the_stages_of_its_classified_destination(tmp_path, state):
    _add(state)
    pipeline, mark, japon, recetas = _multi(tmp_path, state, "recetas")
    pipeline.run_due()
    assert (japon.calls, recetas.calls) == (0, 1)
    assert state.get_job("b1").destination == "recetas" and state.get_job("b1").outcome == Outcome.REVISAR
    assert mark.calls == [("b1", Outcome.REVISAR, "recetas")]


def test_no_destination_is_descartado_without_flow_stages(tmp_path, state):
    _add(state)
    pipeline, mark, japon, recetas = _multi(tmp_path, state, None)
    pipeline.run_due()
    assert (japon.calls, recetas.calls) == (0, 0)
    assert state.get_job("b1").outcome == Outcome.DESCARTADO
    assert mark.calls == [("b1", Outcome.DESCARTADO)]  # sin destino: FakeMark registra el par


def test_unknown_destination_fails_only_that_job(tmp_path, state):
    """Un destino borrado del YAML marca jr:error solo ese job; la cola sigue (ruling del controlador)."""
    _add(state, "b1")
    _add(state, "b2")
    fetch = Step("fetch")
    classify = ByJobStep("classify", {"b1": Classification(destino="nz"), "b2": Classification(destino="japon")})
    publish = Step("publish", result=PublishResult(outcome=Outcome.PROCESADO))
    mark = FakeMark()
    pipeline = Pipeline(state, [fetch, classify], mark, FakeNotifier(), tmp_path / "data", clock=lambda: NOW,
                        flows={"japon": [publish]})

    pipeline.run_due()

    failed = state.get_job("b1")
    assert failed.status == JobStatus.ERROR
    assert "El destino 'nz' del job b1 ya no existe en config/destinos.yaml" in failed.last_error
    done = state.get_job("b2")
    assert done.status == JobStatus.DONE and done.outcome == Outcome.PROCESADO and done.destination == "japon"
    assert mark.calls[-1] == ("b2", Outcome.PROCESADO, "japon")


def test_mark_failed_tags_the_destination_of_the_job(tmp_path, state):
    _add(state)
    state.set_destination("b1", "recetas")
    pipeline, mark, *_ = _multi(tmp_path, state, "recetas")
    pipeline.mark_failed("b1", "x")
    assert mark.calls == [("b1", Outcome.ERROR, "recetas")]


class ByJobStep(Step):
    """Devuelve un resultado distinto por bookmark."""

    def __init__(self, name, results):
        super().__init__(name, result=next(iter(results.values())))
        self.results = results

    def run(self, ctx):
        self.calls += 1
        return self.results[ctx.job.bookmark_id]


# --- limpieza (fase 4) -----------------------------------------------------------


class RecordingCleaner:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def job_finished(self, bookmark_id, outcome):
        self.calls.append((bookmark_id, outcome))
        if self.error:
            raise self.error


class WritingStep(Step):
    """Deja un fichero en el directorio del job, como fetch."""

    def run(self, ctx):
        (ctx.workdir / "video.mp4").write_bytes(b"x")
        return super().run(ctx)


def _cleaning_pipeline(tmp_path, state, retencion_dias=30):
    from tohoku.cleanup import Cleaner

    data_dir = tmp_path / "data"
    fetch = WritingStep("fetch", result=make_fetch())
    transcribe = Step("transcribe")
    transcribe.needs_files = True
    publish = Step("publish", result=PublishResult(outcome=Outcome.PROCESADO))
    cleaner = Cleaner(state, data_dir, retencion_dias, clock=lambda: NOW)
    pipeline = Pipeline(state, [fetch, transcribe, publish], FakeMark(), FakeNotifier(), data_dir, clock=lambda: NOW,
                        cleaner=cleaner)
    return pipeline, fetch, transcribe, publish, data_dir


def test_pipeline_with_cleaner_deletes_job_dir_after_procesado(tmp_path, state):
    _add(state)
    pipeline, _, _, _, data_dir = _cleaning_pipeline(tmp_path, state)

    pipeline.run_due()

    job = state.get_job("b1")
    assert job.status == JobStatus.DONE and job.outcome == Outcome.PROCESADO
    assert not (data_dir / "jobs" / "b1").exists()
    assert state.load_stage("b1", "fetch", FetchResult).files_purged is True
    assert state.load_stage("b1", "transcribe", Dummy) == Dummy()


def test_reprocess_after_cleanup_from_publish_does_not_download_again(tmp_path, state):
    _add(state)
    pipeline, fetch, transcribe, publish, data_dir = _cleaning_pipeline(tmp_path, state)
    pipeline.run_due()
    state.reset("b1")
    state.clear_stages_from("b1", "publish", ("fetch", "transcribe", "publish"))

    pipeline.run_due()

    assert fetch.calls == 1
    assert transcribe.calls == 1
    assert publish.calls == 2
    assert state.get_job("b1").status == JobStatus.DONE
    assert not (data_dir / "jobs" / "b1").exists()


def test_reprocess_after_cleanup_from_a_stage_needing_files_downloads_again(tmp_path, state):
    _add(state)
    pipeline, fetch, transcribe, publish, data_dir = _cleaning_pipeline(tmp_path, state)
    pipeline.run_due()
    state.reset("b1")
    state.clear_stages_from("b1", "transcribe", ("fetch", "transcribe", "publish"))

    pipeline.run_due()

    assert fetch.calls == 2
    assert transcribe.calls == 2
    assert publish.calls == 2
    assert state.get_job("b1").status == JobStatus.DONE
    assert not (data_dir / "jobs" / "b1").exists()
    assert state.load_stage("b1", "fetch", FetchResult).files_purged is True  # limpiado otra vez al terminar


def test_cleaner_is_called_after_finish_and_on_mark_failed(tmp_path, state):
    _add(state, "b1")
    _add(state, "b2")
    cleaner = RecordingCleaner()
    publish = Step("publish", result=PublishResult(outcome=Outcome.PROCESADO))
    pipeline = Pipeline(state, [publish], FakeMark(), FakeNotifier(), tmp_path / "data", clock=lambda: NOW,
                        cleaner=cleaner)

    pipeline.run_job(state.get_job("b1"))
    pipeline.mark_failed("b2", "roto")

    assert cleaner.calls == [("b1", Outcome.PROCESADO), ("b2", Outcome.ERROR)]
    assert state.get_job("b2").status == JobStatus.ERROR


def test_cleanup_failure_does_not_change_the_outcome(tmp_path, state, caplog):
    _add(state)
    publish = Step("publish", result=PublishResult(outcome=Outcome.PROCESADO))
    pipeline = Pipeline(state, [publish], FakeMark(), FakeNotifier(), tmp_path / "data", clock=lambda: NOW,
                        cleaner=RecordingCleaner(OSError("permiso denegado")))

    pipeline.run_due()

    job = state.get_job("b1")
    assert job.status == JobStatus.DONE and job.outcome == Outcome.PROCESADO and job.attempts == 0
    assert "permiso denegado" in caplog.text


# --- Re-descarga solo si hace falta (Task 12) ----------------------------------------


class LoggedStep(Step):
    """Step que apunta su nombre en un registro compartido, para comprobar el orden."""

    def __init__(self, name, log, result=None, needs_files=False):
        super().__init__(name, result=result)
        self.log = log
        if needs_files:
            self.needs_files = True

    def run(self, ctx):
        self.log.append(self.name)
        return super().run(ctx)


def _fetch_step(log):
    return LoggedStep("fetch", log, result=make_fetch(audio_files=["audio.m4a"]))


def _publish_step(log):
    return LoggedStep("publish", log, result=PublishResult(outcome=Outcome.PROCESADO))


def test_purged_fetch_is_not_redownloaded_for_stages_without_files(tmp_path, state):
    _add(state)
    state.save_stage("b1", "fetch", make_fetch(files_purged=True))
    state.save_stage("b1", "transcribe", Dummy())
    state.save_stage("b1", "extract", Dummy())
    log = []
    fetch = _fetch_step(log)
    transcribe = LoggedStep("transcribe", log, needs_files=True)
    extract = LoggedStep("extract", log, needs_files=True)
    geocode = LoggedStep("geocode", log)
    publish = _publish_step(log)
    pipeline = Pipeline(state, [fetch, transcribe, extract, geocode, publish], FakeMark(), FakeNotifier(),
                        tmp_path / "data", clock=lambda: NOW)

    pipeline.run_due()

    assert fetch.calls == 0
    assert geocode.calls == 1
    assert log == ["geocode", "publish"]
    assert state.load_stage("b1", "fetch", FetchResult).files_purged is True
    assert state.get_job("b1").outcome == Outcome.PROCESADO


def test_purged_fetch_is_redownloaded_once_before_a_stage_that_needs_files(tmp_path, state, caplog):
    _add(state)
    state.save_stage("b1", "fetch", make_fetch(files_purged=True))
    state.save_stage("b1", "transcribe", Dummy())
    log = []
    fetch = _fetch_step(log)
    transcribe = LoggedStep("transcribe", log, needs_files=True)
    extract = LoggedStep("extract", log, needs_files=True)
    publish = _publish_step(log)
    pipeline = Pipeline(state, [fetch, transcribe, extract, publish], FakeMark(), FakeNotifier(),
                        tmp_path / "data", clock=lambda: NOW)

    with caplog.at_level("INFO", logger="tohoku.pipeline"):
        pipeline.run_due()

    assert fetch.calls == 1
    assert log == ["fetch", "extract", "publish"]
    saved = state.load_stage("b1", "fetch", FetchResult)
    assert saved.files_purged is False and saved.audio_files == ["audio.m4a"]
    assert "bookmark=b1 re-descarga: los ficheros se limpiaron" in caplog.text


def test_purged_fetch_is_redownloaded_only_once_for_several_stages_needing_files(tmp_path, state):
    _add(state)
    state.save_stage("b1", "fetch", make_fetch(files_purged=True))
    log = []
    fetch = _fetch_step(log)
    transcribe = LoggedStep("transcribe", log, needs_files=True)
    extract = LoggedStep("extract", log, needs_files=True)
    publish = _publish_step(log)
    pipeline = Pipeline(state, [fetch, transcribe, extract, publish], FakeMark(), FakeNotifier(),
                        tmp_path / "data", clock=lambda: NOW)

    pipeline.run_due()

    assert fetch.calls == 1
    assert log == ["fetch", "transcribe", "extract", "publish"]


def test_purged_fetch_is_redownloaded_once_across_common_stages_and_flow(tmp_path, state):
    """`classify` (tramo común) y `extract` (flujo del destino) necesitan ficheros: una sola descarga."""
    _add(state)
    state.save_stage("b1", "fetch", make_fetch(files_purged=True))
    state.save_stage("b1", "transcribe", Dummy())
    log = []
    fetch = _fetch_step(log)
    transcribe = LoggedStep("transcribe", log, needs_files=True)
    classify = LoggedStep("classify", log, result=Classification(destino="japon"), needs_files=True)
    extract = LoggedStep("extract", log, needs_files=True)
    publish = _publish_step(log)
    pipeline = Pipeline(state, [fetch, transcribe, classify], FakeMark(), FakeNotifier(), tmp_path / "data",
                        clock=lambda: NOW, flows={"japon": [extract, publish]})

    pipeline.run_due()

    assert fetch.calls == 1
    assert log == ["fetch", "classify", "extract", "publish"]


def test_purged_fetch_is_redownloaded_when_only_a_flow_stage_needs_files(tmp_path, state):
    _add(state)
    state.save_stage("b1", "fetch", make_fetch(files_purged=True))
    state.save_stage("b1", "transcribe", Dummy())
    state.save_stage("b1", "classify", Classification(destino="japon"))
    log = []
    fetch = _fetch_step(log)
    transcribe = LoggedStep("transcribe", log, needs_files=True)
    classify = LoggedStep("classify", log, result=Classification(destino="japon"), needs_files=True)
    extract = LoggedStep("extract", log, needs_files=True)
    publish = _publish_step(log)
    pipeline = Pipeline(state, [fetch, transcribe, classify], FakeMark(), FakeNotifier(), tmp_path / "data",
                        clock=lambda: NOW, flows={"japon": [extract, publish]})

    pipeline.run_due()

    assert fetch.calls == 1
    assert log == ["fetch", "extract", "publish"]
    assert state.load_stage("b1", "fetch", FetchResult).files_purged is False


def test_fetch_not_purged_is_not_redownloaded(tmp_path, state):
    _add(state)
    state.save_stage("b1", "fetch", make_fetch())
    log = []
    fetch = _fetch_step(log)
    extract = LoggedStep("extract", log, needs_files=True)
    publish = _publish_step(log)
    pipeline = Pipeline(state, [fetch, extract, publish], FakeMark(), FakeNotifier(), tmp_path / "data",
                        clock=lambda: NOW)

    pipeline.run_due()

    assert fetch.calls == 0
    assert log == ["extract", "publish"]


def test_without_fetch_stage_a_purged_fetch_is_left_alone(tmp_path, state):
    _add(state)
    state.save_stage("b1", "fetch", make_fetch(files_purged=True))
    log = []
    extract = LoggedStep("extract", log, needs_files=True)
    publish = _publish_step(log)
    pipeline = Pipeline(state, [extract, publish], FakeMark(), FakeNotifier(), tmp_path / "data", clock=lambda: NOW)

    pipeline.run_due()

    assert log == ["extract", "publish"]
    assert state.get_job("b1").outcome == Outcome.PROCESADO


def test_stages_that_need_files_are_marked():
    from tohoku.stages.classify import ClassifyStage
    from tohoku.stages.extract import ExtractStage
    from tohoku.stages.fetch import FetchStage
    from tohoku.stages.transcribe import TranscribeStage

    assert TranscribeStage.needs_files is True
    assert ClassifyStage.needs_files is True
    assert ExtractStage.needs_files is True
    assert getattr(FetchStage, "needs_files", False) is False


def test_refetch_failing_permanently_marks_the_job_error_without_running_extract(tmp_path, state):
    """Caracterización: la re-descarga sigue la política de errores de siempre (p. ej. el Reel ya no existe)."""
    _add(state)
    state.save_stage("b1", "fetch", make_fetch(files_purged=True))
    log = []
    fetch = LoggedStep("fetch", log, result=make_fetch())
    fetch.error = PermanentError("El Reel ya no existe")
    extract = LoggedStep("extract", log, needs_files=True)
    publish = _publish_step(log)
    mark = FakeMark()
    pipeline = Pipeline(state, [fetch, extract, publish], mark, FakeNotifier(), tmp_path / "data", clock=lambda: NOW)

    pipeline.run_due()

    job = state.get_job("b1")
    assert job.status == JobStatus.ERROR
    assert "El Reel ya no existe" in job.last_error
    assert fetch.calls == 1 and extract.calls == 0 and publish.calls == 0
    assert mark.calls == [("b1", Outcome.ERROR)]
