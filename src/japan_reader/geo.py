from japan_reader.models import GeoMatch, Lugar
from japan_reader.text import fold, normalize_name, similarity

_LAT_RANGE = (20.0, 46.0)
_LNG_RANGE = (122.0, 154.0)
_JAPAN_WORDS = ("japon", "japan", "日本")
CITY_ALIASES: dict[str, list[str]] = {
    "tokio": ["tokyo", "東京"],
    "kioto": ["kyoto", "京都"],
    "osaka": ["大阪"],
    "nara": ["奈良"],
    "hiroshima": ["広島"],
    "sapporo": ["札幌"],
    "fukuoka": ["福岡"],
    "kobe": ["神戸"],
    "yokohama": ["横浜"],
    "nagoya": ["名古屋"],
    "kanazawa": ["金沢"],
    "hakone": ["箱根"],
    "nikko": ["日光"],
    "kamakura": ["鎌倉"],
}
NAME_SIMILARITY = 0.6


def in_japan(match: GeoMatch) -> bool:
    inside = _LAT_RANGE[0] <= match.lat <= _LAT_RANGE[1] and _LNG_RANGE[0] <= match.lng <= _LNG_RANGE[1]
    if not inside:
        return False
    if match.country_code:
        return match.country_code.upper() == "JP"
    # Sin postalAddress: el país tiene que aparecer en la dirección.
    # fold y no normalize_name: normalize_name elimina "japon"/"japan" por ser palabras genéricas.
    address = fold(match.address)
    return any(word in address for word in _JAPAN_WORDS)


def city_matches(match: GeoMatch, ciudad: str | None) -> bool:
    if not ciudad:
        return True
    city = fold(ciudad).strip()
    address = fold(f"{match.address} {match.area}")
    return any(fold(name) in address for name in [city, *CITY_ALIASES.get(city, [])])


def name_matches(match: GeoMatch, lugar: Lugar) -> bool:
    found = normalize_name(match.name)
    wanted = [normalize_name(lugar.nombre)] + ([normalize_name(lugar.nombre_local)] if lugar.nombre_local else [])
    return any(w and (w in found or found in w or similarity(w, found) >= NAME_SIMILARITY) for w in wanted)
