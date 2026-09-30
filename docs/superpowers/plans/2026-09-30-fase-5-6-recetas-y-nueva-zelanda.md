# Fases 5 y 6: flujo `receta` y Nueva Zelanda solo con configuración — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Modo acordado con el usuario:** subagentes con **revisión especial de TDD**. Cada tarea declara el RED esperado, y el controlador vuelve a ejecutar los tests nuevos contra el código anterior a la tarea para confirmarlo. Las tareas con acciones sobre servicios reales (Tasks 2, 7 y 9) se paran y piden confirmación al usuario antes de tocar Trilium, Karakeep o el LLM de pago.
>
> **Estado:** preparado, sin ejecutar (el usuario lo lanzará más adelante).

**Goal:**
- **Fase 5:** añadir un segundo flujo real, `receta`. Guarda recetas en un Recetario de Trilium en vista Tabla, con ingredientes, pasos, atributos promovidos e imagen de portada. Reutiliza las piezas comunes del flujo `viaje` sin cambiar su comportamiento.
- **Fase 6:** demostrar que un destino nuevo del flujo `viaje` (Nueva Zelanda) se añade **sin tocar `src/`**.

**Architecture:**
- **Utilidades comunes:** se extraen de `stages/publish.py` y `stages/extract.py` a dos módulos neutros, sin cambiar su comportamiento:
  - `tohoku/publishing.py`: etiquetas, Bandeja y nota de fallo;
  - `tohoku/llm_json.py`: llamada al LLM con esquema y un reintento.
- **Flujo `receta`:** vive en `src/tohoku/flows/receta/` y tiene sus propias etapas `extract → cover → resolve → publish`.
- **Orden de etapas:** `STAGE_ORDER` pasa a ser el orden canónico de **todas** las etapas conocidas (`… geocode, cover, resolve, publish`), para que `reprocess --from X` borre bien en cualquiera de los dos flujos.
- **Nueva Zelanda:** es YAML, un prompt y documentación.

**Tech Stack:** Python 3.12, uv, Pydantic v2, Pillow, Trilium ETAPI (v0.106), OpenRouter, pytest, respx.

**Spec:** `docs/superpowers/specs/2026-09-30-multi-destino-design.md` (§6.3 receta, criterio de éxito 1 y 2) · **Hoja de ruta:** `docs/superpowers/plans/2026-09-30-fases-2-6-multidestino.md` (fases 5 y 6, con las decisiones de las fases 2 a 4).

**Rama:** `feat/tohoku`, encima de `4b2c791` (fases 0 a 4 listas, sin desplegar). No se integra ni se despliega sin el usuario.

## Global Constraints

- Español en docs, docstrings y mensajes. **Nunca** crear, editar ni mostrar `.env`.
- TDD sin red. `uv run pytest -q` en verde al final de cada tarea, con el recuento real.
- **El flujo `viaje` (Japón) no cambia:**
  - los tests existentes pasan sin cambiar aserciones;
  - la única excepción es `test_build_app_orders_stages` (Task 1), porque `STAGE_ORDER` pasa a incluir `cover`, que no es de `viaje`;
  - las líneas base de `tests/unit/test_baseline.py` siguen en verde.
