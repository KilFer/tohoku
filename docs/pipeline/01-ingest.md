# Stage 1 — ingest

**English** · [Español](01-ingest.es.md)

**What it does:** reads the Karakeep lists configured in `config/destinos.yaml` (`listas` key) and creates a *job* in `state.db` for every new bookmark.

**Input:** the lists in `config/destinos.yaml` (each list points to one or more candidate destinations; for example the "Japan" list, destination `japon`).
**Output:** rows in the `jobs` table (`bookmark_id`, `url`, `platform`, `hint`, `status=pending`, `candidates`: the destinations of its list).
**Dependencies:** Karakeep API (`GET /api/v1/lists/{id}/bookmarks`, paginated with `cursor`).
**Configuration:** `KARAKEEP_URL`, `KARAKEEP_API_KEY`, `POLL_INTERVAL_MINUTES`, `DESTINOS_FILE` (default `config/destinos.yaml`).

**Rules:**
- Bookmarks that already have a job or already carry a `jr:*` tag are ignored (this protects against losing `state.db`).
- Supported URLs: YouTube (`/shorts/`, `watch`, `youtu.be`) and Instagram (`/reel/`, `/reels/`, `/tv/`, `/p/`, also with a username in front).
- Bookmarks that are not links (text notes, loose images: no URL) are ignored: no job and no `jr:error`.
- Links from unsupported domains are recorded without a platform; the pipeline marks them `jr:error` with the reason "unsupported source" (`fuente no soportada`).
- If the same bookmark is in two lists, its candidates are joined (a single job); if the job already exists, is still pending and has no destination yet, its `candidates` are extended.

**Failures:** a list that does not exist → `ConfigError` (stops and notifies through ntfy); 401/403 → `ConfigError`; network/5xx → retried on the next poll.

**How to test it:** `uv run pytest tests/unit/test_ingest_mark.py -k ingest`. For real: `tohoku run-once` and `tohoku status`.
