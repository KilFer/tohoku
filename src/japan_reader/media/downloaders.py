import json
import re
import shutil
import subprocess
from pathlib import Path

import yt_dlp
from pydantic import BaseModel
from yt_dlp.utils import DownloadError

from japan_reader.errors import ConfigError, JapanReaderError, PermanentError, TransientError
from japan_reader.media.subtitles import vtt_to_text
from japan_reader.models import ContentType, SourceMeta
from japan_reader.sources import Platform

VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
SUBTITLE_LANGS = ("es", "en", "ja")
_PERMANENT_MARKERS = (
    "private", "unavailable", "removed", "not available", "login required", "log in",
    "does not exist", "copyright", "sign in to confirm", "404",
    # gallery-dl sin cookies ante un post de Instagram.
    "redirect to login",
    # Reels con restricción de audiencia (edad/país): "This content isn't available to everyone".
    "isn't available", "certain audiences",
)
# Límites de ritmo (sobre todo de Instagram): transitorios aunque el mensaje de yt-dlp incluya
# marcadores permanentes ("Requested content is not available, rate-limit reached or login required").
_RATE_LIMIT_MARKERS = ("rate-limit", "rate limit", "too many requests", "please wait")
_HASHTAG = re.compile(r"#(\w+)")
# HTTP 5xx / 429 son fallos transitorios del servidor aunque su frase de motivo
# (p. ej. "503 Service Unavailable") contenga una palabra de la lista de
# marcadores permanentes ("unavailable"); se comprueban antes que esos marcadores.
# Cubre tanto el formato de yt-dlp ("HTTP Error 503: ...") como el de gallery-dl
# ("HttpError: '503 Service Unavailable' for '<url>'").
_HTTP_STATUS = re.compile(r"http\s*error[:\s]*'?(\d{3})")


class TooLongError(PermanentError):
    """El vídeo supera MAX_VIDEO_DURATION_MIN: no tiene sentido buscar otra copia."""


class DownloadedMedia(BaseModel):
    meta: SourceMeta
    videos: list[Path] = []
    images: list[Path] = []
    subtitles: str | None = None


def classify_download_error(message: str) -> type[JapanReaderError]:
    lowered = message.lower()
    if any(marker in lowered for marker in _RATE_LIMIT_MARKERS):
        return TransientError
    match = _HTTP_STATUS.search(lowered)
    if match and (int(match.group(1)) >= 500 or int(match.group(1)) == 429):
        return TransientError
    return PermanentError if any(marker in lowered for marker in _PERMANENT_MARKERS) else TransientError


