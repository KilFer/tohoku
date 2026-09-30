# Fases 3 y 4: varios destinos con clasificador y limpieza de datos intermedios — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Modo acordado con el usuario:** subagentes con **revisión especial de TDD**. Cada tarea declara qué tests deben fallar (RED) y por qué. El controlador vuelve a ejecutar los tests nuevos contra el código anterior a la tarea para confirmar ese RED. Los tests que ya pasan de entrada son caracterización y se declaran como tal.

**Goal:**
- **Fase 3:** que una lista de Karakeep pueda apuntar a varios destinos, con un clasificador barato que elige uno.
- **Fase 4:** que los datos intermedios no crezcan sin límite.
- **En ambas:** que Japón (lista de un solo destino) siga funcionando como hoy y que los jobs aparcados de la importación reanuden bien.

**Architecture:**
- **Estado:** `jobs` gana `candidates` y `destination`.
- **`classify`:** etapa común nueva entre `transcribe` y el flujo. Con un solo candidato no llama al LLM.
- **Pipeline:** ejecuta el tramo común, lee el destino elegido y ejecuta las etapas del flujo de ese destino (un `FlowRuntime` por destino).
- **`DESCARTADO`:** sustituye a `NO_JAPON`.
- **Limpieza (fase 4):** un módulo `cleanup` borra los ficheros del job al terminar y purga los resultados de etapa pasado `retencion_dias`.

**Tech Stack:** Python 3.12, uv, Pydantic v2, SQLite, pytest, respx, OpenRouter.

**Spec:** `docs/superpowers/specs/2026-09-30-multi-destino-design.md` (§3, §4, §5, §6.4, §7) · **Hoja de ruta:** `docs/superpowers/plans/2026-09-30-fases-2-6-multidestino.md` (fases 3 y 4, con las decisiones de la fase 2).

**Rama:** `feat/tohoku`, encima de `702c82f`. No se integra ni se despliega sin el usuario, y en ningún caso antes de que termine la tanda 7.

## Global Constraints

- Español en docs, docstrings y mensajes. **Nunca** crear, editar ni mostrar `.env`.
- TDD sin red. `uv run pytest -q` en verde al final de cada tarea, con el recuento real.
- **Japón sin cambios visibles**, con cuatro excepciones deliberadas:
  1. La etapa `classify` se inserta y no hace llamadas cuando solo hay un candidato.
  2. `jr:no-japon` pasa a `jr:descartado` para los jobs nuevos.
  3. Se añade la etiqueta `jr:destino:<d>` en Karakeep.
  4. Los ficheros del job se borran al terminar (fase 4).
- **Aserciones:** los tests existentes no cambian ninguna, salvo las que la Task 1 lista (`NO_JAPON` → `DESCARTADO`) y las que la Task 7 lista (orden de etapas con `classify`, varios destinos ya admitidos). Cualquier otra que haya que cambiar es una regresión: se para y se reporta.
- **Compatibilidad con `state.db` real** (unos 900 jobs, 427 pendientes aparcados a mitad):
  - los jobs sin `candidates` son de Japón (el `destino_legado`);
  - `outcome='no-japon'` se lee como `DESCARTADO`;
  - un job aparcado en `geocode` reanuda sin rehacer `extract`.
- **Prefijo `jr`** para todo lo generado (`jr:descartado`, `jr:destino:<d>`).
- Commits en `feat/tohoku`, con el mensaje terminado en `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- No tocar `data/` salvo **leer** una copia de `state.db` en las verificaciones. No construir la imagen de producción ni tocar contenedores (solo `tohoku:fase34` de prueba en las Tasks 9 y 11).

## Decisiones de este plan (rulings)

1. **Jobs anteriores a la fase 3.**
   - La migración deja `candidates` a NULL. `classify` los trata como candidatos `[destino_legado]`, que es una clave nueva y opcional del YAML.
   - Si falta la clave y hay un único destino, se usa ese. Si faltan ambas cosas con varios destinos, es un `ConfigError`.
   - Motivo: no dejar el nombre `japon` fijo en el código de la migración.
2. **`reprocess` de un bookmark que no está en `state.db`:** usa `destino_legado`, salvo que se pase `--destino`. Karakeep no dice en qué listas está un bookmark sin recorrerlas todas.
3. **Destino forzado:**
   - `reprocess --destino X` guarda `destination=X` y borra desde `classify`. `classify` respeta el destino guardado y no llama al LLM.
   - `reprocess --from fetch|transcribe|classify` **sin** `--destino` borra `destination`, así que el destino se vuelve a decidir.
   - `reprocess --from extract` o posterior sin `--destino` conserva el destino y el resultado de `classify`.
4. **Modo `etiqueta`:** la confianza es 1,0 y no hay alternativa (sin logprobs; YAGNI). Los adaptadores específicos (JEV) quedan como punto abierto: hay un registro `CLASSIFIERS` listo para añadirlos.
5. **Modelo del clasificador:** `clasificador.modelo` del YAML. Si no se indica, se usa `OPENROUTER_TEXT_MODEL` (o `OPENROUTER_MODEL`). El preflight solo lo comprueba si alguna lista tiene más de un destino.
6. **`clasificacion-dudosa`:** la calcula `classify` (`Classification.dudosa`) y la añade el `resolve` del flujo `viaje` a los motivos comunes.
7. **`App.stages`:** es el tramo común más las etapas del destino legado. Solo se mantiene para el test de orden de etapas y la CLI `eval`.
8. **Fase 4:**
   - Al limpiar un job terminado se borran su directorio y el resultado de `fetch`, que apunta a esos ficheros. Si se reprocesa, `fetch` vuelve a descargar (y falla si la fuente ya no existe: se documenta).
   - La limpieza de directorios de jobs antiguos terminados se hace en cada pasada del servicio. La primera pasada libera los ~800 existentes.

## Review Focus

1. **Jobs aparcados de la importación** (pendientes con `extract` hecho y sin `candidates`): al desplegar deben pasar por `classify` sin coste y seguir en `geocode`, sin rehacer nada. Test con fixture real en la Task 7 y verificación sobre una copia en la Task 9.
2. **El clasificador devuelve un destino que no es candidato, o texto irreconocible:** un reintento y luego `TransientError`. Nunca se publica en un destino no permitido. Tests en la Task 6.
3. **El mismo bookmark en dos listas con destinos distintos:** un solo job con la unión de candidatos, y se clasifica. Test en la Task 4.
4. **`reprocess --destino` sobre un job ya publicado en otro destino:** se vuelve a publicar en el nuevo. Las notas viejas del otro destino no se borran, y queda documentado. Test en la Task 8.
5. **Purga por retención con un job reprocesándose (PENDING) o en ERROR:** no se toca nada. Tests en la Task 10.

---

## Fase 3

### Task 1: `DESCARTADO` y etiqueta de destino en Karakeep

**Files:**
- Modify: `src/tohoku/models.py` (`Outcome`), `src/tohoku/rules.py:21`, `src/tohoku/stages/mark.py`, `src/tohoku/state.py` (`status_counts`)
- Test: `tests/unit/test_ingest_mark.py`, `tests/unit/test_text_rules.py`, `tests/unit/test_publish.py:189`, `tests/unit/test_state.py`

**Interfaces (produce):**
- `Outcome.DESCARTADO = "descartado"`. `Outcome("no-japon")` devuelve `Outcome.DESCARTADO` (compatibilidad), y `Outcome.NO_JAPON` desaparece.
- `OUTCOME_TAGS[Outcome.DESCARTADO] = "jr:descartado"`.
- `MarkStage.run(bookmark_id, outcome, destination: str | None = None) -> MarkResult`. Pone `[tag]` más `jr:destino:<destination>` si `destination`. Solo quita las etiquetas `jr:` que no estén en ese conjunto. `MarkResult` gana `destination_tag: str | None = None`.
- `StateStore.status_counts()` agrupa `no-japon` bajo `descartado`.

- [ ] **Step 1: Tests (RED)**

Aserciones existentes que cambian (**lista cerrada**):
- `tests/unit/test_ingest_mark.py:75`: `(Outcome.NO_JAPON, "jr:no-japon", True)` → `(Outcome.DESCARTADO, "jr:descartado", True)`;
- `tests/unit/test_text_rules.py:50`: `Outcome.NO_JAPON` → `Outcome.DESCARTADO`;
- `tests/unit/test_publish.py:189`: `Outcome.NO_JAPON` → `Outcome.DESCARTADO`;
- `tests/unit/test_baseline.py` (`test_real_not_japan_result_publishes_nothing`): `Outcome.NO_JAPON` → `Outcome.DESCARTADO`.

Tests nuevos:

`tests/unit/test_ingest_mark.py`:

```python
def test_legacy_no_japon_outcome_is_read_as_descartado():
    assert Outcome("no-japon") is Outcome.DESCARTADO


