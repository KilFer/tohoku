import subprocess
from pathlib import Path


def _probe(args: list[str]) -> str:
    return subprocess.run(["ffprobe", "-v", "error", *args], capture_output=True, text=True, check=True).stdout.strip()


def has_audio(video: Path) -> bool:
    return bool(_probe(["-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(video)]))


def probe_duration(path: Path) -> float | None:
    try:
        return float(_probe(["-show_entries", "format=duration", "-of", "csv=p=0", str(path)]))
    except ValueError:
        return None


def extract_audio(video: Path, dest: Path) -> Path | None:
    """Audio track as mono 16 kHz WAV (ideal format for Whisper)."""
    if not has_audio(video):
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", str(dest)],
        check=True,
        capture_output=True,
    )
    return dest
