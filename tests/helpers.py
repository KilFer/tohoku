import subprocess
from pathlib import Path

from PIL import Image


def make_video(path: Path, colors=("red", "blue", "green"), seconds: int = 1, with_audio: bool = True) -> Path:
    """Vídeo sintético: un tramo de color liso por cada color (cambios de escena bruscos)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-v", "error"]
    for color in colors:
        cmd += ["-f", "lavfi", "-i", f"color=c={color}:s=320x240:d={seconds}:r=10"]
    n = len(colors)
    if with_audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds * n}"]
    video_inputs = "".join(f"[{i}:v]" for i in range(n))
    cmd += ["-filter_complex", f"{video_inputs}concat=n={n}:v=1:a=0[v]", "-map", "[v]"]
    if with_audio:
        cmd += ["-map", f"{n}:a", "-c:a", "aac", "-shortest"]
    cmd += ["-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, check=True, capture_output=True)
    return path


def make_image(path: Path, size=(2000, 1500), color: str = "red") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return path
