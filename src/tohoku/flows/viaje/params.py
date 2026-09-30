from pydantic import BaseModel, ConfigDict, Field

from tohoku.geo import CITY_ALIASES
from tohoku.models import LUGAR_CATEGORIAS
from tohoku.trilium_layout import CATEGORIES


class ViajeParams(BaseModel):
    """Parámetros de un destino del flujo `viaje`. Por defecto, los de Japón (antes eran constantes)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    pais: str = Field("JP", pattern=r"^[A-Z]{2}$")  # ISO 3166-1: regionCode de Places y país esperado
    # Para reconocer el país en una dirección sin postalAddress (en minúsculas y sin acentos).
    nombres_pais: list[str] = Field(default_factory=lambda: ["japon", "japan", "日本"])
    latitud: tuple[float, float] = (20.0, 46.0)
    longitud: tuple[float, float] = (122.0, 154.0)
    categorias_lugar: list[str] = Field(default_factory=lambda: list(LUGAR_CATEGORIAS), min_length=1)
    categorias_cosa: dict[str, str] = Field(default_factory=lambda: dict(CATEGORIES), min_length=1)
    alias_ciudad: dict[str, list[str]] = Field(default_factory=lambda: {k: list(v) for k, v in CITY_ALIASES.items()})
