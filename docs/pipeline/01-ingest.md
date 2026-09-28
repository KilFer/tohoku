# Etapa 1 — ingest

**Qué hace:** lee la lista de Karakeep configurada y crea un *job* en `state.db` por cada bookmark nuevo.

**Entrada:** `KARAKEEP_LIST_ID` (lista "Japón").
**Salida:** filas en la tabla `jobs` (`bookmark_id`, `url`, `platform`, `hint`, `status=pending`).
**Dependencias:** API de Karakeep (`GET /api/v1/lists/{id}/bookmarks`, paginada con `cursor`).
**Configuración:** `KARAKEEP_URL`, `KARAKEEP_API_KEY`, `KARAKEEP_LIST_ID`, `POLL_INTERVAL_MINUTES`.

**Reglas:**
- Se ignoran los bookmarks que ya tienen job o que ya llevan una etiqueta `jr:*` (protege frente a pérdida de `state.db`).
- URLs soportadas: YouTube (`/shorts/`, `watch`, `youtu.be`) e Instagram (`/reel/`, `/reels/`, `/tv/`, `/p/`, también con usuario delante).
- Los bookmarks que no son enlaces (notas de texto, imágenes sueltas: sin URL) se ignoran: ni job ni `jr:error`.
- Los enlaces de dominios no soportados se registran sin plataforma; el pipeline los marca `jr:error` con motivo "fuente no soportada".

**Fallos:** lista inexistente → `ConfigError` (se detiene y avisa por ntfy); 401/403 → `ConfigError`; red/5xx → se reintenta en el siguiente sondeo.

**Cómo probarla:** `uv run pytest tests/unit/test_ingest_mark.py -k ingest`. En real: `japan-reader run-once` y `japan-reader status`.