def test_mark_adds_destination_tag_and_replaces_old_jr_tags():
    karakeep = FakeKarakeep([Bookmark(id="b1", url="https://youtu.be/a", tags=["jr:no-japon", "jr:destino:recetas", "viaje"])])

    result = MarkStage(karakeep).run("b1", Outcome.PROCESADO, destination="japon")

    tags = karakeep.bookmarks["b1"].tags
    assert sorted(t for t in tags if t.startswith("jr:")) == ["jr:destino:japon", "jr:procesado"]
    assert "viaje" in tags and result.destination_tag == "jr:destino:japon"


def test_mark_without_destination_adds_no_destination_tag():
    karakeep = FakeKarakeep([Bookmark(id="b1", url="https://youtu.be/a")])
    result = MarkStage(karakeep).run("b1", Outcome.DESCARTADO)
    assert [t for t in karakeep.bookmarks["b1"].tags if t.startswith("jr:")] == ["jr:descartado"]
    assert result.destination_tag is None
```

`tests/unit/test_state.py`:

```python
def test_legacy_no_japon_jobs_are_counted_as_descartado(state):
    state.add_job("b1", "u1", Platform.YOUTUBE, ContentHint.VIDEO)
    state.finish("b1", Outcome.DESCARTADO)
    state._db.execute("UPDATE jobs SET outcome = 'no-japon' WHERE bookmark_id = 'b1'")  # fila de antes de la fase 3
    state.add_job("b2", "u2", Platform.YOUTUBE, ContentHint.VIDEO)
    state.finish("b2", Outcome.DESCARTADO)

    assert state.status_counts() == {"descartado": 2}
    assert state.get_job("b1").outcome is Outcome.DESCARTADO
```

Run: `uv run pytest tests/unit/test_ingest_mark.py tests/unit/test_text_rules.py tests/unit/test_publish.py tests/unit/test_state.py tests/unit/test_baseline.py -q`
Expected: FAIL con `AttributeError: DESCARTADO` (en la recolección o en cada test) y `TypeError: ... unexpected keyword argument 'destination'`.

- [ ] **Step 2: Implementación**

`src/tohoku/models.py`:

```python
class Outcome(StrEnum):
    PROCESADO = "procesado"
    REVISAR = "revisar"
    DESCARTADO = "descartado"
    ERROR = "error"

    @classmethod
    def _missing_(cls, value: object) -> "Outcome | None":
        # Antes de la fase 3 el contenido ajeno al destino se guardaba como "no-japon".
        return cls.DESCARTADO if value == "no-japon" else None
```

`MarkResult` gana `destination_tag: str | None = None`.

`src/tohoku/rules.py`: `return Outcome.DESCARTADO` en lugar de `Outcome.NO_JAPON`.

`src/tohoku/stages/mark.py`:

```python
OUTCOME_TAGS: dict[Outcome, str] = {
    Outcome.PROCESADO: "jr:procesado",
    Outcome.REVISAR: "jr:revisar",
    Outcome.DESCARTADO: "jr:descartado",
    Outcome.ERROR: "jr:error",
}
DESTINATION_TAG_PREFIX = "jr:destino:"
...
    def run(self, bookmark_id: str, outcome: Outcome, destination: str | None = None) -> MarkResult:
        tag = OUTCOME_TAGS[outcome]
        destination_tag = f"{DESTINATION_TAG_PREFIX}{destination}" if destination else None
        wanted = [tag] + ([destination_tag] if destination_tag else [])
        bookmark = self._karakeep.get_bookmark(bookmark_id)
        stale = [t for t in bookmark.tags if t.startswith("jr:") and t not in wanted]
        if stale:
            self._karakeep.detach_tags(bookmark_id, stale)
        self._karakeep.attach_tags(bookmark_id, wanted)
        archive = outcome != Outcome.ERROR
        if archive:
            self._karakeep.set_archived(bookmark_id, True)
        return MarkResult(tag=tag, archived=archive, destination_tag=destination_tag)
