from types import SimpleNamespace

import pytest

from builders import make_meta
from fakes import FakeTrilium
from tohoku.models import PublishedNote
from tohoku.publishing import create_failure_note, sync_labels, sync_review, upsert_labels
from tohoku.state import StateStore
from tohoku.trilium_layout import init_layout


@pytest.fixture
def env(tmp_path):
    trilium = FakeTrilium()
    viajes = trilium.add_note("root", "Viajes")
    trilium.add_note(viajes, "Ideas de Japón", labels={"jrRoot": ""})
    layout = init_layout(trilium)
    note_id = trilium.add_note(layout.mapa, "Lugar")
    return SimpleNamespace(trilium=trilium, layout=layout, state=StateStore(tmp_path / "state.db"), note_id=note_id)


def _review(env, reasons, bookmark_id="b1", key="lugar:0"):
    sync_review(env.trilium, env.state, env.note_id, reasons, bookmark_id, key, env.layout.revision)


def test_review_enters_inbox_with_reasons(env):
    _review(env, ["baja-confianza"])

    note = env.trilium.get_note(env.note_id)
    assert set(note.parent_note_ids) == {env.layout.mapa, env.layout.revision}
    assert env.trilium.labels(env.note_id)["revisar"] == "baja-confianza"


def test_review_updates_revisar_label(env):
    _review(env, ["baja-confianza"])
    _review(env, ["baja-confianza", "geocodificacion-ambigua"])

    assert env.trilium.labels(env.note_id)["revisar"] == "baja-confianza,geocodificacion-ambigua"


def test_review_leaves_inbox_when_reasons_resolved(env):
    _review(env, ["baja-confianza"])
    _review(env, [])

    assert env.trilium.get_note(env.note_id).parent_note_ids == [env.layout.mapa]
    assert "revisar" not in env.trilium.labels(env.note_id)


def test_review_keeps_note_while_another_source_has_reasons(env):
    env.state.record_publish("b2", PublishedNote(key="lugar:0", note_id=env.note_id, action="merge", review_reasons=["otra"]))
    _review(env, ["baja-confianza"])
    _review(env, [])

    assert env.layout.revision in env.trilium.get_note(env.note_id).parent_note_ids
    assert env.trilium.labels(env.note_id)["revisar"] == "otra"


def test_review_respects_note_user_took_out_of_inbox(env):
    env.state.record_publish("b2", PublishedNote(key="lugar:0", note_id=env.note_id, action="merge", review_reasons=["otra"]))
    _review(env, ["baja-confianza"])
    env.trilium.remove_from_parent(env.note_id, env.layout.revision)

    _review(env, [])

    assert env.trilium.get_note(env.note_id).parent_note_ids == [env.layout.mapa]


def test_create_failure_note_creates_then_resumes(env):
    meta = make_meta(url="https://youtu.be/b1")
    first = create_failure_note(env.trilium, env.layout.root, env.layout.revision, "b1", meta, "texto", "error x")
    second = create_failure_note(env.trilium, env.layout.root, env.layout.revision, "b1", meta, "texto", "error y")

    assert first == second
    labels = env.trilium.labels(first)
    assert labels["jrItem"] == "b1:fallo" and labels["jrTipo"] == "fallo"
    assert env.trilium.get_note(first).parent_note_ids == [env.layout.revision]
    assert "error y" in env.trilium.get_content(first)


def test_labels_helpers_are_reexported_from_publish():
    from tohoku.stages import publish

    assert publish.upsert_labels is upsert_labels and publish.sync_labels is sync_labels
