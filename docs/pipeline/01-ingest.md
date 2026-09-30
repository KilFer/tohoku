# Etapa 1 — ingest

**Qué hace:** lee las listas de Karakeep configuradas en `config/destinos.yaml` (clave `listas`) y crea un *job* en `state.db` por cada bookmark nuevo.

**Entrada:** las listas de `config/destinos.yaml` (cada lista apunta a uno o varios destinos candidatos; hoy una: la lista "Japón", destino `japon`).
**Salida:** filas en la tabla `jobs` (`bookmark_id`, `url`, `platform`, `hint`, `status=pending`, `candidates`: destinos de su lista).
**Dependencias:** API de Karakeep (`GET /api/v1/lists/{id}/bookmarks`, paginada con `cursor`).
**Configuración:** `KARAKEEP_URL`, `KARAKEEP_API_KEY`, `POLL_INTERVAL_MINUTES`, `DESTINOS_FILE` (por defecto `config/destinos.yaml`). `KARAKEEP_LIST_ID` ya no se lee de `.env`: se ignora si sigue ahí.

**Reglas:**
- Se ignoran los bookmarks que ya tienen job o que ya llevan una etiqueta `jr:*` (protege frente a pérdida de `state.db`).
- URLs soportadas: YouTube (`/shorts/`, `watch`, `youtu.be`) e Instagram (`/reel/`, `/reels/`, `/tv/`, `/p/`, también con usuario delante).
- Los bookmarks que no son enlaces (notas de texto, imágenes sueltas: sin URL) se ignoran: ni job ni `jr:error`.
- Los enlaces de dominios no soportados se registran sin plataforma; el pipeline los marca `jr:error` con motivo "fuente no soportada".

- Si el mismo bookmark está en dos listas, sus candidatos se unen (un solo job); si el job ya existe, sigue pendiente y aún no tiene destino, se amplían sus `candidates`.

**Fallos:** lista inexistente → `ConfigError` (se detiene y avisa por ntfy); 401/403 → `ConfigError`; red/5xx → se reintenta en el siguiente sondeo.

**Cómo probarla:** `uv run pytest tests/unit/test_ingest_mark.py -k ingest`. En real: `tohoku run-once` y `tohoku status`.
