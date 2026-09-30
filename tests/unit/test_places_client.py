import json

import httpx
import pytest
import respx

from tohoku.clients.places import FIELD_MASK, PlacesClient
from tohoku.errors import ApiError, ConfigError

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
    assert FIELD_MASK == (
        "places.id,places.displayName,places.formattedAddress,places.location,"
        "places.googleMapsUri,places.types,places.postalAddress,places.addressComponents"
    )


# Formato real devuelto por Google con regionCode=JP: la dirección omite el país.
REAL_PLACE = {
    "id": "ChIJIW0uPRUPAWAR6eI6dRzKGns",
    "displayName": {"text": "Fushimi Inari-taisha", "languageCode": "es"},
    "formattedAddress": "68 Fukakusa Yabunouchichō, Fushimi Ward, Kyoto, 612-0882",
    "location": {"latitude": 34.96769, "longitude": 135.77919},
    "googleMapsUri": "https://maps.google.com/?cid=8870624639634301673",
    "postalAddress": {
        "regionCode": "JP", "languageCode": "es", "postalCode": "612-0882",
        "administrativeArea": "Prefectura de Kioto",
        "addressLines": ["68 Fukakusa Yabunouchicho", "Fushimi-ku, Kioto"],
    },
}


@respx.mock
def test_postal_address_gives_country_and_area():
    respx.post(host=HOST, path="/v1/places:searchText").mock(return_value=httpx.Response(200, json={"places": [REAL_PLACE, PLACE]}))

    real, legacy = PlacesClient("gkey").search("Fushimi Inari Taisha Kyoto")

    assert real.country_code == "JP"
    assert "Prefectura de Kioto" in real.area and "Fushimi-ku, Kioto" in real.area
    assert real.address == "68 Fukakusa Yabunouchichō, Fushimi Ward, Kyoto, 612-0882"
    assert legacy.country_code is None and legacy.area == ""


# Formato real de un área (barrio, ciudad, isla): sin postalAddress, país solo en addressComponents.
REAL_AREA = {
    "id": "ChIJkabukicho",
    "displayName": {"text": "Kabukichō", "languageCode": "es"},
    "formattedAddress": "Kabukichō, Shinjuku, Tokio 160-0021",
    "location": {"latitude": 35.6955, "longitude": 139.7031},
    "googleMapsUri": "https://maps.google.com/?cid=2",
    "types": ["sublocality_level_2", "sublocality", "political"],
    "addressComponents": [
        {"longText": "Kabukichō", "shortText": "Kabukichō", "types": ["sublocality_level_2", "sublocality", "political"]},
        {"longText": "Shinjuku", "shortText": "Shinjuku", "types": ["locality", "political"]},
        {"longText": "Tokio", "shortText": "Tokio", "types": ["administrative_area_level_1", "political"]},
        {"longText": "Japón", "shortText": "JP", "types": ["country", "political"]},
        {"longText": "160-0021", "shortText": "160-0021", "types": ["postal_code"]},
    ],
}


@respx.mock
def test_address_components_give_country_and_area_without_postal_address():
    respx.post(host=HOST, path="/v1/places:searchText").mock(return_value=httpx.Response(200, json={"places": [REAL_AREA]}))

    (area,) = PlacesClient("gkey").search("Kabukicho Shinjuku Tokyo")

    assert area.country_code == "JP"
    assert "Shinjuku" in area.area and "Tokio" in area.area
    assert "160-0021" not in area.area


@respx.mock
def test_postal_address_country_wins_over_components():
    place = REAL_PLACE | {"addressComponents": [{"longText": "Corea", "shortText": "KR", "types": ["country"]}]}
    respx.post(host=HOST, path="/v1/places:searchText").mock(return_value=httpx.Response(200, json={"places": [place]}))

    (match,) = PlacesClient("gkey").search("x")

    assert match.country_code == "JP"


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


@respx.mock
def test_search_region_can_be_changed():
    route = respx.post(host=HOST, path="/v1/places:searchText").mock(return_value=httpx.Response(200, json={}))
    PlacesClient("gkey").search("Sky Tower Auckland", region="NZ")
    assert json.loads(route.calls[0].request.content)["regionCode"] == "NZ"
