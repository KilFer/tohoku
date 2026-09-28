import re

_TIMESTAMP = re.compile(r"^(\d{2}:)?\d{2}:\d{2}\.\d{3} --> ")
_TAG = re.compile(r"<[^>]+>")
_HEADERS = ("WEBVTT", "Kind:", "Language:", "NOTE", "STYLE")


def vtt_to_text(vtt: str) -> str:
    """Texto plano de un WebVTT, sin marcas de tiempo, etiquetas ni líneas repetidas seguidas."""
    lines: list[str] = []
    for raw in vtt.splitlines():
        line = raw.strip()
        if not line or line.startswith(_HEADERS) or _TIMESTAMP.match(line) or line.isdigit():
            continue
        line = _TAG.sub("", line).strip()
        if line and (not lines or lines[-1] != line):
            lines.append(line)
    return " ".join(lines)
