import json
import zipfile

import pytest

from fakes import FakeKarakeep
from tohoku.clients.karakeep import Bookmark
from tohoku.instagram_export import filter_collection, format_import_report, import_items, parse_export

COLLECTIONS = {"saved_saved_collections": [
    {"title": "Collection", "string_map_data": {"Name": {"value": "Japón"}, "Creation Time": {"timestamp": 1700000000}}},
    {"title": "user1", "string_map_data": {"Name": {"href": "https://www.instagram.com/reel/AAA/?igsh=1", "value": "user1"}, "Added Time": {"timestamp": 1}}},
    {"title": "user2", "string_map_data": {"Name": {"href": "https://www.instagram.com/p/BBB/", "value": "user2"}}},
    {"title": "Collection", "string_map_data": {"Name": {"value": "Recetas"}}},
    {"title": "user3", "string_map_data": {"Name": {"href": "https://www.instagram.com/reel/CCC/", "value": "user3"}}},
]}
POSTS = {"saved_saved_media": [
    {"title": "user1", "string_map_data": {"Saved on": {"href": "https://www.instagram.com/reel/AAA/", "timestamp": 1}}},
    {"title": "user4", "string_map_data": {"Saved on": {"href": "https://www.instagram.com/p/DDD/", "timestamp": 2}}},
    {"label_values": [{"label": "URL", "value": "https://www.instagram.com/reel/EEE/", "href": "https://www.instagram.com/reel/EEE/"}]},
]}


def _write_dir(root):
    saved = root / "your_instagram_activity" / "saved"
    saved.mkdir(parents=True)
    (saved / "saved_collections.json").write_text(json.dumps(COLLECTIONS), encoding="utf-8")
    (saved / "saved_posts.json").write_text(json.dumps(POSTS), encoding="utf-8")
    return root


EXPECTED = [
    ("https://www.instagram.com/reel/AAA/", "Japón"),
    ("https://www.instagram.com/p/BBB/", "Japón"),
    ("https://www.instagram.com/reel/CCC/", "Recetas"),
    ("https://www.instagram.com/p/DDD/", None),
    ("https://www.instagram.com/reel/EEE/", None),
]


def test_parse_directory(tmp_path):
    items = parse_export(_write_dir(tmp_path / "export"))
    assert [(i.url, i.collection) for i in items] == EXPECTED


def test_parse_zip(tmp_path):
    root = _write_dir(tmp_path / "export")
    archive = tmp_path / "instagram.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for path in root.rglob("*.json"):
            zf.write(path, path.relative_to(root))
    assert [(i.url, i.collection) for i in parse_export(archive)] == EXPECTED


def test_missing_files(tmp_path):
    with pytest.raises(FileNotFoundError):
        parse_export(tmp_path)


def test_filter_collection_ignores_case_and_accents(tmp_path):
    items = parse_export(_write_dir(tmp_path / "export"))
    assert [i.url for i in filter_collection(items, "japon")] == [
        "https://www.instagram.com/reel/AAA/",
        "https://www.instagram.com/p/BBB/",
    ]


def test_import_items_creates_or_reuses_and_adds_to_list(tmp_path):
    items = filter_collection(parse_export(_write_dir(tmp_path / "export")), "Japón")
    karakeep = FakeKarakeep([Bookmark(id="old", url="https://www.instagram.com/reel/AAA/")])
    karakeep.lists["L1"] = []

    report = import_items(items, karakeep, "L1")

    assert (report.total, report.created, report.existing) == (2, 1, 1)
    assert len(karakeep.lists["L1"]) == 2 and "old" in karakeep.lists["L1"]
    assert "Creados: 1" in format_import_report(report, dry_run=False)


def test_dry_run_does_not_touch_karakeep(tmp_path):
    items = parse_export(_write_dir(tmp_path / "export"))
    karakeep = FakeKarakeep()

    report = import_items(items, karakeep, "L1", dry_run=True)

    assert report.total == 5 and report.created == 5  # 5 would be created; none is created
    assert report.by_collection == {"Japón": 2, "Recetas": 1, "(sin colección)": 2}
    assert karakeep.bookmarks == {} and karakeep.lists["L1"] == []
    assert "simulación" in format_import_report(report, dry_run=True)



def _post(code, kind="reel", caption="#japan"):
    url = f"https://www.instagram.com/{kind}/{code}/"
    return {"dict": [
        {"label": "URL", "value": url, "href": url},
        {"label": "Pie de foto", "value": caption},
        {"dict": [{"dict": [{"label": "URL", "value": "https://example.com/bio"}, {"label": "Nombre de usuario", "value": "someone"}], "title": ""}], "title": "Propietario"},
    ], "title": ""}


def _collection(name, posts):
    return {"fbid": "1", "timestamp": 1, "media": [], "label_values": [
        {"label": "Nombre", "value": name},
        {"label": "Tipo", "value": "Opci\u00c3\u00b3n predeterminada"},
        {"label": "Fecha y hora de la actualizaci\u00c3\u00b3n", "timestamp_value": 1},
        {"dict": posts, "title": ""},
    ]}


# Real format (2026): list of collections with nested posts, newest first, text with mojibake.
NEW_FORMAT = [
    _collection("Cosas de Japon", [_post("N3"), _post("N2", "p"), _post("N1")]),
    _collection("Cocina espa\u00c3\u00b1ola", [_post("R1")]),
]


def test_parse_new_nested_collection_format(tmp_path):
    path = tmp_path / "saved_collections.json"
    path.write_text(json.dumps(NEW_FORMAT), encoding="utf-8")

    items = parse_export(path)

    assert [(i.url, i.collection) for i in items] == [
        ("https://www.instagram.com/reel/N3/", "Cosas de Japon"),
        ("https://www.instagram.com/p/N2/", "Cosas de Japon"),
        ("https://www.instagram.com/reel/N1/", "Cosas de Japon"),
        ("https://www.instagram.com/reel/R1/", "Cocina española"),  # mojibake fixed
    ]
    assert len(filter_collection(items, "cosas de japón")) == 3


def test_import_is_oldest_first_and_limit_counts_only_new(tmp_path):
    path = tmp_path / "saved_collections.json"
    path.write_text(json.dumps(NEW_FORMAT), encoding="utf-8")
    items = filter_collection(parse_export(path), "Cosas de Japon")
    karakeep = FakeKarakeep()
    karakeep.lists["L1"] = []

    first = import_items(items, karakeep, "L1", limit=2)
    second = import_items(items, karakeep, "L1", limit=2)

    urls = [karakeep.bookmarks[b].url for b in karakeep.lists["L1"]]
    assert urls == ["https://www.instagram.com/reel/N1/", "https://www.instagram.com/p/N2/", "https://www.instagram.com/reel/N3/"]
    assert (first.created, first.existing, first.pending) == (2, 0, 1)
    assert (second.created, second.existing, second.pending) == (1, 2, 0)
    assert "Pendientes: 0" in format_import_report(second, dry_run=False)


def test_dry_run_with_limit_reports_next_batch_without_writing(tmp_path):
    path = tmp_path / "saved_collections.json"
    path.write_text(json.dumps(NEW_FORMAT), encoding="utf-8")
    items = filter_collection(parse_export(path), "Cosas de Japon")
    karakeep = FakeKarakeep([Bookmark(id="old", url="https://www.instagram.com/reel/N1/")])
    karakeep.lists["L1"] = []

    report = import_items(items, karakeep, "L1", dry_run=True, limit=1)

    assert (report.created, report.existing, report.pending) == (1, 1, 1)
    assert karakeep.lists["L1"] == [] and len(karakeep.bookmarks) == 1
