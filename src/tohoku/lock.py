import fcntl
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

LOCK_NAME = "tohoku.lock"


class AlreadyRunning(Exception):
    """Otro proceso `run`/`run-once` ya tiene el candado de DATA_DIR."""


@contextmanager
def single_instance(data_dir: Path) -> Iterator[None]:
    """Candado exclusivo no bloqueante (`fcntl.flock`) en `DATA_DIR/tohoku.lock`."""
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / LOCK_NAME
    with open(path, "a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise AlreadyRunning(f"Ya hay otra instancia de tohoku en marcha (candado {path})") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
