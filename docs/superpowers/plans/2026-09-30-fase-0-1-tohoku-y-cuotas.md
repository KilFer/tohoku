# Fases 0 y 1: renombrado a Tohoku y cola que no se para por cuota — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Renombrar el proyecto `japan-reader` → **Tohoku** sin tocar datos reales ni el prefijo `jr`, y hacer que una cuota diaria agotada aparque solo los jobs que la necesitan en vez de detener toda la pasada.

**Architecture:**
- **Fase 0** es un renombrado mecánico: paquete, CLI, Docker, textos y docs. Se mantienen los identificadores que ya viven en Karakeep, Trilium y `state.db`.
- **Fase 1** cambia `Pipeline.run_due`. Un `QuotaExceeded` aparca ese job hasta el reinicio de la cuota y la pasada continúa. No hace falta que las etapas declaren sus cuotas porque `DailyQuota.check()` solo lee un contador local:
  - un job que llega a `geocode` con la cuota agotada se aparca sin llamar a Google;
  - un job cuyas búsquedas están todas en caché termina igualmente;
  - las etapas sin cuota (`fetch`, `transcribe`) siguen avanzando.

**Tech Stack:** Python 3.12, uv, pytest, respx, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-30-multi-destino-design.md` (§4 "Cuotas por clave", §9 fases 0-1, §11 renombrado).

## Global Constraints

- Idioma de docs, docstrings y mensajes: español. Identificadores de código: como el código existente.
- **Nunca** crear, editar ni mostrar `.env`.
- TDD: test primero, sin red. `uv run pytest -q` en verde al final de cada tarea.
- Commits en `master` local. Cada mensaje termina con `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Prefijo `jr` intocable:** etiquetas `jr:*` de Karakeep, atributos `#jr*` de Trilium, `jrRoot`, y el adjunto `japan-reader.json` (`DATA_ATTACHMENT_TITLE`) se mantienen exactamente igual. Es un homenaje intencionado (Japan Reader / JR, Tohoku Shinkansen).
- Acciones sobre servicios reales (parar o levantar el contenedor, mover el directorio) se confirman con el usuario antes y se hacen entre tandas de la importación.
- Docs históricos que **no** se editan: `docs/superpowers/plans/2026-09-28-japan-reader.md` y el cuerpo de `docs/superpowers/specs/2026-09-28-japan-reader-design.md` (solo se le añade una nota de renombrado arriba).

## Review Focus

1. **Adjunto `japan-reader.json` renombrado por un reemplazo masivo:** las fusiones dejarían de encontrar los datos de ~500 notas. Test en la Tarea 0.1 que fija `DATA_ATTACHMENT_TITLE == "japan-reader.json"`.
2. **Volumen de modelos:** si Compose crea `tohoku_whisper-models` vacío, el primer job descarga ~3 GB. La Tarea 0.2 lo declara `external` con el nombre existente y la verificación de la Tarea 0.4 comprueba que no hay descarga.
3. **Contenedor viejo huérfano:** si `japan-reader` sigue corriendo al levantar `tohoku`, los dos procesan la cola a la vez con locks distintos (`japan-reader.lock` y `tohoku.lock`). La Tarea 0.4 para el viejo antes y comprueba con `docker ps`.
4. **Todos los jobs agotan la cuota en la misma pasada:** hay que aparcarlos todos con un solo aviso ntfy. Test en la Tarea 1.2.
5. **Cuota agotada en `publish` a mitad de un job con varias notas:** al reanudar no se duplican notas, porque `published` hace el reprocesado idempotente, igual que hoy. Test en la Tarea 1.2 de que el job aparcado reanuda desde la etapa donde se quedó.

---

## Fase 0: renombrado a Tohoku

### Task 0.1: Paquete, CLI y textos