```

`src/tohoku/state.py`, en `status_counts`: `key = "pendiente" if … else Outcome(row["outcome"]).value if row["outcome"] else row["outcome"]`, para que `no-japon` cuente como `descartado`.

Comprobar: `git grep -n "NO_JAPON\|no-japon" -- src tests ':!tests/fixtures'`. Solo puede quedar el `_missing_` y los dos tests de compatibilidad.

- [ ] **Step 3: GREEN.** Los tests focalizados y la suite completa en verde.
- [ ] **Step 4: Commit** `feat: DESCARTADO outcome (legacy no-japon accepted) and jr:destino tag`.

---

### Task 2: `candidates` y `destination` en `jobs` (con migración)

**Files:**
- Modify: `src/tohoku/state.py`
- Test: `tests/unit/test_state.py`

**Interfaces (produce):**
- `Job.candidates: list[str] | None` (None = job anterior a la fase 3) y `Job.destination: str | None`.
- `StateStore.add_job(bookmark_id, url, platform, hint, candidates: Sequence[str] | None = None) -> bool`.
- `StateStore.add_candidates(bookmark_id, names: Sequence[str]) -> None`: une sin duplicar y conserva el orden.
- `StateStore.set_destination(bookmark_id, destination: str | None) -> None`.
- Migración idempotente al abrir: `ALTER TABLE jobs ADD COLUMN candidates TEXT` y `ADD COLUMN destination TEXT` si faltan.

- [ ] **Step 1: Tests (RED)** en `tests/unit/test_state.py`:

```python
import sqlite3

OLD_JOBS_SCHEMA = """CREATE TABLE jobs (bookmark_id TEXT PRIMARY KEY, url TEXT NOT NULL, platform TEXT, hint TEXT,
    status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at TEXT, last_error TEXT,
    outcome TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"""


def test_old_database_is_migrated_and_old_jobs_have_no_candidates(tmp_path, clock):
    path = tmp_path / "state.db"
    db = sqlite3.connect(path)
    db.execute(OLD_JOBS_SCHEMA)
    db.execute("INSERT INTO jobs (bookmark_id, url, platform, hint, created_at, updated_at) VALUES ('old', 'u', 'youtube', 'video', 'x', 'x')")
    db.commit(); db.close()

    state = StateStore(path, clock=clock)
    StateStore(path, clock=clock)  # la migración es idempotente

    job = state.get_job("old")
    assert job.candidates is None and job.destination is None


def test_candidates_and_destination_roundtrip(state):
    state.add_job("b1", "u1", Platform.YOUTUBE, ContentHint.VIDEO, candidates=["japon", "recetas"])
    state.add_candidates("b1", ["recetas", "nueva_zelanda"])
    state.set_destination("b1", "recetas")

    job = state.get_job("b1")
    assert job.candidates == ["japon", "recetas", "nueva_zelanda"]
    assert job.destination == "recetas"
    state.set_destination("b1", None)
    assert state.get_job("b1").destination is None
```

Run: `uv run pytest tests/unit/test_state.py -q`
Expected: FAIL con `AttributeError: 'Job' object has no attribute 'candidates'` y `TypeError: add_job() got an unexpected keyword argument 'candidates'`.

- [ ] **Step 2: Implementación** en `src/tohoku/state.py`:
- `Job` gana `candidates: list[str] | None = None` y `destination: str | None = None`. Con un `field_validator("candidates", mode="before")` que haga `json.loads` si el valor es `str`.
- `_SCHEMA` no cambia (las bases nuevas se crean con él y después se migran igual).
- `__init__`, tras `executescript`, llama a `self._migrate()`:

```python
    def _migrate(self) -> None:
        """Columnas añadidas después de la primera versión (idempotente)."""
        columns = {row["name"] for row in self._db.execute("PRAGMA table_info(jobs)")}
        if "candidates" not in columns:
            self._db.execute("ALTER TABLE jobs ADD COLUMN candidates TEXT")  # JSON; NULL = anterior a la fase 3
        if "destination" not in columns:
            self._db.execute("ALTER TABLE jobs ADD COLUMN destination TEXT")
```

- `add_job(..., candidates=None)`: inserta `json.dumps(list(candidates))` o NULL.
- `add_candidates`: lee, une (`list(dict.fromkeys(old + new))`) y guarda. Si el job tenía NULL, parte de `[]`.
- `set_destination`: `UPDATE jobs SET destination = ?, updated_at = ?`.

- [ ] **Step 3: GREEN** y suite. **Step 4: Commit** `feat(state): job candidates and destination with in-place migration`.

---

### Task 3: YAML — `clasificador` y `destino_legado`

**Files:**
- Modify: `src/tohoku/destinations.py`, `config/destinos.yaml`
- Test: `tests/unit/test_destinations.py`

**Interfaces (produce):**

```python
class ClassifierConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    modelo: str | None = None                   # None → OPENROUTER_TEXT_MODEL
    modo: str = "json_schema"                   # clave de CLASSIFIERS (Task 5)
    confianza_minima: float = Field(0.5, ge=0, le=1)
    margen_revision: float = Field(0.15, ge=0, le=1)
```

- `DestinationsConfig` gana:
  - `clasificador: ClassifierConfig`;
  - `destino_legado: str`: el destino de los jobs anteriores a la fase 3;
  - `needs_classifier() -> bool`: alguna lista con más de un candidato.
- Claves de primer nivel admitidas: `listas`, `destinos`, `clasificador`, `destino_legado` (la Task 10 añade `limpieza`).
- `destino_legado` ausente con un único destino → ese. Ausente con varios → `ConfigError` que menciona `destino_legado`. Si apunta a un destino inexistente → `ConfigError`.
- **`single_destination()` desaparece**, y con él su test (`test_more_than_one_destination_is_not_supported_yet`), porque la funcionalidad cambia a propósito. Sus usos en `wiring` los sustituye la Task 7. Hasta entonces, `wiring` usa `config.destinos[config.destino_legado]`: esta tarea hace ese cambio mínimo para que la suite siga en verde.

- [ ] **Step 1: Tests (RED)** en `tests/unit/test_destinations.py`:

```python
TWO = JAPON.replace("  L1: [japon]\n", "  L1: [japon]\n  INBOX: [japon, recetas]\n") + """
  recetas:
    flujo: viaje
    raiz: jrRootRecetas
    descripcion: "Recetas"
    prompt: prompts/japon.md
"""


def test_classifier_defaults_and_legacy_with_single_destination(tmp_path):
    config = load_destinations(_write(tmp_path), FLOWS)
    assert config.clasificador == ClassifierConfig()
    assert config.destino_legado == "japon"
    assert not config.needs_classifier()


def test_several_destinations_require_destino_legado(tmp_path):
    with pytest.raises(ConfigError, match="destino_legado"):
        load_destinations(_write(tmp_path, TWO), FLOWS)


