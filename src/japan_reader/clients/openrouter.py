import base64
from pathlib import Path

import httpx
from pydantic import BaseModel

from japan_reader.clients.http import send
from japan_reader.errors import TransientError

BASE_URL = "https://openrouter.ai/api/v1"


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
        data = send(self._http, "POST", f"{BASE_URL}/chat/completions", self.SERVICE, headers=self._headers, json=body).json()
        if data.get("error"):
            raise TransientError(f"openrouter: {data['error']}")
        content = data["choices"][0]["message"].get("content") or ""
        cost = float((data.get("usage") or {}).get("cost") or 0.0)
        return ChatResult(content=content, cost_usd=cost)

    def model_supports_images(self, model: str) -> bool:
        data = send(self._http, "GET", f"{BASE_URL}/models", self.SERVICE, headers=self._headers).json()
        for entry in data.get("data", []):
            if entry.get("id") == model:
                return "image" in (entry.get("architecture") or {}).get("input_modalities", [])
        return False
