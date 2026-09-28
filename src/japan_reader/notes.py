import re
from html import escape
from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter

from japan_reader.models import GeoMatch, SourceMeta
from japan_reader.text import normalize_name

DATA_ATTACHMENT_TITLE = "japan-reader.json"
MIS_NOTAS_HEADING = "<h2>Mis notas</h2>"
_MIS_NOTAS = re.compile(r"<h2[^>]*>(?:\s|<[^>]+>)*Mis notas(?:\s|<[^>]+>)*</h2>", re.I)
_EMPTY_PARAGRAPH = "<p></p>"

ICONS: dict[str, str] = {
    "templo": "bx bx-buildings",
    "santuario": "bx bx-buildings",
    "comida": "bx bx-bowl-hot",
    "cafe": "bx bx-coffee",
    "bar": "bx bx-drink",
    "tienda": "bx bx-shopping-bag",
    "mercado": "bx bx-store",
    "mirador": "bx bx-landscape",
    "barrio": "bx bx-map-alt",
    "museo": "bx bx-palette",
    "parque": "bx bx-leaf",
    "onsen": "bx bx-water",
    "alojamiento": "bx bx-bed",
    "transporte": "bx bx-train",
    "otro": "bx bx-map-pin",
}
COSA_ICON = "bx bx-shopping-bag"
OTRO_ICON = "bx bx-bulb"


class SourceEntry(BaseModel):
    bookmark_id: str
    url: str
    platform: str
    content_type: str
    title: str | None = None
    author: str | None = None
    published: str | None = None
    aporte: str = ""


class LugarData(BaseModel):
    kind: Literal["lugar"] = "lugar"
    nombre: str
    nombre_local: str | None = None
    ciudad: str | None = None
    region: str | None = None
    categoria: str
    resumen: str
    que_hacer: str = ""
    consejos: list[str] = []
    precio_aprox: str | None = None
    place: GeoMatch | None = None
    fuentes: list[SourceEntry] = []


class CosaData(BaseModel):
    kind: Literal["cosa"] = "cosa"
    nombre: str
    categoria: str
    resumen: str
    consejos: list[str] = []
    donde: list[str] = []
    fuentes: list[SourceEntry] = []


class OtroData(BaseModel):
    kind: Literal["otro"] = "otro"
    titulo: str
    contenido: str
    fuentes: list[SourceEntry] = []


NoteData = LugarData | CosaData | OtroData
_ADAPTER: TypeAdapter[NoteData] = TypeAdapter(Annotated[NoteData, Field(discriminator="kind")])


def dump_data(data: NoteData) -> str:
    return data.model_dump_json(indent=2)


def load_data(raw: str) -> NoteData:
    return _ADAPTER.validate_json(raw)


def note_title(data: NoteData) -> str:
    return data.titulo if isinstance(data, OtroData) else data.nombre


def source_entry(bookmark_id: str, meta: SourceMeta, aporte: str) -> SourceEntry:
    return SourceEntry(
        bookmark_id=bookmark_id, url=meta.url, platform=str(meta.platform), content_type=str(meta.content_type),
        title=meta.title, author=meta.author, published=meta.published, aporte=aporte,
    )


def add_source(data: NoteData, entry: SourceEntry) -> bool:
    for i, existing in enumerate(data.fuentes):
        if existing.bookmark_id == entry.bookmark_id:
            data.fuentes[i] = entry
            return False
    data.fuentes.append(entry)
    return True


def name_key(text: str) -> str:
    """Nombre normalizado usado como clave (`#jrNombreNorm`, `#jrItem`). Nunca vacío si hay texto."""
    return normalize_name(text) or text.casefold().replace('"', "").strip()


def item_identity(data: NoteData) -> str:
    """Parte de `#jrItem` que identifica el elemento por su contenido (no por su posición en la extracción)."""
    if isinstance(data, LugarData):
        return f"lugar:{data.place.place_id}" if data.place else f"lugar:n:{name_key(data.nombre)}"
    if isinstance(data, CosaData):
        return f"cosa:{name_key(data.nombre)}"
    return f"otro:{name_key(data.titulo)}"


# Atributos gestionados que se escriben siempre, aunque el usuario los haya cambiado.
ALWAYS_WRITTEN_LABELS = frozenset({"jrTipo", "fuentes"})