def test_several_destinations_with_classifier(tmp_path):
    text = "destino_legado: japon\nclasificador:\n  modelo: cheap/model\n  modo: etiqueta\n  margen_revision: 0.2\n" + TWO
    config = load_destinations(_write(tmp_path, text), FLOWS)
    assert config.needs_classifier() and config.candidates_for("INBOX") == ["japon", "recetas"]
    assert (config.clasificador.modelo, config.clasificador.modo, config.clasificador.margen_revision) == ("cheap/model", "etiqueta", 0.2)


@pytest.mark.parametrize(
    ("prefix", "message"),
    [
        ("destino_legado: nz\n", "destino_legado"),
        ("clasificador:\n  modello: x\n", "clasificador"),
        ("clasificador: 3\n", "clasificador"),
    ],
)
def test_classifier_and_legacy_errors(tmp_path, prefix, message):
    with pytest.raises(ConfigError, match=message):
        load_destinations(_write(tmp_path, prefix + JAPON), FLOWS)
```

(`from tohoku.destinations import ClassifierConfig`.)

Run: `uv run pytest tests/unit/test_destinations.py -q`
Expected: FAIL con `ImportError: cannot import name 'ClassifierConfig'` en la recolección.

- [ ] **Step 2: Implementación** en `destinations.py`, siguiendo el estilo de las comprobaciones existentes:
- `_TOP_KEYS` pasa a ser `{"listas", "destinos", "clasificador", "destino_legado"}`.
- `clasificador`: debe ser un mapa (o no estar). Se valida con `ClassifierConfig.model_validate`, envolviendo el `ValidationError` en `ConfigError(f"{path}: 'clasificador' inválido:\n{exc}")`.
- `destino_legado`, según las reglas de arriba.

`config/destinos.yaml`: añadir, comentado, cómo sería el bloque `clasificador` y explicar `destino_legado`. Con un único destino no hace falta ninguno de los dos, así que el fichero de producción sigue funcionando igual. Si se añade, que sea con `destino_legado: japon`.

- [ ] **Step 3: GREEN** y suite. **Step 4: Commit** `feat(config): classifier settings and destino_legado`.

---

### Task 4: `ingest` con candidatos por lista

**Files:**
- Modify: `src/tohoku/ingest.py`, `src/tohoku/service.py`, `src/tohoku/wiring.py`
- Test: `tests/unit/test_ingest_mark.py`, `tests/unit/test_service.py`

**Interfaces:**
- `ingest(karakeep, state, list_id, candidates: Sequence[str]) -> IngestReport`. Los jobs nuevos se crean con esos `candidates`. Si el job ya existe, sigue `pending` y no tiene `destination`, se llama a `state.add_candidates`.
- El filtro "ya procesado" (etiquetas `jr:*`) no cambia.
- `Service(..., list_ids=...)` pasa a `Service(..., lists: Mapping[str, Sequence[str]])` (lista → candidatos). `wiring` le pasa `destinations.listas`.

- [ ] **Step 1: Tests (RED).** `test_ingest_mark.py`: las llamadas existentes `ingest(karakeep, state, "L1")` ganan el argumento `candidates=["japon"]`. Es construcción, no aserción. Tests nuevos:

```python
def test_ingest_stores_the_list_candidates(state):
    karakeep = FakeKarakeep([Bookmark(id="b1", url="https://youtu.be/a")])
    ingest(karakeep, state, "L1", candidates=["japon", "recetas"])
    assert state.get_job("b1").candidates == ["japon", "recetas"]


def test_same_bookmark_in_two_lists_gets_the_union_of_candidates(state):
    """Review Focus 3."""
    karakeep = FakeKarakeep([Bookmark(id="b1", url="https://youtu.be/a")])
    karakeep.add_to_list("L2", "b1")

    ingest(karakeep, state, "L1", candidates=["japon"])
    ingest(karakeep, state, "L2", candidates=["recetas"])

    assert state.get_job("b1").candidates == ["japon", "recetas"]


def test_candidates_are_not_extended_once_the_destination_is_decided(state):
    karakeep = FakeKarakeep([Bookmark(id="b1", url="https://youtu.be/a")])
    karakeep.add_to_list("L2", "b1")
    ingest(karakeep, state, "L1", candidates=["japon"])
    state.set_destination("b1", "japon")
    ingest(karakeep, state, "L2", candidates=["recetas"])
    assert state.get_job("b1").candidates == ["japon"]
```

`test_service.py`: el helper `_service` pasa `lists={"L1": ["japon"]}` en lugar de `list_ids=("L1",)`, y el test multilista usa `lists={"L1": ["japon"], "L2": ["recetas"]}` y añade `assert state.get_job("b1").candidates == ["recetas"]`.

Run: `uv run pytest tests/unit/test_ingest_mark.py tests/unit/test_service.py -q`
Expected: FAIL con `TypeError: ingest() got an unexpected keyword argument 'candidates'` y `TypeError: ... 'lists'`.

- [ ] **Step 2: Implementación.** En `ingest`, el bucle queda así:

```python
    for bookmark in bookmarks:
        existing = state.get_job(bookmark.id)
        if existing is not None:
            if existing.status == JobStatus.PENDING and existing.destination is None:
                state.add_candidates(bookmark.id, candidates)
            continue
        if any(tag.startswith(JR_TAG_PREFIX) for tag in bookmark.tags):
            continue
        ...
        state.add_job(bookmark.id, bookmark.url, *classified, candidates=candidates)
```

(También en la rama de "fuente no soportada": `state.add_job(bookmark.id, bookmark.url, None, None, candidates=candidates)`.) En `Service.tick`, el bucle recorre `self._lists.items()` y llama a `ingest(..., list_id, candidates)`.

- [ ] **Step 3: GREEN** y suite. **Step 4: Commit** `feat(ingest): jobs carry the candidate destinations of their lists`.

---

### Task 5: Clasificadores (modos `json_schema` y `etiqueta`)

**Files:**
- Create: `src/tohoku/classify/__init__.py`, `src/tohoku/classify/base.py`, `src/tohoku/classify/llm.py`, `src/tohoku/prompts/classify.md`
- Modify: `src/tohoku/clients/openrouter.py` (añade `chat_text`), `tests/fakes.py` (`FakeLLM.chat_text`)
- Test: `tests/unit/test_classifiers.py`, `tests/unit/test_openrouter_client.py`

**Interfaces (produce):**

```python
# classify/base.py
class Candidate(BaseModel):
    nombre: str
    descripcion: str

class Verdict(BaseModel):
    """Respuesta ya interpretada de un clasificador (sin validar contra los candidatos)."""
    destino: str | None            # None = "ninguno"
    confianza: float = 1.0
    alternativa: str | None = None
    confianza_alternativa: float = 0.0
    cost_usd: float = 0.0

