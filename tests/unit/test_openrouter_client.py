import json

import httpx
import pytest
import respx

from helpers import make_image
from japan_reader.clients.openrouter import OpenRouterClient, image_part
from japan_reader.errors import ApiError, ConfigError

HOST = "openrouter.ai"
MODELS = {"data": [
    {"id": "vision/model", "architecture": {"input_modalities": ["text", "image"]},
     "supported_parameters": ["response_format", "temperature"]},
    # Modelo de razonamiento real (openai/gpt-6-luna): no admite temperature.
    {"id": "reasoning/model", "architecture": {"input_modalities": ["text", "image"]},
     "supported_parameters": ["max_tokens", "reasoning", "response_format", "structured_outputs"]},
]}
CHAT_OK = {"choices": [{"message": {"content": "{}"}}], "usage": {"cost": 0.0}}


@respx.mock
def test_chat_json_sends_schema_and_returns_cost():
    respx.get(host=HOST, path="/api/v1/models").mock(return_value=httpx.Response(200, json=MODELS))
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
    assert body["temperature"] == 0.2
    assert route.calls[0].request.headers["Authorization"] == "Bearer key"


@respx.mock
def test_temperature_omitted_when_model_does_not_support_it():
    """Con require_parameters, enviar un parámetro no admitido deja la petición sin proveedor (404)."""
    models = respx.get(host=HOST, path="/api/v1/models").mock(return_value=httpx.Response(200, json=MODELS))
    route = respx.post(host=HOST, path="/api/v1/chat/completions").mock(return_value=httpx.Response(200, json=CHAT_OK))
    client = OpenRouterClient("key")

    client.chat_json("reasoning/model", [{"role": "user", "content": "a"}], {"type": "object"}, "x")
    client.chat_json("reasoning/model", [{"role": "user", "content": "b"}], {"type": "object"}, "x")

    for call in route.calls:
        assert "temperature" not in json.loads(call.request.content)
    assert models.call_count == 1  # la ficha de modelos se consulta una vez y se cachea


@respx.mock
def test_unknown_model_keeps_temperature():
    respx.get(host=HOST, path="/api/v1/models").mock(return_value=httpx.Response(200, json=MODELS))
    route = respx.post(host=HOST, path="/api/v1/chat/completions").mock(return_value=httpx.Response(200, json=CHAT_OK))

    OpenRouterClient("key").chat_json("other/model", [{"role": "user", "content": "a"}], {"type": "object"}, "x")

    assert json.loads(route.calls[0].request.content)["temperature"] == 0.2


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


@respx.mock
def test_model_info():
    respx.get(host=HOST, path="/api/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "vision/model", "supported_parameters": ["response_format"]}]})
    )
    client = OpenRouterClient("key")
    assert client.model_info("vision/model")["supported_parameters"] == ["response_format"]
    assert client.model_info("missing/model") is None


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (400, {"error": {"message": "bad/model is not a valid model ID", "code": 400}}),
        (404, {"error": {"message": "No endpoints found that support the requested parameters", "code": 404}}),
        (404, {"error": {"message": "Model vision/model not found", "code": 404}}),
    ],
)
@respx.mock
def test_chat_json_model_errors_are_config_errors(status, body):
    """Final review 4: modelo inexistente o sin proveedores → ConfigError (pausa y aviso), no jr:error."""
    respx.get(host=HOST, path="/api/v1/models").mock(return_value=httpx.Response(200, json=MODELS))
    respx.post(host=HOST, path="/api/v1/chat/completions").mock(return_value=httpx.Response(status, json=body))
    with pytest.raises(ConfigError, match="modelo"):
        OpenRouterClient("key").chat_json("vision/model", [], {}, "x")


@pytest.mark.parametrize(
    "message",
    ["Invalid JSON in request body", "This endpoint's maximum context length is 8192 tokens for model vision/model"],
)
@respx.mock
def test_other_4xx_stay_api_errors(message):
    respx.get(host=HOST, path="/api/v1/models").mock(return_value=httpx.Response(200, json=MODELS))
    respx.post(host=HOST, path="/api/v1/chat/completions").mock(
        return_value=httpx.Response(400, json={"error": {"message": message, "code": 400}})
    )
    with pytest.raises(ApiError) as info:
        OpenRouterClient("key").chat_json("vision/model", [], {}, "x")
    assert not isinstance(info.value, ConfigError)
