import pytest

from fakes import FakeKarakeep
from japan_reader.clients.karakeep import Bookmark
from japan_reader.ingest import ingest
from japan_reader.models import Outcome
from japan_reader.sources import ContentHint, Platform
from japan_reader.stages.mark import MarkStage
from japan_reader.state import StateStore


@pytest.fixture
def state(tmp_path):
    return StateStore(tmp_path / "state.db")


def test_ingest_creates_jobs_for_new_supported_bookmarks(state):
    karakeep = FakeKarakeep([
        Bookmark(id="b1", url="https://www.youtube.com/shorts/abc"),
        Bookmark(id="b2", url="https://www.instagram.com/p/XYZ/"),
    ])

    report = ingest(karakeep, state, "L1")

    assert report.new == ["b1", "b2"]
    assert state.get_job("b2").platform == Platform.INSTAGRAM
    assert state.get_job("b2").hint == ContentHint.POST


def test_ingest_is_idempotent(state):
    karakeep = FakeKarakeep([Bookmark(id="b1", url="https://youtu.be/abc")])
    ingest(karakeep, state, "L1")
    assert ingest(karakeep, state, "L1").new == []


def test_ingest_registers_unsupported_without_platform(state):
    karakeep = FakeKarakeep([Bookmark(id="b1", url="https://www.tiktok.com/@u/video/1"), Bookmark(id="b2", url=None)])

    report = ingest(karakeep, state, "L1")

    assert report.unsupported == ["b1", "b2"]
    assert state.get_job("b1").platform is None


def test_ingest_skips_bookmarks_already_tagged_when_state_was_lost(state):
    """Review Focus 5: state.db recreado no reprocesa lo ya marcado."""
    karakeep = FakeKarakeep([
        Bookmark(id="b1", url="https://youtu.be/a", tags=["jr:procesado"], archived=True),
        Bookmark(id="b2", url="https://youtu.be/b", tags=["jr:error"]),
        Bookmark(id="b3", url="https://youtu.be/c", tags=["viaje"]),
    ])

    report = ingest(karakeep, state, "L1")

    assert report.new == ["b3"]
    assert not state.has_job("b1") and not state.has_job("b2")


@pytest.mark.parametrize(
    ("outcome", "tag", "archived"),
    [
        (Outcome.PROCESADO, "jr:procesado", True),
        (Outcome.REVISAR, "jr:revisar", True),
        (Outcome.NO_JAPON, "jr:no-japon", True),
        (Outcome.ERROR, "jr:error", False),
    ],
)
def test_mark_tags_and_archives(outcome, tag, archived):
    karakeep = FakeKarakeep([Bookmark(id="b1", url="https://youtu.be/a", tags=["jr:error", "viaje"])])

    result = MarkStage(karakeep).run("b1", outcome)

    bookmark = karakeep.bookmarks["b1"]
    assert result.tag == tag and result.archived is archived
    assert bookmark.archived is archived
    assert tag in bookmark.tags and "viaje" in bookmark.tags
    assert [t for t in bookmark.tags if t.startswith("jr:")] == [tag]
