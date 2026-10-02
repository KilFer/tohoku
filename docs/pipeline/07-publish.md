# Stage 7 — publish

**English** · [Español](07-publish.es.md)

**What it does:** writes to Trilium according to `resolve`'s plan and computes the job's final result.

**Input:** the `fetch`, `transcribe`, `extract`, `geocode` and `resolve` results.
**Output:** `PublishResult {notes: [PublishedNote], outcome}`. `outcome`: `descartado` if it was discarded; `revisar` if any item has review reasons; otherwise `procesado`.

**Dependencies:** Trilium ETAPI (notes, attributes, branches and attachments), OpenRouter (only to rewrite when merging), the `published` table in `state.db`.
**Configuration:** `OPENROUTER_TEXT_MODEL` (or `OPENROUTER_MODEL`), `OPENROUTER_DAILY_BUDGET_USD`, `TRILIUM_URL`, `TRILIUM_ETAPI_TOKEN`. The root (`#jrRoot`) is the destination's `raiz` key in `config/destinos.yaml`.

**Create:** a text note in its place (Lugar → Mapa; Cosa → its category; Otro → Cultura), managed attributes, `~template` and the `tohoku.json` attachment.
**Merge:** reads the attachment, adds the source (or updates it if it is the same bookmark; if it is also the note's only source, the note is regenerated with the new extraction without calling the LLM), one LLM call (`OPENROUTER_TEXT_MODEL`, prompt `prompts/merge.md`) rewrites Resumen, Qué hacer and Consejos, and the HTML is regenerated keeping "Mis notas". If the LLM returns something invalid, the texts are kept and the tips are joined.
**Managed attributes in merges:** each one is rewritten only if it is missing or still holds the value the service wrote last time (computed from the previous attachment); this way the user's corrections are not undone. `#fuentes` and `#jrTipo` are always written.
**Review:** a clone in the review tray + `#revisar=<reasons>`. A note's current reasons are the union of those of all its sources (stored per source in `published` in `state.db`); `#revisar` is rewritten with that union and does not accumulate already resolved reasons. If an item brings reasons, the note enters (or stays in) the tray. If it brings none and no source has reasons any more (for example after a reprocess that resolves it), the tray clone and `#revisar` are removed; the note stays in its place. If it brings none but another source does, `#revisar` is updated only if the note is still in the tray: if the user already took it out, that is respected.
**Failed extraction:** a note in the tray with caption, transcript, error and link.
**Thing with a specific shop:** a `~dondeComprar` relation to the shop's Lugar note.

**Idempotency:** every published item is recorded in `state.db` (`published`). If the job is retried, already published items are not repeated. Reprocessing the same source does not duplicate the "Fuentes" entry or call the LLM. In addition, when a note is created (`create`, or when the merge note was deleted), the first thing written after `create-note` is the label `#jrItem="<bookmark_id>:<identity>"`, where the identity comes from the item's **content** (`lugar:<place_id>`, `lugar:n:<normalized name>`, `cosa:<normalized name>`, `otro:<normalized title>`, `fallo`) and not from its position, so a re-extraction that reorders the items does not mix notes up (`resolve`'s positional key is only used in the `published` table of `state.db`); if the stage is cut off halfway (for example a timeout when creating the attachment), the retry looks for that label under the root and resumes the same note instead of creating another, completing labels, `~template` and the `tohoku.json` attachment idempotently. In a merge, the attachment is written before the content and the labels, so a retry sees the source already incorporated and does not repeat the LLM call. If the merge note no longer exists (404), a new one is created in its place. Before creating (or reusing the `#jrItem` note) the natural key is looked up again (`#googlePlaceId` under the root, or the same `#jrNombreNorm` within 300 m; a place without a card: `#jrTipo=lugar #jrNombreNorm` under the root; `#jrTipo=cosa #jrNombreNorm` in "Comprar y comer"): if another source already created the note after `resolve`'s plan, it is merged into it.

**Failures:** Trilium 5xx or timeouts → retry with a wait; Trilium 4xx → `jr:error` (except the 404 of the merge note, which creates a new note); OpenRouter budget exhausted → waits until the next day.
**How to test it:** `uv run pytest tests/unit/test_publish.py`. Against a real Trilium: `uv run pytest -m integration -k trilium`.
