"""Utilidades de publicación en Trilium compartidas por los flujos (viaje, receta)."""

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
    """Como `upsert_labels`, pero respeta las correcciones del usuario en una nota existente.

    Un atributo gestionado se reescribe solo si falta o si sigue teniendo el valor que el servicio
    escribió la última vez (`old_labels`, calculado del adjunto anterior). Los de `always`
    (`jrTipo` y `fuentes` por defecto) se escriben siempre.
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
    """Mantiene la Bandeja y `#revisar` al día con los motivos vigentes de todas las fuentes de la nota.

    `reasons` son los motivos del elemento que se acaba de publicar.
    - El elemento trae motivos → la nota va (o sigue) en la Bandeja.
    - No trae y ninguna fuente tiene ya motivos → sale de la Bandeja y se borra `#revisar`.
    - No trae pero otra fuente sí: si sigue en la Bandeja se actualiza `#revisar`; si el usuario
      ya la sacó, se respeta.
    `#revisar` es la unión de los motivos vigentes (no se acumulan motivos ya resueltos).
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
    """Crea (o retoma por `#jrItem="<id>:fallo"`) la nota de extracción fallida en la Bandeja."""
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
