import pytest
from PIL import Image

from builders import make_ctx, make_job
from fakes import FakeKarakeep
from helpers import make_image, make_video
from japan_reader.clients.karakeep import Bookmark
from japan_reader.errors import PermanentError, TransientError
from japan_reader.media.downloaders import DownloadedMedia
from japan_reader.models import ContentType, SourceMeta
from japan_reader.sources import ContentHint, Platform
from japan_reader.stages.fetch import FetchStage


class StubVideo:
    def __init__(self, error=None):
        self.error = error

    def download(self, url, platform, dest):
        if self.error:
            raise self.error
        video = make_video(dest / "video.mp4")
        meta = SourceMeta(url=url, platform=platform, content_type=ContentType.VIDEO, title="Vídeo")
        return DownloadedMedia(meta=meta, videos=[video], subtitles="hola")


class StubPost:
    def __init__(self, count=3):
        self.count = count

    def download(self, url, dest):
        images = [make_image(dest / f"{i:02}.jpg") for i in range(self.count)]
        meta = SourceMeta(url=url, platform=Platform.INSTAGRAM, content_type=ContentType.CAROUSEL, description="caption")
        return DownloadedMedia(meta=meta, images=images)


IG_REEL = make_job(url="https://www.instagram.com/reel/X/", platform=Platform.INSTAGRAM, hint=ContentHint.VIDEO)
IG_POST = make_job(url="https://www.instagram.com/p/X/", platform=Platform.INSTAGRAM, hint=ContentHint.POST)


def test_video_produces_audio_and_keyframes_and_removes_video(tmp_path, settings):
    ctx = make_ctx(tmp_path)

    result = FetchStage(settings, StubVideo(), StubPost(), FakeKarakeep()).run(ctx)

    assert result.audio_files == ["audio/00.wav"]
    assert len(result.keyframes) == 3
    assert all((ctx.workdir / f).exists() for f in result.keyframes)
    assert result.subtitles == "hola"
    assert result.images == []
    assert not (ctx.workdir / "raw").exists()


def test_keyframes_can_be_disabled(tmp_path, settings):
    s = settings.model_copy(update={"reel_keyframes_enabled": False})
    result = FetchStage(s, StubVideo(), StubPost(), FakeKarakeep()).run(make_ctx(tmp_path))
    assert result.keyframes == []
    assert result.audio_files == ["audio/00.wav"]


def test_post_images_are_capped_and_resized(tmp_path, settings):
    ctx = make_ctx(tmp_path, job=IG_POST)

    result = FetchStage(settings, StubVideo(), StubPost(count=12), FakeKarakeep()).run(ctx)

    assert len(result.images) == 10
    with Image.open(ctx.workdir / result.images[0]) as im:
        assert max(im.size) == 1024
    assert result.meta.content_type == ContentType.CAROUSEL


def test_instagram_falls_back_to_karakeep_video(tmp_path, settings):
    video_bytes = make_video(tmp_path / "src.mp4").read_bytes()
    karakeep = FakeKarakeep([Bookmark(id="b1", url=IG_REEL.url, title="Desde Karakeep", video_asset_id="a1")])
    karakeep.assets["a1"] = video_bytes

    result = FetchStage(settings, StubVideo(PermanentError("login required")), StubPost(), karakeep).run(make_ctx(tmp_path, job=IG_REEL))

    assert result.meta.title == "Desde Karakeep"
    assert result.audio_files == ["audio/00.wav"]


def test_instagram_without_fallback_reraises(tmp_path, settings):
    karakeep = FakeKarakeep([Bookmark(id="b1", url=IG_REEL.url)])
    with pytest.raises(PermanentError):
        FetchStage(settings, StubVideo(PermanentError("login required")), StubPost(), karakeep).run(make_ctx(tmp_path, job=IG_REEL))


def test_youtube_permanent_error_has_no_fallback(tmp_path, settings):
    with pytest.raises(PermanentError):
        FetchStage(settings, StubVideo(PermanentError("Private video")), StubPost(), FakeKarakeep()).run(make_ctx(tmp_path))


def test_transient_error_is_not_masked_by_fallback(tmp_path, settings):
    karakeep = FakeKarakeep([Bookmark(id="b1", url=IG_REEL.url, video_asset_id="a1")])
    with pytest.raises(TransientError):
        FetchStage(settings, StubVideo(TransientError("timeout")), StubPost(), karakeep).run(make_ctx(tmp_path, job=IG_REEL))


def test_job_without_platform_is_permanent_error(tmp_path, settings):
    job = make_job(url="https://tiktok.com/x", platform=None, hint=None)
    with pytest.raises(PermanentError, match="no soportada"):
        FetchStage(settings, StubVideo(), StubPost(), FakeKarakeep()).run(make_ctx(tmp_path, job=job))
