import json
import zipfile

import pytest

from fakes import FakeKarakeep
from japan_reader.clients.karakeep import Bookmark
from japan_reader.instagram_export import filter_collection, format_import_report, import_items, parse_export

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

    assert report.total == 5 and report.created == 0
    assert report.by_collection == {"Japón": 2, "Recetas": 1, "(sin colección)": 2}
    assert karakeep.bookmarks == {}
    assert "simulación" in format_import_report(report, dry_run=True)
