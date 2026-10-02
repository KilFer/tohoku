import re
from enum import StrEnum
from urllib.parse import parse_qs, urlsplit, urlunsplit


class Platform(StrEnum):
    YOUTUBE = "youtube"
    INSTAGRAM = "instagram"


class ContentHint(StrEnum):
    """Pista por URL; `fetch` confirma el tipo real con los metadatos."""

    VIDEO = "video"
    POST = "post"


_YOUTUBE = re.compile(r"^https?://(?:www\.|m\.)?(?:youtube\.com/(?:shorts/|watch\?)|youtu\.be/)", re.I)
_IG_VIDEO = re.compile(r"^https?://(?:www\.)?instagram\.com/(?:[\w.]+/)?(?:reels?|tv)/[\w-]+", re.I)
_IG_POST = re.compile(r"^https?://(?:www\.)?instagram\.com/(?:[\w.]+/)?p/[\w-]+", re.I)


def classify_url(url: str) -> tuple[Platform, ContentHint] | None:
    if _YOUTUBE.match(url):
        return Platform.YOUTUBE, ContentHint.VIDEO
    if _IG_VIDEO.match(url):
        return Platform.INSTAGRAM, ContentHint.VIDEO
    if _IG_POST.match(url):
        return Platform.INSTAGRAM, ContentHint.POST
    return None


def canonical_url(url: str) -> str:
    """Canonical form for deduplicating links (without tracking parameters)."""
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.").removeprefix("m.")
    if host == "youtu.be":
        return f"https://www.youtube.com/watch?v={parts.path.strip('/')}"
    if host == "youtube.com":
        if parts.path.startswith("/shorts/"):
            return f"https://www.youtube.com/shorts/{parts.path.split('/')[2]}"
        video = parse_qs(parts.query).get("v")
        if video:
            return f"https://www.youtube.com/watch?v={video[0]}"
    if host == "instagram.com":
        segments = [s for s in parts.path.split("/") if s]
        for i, segment in enumerate(segments):
            if segment in ("p", "reel", "reels", "tv") and i + 1 < len(segments):
                kind = "p" if segment == "p" else "reel"
                return f"https://www.instagram.com/{kind}/{segments[i + 1]}/"
    return urlunsplit((parts.scheme or "https", host, parts.path, parts.query, ""))
