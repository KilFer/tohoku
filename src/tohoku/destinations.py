"""Destinos configurables (`config/destinos.yaml`): qué listas de Karakeep van a qué destino y con qué flujo."""
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from tohoku.errors import ConfigError
from tohoku.text import label_key

_BASE_KEYS = ("flujo", "raiz", "descripcion", "prompt")
_TOP_KEYS = {"listas", "destinos", "clasificador", "destino_por_defecto", "limpieza"}
_LABEL = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


class HasParams(Protocol):
    params_model: type[BaseModel]


@dataclass(frozen=True)
class Destination:
    nombre: str
    flujo: str
    raiz: str  # etiqueta de la nota raíz en Trilium, sin '#'
    descripcion: str
    prompt: str  # texto del prompt de extracción (ya leído del fichero)
    params: BaseModel  # parámetros validados con el `params_model` del flujo


class ClassifierConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    modelo: str | None = None  # None → OPENROUTER_TEXT_MODEL
    modo: str = "json_schema"  # clave de CLASSIFIERS
    confianza_minima: float = Field(0.5, ge=0, le=1)
    margen_revision: float = Field(0.15, ge=0, le=1)


class CleanupConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    retencion_dias: int = Field(30, ge=0)  # días que se guardan los resultados de etapa de un job terminado; 0 = borrar al terminar


@dataclass(frozen=True)
class DestinationsConfig:
    listas: dict[str, list[str]]
    destinos: dict[str, Destination]
    clasificador: ClassifierConfig
    destino_por_defecto: str  # destino de reserva para los jobs sin candidatos
    limpieza: CleanupConfig = CleanupConfig()

    def candidates_for(self, list_id: str) -> list[str]:
        return list(self.listas.get(list_id, []))

    def needs_classifier(self) -> bool:
        """Hay clasificador si un bookmark puede tener varios candidatos: una lista con varios destinos, o
        listas con destinos distintos (la ingesta une los candidatos de todas las listas del bookmark)."""
        if any(len(names) > 1 for names in self.listas.values()):
            return True
        return len({name for names in self.listas.values() for name in names}) > 1


