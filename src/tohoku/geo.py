import math
from collections.abc import Mapping, Sequence
from types import MappingProxyType

from tohoku.models import GeoMatch, Lugar
from tohoku.text import fold, normalize_name, similarity

NAME_SIMILARITY = 0.6
# Tied results closer than this distance are the same place (the area and its point of
# interest, the building and the tower...). Measured on real cases: 4-165 m.
SAME_PLACE_RADIUS_M = 300
# Only for comparing names (not for dedup keys): Google returns the name
# in Spanish and the LLM often in English or romaji ("Santuario Meiji" / "Meiji Shrine").
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
    """The result is in the destination's country: within its bounds and with its code (or its name in the address)."""
    inside = lat[0] <= match.lat <= lat[1] and lng[0] <= match.lng <= lng[1]
    if not inside:
        return False
    if match.country_code:
        return match.country_code.upper() == code.upper()
    # Without postalAddress: the country has to appear in the address.
    # fold and not normalize_name: normalize_name removes generic words and could strip part of the country name.
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
    """Similarity between Google's name and the extracted one: 2 = equal, 1 = one contains the other, otherwise the similarity ratio.

    "Equal" allows a different word order and translated words or city aliases ("Torre de Kioto" = "Kyoto Tower").
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
    """Distance in meters (haversine)."""
    return _haversine_m(a.lat, a.lng, b.lat, b.lng)


def near_notes(notes: list, match: GeoMatch) -> list:
    """Notes (with label `geolocation="lat,lng"`) within SAME_PLACE_RADIUS_M of `match`.

    Google sometimes has two listings for the same place (Omoide Yokocho: two placeIds 45 m apart).
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
