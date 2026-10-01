from dataclasses import dataclass

from tohoku.clients.trilium import TNote, TriliumClient
from tohoku.errors import ConfigError
from tohoku.flows.receta.params import RecetaParams
from tohoku.trilium_layout import find_one, root_note

TEMPLATE_RECETA = "Receta"
_RECETARIO = "Recetario"
_REVISION = "Bandeja de revisión"
_PLANTILLAS = "Plantillas"


@dataclass(frozen=True)
class RecetaLayout:
    root: str
    recetario: str
    revision: str
    plantillas: str
    plantilla_receta: str


def _find_template(trilium: TriliumClient, plantillas: str) -> TNote | None:
    # Se busca por título: los atributos de una plantilla se heredan a las notas que la usan.
    return next((n for n in trilium.search("#template", ancestor=plantillas, ancestor_depth="eq1") if n.title == TEMPLATE_RECETA), None)


def resolve_receta_layout(trilium: TriliumClient, root_label: str) -> RecetaLayout:
    root = root_note(trilium, root_label)
    ids: dict[str, str] = {}
    for label in ("jrColeccion", "jrRevision", "jrPlantillas"):
        note = find_one(trilium, f"#{label}", root.note_id)
        if note is None:
            raise ConfigError(f"Falta la nota #{label} en Trilium; ejecuta 'tohoku init-trilium --destino …'")
        ids[label] = note.note_id
    plantilla = _find_template(trilium, ids["jrPlantillas"])
    if plantilla is None:
        raise ConfigError(f"Falta la plantilla '{TEMPLATE_RECETA}' en Trilium; ejecuta 'tohoku init-trilium --destino …'")
    return RecetaLayout(
        root=root.note_id,
        recetario=ids["jrColeccion"],
        revision=ids["jrRevision"],
        plantillas=ids["jrPlantillas"],
        plantilla_receta=plantilla.note_id,
    )


def init_receta_layout(trilium: TriliumClient, root_label: str, params: RecetaParams) -> RecetaLayout:
    """Crea bajo la raíz lo que falte. Idempotente.

    La plantilla `Receta` no se asigna al Recetario: `publish` la pone (`~template`) a cada nota al crearla.
    """
    root = root_note(trilium, root_label).note_id

    def ensure(label: str, title: str, labels: dict[str, str], type: str = "text") -> str:
        existing = find_one(trilium, f"#{label}", root)
        if existing:
            return existing.note_id
        note = trilium.create_note(root, title, type, "")
        for name, value in {label: "", **labels}.items():
            trilium.add_label(note.note_id, name, value)
        return note.note_id

    ensure("jrColeccion", _RECETARIO, {"viewType": params.vista}, type="book")
    ensure("jrRevision", _REVISION, {})
    plantillas = ensure("jrPlantillas", _PLANTILLAS, {})
    if _find_template(trilium, plantillas) is None:
        note = trilium.create_note(plantillas, TEMPLATE_RECETA, "text", "")
        trilium.add_label(note.note_id, "template", "")
        for nombre, tipo in params.atributos.items():
            trilium.add_label(note.note_id, f"label:{nombre}", f"promoted,single,{tipo}")
    return resolve_receta_layout(trilium, root_label)