- **Prefijo `jr`** para todo lo generado: `#jrTipo=receta`, `#jrItem`, `#jrColeccion`, raíz `jrRootRecetas` / `jrRootRecetasTest`.
- **"Mis notas" y los atributos del usuario** (`probada`, `valoracion` y cualquier otro que se añada a mano) no se sobrescriben nunca.
- Commits en `feat/tohoku`, con el mensaje terminado en `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Servicios reales:** crear notas de prueba en Trilium, usar listas de Karakeep o procesar enlaces reales requiere la **confirmación explícita del usuario** en ese momento. Nunca se tocan las notas de Japón.

## Decisiones de este plan (rulings)

1. **No se mueven los módulos del viaje a `flows/viaje/`** (roadmap, ruling 3 de la fase 2).
   - Mover `stages/{extract,geocode,resolve,publish}.py`, `geo.py`, `trilium_layout.py` y `notes.py` cambiaría cientos de imports sin ganar comportamiento.
   - Solo se extrae lo que `receta` reutiliza, a módulos neutros: `publishing.py` y `llm_json.py`.
   - Coste: la asimetría de que `viaje` viva en `stages/` y `receta` en `flows/receta/`, anotada en `docs/operations.md`.
2. **`STAGE_ORDER` canónico:** `("fetch", "transcribe", "classify", "extract", "geocode", "cover", "resolve", "publish")`. `clear_stages_from` borra desde X todas las etapas posteriores de ese orden, aunque el flujo del job no las tenga (no pasa nada). `REPROCESS_FROM` no cambia.
3. **Sin fusión entre fuentes** en recetas (spec §6.3). La identidad es `#jrItem="<bookmark>:receta:<name_key(titulo)>"`. Si ya existe una receta de título parecido, la nota nueva va a la Bandeja como `posible-duplicado`.
4. **Atributos:**
   - `RecetaParams.atributos` define los atributos promovidos de la plantilla `Receta`.
   - El servicio solo **escribe** los que son campos de `RecetaExtraction` (`tipo_plato`, `cocina`, `tiempo_min`, `raciones`, `dificultad`), y con la regla de `sync_labels`: los que el usuario haya corregido se respetan.
   - `atributos_usuario` (`probada`, `valoracion` por defecto) no se escriben nunca.
5. **Portada:**
   - Se sube como adjunto de imagen (`role=image`, JPEG, lado máximo `IMAGE_MAX_SIDE`) y se incrusta al principio del cuerpo.
   - El formato exacto del `<img src=…>` de Trilium 0.106 **se verifica en la Task 2** (spike con confirmación) antes de fijarlo en el render.
6. **Nueva Zelanda sin tocar `src/`** (roadmap, rulings 2, 7 y 8 de la fase 2):
   - `palabras_genericas` sigue siendo global (quitar "japan"/"japon" de un nombre neozelandés no hace daño);
   - los iconos siguen siendo el pin genérico para categorías sin icono;
   - `Thresholds`/`JAPAN_*_CONFIDENCE` no se renombran, porque renombrarlos obligaría a editar `.env`;
   - si al procesar enlaces reales de NZ algo de esto molesta, se abre una tarea aparte.

## Review Focus

1. **`reprocess --from extract` de una receta:** debe borrar también `cover` (orden canónico) y volver a descargar si los ficheros se limpiaron. Test en la Task 1 (orden) y en la Task 6 (flujo completo con Steps).
2. **Receta reprocesada después de que el usuario editara la nota:** se regenera el cuerpo generado y se conservan "Mis notas", `probada`, `valoracion` y cualquier atributo corregido. Test en la Task 5.
3. **Portada que falla al subir:** es un error pasajero con reintento, y el reintento no duplica ni la nota ni la portada (idempotencia por `#jrItem` y por título del adjunto). Test en la Task 5.
4. **Un Reel que no es una receta, en una lista de recetas:** `DESCARTADO`, sin nota y sin `jr:destino`. Test en la Task 6.
5. **YAML con los destinos `japon`, `recetas` y `nueva_zelanda`:** cada lista usa el flujo correcto, los jobs de un solo candidato no llaman al clasificador, y el preflight exige el modelo del clasificador (hay varios destinos en total, corrección I1 de la fase 3). Test en las Tasks 6 y 8.

---

## Fase 5

### Task 1: Utilidades comunes y orden canónico de etapas (refactor, sin cambio en `viaje`)

**Files:**
- Create: `src/tohoku/publishing.py`, `src/tohoku/llm_json.py`, `tests/unit/test_publishing.py`, `tests/unit/test_llm_json.py`
- Modify: `src/tohoku/stages/publish.py` (usa `publishing`; `upsert_labels` y `sync_labels` se reexportan para no romper imports), `src/tohoku/stages/extract.py` (usa `llm_json.structured_call`), `src/tohoku/pipeline.py` (`STAGE_ORDER`), `src/tohoku/rules.py` (`destination_decision` acepta cualquier objeto con `confianza_destino`), `tests/unit/test_wiring_cli.py` (`test_build_app_orders_stages`)

**Interfaces (produce):**

