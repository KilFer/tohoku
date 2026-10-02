from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel

from tohoku.state import Job


@dataclass
class JobContext:
    """What each stage sees: the job, its working directory and the previous results."""

    job: Job
    workdir: Path
    results: dict[str, BaseModel] = field(default_factory=dict)

    def result[T: BaseModel](self, name: str, cls: type[T]) -> T:
        value = self.results[name]
        if not isinstance(value, cls):
            raise TypeError(f"resultado '{name}' es {type(value).__name__}, se esperaba {cls.__name__}")
        return value