def labels_for(data: NoteData) -> dict[str, str]:
    """Atributos que el servicio gestiona. Nunca incluye los manuales (#visitado, #prioridad, #revisar)."""
    if isinstance(data, LugarData):
        labels = {
            "jrTipo": "lugar",
            "categoria": data.categoria,
            "fuentes": str(len(data.fuentes)),
            "iconClass": ICONS.get(data.categoria, ICONS["otro"]),
        }
        if data.ciudad:
            labels["ciudad"] = data.ciudad
        if data.region:
            labels["region"] = data.region
        if data.nombre_local:
            labels["nombreLocal"] = data.nombre_local
        if data.place:
            labels["geolocation"] = f"{data.place.lat},{data.place.lng}"
            labels["googlePlaceId"] = data.place.place_id
            labels["googleMaps"] = data.place.maps_url
        return labels
    if isinstance(data, CosaData):
        return {
            "jrTipo": "cosa",
            "jrNombreNorm": name_key(data.nombre),
            "categoria": data.categoria,
            "fuentes": str(len(data.fuentes)),
            "iconClass": COSA_ICON,
        }
    return {"jrTipo": "otro", "fuentes": str(len(data.fuentes)), "iconClass": OTRO_ICON}


def _p(text: str | None) -> str:
    return f"<p>{escape(text)}</p>" if text else ""


def _ul(items: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{escape(item)}</li>" for item in items) + "</ul>" if items else ""


def _sources(fuentes: list[SourceEntry]) -> str:
    items = []
    for f in fuentes:
        details = " · ".join(escape(x) for x in (f.author, f.platform, f.content_type, f.published) if x)
        aporte = f"<br>{escape(f.aporte)}" if f.aporte else ""
        items.append(f'<li><a href="{escape(f.url, quote=True)}">{escape(f.title or f.url)}</a> — {details}{aporte}</li>')
    return "<h2>Fuentes</h2><ul>" + "".join(items) + "</ul>"


def render_generated(data: NoteData) -> str:
    """Parte de la nota que genera el servicio (todo lo anterior a "Mis notas")."""
    parts: list[str] = []
    if isinstance(data, LugarData):
        parts += ["<h2>Resumen</h2>", _p(data.resumen)]
        if data.que_hacer:
            parts += ["<h2>Qué hacer / comer</h2>", _p(data.que_hacer)]
        consejos = [*data.consejos, *([f"Precio aproximado: {data.precio_aprox}"] if data.precio_aprox else [])]
        if consejos:
            parts += ["<h2>Consejos prácticos</h2>", _ul(consejos)]
        if data.place:
            parts.append(f'<p><a href="{escape(data.place.maps_url, quote=True)}">Abrir en Google Maps</a> · {escape(data.place.address)}</p>')
    elif isinstance(data, CosaData):
        parts += ["<h2>Resumen</h2>", _p(data.resumen)]
        if data.donde:
            parts += ["<h2>Dónde conseguirlo</h2>", _ul(data.donde)]
        if data.consejos:
            parts += ["<h2>Consejos</h2>", _ul(data.consejos)]
    else:
        parts.append(_p(data.contenido))
    parts.append(_sources(data.fuentes))
    return "".join(parts)


def compose_content(generated: str, existing: str | None) -> str:
    """Contenido generado + encabezado "Mis notas" + lo que el usuario tenga debajo (nunca se pierde)."""
    kept = _EMPTY_PARAGRAPH
    if existing and existing.strip():
        match = _MIS_NOTAS.search(existing)
        kept = (existing[match.end():] if match else existing) or _EMPTY_PARAGRAPH
    return generated + MIS_NOTAS_HEADING + kept


def render_failure(meta: SourceMeta, transcript: str, error: str) -> str:
    return (
        f'<p><a href="{escape(meta.url, quote=True)}">{escape(meta.url)}</a> — {escape(meta.author or "")}</p>'
        f"<h2>Error</h2>{_p(error)}"
        f"<h2>Descripción</h2>{_p(meta.description or '(vacía)')}"
        f"<h2>Transcripción</h2>{_p(transcript or '(sin transcripción)')}"
    )