**Files:**
- Move: `src/japan_reader/` → `src/tohoku/` (`git mv`)
- Modify: `pyproject.toml`, `uv.lock` (regenerado), `Dockerfile:21`
- Modify: todos los `import japan_reader…` / `from japan_reader…` en `src/` y `tests/`
- Modify: `src/tohoku/errors.py` (`JapanReaderError` → `TohokuError`) y sus usos
- Modify: `src/tohoku/cli.py:20`, `src/tohoku/clients/openrouter.py:42`, `src/tohoku/lock.py:6`, `src/tohoku/pipeline.py:87,109`, `src/tohoku/service.py:58,65,69,82`
- Modify: `tests/unit/test_service.py:116`, `tests/unit/test_wiring_cli.py:166`, `tests/unit/test_ntfy.py:13,16`
- Modify: `tests/unit/test_notes.py` (test nuevo)

**Interfaces:**
- Produces: paquete `tohoku`; script `tohoku` (`tohoku.cli:app`); `tohoku.errors.TohokuError` (base de todos los errores); `LOCK_NAME = "tohoku.lock"`; títulos de ntfy con el prefijo `"tohoku: "`.
- Se mantiene: `tohoku.notes.DATA_ATTACHMENT_TITLE == "japan-reader.json"`.

- [ ] **Step 1: Test que fija lo que NO se renombra**

Añadir al final de `tests/unit/test_notes.py` (con el import que ya existe en ese fichero, todavía `japan_reader`):

```python
def test_data_attachment_title_is_kept_after_rename():
    """El adjunto de ~500 notas ya existentes se llama así: renombrarlo rompería las fusiones."""
    from japan_reader.notes import DATA_ATTACHMENT_TITLE

    assert DATA_ATTACHMENT_TITLE == "japan-reader.json"
```

Run: `uv run pytest tests/unit/test_notes.py -q`
Expected: PASS (protege contra el reemplazo masivo del paso siguiente).

- [ ] **Step 2: Mover el paquete y reescribir los imports**

```bash
git mv src/japan_reader src/tohoku
grep -rl "japan_reader" src tests | xargs sed -i 's/\bjapan_reader\b/tohoku/g'
grep -rl "JapanReaderError" src tests | xargs sed -i 's/\bJapanReaderError\b/TohokuError/g'
```

Comprobar: `git grep -n "japan_reader\|JapanReaderError" -- src tests` → sin resultados.

- [ ] **Step 3: pyproject, Dockerfile y lock**

En `pyproject.toml`:

```toml
name = "tohoku"
description = "De Karakeep a Trilium: notas estructuradas a partir de Shorts, Reels y posts"
...
[project.scripts]
tohoku = "tohoku.cli:app"
...
packages = ["src/tohoku"]
```

En `Dockerfile`, la última línea:

```dockerfile
CMD ["tohoku", "run"]
```

Run: `uv lock && uv sync`
Expected: `uv.lock` actualizado con `name = "tohoku"`; `uv run tohoku --help` muestra la ayuda.

- [ ] **Step 4: Textos visibles**

Sustituciones exactas. **No** usar un `sed` global sobre `japan-reader`: rompería `japan-reader.json`.

- `src/tohoku/cli.py:20`: `help="tohoku: de Karakeep a Trilium (notas a partir de Shorts, Reels y posts)."`
- `src/tohoku/clients/openrouter.py:42`: `"X-Title": "tohoku"`
- `src/tohoku/lock.py:6`: `LOCK_NAME = "tohoku.lock"`
- `src/tohoku/pipeline.py`: `"tohoku: límite diario alcanzado"`, `"tohoku: error"`
- `src/tohoku/service.py`: `"tohoku en marcha; sondeo cada %d min"`, `"tohoku: error de configuración"`, `"tohoku: error en el ciclo"`, `"tohoku: resumen del día"`
- `src/tohoku/notes.py:10`: se queda como está, con un comentario encima:

```python
# Nombre histórico (japan-reader): lo llevan todas las notas ya publicadas. No cambiar.
DATA_ATTACHMENT_TITLE = "japan-reader.json"
```