class ClassifierError(Exception):
    """La respuesta no se pudo interpretar; `raw` es el texto recibido y `cost_usd` lo gastado."""
    def __init__(self, message: str, raw: str, cost_usd: float) -> None: ...

class Classifier(Protocol):
    def classify(self, text: str, images: list[Path], candidates: list[Candidate], feedback: str | None = None) -> Verdict: ...

# classify/__init__.py
CLASSIFIERS: dict[str, Callable[[OpenRouterClient, str], Classifier]] = {
    "json_schema": JsonSchemaClassifier,
    "etiqueta": LabelClassifier,
}   # los adaptadores de modelos con formato propio (p. ej. JEV) se registran aquí
```

- `OpenRouterClient.chat_text(model, messages) -> ChatResult`: el mismo envío que `chat_json` pero sin `response_format` ni `require_parameters`. Se extrae una función privada `_post(model, body)` compartida por los dos, con el mismo manejo de errores de modelo y de `data["error"]`. `chat_json` no cambia de comportamiento, y lo cubren sus tests existentes.
- `JsonSchemaClassifier(llm, model)`: esquema `{"destino": enum[candidatos + "ninguno"], "confianza", "alternativa": enum[… + null], "confianza_alternativa"}`. El prompt es `classify.md` más la lista de candidatos (`- nombre: descripcion`) y el texto del contenido.
- `LabelClassifier(llm, model)`: el mismo prompt, pidiendo "responde solo con el nombre del destino o `ninguno`". La respuesta se normaliza con `fold`, `strip`, sin comillas ni punto final, y se busca un candidato exacto: si no hay, `ClassifierError`. Confianza 1,0.
- `feedback`: si no es None, se añade como mensaje de usuario final ("Tu respuesta anterior no es válida: …"), para el reintento de la Task 6.

- [ ] **Step 1: Tests (RED)** en `tests/unit/test_classifiers.py`, con `FakeLLM`. `FakeLLM.chat_text(model, messages)` registra `{"model", "messages", "schema": None}` y devuelve la siguiente respuesta. Casos:
- `json_schema` válido → `Verdict` con los cuatro campos y `cost_usd`. `calls[0]["schema"]["properties"]["destino"]["enum"] == ["japon", "recetas", "ninguno"]`. El prompt enviado contiene la descripción de cada candidato.
- `json_schema` con `"destino": "ninguno"` → `destino is None`.
- `json_schema` con JSON roto → `ClassifierError`, con `raw` igual al texto y el coste acumulado.
- `etiqueta`: respuestas `"recetas"`, `" Recetas.\n"` y `'"recetas"'` → `destino == "recetas"`. `"ninguno"` → `None`. `"cocina"` → `ClassifierError`.
- `feedback` → el último mensaje enviado contiene el texto del feedback.
- `CLASSIFIERS` contiene exactamente `json_schema` y `etiqueta`.

En `tests/unit/test_openrouter_client.py`, un test respx: `chat_text` envía un cuerpo **sin** `response_format`, devuelve `content` y `cost`, y un 404 con "no endpoints" lanza `ConfigError`.

Run: `uv run pytest tests/unit/test_classifiers.py tests/unit/test_openrouter_client.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'tohoku.classify'` y `AttributeError: 'OpenRouterClient' object has no attribute 'chat_text'`.

- [ ] **Step 2: Implementación.** `prompts/classify.md` (en español; lo carga `load_prompt("classify")`):

```markdown
Clasificas contenido corto de redes sociales (Shorts, Reels, posts) en UNO de los destinos de una base de notas personal.

Recibirás los destinos posibles con su descripción y el contenido (metadatos, caption, transcripción; a veces imágenes).

- Elige el destino cuyo objetivo encaja mejor con lo que el contenido enseña o recomienda.
- Si no encaja en ninguno, responde "ninguno".
- `confianza`: probabilidad (0-1) de que el destino elegido sea el correcto.
- `alternativa`: el segundo destino más probable (o null) y su `confianza_alternativa`.
- No inventes destinos: usa exactamente uno de los nombres dados.
```

Para `etiqueta`, se añade al final: "Responde únicamente con el nombre del destino (o `ninguno`), sin nada más."

- [ ] **Step 3: GREEN** y suite. **Step 4: Commit** `feat(classify): classifier interface with json_schema and etiqueta modes`.

---

### Task 6: Etapa `classify`

**Files:**
- Create: `src/tohoku/stages/classify.py`
- Modify: `src/tohoku/models.py` (añade `Classification`)
- Test: `tests/unit/test_classify.py`

**Interfaces (produce):**

```python
class Classification(BaseModel):          # models.py; resultado de la etapa "classify"
    destino: str | None                   # None → DESCARTADO
    confianza: float = 1.0
    alternativa: str | None = None
    confianza_alternativa: float = 0.0
    omitido: bool = False                 # sin llamada: un solo candidato o destino forzado
    dudosa: bool = False                  # alternativa a menos de margen_revision → clasificacion-dudosa
    cost_usd: float = 0.0

class ClassifyStage:                      # name = "classify", result_model = Classification
    def __init__(self, config: DestinationsConfig, classifier: Classifier | None, budget: DailyQuota) -> None: ...
