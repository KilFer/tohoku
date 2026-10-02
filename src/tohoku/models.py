from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from tohoku.sources import Platform



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
    # Cleanup deleted the job's files; the metadata is still valid. Stages with `needs_files` download again.
    files_purged: bool = False


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
    categoria: str
    que_es: str
    que_hacer: str = ""
    consejos: list[str] = []
    precio_aprox: str | None = None
    confianza: float = Field(ge=0, le=1)


class Cosa(BaseModel):
    nombre: str
    categoria: str
    que_es: str
    consejos: list[str] = []
    donde: list[str] = []
    donde_lugares: list[str] = []
    confianza: float = Field(ge=0, le=1)


class Otro(BaseModel):
    titulo: str
    contenido: str


class Extraction(BaseModel):
    relacionado_destino: bool
    confianza_destino: float = Field(ge=0, le=1)
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
    country_code: str | None = None  # postalAddress.regionCode or country from addressComponents (ISO 3166-1), e.g. "JP"
    area: str = ""  # prefecture, locality and lines of postalAddress / addressComponents (to check the city)


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
    RECETA = "receta"
    FALLO = "fallo"


class PlannedItem(BaseModel):
    """Decision of `resolve` for one item. `index=-1` on OTRO = synthetic note built from the source summary."""

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
    DESCARTADO = "descartado"
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
    destination_tag: str | None = None


class MergeOutput(BaseModel):
    resumen: str
    que_hacer: str = ""
    consejos: list[str] = []


class Classification(BaseModel):
    """Resultado de la etapa `classify`."""

    destino: str | None  # None → DESCARTADO (discarded)
    confianza: float = 1.0
    alternativa: str | None = None
    confianza_alternativa: float = 0.0
    omitido: bool = False  # no call made: a single candidate or forced destination
    dudosa: bool = False  # alternative within margen_revision → clasificacion-dudosa
    cost_usd: float = 0.0