Tests que cambian con los textos:
- `tests/unit/test_service.py:116`: `("tohoku: resumen del día", "procesado: 1")`
- `tests/unit/test_wiring_cli.py:166`: `"tohoku.lock"`
- `tests/unit/test_ntfy.py:13,16`: `"tohoku: error"`
- `tests/unit/test_notes.py`: el import del test del Step 1 ya dice `tohoku.notes` tras el Step 2.

Comprobar lo que queda: `git grep -n "japan-reader" -- src tests`. Solo deben salir `DATA_ATTACHMENT_TITLE`, su comentario y los tests de `japan-reader.json` (`test_trilium_client.py`, `test_publish.py`, `test_notes.py`).

- [ ] **Step 5: Suite completa**

Run: `uv run pytest -q`
Expected: todo en verde (mismo número de tests que antes + 1).

- [ ] **Step 6: Commit**

```bash
git add -A src tests pyproject.toml uv.lock Dockerfile
git commit -m "refactor: rename package japan_reader to tohoku (keep jr prefix and japan-reader.json)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 0.2: Docker Compose y `.env.example`

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example:13,37`

**Interfaces:**
- Produces: proyecto Compose `tohoku`, servicio `tohoku`, imagen `tohoku:local`, contenedor `tohoku`, y el volumen existente `japan-reader_whisper-models` reutilizado.

- [ ] **Step 1: Escribir el compose**

```yaml
name: tohoku

services:
  tohoku:
    build: .
    image: tohoku:local
    container_name: tohoku
    restart: unless-stopped
    env_file: .env
    environment:
      DATA_DIR: /data
      WHISPER_DOWNLOAD_ROOT: /models
      TZ: Europe/Madrid
    volumes:
      - ./data:/data
      - whisper-models:/models
      - ./secrets:/secrets:ro
    networks:
      - pangolin
    deploy:
      resources:
        limits:
          cpus: "6"
          memory: 6g

networks:
  pangolin:
    external: true

volumes:
  whisper-models:
    # Creado cuando el proyecto se llamaba japan-reader; contiene large-v3 (~3 GB). En una instalación
    # nueva: `docker volume create japan-reader_whisper-models`.
    external: true
    name: japan-reader_whisper-models
```

- [ ] **Step 2: `.env.example`**

- Línea 13: `` `japan-reader eval` `` → `` `tohoku eval` ``.
- Línea 37: `NTFY_TOPIC=tohoku`. El `.env` real no se toca: su topic sigue siendo `kamo`.

- [ ] **Step 3: Validar sin levantar nada**

Run: `docker compose config --quiet && docker compose config | grep -n "name: tohoku\|japan-reader_whisper-models\|container_name"`
Expected: sin errores; `name: tohoku`, `container_name: tohoku` y `name: japan-reader_whisper-models`.

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml .env.example
git commit -m "build: compose project tohoku reusing the existing whisper-models volume

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 0.3: Documentación

**Files:**
- Modify: `README.md`, `CLAUDE.md`, `docs/operations.md`, `docs/pipeline/01-ingest.md` … `08-mark.md`, `docs/trilium-model.md`, `eval/cases.yaml` (si menciona la CLI)
- Modify: `docs/superpowers/specs/2026-09-28-japan-reader-design.md` (solo una nota en la cabecera)

- [ ] **Step 1: Comandos**

```bash
files=$(git grep -l "japan-reader" -- README.md CLAUDE.md docs/operations.md docs/pipeline docs/trilium-model.md eval)
sed -i -e 's/docker compose exec japan-reader japan-reader/docker compose exec tohoku tohoku/g' \
       -e 's/docker compose run --rm japan-reader japan-reader/docker compose run --rm tohoku tohoku/g' \
       -e 's/docker compose logs -f japan-reader/docker compose logs -f tohoku/g' \
       -e 's/`japan-reader \([a-z-]*\)/`tohoku \1/g' $files
git grep -n "japan-reader" -- README.md CLAUDE.md docs/operations.md docs/pipeline docs/trilium-model.md eval
```

