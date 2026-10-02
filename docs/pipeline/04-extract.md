# Stage 4 — extract

**English** · [Español](04-extract.es.md)

**What it does:** decides whether the content belongs to the destination (for example Japan) and extracts places, things and other data as structured JSON.

**Input:** metadata, caption, hashtags, transcript, the post's images and key frames.
**Output:** `ExtractResult {extraction | None, error, cost_usd}`. `Extraction` schema (with `que_hacer`, "what to do", on every place).

**Dependencies:** OpenRouter (OpenAI-compatible API, `POST /api/v1/chat/completions`), the `fetch` and `transcribe` results, the daily `openrouter_usd` counter in `state.db`.

**Configuration:** `OPENROUTER_API_KEY`, `OPENROUTER_MODEL` (multimodal), `OPENROUTER_TEXT_MODEL` (optional), `OPENROUTER_DAILY_BUDGET_USD`.

**Model:** `OPENROUTER_MODEL` (multimodal; on startup it checks that both models exist and support `response_format`/`structured_outputs`) if there are images; `OPENROUTER_TEXT_MODEL` (or the same one) if there are not. The request uses `response_format=json_schema`, `provider.require_parameters=true` and `usage.include=true` to learn the real cost. `temperature=0.2` is only sent if the model supports it according to its entry in `GET /models` (reasoning models do not, and with `require_parameters` OpenRouter would return 404).

**Prompt:** `config/prompts/japon.md` (the destination's `prompt:` key in `config/destinos.yaml`; versioned with the repo and copied into the image). Only the markers `{{categorias_lugar}}` and `{{categorias_cosa}}` are filled in, with the destination's categories. It asks the model to read the text in the images and cross-check it against the audio.

**Validation:** Pydantic; the JSON schema (`response_format`) carries the destination's categories as an `enum`. A category outside the destination's list counts as invalid JSON. If the JSON does not validate, one retry with the error included. If it fails again → `extraction=None` and `resolve` creates a review note `extraccion-fallida`.

**Cost:** every call adds its cost to the daily `openrouter_usd` counter; if `OPENROUTER_DAILY_BUDGET_USD` is exceeded, the job waits until the next day (`QuotaExceeded`), the pass continues with the other jobs (downloads and transcriptions advance; LLM calls are parked the same way) and ntfy is notified once a day.

**Failures:** 401/402/403 → `ConfigError` (invalid key or no balance); 400/404 that talk about the model ("not a valid model", "No endpoints found"…) → `ConfigError` (the service pauses and notifies once; `jr:error` is not set); other 4xx → `jr:error`; 429/5xx/timeout → retry.

**How to test it:** `uv run pytest tests/unit/test_extract.py tests/unit/test_openrouter_client.py`. With real models: `tohoku eval` (see `docs/operations.md`).
