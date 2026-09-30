# Etapa 4 — extract

**Qué hace:** decide si el contenido es del destino (hoy Japón) y extrae lugares, cosas y otros datos en JSON estructurado.

**Entrada:** metadatos, caption, hashtags, transcripción, imágenes del post y fotogramas clave.
**Salida:** `ExtractResult {extraction | None, error, cost_usd}`. Esquema `Extraction` (spec §5.4, más `que_hacer` en cada lugar).

**Dependencias:** OpenRouter (API compatible con OpenAI, `POST /api/v1/chat/completions`), resultados de `fetch` y `transcribe`, contador diario `openrouter_usd` en `state.db`.

**Configuración:** `OPENROUTER_API_KEY`, `OPENROUTER_MODEL` (multimodal), `OPENROUTER_TEXT_MODEL` (opcional), `OPENROUTER_DAILY_BUDGET_USD`.

**Modelo:** `OPENROUTER_MODEL` (multimodal; al arrancar se comprueba que ambos modelos existen y admiten `response_format`/`structured_outputs`) si hay imágenes; `OPENROUTER_TEXT_MODEL` (o el mismo) si no las hay. Petición con `response_format=json_schema`, `provider.require_parameters=true` y `usage.include=true` para conocer el coste real. `temperature=0.2` solo se envía si el modelo la admite según su ficha en `GET /models` (los modelos de razonamiento no la admiten y, con `require_parameters`, OpenRouter devolvería 404).

**Prompt:** `config/prompts/japon.md` (clave `prompt:` del destino en `config/destinos.yaml`; versionado con el repo y copiado a la imagen). Solo se rellenan los marcadores `{{categorias_lugar}}` y `{{categorias_cosa}}` con las categorías del destino. Pide leer el texto de las imágenes y contrastarlo con el audio.

**Validación:** Pydantic; el esquema JSON (`response_format`) lleva como `enum` las categorías del destino. Una categoría fuera de la lista del destino cuenta como JSON no válido. Si el JSON no valida, un reintento con el error incluido. Si vuelve a fallar → `extraction=None` y `resolve` crea una nota de revisión `extraccion-fallida`.

**Coste:** cada llamada suma su coste al contador diario `openrouter_usd`; si se supera `OPENROUTER_DAILY_BUDGET_USD`, el job espera al día siguiente (`QuotaExceeded`), la pasada sigue con los demás jobs (descargas y transcripciones avanzan; las llamadas al LLM se aparcan igual) y se avisa por ntfy una vez al día.

**Fallos:** 401/402/403 → `ConfigError` (clave inválida o sin saldo); 400/404 que hablan del modelo ("not a valid model", "No endpoints found"...) → `ConfigError` (el servicio se pausa y avisa una vez; no se marca `jr:error`); otros 4xx → `jr:error`; 429/5xx/timeout → reintento.

**Cómo probarla:** `uv run pytest tests/unit/test_extract.py tests/unit/test_openrouter_client.py`. Con modelos reales: `tohoku eval` (ver `docs/operations.md`).
