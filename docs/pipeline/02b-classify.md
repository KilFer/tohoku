# Stage 2b — classify

**English** · [Español](02b-classify.es.md)

**What it does:** decides which destination of `config/destinos.yaml` the link goes to, among the candidates of its list. It sits between `transcribe` and `extract` (order: fetch, transcribe, classify, extract, geocode, resolve, publish). The rest of the pipeline uses the chosen destination's flow.

**Input:** `job.candidates` (the destinations of the lists the bookmark is in), `job.destination` (if one is already forced), and the `fetch` and `transcribe` results.

**Output:** `Classification {destino | None, confianza, alternativa, confianza_alternativa, dudosa, omitido, cost_usd}`. The stage result and `jobs.destination` are stored. `destino=None` means `ninguno` (none) and the job ends as `descartado`.

**Dependencies:** OpenRouter (only if there are several candidates; with images, `OPENROUTER_MODEL`), the daily `openrouter_usd` counter, `src/tohoku/prompts/classify.md`, `src/tohoku/classify/` (the `json_schema` and `etiqueta` classifiers, `CLASSIFIERS` registry).

**Configuration:** in `config/destinos.yaml`:
- `clasificador.modelo` (default `OPENROUTER_TEXT_MODEL`, or `OPENROUTER_MODEL`) to classify with text; with images `OPENROUTER_MODEL` (multimodal, checked in the preflight) is always used in the same `modo`, because the text model may not accept images. The classifier is mounted if some bookmark can have several candidates: a list with several destinations **or** lists with different destinations (ingest joins the candidates of all the lists of a bookmark). `clasificador.modo` (`json_schema` | `etiqueta`, default `json_schema`), `clasificador.confianza_minima` (0.5), `clasificador.margen_revision` (0.15).
- `destino_por_defecto`: default destination, used by commands without `--destino` and as the fallback for jobs without candidates (`candidates` NULL). Optional with a single destination; required with several.
- `OPENROUTER_DAILY_BUDGET_USD`.

**Rules:**
- With an already stored destination (`reprocess --destino`) or with a single candidate: no LLM call (`omitido=true`).
- Candidates that no longer exist in `destinos.yaml` are dropped; if none is left, `destino_por_defecto` is used.
- With several candidates: the classifier gets each destination's description, the text (caption, hashtags, transcript) and, if there is no text (empty caption and transcript), up to 2 images, which go to the `OPENROUTER_MODEL` classifier. If the response is invalid or names a destination that is not a candidate, one retry with the error; if it fails again, `TransientError`.
- `ninguno` or `confianza` < `confianza_minima` → `destino=None` (`descartado`, tag `jr:descartado`).
- If there is a different candidate alternative and `confianza - confianza_alternativa` < `margen_revision` → `dudosa=true`; the `viaje` flow's `resolve` adds the review reason `clasificacion-dudosa`.
- Destination names are compared ignoring case, accents and separators: spaces, hyphens and underscores are equivalent (`Nueva Zelanda` = `nueva-zelanda` = `nueva_zelanda`); an unknown `alternativa` is ignored. That is why `destinos.yaml` rejects (`ConfigError` naming both) two destinations that differ only in that (`japon` and `Japón`).
- Files: the stage only needs `data/jobs/<id>/` if it is going to send images. After cleanup (`files_purged`) the pipeline only downloads again for `classify` in that case; a job without a `classify` result reprocessed from `geocode`/`resolve`/`publish` takes `destino_por_defecto` without downloading.
- `etiqueta` mode: confidence 1.0 and no alternative (there are no logprobs). Provider-specific adapters are left open (`CLASSIFIERS` registry).

**Failures:** several candidates without a classifier → `ConfigError`; an invalid response after the retry or 429/5xx → the job is retried; budget exhausted → `QuotaExceeded` (waits until the next day). A decided or forced destination that no longer exists in the YAML fails only that job (`jr:error`), not the queue.

**Example with two flows** (`japon` with flow `viaje`, `recetas` with flow `receta`):

    listas:
      L_JAPAN: [japon]
      L_RECIPES: [recetas]
    destinos: {japon: {flujo: viaje, ...}, recetas: {flujo: receta, ...}}
    destino_por_defecto: japon

- A bookmark only in `L_RECIPES` has one candidate (`recetas`): no LLM call and it follows the `receta` flow. One only in `L_JAPAN` follows the `viaje` flow. One in both lists has two candidates and the classifier decides (there is a classifier because there is more than one destination overall, even if each list has only one).
- A Reel that the classifier sends to `recetas` but is not a recipe ends `descartado`: no note and no `jr:destino`.

**How to test it:** `uv run pytest tests/unit/test_classify.py`. With real cases: `tohoku eval --destino X`. To force: `tohoku reprocess <id> --destino X` (see `docs/operations.md`).
