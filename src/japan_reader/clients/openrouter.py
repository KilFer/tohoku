import base64
from pathlib import Path

import httpx
from pydantic import BaseModel

from japan_reader.clients.http import send
from japan_reader.errors import ApiError, ConfigError, TransientError

BASE_URL = "https://openrouter.ai/api/v1"


# Frases de OpenRouter que indican un modelo mal configurado (nombre erróneo, retirado o sin
# proveedores que admitan los parámetros pedidos). Un error de longitud de contexto no lo es.
_MODEL_ERROR_MARKERS = ("valid model", "no endpoints", "endpoints found", "model not found")


def _is_model_error(exc: ApiError, model: str) -> bool:
    if exc.status not in (400, 404):
        return False
    body = str(exc).lower()
    if "context length" in body:
        return False
    return model.lower() in body or any(marker in body for marker in _MODEL_ERROR_MARKERS)


class ChatResult(BaseModel):
    content: str
    cost_usd: float


def image_part(path: Path) -> dict:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}}


class OpenRouterClient:
    SERVICE = "openrouter"

    def __init__(self, api_key: str, http: httpx.Client | None = None) -> None:
        self._http = http or httpx.Client(timeout=180)
        self._headers = {"Authorization": f"Bearer {api_key}", "X-Title": "japan-reader"}

    def chat_json(self, model: str, messages: list[dict], schema: dict, schema_name: str) -> ChatResult:
        body = {
            "model": model,
            "messages": messages,
            "temperature": 0.2,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": False, "schema": schema},
            },
            "provider": {"require_parameters": True},
            "usage": {"include": True},
        }
        try:
            data = send(self._http, "POST", f"{BASE_URL}/chat/completions", self.SERVICE, headers=self._headers, json=body).json()
        except ApiError as exc:
            if _is_model_error(exc, model):
                raise ConfigError(f"openrouter: el modelo {model} no está disponible o no admite la petición: {exc}") from exc
            raise
        if data.get("error"):
            raise TransientError(f"openrouter: {data['error']}")
        content = data["choices"][0]["message"].get("content") or ""
        cost = float((data.get("usage") or {}).get("cost") or 0.0)
        return ChatResult(content=content, cost_usd=cost)

    def model_info(self, model: str) -> dict | None:
        """Ficha del modelo en `GET /models` (id, architecture, supported_parameters...) o None si no existe."""
        data = send(self._http, "GET", f"{BASE_URL}/models", self.SERVICE, headers=self._headers).json()
        return next((entry for entry in data.get("data", []) if entry.get("id") == model), None)

    def model_supports_images(self, model: str) -> bool:
        info = self.model_info(model)
        return info is not None and supports_images(info)


def supports_images(info: dict) -> bool:
    return "image" in (info.get("architecture") or {}).get("input_modalities", [])


def supports_structured_output(info: dict) -> bool:
    params = info.get("supported_parameters") or []
    return "response_format" in params or "structured_outputs" in params
