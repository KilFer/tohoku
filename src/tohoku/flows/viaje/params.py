from pydantic import BaseModel, ConfigDict, Field, field_validator


class ViajeParams(BaseModel):
    """Parameters of a destination of the `viaje` flow.

    There are no per-country defaults: every destination declares its own in `config/destinos.yaml`
    (the `japon` block of `config/destinos.example.yaml` is the reference example). Only `alias_ciudad`
    is optional.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    pais: str = Field(pattern=r"^[A-Z]{2}$")  # ISO 3166-1: Places regionCode and expected country
    # To recognise the country in an address without postalAddress (lowercase, no accents).
    nombres_pais: list[str]
    latitud: tuple[float, float]
    longitud: tuple[float, float]
    categorias_lugar: list[str] = Field(min_length=1)
    categorias_cosa: dict[str, str] = Field(min_length=1)
    alias_ciudad: dict[str, list[str]] = Field(default_factory=dict)

    @field_validator("nombres_pais")
    @classmethod
    def _sin_nombres_vacios(cls, value: list[str]) -> list[str]:
        # An empty name would match any address in geo.in_country.
        if any(not n.strip() for n in value):
            raise ValueError("nombres_pais no puede contener entradas vacías")
        return value
