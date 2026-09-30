# Fases 2-6: multidestino — Hoja de ruta de implementación

> **For agentic workers:** esta hoja de ruta fija el orden, los ficheros, las interfaces y los tests de aceptación de cada fase. **Antes de ejecutar una fase** se escribe su plan detallado (`docs/superpowers/plans/AAAA-MM-DD-fase-N-….md`, con el código de cada paso) con superpowers:writing-plans, partiendo de esta hoja y del código tal como haya quedado tras la fase anterior. Después se ejecuta con superpowers:subagent-driven-development o superpowers:executing-plans.

**Goal:** Que Tohoku procese varios destinos configurables (Japón, Nueva Zelanda, Recetas) con flujos intercambiables, sin cambiar el comportamiento de Japón.

**Architecture:**
- Destinos en `config/destinos.yaml`, validados con Pydantic.
- Flujos (`viaje`, `receta`) como módulos en `src/tohoku/flows/`, detrás de la interfaz `Flow`.
- El pipeline tiene un tramo común (`fetch → transcribe → classify`), sigue con las etapas del flujo del destino elegido y termina con `mark`.
- Limpieza en dos niveles de los datos intermedios.

**Tech Stack:** Python 3.12, uv, Pydantic v2, PyYAML, pytest, respx, Trilium ETAPI, OpenRouter.

**Spec:** `docs/superpowers/specs/2026-09-30-multi-destino-design.md`

**Por qué no va todo el código aquí:**
- La fase 2 reorganiza el paquete: las rutas, los nombres y las utilidades comunes que usarán las fases 3-5 salen de ese refactor.
- Escribir hoy el código paso a paso de las fases 3-5 sería escribirlo contra una estructura que aún no existe, y se quedaría obsoleto.
- Las interfaces de abajo **sí** son el contrato: los planes detallados deben respetarlas o actualizar esta hoja.

## Global Constraints

- Todas las de `2026-09-30-fase-0-1-tohoku-y-cuotas.md` (español, `.env` intocable, TDD sin red, commits con Co-Authored-By, confirmación antes de actuar sobre servicios reales).
- **Prefijo `jr` para todo lo generado:** etiquetas `jr:*`, atributos `#jr*`, raíces nuevas `jrRoot<Destino>` (`jrRootRecetas`, `jrRootNZ`), adjunto `japan-reader.json`.
- **Japón no cambia:** la suite existente pasa sin modificar ninguna aserción (solo cambia cómo se construye el destino en los tests). `#jrNombreNorm` es idéntico. No se migra ninguna nota.
- Un job = un destino. Los presupuestos y las cuotas son globales.
- Cada fase actualiza sus docs (`docs/pipeline/*`, `operations.md`, `trilium-model.md`, `CLAUDE.md`) y se despliega entre tandas de la importación, tras comprobar con una **copia** de `state.db` que los jobs pendientes reanudan en la etapa correcta.

## Review Focus

1. **`stage_results` antiguos** (`relacionado_japon`, `confianza_japon`, `outcome='no-japon'`) al reprocesar un job de antes del cambio: deben seguir cargándose. Lo cubren los fixtures reales de la fase 2 (Task 2.4).
2. **Bookmark presente en dos listas del YAML:** se unen los candidatos y el job no se duplica. Test en la Task 3.2.
3. **Clasificador que devuelve un destino que no está entre los candidatos** (p. ej. `recetas` para un bookmark de la lista "Japón" sola, o un nombre inventado): no se acepta nunca. Test en la Task 3.3.
4. **Purga por retención de un job que se está reprocesando o está en `ERROR`:** no se purga. Test en la Task 4.1.
5. **Receta sin portada** (vídeo sin fotograma elegido, o un post sin imágenes): la nota se publica sin imagen y sin error. Test en la Task 5.2.

---

## Fase 2: configuración de destinos y refactor a `flows/viaje` (sin cambio visible)

