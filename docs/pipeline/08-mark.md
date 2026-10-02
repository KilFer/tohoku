# Stage 8 — mark

**English** · [Español](08-mark.es.md)

**What it does:** records the result in Karakeep and tidies the Home page.

**Input:** `bookmark_id` and the result (`Outcome`) computed by `publish`, or `error`.
**Output:** `MarkResult {tag, archived}`.
**Dependencies:** Karakeep (`GET /bookmarks/{id}`, `POST/DELETE /bookmarks/{id}/tags`, `PATCH /bookmarks/{id}`).
**Configuration:** `KARAKEEP_URL`, `KARAKEEP_API_KEY`. The stage has no settings of its own; the tags are fixed (see the table).

| Result | Tag | Archive |
|---|---|---|
| procesado (processed) | `jr:procesado` | yes |
| revisar (to review) | `jr:revisar` | yes |
| descartado (discarded) | `jr:descartado` | yes |
| error | `jr:error` | no |

It also adds `jr:destino:<destination>` with the destination decided by `classify`, except for `descartado`: **a `descartado` never carries `jr:destino`**, neither when `classify` chose no destination nor when the destination's flow discards the content (for example the `viaje` flow with content that is not from that country). An `error` carries it only if the job already had a destination. It removes previous result or destination `jr:` tags that differ from the new ones (useful when reprocessing). The user's other tags are not touched.

**Failures:** network/5xx → the job is retried (earlier stages are not repeated); if marking a definitive error fails, the job stays in error anyway and it is logged.

**How to test it:** `uv run pytest tests/unit/test_ingest_mark.py -k mark`.
