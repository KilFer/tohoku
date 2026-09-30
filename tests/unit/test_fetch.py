import pytest
from PIL import Image

from builders import make_ctx, make_job
from fakes import FakeKarakeep
from helpers import make_image, make_video
from tohoku.clients.karakeep import Bookmark
from tohoku.errors import PermanentError, TransientError
from tohoku.media.downloaders import DownloadedMedia, TooLongError
from tohoku.models import ContentType, SourceMeta
from tohoku.sources import ContentHint, Platform
from tohoku.stages.fetch import FetchStage


class StubVideo:
    def __init__(self, error=None, post_error=None):
        self.error = error
        self.post_error = post_error
        self.post_calls = 0

    def download(self, url, platform, dest):
        if self.error:
            raise self.error
        video = make_video(dest / "video.mp4")
        meta = SourceMeta(url=url, platform=platform, content_type=ContentType.VIDEO, title="Vídeo")
        return DownloadedMedia(meta=meta, videos=[video], subtitles="hola")

    def download_post(self, url, dest):
        self.post_calls += 1
        if self.post_error:
            raise self.post_error
        images = [make_image(dest / f"post_{i:02}.jpg") for i in range(2)]
        meta = SourceMeta(url=url, platform=Platform.INSTAGRAM, content_type=ContentType.CAROUSEL, description="desde yt-dlp")
        return DownloadedMedia(meta=meta, images=images)


class StubPost:
    def __init__(self, count=3, error=None):
        self.count = count
        self.error = error

    def download(self, url, dest):
        if self.error:
            raise self.error
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


def test_raw_dir_is_removed_even_when_download_fails(tmp_path, settings):
    """Final review minor a: `raw/` puede contener la copia de las cookies."""

    class Failing:
        def download(self, url, platform, dest):
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "cookies.txt").write_text("secreto")
            raise PermanentError("Private video")

    ctx = make_ctx(tmp_path)
    with pytest.raises(PermanentError):
        FetchStage(settings, Failing(), StubPost(), FakeKarakeep()).run(ctx)
    assert not (ctx.workdir / "raw").exists()


def test_too_long_video_does_not_use_karakeep_fallback(tmp_path, settings):
    karakeep = FakeKarakeep([Bookmark(id="b1", url=IG_REEL.url, video_asset_id="a1")])
    karakeep.assets["a1"] = b"x"
    error = TooLongError("demasiado largo (1200 s > 900 s)")
    with pytest.raises(PermanentError, match="demasiado largo"):
        FetchStage(settings, StubVideo(error), StubPost(), karakeep).run(make_ctx(tmp_path, job=IG_REEL))


class FakeClock:
    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def test_instagram_downloads_are_spaced(tmp_path, settings):
    """Final review 3: descargas de Instagram separadas al menos INSTAGRAM_MIN_INTERVAL_SECONDS."""
    s = settings.model_copy(update={"instagram_min_interval_seconds": 20, "reel_keyframes_enabled": False})
    fake = FakeClock()
    stage = FetchStage(s, StubVideo(), StubPost(count=1), FakeKarakeep(), sleep=fake.sleep, clock=fake.clock)

    stage.run(make_ctx(tmp_path / "1", job=IG_POST))
    assert fake.sleeps == []
    fake.now += 5
    stage.run(make_ctx(tmp_path / "2", job=IG_REEL))
    assert fake.sleeps == [15]
    stage.run(make_ctx(tmp_path / "3"))  # YouTube: sin espera
    assert fake.sleeps == [15]
    fake.now += 30
    stage.run(make_ctx(tmp_path / "4", job=IG_POST))
    assert fake.sleeps == [15]


def test_failed_instagram_download_also_counts_for_spacing(tmp_path, settings):
    fake = FakeClock()
    karakeep = FakeKarakeep([Bookmark(id="b1", url=IG_REEL.url)])
    stage = FetchStage(settings, StubVideo(TransientError("timeout")), StubPost(count=1), karakeep, sleep=fake.sleep, clock=fake.clock)
    with pytest.raises(TransientError):
        stage.run(make_ctx(tmp_path / "1", job=IG_REEL))
    with pytest.raises(TransientError):
        stage.run(make_ctx(tmp_path / "2", job=IG_REEL))
    assert fake.sleeps == [20]


def test_post_falls_back_to_ytdlp_when_gallery_needs_login(tmp_path, settings):
    video = StubVideo()
    gallery = StubPost(error=PermanentError("gallery-dl: HTTP redirect to login page"))

    result = FetchStage(settings, video, gallery, FakeKarakeep()).run(make_ctx(tmp_path, job=IG_POST))

    assert result.meta.description == "desde yt-dlp"
    assert len(result.images) == 2
    assert video.post_calls == 1


def test_post_uses_karakeep_when_ytdlp_also_fails(tmp_path, settings):
    image_bytes = make_image(tmp_path / "src.jpg").read_bytes()
    karakeep = FakeKarakeep([Bookmark(id="b1", url=IG_POST.url, title="Desde Karakeep", image_asset_id="i1")])
    karakeep.assets["i1"] = image_bytes
    video = StubVideo(post_error=PermanentError("yt-dlp: unavailable"))
    gallery = StubPost(error=PermanentError("gallery-dl: HTTP redirect to login page"))

    result = FetchStage(settings, video, gallery, karakeep).run(make_ctx(tmp_path, job=IG_POST))

    assert result.meta.title == "Desde Karakeep"
    assert len(result.images) == 1


def test_post_transient_gallery_error_does_not_try_ytdlp(tmp_path, settings):
    video = StubVideo()
    with pytest.raises(TransientError):
        FetchStage(settings, video, StubPost(error=TransientError("timeout")), FakeKarakeep()).run(make_ctx(tmp_path, job=IG_POST))
    assert video.post_calls == 0


def test_post_transient_ytdlp_error_is_not_masked_by_karakeep(tmp_path, settings):
    karakeep = FakeKarakeep([Bookmark(id="b1", url=IG_POST.url, image_asset_id="i1")])
    video = StubVideo(post_error=TransientError("rate limit"))
    gallery = StubPost(error=PermanentError("gallery-dl: HTTP redirect to login page"))
    with pytest.raises(TransientError):
        FetchStage(settings, video, gallery, karakeep).run(make_ctx(tmp_path, job=IG_POST))
