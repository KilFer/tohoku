"""Trilium publishing utilities shared by the flows (viaje, receta)."""

from tohoku.clients.trilium import TNote, TriliumClient
from tohoku.models import SourceMeta
from tohoku.notes import ALWAYS_WRITTEN_LABELS, render_failure
from tohoku.state import StateStore


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def upsert_labels(trilium: TriliumClient, note: TNote, labels: dict[str, str]) -> None:
    for name, value in labels.items():
        current = note.attr("label", name)
        if current is None:
            trilium.add_label(note.note_id, name, value)
        elif current.value != value:
            trilium.update_attribute(current.attribute_id, value)


def sync_labels(
    trilium: TriliumClient,
    note: TNote,
    labels: dict[str, str],
    old_labels: dict[str, str],
    always: frozenset[str] = ALWAYS_WRITTEN_LABELS,
) -> None:
    """Like `upsert_labels`, but respects the user's corrections on an existing note.

    A managed attribute is rewritten only if it is missing or still has the value the service
    wrote last time (`old_labels`, computed from the previous attachment). Those in `always`
    (`jrTipo` and `fuentes` by default) are always written.
    """
    for name, value in labels.items():
        current = note.attr("label", name)
        if current is None:
            trilium.add_label(note.note_id, name, value)
        elif current.value != value and (name in always or current.value == old_labels.get(name)):
            trilium.update_attribute(current.attribute_id, value)


def sync_review(
    trilium: TriliumClient,
    state: StateStore,
    note_id: str,
    reasons: list[str],
    bookmark_id: str,
    item_key: str,
    revision_id: str,
) -> None:
    """Keeps the Bandeja (review tray) and `#revisar` up to date with the current reasons of all the note's sources.

    `reasons` are the reasons of the item that was just published.
    - The item has reasons → the note goes (or stays) in the Bandeja.
    - It has none and no source has reasons any more → it leaves the Bandeja and `#revisar` is deleted.
    - It has none but another source does: if it is still in the Bandeja `#revisar` is updated; if the user
      already took it out, that is respected.
    `#revisar` is the union of the current reasons (already-resolved reasons are not accumulated).
    """
    all_reasons = _unique(reasons + state.review_reasons_for_note(note_id, exclude=(bookmark_id, item_key)))
    note = trilium.get_note(note_id)
    in_inbox = revision_id in note.parent_note_ids
    label = note.attr("label", "revisar")
    if reasons or (all_reasons and in_inbox):
        if not in_inbox:
            trilium.clone(note_id, revision_id)
        upsert_labels(trilium, note, {"revisar": ",".join(all_reasons)})
        return
    if all_reasons:
        return
    if in_inbox:
        trilium.remove_from_parent(note_id, revision_id)
    if label is not None:
        trilium.delete_attribute(label.attribute_id)


def create_failure_note(
    trilium: TriliumClient,
    root_id: str,
    revision_id: str,
    bookmark_id: str,
    meta: SourceMeta,
    transcript: str,
    error: str,
) -> str:
    """Creates (or resumes via `#jrItem="<id>:fallo"`) the failed-extraction note in the Bandeja."""
    item_id = f"{bookmark_id}:fallo"
    found = trilium.search(f'#jrItem="{item_id}"', ancestor=root_id)
    if found:
        note = found[0]
        upsert_labels(trilium, note, {"jrTipo": "fallo"})
        note_id = note.note_id
    else:
        note = trilium.create_note(revision_id, f"Extracción fallida: {meta.title or meta.url}", "text", "")
        trilium.add_label(note.note_id, "jrItem", item_id)
        trilium.add_label(note.note_id, "jrTipo", "fallo")
        note_id = note.note_id
    trilium.set_content(note_id, render_failure(meta, transcript, error))
    return note_id
