import itertools
import re
from pathlib import Path

from japan_reader.clients.karakeep import Bookmark
from japan_reader.clients.openrouter import ChatResult
from japan_reader.clients.trilium import TAttachment, TAttr, TNote

_CONDITION = re.compile(r'#([\w:]+)(?:=(?:"([^"]*)"|(\S+)))?')


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

    def __init__(self, responses: list[str], cost: float = 0.001, images: bool = True, models: dict | None = None) -> None:
        self.responses = list(responses)
        self.cost = cost
        self.images = images
        self.models = models
        self.calls: list[dict] = []

    def chat_json(self, model, messages, schema, schema_name) -> ChatResult:
        self.calls.append({"model": model, "messages": messages, "schema_name": schema_name})
        return ChatResult(content=self.responses.pop(0), cost_usd=self.cost)

    def model_supports_images(self, model: str) -> bool:
        return self.images

    def model_info(self, model: str) -> dict | None:
        """Por defecto cualquier modelo existe y admite salida estructurada; `models` lo sustituye."""
        if self.models is not None:
            return self.models.get(model)
        modalities = ["text", "image"] if self.images else ["text"]
        return {"id": model, "architecture": {"input_modalities": modalities}, "supported_parameters": ["response_format", "structured_outputs"]}


class FakeTrilium:
    """Trilium en memoria. Soporta búsquedas `#etiqueta` y `#etiqueta=valor` combinadas (AND)."""

    def __init__(self) -> None:
        self._ids = itertools.count(1)
        self.notes: dict[str, dict] = {"root": {"title": "root", "type": "text", "content": "", "parents": []}}
        self.attrs: dict[str, dict] = {}
        self.attachments: dict[str, dict] = {}

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}{next(self._ids)}"

    # --- utilidades de test ---
    def add_note(self, parent: str, title: str, labels: dict | None = None, type: str = "text", content: str = "") -> str:
        note_id = self._new_id("n")
        self.notes[note_id] = {"title": title, "type": type, "content": content, "parents": [parent]}
        for name, value in (labels or {}).items():
            self.add_label(note_id, name, value)
        return note_id

    def labels(self, note_id: str) -> dict[str, str]:
        return {a["name"]: a["value"] for a in self.attrs.values() if a["note"] == note_id and a["type"] == "label"}

    def children(self, parent: str) -> list[str]:
        return [nid for nid, n in self.notes.items() if parent in n["parents"]]

    # --- interfaz de TriliumClient ---
    def app_info(self) -> dict:
        return {"appVersion": "fake"}

    def get_note(self, note_id: str) -> TNote:
        note = self.notes[note_id]
        attributes = [
            TAttr(attributeId=aid, type=a["type"], name=a["name"], value=a["value"])
            for aid, a in self.attrs.items() if a["note"] == note_id
        ]
        return TNote(
            noteId=note_id, title=note["title"], type=note["type"], attributes=attributes,
            parentNoteIds=list(note["parents"]), parentBranchIds=[f"{p}_{note_id}" for p in note["parents"]],
        )

    def create_note(self, parent_id: str, title: str, type: str = "text", content: str = "") -> TNote:
        return self.get_note(self.add_note(parent_id, title, type=type, content=content))

    def get_content(self, note_id: str) -> str:
        return self.notes[note_id]["content"]

    def set_content(self, note_id: str, content: str) -> None:
        self.notes[note_id]["content"] = content

    def add_label(self, note_id: str, name: str, value: str = "") -> str:
        attr_id = self._new_id("a")
        self.attrs[attr_id] = {"note": note_id, "type": "label", "name": name, "value": value}
        return attr_id

    def add_relation(self, note_id: str, name: str, target_id: str) -> str:
        attr_id = self._new_id("a")
        self.attrs[attr_id] = {"note": note_id, "type": "relation", "name": name, "value": target_id}
        return attr_id

    def update_attribute(self, attribute_id: str, value: str) -> None:
        self.attrs[attribute_id]["value"] = value

    def delete_attribute(self, attribute_id: str) -> None:
        del self.attrs[attribute_id]

    def clone(self, note_id: str, parent_id: str) -> str:
        self.notes[note_id]["parents"].append(parent_id)
        return f"{parent_id}_{note_id}"

    def remove_from_parent(self, note_id: str, parent_id: str) -> bool:
        parents = self.notes[note_id]["parents"]
        if parent_id not in parents or len(parents) < 2:
            return False
        parents.remove(parent_id)
        return True

    def create_attachment(self, owner_id: str, title: str, mime: str, content: str, role: str = "file") -> str:
        attachment_id = self._new_id("x")
        self.attachments[attachment_id] = {"owner": owner_id, "title": title, "mime": mime, "role": role, "content": content}
        return attachment_id

    def list_attachments(self, note_id: str) -> list[TAttachment]:
        return [
            TAttachment(attachmentId=aid, title=a["title"], mime=a["mime"], role=a["role"])
            for aid, a in self.attachments.items() if a["owner"] == note_id
        ]

    def get_attachment_content(self, attachment_id: str) -> str:
        return self.attachments[attachment_id]["content"]

    def set_attachment_content(self, attachment_id: str, content: str) -> None:
        self.attachments[attachment_id]["content"] = content

    def search(self, query: str, ancestor: str | None = None, ancestor_depth: str | None = None, limit: int | None = None) -> list[TNote]:
        conditions = [(m.group(1), m.group(2) if m.group(2) is not None else m.group(3)) for m in _CONDITION.finditer(query)]
        found = []
        for note_id in self.notes:
            if note_id == "root" or (ancestor and not self._under(note_id, ancestor, ancestor_depth)):
                continue
            labels = [(a["name"], a["value"]) for a in self.attrs.values() if a["note"] == note_id and a["type"] == "label"]
            if all(any(n == name and (value is None or v == value) for n, v in labels) for name, value in conditions):
                found.append(self.get_note(note_id))
        return found[:limit] if limit else found

    def _under(self, note_id: str, ancestor: str, depth: str | None) -> bool:
        frontier, level = {note_id}, 0
        while frontier:
            level += 1
            parents = {p for n in frontier for p in self.notes[n]["parents"]}
            if ancestor in parents and (depth is None or depth == f"eq{level}"):
                return True
            frontier = parents
        return False
