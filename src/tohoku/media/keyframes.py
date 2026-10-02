import subprocess
from pathlib import Path

from PIL import Image

from tohoku.media.audio import probe_duration

SCENE_THRESHOLD = 0.3
DUPLICATE_THRESHOLD = 8.0


def _ffmpeg(args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-y", "-v", "error", *args], check=True, capture_output=True)


def extract_keyframes(video: Path, out_dir: Path, max_frames: int) -> list[Path]:
    """First frame + scene changes; if they do not reach `max_frames`, fill up with uniform sampling.

    Then drops near-identical ones and spreads the remaining ones across the video.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    _ffmpeg([
        "-i", str(video),
        "-vf", f"select=eq(n\\,0)+gt(scene\\,{SCENE_THRESHOLD})",
        "-fps_mode", "vfr",
        str(out_dir / "scene_%03d.jpg"),
    ])
    frames = sorted(out_dir.glob("scene_*.jpg"))
    if len(frames) < max_frames:
        duration = probe_duration(video) or 1.0
        _ffmpeg(["-i", str(video), "-vf", f"fps={max_frames / duration:.4f}", str(out_dir / "uniform_%03d.jpg")])
        frames += sorted(out_dir.glob("uniform_*.jpg"))
    return pick_evenly(dedupe_similar(frames), max_frames)


def _signature(path: Path) -> bytes:
    # In colour: in greyscale pure red and green almost coincide.
    with Image.open(path) as im:
        return im.convert("RGB").resize((8, 8)).tobytes()


def dedupe_similar(paths: list[Path], threshold: float = DUPLICATE_THRESHOLD) -> list[Path]:
    kept: list[Path] = []
    signatures: list[bytes] = []
    for path in paths:
        sig = _signature(path)
        if all(sum(abs(a - b) for a, b in zip(sig, other)) / len(sig) > threshold for other in signatures):
            kept.append(path)
            signatures.append(sig)
    return kept


def pick_evenly[T](items: list[T], n: int) -> list[T]:
    if len(items) <= n:
        return list(items)
    if n == 1:
        return [items[0]]
    return [items[round(i * (len(items) - 1) / (n - 1))] for i in range(n)]
