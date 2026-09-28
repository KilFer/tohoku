import httpx

from japan_reader.errors import ApiError, ConfigError, TransientError


def check_status(resp: httpx.Response, service: str) -> None:
    code = resp.status_code
    if code < 400:
        return
    if code in (401, 402, 403):
        raise ConfigError(f"{service}: credenciales o saldo rechazados (HTTP {code})")
    if code == 429 or code >= 500:
        raise TransientError(f"{service}: HTTP {code}")
    raise ApiError(service, code, resp.text)


def send(client: httpx.Client, method: str, url: str, service: str, **kwargs) -> httpx.Response:
    try:
        resp = client.request(method, url, **kwargs)
    except httpx.TransportError as exc:
        raise TransientError(f"{service}: {exc!r}") from exc
    check_status(resp, service)
    return resp