Revisar a mano cada línea restante: nombres de proyecto → Tohoku. `japan-reader.json` y las rutas de los docs históricos (`2026-09-28-japan-reader-*.md`) se quedan.

- [ ] **Step 2: Textos de cabecera**

- `README.md` línea 1: `# Tohoku`, seguida de un párrafo: "Antes *japan-reader*. Convierte Shorts, Reels y posts guardados en Karakeep en notas de Trilium. El prefijo `jr` de etiquetas y atributos se mantiene a propósito: Japan Reader y JR, la compañía de la Tohoku Shinkansen."
- `CLAUDE.md` línea 1: `# CLAUDE.md — Tohoku (antes japan-reader)`. En "Entorno": contenedor `tohoku`, volumen `japan-reader_whisper-models` (externo, nombre histórico). En "Reglas de trabajo": una línea "El prefijo `jr` (Karakeep `jr:*`, Trilium `#jr*`, adjunto `japan-reader.json`) es intencionado y no se renombra."
- `docs/trilium-model.md`: tras el primer párrafo, "El prefijo `jr` de todos los atributos y del adjunto `japan-reader.json` viene del nombre original del proyecto y se mantiene."
- `docs/superpowers/specs/2026-09-28-japan-reader-design.md`: bajo `- **Autor:**`, añadir `- **Nota (2026-09-30):** el proyecto se renombró a Tohoku; ver 2026-09-30-multi-destino-design.md §11.`

- [ ] **Step 3: Commit**

```bash
git add README.md CLAUDE.md docs eval
git commit -m "docs: rename project to Tohoku

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 0.4: Despliegue (con el usuario)

Requiere confirmación del usuario y hacerse **entre tandas**. Los jobs pendientes esperando cuota no importan: reanudan igual.

- [ ] **Step 1: Estado previo**

Run: `docker exec japan-reader japan-reader status`. Se usa `docker exec` y no `docker compose exec` porque el compose del repo ya define el servicio `tohoku`. Anotar los recuentos.

- [ ] **Step 2: Parar y quitar el contenedor viejo**

Run: `docker stop japan-reader && docker rm japan-reader && docker ps -a --format '{{.Names}}' | grep -c '^japan-reader$'`
Expected: `0`.

- [ ] **Step 3: Construir y levantar**

Run: `docker compose build && docker compose up -d && docker ps --format '{{.Names}} {{.Status}}' | grep tohoku`
Expected: `tohoku Up …`.

- [ ] **Step 4: Verificar**

- `docker compose exec tohoku tohoku status`: mismos recuentos que en el Step 1.
- `docker compose logs --since 5m tohoku | grep -i "download\|descarg"`: sin descargas de modelo. Cuando procese un Reel, `docker compose logs tohoku | grep -i whisper` debe mostrar que carga de `/models`.
- `docker volume ls | grep whisper`: solo `japan-reader_whisper-models`.
- Borrar el lock viejo: `docker compose exec tohoku rm -f /data/japan-reader.lock`.

- [ ] **Step 5: Actualizar el estado en `CLAUDE.md` y hacer commit**

Añadir en "Estado": `2026-09-30: renombrado a Tohoku desplegado (contenedor tohoku, mismo state.db y volumen de modelos).`

```bash
git commit -am "docs: record Tohoku rename deployment

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 0.5: Renombrar el directorio del repositorio (con el usuario, al final)

Rompe la ruta de la sesión de Claude Code en curso: es lo último de la fase 0 y después se abre una sesión nueva en `/media/1tb-disk/tohoku`.

