# Etapa 7 — publish

**Qué hace:** escribe en Trilium según el plan de `resolve` y calcula el resultado final del job.

**Entrada:** resultados de `fetch`, `transcribe`, `extract`, `geocode` y `resolve`.
**Salida:** `PublishResult {notes: [PublishedNote], outcome}`. `outcome`: `no-japon` si se descartó; `revisar` si algún elemento tiene motivos de revisión; si no, `procesado`.

**Dependencias:** Trilium ETAPI (notas, atributos, ramas y adjuntos), OpenRouter (solo para reescribir al fusionar), tabla `published` de `state.db`.
**Configuración:** `OPENROUTER_TEXT_MODEL` (o `OPENROUTER_MODEL`), `OPENROUTER_DAILY_BUDGET_USD`, `TRILIUM_URL`, `TRILIUM_ETAPI_TOKEN`, `TRILIUM_ROOT_LABEL`.

**Crear:** nota de texto en su sitio (Lugar → Mapa; Cosa → su categoría; Otro → Cultura), atributos gestionados, `~template` y adjunto `japan-reader.json`.
**Fusionar:** lee el adjunto, añade la fuente (o la actualiza si es el mismo bookmark), una llamada al LLM (`OPENROUTER_TEXT_MODEL`, prompt `prompts/merge.md`) reescribe Resumen, Qué hacer y Consejos, y se regenera el HTML conservando "Mis notas". Si el LLM devuelve algo inválido, se conservan los textos y se unen los consejos.
**Revisión:** clon en la Bandeja de revisión + `#revisar=<motivos>` (se acumulan).
**Extracción fallida:** nota en la Bandeja con caption, transcripción, error y enlace.
**Cosa con local concreto:** relación `~dondeComprar` hacia la nota Lugar del local.

**Idempotencia:** cada elemento publicado se registra en `state.db` (`published`). Si el job se reintenta, los elementos ya publicados no se repiten. Reprocesar la misma fuente no duplica la entrada de "Fuentes" ni llama al LLM.

**Fallos:** errores de Trilium → reintento; presupuesto de OpenRouter agotado → espera al día siguiente.
**Cómo probarla:** `uv run pytest tests/unit/test_publish.py`. Contra Trilium real: `uv run pytest -m integration -k trilium`.
