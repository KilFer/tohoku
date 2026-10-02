# Stage 2 — fetch

**English** · [Español](02-fetch.es.md)

**What it does:** downloads the content and its metadata and prepares the media for the following stages.

**Input:** job (`url`, `platform`, `hint`).
**Output:** `FetchResult {meta, audio_files, subtitles, images, keyframes}`; files in `data/jobs/<bookmark_id>/` (`audio/NN.wav`, `images/NN.jpg`, `frames/VV_NN.jpg`). The original video is deleted when the stage ends.

**Note (cleanup and reprocessing):** when the job finishes (except `error`, which keeps its files until a reprocess finishes it) `data/jobs/<id>/` is deleted, but the `fetch` result is **kept** with its metadata (title, author, caption, URL, used by `publish`) and the `files_purged: true` mark (older results without the key are read as `false`). The pipeline runs `fetch` again only if it is going to run a stage that needs the files and the stored `fetch` has `files_purged`; at most once per job. `transcribe` and `extract` need the files (`needs_files`), and `classify` only when it is going to send images to the classifier (`needs_files_for`: several current candidates, no forced destination, and empty caption and transcript); a job with no `classify` result downloads nothing for it (it is resolved with `destino_legado`).
- `reprocess --from geocode`, `--from resolve` or `--from publish`: downloads nothing and does not fail if the Reel no longer exists (within the retention).
- `--from extract` or `--from classify`: downloads again (`extract` needs frames; `classify` only if it classifies with images); fails if the original is no longer available. (`transcribe` also needs the files; it is repeated with `--from fetch`.)
- `--from fetch`: as always.
- After the retention (`retencion_dias`), or with `retencion_dias: 0`: no stage results remain and everything is redone (download, Whisper, LLM and Places).

See the "Cleanup" section of `docs/operations.md`.

| Type | Tool | What it gets |
|---|---|---|
| Video (Short, Reel) | yt-dlp | video ≤720p, **manual** subtitles (es > en > ja), metadata |
| Image post / carousel | gallery-dl; if it fails permanently, yt-dlp | images (and carousel videos), caption, author, date |

- Audio: mono 16 kHz WAV with ffmpeg (if the video has audio).
- Key frames (if `REEL_KEYFRAMES_ENABLED=true`): first frame + scene changes (threshold 0.3), completed with uniform sampling, without near-duplicates, at most `KEYFRAMES_MAX`.
- Images: at most `POST_IMAGES_MAX`, resized to `IMAGE_MAX_SIDE` px (JPEG).
- Videos longer than `MAX_VIDEO_DURATION_MIN` are rejected before downloading.
- Instagram: at least `INSTAGRAM_MIN_INTERVAL_SECONDS` seconds (20 by default) pass between two consecutive downloads (yt-dlp or gallery-dl); the stage waits if needed.
- The temporary `raw/` directory (original video and the cookies copy) is always deleted at the end, even if the download fails.

**Plan B for posts:** without cookies, gallery-dl gets "HTTP redirect to login page" on any post. On a permanent gallery-dl error, yt-dlp is tried with `ignore_no_formats_error`: it returns the caption and, for each carousel element, the thumbnail at original size (for example 1440×1800), which is downloaded as an image; elements with video are downloaded as video. It costs only one extra request to Instagram per post.

**Fallback:** if Instagram fails permanently (for example it requires login), the video or image that Karakeep archived for the bookmark is used. It is not used when the video is rejected for being too long.

**Dependencies:** yt-dlp, gallery-dl, ffmpeg/ffprobe, Pillow, Karakeep (fallback).
**Configuration:** `INSTAGRAM_COOKIES_FILE` (a copy is used; the original is never modified), `REEL_KEYFRAMES_ENABLED`, `KEYFRAMES_MAX`, `POST_IMAGES_MAX`, `IMAGE_MAX_SIDE`, `MAX_VIDEO_DURATION_MIN`, `INSTAGRAM_MIN_INTERVAL_SECONDS`. An empty `INSTAGRAM_COOKIES_FILE=` is the same as not setting it.

**Failures:** private/deleted/login required/redirect to login/audience restriction ("isn't available to everyone")/404/too long → `PermanentError` (`jr:error`); timeouts, 5xx, 429 and rate limits ("rate-limit", "too many requests", "please wait", even if the message also says "login required") → `TransientError` (retry); a cookies file that does not exist → `ConfigError`.

**How to test it:** `uv run pytest tests/unit/test_fetch.py tests/unit/test_downloaders.py tests/unit/test_media.py`. Real download: `uv run pytest -m integration -k ytdlp`.
