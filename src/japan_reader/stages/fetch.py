import logging
import shutil
import time
from collections.abc import Callable
from pathlib import Path

from japan_reader.clients.karakeep import KarakeepClient
from japan_reader.config import Settings
from japan_reader.context import JobContext
from japan_reader.errors import JapanReaderError, PermanentError
from japan_reader.media.audio import extract_audio
from japan_reader.media.downloaders import DownloadedMedia, GalleryDlDownloader, TooLongError, YtDlpDownloader
from japan_reader.media.images import resize_image
from japan_reader.media.keyframes import extract_keyframes
from japan_reader.models import ContentType, FetchResult, SourceMeta
from japan_reader.sources import ContentHint, Platform
from japan_reader.state import Job

log = logging.getLogger(__name__)


class FetchStage:
    """Etapa 2: descarga medios y metadatos y los deja listos para transcribir y extraer."""

    name = "fetch"
    result_model = FetchResult

    def __init__(
        self,
        settings: Settings,
        ytdlp: YtDlpDownloader,
        gallery: GalleryDlDownloader,
        karakeep: KarakeepClient,
        keyframer=extract_keyframes,
        audio_extractor=extract_audio,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._ytdlp = ytdlp
        self._gallery = gallery
        self._karakeep = karakeep
        self._keyframer = keyframer
        self._audio = audio_extractor
        self._sleep = sleep
        self._clock = clock
        self._last_instagram: float | None = None

    def run(self, ctx: JobContext) -> FetchResult:
        for sub in ("raw", "images", "frames", "audio"):
            shutil.rmtree(ctx.workdir / sub, ignore_errors=True)
        raw = ctx.workdir / "raw"
        try:
            media, images, audio, frames = self._fetch(ctx, raw)
        finally:
            # `raw/` puede contener la copia de las cookies de Instagram: se borra siempre.
            shutil.rmtree(raw, ignore_errors=True)

        def rel(path: Path) -> str:
            return str(path.relative_to(ctx.workdir))

        log.info(
            "bookmark=%s fetch tipo=%s imagenes=%d fotogramas=%d audios=%d",
            ctx.job.bookmark_id, media.meta.content_type, len(images), len(frames), len(audio),
        )
        return FetchResult(
            meta=media.meta,
            audio_files=[rel(p) for p in audio],
            subtitles=media.subtitles,
            images=[rel(p) for p in images],
            keyframes=[rel(p) for p in frames],
        )

    def _fetch(self, ctx: JobContext, raw: Path) -> tuple[DownloadedMedia, list[Path], list[Path], list[Path]]:
        media = self._download(ctx.job, raw)
        s = self._settings
        images = [
            resize_image(path, ctx.workdir / "images" / f"{i:02}.jpg", s.image_max_side)
            for i, path in enumerate(media.images[: s.post_images_max])
        ]
        audio: list[Path] = []
        frames: list[Path] = []
        for i, video in enumerate(media.videos):
            track = self._audio(video, ctx.workdir / "audio" / f"{i:02}.wav")
            if track:
                audio.append(track)
            if s.reel_keyframes_enabled:
                for j, frame in enumerate(self._keyframer(video, raw / f"frames{i:02}", s.keyframes_max)):
                    frames.append(resize_image(frame, ctx.workdir / "frames" / f"{i:02}_{j:02}.jpg", s.image_max_side))
        return media, images, audio, frames

    def _wait_for_instagram(self) -> None:
        """Deja al menos INSTAGRAM_MIN_INTERVAL_SECONDS entre descargas de Instagram (límites de ritmo)."""
        if self._last_instagram is None:
            return
        wait = self._settings.instagram_min_interval_seconds - (self._clock() - self._last_instagram)
        if wait > 0:
            log.info("espero %.0f s antes de la siguiente descarga de Instagram", wait)
            self._sleep(wait)

    def _download(self, job: Job, raw: Path) -> DownloadedMedia:
        if job.platform is None or job.hint is None:
            raise PermanentError("fuente no soportada")
        instagram = job.platform == Platform.INSTAGRAM
        if instagram:
            self._wait_for_instagram()
        try:
            if job.hint == ContentHint.VIDEO:
                return self._ytdlp.download(job.url, job.platform, raw)
            return self._gallery.download(job.url, raw)
        except PermanentError as exc:
            if not instagram or isinstance(exc, TooLongError):
                raise
            fallback = self._from_karakeep(job, raw)
            if fallback is None:
                raise
            log.warning("bookmark=%s descarga fallida (%s); uso los medios archivados por Karakeep", job.bookmark_id, exc)
            return fallback
        finally:
            if instagram:
                self._last_instagram = self._clock()

    def _from_karakeep(self, job: Job, raw: Path) -> DownloadedMedia | None:
        try:
            bookmark = self._karakeep.get_bookmark(job.bookmark_id)

            def meta(content_type: ContentType) -> SourceMeta:
                return SourceMeta(
                    url=job.url, platform=job.platform, content_type=content_type,
                    title=bookmark.title, description=bookmark.description, author=bookmark.author,
                )

            if bookmark.video_asset_id:
                video = self._karakeep.download_asset(bookmark.video_asset_id, raw / "karakeep_video.mp4")
                return DownloadedMedia(meta=meta(ContentType.VIDEO), videos=[video])
            if bookmark.image_asset_id:
                image = self._karakeep.download_asset(bookmark.image_asset_id, raw / "karakeep_image.jpg")
                return DownloadedMedia(meta=meta(ContentType.IMAGE), images=[image])
        except JapanReaderError as exc:
            log.warning("bookmark=%s no se pudo usar el respaldo de Karakeep: %s", job.bookmark_id, exc)
        return None