> **Estado: ejecutada (2026-09-30) en `feat/tohoku`, con el plan `2026-09-30-fase-2-destinos-y-flujo-viaje.md`.** Donde las tareas 2.1-2.5 de abajo difieren de lo que sigue, manda esto. Decisiones (rulings) del plan de la fase 2:
>
> 1. **Prompt completo por destino** (clave `prompt:` en el YAML, p. ej. `config/prompts/japon.md`) en lugar de `viaje.md` base + `contexto`. El prompt de Japón queda idéntico texto a texto; solo se renderizan `{{categorias_lugar}}` y `{{categorias_cosa}}`. Coste: dos destinos de viaje duplican texto de prompt (es contenido, no código). Por tanto no existe `src/tohoku/prompts/viaje.md` ni el campo `contexto`.
> 2. **`palabras_genericas` por destino se aplaza a la fase 6.** `normalize_name` sigue con su lista global, así que las claves `#jrNombreNorm` de Japón no cambian. Nueva Zelanda decidirá si lo necesita.
> 3. **Mover los módulos a `flows/viaje/` y extraer utilidades comunes (Task 2.3) se aplaza a la fase 5**, cuando el segundo flujo muestre qué es común de verdad. En la fase 2, `flows/viaje/` solo contiene los parámetros, el prompt y el adaptador `Flow`; `stages/*`, `geo.py`, `trilium_layout.py` y `rules.py` no se han movido.
> 4. **El pipeline no cambia en la fase 2.** `wiring` monta la lista de etapas; el destino por job y `resolve_destination` llegan en la fase 3.
> 5. **Interfaz `Flow`:** `build(dest, deps) -> FlowRuntime` (con `.stages` y `.refresh()`) e `init_trilium(trilium, dest) -> str`. `refresh()` sustituye al `layout.refresh()` del preflight y mantiene el contrato duck-typed de los tests de `preflight`. Sustituye a `stages/init_trilium/check` de la Task 2.2.
> 6. **Caché de Places:** las entradas existentes son de Japón y siguen sin prefijo; otros países usan el prefijo `"<PAIS>|"`.
> 7. **Sin iconos por destino:** una categoría sin icono usa el pin genérico (`ICONS["otro"]`). No hay campo `iconos` en `ViajeParams`.
> 8. **`Thresholds` y sus variables de entorno** (`JAPAN_MIN_CONFIDENCE`...) no se renombran en la fase 2.
>
> Otros ajustes ya aplicados: el compose monta `./config:/app/config:ro` (no `/config`) y la imagen lleva `config/` (`COPY config ./config`); `KARAKEEP_LIST_ID` y `TRILIUM_ROOT_LABEL` se eliminan de `Settings`; `ClassifierConfig` y `CleanupConfig` no existen todavía (fases 3 y 4).
>
> **Aplazado a otras fases:** a la **fase 5**, mover módulos a `flows/viaje/` y extraer las utilidades comunes de publicación (Task 2.3), y la interfaz definitiva de `Flow` cuando haya dos flujos; a la **fase 6**, `palabras_genericas` por destino, los iconos por destino si NZ los necesita y el renombrado de `Thresholds`/`JAPAN_*` si procede.


### Task 2.1: Modelo de configuración y carga del YAML

**Files:**
- Create: `src/tohoku/destinations.py`, `config/destinos.yaml`, `tests/unit/test_destinations.py`
- Modify: `src/tohoku/config.py` (añade `destinos_file: Path = Path("config/destinos.yaml")`; `karakeep_list_id` y `trilium_root_label` pasan al YAML), `docker-compose.yml` (monta `./config:/config:ro`, `DESTINOS_FILE=/config/destinos.yaml`), `pyproject.toml` (`pyyaml` si no está)

**Interfaces (produce):**

