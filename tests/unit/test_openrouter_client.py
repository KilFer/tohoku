import json

import httpx
import respx

from helpers import make_image
from japan_reader.clients.openrouter import OpenRouterClient, image_part

HOST = "openrouter.ai"


@respx.mock
def test_chat_json_sends_schema_and_returns_cost():
    route = respx.post(host=HOST, path="/api/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": '{"a": 1}'}}], "usage": {"cost": 0.0123}})
    )

    result = OpenRouterClient("key").chat_json("vision/model", [{"role": "user", "content": "hola"}], {"type": "object"}, "extraction")

    assert result.content == '{"a": 1}'
    assert result.cost_usd == 0.0123
    body = json.loads(route.calls[0].request.content)
    assert body["model"] == "vision/model"
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["name"] == "extraction"
    assert body["provider"] == {"require_parameters": True}
    assert body["usage"] == {"include": True}
    assert route.calls[0].request.headers["Authorization"] == "Bearer key"


@respx.mock
def test_model_supports_images():
    respx.get(host=HOST, path="/api/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [
            {"id": "vision/model", "architecture": {"input_modalities": ["text", "image"]}},
            {"id": "text/model", "architecture": {"input_modalities": ["text"]}},
        ]})
    )
    client = OpenRouterClient("key")
    assert client.model_supports_images("vision/model") is True
    assert client.model_supports_images("text/model") is False
    assert client.model_supports_images("missing/model") is False


def test_image_part_is_data_url(tmp_path):
    part = image_part(make_image(tmp_path / "a.jpg", size=(10, 10)))
    assert part["type"] == "image_url"
    assert part["image_url"]["url"].startswith("data:image/jpeg;base64,")