```python
# publishing.py
def upsert_labels(trilium, note: TNote, labels: dict[str, str]) -> None            # movido tal cual
def sync_labels(trilium, note: TNote, labels, old_labels, always: frozenset[str] = ALWAYS_WRITTEN_LABELS) -> None
def sync_review(trilium, state, note_id: str, reasons: list[str], bookmark_id: str, item_key: str, revision_id: str) -> None
    # el cuerpo de PublishStage._sync_review, sin depender de Layout ni de PlannedItem
def create_failure_note(trilium, root_id: str, revision_id: str, bookmark_id: str, meta: SourceMeta, transcript: str, error: str) -> str
    # el cuerpo de PublishStage._create_failure

# llm_json.py
@dataclass
class StructuredResult[T]:
    value: T | None
    error: str
    cost_usd: float

def structured_call[T](llm, budget, model: str, messages: list[dict], schema: dict, name: str,
                       parse: Callable[[str], T], check: Callable[[T], list[str]] = lambda _v: []) -> StructuredResult[T]
    # dos intentos: budget.check(), chat_json, budget.add, strip_fences + parse (ValidationError → problema),
    # check(); si hay problemas, reintento con el mismo mensaje de corrección que hoy usa ExtractStage.

# pipeline.py
STAGE_ORDER = ("fetch", "transcribe", "classify", "extract", "geocode", "cover", "resolve", "publish")
```

- [ ] **Step 1: Tests (RED).**
  - `test_publishing.py`:
    - `sync_review` con los mismos casos que hoy prueba `test_publish.py` a través de `PublishStage`: entra en la Bandeja, se actualiza `#revisar`, sale al resolverse los motivos, y respeta una nota que el usuario ya sacó;
    - `create_failure_note` crea la nota o la retoma por `#jrItem="<id>:fallo"`.
  - `test_llm_json.py`: respuesta válida a la primera; inválida y luego válida (el segundo mensaje contiene "La respuesta no cumple el esquema"); `check` con problemas provoca un reintento; dos respuestas inválidas dan `value=None` y `error`; el coste de las dos llamadas se suma al presupuesto; `QuotaExceeded` antes de llamar.
  - `test_wiring_cli.py::test_build_app_orders_stages`: su aserción pasa a comparar con `list(COMMON_STAGES) + ["extract", "geocode", "resolve", "publish"]`. Es el único cambio de aserción (ver Global Constraints).
  - Test nuevo en `test_service.py`: `clear_stages_from(…, "extract", STAGE_ORDER)` sobre un job con resultados `extract`, `cover` y `publish` borra los tres.
  - Expected RED: `ModuleNotFoundError: tohoku.publishing` / `tohoku.llm_json`; el orden de etapas no contiene `cover`.
- [ ] **Step 2: Implementación.**
  - Mover el código tal cual. `PublishStage._sync_review` y `_create_failure` pasan a llamar a las funciones nuevas.
  - `ExtractStage.run` usa `structured_call(parse=Extraction.model_validate_json, check=lambda e: invalid_categories(e, self._params))` y conserva su log.
- [ ] **Step 3: GREEN.** `test_publish.py`, `test_extract.py` y `test_baseline.py` pasan **sin cambios**, y la suite completa también.
- [ ] **Step 4: Commit** `refactor: shared publishing and structured LLM helpers; canonical stage order`.

### Task 2: Adjuntos de imagen en Trilium (con spike real, previa confirmación)

**Files:**
- Modify: `src/tohoku/clients/trilium.py` (`create_image_attachment`), `tests/fakes.py` (`FakeTrilium.create_image_attachment`)
- Test: `tests/unit/test_trilium_client.py`

**Interfaces (produce):**

```python
def create_image_attachment(self, owner_id: str, title: str, data: bytes, mime: str = "image/jpeg") -> str:
    """Crea un adjunto role=image y sube su contenido binario. Devuelve attachmentId."""
def image_src(attachment_id: str, title: str) -> str:   # en tohoku/clients/trilium.py; formato verificado en el Step 3
```

- [ ] **Step 1: Tests (RED)** con respx:
  - primero va `POST /attachments` con `role=image`, `mime=image/jpeg` y `content=""`;
  - después va `PUT /attachments/{id}/content` con el cuerpo binario y `Content-Type: application/octet-stream`;
  - devuelve el id.

  `FakeTrilium` guarda `data` como `bytes`.