```python
class ClassifierConfig(BaseModel):
    modelo: str | None = None
    modo: Literal["json_schema", "etiqueta"] = "json_schema"   # se amplía con adaptadores en la fase 3
    confianza_minima: float = 0.5
    margen_revision: float = 0.15

class CleanupConfig(BaseModel):
    retencion_dias: int = 30

class Destination(BaseModel):
    nombre: str              # clave en el YAML ("japon")
    flujo: str               # "viaje" | "receta"
    raiz: str                # etiqueta de la raíz en Trilium ("jrRoot")
    descripcion: str
    contexto: Path | None
    params: BaseModel        # ViajeParams / RecetaParams, validado por el flujo

class DestinationsConfig(BaseModel):
    clasificador: ClassifierConfig
    limpieza: CleanupConfig
    listas: dict[str, list[str]]           # id de lista de Karakeep → nombres de destino
    destinos: dict[str, Destination]
    def candidates_for(self, list_id: str) -> list[str]: ...

def load_destinations(path: Path, flows: Mapping[str, Flow]) -> DestinationsConfig
    # ConfigError si: YAML inválido, flujo desconocido, lista → destino inexistente, contexto ausente,
    # parámetros que no validan contra flows[flujo].params_model
```

**Tests de aceptación:** YAML mínimo válido; cada caso de `ConfigError` anterior con un mensaje que nombra la clave culpable; los parámetros por defecto de `ViajeParams` reproducen las constantes actuales.

### Task 2.2: Interfaz `Flow` y registro

**Files:**
- Create: `src/tohoku/flows/__init__.py` (`FLOWS: dict[str, Flow]`), `src/tohoku/flows/base.py`

**Interfaces (produce):**

```python
class Flow(Protocol):
    name: str
    params_model: type[BaseModel]
    def stages(self, dest: Destination) -> list[Stage]
    def init_trilium(self, dest: Destination) -> None
    def check(self, dest: Destination) -> None          # preflight; ConfigError si falta la estructura
```

### Task 2.3: Utilidades comunes de publicación

Se sacan de `stages/publish.py` y `notes.py` a `src/tohoku/flows/common/` sin cambiar su comportamiento:
- `upsert_labels` y `sync_labels`;
- "Mis notas" (`compose_content` y parte de `render_*`);
- adjunto de datos (`load_data`/`dump_data`, `DATA_ATTACHMENT_TITLE`);
- `SourceEntry` y `add_source`;
- clonado y sincronización de la Bandeja;
- llamada al LLM con reintento de esquema (hoy dentro de `ExtractStage.run`).

**Tests de aceptación:** `test_publish.py` y `test_notes.py` pasan sin cambiar aserciones (solo cambian imports).

### Task 2.4: Flujo `viaje` = código actual parametrizado por destino

**Files:**
- Move: `stages/extract.py`, `stages/geocode.py`, `stages/resolve.py`, `stages/publish.py`, `geo.py`, `trilium_layout.py`, `rules.py`, y los modelos de viaje de `models.py` → `src/tohoku/flows/viaje/`
- Create: `src/tohoku/flows/viaje/params.py`, `src/tohoku/prompts/viaje.md` (el `extract.md` actual con `{contexto}`, `{categorias_lugar}`, `{categorias_cosa}`), `config/prompts/japon.md` (el texto de Japón que sale de `extract.md`)
- Create: `tests/fixtures/state_results/` (3-5 JSON reales de `extract`/`geocode`/`resolve` exportados de una copia de `state.db`, sin datos personales)

**Interfaces (produce):**

```python
class ViajeParams(BaseModel):
    pais: str = "JP"                                   # ISO 3166-1
    palabras_genericas: list[str] = ["japan", "japon"]
    categorias_lugar: list[str] = [...15 actuales...]
    categorias_cosa: dict[str, str] = {...5 actuales...}
    alias_ciudad: dict[str, list[str]] = {...CITY_ALIASES actual...}
    iconos: dict[str, str] = {...ICONS actual...}

class Extraction(BaseModel):                           # viaje
    relacionado_destino: bool = Field(validation_alias=AliasChoices("relacionado_destino", "relacionado_japon"))
    confianza_destino: float = Field(ge=0, le=1, validation_alias=AliasChoices("confianza_destino", "confianza_japon"))
    ...

def extraction_schema(params: ViajeParams) -> dict     # JSON Schema con enum de categorías del destino
def in_country(match: GeoMatch, pais: str) -> bool     # sustituye a in_japan
def name_key(name: str, generic: Iterable[str]) -> str # palabras comunes + las del destino
```

