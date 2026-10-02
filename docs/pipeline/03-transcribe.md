# Stage 3 — transcribe

**English** · [Español](03-transcribe.es.md)

**What it does:** gets the spoken text of the content.

**Input:** `FetchResult.audio_files` and `FetchResult.subtitles`.
**Output:** `Transcript {text, language, origin: subtitulos|whisper|none}`.

**Rules:**
- If there are manual subtitles with at least 5 words, they are used and Whisper does not run.
- No audio (image posts or carousels without videos) → `origin=none`, empty text.
- Carousels with several videos: each track is transcribed separately and labelled `[Elemento N]` (item N).
- When done, the WAV files are deleted (images and frames are kept so you can reprocess from `extract`).

**Dependencies:** faster-whisper (CTranslate2, CPU). The model (~3 GB for `large-v3`) is downloaded once into `WHISPER_DOWNLOAD_ROOT` (the `/models` volume in Docker).
**Configuration:** `WHISPER_MODEL` (`large-v3` by default; `large-v3-turbo` is faster), `WHISPER_COMPUTE_TYPE` (`int8`), `WHISPER_THREADS` (6), VAD enabled, `beam_size=5`.

**Expected performance:** on a 6-core server CPU, a few minutes per minute of audio with `large-v3`. The queue is sequential.

**Failures:** library or read errors → the job is retried (the audio is not deleted until it finishes successfully).

**How to test it:** `uv run pytest tests/unit/test_transcribe.py`. With a real model: `uv run pytest -m integration -k whisper`.
