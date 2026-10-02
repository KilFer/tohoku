from pydantic import BaseModel, ConfigDict, Field, field_validator


class ViajeParams(BaseModel):
    """Parámetros de un destino del flujo `viaje`.

    No hay valores por defecto de ningún país: cada destino declara los suyos en `config/destinos.yaml`
    (el bloque `japon` de `config/destinos.example.yaml` es el ejemplo de referencia). Solo `alias_ciudad`
    es opcional.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    pais: str = Field(pattern=r"^[A-Z]{2}$")  # ISO 3166-1: regionCode de Places y país esperado
    # Para reconocer el país en una dirección sin postalAddress (en minúsculas y sin acentos).
    nombres_pais: list[str]
    latitud: tuple[float, float]
    longitud: tuple[float, float]
    categorias_lugar: list[str] = Field(min_length=1)
    categorias_cosa: dict[str, str] = Field(min_length=1)
    alias_ciudad: dict[str, list[str]] = Field(default_factory=dict)

    @field_validator("nombres_pais")
    @classmethod
    def _sin_nombres_vacios(cls, value: list[str]) -> list[str]:
        # Un nombre vacío casaría con cualquier dirección en geo.in_country.
        if any(not n.strip() for n in value):
            raise ValueError("nombres_pais no puede contener entradas vacías")
        return value