def load_destinations(path: Path, flows: Mapping[str, HasParams]) -> DestinationsConfig:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"No existe el fichero de destinos {path} (DESTINOS_FILE)") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: YAML inválido: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: se esperaba un mapa con 'listas' y 'destinos'")
    unknown = sorted(set(raw) - _TOP_KEYS)
    if unknown:
        raise ConfigError(f"{path}: claves desconocidas: {', '.join(unknown)}")
    destinos_raw = raw.get("destinos") or {}
    if not isinstance(destinos_raw, dict):
        raise ConfigError(f"{path}: 'destinos' debe ser un mapa")
    if not destinos_raw:
        raise ConfigError(f"{path}: no hay ningún destino en 'destinos'")
    destinos = {str(name): _destination(path, str(name), spec, flows) for name, spec in destinos_raw.items()}
    seen: dict[str, str] = {}
    for name in destinos:
        other = seen.setdefault(label_key(name), name)
        if other != name:
            raise ConfigError(
                f"{path}: los destinos '{other}' y '{name}' son el mismo nombre para el clasificador"
                " (mayúsculas, acentos, espacios, guiones y guiones bajos no cuentan); renombra uno"
            )
    listas_raw = raw.get("listas") or {}
    if not isinstance(listas_raw, dict):
        raise ConfigError(f"{path}: 'listas' debe ser un mapa")
    if not listas_raw:
        raise ConfigError(f"{path}: no hay ninguna lista de Karakeep en 'listas'")
    listas: dict[str, list[str]] = {}
    for list_id, names in listas_raw.items():
        if names is not None and not isinstance(names, str) and not (
            isinstance(names, list) and all(isinstance(n, str) for n in names)
        ):
            raise ConfigError(f"{path}: la lista '{list_id}' debe ser un destino o una lista de destinos")
        names = [names] if isinstance(names, str) else list(names or [])
        if not names:
            raise ConfigError(f"{path}: la lista '{list_id}' no apunta a ningún destino")
        missing = [n for n in names if n not in destinos]
        if missing:
            raise ConfigError(f"{path}: la lista '{list_id}' apunta a destinos que no existen: {', '.join(missing)}")
        listas[str(list_id)] = names
    clasificador_raw = raw.get("clasificador")
    if clasificador_raw is None:
        clasificador = ClassifierConfig()
    elif not isinstance(clasificador_raw, dict):
        raise ConfigError(f"{path}: 'clasificador' debe ser un mapa")
    else:
        try:
            clasificador = ClassifierConfig.model_validate(clasificador_raw)
        except ValidationError as exc:
            raise ConfigError(f"{path}: 'clasificador' inválido:\n{exc}") from exc
    limpieza_raw = raw.get("limpieza")
    if limpieza_raw is None:
        limpieza = CleanupConfig()
    elif not isinstance(limpieza_raw, dict):
        raise ConfigError(f"{path}: 'limpieza' debe ser un mapa")
    else:
        try:
            limpieza = CleanupConfig.model_validate(limpieza_raw)
        except ValidationError as exc:
            raise ConfigError(f"{path}: 'limpieza' inválido:\n{exc}") from exc
    por_defecto = raw.get("destino_por_defecto")
    if por_defecto is None:
        if len(destinos) != 1:
            raise ConfigError(f"{path}: con varios destinos hay que indicar 'destino_por_defecto' (el destino de reserva para los jobs sin candidatos)")
        por_defecto = next(iter(destinos))
    elif not isinstance(por_defecto, str) or por_defecto not in destinos:
        raise ConfigError(f"{path}: 'destino_por_defecto' apunta a un destino que no existe: {por_defecto}")
    return DestinationsConfig(
        listas=listas, destinos=destinos, clasificador=clasificador, destino_por_defecto=por_defecto, limpieza=limpieza,
    )


def _destination(path: Path, name: str, spec: Any, flows: Mapping[str, HasParams]) -> Destination:
    where = f"{path}: destino '{name}'"
    if not isinstance(spec, dict):
        raise ConfigError(f"{where}: se esperaba un mapa")
    missing = [key for key in _BASE_KEYS if key not in spec]
    if missing:
        raise ConfigError(f"{where}: faltan claves: {', '.join(missing)}")
    for key in _BASE_KEYS:
        value = spec[key]
        if value is None or (isinstance(value, str) and not value.strip()):
            hint = " (¿un '#' sin comillas? escribe la etiqueta sin '#')" if key == "raiz" else ""
            raise ConfigError(f"{where}: '{key}' está vacío{hint}")
        if not isinstance(value, str):
            raise ConfigError(f"{where}: '{key}' debe ser texto")
    flujo = spec["flujo"]
    if flujo not in flows:
        raise ConfigError(f"{where}: flujo desconocido '{flujo}' (disponibles: {', '.join(sorted(flows))})")
    raiz = spec["raiz"]
    if not _LABEL.match(raiz):
        raise ConfigError(f"{where}: 'raiz' debe ser el nombre de una etiqueta de Trilium, sin '#' (p. ej. jrRoot)")
    prompt_path = (path.parent / spec["prompt"]).resolve()
    if not prompt_path.is_file():
        raise ConfigError(f"{where}: no existe el prompt {prompt_path}")
    params_raw = {key: value for key, value in spec.items() if key not in _BASE_KEYS}
    try:
        params = flows[flujo].params_model.model_validate(params_raw)
    except ValidationError as exc:
        raise ConfigError(f"{where}: parámetros inválidos para el flujo '{flujo}':\n{exc}") from exc
    return Destination(
        nombre=name, flujo=flujo, raiz=raiz, descripcion=spec["descripcion"],
        prompt=prompt_path.read_text(encoding="utf-8"), params=params,
    )
