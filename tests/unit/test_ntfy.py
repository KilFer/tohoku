import json

import httpx
import respx

from tohoku.clients.ntfy import Notifier


@respx.mock
def test_send_posts_json_with_token():
    route = respx.post("https://ntfy.example.com").mock(return_value=httpx.Response(200))

    Notifier("https://ntfy.example.com/", "japan", "tk").send("tohoku: error", "Vídeo privado", priority=4, tags=["warning"])

    body = json.loads(route.calls[0].request.content)
    assert body == {"topic": "japan", "title": "tohoku: error", "message": "Vídeo privado", "priority": 4, "tags": ["warning"]}
    assert route.calls[0].request.headers["Authorization"] == "Bearer tk"


def test_disabled_without_url():
    notifier = Notifier(None, None, None)
    assert notifier.enabled is False
    notifier.send("t", "m")


@respx.mock
def test_failures_never_raise():
    respx.post("https://ntfy.example.com").mock(side_effect=httpx.ConnectError("down"))
    Notifier("https://ntfy.example.com", "japan", None).send("t", "m")


def test_invalid_url_never_raises():
    Notifier("http://bad url", "japan", None).send("t", "m")