def prepare_cookies(src: Path | None, dest_dir: Path) -> Path | None:
    """Copia de trabajo de las cookies: yt-dlp y gallery-dl reescriben el fichero que usan."""
    if src is None:
        return None
    if not src.exists():
        raise ConfigError(f"No existe el fichero de cookies de Instagram: {src}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    copy = dest_dir / "cookies.txt"
    shutil.copyfile(src, copy)
    return copy


def meta_from_ytdlp(info: dict, url: str, platform: Platform) -> SourceMeta:
    description = info.get("description") or ""
    hashtags = sorted(set(info.get("tags") or []) | set(_HASHTAG.findall(description)))
    upload = info.get("upload_date")
    return SourceMeta(
        url=url,
        platform=platform,
        content_type=ContentType.VIDEO,
        title=info.get("title"),
        description=description or None,
        hashtags=hashtags,
        author=info.get("uploader") or info.get("channel"),
        published=f"{upload[:4]}-{upload[4:6]}-{upload[6:8]}" if upload else None,
        duration_s=info.get("duration"),
    )


def meta_from_gallerydl(data: dict, url: str, content_type: ContentType) -> SourceMeta:
    description = data.get("description") or ""
    tags = [t.lstrip("#") for t in data.get("tags") or []] or _HASHTAG.findall(description)
    date = data.get("date")
    return SourceMeta(
        url=url,
        platform=Platform.INSTAGRAM,
        content_type=content_type,
        description=description or None,
        hashtags=sorted(set(tags)),
        author=data.get("username") or data.get("fullname"),
        published=str(date)[:10] if date else None,
    )


class YtDlpDownloader:
    """Vídeos de YouTube e Instagram Reels."""

    def __init__(self, cookies_file: Path | None, max_duration_s: int, ydl_factory=yt_dlp.YoutubeDL) -> None:
        self._cookies = cookies_file
        self._max_duration = max_duration_s
        self._factory = ydl_factory

    def download(self, url: str, platform: Platform, dest: Path) -> DownloadedMedia:
        dest.mkdir(parents=True, exist_ok=True)
        cookies = prepare_cookies(self._cookies, dest)
        opts = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "outtmpl": str(dest / "video.%(ext)s"),
            "format": "bv*[height<=720]+ba/b[height<=720]/b",
            "merge_output_format": "mp4",
            "writesubtitles": True,
            "writeautomaticsub": False,
            "subtitleslangs": list(SUBTITLE_LANGS),
            "subtitlesformat": "vtt",
            "cookiefile": str(cookies) if cookies else None,
        }
        try:
            with self._factory(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                duration = info.get("duration")
                if duration and duration > self._max_duration:
                    raise TooLongError(f"demasiado largo ({duration:.0f} s > {self._max_duration} s)")
                ydl.process_ie_result(info, download=True)
        except DownloadError as exc:
            raise classify_download_error(str(exc))(f"yt-dlp: {exc}") from exc
        videos = [p for p in sorted(dest.glob("video.*")) if p.suffix in VIDEO_EXTS]
        if not videos:
            raise PermanentError("yt-dlp: no se descargó ningún vídeo")
        return DownloadedMedia(meta=meta_from_ytdlp(info, url, platform), videos=videos[:1], subtitles=self._subtitles(dest))

    def download_post(self, url: str, dest: Path) -> DownloadedMedia:
        """Post de Instagram (imagen o carrusel) sin sesión: plan B cuando gallery-dl exige login.

        Las imágenes no tienen formatos para yt-dlp; se descarga su miniatura a tamaño original.
        Los elementos de vídeo de un carrusel se descargan como vídeo.
        """
        dest.mkdir(parents=True, exist_ok=True)
        cookies = prepare_cookies(self._cookies, dest)
        opts = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "ignore_no_formats_error": True,
            "outtmpl": str(dest / "post_%(id)s.%(ext)s"),
            "format": "bv*[height<=720]+ba/b[height<=720]/b",
            "merge_output_format": "mp4",
            "cookiefile": str(cookies) if cookies else None,
        }
        images: list[Path] = []
        videos: list[Path] = []
        try:
            with self._factory(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                entries = [e for e in info.get("entries") or [] if e] if info.get("_type") == "playlist" else [info]
                for i, entry in enumerate(entries):
                    if entry.get("formats"):
                        ydl.process_ie_result(entry, download=True)
                        videos += [p for p in sorted(dest.glob(f"post_{entry['id']}.*")) if p.suffix in VIDEO_EXTS]
                        continue
                    thumbnail = entry.get("thumbnail") or ((entry.get("thumbnails") or [{}])[-1]).get("url")
                    if thumbnail:
                        response = ydl.urlopen(thumbnail)
                        try:
                            path = dest / f"post_{i:02}.jpg"
                            path.write_bytes(response.read())
                        finally:
                            response.close()
                        images.append(path)
        except DownloadError as exc:
            raise classify_download_error(str(exc))(f"yt-dlp: {exc}") from exc
        if not images and not videos:
            raise PermanentError("yt-dlp: el post no contiene medios")
        if len(images) + len(videos) > 1:
            content_type = ContentType.CAROUSEL
        else:
            content_type = ContentType.VIDEO if videos else ContentType.IMAGE
        meta = meta_from_ytdlp(info, url, Platform.INSTAGRAM).model_copy(update={"content_type": content_type, "duration_s": None})
        return DownloadedMedia(meta=meta, images=images, videos=videos)

    @staticmethod
    def _subtitles(dest: Path) -> str | None:
        for lang in SUBTITLE_LANGS:
            path = dest / f"video.{lang}.vtt"
            if path.exists():
                return vtt_to_text(path.read_text(encoding="utf-8")) or None
        return None


class GalleryDlDownloader:
    """Posts de Instagram (imagen o carrusel; los elementos de vídeo se devuelven como vídeos)."""

    def __init__(self, cookies_file: Path | None, binary: str = "gallery-dl", runner=subprocess.run) -> None:
        self._cookies = cookies_file
        self._binary = binary
        self._run = runner

    def download(self, url: str, dest: Path) -> DownloadedMedia:
        dest.mkdir(parents=True, exist_ok=True)
        cmd = [self._binary, "--directory", str(dest), "--filename", "{num:>02}.{extension}", "--write-metadata", "--no-part"]
        cookies = prepare_cookies(self._cookies, dest)
        if cookies:
            cmd += ["--cookies", str(cookies)]
        cmd.append(url)
        try:
            proc = self._run(cmd, capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired as exc:
            raise TransientError("gallery-dl: tiempo de espera agotado") from exc
        files = sorted(p for p in dest.iterdir() if p.suffix.lower() in IMAGE_EXTS | VIDEO_EXTS)
        if proc.returncode != 0 and not files:
            message = (proc.stderr or "").strip()[-500:]
            raise classify_download_error(message)(f"gallery-dl: {message}")
        if not files:
            raise PermanentError("gallery-dl: el post no contiene medios")
        metadata_files = sorted(dest.glob("*.json"))
        data = json.loads(metadata_files[0].read_text(encoding="utf-8")) if metadata_files else {}
        images = [p for p in files if p.suffix.lower() in IMAGE_EXTS]
        videos = [p for p in files if p.suffix.lower() in VIDEO_EXTS]
        if len(files) > 1:
            content_type = ContentType.CAROUSEL
        else:
            content_type = ContentType.VIDEO if videos else ContentType.IMAGE
        return DownloadedMedia(meta=meta_from_gallerydl(data, url, content_type), images=images, videos=videos)
