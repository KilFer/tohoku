import json

import httpx
import pytest
import respx

from japan_reader.clients.places import FIELD_MASK, PlacesClient
from japan_reader.errors import ApiError, ConfigError

HOST = "places.googleapis.com"
PLACE = {
    "id": "ChIJ123",
    "displayName": {"text": "Ichiran Shibuya", "languageCode": "es"},
    "formattedAddress": "1-22-7 Jinnan, Shibuya, Tokio 150-0041, Japón",
    "location": {"latitude": 35.6614, "longitude": 139.7005},
    "googleMapsUri": "https://maps.google.com/?cid=1",
    "types": ["ramen_restaurant", "restaurant"],
}


@respx.mock
def test_search_request_and_parsing():
    route = respx.post(host=HOST, path="/v1/places:searchText").mock(return_value=httpx.Response(200, json={"places": [PLACE, {"id": "no-location"}]}))

    results = PlacesClient("gkey").search("Ichiran Shibuya Tokyo")

    assert len(results) == 1
    match = results[0]
    assert (match.place_id, match.name, match.lat, match.lng) == ("ChIJ123", "Ichiran Shibuya", 35.6614, 139.7005)
    request = route.calls[0].request
    assert request.headers["X-Goog-Api-Key"] == "gkey"
    assert request.headers["X-Goog-FieldMask"] == FIELD_MASK
    assert json.loads(request.content) == {"textQuery": "Ichiran Shibuya Tokyo", "regionCode": "JP", "languageCode": "es", "pageSize": 5}


def test_field_mask_only_pro_fields():
    assert FIELD_MASK == "places.id,places.displayName,places.formattedAddress,places.location,places.googleMapsUri,places.types"


@respx.mock
def test_empty_response():
    respx.post(host=HOST, path="/v1/places:searchText").mock(return_value=httpx.Response(200, json={}))
    assert PlacesClient("gkey").search("nada") == []


@respx.mock
def test_invalid_key_is_config_error():
    respx.post(host=HOST, path="/v1/places:searchText").mock(
        return_value=httpx.Response(400, json={"error": {"message": "API key not valid. Please pass a valid API key."}})
    )
    with pytest.raises(ConfigError):
        PlacesClient("bad").search("x")


@respx.mock
def test_other_400_is_api_error():
    respx.post(host=HOST, path="/v1/places:searchText").mock(return_value=httpx.Response(400, json={"error": {"message": "bad query"}}))
    with pytest.raises(ApiError):
        PlacesClient("gkey").search("x")