- [ ] **Step 2: Implementación** mínima.
- [ ] **Step 3: Spike real (PARAR y pedir confirmación al usuario antes).**
  - Hay que tener una nota de prueba bajo `#jrRootTest`; si no existe, el usuario la crea.
  - Desde el host (`TRILIUM_URL=http://localhost:8750`), con un script en el scratchpad que lee el token con `dotenv_values` sin imprimirlo:
    1. crear una nota hija;
    2. subir una imagen de prueba con `create_image_attachment`;
    3. poner como contenido `<p><img src="{image_src(...)}"></p>`, probando primero `api/attachments/<id>/image/<title>`;
    4. el usuario comprueba en Trilium que la imagen se ve en la nota y en una colección en Cuadrícula y en Tabla.
  - Anotar el formato que funciona en el ledger (*ruling*) y fijarlo en `image_src`, con su test.
  - Borrar la nota de prueba (con confirmación).
- [ ] **Step 4: Commit** `feat(trilium): image attachments (binary upload) and image src helper`.

### Task 3: Parámetros, estructura en Trilium y `init-trilium` de recetas

**Files:**
- Create: `src/tohoku/flows/receta/__init__.py`, `flows/receta/params.py`, `flows/receta/layout.py`, `tests/unit/test_receta_layout.py`

**Interfaces (produce):**

```python
class RecetaParams(BaseModel):                     # extra="forbid", frozen
    vista: Literal["table", "grid", "list"] = "table"
    atributos: dict[str, Literal["text", "number", "boolean"]] = {
        "tipo_plato": "text", "cocina": "text", "tiempo_min": "number", "raciones": "number",
        "dificultad": "text", "probada": "boolean", "valoracion": "number",
    }
    atributos_usuario: list[str] = ["probada", "valoracion"]
    # validación: nombres de atributo que sean etiquetas válidas de Trilium; atributos_usuario ⊆ atributos

@dataclass(frozen=True)
class RecetaLayout:
    root: str; recetario: str; revision: str; plantillas: str; plantilla_receta: str

def resolve_receta_layout(trilium, root_label: str) -> RecetaLayout         # ConfigError "…ejecuta 'tohoku init-trilium --destino …'"
def init_receta_layout(trilium, root_label: str, params: RecetaParams) -> RecetaLayout   # idempotente
```

**Estructura que crea:**
- Recetario: `book` con `#jrColeccion` y `#viewType=<vista>`. La plantilla `Receta` no se pone en el Recetario: `publish` la asigna (`~template`) a cada nota al crearla, igual que hace `viaje`.
- Bandeja de revisión (`#jrRevision`).
- Plantillas (`#jrPlantillas`) con `Receta` (`#template`) y un `label:<atributo>=promoted,single,<tipo>` por cada entrada de `atributos`.

Reutilizar `_find_one` y `_root` de `trilium_layout.py` (importarlos; si son privados, hacerlos públicos con un alias; es un cambio de nombre, no de comportamiento).

- [ ] **Step 1: Tests (RED)** con `FakeTrilium`:
  - `init` crea todo con los atributos indicados;
  - `init` dos veces no duplica nada;
  - `resolve` antes de `init` → `ConfigError` que menciona `init-trilium`;
  - `vista="grid"` → `#viewType=grid`;
  - un atributo con un nombre inválido (`"tiempo min"`) → error de validación de `RecetaParams`;
  - `atributos_usuario` con un nombre que no está en `atributos` → error.
- [ ] **Step 2: Implementación. Step 3: GREEN. Step 4: Commit** `feat(receta): params and Trilium recipe book layout`.

### Task 4: `extract` y `cover` de recetas

**Files:**
- Create: `src/tohoku/flows/receta/models.py`, `flows/receta/extract.py`, `flows/receta/cover.py`, `config/prompts/recetas.md`, `tests/unit/test_receta_extract.py`

**Interfaces (produce):**
- `Ingrediente`, `RecetaExtraction` y `CoverResult`, como en la hoja de ruta (fase 5, Task 5.2).
- `RecetaExtractResult(extraction: RecetaExtraction | None, error: str | None, cost_usd: float)`.
- `RecetaExtractStage(settings, llm, budget, system_prompt)`, con `name="extract"`, `result_model=RecetaExtractResult` y `needs_files=True`:
  - usa `structured_call`;
  - el modelo es `OPENROUTER_MODEL` si hay imágenes y `text_model` si no, como en `viaje`;
  - las imágenes son las del post más los fotogramas, en ese orden. `portada` es un índice en esa lista.