Cambios de comportamiento: ninguno. `Layout` se resuelve desde `dest.raiz` y `categorias_cosa`. `rules.japan_decision` pasa a `destination_decision`.

**Tests de aceptación:**
- La suite actual pasa sin cambiar aserciones.
- `name_key` da exactamente el mismo resultado que antes para 50 nombres reales de `#jrNombreNorm` (fixture).
- Los fixtures de `state_results` antiguos se cargan y `resolve` + `publish` (con fakes) producen el mismo plan.
- `extraction_schema(ViajeParams())` es equivalente al esquema actual.
- El prompt renderizado para Japón es igual, texto por texto, al `extract.md` actual (salvo espacios).

### Task 2.5: Pipeline y cableado por destino

**Files:**
- Modify: `src/tohoku/pipeline.py` (tramo común + `FLOWS[dest.flujo].stages(dest)` + `mark`), `src/tohoku/wiring.py` (carga el YAML, el preflight llama a `flow.check(dest)` por destino), `src/tohoku/ingest.py` (lista del YAML), `src/tohoku/cli.py` (`init-trilium --destino`, que por defecto usa el único destino)
- Test: `tests/unit/test_wiring_cli.py`, `tests/unit/test_pipeline.py`

**Interfaces (produce):**
- `Pipeline(state, common_stages, resolve_destination: Callable[[Job], Destination], flows, mark, notifier, data_dir)`.
- En esta fase `resolve_destination` devuelve siempre el único destino. La fase 3 lo sustituye por el resultado de `classify`.

**Verificación de la fase:**
- `uv run pytest -q` en verde.
- Sobre una copia de `state.db` en el host: `tohoku status` da los mismos recuentos.
- Un `reprocess --from resolve` de un job antiguo en un entorno de prueba (raíz `#jrRootTest`) publica igual.
- Despliegue entre tandas.

---

## Fase 3: varias listas, clasificador y destino por job

### Rulings de la fase 3 (plan de ejecución `2026-09-30-fase-3-4-clasificador-y-limpieza.md`)

Prevalecen sobre lo que digan las tareas de más abajo.

1. **Jobs anteriores:** la migración deja `candidates` y `destination` a NULL (no asigna `japon`). `classify` los trata como `[destino_legado]`, clave opcional del YAML: por defecto el único destino; con varios y sin la clave, `ConfigError`.
2. **`reprocess` de un bookmark que no está en `state.db`:** usa `destino_legado`, salvo `--destino`.
3. **Destino forzado:** `reprocess --destino X` guarda `destination=X` y repite desde `classify` (que no llama al LLM). `--from fetch|transcribe|classify` sin `--destino` olvida el destino; `--from extract` o posterior lo conserva. Las notas viejas de Trilium no se borran.
4. **Modo `etiqueta`:** confianza 1,0 y sin alternativa; adaptadores específicos (JEV) abiertos vía registro `CLASSIFIERS`.
5. **Modelo del clasificador:** `clasificador.modelo`, o `OPENROUTER_TEXT_MODEL`/`OPENROUTER_MODEL`. El preflight solo lo comprueba si alguna lista tiene varios destinos.
6. **`clasificacion-dudosa`:** la calcula `classify` (`Classification.dudosa`) y la añade el `resolve` del flujo `viaje`.
7. **`App.stages`:** tramo común + etapas del destino legado; solo para el test de orden y `eval`.
8. **Fase 4:** al limpiar un job terminado se borran su directorio y el resultado de `fetch`; un reprocesado vuelve a descargar. La limpieza se hace en cada pasada del servicio.
9. **Destino retirado del YAML:** no para la cola. `classify` descarta los candidatos obsoletos (respaldo `destino_legado`); un job cuyo destino decidido o forzado ya no existe falla solo (`PermanentError` → `jr:error`), no `ConfigError`.
10. **Despliegue:** Tohoku (fases 0-4) se despliega solo cuando termine la importación de Instagram en curso; no habrá jobs legados aparcados en ese momento.

