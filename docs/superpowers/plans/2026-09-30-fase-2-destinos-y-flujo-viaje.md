# Fase 2: configuración de destinos y flujo `viaje` — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Modo acordado con el usuario:** subagentes, con **revisión especial de TDD**. Cada tarea declara qué tests deben fallar (RED) y con qué error antes de implementar. El revisor comprueba que el implementador ejecutó el RED, que el fallo fue el esperado (no un error de import o de sintaxis) y que después pasó a GREEN. Una tarea cuyo RED no se vio no está terminada.

**Goal:** Sacar de constantes a un fichero `config/destinos.yaml` todo lo específico de Japón (lista de Karakeep, raíz de Trilium, país, límites geográficos, alias de ciudad, categorías, prompt de extracción), detrás de una interfaz `Flow`, **sin cambiar nada de lo que produce Japón**.

**Architecture:**
- `destinations.py` carga y valida el YAML. Cada destino apunta a un flujo registrado en `flows/registry.py`. El único flujo por ahora es `viaje`, con parámetros `ViajeParams` cuyos valores por defecto son exactamente los de Japón.
- Las etapas existentes (`geocode`, `extract`, `resolve`, `publish`) y `trilium_layout` reciben esos parámetros como argumentos opcionales. Sus valores por defecto reproducen el comportamiento actual, así que los tests existentes siguen construyéndolas igual.
- `wiring` construye las etapas con `FLOWS[dest.flujo].build(dest, deps)`. El pipeline no cambia.

**Tech Stack:** Python 3.12, uv, Pydantic v2, PyYAML, pytest, respx.

**Spec:** `docs/superpowers/specs/2026-09-30-multi-destino-design.md` (§2, §6.2) · **Hoja de ruta:** `docs/superpowers/plans/2026-09-30-fases-2-6-multidestino.md` (Fase 2).

**Rama:** `feat/tohoku`. Nada de esta fase se integra en `master` ni se despliega sin el visto bueno del usuario (Task 8).

## Global Constraints

- Idioma: español en docs, docstrings y mensajes. **Nunca** crear, editar ni mostrar `.env`.
- TDD sin red (`tests/fakes.py`, `tests/builders.py`, respx). `uv run pytest -q` en verde al final de cada tarea. El recuento sale de la salida real, no se estima.
- **Equivalencia de Japón:**
  - Los tests existentes pasan **sin modificar ninguna aserción**. Solo se permite cambiar imports, cómo se construye un objeto (argumentos de etapas y helpers de test) y la firma de los fakes.
  - Si un test existente necesita otra aserción, es una regresión: se para y se reporta.
- Las claves de deduplicación no cambian: `#jrNombreNorm`, `#jrItem` y `name_key`/`normalize_name` quedan intactas en esta fase.
- **Prefijo `jr` intocable** (etiquetas, atributos, `jrRoot`, adjunto `japan-reader.json`).
- Commits en `feat/tohoku`. Cada mensaje termina con `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- No tocar `data/` salvo **leer** una copia de `state.db` en la Task 1.

## Decisiones que ajustan la hoja de ruta (rulings del plan)

1. **Prompt completo por destino** (clave `prompt:` en el YAML) en lugar de "`viaje.md` base + `contexto`".
   - Por qué: el prompt de Japón queda idéntico texto a texto, y un destino nuevo puede ajustarlo por completo.
   - Qué se renderiza: solo los marcadores `{{categorias_lugar}}` y `{{categorias_cosa}}`.
   - Coste: dos destinos de viaje duplican texto de prompt (es contenido, no código).
2. **`palabras_genericas` por destino se aplaza a la fase 6.** `normalize_name` sigue con su lista global, así que las claves de Japón no pueden cambiar. Nueva Zelanda decidirá si lo necesita.
3. **Mover los módulos a `flows/viaje/` y extraer utilidades comunes se aplaza a la fase 5**, cuando el segundo flujo muestre qué es común de verdad. En esta fase, `flows/viaje/` solo contiene los parámetros, el prompt y el adaptador `Flow`.
4. **El pipeline no cambia en la fase 2.** `wiring` monta la lista de etapas. El destino por job llega en la fase 3.
5. **Interfaz `Flow`:**
   - `build(dest, deps) -> FlowRuntime`, con `.stages` y `.refresh()`;
   - `init_trilium(trilium, dest) -> str`.
   - `refresh()` sustituye al `layout.refresh()` del preflight actual y mantiene el mismo contrato duck-typed que ya usan los tests de `preflight`.
6. **Caché de Places:** las entradas existentes son de Japón y siguen sin prefijo. Otros países usan el prefijo `"<PAIS>|"`.
7. **Sin iconos por destino:** una categoría sin icono usa el pin genérico (`ICONS["otro"]`), como hoy.
8. **`Thresholds` y sus variables de entorno** (`JAPAN_MIN_CONFIDENCE`…) no se renombran en esta fase.

## Review Focus

1. **`state.db` real con `relacionado_japon`/`confianza_japon`:** un `reprocess --from geocode` debe seguir funcionando. Tests en Task 1 (carga) y Task 4 (valores, resolve y publish sobre JSON reales).
2. **El LLM devuelve una categoría que no es del destino:** hoy provoca un reintento por `ValidationError`, y tras el cambio a `str` debe seguir haciéndolo. Test en Task 6.
3. **`config/destinos.yaml` con una errata** (clave de parámetro mal escrita, `#` en la raíz, prompt inexistente, lista que apunta a un destino que no existe): debe dar `ConfigError` con un mensaje que nombre la clave, nunca un fallo silencioso. Tests en Task 2.
4. **Caché de Places compartida entre países:** una consulta de Nueva Zelanda no debe reutilizar la entrada de Japón, y Japón no debe perder su caché. Test en Task 3.
5. **Contenedor sin el YAML montado:** la imagen debe llevar `config/` dentro y arrancar igual. Verificación en Task 8.

---

### Task 1: Líneas base (caracterización del comportamiento actual)

Solo fixtures y tests de caracterización, **sin cambiar código de producción**. Estos tests pasan en cuanto se escriben: fijan lo que las tareas siguientes no pueden alterar. Por eso aquí no hay RED, y el revisor debe comprobar que no se tocó `src/`.

**Files:**
- Create: `tests/fixtures/baseline/extract_prompt.md`, `tests/fixtures/baseline/extraction_schema.json`, `tests/fixtures/baseline/name_keys.json`, `tests/fixtures/baseline/rich_plan.json`
- Create: `tests/fixtures/state_results/{rich,no_japon}_{extract,geocode,resolve}.json` (6 ficheros)
- Create: `tests/unit/test_baseline.py`

**Interfaces:**
- Produces: las constantes de ruta `FIXTURES`, `BASELINE` y `STATE` en `tests/unit/test_baseline.py`, que amplían las Tasks 4, 5 y 6.

- [ ] **Step 1: Copia de solo lectura de `state.db`**

```bash
SCRATCH=/tmp/claude-1000/-media-1tb-disk-japan-reader/ae84541b-fb58-40c8-851c-2ad836c092c9/scratchpad
uv run python - <<EOF
import sqlite3
src = sqlite3.connect("file:data/state.db?mode=ro", uri=True)
dst = sqlite3.connect("$SCRATCH/state-baseline.db")
src.backup(dst)
print(dst.execute("select count(*) from stage_results where stage='extract'").fetchone())
EOF
```

Expected: un número > 700. Si `data/state.db` no se puede leer (propietario root), usar `docker cp japan-reader:/data/state.db "$SCRATCH/state-baseline.db"`, o `tohoku:` si ya se desplegó.

- [ ] **Step 2: Generar las fixtures con el código actual**

```bash
PYTHONPATH=tests uv run python - <<EOF
import json, sqlite3
from pathlib import Path
from builders import make_ctx, make_fetch
from fakes import FakeTrilium
from tohoku.config import Thresholds
from tohoku.models import Extraction, ExtractResult, GeocodeResult, Transcript
from tohoku.notes import name_key
from tohoku.stages.resolve import ResolveStage
from tohoku.trilium_layout import init_layout

db = sqlite3.connect("$SCRATCH/state-baseline.db")
base = Path("tests/fixtures/baseline"); base.mkdir(parents=True, exist_ok=True)
(base / "extract_prompt.md").write_text(Path("src/tohoku/prompts/extract.md").read_text(encoding="utf-8"), encoding="utf-8")
(base / "extraction_schema.json").write_text(json.dumps(Extraction.model_json_schema(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

names = set()
for (data,) in db.execute("SELECT data FROM stage_results WHERE stage='extract' ORDER BY bookmark_id"):
    ex = json.loads(data).get("extraction") or {}
    names.update(x["nombre"] for x in ex.get("lugares", []) + ex.get("cosas", []))
    names.update(x["titulo"] for x in ex.get("otros", []))
ordered = sorted(names)
sample = ordered[:: max(1, len(ordered) // 300)]
(base / "name_keys.json").write_text(json.dumps({n: name_key(n) for n in sample}, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

def pick(sql):
    return db.execute(sql).fetchone()[0]
rich = pick("""SELECT j.bookmark_id FROM jobs j JOIN stage_results s ON s.bookmark_id = j.bookmark_id AND s.stage = 'extract'
  WHERE j.outcome = 'procesado' AND json_array_length(json_extract(s.data, '$.extraction.lugares')) >= 2
  AND json_array_length(json_extract(s.data, '$.extraction.cosas')) >= 1 ORDER BY j.bookmark_id LIMIT 1""")
nojp = pick("SELECT bookmark_id FROM jobs WHERE outcome = 'no-japon' ORDER BY bookmark_id LIMIT 1")
out = Path("tests/fixtures/state_results"); out.mkdir(parents=True, exist_ok=True)
for label, bid in (("rich", rich), ("no_japon", nojp)):
    for stage, data in db.execute("SELECT stage, data FROM stage_results WHERE bookmark_id = ? AND stage IN ('extract', 'geocode', 'resolve')", (bid,)):
        (out / f"{label}_{stage}.json").write_text(json.dumps(json.loads(data), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

# Plan que produce HOY resolve sobre la extracción real, con un Trilium vacío (no el guardado, que depende de su Trilium).
import tempfile
trilium = FakeTrilium(); trilium.add_note("root", "Ideas de Japón", labels={"jrRoot": ""}); layout = init_layout(trilium)
ctx = make_ctx(Path(tempfile.mkdtemp()), fetch=make_fetch(), transcribe=Transcript(text="x", origin="whisper"),
               extract=ExtractResult.model_validate_json((out / "rich_extract.json").read_text(encoding="utf-8")),
               geocode=GeocodeResult.model_validate_json((out / "rich_geocode.json").read_text(encoding="utf-8")))
plan = ResolveStage(trilium, lambda: layout, Thresholds()).run(ctx)
(base / "rich_plan.json").write_text(json.dumps([[i.key, i.kind.value, i.action, i.alias_of] for i in plan.items], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(rich, nojp, len(sample), len(plan.items))
EOF
ls tests/fixtures/state_results | wc -l
```