```

**Comportamiento de `run(ctx)`:**
1. `ctx.job.destination` definido (forzado) → `Classification(destino=job.destination, omitido=True)`.
2. `candidates = ctx.job.candidates or [config.destino_legado]` (job anterior a la fase 3 → legado).
3. Un solo candidato → `Classification(destino=candidates[0], omitido=True)`, sin LLM.
4. Varios candidatos:
   - `budget.check()` antes de cada llamada.
   - Texto: `build_user_text(fetch, transcript)` de `stages/extract.py`. Si caption y transcripción están vacías, se añaden hasta 2 imágenes (`fetch.images + fetch.keyframes`).
   - Se llama al clasificador. Si lanza `ClassifierError` o devuelve un destino que no está en `candidates`: **un** reintento con `feedback` (qué falló y cuáles son los candidatos válidos). Si vuelve a fallar → `TransientError("clasificador: respuesta no válida: …")`.
   - El coste de todas las llamadas se suma al presupuesto y al resultado.
   - Con `destino is None` o `confianza < confianza_minima` → `destino=None`.
   - `dudosa = alternativa ∈ candidates and alternativa != destino and confianza - confianza_alternativa < margen_revision`.
5. `classifier is None` con varios candidatos → `ConfigError`. No debería pasar, porque el preflight lo impide.

- [ ] **Step 1: Tests (RED)** en `tests/unit/test_classify.py`, con un `FakeClassifier` que devuelve una lista de `Verdict` o excepciones en orden y registra `feedback` e imágenes. Casos (cada uno es un test):
- candidato único → `omitido=True`, sin llamadas, coste 0;
- job anterior a la fase 3 (`candidates=None`) → destino legado, sin llamadas;
- destino forzado → ese destino, sin llamadas, aunque haya varios candidatos;
- varios candidatos, veredicto válido → `destino`, `confianza` y coste, que también sale en el contador `openrouter_usd`;
- `ninguno` → `destino=None`;
- confianza 0,4 < mínimo 0,5 → `destino=None`;
- alternativa a 0,1 (margen 0,15) → `dudosa=True`; a 0,3 → `False`;
- destino fuera de los candidatos y luego válido → un reintento; el segundo `feedback` menciona los candidatos;
- dos respuestas inválidas (`ClassifierError`, luego destino inventado) → `TransientError`;
- sin caption ni transcripción → el clasificador recibe 2 imágenes; con texto → 0;
- presupuesto agotado → `QuotaExceeded` antes de llamar.

Los contextos se construyen con `make_ctx`, `make_fetch` y `Transcript`, y el job con `candidates` y `destination` (añadir esos parámetros opcionales a `builders.make_job`).

Run: `uv run pytest tests/unit/test_classify.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'tohoku.stages.classify'`.

- [ ] **Step 2: Implementación**, según la interfaz y el comportamiento descritos.
- [ ] **Step 3: GREEN** y suite. **Step 4: Commit** `feat(classify): classify stage (skip with one candidate, retry once, doubtful margin)`.

---

### Task 7: Pipeline con destino por job y cableado de varios destinos

**Files:**
- Modify: `src/tohoku/pipeline.py`, `src/tohoku/wiring.py`, `src/tohoku/cli.py` (`init-trilium`, `eval`), `src/tohoku/service.py` (`REPROCESS_FROM`)
- Test: `tests/unit/test_pipeline.py`, `tests/unit/test_wiring_cli.py`, `tests/unit/test_baseline.py`

**Interfaces (produce):**
- `STAGE_ORDER = ("fetch", "transcribe", "classify", "extract", "geocode", "resolve", "publish")`, y `COMMON_STAGES = ("fetch", "transcribe", "classify")`.
- `Pipeline(state, stages, mark, notifier, data_dir, clock=utcnow, flows: Mapping[str, Sequence[Stage]] | None = None)`:
  - `stages` = tramo común; `flows` = destino → etapas del flujo.
  - Con `flows=None` se comporta como hoy: `stages` es la lista completa. Así los tests existentes de `test_pipeline.py` no cambian.
  - Con `flows`, tras `classify`:
    - `destino is None` → `mark(DESCARTADO, None)` y `finish(DESCARTADO)`;
    - si no → `state.set_destination` y se ejecutan las etapas de `flows[destino]`. El `mark` final recibe `destination`.
  - Un destino que no está en `flows` es un `ConfigError`, porque el YAML ha cambiado bajo un job ya clasificado.
- `wiring.build_app`:
  - `runtimes = {name: FLOWS[d.flujo].build(d, deps) for name, d in destinations.destinos.items()}`.
  - `classifier = CLASSIFIERS[cfg.modo](llm, cfg.modelo or settings.text_model) if destinations.needs_classifier() else None`.
  - Tramo común: `[FetchStage, transcribe, ClassifyStage(destinations, classifier, llm_budget)]`.
  - `Pipeline(..., flows={n: r.stages for n, r in runtimes.items()})`.
  - `App` gana `runtimes`, pierde `runtime`, y mantiene `destination` (el legado) y `stages` (común + legado; ruling 7).
- `preflight(settings, trilium, llm, *layouts, classifier_model: str | None = None, classifier_mode: str = "json_schema")`:
  - refresca cada layout;
  - si `classifier_model` está definido, comprueba que el modelo existe (ConfigError con `clasificador.modelo=…`) y, en modo `json_schema`, que admite salida estructurada.
  - Las llamadas existentes con un solo layout siguen valiendo.
- CLI:
  - `init-trilium` sin `--destino` y con varios destinos → error "indica --destino (…)".
  - `eval` gana `--destino`, por defecto el legado.
  - `REPROCESS_FROM` = `("fetch", "classify", "extract", "geocode", "resolve", "publish")`.

- [ ] **Step 1: Tests (RED).**

Aserciones existentes que cambian (**lista cerrada**): ninguna en `test_pipeline.py`. `test_build_app_orders_stages` compara con `STAGE_ORDER`: el literal de la aserción no cambia, pero ahora incluye `classify`.

Sustituir `test_build_app_rejects_several_destinations_for_now` por `test_build_app_accepts_several_destinations`: el mismo YAML con `nz` y `destino_legado: japon`, y comprueba que `set(app.runtimes) == {"japon", "nz"}`.

Tests nuevos en `test_pipeline.py`:

```python
def _multi(tmp_path, state, verdict_destino):
    fetch = Step("fetch")
    classify = Step("classify", result=Classification(destino=verdict_destino))
    japon_publish = Step("publish", result=PublishResult(outcome=Outcome.PROCESADO))
    recetas_publish = Step("publish", result=PublishResult(outcome=Outcome.REVISAR))
    mark = FakeMark()
    pipeline = Pipeline(state, [fetch, classify], mark, FakeNotifier(), tmp_path / "data", clock=lambda: NOW,
                        flows={"japon": [japon_publish], "recetas": [recetas_publish]})
    return pipeline, mark, japon_publish, recetas_publish


def test_job_runs_the_stages_of_its_classified_destination(tmp_path, state):
    _add(state)
    pipeline, mark, japon, recetas = _multi(tmp_path, state, "recetas")
    pipeline.run_due()
    assert (japon.calls, recetas.calls) == (0, 1)
    assert state.get_job("b1").destination == "recetas" and state.get_job("b1").outcome == Outcome.REVISAR
    assert mark.calls == [("b1", Outcome.REVISAR, "recetas")]


def test_no_destination_is_descartado_without_flow_stages(tmp_path, state):
    _add(state)
    pipeline, mark, japon, recetas = _multi(tmp_path, state, None)
    pipeline.run_due()
    assert (japon.calls, recetas.calls) == (0, 0)
    assert state.get_job("b1").outcome == Outcome.DESCARTADO
    assert mark.calls == [("b1", Outcome.DESCARTADO, None)]


def test_unknown_destination_is_config_error(tmp_path, state):
    _add(state)
    pipeline, *_ = _multi(tmp_path, state, "nz")
    with pytest.raises(ConfigError, match="nz"):
        pipeline.run_due()
