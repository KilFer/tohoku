import httpx

from japan_reader.clients.http import send
from japan_reader.errors import ApiError, ConfigError
from japan_reader.models import GeoMatch

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
# Solo campos del SKU "Text Search Pro" (5.000 llamadas gratis al mes). No añadir campos Enterprise.
FIELD_MASK = "places.id,places.displayName,places.formattedAddress,places.location,places.googleMapsUri,places.types"


class PlacesClient:
    SERVICE = "google-places"

    def __init__(self, api_key: str, http: httpx.Client | None = None) -> None:
        self._http = http or httpx.Client(timeout=30)
        self._headers = {"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": FIELD_MASK}

    def search(self, query: str) -> list[GeoMatch]:
        body = {"textQuery": query, "regionCode": "JP", "languageCode": "es", "pageSize": 5}
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
            matches.append(
                GeoMatch(
                    place_id=place["id"],
                    name=(place.get("displayName") or {}).get("text", ""),
                    address=place.get("formattedAddress", ""),
                    lat=place["location"]["latitude"],
                    lng=place["location"]["longitude"],
                    maps_url=place.get("googleMapsUri", ""),
                    types=place.get("types", []),
                )
            )
        return matches
