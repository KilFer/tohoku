import logging
from pathlib import Path
from typing import Protocol

from tohoku.context import JobContext
from tohoku.models import FetchResult, Transcript

log = logging.getLogger(__name__)

MIN_SUBTITLE_WORDS = 5


class Transcriber(Protocol):
    def transcribe(self, audio: Path) -> tuple[str, str | None]: ...


class WhisperTranscriber:
    """faster-whisper en CPU. El modelo se carga la primera vez que se usa."""

    def __init__(self, model_name: str, compute_type: str, download_root: Path, threads: int) -> None:
        self._name = model_name
        self._compute_type = compute_type
        self._download_root = download_root
        self._threads = threads
        self._model = None

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            log.info("cargando modelo whisper %s (%s)", self._name, self._compute_type)
            self._model = WhisperModel(
                self._name,
                device="cpu",
                compute_type=self._compute_type,
                cpu_threads=self._threads,
                download_root=str(self._download_root),
            )
        return self._model

    def transcribe(self, audio: Path) -> tuple[str, str | None]:
        segments, info = self._load().transcribe(str(audio), vad_filter=True, beam_size=5)
        text = " ".join(segment.text.strip() for segment in segments).strip()
        return text, info.language


class TranscribeStage:
    """Etapa 3: texto del audio (subtítulos manuales o Whisper). Borra el audio al terminar."""

    name = "transcribe"
    result_model = Transcript

    def __init__(self, transcriber: Transcriber) -> None:
        self._transcriber = transcriber

    def run(self, ctx: JobContext) -> Transcript:
        fetch = ctx.result("fetch", FetchResult)
        audio = [ctx.workdir / rel for rel in fetch.audio_files]
        if fetch.subtitles and len(fetch.subtitles.split()) >= MIN_SUBTITLE_WORDS:
            result = Transcript(text=fetch.subtitles, origin="subtitulos")
        elif not audio:
            result = Transcript(origin="none")
        else:
            parts: list[str] = []
            language: str | None = None
            for i, path in enumerate(audio):
                text, lang = self._transcriber.transcribe(path)
                language = language or lang
                parts.append(f"[Elemento {i + 1}] {text}" if len(audio) > 1 else text)
            result = Transcript(text="\n".join(parts).strip(), language=language, origin="whisper")
        for path in audio:
            path.unlink(missing_ok=True)
        log.info("bookmark=%s transcripcion origen=%s palabras=%d", ctx.job.bookmark_id, result.origin, len(result.text.split()))
        return result