- `CoverStage(settings)`, con `name="cover"`, `result_model=CoverResult` y `needs_files=True`:
  - `portada` válida → esa imagen;
  - post sin `portada` → la primera imagen;
  - vídeo sin `portada`, o índice fuera de rango → `None`;
  - redimensiona con `media.images.resize_image` a `data/jobs/<id>/cover.jpg` con `IMAGE_MAX_SIDE`.
- `config/prompts/recetas.md`: prompt completo en español para extraer recetas (qué es una receta, cantidades con unidad, pasos en orden, grupos de ingredientes, "no inventes", `portada` = índice del fotograma o imagen donde se ve el plato terminado), con `relacionado_destino`/`confianza_destino` = "¿es una receta de cocina?".

- [ ] **Step 1: Tests (RED):**
  - extracción válida (el esquema enviado es `RecetaExtraction.model_json_schema()`);
  - reintento de esquema reutilizando `structured_call`;
  - modelo de visión con imágenes y de texto sin ellas;
  - la lista de imágenes enviada sigue el orden post + fotogramas;
  - los casos de portada de la hoja de ruta: fuera de rango → `None`; post sin portada → la primera; vídeo sin portada → `None`; la imagen resultante mide como máximo `IMAGE_MAX_SIDE` (con `make_image` de 2000×1500);
  - presupuesto agotado → `QuotaExceeded`.
- [ ] **Step 2: Implementación. Step 3: GREEN. Step 4: Commit** `feat(receta): recipe extraction and cover image stages`.

### Task 5: `resolve`, `render` y `publish` de recetas

**Files:**
- Create: `src/tohoku/flows/receta/resolve.py`, `flows/receta/render.py`, `flows/receta/publish.py`, `tests/unit/test_receta_publish.py`

**Interfaces (produce):**
- `RecetaResolveStage(trilium, layout, thresholds)`, con `name="resolve"`, que devuelve `ResolveResult` (reutiliza `PlannedItem`: `kind` nuevo `ItemKind.RECETA = "receta"`, que se añade a `models.ItemKind`):
  - con `extraction=None` → un elemento `FALLO` con `extraccion-fallida`;
  - con `destination_decision == "no"` → sin elementos;
  - motivos: `clasificacion-incierta` (relevancia dudosa), `clasificacion-dudosa` (del resultado de `classify`), `baja-confianza` (`confianza < item_review`), `posible-duplicado` (similitud ≥ `cosa_duplicate` con el `#jrNombreNorm` de otra receta bajo la raíz).
- `RecetaData(BaseModel)`: `kind="receta"`, `titulo`, `resumen`, `raciones`, `tiempo_min`, `dificultad`, `tipo_plato`, `cocina`, `ingredientes`, `pasos`, `consejos`, `fuentes: list[SourceEntry]` y `portada_adjunto: str | None`. Se guarda en el adjunto `japan-reader.json` con `dump_data`/`load_data` propios del flujo (el discriminador `kind` no choca con el de `viaje`).
- `render_receta(data, image_src: str | None) -> str`: portada `<p><img …></p>`, Resumen, Ingredientes (una lista por `grupo`, en el orden de aparición), Preparación (`<ol>`), Consejos y Fuentes (mismo formato que `notes._sources`; reutilizarlo). "Mis notas" la añade `compose_content`.
- `RecetaPublishStage(trilium, layout, settings, state)`, con `name="publish"` y resultado `PublishResult`:
  - **Crear o retomar por `#jrItem`:**
    1. crear la nota bajo el Recetario con `#jrItem`;
    2. subir la portada si hay `CoverResult.path` (título fijo `portada.jpg`; si ya existe un adjunto con ese título, se reutiliza);
    3. escribir contenido, atributos (`jrTipo=receta`, `jrNombreNorm`, `fuentes`, `iconClass=bx bx-bowl-rice` y los campos de receta como etiquetas de los promovidos), `~template` y el adjunto de datos;
    4. sincronizar la Bandeja (`publishing.sync_review`).
  - **Reprocesado del mismo enlace:** regenera los datos y el cuerpo, conserva "Mis notas", aplica `sync_labels` con los atributos anteriores (así respeta las correcciones) y **nunca** escribe `atributos_usuario`.
  - `FALLO` → `publishing.create_failure_note`.
  - El resultado sale de `decide_outcome`.

