import httpx
from pydantic import BaseModel, ConfigDict, Field

from tohoku.clients.http import send


class TAttr(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    attribute_id: str = Field(alias="attributeId")
    type: str
    name: str
    value: str = ""


class TNote(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    note_id: str = Field(alias="noteId")
    title: str
    type: str = "text"
    attributes: list[TAttr] = []
    parent_note_ids: list[str] = Field(default=[], alias="parentNoteIds")
    parent_branch_ids: list[str] = Field(default=[], alias="parentBranchIds")

    def attr(self, type: str, name: str) -> TAttr | None:
        return next((a for a in self.attributes if a.type == type and a.name == name), None)

    def label(self, name: str) -> str | None:
        found = self.attr("label", name)
        return found.value if found else None

    def relations(self, name: str) -> list[str]:
        return [a.value for a in self.attributes if a.type == "relation" and a.name == name]


class TAttachment(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    attachment_id: str = Field(alias="attachmentId")
    title: str
    mime: str = ""
    role: str = ""


class TriliumClient:
    """Cliente mínimo de ETAPI (Trilium v0.106)."""

    SERVICE = "trilium"

    def __init__(self, base_url: str, token: str, http: httpx.Client | None = None) -> None:
        self._http = http or httpx.Client(timeout=60)
        self._base = base_url.rstrip("/") + "/etapi"
        self._headers = {"Authorization": token}

    def _req(self, method: str, path: str, **kwargs) -> httpx.Response:
        headers = self._headers | kwargs.pop("headers", {})
        return send(self._http, method, self._base + path, self.SERVICE, headers=headers, **kwargs)

    def app_info(self) -> dict:
        return self._req("GET", "/app-info").json()

    def search(self, query: str, ancestor: str | None = None, ancestor_depth: str | None = None, limit: int | None = None) -> list[TNote]:
        params: dict[str, str | int] = {"search": query}
        if ancestor:
            params["ancestorNoteId"] = ancestor
        if ancestor_depth:
            params["ancestorDepth"] = ancestor_depth
        if limit:
            params["limit"] = limit
        return [TNote.model_validate(n) for n in self._req("GET", "/notes", params=params).json()["results"]]

    def get_note(self, note_id: str) -> TNote:
        return TNote.model_validate(self._req("GET", f"/notes/{note_id}").json())

    def create_note(self, parent_id: str, title: str, type: str = "text", content: str = "") -> TNote:
        body = {"parentNoteId": parent_id, "title": title, "type": type, "content": content}
        return TNote.model_validate(self._req("POST", "/create-note", json=body).json()["note"])

    def get_content(self, note_id: str) -> str:
        return self._req("GET", f"/notes/{note_id}/content").text

    def set_content(self, note_id: str, content: str) -> None:
        self._req("PUT", f"/notes/{note_id}/content", content=content.encode("utf-8"), headers={"Content-Type": "text/plain; charset=utf-8"})

    def _add_attribute(self, note_id: str, type: str, name: str, value: str) -> str:
        body = {"noteId": note_id, "type": type, "name": name, "value": value, "isInheritable": False}
        return self._req("POST", "/attributes", json=body).json()["attributeId"]

    def add_label(self, note_id: str, name: str, value: str = "") -> str:
        return self._add_attribute(note_id, "label", name, value)

    def add_relation(self, note_id: str, name: str, target_id: str) -> str:
        return self._add_attribute(note_id, "relation", name, target_id)

    def update_attribute(self, attribute_id: str, value: str) -> None:
        self._req("PATCH", f"/attributes/{attribute_id}", json={"value": value})

    def delete_attribute(self, attribute_id: str) -> None:
        self._req("DELETE", f"/attributes/{attribute_id}")

    def clone(self, note_id: str, parent_id: str) -> str:
        return self._req("POST", "/branches", json={"noteId": note_id, "parentNoteId": parent_id}).json()["branchId"]

    def remove_from_parent(self, note_id: str, parent_id: str) -> bool:
        """Quita el clon de `note_id` bajo `parent_id`. Nunca borra la última rama (eso borraría la nota)."""
        note = self.get_note(note_id)
        if parent_id not in note.parent_note_ids or len(note.parent_note_ids) < 2:
            return False
        for branch_id in note.parent_branch_ids:
            if self._req("GET", f"/branches/{branch_id}").json().get("parentNoteId") == parent_id:
                self._req("DELETE", f"/branches/{branch_id}")
                return True
        return False

    def create_attachment(self, owner_id: str, title: str, mime: str, content: str, role: str = "file") -> str:
        body = {"ownerId": owner_id, "role": role, "mime": mime, "title": title, "content": content, "position": 10}
        return self._req("POST", "/attachments", json=body).json()["attachmentId"]

    def list_attachments(self, note_id: str) -> list[TAttachment]:
        return [TAttachment.model_validate(a) for a in self._req("GET", f"/notes/{note_id}/attachments").json()]

    def get_attachment_content(self, attachment_id: str) -> str:
        return self._req("GET", f"/attachments/{attachment_id}/content").text

    def set_attachment_content(self, attachment_id: str, content: str) -> None:
        self._req(
            "PUT", f"/attachments/{attachment_id}/content",
            content=content.encode("utf-8"), headers={"Content-Type": "text/plain; charset=utf-8"},
        )
