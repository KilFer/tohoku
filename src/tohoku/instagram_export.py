import json
import re
import zipfile
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from tohoku.clients.karakeep import KarakeepClient
from tohoku.sources import canonical_url
from tohoku.text import fold

_WANTED = ("saved_collections.json", "saved_posts.json")
_IG_URL = re.compile(r"https?://(?:www\.)?instagram\.com/(?:[\w.]+/)?(?:p|reels?|tv)/[\w-]+", re.I)
NO_COLLECTION = "(sin colección)"


@dataclass(frozen=True)
class ExportedItem:
    url: str
    collection: str | None


@dataclass
class ImportReport:
    total: int = 0
    created: int = 0
    existing: int = 0
    pending: int = 0  # new ones left for later batches (because of --limit)
    by_collection: dict[str, int] = field(default_factory=dict)


def _fix_text(text: str | None) -> str | None:
    """Undoes the mojibake of Instagram exports (UTF-8 stored as Latin-1)."""
    if not text:
        return text
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def _is_collection_block(entry: dict) -> bool:
    """2026 format: each entry is a collection with its posts nested in `label_values[].dict`."""
    return any(isinstance(value, dict) and "dict" in value for value in entry.get("label_values") or [])


def _load_files(path: Path) -> list[tuple[str, object]]:
    found: list[tuple[str, object]] = []
    if path.is_file() and path.suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            for name in sorted(archive.namelist()):
                if name.endswith(_WANTED):
                    found.append((name, json.loads(archive.read(name))))
    elif path.is_dir():
        for file in sorted(path.rglob("*.json")):
            if file.name in _WANTED:
                found.append((file.name, json.loads(file.read_text(encoding="utf-8"))))
    elif path.is_file():
        found.append((path.name, json.loads(path.read_text(encoding="utf-8"))))
    if not found:
        raise FileNotFoundError(f"No encuentro {' ni '.join(_WANTED)} en {path}")
    return found


def _entries(data: object) -> list[dict]:
    if isinstance(data, list):
        return [e for e in data if isinstance(e, dict)]
    if isinstance(data, dict):
        for value in data.values():
            if isinstance(value, list):
                return [e for e in value if isinstance(e, dict)]
    return []


def _strings(obj: object) -> Iterator[str]:
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for value in obj.values():
            yield from _strings(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _strings(value)


def _collection_name(entry: dict) -> str | None:
    for value in (entry.get("string_map_data") or {}).values():
        if isinstance(value, dict) and value.get("value") and not value.get("href"):
            return value["value"]
    for value in entry.get("label_values") or []:
        if isinstance(value, dict) and value.get("value") and not value.get("href"):
            return value["value"]
    return entry.get("title")


def parse_export(path: Path) -> list[ExportedItem]:
    """Reads the official Instagram export (folder, .zip or loose JSON).

    Formats of `saved_collections.json`:
    - classic: each collection starts with an entry without URL (its name) followed by its posts;
    - 2026: list of collections, each with its name in `label_values` and its posts nested.
    A post saved in a collection and also in `saved_posts.json` keeps the collection.
    Returns the links in file order (Instagram lists the most recent first).
    """
    by_url: dict[str, ExportedItem] = {}
    for name, data in _load_files(path):
        in_collections = "collections" in name
        current: str | None = None
        for entry in _entries(data):
            if in_collections and _is_collection_block(entry):
                current = _fix_text(_collection_name(entry))
            urls = list(dict.fromkeys(canonical_url(m.group(0)) for s in _strings(entry) if (m := _IG_URL.match(s))))
            if not urls:
                if in_collections:
                    current = _fix_text(_collection_name(entry))
                continue
            for url in urls:
                item = ExportedItem(url=url, collection=current if in_collections else None)
                previous = by_url.get(url)
                if previous is None or (previous.collection is None and item.collection):
                    by_url[url] = item
    return list(by_url.values())


def filter_collection(items: list[ExportedItem], name: str) -> list[ExportedItem]:
    wanted = fold(name).strip()
    return [item for item in items if item.collection and fold(item.collection).strip() == wanted]


def import_items(
    items: list[ExportedItem],
    karakeep: KarakeepClient,
    list_id: str,
    dry_run: bool = False,
    limit: int | None = None,
) -> ImportReport:
    """Imports from oldest to newest (reverse of file order).

    `limit` counts only new links: rerunning the same command imports the next batch.
    In dry-run mode Karakeep is queried (read-only) to say what would be created, writing nothing.
    """
    report = ImportReport(total=len(items), by_collection=dict(Counter(i.collection or NO_COLLECTION for i in items)))
    for item in reversed(items):
        bookmark_id = karakeep.find_by_url(item.url)
        if bookmark_id:
            report.existing += 1
            if not dry_run:
                karakeep.add_to_list(list_id, bookmark_id)
            continue
        if limit is not None and report.created >= limit:
            report.pending += 1
            continue
        report.created += 1
        if not dry_run:
            karakeep.add_to_list(list_id, karakeep.create_link(item.url))
    return report


def format_import_report(report: ImportReport, dry_run: bool) -> str:
    lines = [f"Enlaces encontrados: {report.total}" + (" (simulación, no se ha tocado Karakeep)" if dry_run else "")]
    lines += [f"  {name}: {count}" for name, count in sorted(report.by_collection.items())]
    verb = "Se crearían" if dry_run else "Creados"
    lines.append(f"{verb}: {report.created} · Ya existían: {report.existing} · Pendientes: {report.pending}")
    return "\n".join(lines)
