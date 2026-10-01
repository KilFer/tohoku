import json

import httpx
import pytest
import respx

from tohoku.clients.trilium import TriliumClient, image_src

HOST = "trilium.test"
NOTE = {
    "noteId": "n1", "title": "Ichiran", "type": "text",
    "attributes": [
        {"attributeId": "a1", "noteId": "n1", "type": "label", "name": "ciudad", "value": "Tokio"},
        {"attributeId": "a2", "noteId": "n1", "type": "relation", "name": "dondeComprar", "value": "n9"},
    ],
    "parentNoteIds": ["p1"], "parentBranchIds": ["p1_n1"],
}


@pytest.fixture
def client():
    return TriliumClient("http://trilium.test/", "etapi-token")


@respx.mock
def test_search_params_and_parsing(client):
    route = respx.get(host=HOST, path="/etapi/notes").mock(return_value=httpx.Response(200, json={"results": [NOTE]}))

    notes = client.search('#googlePlaceId="X"', ancestor="root1", ancestor_depth="eq1", limit=5)

    params = route.calls[0].request.url.params
    assert params["search"] == '#googlePlaceId="X"'
    assert params["ancestorNoteId"] == "root1"
    assert params["ancestorDepth"] == "eq1"
    assert params["limit"] == "5"
    assert route.calls[0].request.headers["Authorization"] == "etapi-token"
    note = notes[0]
    assert note.label("ciudad") == "Tokio"
    assert note.relations("dondeComprar") == ["n9"]
    assert note.parent_note_ids == ["p1"]


@respx.mock
def test_create_note_and_content(client):
    create = respx.post(host=HOST, path="/etapi/create-note").mock(return_value=httpx.Response(201, json={"note": NOTE, "branch": {}}))
    put = respx.put(host=HOST, path="/etapi/notes/n1/content").mock(return_value=httpx.Response(204))

    note = client.create_note("p1", "Ichiran", "text", "<p>x</p>")
    client.set_content("n1", "<p>nuevo</p>")

    assert note.note_id == "n1"
    assert json.loads(create.calls[0].request.content) == {"parentNoteId": "p1", "title": "Ichiran", "type": "text", "content": "<p>x</p>"}
    assert put.calls[0].request.content == "<p>nuevo</p>".encode()
    assert put.calls[0].request.headers["Content-Type"].startswith("text/plain")


@respx.mock
def test_attributes_branches_and_attachments(client):
    attr = respx.post(host=HOST, path="/etapi/attributes").mock(return_value=httpx.Response(201, json={"attributeId": "a9"}))
    patch = respx.patch(host=HOST, path="/etapi/attributes/a9").mock(return_value=httpx.Response(200, json={}))
    branch = respx.post(host=HOST, path="/etapi/branches").mock(return_value=httpx.Response(201, json={"branchId": "b9"}))
    attach = respx.post(host=HOST, path="/etapi/attachments").mock(return_value=httpx.Response(201, json={"attachmentId": "x9"}))
    respx.get(host=HOST, path="/etapi/notes/n1/attachments").mock(
        return_value=httpx.Response(200, json=[{"attachmentId": "x9", "title": "japan-reader.json", "mime": "application/json", "role": "file"}])
    )

    assert client.add_label("n1", "ciudad", "Tokio") == "a9"
    assert client.add_relation("n1", "template", "t1") == "a9"
    client.update_attribute("a9", "Kioto")
    assert client.clone("n1", "rev") == "b9"
    assert client.create_attachment("n1", "japan-reader.json", "application/json", "{}") == "x9"
    assert client.list_attachments("n1")[0].title == "japan-reader.json"

    assert json.loads(attr.calls[0].request.content) == {"noteId": "n1", "type": "label", "name": "ciudad", "value": "Tokio", "isInheritable": False}
    assert json.loads(attr.calls[1].request.content)["type"] == "relation"
    assert json.loads(patch.calls[0].request.content) == {"value": "Kioto"}
    assert json.loads(branch.calls[0].request.content) == {"noteId": "n1", "parentNoteId": "rev"}
    assert json.loads(attach.calls[0].request.content) == {
        "ownerId": "n1", "role": "file", "mime": "application/json", "title": "japan-reader.json", "content": "{}", "position": 10,
    }


@respx.mock
def test_remove_from_parent_deletes_only_that_branch(client):
    note = NOTE | {"parentNoteIds": ["p1", "inbox"], "parentBranchIds": ["p1_n1", "inbox_n1"]}
    respx.get(host=HOST, path="/etapi/notes/n1").mock(return_value=httpx.Response(200, json=note))
    respx.get(host=HOST, path="/etapi/branches/p1_n1").mock(return_value=httpx.Response(200, json={"branchId": "p1_n1", "noteId": "n1", "parentNoteId": "p1"}))
    respx.get(host=HOST, path="/etapi/branches/inbox_n1").mock(return_value=httpx.Response(200, json={"branchId": "inbox_n1", "noteId": "n1", "parentNoteId": "inbox"}))
    delete = respx.delete(host=HOST, path="/etapi/branches/inbox_n1").mock(return_value=httpx.Response(204))

    assert client.remove_from_parent("n1", "inbox") is True
    assert delete.called


@respx.mock
def test_remove_from_parent_never_deletes_the_last_branch(client):
    respx.get(host=HOST, path="/etapi/notes/n1").mock(return_value=httpx.Response(200, json=NOTE))
    delete = respx.delete(host=HOST, path__regex=r"/etapi/branches/.*")

    assert client.remove_from_parent("n1", "p1") is False
    assert not delete.called


@respx.mock
def test_create_image_attachment_posts_then_uploads_binary(client):
    post = respx.post(host=HOST, path="/etapi/attachments").mock(return_value=httpx.Response(201, json={"attachmentId": "att1"}))
    put = respx.put(host=HOST, path="/etapi/attachments/att1/content").mock(return_value=httpx.Response(204))
    data = b"\xff\xd8\xff\xe0binary"

    attachment_id = client.create_image_attachment("n1", "portada.jpg", data)

    assert attachment_id == "att1"
    body = json.loads(post.calls[0].request.content)
    assert body["ownerId"] == "n1" and body["role"] == "image"
    assert body["mime"] == "image/jpeg" and body["title"] == "portada.jpg" and body["content"] == ""
    assert put.calls[0].request.content == data
    assert put.calls[0].request.headers["Content-Type"] == "application/octet-stream"
    assert respx.calls[0].request.method == "POST" and respx.calls[1].request.method == "PUT"


def test_image_src_format():
    assert image_src("att1", "portada.jpg") == "api/attachments/att1/image/portada.jpg"
    assert image_src("att1", "mi portada.jpg") == "api/attachments/att1/image/mi%20portada.jpg"


@respx.mock
def test_set_attachment_data_puts_binary(client):
    put = respx.put(host=HOST, path="/etapi/attachments/att1/content").mock(return_value=httpx.Response(204))
    client.set_attachment_data("att1", b"\xff\xd8bin")
    assert put.calls[0].request.content == b"\xff\xd8bin"
    assert put.calls[0].request.headers["Content-Type"] == "application/octet-stream"
