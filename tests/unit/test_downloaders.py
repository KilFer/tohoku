import json
import stat
import subprocess
from pathlib import Path

import pytest
from yt_dlp.utils import DownloadError

from japan_reader.errors import ConfigError, PermanentError, TransientError
from japan_reader.media.downloaders import (
    GalleryDlDownloader,
    TooLongError,
    YtDlpDownloader,
    classify_download_error,
    prepare_cookies,
)
from japan_reader.models import ContentType
from japan_reader.sources import Platform

VTT = "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nBienvenidos a Kioto\n"


def ydl_factory(info: dict, error: str | None = None, subtitles: bool = True):
    created = []

    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts
            created.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            cookie = self.opts.get("cookiefile")
            if cookie:
                Path(cookie).write_text("rewritten by yt-dlp")
            return False

        def extract_info(self, url, download=False):
            if error:
                raise DownloadError(error)
            return dict(info)

        def process_ie_result(self, result, download=True):
            dest = Path(self.opts["outtmpl"]).parent
            (dest / "video.mp4").write_bytes(b"video")
            if subtitles:
                (dest / "video.es.vtt").write_text(VTT)
            return result

    FakeYDL.created = created
    return FakeYDL


INFO = {
    "title": "Fushimi Inari al amanecer",
    "description": "Consejos para evitar colas #kyoto #japon",
    "uploader": "viajero",
    "upload_date": "20260801",
    "duration": 45,
    "tags": ["travel"],
}


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("ERROR: Private video", PermanentError),
        ("ERROR: This video is unavailable", PermanentError),
        # Final review 3: los límites de ritmo de Instagram son transitorios aunque el mensaje
        # contenga también marcadores permanentes ("not available", "login required").
        ("Requested content is not available, rate-limit reached or login required", TransientError),
        ("HTTP Error 429: Too Many Requests", TransientError),
        ("Please wait a few minutes before you try again.", TransientError),
        ("rate limit exceeded", TransientError),
        ("HTTP Error 404: Not Found", PermanentError),
        ("Read timed out", TransientError),
        ("HTTP Error 503: Service Unavailable", TransientError),
        ("HttpError: '503 Service Unavailable' for 'https://x'", TransientError),
        ("HttpError: '429 Too Many Requests' for 'https://x'", TransientError),
        # gallery-dl sin cookies ante un post de Instagram: reintentar no sirve de nada.
        ("[instagram][error] HTTP redirect to login page (https://www.instagram.com/accounts/login/)", PermanentError),
        # Reel con restricción de audiencia (edad/país): sin sesión nunca se podrá ver.
        ("ERROR: [Instagram] C73RxLTy8qF: This content isn't available to everyone: It can't be seen by certain audiences.", PermanentError),
    ],
)
def test_classify_download_error(message, expected):
    assert classify_download_error(message) is expected


def test_ytdlp_download_returns_video_meta_and_subtitles(tmp_path):
    factory = ydl_factory(INFO)
    media = YtDlpDownloader(None, 900, ydl_factory=factory).download("https://youtu.be/x", Platform.YOUTUBE, tmp_path / "raw")

    assert media.videos == [tmp_path / "raw" / "video.mp4"]
    assert media.subtitles == "Bienvenidos a Kioto"
    assert media.meta.title == "Fushimi Inari al amanecer"
    assert media.meta.author == "viajero"
    assert media.meta.published == "2026-08-01"
    assert media.meta.content_type == ContentType.VIDEO
    assert set(media.meta.hashtags) == {"kyoto", "japon", "travel"}
    opts = factory.created[0].opts
    assert opts["writesubtitles"] is True and opts["writeautomaticsub"] is False


def test_ytdlp_rejects_long_videos(tmp_path):
    with pytest.raises(TooLongError, match="demasiado largo"):
        YtDlpDownloader(None, 900, ydl_factory=ydl_factory(INFO | {"duration": 3600})).download(
            "https://youtu.be/x", Platform.YOUTUBE, tmp_path / "raw"
        )