```

`FakeMark.run(self, bookmark_id, outcome, destination=None)` registra `(bookmark_id, outcome)` si `destination` es None, para no tocar las aserciones existentes, y `(bookmark_id, outcome, destination)` si no.

`tests/unit/test_baseline.py`, **Review Focus 1** (job aparcado de la importación):

```python
def test_parked_legacy_job_resumes_after_extract_without_redoing_it(tmp_path, settings):
    trilium, layout = _japan_trilium()
    state = StateStore(tmp_path / "state.db")
    state.add_job("b1", "https://www.instagram.com/reel/x/", Platform.INSTAGRAM, ContentHint.VIDEO)  # sin candidates: anterior a la fase 3
    state.save_stage("b1", "fetch", make_fetch())
    state.save_stage("b1", "transcribe", Transcript(text="x", origin="whisper"))
    state.save_stage("b1", "extract", ExtractResult.model_validate_json(_read(STATE / "rich_extract.json")))
    config = load_destinations(settings.destinos_file, FLOWS)
    extract = Step("extract", result=ExtractResult())   # no debe ejecutarse: el resultado ya está guardado
    geocode = Step("geocode", result=GeocodeResult.model_validate_json(_read(STATE / "rich_geocode.json")))
    publish = Step("publish", result=PublishResult(outcome=Outcome.PROCESADO))
    pipeline = Pipeline(
        state, [Step("fetch"), Step("transcribe"), ClassifyStage(config, None, DailyQuota(state, "openrouter_usd", 1))],
        FakeMark(), FakeNotifier(), tmp_path / "data",
        flows={"japon": [extract, geocode, ResolveStage(trilium, lambda: layout, Thresholds()), publish]},
    )

    pipeline.run_job(state.get_job("b1"))

    assert extract.calls == 0 and geocode.calls == 1
    assert state.load_stage("b1", "classify", Classification) == Classification(destino="japon", omitido=True)
    plan = state.load_stage("b1", "resolve", ResolveResult)
    assert [[i.key, i.kind.value, i.action, i.alias_of] for i in plan.items] == json.loads(_read(BASELINE / "rich_plan.json"))
    assert state.get_job("b1").destination == "japon"
```

(`Step`, `FakeMark` y `FakeNotifier` se mueven de `tests/unit/test_pipeline.py` a `tests/fakes.py` para poder reutilizarlos; es un cambio de ubicación, no de aserciones. `Step("fetch")` y `Step("transcribe")` no se ejecutan porque sus resultados ya están guardados; si se ejecutaran, devolverían `Dummy` y el test fallaría al usarlos.)

Run: `uv run pytest tests/unit/test_pipeline.py tests/unit/test_wiring_cli.py tests/unit/test_baseline.py -q`
Expected: FAIL con `TypeError: Pipeline.__init__() got an unexpected keyword argument 'flows'`, `ImportError: Classification` o `AttributeError: runtimes`.

- [ ] **Step 2: Implementación.** En `Pipeline.run_job`, extraer `_run_stages(ctx, stages)` (el bucle actual de cargar o ejecutar y guardar) y usarlo dos veces:

```python
            self._run_stages(ctx, self._stages)
            destination = None
            if self._flows is not None:
                decision = ctx.result("classify", Classification)
                if decision.destino is None:
                    self._finish(job, Outcome.DESCARTADO, None)
                    return
                if decision.destino not in self._flows:
                    raise ConfigError(f"El destino '{decision.destino}' del job {job.bookmark_id} ya no existe en config/destinos.yaml")
                destination = decision.destino
                self._state.set_destination(job.bookmark_id, destination)
                self._run_stages(ctx, self._flows[destination])
            outcome = ctx.result("publish", PublishResult).outcome
            self._finish(job, outcome, destination)
```

`_finish(job, outcome, destination)` hace `mark.run(...)`, pasando `destination` solo si no es None, más `state.finish` y el log. `mark_failed` pasa `job.destination` si existe.

- [ ] **Step 3: GREEN** y suite. **Step 4: Commit** `feat(pipeline): per-job destination with one flow runtime per destination`.

---

### Task 8: `reprocess --destino` y `clasificacion-dudosa`

**Files:**
- Modify: `src/tohoku/service.py` (`reprocess`), `src/tohoku/cli.py` (`reprocess --destino`), `src/tohoku/stages/resolve.py`
- Test: `tests/unit/test_service.py`, `tests/unit/test_wiring_cli.py`, `tests/unit/test_resolve.py`

**Interfaces:**
- `reprocess(state, karakeep, bookmark_id, from_stage, destination: str | None = None, known: Collection[str] = ())`:
  - con `destination`: debe estar en `known` (`ValueError` si no). Guarda `set_destination` y borra desde `classify` (o desde `from_stage` si es anterior).
  - sin `destination` y `from_stage` en `("fetch", "transcribe", "classify")`: `set_destination(None)`.
  - Un bookmark desconocido se crea sin `candidates`, así que usa el destino legado (ruling 2).
- CLI: `reprocess ... [--destino X]` pasa `known=loaded.destinations.destinos`.
- `ResolveStage`: si `ctx.results.get("classify")` existe y es `dudosa`, añade `"clasificacion-dudosa"` a `common`.

- [ ] **Step 1: Tests (RED):**
- `test_service.py`:
  - `--destino` válido → destino guardado y resultados de `classify` en adelante borrados;
  - `--destino` desconocido → `ValueError` con el nombre;
  - `--from fetch` sin `--destino` sobre un job con destino → destino a None;
  - `--from geocode` sin `--destino` → conserva destino y `classify`.
- **Review Focus 4:** un job `DONE` con destino `japon` → `reprocess --destino recetas` → `pending`, destino `recetas`, `published` de ese job borrado (porque se borra desde `classify`, que incluye `publish`). Un docstring del test explica que las notas antiguas en Trilium no se borran.
- `test_resolve.py`: `Classification(destino="japon", dudosa=True)` en `ctx` → todos los elementos llevan `clasificacion-dudosa`; `dudosa=False` o sin `classify` → no lo llevan (este último caso es el comportamiento actual).
- `test_wiring_cli.py`: `reprocess b1 --destino nz` con `fake_app` sin ese destino → salida 1 y mensaje.

Run: los tres ficheros. Expected: FAIL con `TypeError: reprocess() got an unexpected keyword argument 'destination'` y la aserción de `clasificacion-dudosa`.

- [ ] **Step 2: Implementación** según la interfaz. **Step 3: GREEN** y suite. **Step 4: Commit** `feat: reprocess --destino and clasificacion-dudosa review reason`.

---

### Task 9: Docs y verificación de la fase 3 sobre una copia real

**Files:** `docs/operations.md` (varios destinos, clasificador, `destino_legado`, `reprocess --destino`, `jr:descartado`, `jr:destino:*`), `docs/pipeline/` (nuevo `02b-classify.md` con las 7 secciones de siempre; `01-ingest.md`, `06-resolve.md` y `08-mark.md`), `docs/trilium-model.md` (motivo `clasificacion-dudosa`), `CLAUDE.md` (Estado), hoja de ruta (rulings de este plan).

- [ ] **Step 1: Docs.**
- [ ] **Step 2: Verificación sobre una copia** (sin tocar producción): con una copia de `state.db` (backup de solo lectura) y `docker build -t tohoku:fase34 .`, ejecutar `tohoku status`. Después, con `uv run python`, abrir la copia con `StateStore` (esto aplica la migración) y comprobar:
  - las columnas existen;
  - todos los jobs tienen `candidates` NULL;
  - `status` da los mismos recuentos, sumando `no-japon` a `descartado`.

  Limpiar la copia y la imagen al terminar.
- [ ] **Step 3: Commit** `docs: phase 3 (several destinations and classifier)`. **Parada para el usuario.**

---

## Fase 4

### Task 10: Limpieza en dos niveles

**Files:**
- Create: `src/tohoku/cleanup.py`
- Modify: `src/tohoku/destinations.py` (clave `limpieza`), `src/tohoku/state.py` (`delete_stage`, `purge_stage_results`, `done_job_ids_with_dirs`… ver interfaz), `src/tohoku/pipeline.py` (limpia tras terminar), `src/tohoku/service.py` (purga en cada pasada), `src/tohoku/wiring.py`, `config/destinos.yaml` (comentario de `limpieza`)
- Test: `tests/unit/test_cleanup.py`, `tests/unit/test_destinations.py`, `tests/unit/test_pipeline.py`

**Interfaces (produce):**

```python
class CleanupConfig(BaseModel):       # destinations.py; clave `limpieza` del YAML (opcional)
    model_config = ConfigDict(extra="forbid", frozen=True)
    retencion_dias: int = Field(30, ge=0)

