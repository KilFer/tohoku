# Etapa 7 — publish

**Qué hace:** escribe en Trilium según el plan de `resolve` y calcula el resultado final del job.

**Entrada:** resultados de `fetch`, `transcribe`, `extract`, `geocode` y `resolve`.
**Salida:** `PublishResult {notes: [PublishedNote], outcome}`. `outcome`: `no-japon` si se descartó; `revisar` si algún elemento tiene motivos de revisión; si no, `procesado`.

**Dependencias:** Trilium ETAPI (notas, atributos, ramas y adjuntos), OpenRouter (solo para reescribir al fusionar), tabla `published` de `state.db`.
**Configuración:** `OPENROUTER_TEXT_MODEL` (o `OPENROUTER_MODEL`), `OPENROUTER_DAILY_BUDGET_USD`, `TRILIUM_URL`, `TRILIUM_ETAPI_TOKEN`, `TRILIUM_ROOT_LABEL`.

**Crear:** nota de texto en su sitio (Lugar → Mapa; Cosa → su categoría; Otro → Cultura), atributos gestionados, `~template` y adjunto `japan-reader.json`.
**Fusionar:** lee el adjunto, añade la fuente (o la actualiza si es el mismo bookmark; si además es la única fuente de la nota, la nota se regenera con la extracción nueva sin llamar al LLM), una llamada al LLM (`OPENROUTER_TEXT_MODEL`, prompt `prompts/merge.md`) reescribe Resumen, Qué hacer y Consejos, y se regenera el HTML conservando "Mis notas". Si el LLM devuelve algo inválido, se conservan los textos y se unen los consejos.
**Atributos gestionados en fusiones:** cada uno se reescribe solo si falta o si conserva el valor que el servicio escribió la vez anterior (calculado del adjunto previo); así no se deshacen las correcciones del usuario. `#fuentes` y `#jrTipo` se escriben siempre.
**Revisión:** clon en la Bandeja de revisión + `#revisar=<motivos>` (se acumulan).
**Extracción fallida:** nota en la Bandeja con caption, transcripción, error y enlace.
**Cosa con local concreto:** relación `~dondeComprar` hacia la nota Lugar del local.

**Idempotencia:** cada elemento publicado se registra en `state.db` (`published`). Si el job se reintenta, los elementos ya publicados no se repiten. Reprocesar la misma fuente no duplica la entrada de "Fuentes" ni llama al LLM. Además, al crear una nota (`create` o cuando la nota de fusión ha sido borrada), lo primero que se escribe tras `create-note` es la etiqueta `#jrItem="<bookmark_id>:<identidad>"`, donde la identidad sale del **contenido** del elemento (`lugar:<place_id>`, `lugar:n:<nombre normalizado>`, `cosa:<nombre normalizado>`, `otro:<título normalizado>`, `fallo`) y no de su posición, para que una re-extracción que reordene los elementos no mezcle notas (la clave posicional de `resolve` solo se usa en la tabla `published` de `state.db`); si la etapa se corta a medias (p. ej. un timeout al crear el adjunto), el reintento busca esa etiqueta bajo la raíz y retoma la misma nota en vez de crear otra, completando de forma idempotente etiquetas, `~template` y el adjunto `japan-reader.json`. En la fusión, el adjunto se escribe antes que el contenido y las etiquetas, así un reintento ve la fuente ya incorporada y no repite la llamada al LLM. Si la nota de fusión ya no existe (404), se crea una nueva en su lugar. Antes de crear (o de reutilizar la nota de `#jrItem`) se vuelve a buscar la clave natural (`#googlePlaceId` bajo la raíz; lugar sin ficha: `#jrTipo=lugar #jrNombreNorm` bajo la raíz; `#jrTipo=cosa #jrNombreNorm` en "Comprar y comer"): si otra fuente ya creó la nota después del plan de `resolve`, se fusiona en ella.

**Fallos:** Trilium 5xx o timeouts → reintento con espera; Trilium 4xx → `jr:error` (salvo el 404 de la nota de fusión, que crea una nota nueva); presupuesto de OpenRouter agotado → espera al día siguiente.
**Cómo probarla:** `uv run pytest tests/unit/test_publish.py`. Contra Trilium real: `uv run pytest -m integration -k trilium`.
