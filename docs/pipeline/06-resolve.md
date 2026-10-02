# Stage 6 — resolve

**English** · [Español](06-resolve.es.md)

**What it does:** compares what was extracted with what already exists in Trilium and decides, item by item, whether to create, merge or mark as an alias; it also computes the review reasons.

**Input:** `ExtractResult`, `GeocodeResult`, the Trilium structure.

**Output:** `ResolveResult {items: [PlannedItem {key, kind, index, action, existing_note_id, alias_of, review_reasons}]}`.

**Dependencies:** Trilium ETAPI (searching notes by attributes under the `#jrRoot` root), the `extract` and `geocode` results.

**Rules:**
- Failed extraction → a single `fallo` (failure) item with `extraccion-fallida`.
- `confianza_destino` < 0.4 → no items (result `descartado`).
- 0.4 ≤ `confianza_destino` < 0.7 → all items with `clasificacion-incierta`.
- If `classify` marked the classification as doubtful (a close alternative), all items also carry `clasificacion-dudosa`.
- Item with `confianza` < 0.7 → `baja-confianza`.
- Place: looks for `#googlePlaceId` under the root; if there is none, a place with the same `#jrNombreNorm` whose `#geolocation` is within 300 m (Google sometimes has two cards for the same place: "Omoide Yokocho", two placeIds 45 m apart) → `merge` (keeps the existing note's card) or `create`. Without coordinates → looks for `#jrTipo=lugar #jrNombreNorm="<normalized>"` under the root → `merge` or `create`, always with the geocoding reason (so a place Google cannot find is not repeated in every source). The same `place_id` (or, without a card, the same normalized name) twice in the same source → `alias` of the first.
- Thing (`cosa`): looks for `#jrTipo=cosa #jrNombreNorm="<normalized>"` in "Comprar y comer" → `merge`; otherwise it compares against all things and, if one has similarity ≥ 0.85, `create` + `posible-duplicado`. The same normalized name twice → `alias`.
- Other → always `create`. If the content belongs to the destination but there are no items → `otro:resumen` with the source's summary.

**Configuration:** `JAPAN_MIN_CONFIDENCE`, `JAPAN_REVIEW_CONFIDENCE`, `ITEM_REVIEW_CONFIDENCE`, `COSA_DUPLICATE_SIMILARITY` (the `JAPAN_*` names are historical; they apply to every destination).

**Failures:** Trilium errors → retry; missing structure → `ConfigError`.

**How to test it:** `uv run pytest tests/unit/test_resolve.py`.
