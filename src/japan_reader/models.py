from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from japan_reader.sources import Platform

LUGAR_CATEGORIAS = (
    "templo", "santuario", "comida", "cafe", "bar", "tienda", "mercado", "mirador",
    "barrio", "museo", "parque", "onsen", "alojamiento", "transporte", "otro",
)
COSA_CATEGORIAS = ("souvenirs", "comida", "cadenas", "cosmetica", "otros")

LugarCategoria = Literal[
    "templo", "santuario", "comida", "cafe", "bar", "tienda", "mercado", "mirador",
    "barrio", "museo", "parque", "onsen", "alojamiento", "transporte", "otro",
]
CosaCategoria = Literal["souvenirs", "comida", "cadenas", "cosmetica", "otros"]


class ContentType(StrEnum):
    VIDEO = "video"
    IMAGE = "image"
    CAROUSEL = "carousel"


class SourceMeta(BaseModel):
    url: str
    platform: Platform
    content_type: ContentType
    title: str | None = None
    description: str | None = None
    hashtags: list[str] = []
    author: str | None = None
    published: str | None = None
    duration_s: float | None = None


class FetchResult(BaseModel):
    """Salida de `fetch`. Las rutas son relativas al directorio del job."""

    meta: SourceMeta
    audio_files: list[str] = []
    subtitles: str | None = None
    images: list[str] = []
    keyframes: list[str] = []


class Transcript(BaseModel):
    text: str = ""
    language: str | None = None
    origin: Literal["subtitulos", "whisper", "none"] = "none"


class Lugar(BaseModel):
    nombre: str
    nombre_local: str | None = None
    consulta_busqueda: str
    ciudad: str | None = None
    region: str | None = None
    categoria: LugarCategoria
    que_es: str
    que_hacer: str = ""
    consejos: list[str] = []
    precio_aprox: str | None = None
    confianza: float = Field(ge=0, le=1)


class Cosa(BaseModel):
    nombre: str
    categoria: CosaCategoria
    que_es: str
    consejos: list[str] = []
    donde: list[str] = []
    donde_lugares: list[str] = []
    confianza: float = Field(ge=0, le=1)


class Otro(BaseModel):
    titulo: str
    contenido: str


class Extraction(BaseModel):
    relacionado_japon: bool
    confianza_japon: float = Field(ge=0, le=1)
    idioma: str
    resumen_fuente: str
    lugares: list[Lugar] = []
    cosas: list[Cosa] = []
    otros: list[Otro] = []


class ExtractResult(BaseModel):
    extraction: Extraction | None = None
    error: str | None = None
    cost_usd: float = 0.0


class GeoMatch(BaseModel):
    place_id: str
    name: str
    address: str
    lat: float
    lng: float
    maps_url: str
    types: list[str] = []


class GeoOutcome(BaseModel):
    lugar_index: int
    match: GeoMatch | None = None
    review_reason: str | None = None


class GeocodeResult(BaseModel):
    outcomes: list[GeoOutcome] = []


class ItemKind(StrEnum):
    LUGAR = "lugar"
    COSA = "cosa"
    OTRO = "otro"
    FALLO = "fallo"


class PlannedItem(BaseModel):
    """Decisión de `resolve` para un elemento. `index=-1` en OTRO = nota sintética del resumen."""

    key: str
    kind: ItemKind
    index: int
    action: Literal["create", "merge", "alias"]
    existing_note_id: str | None = None
    alias_of: str | None = None
    review_reasons: list[str] = []


class ResolveResult(BaseModel):
    items: list[PlannedItem] = []


class Outcome(StrEnum):
    PROCESADO = "procesado"
    REVISAR = "revisar"
    NO_JAPON = "no-japon"
    ERROR = "error"


class PublishedNote(BaseModel):
    key: str
    note_id: str
    action: Literal["create", "merge", "alias"]
    review_reasons: list[str] = []


class PublishResult(BaseModel):
    notes: list[PublishedNote] = []
    outcome: Outcome


class MarkResult(BaseModel):
    tag: str
    archived: bool


class MergeOutput(BaseModel):
    resumen: str
    que_hacer: str = ""
    consejos: list[str] = []
