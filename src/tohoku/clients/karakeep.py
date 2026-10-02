from collections.abc import Iterator
from pathlib import Path

import httpx
from pydantic import BaseModel

from tohoku.clients.http import send


class Bookmark(BaseModel):
    id: str
    url: str | None = None
    title: str | None = None
    description: str | None = None
    author: str | None = None
    archived: bool = False
    tags: list[str] = []
    video_asset_id: str | None = None
    image_asset_id: str | None = None

    @classmethod
    def from_api(cls, data: dict) -> "Bookmark":
        content = data.get("content") or {}
        is_link = content.get("type") == "link"
        return cls(
            id=data["id"],
            url=content.get("url") if is_link else None,
            title=data.get("title") or content.get("title"),
            description=content.get("description"),
            author=content.get("author"),
            archived=bool(data.get("archived", False)),
            tags=[tag["name"] for tag in data.get("tags", [])],
            video_asset_id=content.get("videoAssetId"),
            image_asset_id=content.get("imageAssetId"),
        )


class KarakeepClient:
    """Minimal client for the Karakeep REST API (`/api/v1`)."""

    SERVICE = "karakeep"

    def __init__(self, base_url: str, api_key: str, http: httpx.Client | None = None) -> None:
        self._http = http or httpx.Client(timeout=60)
        self._base = base_url.rstrip("/") + "/api/v1"
        self._headers = {"Authorization": f"Bearer {api_key}"}

    def _req(self, method: str, path: str, **kwargs) -> httpx.Response:
        return send(self._http, method, self._base + path, self.SERVICE, headers=self._headers, **kwargs)

    def list_bookmarks(self, list_id: str) -> Iterator[Bookmark]:
        cursor: str | None = None
        while True:
            params = {"limit": 100, "includeContent": "false"}
            if cursor:
                params["cursor"] = cursor
            data = self._req("GET", f"/lists/{list_id}/bookmarks", params=params).json()
            for item in data.get("bookmarks", []):
                yield Bookmark.from_api(item)
            cursor = data.get("nextCursor")
            if not cursor:
                return

    def get_bookmark(self, bookmark_id: str) -> Bookmark:
        return Bookmark.from_api(self._req("GET", f"/bookmarks/{bookmark_id}").json())

    def attach_tags(self, bookmark_id: str, names: list[str]) -> None:
        self._req("POST", f"/bookmarks/{bookmark_id}/tags", json={"tags": [{"tagName": n} for n in names]})

    def detach_tags(self, bookmark_id: str, names: list[str]) -> None:
        self._req("DELETE", f"/bookmarks/{bookmark_id}/tags", json={"tags": [{"tagName": n} for n in names]})

    def set_archived(self, bookmark_id: str, archived: bool) -> None:
        self._req("PATCH", f"/bookmarks/{bookmark_id}", json={"archived": archived})

    def download_asset(self, asset_id: str, dest: Path) -> Path:
        resp = self._req("GET", f"/assets/{asset_id}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)
        return dest

    def find_by_url(self, url: str) -> str | None:
        return self._req("GET", "/bookmarks/check-url", params={"url": url}).json().get("bookmarkId")

    def create_link(self, url: str) -> str:
        return self._req("POST", "/bookmarks", json={"type": "link", "url": url, "source": "import"}).json()["id"]

    def add_to_list(self, list_id: str, bookmark_id: str) -> None:
        self._req("PUT", f"/lists/{list_id}/bookmarks/{bookmark_id}")