Expected: imprime los dos `bookmark_id`, unos 300 nombres y el número de elementos del plan. `ls` da `6`. Si `no_japon` no tiene `geocode`/`resolve` guardados, son menos de 6: se anota como *ruling* y se ajusta la aserción del Step 3 al número real.

Revisar a mano `rich_extract.json`: es contenido público de redes (nombres de sitios, resúmenes) y no contiene secretos. Si contuviera algo personal, elegir otro `bookmark_id` con `LIMIT 1 OFFSET 1`.

- [ ] **Step 3: Tests de caracterización**

`tests/unit/test_baseline.py`:

```python
"""Líneas base del comportamiento de Japón antes del multidestino (fase 2).

Las fixtures se generaron con el código anterior al refactor: estos tests no se regeneran, se cumplen.
"""
import json
from pathlib import Path

from tohoku.models import Extraction, ExtractResult, GeocodeResult, ResolveResult
from tohoku.notes import name_key

FIXTURES = Path(__file__).parents[1] / "fixtures"
BASELINE = FIXTURES / "baseline"
STATE = FIXTURES / "state_results"
REPO = Path(__file__).parents[2]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_extract_prompt_matches_baseline():
    assert _read(REPO / "src/tohoku/prompts/extract.md") == _read(BASELINE / "extract_prompt.md")


def test_extraction_schema_matches_baseline():
    assert Extraction.model_json_schema() == json.loads(_read(BASELINE / "extraction_schema.json"))


def test_name_keys_match_baseline():
    expected = json.loads(_read(BASELINE / "name_keys.json"))
    assert len(expected) > 100
    assert {name: name_key(name) for name in expected} == expected


def test_real_stage_results_load():
    assert len(list(STATE.glob("*.json"))) == 6
    for path in STATE.glob("*_extract.json"):
        ExtractResult.model_validate_json(_read(path))
    for path in STATE.glob("*_geocode.json"):
        GeocodeResult.model_validate_json(_read(path))
    for path in STATE.glob("*_resolve.json"):
        ResolveResult.model_validate_json(_read(path))
```

Run: `uv run pytest tests/unit/test_baseline.py -q`
Expected: `4 passed`.

- [ ] **Step 4: Suite y commit**

Run: `uv run pytest -q` → Expected: `296 passed` (292 + 4).

```bash
git add tests/fixtures tests/unit/test_baseline.py
git commit -m "test: baseline fixtures for Japan behaviour before multi-destination refactor

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Configuración de destinos, interfaz `Flow` y `ViajeParams`

**Files:**
- Create: `src/tohoku/destinations.py`, `src/tohoku/flows/__init__.py` (vacío, con docstring), `src/tohoku/flows/base.py`, `src/tohoku/flows/viaje/__init__.py` (vacío, con docstring), `src/tohoku/flows/viaje/params.py`
- Test: `tests/unit/test_destinations.py`

**Interfaces:**
- Produces:
  - `tohoku.destinations.Destination`: dataclass congelado con `nombre: str`, `flujo: str`, `raiz: str`, `descripcion: str`, `prompt: str` (el texto ya leído) y `params: BaseModel`.
  - `tohoku.destinations.DestinationsConfig`: dataclass congelado con `listas: dict[str, list[str]]`, `destinos: dict[str, Destination]`, `candidates_for(list_id) -> list[str]` y `single_destination() -> Destination`.
  - `tohoku.destinations.load_destinations(path: Path, flows: Mapping[str, HasParams]) -> DestinationsConfig`.
  - `tohoku.flows.base.FlowDeps`, `FlowRuntime` y `Flow` (ver código).
  - `tohoku.flows.viaje.params.ViajeParams`.

- [ ] **Step 1: Tests (RED)**

`tests/unit/test_destinations.py`:

```python
from types import SimpleNamespace

import pytest

from tohoku.destinations import load_destinations
from tohoku.errors import ConfigError
from tohoku.flows.viaje.params import ViajeParams
from tohoku.geo import CITY_ALIASES
from tohoku.models import LUGAR_CATEGORIAS
from tohoku.trilium_layout import CATEGORIES

FLOWS = {"viaje": SimpleNamespace(params_model=ViajeParams)}

JAPON = """
listas:
  L1: [japon]
destinos:
  japon:
    flujo: viaje
    raiz: jrRoot
    descripcion: "Viaje a Japón"
    prompt: prompts/japon.md
"""


def _write(tmp_path, text=JAPON, prompt="PROMPT DE JAPÓN"):
    (tmp_path / "prompts").mkdir(exist_ok=True)
    (tmp_path / "prompts" / "japon.md").write_text(prompt, encoding="utf-8")
    path = tmp_path / "destinos.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_minimal_japan_config(tmp_path):
    config = load_destinations(_write(tmp_path), FLOWS)

    dest = config.single_destination()
    assert (dest.nombre, dest.flujo, dest.raiz, dest.descripcion) == ("japon", "viaje", "jrRoot", "Viaje a Japón")
    assert dest.prompt == "PROMPT DE JAPÓN"
    assert dest.params == ViajeParams()
    assert config.candidates_for("L1") == ["japon"]
    assert config.candidates_for("otra") == []


def test_viaje_defaults_are_the_japan_constants():
    p = ViajeParams()
    assert p.pais == "JP"
    assert p.nombres_pais == ["japon", "japan", "日本"]
    assert (p.latitud, p.longitud) == ((20.0, 46.0), (122.0, 154.0))
    assert p.categorias_lugar == list(LUGAR_CATEGORIAS)
    assert p.categorias_cosa == CATEGORIES
    assert p.alias_ciudad == CITY_ALIASES


def test_new_zealand_params(tmp_path):
    text = JAPON + """
  nz:
    flujo: viaje
    raiz: jrRootNZ
    descripcion: "Viaje a Nueva Zelanda"
    prompt: prompts/japon.md
    pais: NZ
    nombres_pais: [new zealand, nueva zelanda]
    latitud: [-48.0, -34.0]
    longitud: [166.0, 179.0]
    categorias_lugar: [naturaleza, pueblo, otro]
"""
    config = load_destinations(_write(tmp_path, text), FLOWS)

    nz = config.destinos["nz"].params
    assert (nz.pais, nz.latitud, nz.categorias_lugar) == ("NZ", (-48.0, -34.0), ["naturaleza", "pueblo", "otro"])
    assert nz.categorias_cosa == CATEGORIES  # lo no indicado toma el valor por defecto


def test_single_list_value_can_be_a_string(tmp_path):
    config = load_destinations(_write(tmp_path, JAPON.replace("[japon]", "japon")), FLOWS)
    assert config.candidates_for("L1") == ["japon"]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (JAPON + "otra: 1\n", "claves desconocidas: otra"),
        (JAPON.replace("flujo: viaje", "flujo: receta"), "flujo desconocido 'receta'"),
        (JAPON.replace("[japon]", "[japon, nz]"), "no existen: nz"),
        (JAPON.replace("prompts/japon.md", "prompts/nz.md"), "no existe el prompt"),
        (JAPON.replace("raiz: jrRoot", "raiz: '#jrRoot'"), "'raiz'"),
        (JAPON.replace("    prompt:", "    paiss: NZ\n    prompt:"), "paiss"),
        (JAPON.replace("    raiz: jrRoot\n", ""), "faltan claves: raiz"),
        ("listas:\n  L1: [japon]\ndestinos: {}\n", "ningún destino"),
        (JAPON.replace("  L1: [japon]\n", ""), "ninguna lista"),
        ("listas: [\n", "YAML inválido"),
    ],
)
def test_config_errors_name_the_culprit(tmp_path, text, message):
    with pytest.raises(ConfigError, match=message):
        load_destinations(_write(tmp_path, text), FLOWS)


def test_missing_file_mentions_the_setting(tmp_path):
    with pytest.raises(ConfigError, match="DESTINOS_FILE"):
        load_destinations(tmp_path / "no.yaml", FLOWS)


def test_more_than_one_destination_is_not_supported_yet(tmp_path):
    text = JAPON + "  nz:\n    flujo: viaje\n    raiz: jrRootNZ\n    descripcion: NZ\n    prompt: prompts/japon.md\n    pais: NZ\n"
    config = load_destinations(_write(tmp_path, text), FLOWS)
    with pytest.raises(ConfigError, match="fase 3"):
        config.single_destination()
```

(`FLOWS` es un objeto mínimo con `params_model`: `load_destinations` no necesita nada más del flujo.)

Run: `uv run pytest tests/unit/test_destinations.py -q`
Expected: FAIL en la recolección con `ModuleNotFoundError: No module named 'tohoku.destinations'` (y `tohoku.flows`).

- [ ] **Step 2: Implementación**

`src/tohoku/flows/__init__.py`:

```python
"""Flujos de procesamiento (viaje, receta…). El registro está en `tohoku.flows.registry`."""
```

`src/tohoku/flows/viaje/__init__.py`:

```python
"""Flujo `viaje`: lugares (Geo Map), cosas y otros. Japón y Nueva Zelanda son destinos de este flujo."""
```

`src/tohoku/flows/viaje/params.py`:

```python
from pydantic import BaseModel, ConfigDict, Field

from tohoku.geo import CITY_ALIASES
from tohoku.models import LUGAR_CATEGORIAS
from tohoku.trilium_layout import CATEGORIES


