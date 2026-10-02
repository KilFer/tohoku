from datetime import UTC, datetime, timedelta

import pytest
from pydantic import BaseModel

from builders import make_fetch
from tohoku.cleanup import Cleaner
from tohoku.models import FetchResult, Outcome, PublishedNote
from tohoku.sources import ContentHint, Platform
from tohoku.state import JobStatus, StateStore

NOW = datetime(2026, 9, 30, 10, 0, tzinfo=UTC)
STAGES = ("fetch", "transcribe", "extract")


class Saved(BaseModel):
    value: int = 1


class Clock:
    def __init__(self, now=NOW):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def state(tmp_path, clock):
    return StateStore(tmp_path / "state.db", clock=clock)


def _job(state, data_dir, bid, outcome=Outcome.PROCESADO, with_dir=True):
    """Job with stage results, a publication and (optionally) its directory with files."""
    state.add_job(bid, f"https://youtu.be/{bid}", Platform.YOUTUBE, ContentHint.VIDEO)
    state.save_stage(bid, "fetch", make_fetch())
    for stage in STAGES[1:]:
        state.save_stage(bid, stage, Saved())
    state.record_publish(bid, PublishedNote(key=f"lugar:{bid}", note_id=f"n-{bid}", action="create"))
    if outcome is not None:
        state.finish(bid, outcome, "motivo" if outcome == Outcome.ERROR else None)
    if with_dir:
        workdir = data_dir / "jobs" / bid
        (workdir / "frames").mkdir(parents=True)
        (workdir / "video.mp4").write_bytes(b"x" * 10)
        (workdir / "frames" / "f1.jpg").write_bytes(b"y")
    return data_dir / "jobs" / bid


def _stages(state, bid):
    return {stage for stage in STAGES if state.load_stage(bid, stage, Saved) is not None}


def _assert_fetch_purged(state, bid):
    """The fetch result remains (metadata for publish) marked with files_purged."""
    fetch = state.load_stage(bid, "fetch", FetchResult)
    assert fetch is not None and fetch.files_purged is True
    assert fetch.meta == make_fetch().meta


# --- job_finished ---------------------------------------------------------------


def test_job_finished_deletes_dir_and_marks_fetch_purged_keeping_all_results(tmp_path, state, clock):
    data_dir = tmp_path / "data"
    workdir = _job(state, data_dir, "b1")
    cleaner = Cleaner(state, data_dir, 30, clock=clock)

    cleaner.job_finished("b1", Outcome.PROCESADO)

    assert not workdir.exists()
    assert (data_dir / "jobs").is_dir()
    assert _stages(state, "b1") == set(STAGES)
    _assert_fetch_purged(state, "b1")


def test_job_finished_with_error_deletes_nothing(tmp_path, state, clock):
    data_dir = tmp_path / "data"
    workdir = _job(state, data_dir, "b1", outcome=Outcome.ERROR)
    cleaner = Cleaner(state, data_dir, 30, clock=clock)

    cleaner.job_finished("b1", Outcome.ERROR)

    assert (workdir / "video.mp4").is_file() and (workdir / "frames" / "f1.jpg").is_file()
    assert _stages(state, "b1") == set(STAGES)
    assert state.load_stage("b1", "fetch", FetchResult).files_purged is False


def test_job_finished_with_zero_retention_deletes_all_stage_results_but_not_published_or_job(tmp_path, state, clock):
    data_dir = tmp_path / "data"
    workdir = _job(state, data_dir, "b1")
    cleaner = Cleaner(state, data_dir, 0, clock=clock)

    cleaner.job_finished("b1", Outcome.PROCESADO)

    assert not workdir.exists()
    assert _stages(state, "b1") == set()
    assert set(state.published("b1")) == {"lugar:b1"}
    job = state.get_job("b1")
    assert job.status == JobStatus.DONE and job.outcome == Outcome.PROCESADO


def test_job_finished_without_directory_still_marks_fetch_purged(tmp_path, state, clock):
    data_dir = tmp_path / "data"
    _job(state, data_dir, "b1", with_dir=False)

    Cleaner(state, data_dir, 30, clock=clock).job_finished("b1", Outcome.DESCARTADO)

    assert _stages(state, "b1") == set(STAGES)
    _assert_fetch_purged(state, "b1")


@pytest.mark.parametrize("bad_id", ["", ".", "..", "../fuera", "a/b", "a\\b"])
def test_job_finished_refuses_unsafe_ids(tmp_path, state, clock, bad_id):
    data_dir = tmp_path / "data"
    outside = tmp_path / "fuera"
    outside.mkdir()
    (outside / "keep.txt").write_text("no borrar")
    (data_dir / "jobs" / "a" / "b").mkdir(parents=True)
    (data_dir / "jobs" / "a" / "b" / "keep.txt").write_text("no borrar")

    Cleaner(state, data_dir, 30, clock=clock).job_finished(bad_id, Outcome.PROCESADO)

    assert (outside / "keep.txt").is_file()
    assert (data_dir / "jobs" / "a" / "b" / "keep.txt").is_file()
    assert (data_dir / "jobs").is_dir() and data_dir.is_dir()


def test_job_finished_does_not_follow_symlinked_job_dir(tmp_path, state, clock):
    data_dir = tmp_path / "data"
    outside = tmp_path / "fuera"
    outside.mkdir()
    (outside / "keep.txt").write_text("no borrar")
    (data_dir / "jobs").mkdir(parents=True)
    (data_dir / "jobs" / "b1").symlink_to(outside, target_is_directory=True)
    _job(state, data_dir, "b1", with_dir=False)

    Cleaner(state, data_dir, 30, clock=clock).job_finished("b1", Outcome.PROCESADO)

    assert (outside / "keep.txt").is_file()


