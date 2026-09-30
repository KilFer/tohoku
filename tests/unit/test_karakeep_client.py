import json

import httpx
import pytest
import respx

from tohoku.clients.karakeep import KarakeepClient
from tohoku.errors import ApiError, ConfigError, TransientError

HOST = "karakeep.test"


def _bookmark(bid, url, tags=(), archived=False, video=None):
    return {
        "id": bid,
        "title": None,
        "archived": archived,
        "tags": [{"id": f"t-{t}", "name": t, "attachedBy": "human"} for t in tags],
        "content": {"type": "link", "url": url, "title": f"T {bid}", "description": "desc", "videoAssetId": video},
    }


@pytest.fixture
def client():
    return KarakeepClient("http://karakeep.test/", "secret")


@respx.mock
def test_list_bookmarks_paginates(client):
    route = respx.get(host=HOST, path="/api/v1/lists/L1/bookmarks").mock(
        side_effect=[
            httpx.Response(200, json={"bookmarks": [_bookmark("b1", "https://youtu.be/a")], "nextCursor": "c2"}),
            httpx.Response(200, json={"bookmarks": [_bookmark("b2", "https://youtu.be/b", tags=["jr:procesado"])], "nextCursor": None}),
        ]
    )

    bookmarks = list(client.list_bookmarks("L1"))

    assert [b.id for b in bookmarks] == ["b1", "b2"]
    assert bookmarks[0].url == "https://youtu.be/a"
    assert bookmarks[0].title == "T b1"
    assert bookmarks[1].tags == ["jr:procesado"]
    assert route.calls[0].request.headers["Authorization"] == "Bearer secret"
    assert route.calls[1].request.url.params["cursor"] == "c2"


@respx.mock
def test_tags_archive_and_lists(client):
    attach = respx.post(host=HOST, path="/api/v1/bookmarks/b1/tags").mock(return_value=httpx.Response(200, json={"attached": []}))
    detach = respx.delete(host=HOST, path="/api/v1/bookmarks/b1/tags").mock(return_value=httpx.Response(200, json={"detached": []}))
    patch = respx.patch(host=HOST, path="/api/v1/bookmarks/b1").mock(return_value=httpx.Response(200, json={"id": "b1"}))
    add = respx.put(host=HOST, path="/api/v1/lists/L1/bookmarks/b1").mock(return_value=httpx.Response(204))

    client.attach_tags("b1", ["jr:procesado"])
    client.detach_tags("b1", ["jr:error"])
    client.set_archived("b1", True)
    client.add_to_list("L1", "b1")

    assert json.loads(attach.calls[0].request.content) == {"tags": [{"tagName": "jr:procesado"}]}
    assert json.loads(detach.calls[0].request.content) == {"tags": [{"tagName": "jr:error"}]}
    assert json.loads(patch.calls[0].request.content) == {"archived": True}
    assert add.called


@respx.mock
def test_find_and_create(client):
    respx.get(host=HOST, path="/api/v1/bookmarks/check-url").mock(return_value=httpx.Response(200, json={"bookmarkId": None}))
    create = respx.post(host=HOST, path="/api/v1/bookmarks").mock(return_value=httpx.Response(201, json=_bookmark("new", "https://youtu.be/z")))

    assert client.find_by_url("https://youtu.be/z") is None
    assert client.create_link("https://youtu.be/z") == "new"
    assert json.loads(create.calls[0].request.content) == {"type": "link", "url": "https://youtu.be/z", "source": "import"}


@respx.mock
def test_download_asset(client, tmp_path):
    respx.get(host=HOST, path="/api/v1/assets/a1").mock(return_value=httpx.Response(200, content=b"video-bytes"))
    dest = client.download_asset("a1", tmp_path / "v.mp4")
    assert dest.read_bytes() == b"video-bytes"


@respx.mock
@pytest.mark.parametrize(("status", "error"), [(401, ConfigError), (500, TransientError), (429, TransientError), (404, ApiError)])
def test_status_mapping(client, status, error):
    respx.get(host=HOST, path="/api/v1/bookmarks/b1").mock(return_value=httpx.Response(status, text="boom"))
    with pytest.raises(error):
        client.get_bookmark("b1")


@respx.mock
def test_transport_error_is_transient(client):
    respx.get(host=HOST, path="/api/v1/bookmarks/b1").mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(TransientError):
        client.get_bookmark("b1")
