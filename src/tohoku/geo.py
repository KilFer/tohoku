import math
from collections.abc import Mapping, Sequence
from types import MappingProxyType

from tohoku.models import GeoMatch, Lugar
from tohoku.text import fold, normalize_name, similarity

NAME_SIMILARITY = 0.6
# Resultados empatados a menos de esta distancia son el mismo sitio (la zona y su punto de
# interés, el edificio y la torre...). Medido en casos reales: 4-165 m.
SAME_PLACE_RADIUS_M = 300
# Solo para comparar nombres (no para las claves de deduplicación): Google devuelve el nombre
# en español y el LLM a menudo en inglés o romaji ("Santuario Meiji" / "Meiji Shrine").
_NAME_EQUIVALENTS = {
    "shrine": ("santuario", "jinja", "jingu"),
    "temple": ("templo",),
    "tower": ("torre",),
    "lake": ("lago",),
    "station": ("estacion", "eki"),
    "castle": ("castillo",),
    "park": ("parque", "koen"),
    "garden": ("jardin", "jardines", "gardens"),
    "museum": ("museo",),
    "market": ("mercado",),
    "bridge": ("puente",),
    "island": ("isla",),
    "mount": ("monte", "mountain", "montana"),
    "street": ("calle",),
    "beach": ("playa",),
    "waterfall": ("cascada",),
    "center": ("centro", "centre"),
    "airport": ("aeropuerto",),
}
_NAME_STOPWORDS = {"de", "del", "la", "el", "los", "las", "of"}


def in_country(match: GeoMatch, code: str, names: Sequence[str], lat: tuple[float, float], lng: tuple[float, float]) -> bool:
    """El resultado está en el país del destino: dentro de sus límites y con su código (o su nombre en la dirección)."""
    inside = lat[0] <= match.lat <= lat[1] and lng[0] <= match.lng <= lng[1]
    if not inside:
        return False
    if match.country_code:
        return match.country_code.upper() == code.upper()
    # Sin postalAddress: el país tiene que aparecer en la dirección.
    # fold y no normalize_name: normalize_name elimina "japon"/"japan" por ser palabras genéricas.
    address = fold(match.address)
    return any(fold(word) in address for word in names)


def city_matches(match: GeoMatch, ciudad: str | None, aliases: Mapping[str, Sequence[str]] = MappingProxyType({})) -> bool:
    if not ciudad:
        return True
    city = fold(ciudad).strip()
    address = fold(f"{match.address} {match.area}")
    return any(fold(name) in address for name in [city, *aliases.get(city, [])])


def _canonical_words(aliases: Mapping[str, Sequence[str]]) -> dict[str, str]:
    words = {alias: canon for canon, alias_list in _NAME_EQUIVALENTS.items() for alias in alias_list}
    words |= {fold(alias): city for city, alias_list in aliases.items() for alias in alias_list}
    return words


def _name_words(text: str, canonical: Mapping[str, str]) -> list[str]:
    return [canonical.get(w, w) for w in normalize_name(text).split() if w not in _NAME_STOPWORDS]


def name_score(match: GeoMatch, lugar: Lugar, aliases: Mapping[str, Sequence[str]] = MappingProxyType({})) -> float:
    """Parecido entre el nombre de Google y el extraído: 2 = igual, 1 = uno contiene al otro, si no la similitud.

    "Igual" admite otro orden y palabras traducidas o alias de ciudad ("Torre de Kioto" = "Kyoto Tower").
    """
    canonical = _canonical_words(aliases)
    found_words = _name_words(match.name, canonical)
    found = " ".join(found_words)
    names = [lugar.nombre] + ([lugar.nombre_local] if lugar.nombre_local else [])
    best = 0.0
    for name in names:
        words = _name_words(name, canonical)
        w = " ".join(words)
        if not w or not found:
            continue
        if w == found or sorted(words) == sorted(found_words):
            return 2.0
        best = max(best, 1.0 if (w in found or found in w) else similarity(w, found))
    return best


def _haversine_m(lat_a: float, lng_a: float, lat_b: float, lng_b: float) -> float:
    lat1, lat2 = math.radians(lat_a), math.radians(lat_b)
    dlat, dlng = lat2 - lat1, math.radians(lng_b - lng_a)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(h))


def distance_m(a: GeoMatch, b: GeoMatch) -> float:
    """Distancia en metros (haversine)."""
    return _haversine_m(a.lat, a.lng, b.lat, b.lng)


def near_notes(notes: list, match: GeoMatch) -> list:
    """Notas (con etiqueta `geolocation="lat,lng"`) a menos de SAME_PLACE_RADIUS_M de `match`.

    Google a veces tiene dos fichas para el mismo sitio (Omoide Yokocho: dos placeId a 45 m).
    """
    near = []
    for note in notes:
        try:
            lat, lng = (float(x) for x in (note.label("geolocation") or "").split(","))
        except ValueError:
            continue
        if _haversine_m(lat, lng, match.lat, match.lng) <= SAME_PLACE_RADIUS_M:
            near.append(note)
    return near


def name_matches(match: GeoMatch, lugar: Lugar, aliases: Mapping[str, Sequence[str]] = MappingProxyType({})) -> bool:
    return name_score(match, lugar, aliases) >= NAME_SIMILARITY