class ViajeParams(BaseModel):
    """Parámetros de un destino del flujo `viaje`. Por defecto, los de Japón (antes eran constantes)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    pais: str = Field("JP", pattern=r"^[A-Z]{2}$")  # ISO 3166-1: regionCode de Places y país esperado
    # Para reconocer el país en una dirección sin postalAddress (en minúsculas y sin acentos).
    nombres_pais: list[str] = Field(default_factory=lambda: ["japon", "japan", "日本"])
    latitud: tuple[float, float] = (20.0, 46.0)
    longitud: tuple[float, float] = (122.0, 154.0)
    categorias_lugar: list[str] = Field(default_factory=lambda: list(LUGAR_CATEGORIAS), min_length=1)
    categorias_cosa: dict[str, str] = Field(default_factory=lambda: dict(CATEGORIES), min_length=1)
    alias_ciudad: dict[str, list[str]] = Field(default_factory=lambda: {k: list(v) for k, v in CITY_ALIASES.items()})
```

`src/tohoku/destinations.py`:

```python
"""Destinos configurables (`config/destinos.yaml`): qué listas de Karakeep van a qué destino y con qué flujo."""
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import yaml
from pydantic import BaseModel, ValidationError

from tohoku.errors import ConfigError

_BASE_KEYS = ("flujo", "raiz", "descripcion", "prompt")
_TOP_KEYS = {"listas", "destinos"}
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


@dataclass(frozen=True)
class DestinationsConfig:
    listas: dict[str, list[str]]
    destinos: dict[str, Destination]

    def candidates_for(self, list_id: str) -> list[str]:
        return list(self.listas.get(list_id, []))

    def single_destination(self) -> Destination:
        """Fase 2: un único destino. Varios destinos (clasificador) llegan en la fase 3."""
        if len(self.destinos) != 1:
            raise ConfigError(
                f"Hay {len(self.destinos)} destinos configurados; de momento solo se admite uno (varios destinos: fase 3)"
            )
        return next(iter(self.destinos.values()))


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
    if not destinos_raw:
        raise ConfigError(f"{path}: no hay ningún destino en 'destinos'")
    destinos = {str(name): _destination(path, str(name), spec, flows) for name, spec in destinos_raw.items()}
    listas_raw = raw.get("listas") or {}
    if not listas_raw:
        raise ConfigError(f"{path}: no hay ninguna lista de Karakeep en 'listas'")
    listas: dict[str, list[str]] = {}
    for list_id, names in listas_raw.items():
        names = [names] if isinstance(names, str) else [str(n) for n in names or []]
        if not names:
            raise ConfigError(f"{path}: la lista '{list_id}' no apunta a ningún destino")
        missing = [n for n in names if n not in destinos]
        if missing:
            raise ConfigError(f"{path}: la lista '{list_id}' apunta a destinos que no existen: {', '.join(missing)}")
        listas[str(list_id)] = names
    return DestinationsConfig(listas=listas, destinos=destinos)


def _destination(path: Path, name: str, spec: Any, flows: Mapping[str, HasParams]) -> Destination:
    where = f"{path}: destino '{name}'"
    if not isinstance(spec, dict):
        raise ConfigError(f"{where}: se esperaba un mapa")
    missing = [key for key in _BASE_KEYS if key not in spec]
    if missing:
        raise ConfigError(f"{where}: faltan claves: {', '.join(missing)}")
    flujo = str(spec["flujo"])
    if flujo not in flows:
        raise ConfigError(f"{where}: flujo desconocido '{flujo}' (disponibles: {', '.join(sorted(flows))})")
    raiz = str(spec["raiz"])
    if not _LABEL.match(raiz):
        raise ConfigError(f"{where}: 'raiz' debe ser el nombre de una etiqueta de Trilium, sin '#' (p. ej. jrRoot)")
    prompt_path = (path.parent / str(spec["prompt"])).resolve()
    if not prompt_path.is_file():
        raise ConfigError(f"{where}: no existe el prompt {prompt_path}")
    params_raw = {key: value for key, value in spec.items() if key not in _BASE_KEYS}
    try:
        params = flows[flujo].params_model.model_validate(params_raw)
    except ValidationError as exc:
        raise ConfigError(f"{where}: parámetros inválidos para el flujo '{flujo}':\n{exc}") from exc
    return Destination(
        nombre=name, flujo=flujo, raiz=raiz, descripcion=str(spec["descripcion"]),
        prompt=prompt_path.read_text(encoding="utf-8"), params=params,
    )
```

`src/tohoku/flows/base.py`:

```python
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel

from tohoku.clients.openrouter import OpenRouterClient
from tohoku.clients.places import PlacesClient
from tohoku.clients.trilium import TriliumClient
from tohoku.config import Settings
from tohoku.destinations import Destination
from tohoku.pipeline import Stage
from tohoku.quota import DailyQuota
from tohoku.state import StateStore


@dataclass(frozen=True)
class FlowDeps:
    """Clientes y cuotas compartidos que un flujo necesita para montar sus etapas."""

    settings: Settings
    state: StateStore
    trilium: TriliumClient
    llm: OpenRouterClient
    places: PlacesClient
    llm_budget: DailyQuota
    places_quota: DailyQuota


class FlowRuntime(Protocol):
    """Un flujo montado para un destino."""

    stages: list[Stage]  # etapas propias del flujo (después de fetch y transcribe)

    def refresh(self) -> object:
        """Vuelve a resolver la estructura del destino en Trilium. ConfigError si está incompleta."""
        ...


class Flow(Protocol):
    name: str
    params_model: type[BaseModel]

    def build(self, dest: Destination, deps: FlowDeps) -> FlowRuntime: ...

    def init_trilium(self, trilium: TriliumClient, dest: Destination) -> str:
        """Crea lo que falte bajo la raíz del destino (idempotente) y devuelve un resumen para la CLI."""
        ...
```

- [ ] **Step 3: GREEN**

Run: `uv run pytest tests/unit/test_destinations.py -q` → Expected: todos pasan.
Run: `uv run pytest -q` → Expected: verde (296 + los nuevos).

- [ ] **Step 4: Commit**

```bash
git add src/tohoku/destinations.py src/tohoku/flows tests/unit/test_destinations.py
git commit -m "feat(config): destinations file loader, Flow protocol and ViajeParams (Japan defaults)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: País, límites, alias de ciudad y región de Places por destino

**Files:**
- Modify: `src/tohoku/geo.py`, `src/tohoku/clients/places.py:25-26`, `src/tohoku/stages/geocode.py`
- Test: `tests/unit/test_geocode.py` (tests nuevos + firma de `FakePlaces`), `tests/unit/test_places_client.py` (test nuevo)

**Interfaces:**
- Consumes: `ViajeParams` (Task 2).
- Produces:
  - `geo.in_country(match, code: str, names: Sequence[str], lat: tuple[float, float], lng: tuple[float, float]) -> bool`;
  - `geo.city_matches(match, ciudad, aliases: Mapping[str, Sequence[str]] = CITY_ALIASES)`;
  - `geo.name_score(match, lugar, aliases=CITY_ALIASES)`;
  - `geo.name_matches(match, lugar, aliases=CITY_ALIASES)`;
  - `PlacesClient.search(query, region: str = "JP")`;
  - `GeocodeStage(places, quota, thresholds, cache=None, params: ViajeParams | None = None)`.
  - `geo.in_japan` desaparece.

- [ ] **Step 1: Tests (RED)**

En `tests/unit/test_geocode.py`, cambiar `FakePlaces`. Es un cambio de fake, no de aserción:

```python
class FakePlaces:
    def __init__(self, answers: dict[str, list]):
        self.answers = answers
        self.queries: list[str] = []
        self.regions: list[str] = []

    def search(self, query, region="JP"):
        self.queries.append(query)
        self.regions.append(region)
        return self.answers.get(query, [])
```

Añadir al final:

```python
from tohoku.flows.viaje.params import ViajeParams
from tohoku.geo import city_matches, in_country

NZ = ViajeParams(
    pais="NZ", nombres_pais=["new zealand", "nueva zelanda"], latitud=(-48.0, -34.0), longitud=(166.0, 179.0),
    categorias_lugar=["naturaleza", "otro"], alias_ciudad={"auckland": ["tamaki makaurau"]},
)
# La dirección usa el nombre maorí de la ciudad: solo casa con "Auckland" gracias a los alias del destino.
SKY_TOWER = make_geo("NZ1", "Sky Tower", "Victoria St W, Tāmaki Makaurau 1010, Nueva Zelanda", lat=-36.85, lng=174.76,
                     country_code="NZ", area="")


def _run_nz(tmp_path, state, places, lugar):
    ctx = make_ctx(tmp_path, extract=ExtractResult(extraction=make_extraction(0.95, lugares=[lugar])))
    return GeocodeStage(places, DailyQuota(state, "places_calls", 150), Thresholds(), cache=state, params=NZ).run(ctx)


def test_destination_country_and_region(tmp_path, state):
    places = FakePlaces({"Sky Tower Auckland": [SKY_TOWER]})
    lugar = make_lugar("Sky Tower", consulta_busqueda="Sky Tower Auckland", ciudad="Auckland", categoria="otro")

    outcome = _run_nz(tmp_path, state, places, lugar).outcomes[0]

    assert outcome.match.place_id == "NZ1" and outcome.review_reason is None
    assert places.regions == ["NZ"]


def test_result_in_japan_is_rejected_for_a_new_zealand_destination(tmp_path, state):
    places = FakePlaces({"Ichiran Shibuya Tokyo": [SHIBUYA]})
    outcome = _run_nz(tmp_path, state, places, make_lugar()).outcomes[0]
    assert outcome.match is None and outcome.review_reason == "geocodificacion-fallida"


def test_places_cache_is_per_country_and_japan_keeps_its_entries(tmp_path, state):
    state.put_places_cache("Ichiran Shibuya Tokyo", [SHIBUYA.model_dump()])  # entrada anterior al multidestino
    jp, nz = FakePlaces({"Ichiran Shibuya Tokyo": [SHIBUYA]}), FakePlaces({})

    _run(tmp_path, state, jp, [make_lugar()])
    _run_nz(tmp_path, state, nz, make_lugar())

    assert jp.queries == []  # Japón reutiliza su caché de siempre
    assert nz.queries == ["Ichiran Shibuya Tokyo"]  # Nueva Zelanda no la comparte


def test_in_country_uses_code_bounds_and_names():
    assert in_country(SKY_TOWER, "NZ", NZ.nombres_pais, NZ.latitud, NZ.longitud)
    assert not in_country(SKY_TOWER, "JP", ["japon"], (20.0, 46.0), (122.0, 154.0))
    no_code = make_geo("X", "Hobbiton", "Matamata 3472, Nueva Zelanda", lat=-37.87, lng=175.68)
    assert in_country(no_code, "NZ", NZ.nombres_pais, NZ.latitud, NZ.longitud)


def test_city_aliases_come_from_the_destination():
    assert city_matches(SKY_TOWER, "Auckland", NZ.alias_ciudad)
    assert not city_matches(SKY_TOWER, "Auckland")  # con los alias de Japón (por defecto) no casa
```

En `tests/unit/test_places_client.py`:

```python
@respx.mock
def test_search_region_can_be_changed():
    route = respx.post(host=HOST, path="/v1/places:searchText").mock(return_value=httpx.Response(200, json={}))
    PlacesClient("gkey").search("Sky Tower Auckland", region="NZ")
    assert json.loads(route.calls[0].request.content)["regionCode"] == "NZ"
```

(Si `make_lugar` no acepta `consulta_busqueda`, `ciudad` o `categoria` como `overrides`, sí los acepta: usa `base | overrides`.)

Run: `uv run pytest tests/unit/test_geocode.py tests/unit/test_places_client.py -q`
Expected: FAIL. Errores esperados: `ImportError: cannot import name 'in_country'` en la recolección de `test_geocode.py` y `TypeError: ... unexpected keyword argument 'region'` en `test_places_client.py`.

- [ ] **Step 2: Implementación**

`src/tohoku/geo.py`: sustituir `_LAT_RANGE`, `_LNG_RANGE`, `_JAPAN_WORDS`, `in_japan`, `city_matches`, `_canonical_words`, `_CANONICAL`, `_name_words`, `name_score` y `name_matches` por:

```python
from collections.abc import Mapping, Sequence
...

def in_country(match: GeoMatch, code: str, names: Sequence[str], lat: tuple[float, float], lng: tuple[float, float]) -> bool:
    """El resultado está en el país del destino: dentro de sus límites y con su código (o su nombre en la dirección)."""
    inside = lat[0] <= match.lat <= lat[1] and lng[0] <= match.lng <= lng[1]
    if not inside:
        return False
    if match.country_code:
        return match.country_code.upper() == code.upper()
    # Sin postalAddress: el país tiene que aparecer en la dirección.
    # fold y no normalize_name: normalize_name elimina "japon"/"japan" por ser palabras genéricas.
    address = fold(match.address)
    return any(fold(word) in address for word in names)


def city_matches(match: GeoMatch, ciudad: str | None, aliases: Mapping[str, Sequence[str]] = CITY_ALIASES) -> bool:
    if not ciudad:
        return True
    city = fold(ciudad).strip()
    address = fold(f"{match.address} {match.area}")
    return any(fold(name) in address for name in [city, *aliases.get(city, [])])


def _canonical_words(aliases: Mapping[str, Sequence[str]]) -> dict[str, str]:
    words = {alias: canon for canon, alias_list in _NAME_EQUIVALENTS.items() for alias in alias_list}
    words |= {fold(alias): city for city, alias_list in aliases.items() for alias in alias_list}
    return words


def _name_words(text: str, canonical: Mapping[str, str]) -> list[str]:
    return [canonical.get(w, w) for w in normalize_name(text).split() if w not in _NAME_STOPWORDS]


def name_score(match: GeoMatch, lugar: Lugar, aliases: Mapping[str, Sequence[str]] = CITY_ALIASES) -> float:
    """Parecido entre el nombre de Google y el extraído: 2 = igual, 1 = uno contiene al otro, si no la similitud.

    "Igual" admite otro orden y palabras traducidas o alias de ciudad ("Torre de Kioto" = "Kyoto Tower").
    """
    canonical = _canonical_words(aliases)
    found_words = _name_words(match.name, canonical)
    found = " ".join(found_words)
    names = [lugar.nombre] + ([lugar.nombre_local] if lugar.nombre_local else [])
    best = 0.0
    for name in names:
        words = _name_words(name, canonical)
        w = " ".join(words)
        if not w or not found:
            continue
        if w == found or sorted(words) == sorted(found_words):
            return 2.0
        best = max(best, 1.0 if (w in found or found in w) else similarity(w, found))
    return best
...
def name_matches(match: GeoMatch, lugar: Lugar, aliases: Mapping[str, Sequence[str]] = CITY_ALIASES) -> bool:
    return name_score(match, lugar, aliases) >= NAME_SIMILARITY
```

(`CITY_ALIASES`, `_NAME_EQUIVALENTS`, `_NAME_STOPWORDS`, `NAME_SIMILARITY`, `SAME_PLACE_RADIUS_M`, `distance_m`, `near_notes` y `_haversine_m` no cambian.)

`src/tohoku/clients/places.py`:

```python
    def search(self, query: str, region: str = "JP") -> list[GeoMatch]:
        body = {"textQuery": query, "regionCode": region, "languageCode": "es", "pageSize": 5}
```

`src/tohoku/stages/geocode.py`:

```python
from tohoku.flows.viaje.params import ViajeParams
from tohoku.geo import NAME_SIMILARITY, SAME_PLACE_RADIUS_M, city_matches, distance_m, in_country, name_score
...
    def __init__(self, places, quota, thresholds, cache=None, params: ViajeParams | None = None) -> None:
        self._places = places
        self._quota = quota
        self._th = thresholds
        self._cache = cache
        self._params = params or ViajeParams()
        # Las búsquedas guardadas antes del multidestino son de Japón y no llevan prefijo.
        self._cache_prefix = "" if self._params.pais == "JP" else f"{self._params.pais}|"

    def _in_country(self, match: GeoMatch) -> bool:
        p = self._params
        return in_country(match, p.pais, p.nombres_pais, p.latitud, p.longitud)
```

En `_geocode`:
- `in_jp = [r for r in results if in_japan(r)]` pasa a `in_dest = [r for r in results if self._in_country(r)]`, y las demás referencias a `in_jp` pasan a `in_dest`;
- `city_matches(r, lugar.ciudad)` pasa a `city_matches(r, lugar.ciudad, self._params.alias_ciudad)`;
- `_choose(valid, lugar)` pasa a `_choose(valid, lugar, self._params.alias_ciudad)`.

Donde el código use `name_score(r, lugar)` o `name_matches(r, lugar)` (incluido `_choose`), pasar los alias. `_choose` gana el parámetro `aliases: Mapping[str, Sequence[str]]`.

En `_search`:

```python
    def _search(self, query: str) -> list[GeoMatch]:
        key = self._cache_prefix + query
        if self._cache is not None:
            cached = self._cache.get_places_cache(key, CACHE_MAX_AGE)
            if cached is not None:
                return [GeoMatch.model_validate(r) for r in cached]
        self._quota.check()
        results = self._places.search(query, region=self._params.pais)
        self._quota.add(1)
        if self._cache is not None:
            self._cache.put_places_cache(key, [r.model_dump() for r in results])
        return results
```

Comprobar: `git grep -n "in_japan" -- src tests` → sin resultados.

- [ ] **Step 3: GREEN y suite**

Run: `uv run pytest tests/unit/test_geocode.py tests/unit/test_places_client.py -q` → todos pasan.
Run: `uv run pytest -q` → verde. Ninguna aserción existente modificada: comprobarlo con `git diff -U0 tests | grep '^-.*assert'`, que debe salir vacío.

- [ ] **Step 4: Commit**

```bash
git add src/tohoku/geo.py src/tohoku/clients/places.py src/tohoku/stages/geocode.py tests/unit/test_geocode.py tests/unit/test_places_client.py
git commit -m "feat(geocode): country, bounds, city aliases and Places region per destination

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: `relacionado_destino` / `confianza_destino` con compatibilidad hacia atrás

**Files:**
- Modify: `src/tohoku/models.py:83-86`, `src/tohoku/rules.py`, `src/tohoku/stages/{extract,geocode,resolve,publish}.py`, `src/tohoku/evaluation.py`, `src/tohoku/prompts/extract.md` (solo los dos nombres de campo)
- Modify (construcción): `tests/builders.py:54-58`, `tests/unit/test_text_rules.py` (import)
- Test: `tests/unit/test_baseline.py`

**Interfaces:**
- Produces:
  - `Extraction.relacionado_destino: bool` y `Extraction.confianza_destino: float`. Al validar se aceptan también los nombres antiguos; al serializar se escriben los nuevos.
  - `tohoku.rules.destination_decision(extraction, th) -> Literal["no", "uncertain", "yes"]`. `japan_decision` desaparece.

- [ ] **Step 1: Tests (RED)**

En `tests/unit/test_baseline.py`, añadir los renombrados y sustituir los dos primeros tests:

```python
from tohoku.config import Thresholds
from tohoku.models import Outcome, Transcript
from tohoku.quota import DailyQuota
from tohoku.state import StateStore
from tohoku.stages.publish import PublishStage
from tohoku.stages.resolve import ResolveStage
from tohoku.trilium_layout import init_layout
from builders import make_ctx, make_fetch
from fakes import FakeLLM, FakeTrilium

# Único cambio intencionado respecto a la línea base: los campos de relevancia ya no se llaman "japon".
RENAMES = {
    "relacionado_japon": "relacionado_destino",
    "confianza_japon": "confianza_destino",
    "Relacionado Japon": "Relacionado Destino",
    "Confianza Japon": "Confianza Destino",
}


def _renamed(text: str) -> str:
    for old, new in RENAMES.items():
        text = text.replace(old, new)
    return text


def test_extract_prompt_matches_baseline():
    assert _read(REPO / "src/tohoku/prompts/extract.md") == _renamed(_read(BASELINE / "extract_prompt.md"))


def test_extraction_schema_matches_baseline():
    assert Extraction.model_json_schema() == json.loads(_renamed(_read(BASELINE / "extraction_schema.json")))


def test_real_extract_keeps_its_values_and_is_saved_with_new_names():
    raw = json.loads(_read(STATE / "rich_extract.json"))
    result = ExtractResult.model_validate(raw)

    assert result.extraction.confianza_destino == raw["extraction"]["confianza_japon"]
    assert result.extraction.relacionado_destino == raw["extraction"]["relacionado_japon"]
    dumped = json.loads(result.model_dump_json())["extraction"]
    assert "confianza_destino" in dumped and "confianza_japon" not in dumped
    assert ExtractResult.model_validate_json(result.model_dump_json()) == result


def _real_ctx(tmp_path, label):
    return make_ctx(
        tmp_path, fetch=make_fetch(), transcribe=Transcript(text="x", origin="whisper"),
        extract=ExtractResult.model_validate_json(_read(STATE / f"{label}_extract.json")),
        geocode=GeocodeResult.model_validate_json(_read(STATE / f"{label}_geocode.json")),
    )


def _japan_trilium():
    trilium = FakeTrilium()
    trilium.add_note("root", "Ideas de Japón", labels={"jrRoot": ""})
    return trilium, init_layout(trilium)


def test_real_results_resolve_like_baseline_and_publish(tmp_path, settings):
    trilium, layout = _japan_trilium()
    ctx = _real_ctx(tmp_path, "rich")

    plan = ResolveStage(trilium, lambda: layout, Thresholds()).run(ctx)

    assert [[i.key, i.kind.value, i.action, i.alias_of] for i in plan.items] == json.loads(_read(BASELINE / "rich_plan.json"))
    ctx.results["resolve"] = plan
    state = StateStore(tmp_path / "state.db")
    merged = json.dumps({"resumen": "r", "que_hacer": "", "consejos": []})
    result = PublishStage(trilium, lambda: layout, FakeLLM([merged] * 10), settings, DailyQuota(state, "openrouter_usd", 10), state).run(ctx)
    assert len(result.notes) == sum(i.action != "alias" for i in plan.items)


def test_real_not_japan_result_publishes_nothing(tmp_path, settings):
    trilium, layout = _japan_trilium()
    ctx = _real_ctx(tmp_path, "no_japon")
    ctx.results["resolve"] = ResolveStage(trilium, lambda: layout, Thresholds()).run(ctx)
    state = StateStore(tmp_path / "state.db")
    result = PublishStage(trilium, lambda: layout, FakeLLM([]), settings, DailyQuota(state, "openrouter_usd", 10), state).run(ctx)
    assert result.notes == [] and result.outcome == Outcome.NO_JAPON
```

(`settings` es la fixture de `tests/conftest.py`.)

Run: `uv run pytest tests/unit/test_baseline.py -q`
Expected: FAIL en `test_extract_prompt_matches_baseline` y `test_extraction_schema_matches_baseline` (siguen con los nombres viejos) y en `test_real_extract_keeps…` con `AttributeError: 'Extraction' object has no attribute 'confianza_destino'`. Los dos tests de resolve y publish **pasan** ya: caracterizan la línea base, y el revisor debe saberlo.

- [ ] **Step 2: Implementación**

`src/tohoku/models.py`:

```python
from pydantic import AliasChoices, BaseModel, Field
...
class Extraction(BaseModel):
    # Antes relacionado_japon / confianza_japon: se aceptan al leer resultados ya guardados en state.db.
    relacionado_destino: bool = Field(validation_alias=AliasChoices("relacionado_destino", "relacionado_japon"))
    confianza_destino: float = Field(ge=0, le=1, validation_alias=AliasChoices("confianza_destino", "confianza_japon"))
    idioma: str
    ...
```

`src/tohoku/rules.py`:

```python
DestinationDecision = Literal["no", "uncertain", "yes"]


def destination_decision(extraction: Extraction, th: Thresholds) -> DestinationDecision:
    """Clasifica con `confianza_destino` (spec §7): ¿trata el contenido sobre el destino?"""
    if extraction.confianza_destino < th.japan_min:
        return "no"
    if extraction.confianza_destino < th.japan_review:
        return "uncertain"
    return "yes"


def decide_outcome(decision: DestinationDecision, notes: list[PublishedNote]) -> Outcome:
```

(El cuerpo de `decide_outcome` no cambia.)

Sustituir `japan_decision` por `destination_decision` (import y llamadas) en `stages/geocode.py`, `stages/resolve.py`, `stages/publish.py`, `evaluation.py` y `tests/unit/test_text_rules.py`. En este último solo cambian el import y el nombre de la función llamada; las aserciones quedan igual.

`src/tohoku/stages/extract.py`, en el `log.info` de éxito: `"bookmark=%s extraccion relevancia=%.2f lugares=%d cosas=%d otros=%d coste=%.4f"` con `extraction.confianza_destino`.

`src/tohoku/prompts/extract.md`: en el punto 1, `confianza_japon` pasa a `confianza_destino` (las dos veces) y `relacionado_japon` a `relacionado_destino`. No se cambia ninguna otra palabra.

`tests/builders.py`:

```python
def make_extraction(confianza_destino=0.95, lugares=(), cosas=(), otros=()) -> Extraction:
    return Extraction(
        relacionado_destino=confianza_destino >= 0.5, confianza_destino=confianza_destino, idioma="es",
        ...
```

Comprobar: `git grep -n "confianza_japon\|relacionado_japon\|japan_decision" -- src tests ':!tests/fixtures'`. Solo pueden quedar los alias de `models.py`, el `VALID` de `tests/unit/test_extract.py` (JSON con nombres antiguos, que sigue siendo válido: así se prueba la compatibilidad) y `_extraction` de `test_text_rules.py` (construcción por alias).

- [ ] **Step 3: GREEN y suite**

Run: `uv run pytest tests/unit/test_baseline.py -q` → todos pasan.
Run: `uv run pytest -q` → verde. `git diff -U0 tests/unit | grep '^-.*assert'` sale vacío (salvo las dos funciones de línea base sustituidas en `test_baseline.py`, que son de esta fase).

- [ ] **Step 4: Commit**

```bash
git add src tests
git commit -m "refactor: relevance fields are per destination (legacy *_japon still accepted)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Flujo `viaje`, `config/destinos.yaml` y cableado con un único destino

**Files:**
- Move: `src/tohoku/prompts/extract.md` → `config/prompts/japon.md` (`git mv`)
- Create: `config/destinos.yaml`, `tests/fixtures/destinos.yaml`, `src/tohoku/flows/registry.py`, `src/tohoku/flows/viaje/flow.py`
- Modify: `src/tohoku/trilium_layout.py`, `src/tohoku/stages/extract.py`, `src/tohoku/config.py`, `src/tohoku/wiring.py`, `src/tohoku/cli.py` (`eval`), `tests/conftest.py`, `tests/unit/test_extract.py` (helper `_stage`), `tests/unit/test_baseline.py`
- Test: `tests/unit/test_flow_viaje.py`, `tests/unit/test_wiring_cli.py` (tests nuevos)

**Interfaces:**
- Consumes: `load_destinations`, `Destination`, `FlowDeps` y `ViajeParams` (Task 2); `GeocodeStage(..., params=)` (Task 3).
- Produces:
  - `resolve_layout(trilium, root_label="jrRoot", categorias: Mapping[str, str] = CATEGORIES)` e `init_layout(trilium, root_label="jrRoot", categorias=CATEGORIES)`;
  - `ExtractStage(settings, llm, budget, system_prompt: str, params: ViajeParams | None = None)`;
  - `tohoku.flows.registry.FLOWS: dict[str, Flow]` con la entrada `"viaje"`;
  - `ViajeFlow.build(dest, deps) -> ViajeRuntime` (`.stages`, `.layout: LayoutCache`, `.refresh()`);
  - `ViajeFlow.init_trilium(trilium, dest) -> str`;
  - `Settings.destinos_file: Path = Path("config/destinos.yaml")`;
  - `App` con `destinations`, `destination` y `runtime`. `App.layout` pasa a ser `runtime.layout`.

- [ ] **Step 1: Tests (RED)**

`tests/fixtures/destinos.yaml`:

```yaml
# Configuración de tests: la lista L1 de la fixture `settings` y el prompt real de Japón.
listas:
  L1: [japon]
destinos:
  japon:
    flujo: viaje
    raiz: jrRoot
    descripcion: "Viaje a Japón: lugares, comida, compras y cultura de Japón"
    prompt: ../../config/prompts/japon.md
```

En `tests/conftest.py`, añadir a `Settings(...)` el argumento `destinos_file=Path(__file__).parent / "fixtures" / "destinos.yaml",` (con `from pathlib import Path`).

`tests/unit/test_flow_viaje.py`:

```python
from pathlib import Path

import pytest

from fakes import FakeLLM, FakeTrilium
from tohoku.clients.places import PlacesClient
from tohoku.destinations import Destination
from tohoku.errors import ConfigError
from tohoku.flows.base import FlowDeps
from tohoku.flows.registry import FLOWS
from tohoku.flows.viaje.params import ViajeParams
from tohoku.pipeline import STAGE_ORDER
from tohoku.quota import DailyQuota
from tohoku.state import StateStore


def _dest(**params):
    return Destination(nombre="nz", flujo="viaje", raiz="jrRootNZ", descripcion="NZ", prompt="PROMPT NZ", params=ViajeParams(**params))


def _deps(settings, tmp_path, trilium):
    state = StateStore(tmp_path / "state.db")
    return FlowDeps(settings=settings, state=state, trilium=trilium, llm=FakeLLM([]), places=PlacesClient("k"),
                    llm_budget=DailyQuota(state, "openrouter_usd", 1), places_quota=DailyQuota(state, "places_calls", 1))


def test_viaje_is_registered():
    assert FLOWS["viaje"].params_model is ViajeParams


def test_build_gives_the_flow_stages_in_order(settings, tmp_path):
    runtime = FLOWS["viaje"].build(_dest(), _deps(settings, tmp_path, FakeTrilium()))
    assert [s.name for s in runtime.stages] == list(STAGE_ORDER[2:])  # extract, geocode, resolve, publish


def test_init_trilium_uses_the_destination_root_and_categories(settings, tmp_path):
    trilium = FakeTrilium()
    trilium.add_note("root", "Viaje a Nueva Zelanda", labels={"jrRootNZ": ""})
    dest = _dest(categorias_cosa={"artesania": "Artesanía", "comida": "Comida"})

    summary = FLOWS["viaje"].init_trilium(trilium, dest)

    runtime = FLOWS["viaje"].build(dest, _deps(settings, tmp_path, trilium))
    layout = runtime.refresh()
    assert set(layout.categorias) == {"artesania", "comida"}
    assert "Mapa=" in summary


def test_refresh_fails_until_init(settings, tmp_path):
    trilium = FakeTrilium()
    trilium.add_note("root", "Viaje a Nueva Zelanda", labels={"jrRootNZ": ""})
    runtime = FLOWS["viaje"].build(_dest(), _deps(settings, tmp_path, trilium))
    with pytest.raises(ConfigError, match="init-trilium"):
        runtime.refresh()


def test_extract_stage_gets_the_destination_prompt(settings, tmp_path):
    runtime = FLOWS["viaje"].build(_dest(), _deps(settings, tmp_path, FakeTrilium()))
    extract = next(s for s in runtime.stages if s.name == "extract")
    assert extract.system_prompt == "PROMPT NZ"
```

En `tests/unit/test_wiring_cli.py`, al final:

```python
def test_build_app_uses_the_destination_from_config(settings):
    app = build_app(settings)
    assert app.destination.nombre == "japon" and app.destination.raiz == "jrRoot"
    assert "Japón" in next(s for s in app.stages if s.name == "extract").system_prompt


def test_build_app_rejects_several_destinations_for_now(settings, tmp_path):
    text = (Path(__file__).parents[1] / "fixtures" / "destinos.yaml").read_text(encoding="utf-8")
    text = text.replace("../../config", str(Path(__file__).parents[2] / "config"))
    text += "  nz:\n    flujo: viaje\n    raiz: jrRootNZ\n    descripcion: NZ\n    prompt: " + str(Path(__file__).parents[2] / "config/prompts/japon.md") + "\n    pais: NZ\n"
    path = tmp_path / "destinos.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match="fase 3"):
        build_app(settings.model_copy(update={"destinos_file": path}))
```

(añadir `from pathlib import Path` si falta).

En `tests/unit/test_baseline.py`, sustituir `test_extract_prompt_matches_baseline`:

```python
def test_japan_prompt_matches_baseline():
    assert _read(REPO / "config/prompts/japon.md") == _renamed(_read(BASELINE / "extract_prompt.md"))
```

En `tests/unit/test_extract.py`, el helper `_stage` (construcción) pasa a ser:

```python
def _stage(settings, llm, state, limit=1.0):
    return ExtractStage(settings, llm, DailyQuota(state, "openrouter_usd", limit), "prompt de prueba")
```

Run: `uv run pytest tests/unit/test_flow_viaje.py tests/unit/test_wiring_cli.py tests/unit/test_baseline.py tests/unit/test_extract.py -q`
Expected: FAIL. Errores esperados:
- `test_flow_viaje.py`: `ModuleNotFoundError: No module named 'tohoku.flows.registry'`;
- `test_japan_prompt_matches_baseline`: `FileNotFoundError` (`config/prompts/japon.md`);
- `test_extract.py`: `TypeError: ExtractStage.__init__() takes 4 positional arguments but 5 were given`;
- los dos tests nuevos de `test_wiring_cli.py`: `AttributeError: 'App' object has no attribute 'destination'` y `DID NOT RAISE`.

(`Settings` ignora el `destinos_file` desconocido gracias a `extra="ignore"`, así que la fixture se sigue creando.)

- [ ] **Step 2: Implementación**

```bash
mkdir -p config/prompts && git mv src/tohoku/prompts/extract.md config/prompts/japon.md
```

`config/destinos.yaml`:

```yaml
# Destinos de Tohoku: qué listas de Karakeep se procesan, con qué flujo y dónde se publican.
# Referencia: docs/superpowers/specs/2026-09-30-multi-destino-design.md §2 y docs/operations.md.
# Fase 2: un único destino. Varios destinos (clasificador) llegan en la fase 3.
listas:
  seo5xdpquppqfy4hmzzeekfh: [japon]   # lista "Japón" de Karakeep
destinos:
  japon:
    flujo: viaje
    raiz: jrRoot                        # etiqueta de "Home › Viajes › Ideas de Japón"
    descripcion: "Viaje a Japón: lugares, comida, compras y cultura de Japón"
    prompt: prompts/japon.md
    pais: JP                            # el resto de parámetros del flujo viaje toman sus valores por defecto (Japón)
```

`src/tohoku/trilium_layout.py`:
- `resolve_layout(trilium, root_label: str = "jrRoot", categorias: Mapping[str, str] = CATEGORIES)`: el bucle de categorías recorre `categorias` en lugar de `CATEGORIES`.
- `init_layout(trilium, root_label="jrRoot", categorias=CATEGORIES)`: igual, y al final `return resolve_layout(trilium, root_label, categorias)`.
- El mensaje de `_root` pasa a ser `f"No se encuentra la nota raíz con #{root_label}. Añade esa etiqueta a la nota raíz del destino en Trilium."`. Sigue conteniendo `#jrRoot`, que es lo que comprueba el test existente.

`src/tohoku/stages/extract.py`:

```python
    def __init__(self, settings: Settings, llm: OpenRouterClient, budget: DailyQuota, system_prompt: str) -> None:
        self._settings = settings
        self._llm = llm
        self._budget = budget
        self.system_prompt = system_prompt
```

En `run`, `{"role": "system", "content": load_prompt("extract")}` pasa a `{"role": "system", "content": self.system_prompt}`. Quitar el import de `load_prompt` si queda sin uso. (`params` llega en la Task 6.)

`src/tohoku/flows/viaje/flow.py`:

```python
from dataclasses import dataclass

from tohoku.clients.trilium import TriliumClient
from tohoku.destinations import Destination
from tohoku.flows.base import FlowDeps
from tohoku.flows.viaje.params import ViajeParams
from tohoku.pipeline import Stage
from tohoku.stages.extract import ExtractStage
from tohoku.stages.geocode import GeocodeStage
from tohoku.stages.publish import PublishStage
from tohoku.stages.resolve import ResolveStage
from tohoku.trilium_layout import Layout, LayoutCache, init_layout, resolve_layout


@dataclass
class ViajeRuntime:
    stages: list[Stage]
    layout: LayoutCache

    def refresh(self) -> Layout:
        return self.layout.refresh()


class ViajeFlow:
    """Lugares al Geo Map, cosas a "Comprar y comer", el resto a "Cultura" (docs/trilium-model.md)."""

    name = "viaje"
    params_model = ViajeParams

    def build(self, dest: Destination, deps: FlowDeps) -> ViajeRuntime:
        params: ViajeParams = dest.params  # type: ignore[assignment]
        layout = LayoutCache(lambda: resolve_layout(deps.trilium, dest.raiz, params.categorias_cosa))
        th = deps.settings.thresholds
        stages: list[Stage] = [
            ExtractStage(deps.settings, deps.llm, deps.llm_budget, dest.prompt),
            GeocodeStage(deps.places, deps.places_quota, th, cache=deps.state, params=params),
            ResolveStage(deps.trilium, layout, th),
            PublishStage(deps.trilium, layout, deps.llm, deps.settings, deps.llm_budget, deps.state),
        ]
        return ViajeRuntime(stages=stages, layout=layout)

    def init_trilium(self, trilium: TriliumClient, dest: Destination) -> str:
        params: ViajeParams = dest.params  # type: ignore[assignment]
        layout = init_layout(trilium, dest.raiz, params.categorias_cosa)
        return f"Estructura lista. Mapa={layout.mapa} Comprar={layout.comprar} Revisión={layout.revision}"
```

`src/tohoku/flows/registry.py`:

```python
from tohoku.flows.base import Flow
from tohoku.flows.viaje.flow import ViajeFlow

FLOWS: dict[str, Flow] = {"viaje": ViajeFlow()}
```

`src/tohoku/config.py`: añadir `destinos_file: Path = Path("config/destinos.yaml")` junto a `data_dir`. (`karakeep_list_id` y `trilium_root_label` se quitan en la Task 7.)

`src/tohoku/wiring.py`:
- `App` gana `destinations: DestinationsConfig`, `destination: Destination` y `runtime: FlowRuntime`.
- `build_app`:

```python
    destinations = load_destinations(settings.destinos_file, FLOWS)
    destination = destinations.single_destination()
    deps = FlowDeps(settings=settings, state=state, trilium=trilium, llm=llm, places=places,
                    llm_budget=llm_budget, places_quota=places_quota)
    runtime = FLOWS[destination.flujo].build(destination, deps)
    stages: list[Stage] = [FetchStage(settings, ytdlp, gallery, karakeep), transcribe, *runtime.stages]
    ...
    service = Service(karakeep, state, pipeline, notifier, settings, lambda: preflight(settings, trilium, llm, runtime))
```

  Se eliminan la `LayoutCache` local, `thresholds` si queda sin uso y las construcciones directas de `ExtractStage`/`GeocodeStage`/`ResolveStage`/`PublishStage`. `App(..., layout=runtime.layout, destinations=destinations, destination=destination, runtime=runtime, ...)`.
- `preflight(settings, trilium, llm, layout)`: el parámetro se queda, anotado `layout: FlowRuntime | LayoutCache` (ambos tienen `.refresh()`). El cuerpo no cambia.

`src/tohoku/cli.py`, comando `eval`:

```python
    extract = ExtractStage(settings, loaded.llm, loaded.llm_budget, loaded.destination.prompt)
    scores = runner.run(load_cases(cases), extract, settings.thresholds, keyframes)
```

`tests/unit/test_baseline.py`: `REPO / "src/tohoku/prompts/extract.md"` ya no existe. Solo lo usaba el test sustituido en el Step 1.

- [ ] **Step 3: GREEN y suite**

Run: `uv run pytest tests/unit/test_flow_viaje.py tests/unit/test_wiring_cli.py tests/unit/test_baseline.py tests/unit/test_extract.py -q` → pasan.
Run: `uv run pytest -q` → verde. `test_build_app_orders_stages` (sin tocar) sigue pasando.

- [ ] **Step 4: Commit**

```bash
git add -A config src tests
git commit -m "feat: viaje flow built from config/destinos.yaml (single destination: Japan)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Categorías del destino en el prompt, el esquema y la validación

**Files:**
- Create: `src/tohoku/flows/viaje/prompt.py`
- Modify: `config/prompts/japon.md` (dos marcadores), `src/tohoku/models.py` (`categoria: str`), `src/tohoku/stages/extract.py`, `src/tohoku/flows/viaje/flow.py`
- Modify (fake): `tests/fakes.py` (`FakeLLM.calls` registra `schema`)
- Test: `tests/unit/test_extract.py`, `tests/unit/test_baseline.py`, `tests/unit/test_flow_viaje.py`

**Interfaces:**
- Consumes: `ViajeParams` y `ViajeFlow.build` (Task 5).
- Produces:
  - `render_extract_prompt(template: str, params: ViajeParams) -> str`;
  - `extraction_schema(params) -> dict`;
  - `invalid_categories(extraction, params) -> list[str]`;
  - `ExtractStage(settings, llm, budget, system_prompt, params: ViajeParams | None = None)`.

- [ ] **Step 1: Tests (RED)**

`tests/fakes.py`, en `FakeLLM.chat_json`: `self.calls.append({"model": model, "messages": messages, "schema": schema, "schema_name": schema_name})`.

En `tests/unit/test_baseline.py`, sustituir los dos tests de prompt y esquema:

```python
from tohoku.flows.viaje.params import ViajeParams
from tohoku.flows.viaje.prompt import extraction_schema, render_extract_prompt


def test_japan_prompt_renders_as_baseline():
    rendered = render_extract_prompt(_read(REPO / "config/prompts/japon.md"), ViajeParams())
    assert rendered == _renamed(_read(BASELINE / "extract_prompt.md"))


def test_japan_extraction_schema_matches_baseline():
    assert extraction_schema(ViajeParams()) == json.loads(_renamed(_read(BASELINE / "extraction_schema.json")))
```

En `tests/unit/test_extract.py`, al final:

```python
from tohoku.flows.viaje.params import ViajeParams
from tohoku.flows.viaje.prompt import extraction_schema

NZ_PARAMS = ViajeParams(pais="NZ", categorias_lugar=["naturaleza", "otro"], categorias_cosa={"artesania": "Artesanía"})


def _nz_payload(categoria):
    return json.dumps({
        "relacionado_destino": True, "confianza_destino": 0.9, "idioma": "es", "resumen_fuente": "Hobbiton",
        "lugares": [make_lugar("Hobbiton", categoria=categoria).model_dump()], "cosas": [], "otros": [],
    })


def test_schema_sent_to_the_llm_uses_destination_categories(tmp_path, settings, state):
    llm = FakeLLM([_nz_payload("naturaleza")])
    ExtractStage(settings, llm, DailyQuota(state, "openrouter_usd", 1.0), "p", NZ_PARAMS).run(_ctx(tmp_path))
    schema = llm.calls[0]["schema"]
    assert schema == extraction_schema(NZ_PARAMS)
    assert schema["$defs"]["Lugar"]["properties"]["categoria"]["enum"] == ["naturaleza", "otro"]
    assert schema["$defs"]["Cosa"]["properties"]["categoria"]["enum"] == ["artesania"]


def test_category_outside_the_destination_is_retried(tmp_path, settings, state):
    llm = FakeLLM([_nz_payload("comida"), _nz_payload("naturaleza")])

    result = ExtractStage(settings, llm, DailyQuota(state, "openrouter_usd", 1.0), "p", NZ_PARAMS).run(_ctx(tmp_path))

    assert result.extraction.lugares[0].categoria == "naturaleza"
    assert "categoria 'comida'" in llm.calls[1]["messages"][-1]["content"]


def test_japan_category_not_in_the_list_is_still_retried(tmp_path, settings, state):
    """Antes lo rechazaba el Literal de Pydantic; ahora la comprobación del destino."""
    bad = json.loads(VALID)
    bad["lugares"][0]["categoria"] = "playa"
    llm = FakeLLM([json.dumps(bad), VALID])
    result = _stage(settings, llm, state).run(_ctx(tmp_path))
    assert result.extraction is not None and len(llm.calls) == 2
```

En `tests/unit/test_flow_viaje.py`:

```python
def test_extract_prompt_is_rendered_with_destination_categories(settings, tmp_path):
    dest = Destination(nombre="nz", flujo="viaje", raiz="jrRootNZ", descripcion="NZ",
                       prompt="Lugar: {{categorias_lugar}} · Cosa: {{categorias_cosa}}",
                       params=ViajeParams(categorias_lugar=["naturaleza", "otro"], categorias_cosa={"a": "A", "b": "B"}))
    extract = next(s for s in FLOWS["viaje"].build(dest, _deps(settings, tmp_path, FakeTrilium())).stages if s.name == "extract")
    assert extract.system_prompt == "Lugar: naturaleza, otro · Cosa: a | b"
```

Run: `uv run pytest tests/unit/test_baseline.py tests/unit/test_extract.py tests/unit/test_flow_viaje.py -q`
Expected: FAIL en la recolección con `ModuleNotFoundError: No module named 'tohoku.flows.viaje.prompt'`. Después de crear un `prompt.py` vacío, los tests fallarían por separado: esquema sin `enum` del destino, categoría `comida` aceptada y prompt sin renderizar.

- [ ] **Step 2: Implementación**

`config/prompts/japon.md`, solo dos cambios:
- `` - `categoria`: souvenirs | comida | cadenas | cosmetica | otros. `` pasa a `` - `categoria`: {{categorias_cosa}}. `` (el resto de la línea igual);
- `Categorías de lugar: templo, santuario, comida, cafe, bar, tienda, mercado, mirador, barrio, museo, parque, onsen, alojamiento, transporte, otro.` pasa a `Categorías de lugar: {{categorias_lugar}}.`

`src/tohoku/flows/viaje/prompt.py`:

```python
import copy

from tohoku.flows.viaje.params import ViajeParams
from tohoku.models import Extraction


def render_extract_prompt(template: str, params: ViajeParams) -> str:
    """Rellena las categorías del destino en el prompt (`{{categorias_lugar}}`, `{{categorias_cosa}}`)."""
    return template.replace("{{categorias_lugar}}", ", ".join(params.categorias_lugar)).replace(
        "{{categorias_cosa}}", " | ".join(params.categorias_cosa)
    )


def extraction_schema(params: ViajeParams) -> dict:
    """Esquema JSON de `Extraction` con las categorías del destino como `enum`."""
    schema = copy.deepcopy(Extraction.model_json_schema())
    schema["$defs"]["Lugar"]["properties"]["categoria"]["enum"] = list(params.categorias_lugar)
    schema["$defs"]["Cosa"]["properties"]["categoria"]["enum"] = list(params.categorias_cosa)
    return schema


def invalid_categories(extraction: Extraction, params: ViajeParams) -> list[str]:
    """Categorías que no son del destino, como mensajes para pedir al LLM que corrija."""
    lugares = ", ".join(params.categorias_lugar)
    cosas = ", ".join(params.categorias_cosa)
    return [
        *(f"lugares[{i}].categoria '{l.categoria}' no es una de: {lugares}"
          for i, l in enumerate(extraction.lugares) if l.categoria not in params.categorias_lugar),
        *(f"cosas[{i}].categoria '{c.categoria}' no es una de: {cosas}"
          for i, c in enumerate(extraction.cosas) if c.categoria not in params.categorias_cosa),
    ]
```

`src/tohoku/models.py`:
- `Lugar.categoria: str` y `Cosa.categoria: str`. Las categorías válidas dependen del destino (`ViajeParams`).
- Borrar `LugarCategoria` y `CosaCategoria`.
- `LUGAR_CATEGORIAS` y `COSA_CATEGORIAS` se quedan: son los valores por defecto de Japón.

`src/tohoku/stages/extract.py`:

```python
from tohoku.flows.viaje.params import ViajeParams
from tohoku.flows.viaje.prompt import extraction_schema, invalid_categories
...
    def __init__(self, settings, llm, budget, system_prompt: str, params: ViajeParams | None = None) -> None:
        ...
        self.system_prompt = system_prompt
        self._params = params or ViajeParams()
```

En `run`: `schema = extraction_schema(self._params)`, y el bloque de validación queda:

```python
            try:
                extraction = Extraction.model_validate_json(strip_fences(result.content))
                problems = invalid_categories(extraction, self._params)
            except ValidationError as exc:
                problems = [str(exc)]
            if problems:
                error = "\n".join(problems)
                messages = [
                    *messages,
                    {"role": "assistant", "content": result.content},
                    {"role": "user", "content": f"La respuesta no cumple el esquema:\n{error}\nDevuelve únicamente el JSON corregido."},
                ]
                continue
```

(El `log.info` de éxito y el `return` no cambian.)

`src/tohoku/flows/viaje/flow.py`, en `build`:

```python
            ExtractStage(deps.settings, deps.llm, deps.llm_budget, render_extract_prompt(dest.prompt, params), params),
```

`src/tohoku/cli.py`, en `eval`, lo mismo:

```python
    params = loaded.destination.params
    extract = ExtractStage(settings, loaded.llm, loaded.llm_budget, render_extract_prompt(loaded.destination.prompt, params), params)
```

- [ ] **Step 3: GREEN y suite**

Run: `uv run pytest tests/unit/test_baseline.py tests/unit/test_extract.py tests/unit/test_flow_viaje.py -q` → pasan.
Run: `uv run pytest -q` → verde.

Comprobación extra, que el revisor repite: `uv run python -c "from tohoku.flows.viaje.prompt import render_extract_prompt; from tohoku.flows.viaje.params import ViajeParams; print(render_extract_prompt(open('config/prompts/japon.md').read(), ViajeParams()))" | diff - <(sed -e 's/relacionado_japon/relacionado_destino/g' -e 's/confianza_japon/confianza_destino/g' tests/fixtures/baseline/extract_prompt.md)` → sin salida.

- [ ] **Step 4: Commit**

```bash
git add -A config src tests
git commit -m "feat(extract): place and thing categories come from the destination

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Listas y raíz desde el YAML (Settings, servicio, CLI y Docker)

**Files:**
- Modify: `src/tohoku/config.py` (quitar `karakeep_list_id` y `trilium_root_label`), `src/tohoku/service.py`, `src/tohoku/wiring.py`, `src/tohoku/cli.py` (`init-trilium`, `import-instagram`), `Dockerfile`, `docker-compose.yml`, `.env.example`, `tests/conftest.py`
- Test: `tests/unit/test_service.py`, `tests/unit/test_wiring_cli.py`, `tests/unit/test_config.py`

**Interfaces:**
- Consumes: `DestinationsConfig` (Task 2), `App.destinations` y `App.destination` (Task 5), `FLOWS` (Task 5).
- Produces:
  - `Service(karakeep, state, pipeline, notifier, settings, preflight, list_ids: Sequence[str], clock=...)` hace el ingest de cada lista;
  - la CLI `init-trilium [--destino X]`;
  - la CLI `import-instagram ... [--lista ID]`.

- [ ] **Step 1: Tests (RED)**

`tests/unit/test_service.py`: el helper `_service` pasa `list_ids=("L1",)` antes de `clock`. Es construcción. Añadir:

```python
def test_tick_ingests_every_configured_list(state, settings):
    karakeep = FakeKarakeep()
    karakeep.add_bookmark("a1", "https://youtu.be/a1"); karakeep.add_to_list("L1", "a1")
    karakeep.add_bookmark("b1", "https://youtu.be/b1"); karakeep.add_to_list("L2", "b1")
    service = Service(karakeep, state, FakePipeline(), FakeNotifier(), settings, lambda: None, list_ids=("L1", "L2"))

    service.tick()

    assert state.has_job("a1") and state.has_job("b1")
```

(Si `FakeKarakeep` no tiene `add_bookmark` con esa firma, usar el mismo mecanismo que ya usa el `_service` existente para crear `b1` en `L1`. El implementador lo lee en `tests/fakes.py:12-58` y lo anota como *ruling* si difiere.)

`tests/unit/test_wiring_cli.py`, añadir:

```python
def test_cli_init_trilium_uses_the_configured_destination(monkeypatch, settings):
    trilium = FakeTrilium()
    trilium.add_note("root", "Ideas de Japón", labels={"jrRoot": ""})
    app = build_app(settings)
    monkeypatch.setattr(cli, "_load", lambda: SimpleNamespace(**{**app.__dict__, "trilium": trilium}))

    result = CliRunner().invoke(cli.app, ["init-trilium"])

    assert result.exit_code == 0, result.output
    assert "Estructura lista" in result.output
    assert trilium.search("#jrMapa")


def test_cli_init_trilium_rejects_unknown_destination(monkeypatch, settings):
    app = build_app(settings)
    monkeypatch.setattr(cli, "_load", lambda: app)
    result = CliRunner().invoke(cli.app, ["init-trilium", "--destino", "nz"])
    assert result.exit_code == 2


def test_cli_import_uses_the_only_configured_list(monkeypatch, settings, tmp_path):
    app = build_app(settings)
    seen = {}
    monkeypatch.setattr(cli, "_load", lambda: app)
    monkeypatch.setattr(cli, "parse_export", lambda path: [])
    monkeypatch.setattr(cli, "import_items", lambda items, karakeep, list_id, dry_run, limit: seen.setdefault("list", list_id) and None)
    monkeypatch.setattr(cli, "format_import_report", lambda report, dry_run: "ok")

    result = CliRunner().invoke(cli.app, ["import-instagram", str(tmp_path / "x.json"), "--dry-run"])

    assert result.exit_code == 0, result.output
    assert seen["list"] == "L1"
```

`tests/unit/test_config.py`:
- en `REQUIRED`, quitar `"KARAKEEP_LIST_ID": "L"`, porque ya no es obligatorio;
- en `test_settings_read_from_environment_with_defaults`, la línea `assert s.trilium_root_label == "jrRoot"` pasa a `assert s.destinos_file == Path("config/destinos.yaml")`. Es la **única** aserción que cambia en toda la fase: el ajuste se trasladó de `.env` al YAML. El revisor la acepta explícitamente por este motivo.

Run: `uv run pytest tests/unit/test_service.py tests/unit/test_wiring_cli.py tests/unit/test_config.py -q`
Expected: FAIL. Errores esperados:
- todos los tests de `test_service.py` que usan `_service`, y el nuevo: `TypeError: Service.__init__() got an unexpected keyword argument 'list_ids'`;
- `test_cli_init_trilium_rejects_unknown_destination`: el código de salida es 2 por `No such option: --destino`. El test pasaría por el motivo equivocado, así que el implementador comprueba en la salida que el error es ese y lo anota; tras el Step 2 debe seguir en 2, pero por el destino desconocido;
- `test_cli_init_trilium_uses_the_configured_destination` puede pasar ya: la raíz de `settings` y la del YAML son la misma, `jrRoot`. Es caracterización y se anota;
- `test_settings_read_from_environment_with_defaults`: `ValidationError` (falta `KARAKEEP_LIST_ID`, que todavía es obligatorio).

`test_cli_import_uses_the_only_configured_list` puede pasar ya (la lista de `settings` y la del YAML son la misma, `L1`): es caracterización. **Anotar en el ledger qué tests fallaron y con qué error.**

- [ ] **Step 2: Implementación**

`src/tohoku/config.py`: borrar `karakeep_list_id: str` y `trilium_root_label: str = "jrRoot"`.

`src/tohoku/service.py`:

```python
        preflight: Callable[[], None],
        list_ids: Sequence[str],
        clock: Callable[[], datetime] = _local_now,
    ) -> None:
        ...
        self._list_ids = list(list_ids)
...
    def tick(self) -> None:
        if not self._ready:
            self._preflight()
            self._ready = True
        new: list[str] = []
        unsupported: list[str] = []
        for list_id in self._list_ids:
            report = ingest(self._karakeep, self._state, list_id)
            new += report.new
            unsupported += report.unsupported
        processed = self._pipeline.run_due()
        if new or unsupported or processed:
            log.info("sondeo nuevos=%d no_soportados=%d procesados=%d", len(new), len(unsupported), processed)
        self._maybe_daily_summary()
```

(con `from collections.abc import Callable, Sequence`).

`src/tohoku/wiring.py`: `Service(karakeep, state, pipeline, notifier, settings, lambda: preflight(settings, trilium, llm, runtime), list_ids=list(destinations.listas))`.

`src/tohoku/cli.py`:

```python
from tohoku.flows.registry import FLOWS
...
@app.command("init-trilium")
def init_trilium(
    destino: Annotated[str | None, typer.Option(help="Destino de config/destinos.yaml (por defecto, el único)")] = None,
) -> None:
    """Crea bajo la nota raíz del destino la estructura que falte (idempotente)."""
    loaded = _load()
    try:
        dest = loaded.destinations.destinos.get(destino) if destino else loaded.destination
        if dest is None:
            raise ConfigError(f"No existe el destino '{destino}' en {loaded.settings.destinos_file}")
        summary = FLOWS[dest.flujo].init_trilium(loaded.trilium, dest)
    except ConfigError as exc:
        raise _config_exit(exc) from exc
    typer.echo(summary)
```

En `import-instagram`, añadir la opción y resolver la lista:

```python
    lista: Annotated[str | None, typer.Option(help="Lista de Karakeep destino (por defecto, la única de config/destinos.yaml)")] = None,
...
    listas = list(loaded.destinations.listas)
    list_id = lista or (listas[0] if len(listas) == 1 else None)
    if list_id is None:
        typer.echo(f"Hay {len(listas)} listas configuradas: indica una con --lista ({', '.join(listas)})", err=True)
        raise typer.Exit(2)
    report = import_items(items, loaded.karakeep, list_id, dry_run, limit)
```

`_load`: si `build_app` lanza `ConfigError` (YAML inválido), mostrarlo con `_config_exit`:

```python
def _load() -> App:
    setup_logging()
    try:
        return build_app(Settings())
    except ValidationError as exc:
        typer.echo(f"Configuración incompleta (revisa .env):\n{exc}", err=True)
        raise typer.Exit(2) from exc
    except ConfigError as exc:
        raise _config_exit(exc) from exc
```

`tests/conftest.py`: quitar `karakeep_list_id="L1",`.

`Dockerfile`, después de `COPY src ./src`:

```dockerfile
COPY config ./config
```

`docker-compose.yml`, en `volumes` del servicio:

```yaml
      - ./config:/app/config:ro   # destinos y prompts editables sin reconstruir (reiniciar el contenedor)
```

`.env.example`:
- quitar `KARAKEEP_LIST_ID=…` y `TRILIUM_ROOT_LABEL=…`;
- añadir `# DESTINOS_FILE=config/destinos.yaml   # listas de Karakeep, raíces de Trilium y prompts (ver config/destinos.yaml)`.

El `.env` real **no se toca**: su `KARAKEEP_LIST_ID` queda ignorado (`extra="ignore"`). Se avisa al usuario de que puede borrar esa línea cuando quiera.

- [ ] **Step 3: GREEN y suite**

Run: `uv run pytest -q` → verde.
Run: `git grep -n "karakeep_list_id\|trilium_root_label\|KARAKEEP_LIST_ID\|TRILIUM_ROOT_LABEL" -- src tests .env.example` → sin resultados.
Run: `docker compose config --quiet` → sin errores.

- [ ] **Step 4: Commit**

```bash
git add -A src tests Dockerfile docker-compose.yml .env.example
git commit -m "feat: Karakeep lists and Trilium root come from config/destinos.yaml

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Documentación, hoja de ruta y verificación sobre una copia real

**Files:**
- Modify: `docs/operations.md` (sección "Destinos: `config/destinos.yaml`"), `docs/pipeline/01-ingest.md`, `04-extract.md` y `05-geocode.md` (secciones Configuración), `docs/trilium-model.md` (raíz por destino), `README.md` (puesta en marcha), `CLAUDE.md` (Entorno y Estado), `docs/superpowers/plans/2026-09-30-fases-2-6-multidestino.md` (rulings 1-8 de este plan en la Fase 2 y lo aplazado a las fases 5 y 6)

- [ ] **Step 1: Docs.**
  - `operations.md` explica:
    - la estructura del YAML;
    - que editar `config/` no requiere reconstruir, solo `docker compose restart tohoku`;
    - que el prompt de Japón está en `config/prompts/japon.md`, con los marcadores `{{categorias_lugar}}` y `{{categorias_cosa}}`;
    - que `init-trilium` acepta `--destino` e `import-instagram` acepta `--lista`;
    - que `KARAKEEP_LIST_ID` y `TRILIUM_ROOT_LABEL` ya no se leen de `.env`.
  - `04-extract.md`: la ruta del prompt es `config/prompts/japon.md`.
  - `05-geocode.md`: país, límites, alias y región vienen del destino, y la caché va separada por país (Japón sin prefijo).

- [ ] **Step 2: Verificación con la imagen y una copia de `state.db`** (sin tocar producción)

```bash
SCRATCH=/tmp/claude-1000/-media-1tb-disk-japan-reader/ae84541b-fb58-40c8-851c-2ad836c092c9/scratchpad
docker build -t tohoku:fase2 .
mkdir -p "$SCRATCH/data-copy" && uv run python -c "import sqlite3; s=sqlite3.connect('file:data/state.db?mode=ro', uri=True); d=sqlite3.connect('$SCRATCH/data-copy/state.db'); s.backup(d)"
docker run --rm --env-file .env -e DATA_DIR=/data -v "$SCRATCH/data-copy:/data" tohoku:fase2 tohoku status
docker compose exec tohoku tohoku status
```

Expected:
- los dos `status` dan los mismos recuentos (salvo el avance de la cola entre ambas lecturas);
- el contenedor de prueba arranca **sin** montar `./config`, lo que demuestra que la imagen lleva el YAML.

Después: `docker rmi tohoku:fase2` y `rm -r "$SCRATCH/data-copy"`.

- [ ] **Step 3: Commit y parada**

```bash
git add README.md CLAUDE.md docs
git commit -m "docs: destinations config, viaje flow and phase 2 rulings

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

**Parada para el usuario.** Informar de qué ha cambiado y de las decisiones tomadas. La integración en `master` (`git switch master && git merge --ff-only feat/tohoku`) y el despliegue se hacen solo con su visto bueno, entre tandas: `docker compose build && docker compose up -d`, y comprobar que `status` coincide y que el primer enlace procesado publica como antes.