- [ ] **Step 1: Tests (RED)** con `FakeTrilium` y un `StateStore` temporal:
  - crear (padre = Recetario, plantilla, etiquetas, portada incrustada con el `image_src` de la Task 2, orden de las secciones);
  - ingredientes agrupados;
  - publicar sin portada;
  - **Review Focus 2:** el usuario edita "Mis notas", pone `#probada=true` y corrige `#cocina` → al reprocesar se conservan esos tres y se actualiza el resto;
  - `posible-duplicado` → Bandeja con `#revisar`;
  - **Review Focus 3:** subir la portada falla a la primera (`TransientError`) y el reintento no duplica la nota ni la portada;
  - `FALLO` → nota de fallo en la Bandeja;
  - relevancia "no" → `DESCARTADO` sin notas.
- [ ] **Step 2: Implementación. Step 3: GREEN. Step 4: Commit** `feat(receta): recipe resolve, render and publish`.

### Task 6: `RecetaFlow`, registro, cableado y documentación

**Files:**
- Create: `src/tohoku/flows/receta/flow.py`, `docs/flujos/receta.md` (qué hace, estructura en Trilium, etapas, configuración, fallos, cómo probarlo), `tests/unit/test_flow_receta.py`
- Modify: `src/tohoku/flows/registry.py` (`"receta": RecetaFlow()`), `config/destinos.yaml` (bloque `recetas` **comentado**, con su lista y `destino_legado: japon`), `docs/operations.md` (cómo activar Recetas; asimetría `stages/` y `flows/receta/`), `docs/trilium-model.md` (sección Recetario y nota Receta), `docs/pipeline/02b-classify.md` (ejemplo con dos flujos), `CLAUDE.md` (Estado), hoja de ruta (rulings de este plan)

**Interfaces (produce):** `RecetaFlow` con `name="receta"`, `params_model=RecetaParams`:
- `build(dest, deps) -> RecetaRuntime(stages=[extract, cover, resolve, publish], layout=LayoutCache(...))`, con `refresh()`;
- `init_trilium(trilium, dest) -> str` ("Estructura lista. Recetario=… Revisión=…").

- [ ] **Step 1: Tests (RED):**
  - `FLOWS["receta"]` existe;
  - `build` da las etapas `["extract", "cover", "resolve", "publish"]`;
  - `init_trilium` con `FakeTrilium`;
  - **Review Focus 5:** `build_app` con una fixture YAML de `japon` (lista L1) más `recetas` (lista L2) → `app.runtimes` tiene los dos flujos, hay clasificador (unión de destinos) y un job de L2 tiene candidatos `["recetas"]`;
  - **Review Focus 1:** pipeline con `flows={"recetas": [Steps extract/cover/resolve/publish]}` y `reprocess --from extract` → se vuelven a ejecutar `extract` y `cover`;
  - **Review Focus 4:** relevancia "no" en una receta → `DESCARTADO` y `mark` sin destino.
- [ ] **Step 2: Implementación y docs. Step 3: GREEN. Step 4: Commit** `feat(receta): recipe flow registered and documented`.

### Task 7: Integración real de Recetas (con el usuario)

**PARAR y pedir confirmación** antes de cada paso:
1. El usuario crea en Trilium la nota "Recetas (test)" con `#jrRootRecetasTest` y, si quiere, una lista de Karakeep de prueba.
2. Con una copia de `config/destinos.yaml` fuera del repo (en el scratchpad), apuntar `recetas` a `jrRootRecetasTest` y ejecutar `init-trilium --destino recetas` con esa configuración (contenedor de prueba `tohoku:fase56`, **sin tocar producción**).
   - Montar la copia en `/app/config` con `-v`.
   - **No** usar `docker run --env-file .env`: Docker no quita los comentarios en línea. Generar un fichero temporal con `dotenv_values`, sin imprimirlo, y borrarlo al terminar.
   - `DATA_DIR` a un directorio temporal.
