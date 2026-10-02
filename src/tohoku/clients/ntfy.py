import logging
from collections.abc import Sequence

import httpx

log = logging.getLogger(__name__)


class Notifier:
    """ntfy notifications (JSON publish at the server root). Never interrupts the service."""

    def __init__(self, url: str | None, topic: str | None, token: str | None, http: httpx.Client | None = None) -> None:
        self._url = url.rstrip("/") if url else None
        self._topic = topic
        self._token = token
        self._http = http or httpx.Client(timeout=15)

    @property
    def enabled(self) -> bool:
        return bool(self._url and self._topic)

    def send(self, title: str, message: str, priority: int = 3, tags: Sequence[str] = ()) -> None:
        if not self.enabled:
            log.info("ntfy desactivado; aviso no enviado: %s", title)
            return
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        body = {"topic": self._topic, "title": title, "message": message, "priority": priority, "tags": list(tags)}
        try:
            self._http.post(self._url, json=body, headers=headers).raise_for_status()
        except Exception as exc:
            log.warning("no se pudo enviar el aviso ntfy '%s': %s", title, exc)
