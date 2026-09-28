# Etapa 4 — extract

**Qué hace:** decide si el contenido es de Japón y extrae lugares, cosas y otros datos en JSON estructurado.

**Entrada:** metadatos, caption, hashtags, transcripción, imágenes del post y fotogramas clave.
**Salida:** `ExtractResult {extraction | None, error, cost_usd}`. Esquema `Extraction` (spec §5.4, más `que_hacer` en cada lugar).

**Dependencias:** OpenRouter (API compatible con OpenAI, `POST /api/v1/chat/completions`), resultados de `fetch` y `transcribe`, contador diario `openrouter_usd` en `state.db`.

**Configuración:** `OPENROUTER_API_KEY`, `OPENROUTER_MODEL` (multimodal), `OPENROUTER_TEXT_MODEL` (opcional), `OPENROUTER_DAILY_BUDGET_USD`.

**Modelo:** `OPENROUTER_MODEL` (multimodal; se comprueba al arrancar) si hay imágenes; `OPENROUTER_TEXT_MODEL` (o el mismo) si no las hay. Petición con `response_format=json_schema`, `provider.require_parameters=true` y `usage.include=true` para conocer el coste real.

**Prompt:** `src/japan_reader/prompts/extract.md` (versionado con el código). Pide leer el texto de las imágenes y contrastarlo con el audio.

**Validación:** Pydantic. Si el JSON no valida, un reintento con el error incluido. Si vuelve a fallar → `extraction=None` y `resolve` crea una nota de revisión `extraccion-fallida`.

**Coste:** cada llamada suma su coste al contador diario `openrouter_usd`; si se supera `OPENROUTER_DAILY_BUDGET_USD`, el job espera al día siguiente (`QuotaExceeded`) y se avisa por ntfy.

**Fallos:** 401/402/403 → `ConfigError` (clave inválida o sin saldo); 429/5xx/timeout → reintento.

**Cómo probarla:** `uv run pytest tests/unit/test_extract.py tests/unit/test_openrouter_client.py`. Con modelos reales: `japan-reader eval` (ver `docs/operations.md`).
