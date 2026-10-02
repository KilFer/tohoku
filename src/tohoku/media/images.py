from pathlib import Path

from PIL import Image, ImageOps


def resize_image(src: Path, dest: Path, max_side: int) -> Path:
    """Convert to JPEG with the longer side capped, to make vision calls cheaper."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        image = ImageOps.exif_transpose(im).convert("RGB")
        image.thumbnail((max_side, max_side))
        image.save(dest, "JPEG", quality=85)
    return dest
