import httpx

from tohoku.clients.http import send
from tohoku.errors import ApiError, ConfigError
from tohoku.models import GeoMatch

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
# Only fields of the "Text Search Pro" SKU (5,000 free calls per month). Do not add Enterprise fields.
# postalAddress is Pro and carries the country: with regionCode=JP, formattedAddress omits it.
# Areas (cities, neighbourhoods, islands) have no postalAddress: country and city come from
# addressComponents (also Pro).
FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,places.location,"
    "places.googleMapsUri,places.types,places.postalAddress,places.addressComponents"
)
_AREA_COMPONENTS = {"administrative_area_level_1", "administrative_area_level_2", "locality", "sublocality", "colloquial_area"}


class PlacesClient:
    SERVICE = "google-places"

    def __init__(self, api_key: str, http: httpx.Client | None = None) -> None:
        self._http = http or httpx.Client(timeout=30)
        self._headers = {"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": FIELD_MASK}

    def search(self, query: str, region: str = "JP") -> list[GeoMatch]:
        body = {"textQuery": query, "regionCode": region, "languageCode": "es", "pageSize": 5}
        try:
            resp = send(self._http, "POST", SEARCH_URL, self.SERVICE, headers=self._headers, json=body)
        except ApiError as exc:
            if exc.status == 400 and "api key" in str(exc).lower():
                raise ConfigError("google-places: API key inválida") from exc
            raise
        matches = []
        for place in resp.json().get("places", []):
            if "location" not in place:
                continue
            postal = place.get("postalAddress") or {}
            components = place.get("addressComponents") or []
            country = next((c.get("shortText") for c in components if "country" in c.get("types", [])), None)
            area_parts = [
                postal.get("administrativeArea"), postal.get("locality"), *postal.get("addressLines", []),
                *(c.get("longText") for c in components if _AREA_COMPONENTS & set(c.get("types", []))),
            ]
            matches.append(
                GeoMatch(
                    place_id=place["id"],
                    name=(place.get("displayName") or {}).get("text", ""),
                    address=place.get("formattedAddress", ""),
                    lat=place["location"]["latitude"],
                    lng=place["location"]["longitude"],
                    maps_url=place.get("googleMapsUri", ""),
                    types=place.get("types", []),
                    country_code=postal.get("regionCode") or country,
                    area=" ".join(dict.fromkeys(part for part in area_parts if part)),
                )
            )
        return matches