3. Procesar 2-3 Reels de recetas reales que elija el usuario (coste de LLM estimado: < 0,01 $): `run-once` en el contenedor de prueba con un `DATA_DIR` temporal.
4. El usuario revisa en Trilium la vista Tabla (columnas promovidas), la Cuadrícula (portada) y una nota (ingredientes, pasos, "Mis notas").
5. Anotar el resultado en `CLAUDE.md` y limpiar (la nota de prueba la conserva o la borra el usuario).

---

## Fase 6

### Task 8: Nueva Zelanda como configuración (sin tocar `src/`)

**Files:**
- Create: `config/prompts/nueva_zelanda.md`, `tests/fixtures/destinos_tres.yaml`, `tests/unit/test_destino_nz.py`
- Modify: `config/destinos.yaml` (bloque `nueva_zelanda` **comentado**), `docs/operations.md` (sección "Cómo añadir un destino", paso a paso), hoja de ruta (decisión 6 de este plan)

**`config/prompts/nueva_zelanda.md`:** una copia adaptada de `japon.md`:
- viaje a Nueva Zelanda; ciudades Auckland, Wellington, Queenstown, Christchurch, Rotorua…; regiones Isla Norte / Isla Sur;
- nombres locales en maorí si aparecen;
- los mismos campos y los marcadores `{{categorias_lugar}}` / `{{categorias_cosa}}`.

**Bloque YAML (comentado en producción; activo en la fixture):**

```yaml
  nueva_zelanda:
    flujo: viaje
    raiz: jrRootNZ
    descripcion: "Viaje a Nueva Zelanda: naturaleza, rutas, pueblos, comida y cultura de Nueva Zelanda"
    prompt: prompts/nueva_zelanda.md
    pais: NZ
    nombres_pais: [new zealand, nueva zelanda, aotearoa]
    latitud: [-47.5, -34.0]
    longitud: [166.0, 179.0]
    categorias_lugar: [naturaleza, ruta, mirador, pueblo, playa, comida, cafe, bar, museo, alojamiento, transporte, otro]
    categorias_cosa: {souvenirs: Souvenirs, comida: Comida, otros: Otros}
    alias_ciudad: {auckland: [tamaki makaurau], wellington: [te whanganui-a-tara], christchurch: [otautahi]}
```

- [ ] **Step 1: Tests (RED: falla la carga porque no existe `config/prompts/nueva_zelanda.md`).** `test_destino_nz.py` carga `destinos_tres.yaml` (`japon` + `recetas` + `nueva_zelanda`) y comprueba:
  - los parámetros de NZ;
  - que el prompt de NZ renderiza sus categorías;
  - `in_country(SKY_TOWER, "NZ", …)` y el rechazo de un resultado de Japón;
  - que la clave de caché de Places de NZ lleva el prefijo `NZ|`;
  - que `init_trilium` de NZ crea la estructura bajo `#jrRootNZ` con sus categorías de cosa;
  - que un job de la lista de NZ con un solo candidato no llama al clasificador.
- [ ] **Step 2:** solo configuración, el prompt y la documentación. **Criterio:** `git diff --stat -- src/` vacío. Si algo exige tocar `src/`, se para y se reporta como fallo de diseño (spec, criterio de éxito 1).
- [ ] **Step 3: GREEN. Step 4: Commit** `feat(config): New Zealand destination (configuration only)`.

### Task 9: Nueva Zelanda real (con el usuario)

**PARAR y pedir confirmación** antes de cada paso:
1. El usuario crea "Viaje a Nueva Zelanda" en Trilium con `#jrRootNZ` y una lista de Karakeep para NZ (o decide usar una inbox con varios destinos).
2. Descomentar el bloque en `config/destinos.yaml` con el id real de la lista (es la configuración de producción: solo después de desplegar Tohoku y con el visto bueno del usuario).
3. `tohoku init-trilium --destino nueva_zelanda`.
4. Procesar 2-3 enlaces reales de NZ y revisar el Geo Map de NZ y la Bandeja.
5. Decidir con los resultados si hace falta algo de la decisión 6 (palabras genéricas, iconos). Si hace falta, es una tarea aparte.