- [ ] **Step 1:** `docker compose down`. El contenedor debe estar parado porque el bind `./data` cambia de ruta.
- [ ] **Step 2:** `mv /media/1tb-disk/japan-reader /media/1tb-disk/tohoku`
- [ ] **Step 3:** `cd /media/1tb-disk/tohoku && rm -rf .venv && uv sync && uv run pytest -q`. El `.venv` guarda rutas absolutas. Expected: verde.
- [ ] **Step 4:** Mover la memoria de Claude: `mkdir -p ~/.claude/projects/-media-1tb-disk-tohoku && mv ~/.claude/projects/-media-1tb-disk-japan-reader/memory ~/.claude/projects/-media-1tb-disk-tohoku/`
- [ ] **Step 5:** `docker compose up -d && docker compose exec tohoku tohoku status`. Expected: mismos recuentos.
- [ ] **Step 6:** En `CLAUDE.md` no hay rutas absolutas del repo. Comprobar con `grep -n "/media/1tb-disk/japan-reader" CLAUDE.md docs -r`: sin resultados; si los hay, corregirlos y hacer commit.

---

## Fase 1: la cola no se para por una cuota agotada

### Task 1.1: `QuotaExceeded` lleva la clave de la cuota

**Files:**
- Modify: `src/tohoku/errors.py`
- Modify: `src/tohoku/quota.py:15`
- Test: `tests/unit/test_state.py:136-141`

**Interfaces:**
- Produces: `QuotaExceeded(key: str, message: str)` con el atributo `.key` (`"places_calls"`, `"openrouter_usd"`); `str(exc)` sigue siendo el mensaje.

- [ ] **Step 1: Test**

Sustituir `test_daily_quota` en `tests/unit/test_state.py`:

```python
def test_daily_quota(state):
    quota = DailyQuota(state, "places_calls", limit=2)
    quota.check()
    quota.add(2)
    with pytest.raises(QuotaExceeded) as info:
        quota.check()
    assert info.value.key == "places_calls"
    assert str(info.value) == "límite diario alcanzado: places_calls (2)"
```

Run: `uv run pytest tests/unit/test_state.py::test_daily_quota -q`
Expected: FAIL (`AttributeError: 'QuotaExceeded' object has no attribute 'key'`).

- [ ] **Step 2: Implementación**

`src/tohoku/errors.py`:

```python
class QuotaExceeded(TohokuError):
    """Límite diario alcanzado: el job espera al día siguiente sin consumir reintentos."""

    def __init__(self, key: str, message: str) -> None:
        super().__init__(message)
        self.key = key
```

`src/tohoku/quota.py`, en `check()`:

```python
            raise QuotaExceeded(self.key, f"límite diario alcanzado: {self.key} ({self.limit:g})")
```

(`:g` hace que `limit=2` se muestre `2` y no `2.0`; los contadores son `float`.)

En `tests/unit/test_pipeline.py`, adaptar las dos construcciones existentes:
- línea 139: `QuotaExceeded("places_calls", "límite diario alcanzado: places_calls (150)")`
- línea 181: `QuotaExceeded("openrouter_usd", "presupuesto agotado")`

- [ ] **Step 3: Verificar**

Run: `uv run pytest -q`
Expected: verde.

- [ ] **Step 4: Commit**

```bash
git add src/tohoku/errors.py src/tohoku/quota.py tests/unit/test_state.py tests/unit/test_pipeline.py
git commit -m "feat(quota): QuotaExceeded carries the quota key

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 1.2: Aparcar el job y seguir con la pasada

**Files:**
- Modify: `src/tohoku/pipeline.py:54-90`
- Test: `tests/unit/test_pipeline.py`

**Interfaces:**
- Consumes: `QuotaExceeded.key` (Task 1.1).
- Produces: `Pipeline.run_due() -> int` (número de jobs intentados en la pasada, igual que antes); `Pipeline.run_job(job) -> None` (antes devolvía `bool`; su único llamador es `run_due`). Aviso ntfy con clave `f"quota:{exc.key}"`, una vez al día por cuota.

- [ ] **Step 1: Tests**

En `tests/unit/test_pipeline.py`, añadir un paso que falla solo para algunos bookmarks:

```python
class QuotaStep(Step):
    """Agota la cuota solo para los bookmarks indicados (los demás no la necesitan: p. ej. todo en caché)."""

    def __init__(self, name, key, for_bookmarks):
        super().__init__(name)
        self.key = key
        self.for_bookmarks = set(for_bookmarks)

    def run(self, ctx):
        self.calls += 1
        if ctx.job.bookmark_id in self.for_bookmarks:
            raise QuotaExceeded(self.key, f"límite diario alcanzado: {self.key} (150)")
        return self.result