### Task 3.1: Estado — `candidates`, `destination` y `DESCARTADO`

**Files:** `src/tohoku/state.py`, `src/tohoku/models.py`, `src/tohoku/stages/mark.py`, `tests/unit/test_state.py`, `tests/unit/test_ingest_mark.py`

**Interfaces (produce):**
- `Job.candidates: list[str]` y `Job.destination: str | None`.
- `StateStore.add_job(..., candidates: list[str])`.
- `StateStore.set_destination(bookmark_id, destination)`.
- La migración `ALTER TABLE` es idempotente; a los jobs existentes les asigna `candidates=["japon"]` y `destination="japon"` (el nombre del destino de la lista actual).
- `Outcome.DESCARTADO = "descartado"`. Al leer `"no-japon"` se obtiene `DESCARTADO`.
- `OUTCOME_TAGS[DESCARTADO] = "jr:descartado"`.
- `MarkStage.run(bookmark_id, outcome, destination: str | None)` añade `jr:destino:<d>` y considera obsoletas solo las etiquetas `jr:` de resultado o de destino distintas de las nuevas.

**Tests de aceptación:** migración sobre un `state.db` con el esquema viejo; `no-japon` se lee como `DESCARTADO`; al marcar se quitan `jr:no-japon` y el `jr:destino:` anterior pero se conservan las etiquetas que no son `jr:`.

### Task 3.2: Ingest de varias listas

**Files:** `src/tohoku/ingest.py`, `src/tohoku/service.py`, `tests/unit/test_ingest_mark.py`

**Interfaces:** `ingest(karakeep, state, config: DestinationsConfig) -> IngestReport`. Recorre `config.listas`. Si un bookmark aparece en dos listas, sus candidatos se unen (y si el job ya existe y sigue pendiente sin destino, se amplían sus `candidates`).

**Tests de aceptación:** una lista con un destino; dos listas; el mismo bookmark en dos listas → un solo job con la unión de candidatos; 404 de una lista → `ConfigError` que nombra la lista.

### Task 3.3: Clasificador con modos

**Files:**
- Create: `src/tohoku/classify/__init__.py`, `classify/base.py`, `classify/json_schema.py`, `classify/label.py`, `src/tohoku/stages/classify.py`, `src/tohoku/prompts/classify.md`
- Test: `tests/unit/test_classify.py`

**Interfaces (produce):**

```python
class Classification(BaseModel):
    destino: str | None                  # None = ninguno
    confianza: float
    alternativa: str | None = None
    confianza_alternativa: float = 0.0
    cost_usd: float = 0.0
    omitido: bool = False                # True si no hubo llamada (un solo candidato o destino forzado)

class Classifier(Protocol):
    def classify(self, text: str, images: list[Path], candidates: list[Destination]) -> Classification

class ClassifyStage:                     # name = "classify", result_model = Classification
    ...                                  # un candidato → omitido; varios → Classifier; valida destino ∈ candidatos
```

- **`json_schema`:** `response_format` con `enum` de los candidatos más `"ninguno"`.
- **`etiqueta`:** respuesta de texto libre; se normaliza y se busca un candidato exacto.
- **Adaptadores:** un registro `CLASSIFIERS: dict[str, Callable[..., Classifier]]` para añadir el del modelo concreto (JEV) cuando se elija. Es el punto abierto de la spec §3.

**Tests de aceptación:**
- Un candidato → no se llama al LLM.
- Varios candidatos → cada modo con respuestas válidas.
- Destino inventado o fuera de los candidatos → un reintento y luego `TransientError`.
- `ninguno` o confianza < mínima → `destino=None`.
- Alternativa dentro del margen → se conserva para `clasificacion-dudosa`.
- Sin caption ni transcripción → se adjuntan 2 fotogramas.
- El coste se suma al presupuesto `openrouter_usd` y respeta `QuotaExceeded`.