def test_ytdlp_maps_errors(tmp_path):
    with pytest.raises(PermanentError):
        YtDlpDownloader(None, 900, ydl_factory=ydl_factory(INFO, error="Private video")).download(
            "https://youtu.be/x", Platform.YOUTUBE, tmp_path / "raw"
        )


def test_cookies_file_is_never_written(tmp_path):
    """Review Focus 4: el fichero original (montado solo lectura) no se modifica."""
    original = tmp_path / "cookies.txt"
    original.write_text("# Netscape HTTP Cookie File\n")
    original.chmod(stat.S_IRUSR)
    factory = ydl_factory(INFO)

    YtDlpDownloader(original, 900, ydl_factory=factory).download("https://instagram.com/reel/x", Platform.INSTAGRAM, tmp_path / "raw")

    used = Path(factory.created[0].opts["cookiefile"])
    assert used != original
    assert original.read_text() == "# Netscape HTTP Cookie File\n"


def test_prepare_cookies_missing_file(tmp_path):
    with pytest.raises(ConfigError):
        prepare_cookies(tmp_path / "missing.txt", tmp_path)
    assert prepare_cookies(None, tmp_path) is None


def gallery_runner(files: dict[str, bytes], meta: dict, returncode: int = 0, stderr: str = ""):
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        dest = Path(cmd[cmd.index("--directory") + 1])
        dest.mkdir(parents=True, exist_ok=True)
        for name, data in files.items():
            (dest / name).write_bytes(data)
            (dest / f"{name}.json").write_text(json.dumps(meta))
        return subprocess.CompletedProcess(cmd, returncode, stdout="", stderr=stderr)

    run.calls = calls
    return run


POST_META = {"description": "Qué comprar en Don Quijote #souvenirs", "username": "tokyoshop", "date": "2026-07-01 10:00:00", "tags": ["#souvenirs"]}


def test_gallery_carousel(tmp_path):
    runner = gallery_runner({"01.jpg": b"a", "02.jpg": b"b"}, POST_META)

    media = GalleryDlDownloader(None, runner=runner).download("https://www.instagram.com/p/X/", tmp_path / "raw")

    assert media.meta.content_type == ContentType.CAROUSEL
    assert [p.name for p in media.images] == ["01.jpg", "02.jpg"]
    assert media.videos == []
    assert media.meta.author == "tokyoshop"
    assert media.meta.published == "2026-07-01"
    assert media.meta.hashtags == ["souvenirs"]


def test_gallery_single_video_post(tmp_path):
    media = GalleryDlDownloader(None, runner=gallery_runner({"01.mp4": b"v"}, POST_META)).download(
        "https://www.instagram.com/p/X/", tmp_path / "raw"
    )
    assert media.meta.content_type == ContentType.VIDEO
    assert [p.name for p in media.videos] == ["01.mp4"]


def test_gallery_errors(tmp_path):
    with pytest.raises(PermanentError):
        GalleryDlDownloader(None, runner=gallery_runner({}, {}, 1, "HttpError: '404 Not Found'")).download("u", tmp_path / "a")
    with pytest.raises(TransientError):
        GalleryDlDownloader(None, runner=gallery_runner({}, {}, 1, "Read timed out")).download("u", tmp_path / "b")
    with pytest.raises(PermanentError, match="no contiene medios"):
        GalleryDlDownloader(None, runner=gallery_runner({}, {})).download("u", tmp_path / "c")


def test_gallery_uses_cookie_copy(tmp_path):
    original = tmp_path / "cookies.txt"
    original.write_text("c")
    runner = gallery_runner({"01.jpg": b"a"}, POST_META)

    GalleryDlDownloader(original, runner=runner).download("https://www.instagram.com/p/X/", tmp_path / "raw")

    cmd = runner.calls[0]
    assert Path(cmd[cmd.index("--cookies") + 1]) != original


