from collections.abc import Callable, Mapping
from dataclasses import dataclass

from tohoku.clients.trilium import TNote, TriliumClient
from tohoku.errors import ConfigError

CATEGORIES: dict[str, str] = {
    "souvenirs": "Souvenirs",
    "comida": "Comida",
    "cadenas": "Cadenas",
    "cosmetica": "Cosmética",
    "otros": "Otros",
}
GEO_MAP_TEMPLATE = "_template_geo_map"
_SECTIONS = {
    "jrMapa": "Mapa de lugares",
    "jrComprar": "Comprar y comer",
    "jrCultura": "Cultura y curiosidades",
    "jrRevision": "Bandeja de revisión",
    "jrPlantillas": "Plantillas",
}
TEMPLATE_LUGAR = "Lugar"
TEMPLATE_COSA = "Cosa"
_TEMPLATE_LABELS = {
    TEMPLATE_LUGAR: {
        "label:visitado": "promoted,single,boolean",
        "label:prioridad": "promoted,single,number",
        "label:ciudad": "promoted,single,text",
        "label:categoria": "promoted,single,text",
    },
    TEMPLATE_COSA: {
        "label:comprado": "promoted,single,boolean",
        "label:categoria": "promoted,single,text",
    },
}


@dataclass(frozen=True)
class Layout:
    root: str
    mapa: str
    comprar: str
    cultura: str
    revision: str
    plantillas: str
    plantilla_lugar: str
    plantilla_cosa: str
    categorias: dict[str, str]


def find_one(trilium: TriliumClient, query: str, ancestor: str | None = None, depth: str | None = None) -> TNote | None:
    found = trilium.search(query, ancestor=ancestor, ancestor_depth=depth)
    if len(found) > 1:
        raise ConfigError(f"Hay {len(found)} notas que cumplen '{query}' en Trilium; debe haber solo una")
    return found[0] if found else None



def find_template(trilium: TriliumClient, plantillas: str, title: str) -> TNote | None:
    # Las plantillas se buscan por título: sus atributos se heredan a las notas que las usan.
    return next((n for n in trilium.search("#template", ancestor=plantillas, ancestor_depth="eq1") if n.title == title), None)



def root_note(trilium: TriliumClient, root_label: str) -> TNote:
    root = find_one(trilium, f"#{root_label}")
    if root is None:
        raise ConfigError(f"No se encuentra la nota raíz con #{root_label}. Añade esa etiqueta a la nota raíz del destino en Trilium.")
    return root



# Las notas de estructura se buscan solo como hijas directas (eq1): así una raíz de otro destino anidada no choca.
def resolve_layout(trilium: TriliumClient, root_label: str = "jrRoot", categorias: Mapping[str, str] = CATEGORIES) -> Layout:
    root = root_note(trilium, root_label)
    ids: dict[str, str] = {}
    for label in _SECTIONS:
        note = find_one(trilium, f"#{label}", root.note_id, depth="eq1")
        if note is None:
            raise ConfigError(f"Falta la nota #{label} en Trilium; ejecuta 'tohoku init-trilium'")
        ids[label] = note.note_id
    resueltas: dict[str, str] = {}
    for key in categorias:
        note = find_one(trilium, f"#jrCategoria={key}", ids["jrComprar"], depth="eq1")
        if note is None:
            raise ConfigError(f"Falta la categoría '{key}' en Trilium; ejecuta 'tohoku init-trilium'")
        resueltas[key] = note.note_id
    templates = {}
    for title in (TEMPLATE_LUGAR, TEMPLATE_COSA):
        note = find_template(trilium, ids["jrPlantillas"], title)
        if note is None:
            raise ConfigError(f"Falta la plantilla '{title}' en Trilium; ejecuta 'tohoku init-trilium'")
        templates[title] = note.note_id
    return Layout(
        root=root.note_id,
        mapa=ids["jrMapa"],
        comprar=ids["jrComprar"],
        cultura=ids["jrCultura"],
        revision=ids["jrRevision"],
        plantillas=ids["jrPlantillas"],
        plantilla_lugar=templates[TEMPLATE_LUGAR],
        plantilla_cosa=templates[TEMPLATE_COSA],
        categorias=resueltas,
    )


def init_layout(trilium: TriliumClient, root_label: str = "jrRoot", categorias: Mapping[str, str] = CATEGORIES) -> Layout:
    """Crea bajo la raíz lo que falte. Idempotente."""
    root = root_note(trilium, root_label).note_id

    def ensure(query: str, ancestor: str, parent: str, title: str, labels: dict[str, str], **kwargs) -> str:
        existing = find_one(trilium, query, ancestor, depth="eq1")
        if existing:
            return existing.note_id
        note = trilium.create_note(parent, title, kwargs.get("type", "text"), "")
        for name, value in labels.items():
            trilium.add_label(note.note_id, name, value)
        for name, target in kwargs.get("relations", {}).items():
            trilium.add_relation(note.note_id, name, target)
        return note.note_id

    ensure("#jrMapa", root, root, _SECTIONS["jrMapa"], {"jrMapa": ""}, type="book", relations={"template": GEO_MAP_TEMPLATE})
    comprar = ensure("#jrComprar", root, root, _SECTIONS["jrComprar"], {"jrComprar": ""})
    for key, title in categorias.items():
        ensure(f"#jrCategoria={key}", comprar, comprar, title, {"jrCategoria": key})
    ensure("#jrCultura", root, root, _SECTIONS["jrCultura"], {"jrCultura": ""})
    ensure("#jrRevision", root, root, _SECTIONS["jrRevision"], {"jrRevision": ""})
    plantillas = ensure("#jrPlantillas", root, root, _SECTIONS["jrPlantillas"], {"jrPlantillas": ""})
    for title, labels in _TEMPLATE_LABELS.items():
        if find_template(trilium, plantillas, title) is None:
            note = trilium.create_note(plantillas, title, "text", "")
            trilium.add_label(note.note_id, "template", "")
            for name, value in labels.items():
                trilium.add_label(note.note_id, name, value)
    return resolve_layout(trilium, root_label, categorias)


class LayoutCache:
    """Resuelve la estructura una vez y la reutiliza; `refresh()` fuerza releerla."""

    def __init__(self, loader: Callable[[], Layout]) -> None:
        self._loader = loader
        self._layout: Layout | None = None

    def __call__(self) -> Layout:
        if self._layout is None:
            self._layout = self._loader()
        return self._layout

    def refresh(self) -> Layout:
        self._layout = self._loader()
        return self._layout