### Task 3.4: Pipeline con destino por job, `reprocess --destino` y `clasificacion-dudosa`

**Files:** `src/tohoku/pipeline.py`, `src/tohoku/service.py` (`REPROCESS_FROM` incluye `classify`), `src/tohoku/cli.py`, las etapas `resolve` de los flujos (motivo `clasificacion-dudosa`), `tests/unit/test_pipeline.py`, `tests/unit/test_wiring_cli.py`

**Comportamiento:**
- Después de `classify`: `destino=None` → `DESCARTADO` (marcar y terminar). Si no, `set_destination` y se ejecutan las etapas del flujo.
- `reprocess --destino recetas <id>` borra los resultados desde `classify`, fija el destino y guarda un `Classification(omitido=True)`.
- `resolve` añade `clasificacion-dudosa` a los elementos si la alternativa estaba dentro del margen.

**Tests de aceptación:** un job descartado por el clasificador se marca `jr:descartado` sin ejecutar `extract`; `reprocess --destino` con un destino desconocido → error claro; `clasificacion-dudosa` llega a `#revisar`.

---

## Fase 4: limpieza en dos niveles

### Task 4.1: Limpieza al terminar y purga por retención

**Files:** `src/tohoku/cleanup.py`, `src/tohoku/pipeline.py` (llama a la limpieza tras `finish` si el resultado no es `ERROR`), `src/tohoku/service.py` (purga una vez por pasada), `src/tohoku/state.py` (`purge_stage_results(older_than) -> int`, `delete_stage(bookmark_id, stage)`), `tests/unit/test_cleanup.py`

**Interfaces:**
- `cleanup_finished_job(state, data_dir, bookmark_id)` borra `data/jobs/<id>/` y el resultado `fetch`.
- `purge_expired(state, retencion_dias) -> int` borra los `stage_results` de jobs `DONE` cuyo `updated_at` sea anterior al límite. `retencion_dias=0` → purga inmediata tras terminar.

**Tests de aceptación:**
- Job `DONE` → sin directorio y sin `fetch`; se conservan `transcribe`/`extract`.
- Job `ERROR` → nada borrado.
- Job `PENDING` (reprocesándose) → nada purgado.
- Tras la purga, `reprocess --from geocode` rehace `fetch`/`transcribe`/`extract`: los Steps falsos cuentan las llamadas.
- `published` y el registro de `jobs` no se tocan nunca.

**Despliegue:** la primera pasada limpia los ~800+ directorios de jobs terminados. Hay que avisar al usuario del espacio liberado (`du -sh data/jobs` antes y después).

---

## Fase 5: flujo `receta`

> **Recibe de la fase 2** (rulings 3 y 5): mover los módulos del viaje a `flows/viaje/`, extraer las utilidades comunes (Task 2.3) y fijar la interfaz `Flow` (`build`/`init_trilium`) con dos flujos reales.

### Task 5.1: Parámetros, estructura en Trilium e `init-trilium --destino recetas`

**Files:** `src/tohoku/flows/receta/{__init__,params,layout}.py`, `tests/unit/test_receta_layout.py`

**Interfaces:**

```python
class RecetaParams(BaseModel):
    vista: Literal["table", "grid", "list"] = "table"
    atributos: dict[str, Literal["text", "number", "boolean"]]    # → promovidos de la plantilla "Receta"
    atributos_usuario: list[str] = ["probada", "valoracion"]      # nunca los escribe el servicio

@dataclass(frozen=True)
class RecetaLayout:
    root: str
    recetario: str      # #jrColeccion, book, #viewType=<vista>
    revision: str
    plantillas: str
    plantilla_receta: str
```

**Tests de aceptación:** `init_trilium` es idempotente (FakeTrilium) y crea el Recetario con `#viewType`, la Bandeja y la plantilla con un promovido por atributo; `check` lanza `ConfigError` si falta alguna pieza.