def post_ydl_factory(info: dict, images: dict[str, bytes] | None = None, error: str | None = None):
    """yt-dlp ante un post de Instagram: sin formatos en las imágenes, miniatura a tamaño original."""
    created = []

    class FakeResponse:
        def __init__(self, data: bytes):
            self._data = data

        def read(self):
            return self._data

        def close(self):
            pass

    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts
            self.processed = []
            created.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download=False):
            if error:
                raise DownloadError(error)
            return json.loads(json.dumps(info))

        def urlopen(self, url):
            return FakeResponse((images or {})[url])

        def process_ie_result(self, result, download=True):
            self.processed.append(result["id"])
            Path(self.opts["outtmpl"].replace("%(id)s", result["id"]).replace("%(ext)s", "mp4")).write_bytes(b"video")
            return result


    FakeYDL.created = created
    return FakeYDL


def image_entry(entry_id: str) -> dict:
    return {"id": entry_id, "formats": [], "thumbnail": f"https://cdn/{entry_id}.jpg", "thumbnails": [{"url": f"https://cdn/{entry_id}_small.jpg"}]}


POST_INFO = {
    "_type": "playlist",
    "id": "C5qf",
    "title": "Post by japan.undiscovered",
    "description": "Las 6 torres más famosas de Japón #tokyotower",
    "uploader": "Discover Japan",
    "channel": "japan.undiscovered",
    "upload_date": "20240412",
    "entries": [image_entry("a"), None, image_entry("b")],
}


def test_ytdlp_post_carousel_downloads_original_images(tmp_path):
    factory = post_ydl_factory(POST_INFO, {"https://cdn/a.jpg": b"A", "https://cdn/b.jpg": b"B"})

    media = YtDlpDownloader(None, 900, ydl_factory=factory).download_post("https://www.instagram.com/p/C5qf/", tmp_path / "raw")

    assert [p.read_bytes() for p in media.images] == [b"A", b"B"]
    assert media.videos == []
    assert media.meta.content_type == ContentType.CAROUSEL
    assert media.meta.platform == Platform.INSTAGRAM
    assert media.meta.description == "Las 6 torres más famosas de Japón #tokyotower"
    assert media.meta.published == "2024-04-12"
    assert factory.created[0].opts["ignore_no_formats_error"] is True
    assert factory.created[0].processed == []


def test_ytdlp_post_single_image_uses_last_thumbnail_without_best(tmp_path):
    info = {"id": "X", "formats": [], "description": "Onigiri de 7-Eleven", "thumbnails": [{"url": "https://cdn/s.jpg"}, {"url": "https://cdn/l.jpg"}]}
    factory = post_ydl_factory(info, {"https://cdn/l.jpg": b"L"})

    media = YtDlpDownloader(None, 900, ydl_factory=factory).download_post("https://www.instagram.com/p/X/", tmp_path / "raw")

    assert [p.read_bytes() for p in media.images] == [b"L"]
    assert media.meta.content_type == ContentType.IMAGE


def test_ytdlp_post_downloads_videos_inside_carousel(tmp_path):
    video = {"id": "v", "formats": [{"format_id": "1"}], "thumbnail": "https://cdn/v.jpg"}
    info = POST_INFO | {"entries": [image_entry("a"), video]}
    factory = post_ydl_factory(info, {"https://cdn/a.jpg": b"A"})

    media = YtDlpDownloader(None, 900, ydl_factory=factory).download_post("https://www.instagram.com/p/C5qf/", tmp_path / "raw")

    assert [p.read_bytes() for p in media.images] == [b"A"]
    assert [p.name for p in media.videos] == ["post_v.mp4"]
    assert factory.created[0].processed == ["v"]
    assert media.meta.content_type == ContentType.CAROUSEL


def test_ytdlp_post_without_media_is_permanent(tmp_path):
    factory = post_ydl_factory({"id": "X", "formats": [], "thumbnails": []})
    with pytest.raises(PermanentError, match="no contiene medios"):
        YtDlpDownloader(None, 900, ydl_factory=factory).download_post("https://www.instagram.com/p/X/", tmp_path / "raw")


def test_ytdlp_post_maps_errors(tmp_path):
    with pytest.raises(PermanentError):
        YtDlpDownloader(None, 900, ydl_factory=post_ydl_factory({}, error="This content is unavailable")).download_post(
            "https://www.instagram.com/p/X/", tmp_path / "raw"
        )