```

Sustituir `test_quota_exceeded_stops_the_pass` por:

```python
def test_quota_exceeded_parks_job_and_pass_continues(tmp_path, state):
    """Con la cuota agotada solo espera el job que la necesita; el resto de la cola sigue."""
    _add(state, "b1")
    _add(state, "b2")
    fetch = Step("fetch")
    geocode = QuotaStep("geocode", "places_calls", for_bookmarks={"b1"})
    publish = Step("publish", result=PublishResult(outcome=Outcome.PROCESADO))
    notifier = FakeNotifier()
    pipeline = Pipeline(state, [fetch, geocode, publish], FakeMark(), notifier, tmp_path / "data", clock=lambda: NOW)

    assert pipeline.run_due() == 2

    b1, b2 = state.get_job("b1"), state.get_job("b2")
    assert b1.status == JobStatus.PENDING and b1.attempts == 0
    assert b1.next_attempt_at == datetime(2026, 9, 29, 7, 5, tzinfo=UTC)
    assert b2.status == JobStatus.DONE and b2.outcome == Outcome.PROCESADO
    assert state.load_stage("b1", "fetch", Dummy) == Dummy()  # lo hecho antes de la cuota queda guardado
    assert len(notifier.sent) == 1


def test_parked_job_resumes_at_the_quota_stage(tmp_path, state):
    _add(state, "b1")
    fetch = Step("fetch")
    geocode = QuotaStep("geocode", "places_calls", for_bookmarks={"b1"})
    publish = Step("publish", result=PublishResult(outcome=Outcome.PROCESADO))
    pipeline = Pipeline(state, [fetch, geocode, publish], FakeMark(), FakeNotifier(), tmp_path / "data", clock=lambda: NOW)
    pipeline.run_due()

    geocode.for_bookmarks.clear()  # vuelve la cuota
    job = state.get_job("b1")
    pipeline.run_job(job)

    assert fetch.calls == 1 and geocode.calls == 2 and publish.calls == 1
    assert state.get_job("b1").status == JobStatus.DONE


def test_quota_notifies_once_per_key_even_if_every_job_hits_it(tmp_path, state):
    for bid in ("b1", "b2", "b3"):
        _add(state, bid)
    geocode = QuotaStep("geocode", "places_calls", for_bookmarks={"b1", "b2", "b3"})
    notifier = FakeNotifier()
    pipeline = Pipeline(state, [geocode], FakeMark(), notifier, tmp_path / "data", clock=lambda: NOW)

    pipeline.run_due()

    assert all(state.get_job(b).status == JobStatus.PENDING for b in ("b1", "b2", "b3"))
    assert [title for title, _ in notifier.sent] == ["tohoku: límite diario alcanzado"]
```

En `test_quota_waits_until_tomorrow_and_notifies_once` (línea 136), añadir al final:

```python
    assert state.get_job("b2").next_attempt_at == datetime(2026, 9, 29, 7, 5, tzinfo=UTC)