class Cleaner:                        # cleanup.py
    def __init__(self, state: StateStore, data_dir: Path, retencion_dias: int, clock=utcnow) -> None: ...
    def job_finished(self, bookmark_id: str, outcome: Outcome) -> None:
        """Tras terminar: si no es ERROR, borra data/jobs/<id>/ y el resultado de fetch; con retención 0, todos los resultados."""
    def purge(self) -> int:
        """Una vez por pasada: resultados de etapa de jobs DONE más antiguos que la retención, y directorios de jobs DONE que sigan en disco. Devuelve cuántos jobs ha tocado."""
```

- `StateStore.delete_stage(bookmark_id, stage)`.
- `StateStore.purge_stage_results(older_than: datetime) -> list[str]`: borra los `stage_results` de jobs `status='done'` con `updated_at < older_than` y devuelve sus ids. **Nunca** toca `pending`, `error`, `published` ni la tabla `jobs`.
- `StateStore.done_job_ids() -> set[str]`.
- `Pipeline(..., cleaner: Cleaner | None = None)`: llama a `cleaner.job_finished` después de `state.finish` (en `_finish` y en `mark_failed`, que no limpia porque es ERROR). Si la limpieza falla (`OSError`), se registra un aviso y no afecta al job.
- `Service.tick` llama a `cleaner.purge()` después de `run_due` y lo registra en el log si ha tocado algún job.

- [ ] **Step 1: Tests (RED)** en `tests/unit/test_cleanup.py` (usar `tmp_path`; estado con reloj controlado):
- job `DONE` con directorio y resultados `fetch`/`transcribe`/`extract` → `job_finished` borra el directorio y `fetch`; `transcribe` y `extract` se conservan;
- `outcome=ERROR` → no se borra nada;
- `retencion_dias=0` → `job_finished` borra todos los resultados de etapa; `published` y `jobs` intactos;
- `purge`: un job `DONE` terminado hace 31 días → resultados purgados. Uno de hace 5 días → no. Uno `PENDING` antiguo (reprocesándose) → no. Uno `ERROR` antiguo → no. **Review Focus 5**;
- `purge` borra directorios de jobs `DONE` que siguen en disco (los ~800 antiguos) y no los de `pending`/`error`;
- `test_pipeline.py`:
  - pipeline con `cleaner` → tras un job `PROCESADO` no existe `data/jobs/b1`;
  - tras un reprocesado que vuelve a ejecutar `fetch` (resultado borrado), el `Step` de `fetch` se llama otra vez y los resultados siguientes guardados se reutilizan;
- `test_destinations.py`: `limpieza: {retencion_dias: 7}` se lee, `limpieza: {retencion_dias: -1}` → `ConfigError` que menciona `limpieza`, y sin la clave el valor es 30.

Run: `uv run pytest tests/unit/test_cleanup.py tests/unit/test_destinations.py tests/unit/test_pipeline.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'tohoku.cleanup'` e `ImportError: CleanupConfig`.

- [ ] **Step 2: Implementación.** `Cleaner.job_finished` usa `shutil.rmtree(dir, ignore_errors=False)` dentro de `try/except OSError` (con log). La ruta es siempre `data_dir / "jobs" / bookmark_id`: se comprueba que el id no contiene `/` ni `..` antes de borrar.
- [ ] **Step 3: GREEN** y suite. **Step 4: Commit** `feat(cleanup): delete job files after finishing and purge stage results after retention`.

### Task 11: Docs y verificación de la fase 4

**Files:** `docs/operations.md` (sección "Limpieza": qué se borra y cuándo, `retencion_dias`, qué implica para `reprocess`: vuelve a descargar y, pasada la retención, a transcribir y extraer), `docs/pipeline/02-fetch.md` (el directorio se borra al terminar), `CLAUDE.md` (Estado; quitar la nota de que `data/jobs` crece), hoja de ruta.

- [ ] **Step 1: Docs.**
- [ ] **Step 2: Verificación sobre una copia:**
  - copia de `data/state.db` y de `data/jobs/` (unos 200 MB) en el scratchpad;
  - un `Cleaner` con `retencion_dias=30` ejecuta `purge()` sobre la copia: `du -sh` antes y después, número de directorios borrados (≈ jobs DONE), ningún directorio de `pending`/`error` borrado y ningún resultado de etapa purgado (todos tienen menos de 30 días);
  - borrar la copia.
- [ ] **Step 3: Commit** `docs: phase 4 (cleanup)`. **Parada para el usuario** antes de la revisión final de la rama.
