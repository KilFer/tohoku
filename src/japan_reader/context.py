from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel

from japan_reader.state import Job


@dataclass
class JobContext:
    """Lo que ve cada etapa: el job, su directorio de trabajo y los resultados previos."""

    job: Job
    workdir: Path
    results: dict[str, BaseModel] = field(default_factory=dict)

    def result[T: BaseModel](self, name: str, cls: type[T]) -> T:
        value = self.results[name]
        if not isinstance(value, cls):
            raise TypeError(f"resultado '{name}' es {type(value).__name__}, se esperaba {cls.__name__}")
        return value