def test_job_finished_logs_and_swallows_os_errors(tmp_path, state, clock, monkeypatch, caplog):
    data_dir = tmp_path / "data"
    workdir = _job(state, data_dir, "b1")

    def boom(*args, **kwargs):
        raise OSError("disco de solo lectura")

    monkeypatch.setattr("tohoku.cleanup.shutil.rmtree", boom)
    Cleaner(state, data_dir, 30, clock=clock).job_finished("b1", Outcome.PROCESADO)

    assert workdir.exists()
    assert "disco de solo lectura" in caplog.text


# --- purge ------------------------------------------------------------------------


def _finished_at(state, clock, data_dir, bid, when, outcome=Outcome.PROCESADO, with_dir=False):
    clock.now = when
    path = _job(state, data_dir, bid, outcome=outcome, with_dir=with_dir)
    clock.now = NOW
    return path


def test_purge_by_retention_only_touches_old_done_jobs(tmp_path, state, clock):
    """Review Focus 5: neither PENDING (being reprocessed) nor ERROR are purged even if old."""
    data_dir = tmp_path / "data"
    _finished_at(state, clock, data_dir, "viejo", NOW - timedelta(days=31))
    _finished_at(state, clock, data_dir, "reciente", NOW - timedelta(days=5))
    _finished_at(state, clock, data_dir, "reprocesando", NOW - timedelta(days=40), outcome=None)
    _finished_at(state, clock, data_dir, "roto", NOW - timedelta(days=40), outcome=Outcome.ERROR)
    assert state.get_job("reprocesando").status == JobStatus.PENDING

    touched = Cleaner(state, data_dir, 30, clock=clock).purge()

    assert touched == 1
    assert _stages(state, "viejo") == set()
    assert _stages(state, "reciente") == set(STAGES)
    assert _stages(state, "reprocesando") == set(STAGES)
    assert _stages(state, "roto") == set(STAGES)
    for bid in ("viejo", "reciente", "reprocesando", "roto"):
        assert state.has_job(bid)
        assert set(state.published(bid)) == {f"lugar:{bid}"}
    assert state.get_job("viejo").status == JobStatus.DONE


def test_purge_twice_does_not_count_again(tmp_path, state, clock):
    data_dir = tmp_path / "data"
    _finished_at(state, clock, data_dir, "viejo", NOW - timedelta(days=31))
    cleaner = Cleaner(state, data_dir, 30, clock=clock)

    assert cleaner.purge() == 1
    assert cleaner.purge() == 0


def test_purge_deletes_leftover_dirs_of_done_jobs_only(tmp_path, state, clock):
    data_dir = tmp_path / "data"
    done = _finished_at(state, clock, data_dir, "hecho", NOW - timedelta(days=2), with_dir=True)
    pending = _finished_at(state, clock, data_dir, "pendiente", NOW - timedelta(days=2), outcome=None, with_dir=True)
    error = _finished_at(state, clock, data_dir, "roto", NOW - timedelta(days=2), outcome=Outcome.ERROR, with_dir=True)
    unknown = data_dir / "jobs" / "desconocido"
    unknown.mkdir()
    (unknown / "keep.txt").write_text("x")
    stray = data_dir / "jobs" / "suelto.txt"
    stray.write_text("x")

    touched = Cleaner(state, data_dir, 30, clock=clock).purge()

    assert touched == 1
    assert not done.exists()
    assert (pending / "video.mp4").is_file()
    assert (error / "video.mp4").is_file()
    assert (unknown / "keep.txt").is_file()
    assert stray.is_file()
    # Without files, the fetch result is kept marked with files_purged; the others are untouched.
    assert _stages(state, "hecho") == set(STAGES)
    _assert_fetch_purged(state, "hecho")
    assert _stages(state, "pendiente") == set(STAGES) and _stages(state, "roto") == set(STAGES)
    for bid in ("pendiente", "roto"):
        assert state.load_stage(bid, "fetch", FetchResult).files_purged is False


def test_purge_counts_a_job_once_when_dir_and_results_are_purged(tmp_path, state, clock):
    data_dir = tmp_path / "data"
    old = _finished_at(state, clock, data_dir, "viejo", NOW - timedelta(days=31), with_dir=True)

    assert Cleaner(state, data_dir, 30, clock=clock).purge() == 1
    assert not old.exists() and _stages(state, "viejo") == set()


def test_purge_without_jobs_dir_is_a_no_op(tmp_path, state, clock):
    assert Cleaner(state, tmp_path / "data", 30, clock=clock).purge() == 0
    assert not (tmp_path / "data" / "jobs").exists()


# --- StateStore -----------------------------------------------------------------


def test_state_helpers(tmp_path, state, clock):
    data_dir = tmp_path / "data"
    _finished_at(state, clock, data_dir, "viejo", NOW - timedelta(days=31))
    _finished_at(state, clock, data_dir, "roto", NOW - timedelta(days=31), outcome=Outcome.ERROR)
    _finished_at(state, clock, data_dir, "pendiente", NOW - timedelta(days=31), outcome=None)

    assert state.done_job_ids() == {"viejo"}
    state.delete_stage("roto", "fetch")
    assert _stages(state, "roto") == {"transcribe", "extract"}
    assert state.purge_stage_results(NOW - timedelta(days=30)) == ["viejo"]
    assert state.purge_stage_results(NOW - timedelta(days=30)) == []
    state.delete_stages("pendiente")
    assert _stages(state, "pendiente") == set()
    assert set(state.published("pendiente")) == {"lugar:pendiente"}