### Task 5.2: `extract` y `cover`

**Files:** `src/tohoku/flows/receta/{models,extract,cover}.py`, `src/tohoku/prompts/receta.md`, `config/prompts/recetas.md`, `tests/unit/test_receta_extract.py`

**Interfaces:**

```python
class Ingrediente(BaseModel):
    cantidad: str | None = None
    unidad: str | None = None
    ingrediente: str
    nota: str | None = None
    grupo: str | None = None

class RecetaExtraction(BaseModel):
    relacionado_destino: bool
    confianza_destino: float
    titulo: str
    resumen: str
    raciones: int | None = None
    tiempo_min: int | None = None
    dificultad: str | None = None
    tipo_plato: str | None = None
    cocina: str | None = None
    ingredientes: list[Ingrediente] = []
    pasos: list[str] = []
    consejos: list[str] = []
    portada: int | None = None        # índice en imágenes + fotogramas enviados al LLM
    confianza: float

class CoverResult(BaseModel):
    path: str | None = None           # relativa al workdir
```

**Tests de aceptación:**
- La extracción válida y el reintento de esquema reutilizan la utilidad común.
- `portada` fuera de rango → sin portada.
- Post sin `portada` → primera imagen.
- Vídeo sin `portada` → sin portada.
- La imagen se redimensiona al lado máximo configurado.

### Task 5.3: `resolve` y `publish` de recetas

**Files:** `src/tohoku/flows/receta/{resolve,publish,render}.py`, `tests/unit/test_receta_publish.py`

**Comportamiento:**
- Identidad: `#jrItem="<bookmark>:receta:<nombre normalizado>"` y `#jrTipo=receta`.
- Sin fusión entre fuentes.
- Similitud ≥ `cosa_duplicate` → `posible-duplicado`.
- La nota se crea bajo el Recetario con `~template=Receta` y los promovidos rellenos. `probada` y `valoracion` no se escriben nunca.
- Portada: adjunto de imagen incrustado arriba.
- Cuerpo: Resumen, Ingredientes (agrupados), Preparación (numerada), Consejos, Fuentes y Mis notas.
- Bandeja sincronizada con las utilidades comunes.

**Tests de aceptación:**
- Crear.
- Reprocesar el mismo enlace: regenera y conserva "Mis notas" y los atributos corregidos por el usuario.
- `posible-duplicado`.
- Publicar sin portada.
- Idempotencia tras un fallo a medias (el adjunto falla a la primera, como en el test existente de `publish`).

**Verificación de la fase:** integración manual con una nota `#jrRootRecetasTest` y 2-3 Reels de recetas reales (confirmar con el usuario antes: coste de LLM). Comprobar a mano la vista Tabla en Trilium.

---

## Fase 6: Nueva Zelanda solo con configuración

> **Recibe de la fase 2** (rulings 2, 7 y 8): decidir si NZ necesita `palabras_genericas` propias (hoy global), iconos propios (hoy pin genérico) y si se renombran `Thresholds`/`JAPAN_*`.

### Task 6.1: Destino NZ

**Files:** `config/destinos.yaml` (destino `nueva_zelanda`), `config/prompts/nueva_zelanda.md`, `docs/operations.md` ("Cómo añadir un destino")

**Pasos:**
1. El usuario crea "Viaje a Nueva Zelanda" en Trilium con `#jrRootNZ`.
2. `tohoku init-trilium --destino nueva_zelanda`.
3. Lista de Karakeep nueva (o la inbox) en `listas`.
4. Procesar 2-3 enlaces reales (con confirmación).

**Criterio:** ningún cambio en `src/`. Si hace falta alguno, es un fallo de diseño: se corrige en `flows/viaje` y se documenta.

**Tests de aceptación:** un test de configuración que carga un YAML con `japon` y `nueva_zelanda` y comprueba que `in_country(..., "NZ")` y el `name_key` de NZ usan los parámetros del destino.