```

Run: `uv run pytest tests/unit/test_pipeline.py -q`
Expected: FAIL en `test_quota_exceeded_parks_job_and_pass_continues` (b2 sigue `PENDING`) y en la aserción nueva de `test_quota_waits…`.

- [ ] **Step 2: Implementación**

En `src/tohoku/pipeline.py`, sustituir `run_due` y la cabecera y el `except QuotaExceeded` de `run_job`, y quitar los `return True` / `return False`:

```python
    def run_due(self) -> int:
        """Procesa los jobs pendientes. Un job que agota una cuota diaria espera a que se renueve; los demás siguen.

        `DailyQuota.check()` solo lee un contador local: los jobs que lleguen después a una etapa con la
        cuota agotada se aparcan sin llamar a la API, y los que no la necesiten (caché, etapas sin cuota) avanzan.
        """
        jobs = self._state.due_jobs()
        for job in jobs:
            self.run_job(job)
        return len(jobs)

    def run_job(self, job: Job) -> None:
        """Ejecuta un job hasta el final o hasta el primer error, aplicando la política de errores."""
        if job.platform is None:
            self.mark_failed(job.bookmark_id, "fuente no soportada")
            return
        ...
        except QuotaExceeded as exc:
            self._state.schedule_retry(job.bookmark_id, self._tomorrow(), str(exc), count_attempt=False)
            self.notify_once(f"quota:{exc.key}", "tohoku: límite diario alcanzado", f"{exc}. Se reanuda mañana.")
```

(El resto de `run_job` no cambia. Borrar el `return True` final y el `return False` del bloque de cuota.)

- [ ] **Step 3: Verificar**

Run: `uv run pytest -q`
Expected: verde.

- [ ] **Step 4: Commit**

```bash
git add src/tohoku/pipeline.py tests/unit/test_pipeline.py
git commit -m "feat(pipeline): an exhausted quota parks the job instead of stopping the pass

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 1.3: Documentación y despliegue

**Files:**
- Modify: `docs/pipeline/05-geocode.md:22`, `docs/pipeline/04-extract.md:18`, `docs/operations.md` (§ "Costes y cuotas"), `CLAUDE.md` ("Pendientes": quitar "Con la cuota de Places agotada se para toda la cola"; "Estado": línea de despliegue)
- Modify: `docs/superpowers/specs/2026-09-30-multi-destino-design.md` §4 "Cuotas por clave"

- [ ] **Step 1: Docs de etapa**

- `05-geocode.md`: sustituir "y la pasada se detiene (los demás jobs siguen pendientes)" por "y la pasada sigue con los demás jobs: los que lleguen a `geocode` con búsquedas nuevas se aparcan igual sin llamar a Google; los que lo tengan todo en caché, o estén en etapas anteriores, avanzan".
- `04-extract.md`: sustituir "la pasada se detiene (los demás jobs siguen pendientes)" por "la pasada sigue con los demás jobs (descargas y transcripciones avanzan; las llamadas al LLM se aparcan igual)".
- `operations.md`: añadir en "Costes y cuotas": "Con una cuota agotada la cola no se para: solo esperan los jobs que la necesitan. Un aviso ntfy por cuota y día."

- [ ] **Step 2: Spec §4.** Sustituir el apartado "Cuotas por clave" por:

```markdown
### Cuotas por clave (la cola no se para)

- `QuotaExceeded` lleva la clave de su cuota (`places_calls`, `openrouter_usd`). El job afectado se aparca hasta el siguiente reinicio de cuota, sin gastar un intento, y **la pasada continúa**.
- No hace falta que las etapas declaren sus cuotas: `DailyQuota.check()` lee un contador local, así que un job que llega a una etapa con la cuota agotada se aparca sin llamar a la API, y uno que no la necesita (búsquedas en caché, etapas sin cuota) avanza.
- El aviso por ntfy se manda una vez al día por clave.
```

- [ ] **Step 3: Commit**

```bash
git add docs CLAUDE.md
git commit -m "docs: quota no longer stops the queue

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 4: Despliegue (con el usuario, entre tandas)**

Run: `docker compose build && docker compose up -d && docker compose logs --since 2m tohoku`
Verificación: la próxima vez que se agote Places (o forzándolo con un límite bajo **solo** si el usuario lo pide), `tohoku status` muestra jobs que siguen terminando (`procesado` sube) mientras otros esperan con `last_error` "límite diario alcanzado: places_calls". Llega un único aviso ntfy.
