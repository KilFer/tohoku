import json
import stat
import subprocess
from pathlib import Path

import pytest
from yt_dlp.utils import DownloadError

from japan_reader.errors import ConfigError, PermanentError, TransientError
from japan_reader.media.downloaders import (
    GalleryDlDownloader,
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
        ("Requested content is not available, rate-limit reached or login required", PermanentError),
        ("HTTP Error 404: Not Found", PermanentError),
        ("Read timed out", TransientError),
        ("HTTP Error 503: Service Unavailable", TransientError),
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
    with pytest.raises(PermanentError, match="demasiado largo"):
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
