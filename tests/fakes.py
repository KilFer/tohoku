from pathlib import Path

from japan_reader.clients.karakeep import Bookmark
from japan_reader.clients.openrouter import ChatResult


class FakeKarakeep:
    """Karakeep en memoria con la misma interfaz pública que KarakeepClient."""

    def __init__(self, bookmarks: list[Bookmark] | None = None) -> None:
        self.bookmarks: dict[str, Bookmark] = {b.id: b for b in bookmarks or []}
        self.lists: dict[str, list[str]] = {"L1": [b.id for b in bookmarks or []]}
        self.assets: dict[str, bytes] = {}
        self.calls: list[tuple] = []

    def list_bookmarks(self, list_id: str):
        yield from (self.bookmarks[bid] for bid in self.lists.get(list_id, []))

    def get_bookmark(self, bookmark_id: str) -> Bookmark:
        return self.bookmarks[bookmark_id]

    def attach_tags(self, bookmark_id: str, names: list[str]) -> None:
        self.calls.append(("attach", bookmark_id, tuple(names)))
        bookmark = self.bookmarks[bookmark_id]
        bookmark.tags = sorted(set(bookmark.tags) | set(names))

    def detach_tags(self, bookmark_id: str, names: list[str]) -> None:
        self.calls.append(("detach", bookmark_id, tuple(names)))
        bookmark = self.bookmarks[bookmark_id]
        bookmark.tags = [t for t in bookmark.tags if t not in names]

    def set_archived(self, bookmark_id: str, archived: bool) -> None:
        self.calls.append(("archive", bookmark_id, archived))
        self.bookmarks[bookmark_id].archived = archived

    def download_asset(self, asset_id: str, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.assets[asset_id])
        return dest

    def find_by_url(self, url: str) -> str | None:
        return next((b.id for b in self.bookmarks.values() if b.url == url), None)

    def create_link(self, url: str) -> str:
        bid = f"new{len(self.bookmarks) + 1}"
        self.bookmarks[bid] = Bookmark(id=bid, url=url)
        return bid

    def add_to_list(self, list_id: str, bookmark_id: str) -> None:
        self.lists.setdefault(list_id, [])
        if bookmark_id not in self.lists[list_id]:
            self.lists[list_id].append(bookmark_id)


class FakeLLM:
    """OpenRouter falso: devuelve las respuestas en orden y registra las llamadas."""

    def __init__(self, responses: list[str], cost: float = 0.001, images: bool = True) -> None:
        self.responses = list(responses)
        self.cost = cost
        self.images = images
        self.calls: list[dict] = []

    def chat_json(self, model, messages, schema, schema_name) -> ChatResult:
        self.calls.append({"model": model, "messages": messages, "schema_name": schema_name})
        return ChatResult(content=self.responses.pop(0), cost_usd=self.cost)

    def model_supports_images(self, model: str) -> bool:
        return self.images
