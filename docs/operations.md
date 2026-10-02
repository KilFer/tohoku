# Operating Tohoku

**English** · [Español](operations.es.md)

Examples use the reference setup: a Karakeep list called "Japan" feeding a `japon` trip destination.

## Day to day
- Save the link (Short, Reel or post) in a Karakeep list that appears in `config/destinos.yaml`. Nothing else.
- It is processed within ≤10 minutes. Reels take a few minutes longer (Whisper on CPU).
- Result in Karakeep: `jr:procesado` (processed) / `jr:revisar` (to review) / `jr:descartado` (discarded), all archived, or `jr:error` (stays visible on the Home page), plus `jr:destino:<destination>` with the chosen destination.

## Reviewing the tray
In Trilium, `<destination root> › Bandeja de revisión`. Each note carries `#revisar=<reasons>`:
- `geocodificacion-fallida` / `geocodificacion-ambigua` (geocoding failed / ambiguous): fix `#geolocation` (lat,lng) and `#googleMaps` if needed.
- `posible-duplicado` (possible duplicate): if it is the same thing as another note, copy what is useful into the other one and delete this one.
- `clasificacion-dudosa` (doubtful classification): the classifier hesitated between two destinations; if the note is not where it belongs, run `reprocess <id> --destino X`.
- `baja-confianza` / `clasificacion-incierta` (low confidence / uncertain classification): check that the content makes sense.
- `extraccion-fallida` (extraction failed): the note carries the caption and transcript; create the note by hand or reprocess.

When you are done: remove `#revisar` and remove the clone from the tray (right click → "Delete", only on the tray branch).

## Destinations: `config/destinos.yaml`
Which Karakeep lists are processed and how each one is published. A list can have several candidate destinations; then `classify` picks one with an LLM. Structure:

    listas:
      <karakeep-list-id>: [japon]         # Karakeep list id → candidate destinations
    destinos:
      japon:
        flujo: viaje                      # viaje | receta (docs/flujos/receta.md)
        raiz: jrRoot                      # label of the root note in Trilium
        descripcion: "Trip to Japan: ..."
        prompt: prompts/japon.md          # relative to config/
        pais: JP                          # ISO 3166-1; Places regionCode
        nombres_pais: [japon, japan, 日本]  # country names (lowercase, no accents) for addresses without postalAddress
        latitud: [20.0, 46.0]             # [min, max] of the country
        longitud: [122.0, 154.0]
        categorias_lugar: [templo, ..., otro]
        categorias_cosa: {souvenirs: Souvenirs, ..., otros: Otros}
        alias_ciudad: {tokio: [tokyo, 東京]}   # optional: city aliases
    clasificador:                         # optional
      modelo: ...                         # defaults to OPENROUTER_TEXT_MODEL
      modo: json_schema                   # or etiqueta
      confianza_minima: 0.5               # below this → discarded
      margen_revision: 0.15               # closer alternative → clasificacion-dudosa
    destino_por_defecto: japon                 # default destination; required with several destinations

- The service polls **all** the lists in the YAML. The YAML path is `DESTINOS_FILE` (default `config/destinos.yaml`).
- An invalid file (malformed YAML, unknown or misspelled key, `#` in the root, missing prompt, a list that points to a destination that does not exist) produces `Error de configuración` naming the key, and exits with code 2.
- The image contains `config/` (`COPY config ./config`) and the compose file mounts it read-only (`./config:/app/config:ro`): **editing `config/` does not require a rebuild**, `docker compose restart tohoku` is enough.
- After editing `config/` and restarting, check `docker compose logs tohoku`: a configuration error makes the container exit on startup (code 2) **without a ntfy notification**.
- The Japan prompt is `config/prompts/japon.md`. Only the markers `{{categorias_lugar}}` and `{{categorias_cosa}}` (the destination's categories) are substituted; the rest of the text is yours. If the LLM returns a category that is not one of the destination's, it is retried once with the error.
- `destino_por_defecto` (by default, the only destination) is the destination used by commands without `--destino`/`--lista` and when a bookmark has no recorded candidates, for example a `reprocess` of a bookmark that is not in `state.db`. A destination removed from the YAML does not stop the queue: `classify` ignores such candidates (falling back to `destino_por_defecto`) and only the job whose already decided or forced destination no longer exists fails (`jr:error`).
- The classifier is only mounted if some bookmark can have several candidates (a list with several destinations, or lists with different destinations, because ingest joins the candidates of all the lists a bookmark is in) and it is only called when there are several candidates. The preflight checks its model only in that case (in `json_schema` mode also that it supports structured output). With one candidate there is no LLM call. If there is no caption or transcript, classification uses images with `OPENROUTER_MODEL` (multimodal) instead of `clasificador.modelo`.
- Two destinations whose names differ only in case, accents or separators (`japon`/`Japón`) are a configuration error: the classifier could not tell them apart.
- `init-trilium [--destino X]` creates the structure under that destination's root (by default the only one; with several destinations `--destino` is required). `eval --destino X` evaluates with that destination's prompt (only `viaje` destinations; any other flow fails with a configuration error). `import-instagram ... [--lista ID]` chooses the target Karakeep list (by default the only one in the YAML; with several you must say which).

### Activating recipes

1. In Trilium, create the recipe book's root note and mark it `#jrRootRecetas` (for tests, `#jrRootRecetasTest`).
2. In `config/destinos.yaml`, add the `recetas` block, add the recipes Karakeep list under `listas` (`<id>: [recetas]`) and set `destino_por_defecto: japon` (required with several destinations). With one list carrying only `recetas` and another only `japon`, a bookmark in both goes through `classify` (there is a classifier as soon as there are two destinations).
3. `docker compose exec tohoku tohoku init-trilium --destino recetas` (`./config` is mounted read-only in the container, so `exec` already sees the edited YAML). It is idempotent, but it does not add new promoted attributes to a `Receta` template that already exists: if you change `atributos`, add the promoted ones by hand in Trilium.
4. `docker compose restart tohoku` (the first start checks the classifier's model). The order matters: if you restart before `init-trilium`, the preflight fails in `refresh()` and **all** queues are paused (including the others), with a configuration-error notification in ntfy.
5. See `docs/flujos/receta.md`.

### Adding a destination

A new trip destination (New Zealand, Portugal…) is configuration only: nothing in `src/` changes. A complete commented example (`nueva_zelanda`) is at the end of `config/destinos.example.yaml`, and it is tested in `tests/unit/test_destino_nz.py` with `tests/fixtures/destinos_tres.yaml`.

1. In Karakeep, create the destination's list and note its id.
2. In Trilium, create the destination's root note and mark it with its label (`#jrRootNZ`; for tests, the `Test` variant).
3. Write the prompt in `config/prompts/<destination>.md`: copy `config/prompts/japon.md` and adapt country, cities and regions; keep the fields and the markers `{{categorias_lugar}}` and `{{categorias_cosa}}`.
4. In `config/destinos.yaml`: add the destination's block (`flujo: viaje`, `raiz`, `descripcion`, `prompt`, ISO-2 `pais`, `nombres_pais`, `latitud`/`longitud` [min, max] of the country, `categorias_lugar`, `categorias_cosa`; `alias_ciudad` is optional: there are no per-country defaults, so every one of the other keys is required), its list under `listas` and, if it is the second destination, `destino_por_defecto: japon` (required with several destinations). The YAML is validated on load: an error shows with `docker compose exec tohoku tohoku init-trilium --destino <name>`.
5. `docker compose exec tohoku tohoku init-trilium --destino <name>` creates the map, "Comprar y comer", "Cultura y curiosidades" and the tray under the root (idempotent).
6. `docker compose restart tohoku`. **Always after `init-trilium`**: if the service starts with a destination that has no structure, the preflight fails in `refresh()` and all queues are paused, with a configuration-error notification in ntfy.
7. Try a few links (`import-instagram ... --lista <id> --limit 5`) and review the tray before importing more.

Particularities of non-Japan destinations: the Places search cache key carries a `<COUNTRY>|` prefix except for Japan; `palabras_genericas` is global (it does not distinguish destinations); categories without an icon use the generic pin; the `JAPAN_*_CONFIDENCE` thresholds in `.env` apply to every trip destination (the name was kept so existing `.env` files need no edits).

Code layout: the `viaje` flow lives in `src/tohoku/stages/` (+ `geo.py`, `trilium_layout.py`, `notes.py`) and the `receta` flow in `src/tohoku/flows/receta/`. Shared utilities are in neutral modules (`publishing.py`, `llm_json.py`). `reprocess --from extract` also repeats `cover` in recipes (canonical stage order).

## Commands
    docker compose exec tohoku tohoku status
    docker compose run --rm tohoku tohoku run-once   # only with the service stopped (lock)
    docker compose exec tohoku tohoku reprocess <bookmarkId> [<bookmarkId>...] --from extract
    docker compose exec tohoku tohoku reprocess --all-errors --from fetch
    docker compose logs -f tohoku

`run` and `run-once` take an exclusive lock on `DATA_DIR/tohoku.lock`: if another instance is already running (for example the container), `run-once` exits with code 3 and a clear message, and `run` logs it and exits with code 3. The other commands (`status`, `reprocess`…) do not need it.

`reprocess --from`: `fetch` (download again), `classify` (decide the destination again), `extract` (new prompt or model, no re-transcription), `geocode`, `resolve`, `publish`. A recipe job has no `geocode` stage and there is no `--from cover`: `--from geocode` acts as "from `cover`" (repeats `cover`, `resolve` and `publish`, and downloads again if the files were already cleaned up). The bookmarkId is in the bookmark's URL in Karakeep. Several ids are accepted at once; `--all-errors` puts **every** job in error back in the queue (useful after fixing cookies or the model).

`reprocess --destino X` forces the destination (it must be configured in `destinos.yaml`) and repeats from `classify`; `classify` respects the stored destination and does not call the LLM. Notes already published in Trilium are **not deleted**: if the destination changes, delete them by hand. Without `--destino`, `--from fetch|classify` forgets the destination and reclassifies; `--from extract` or later keeps it. If the classification was doubtful, the notes carry the reason `clasificacion-dudosa`.

## Changing the model
1. Fill `eval/cases.yaml` with 10-15 real cases.
2. `docker compose run --rm -v ./eval:/app/eval tohoku tohoku eval --model <model>` and the same with `--no-keyframes`.
3. Choose by hits (Places column) and cost; change `OPENROUTER_MODEL` in `.env` and run `docker compose up -d`.

On startup it checks that `OPENROUTER_MODEL` and `OPENROUTER_TEXT_MODEL` exist in OpenRouter and support structured JSON output (`response_format`/`structured_outputs`), and that `OPENROUTER_MODEL` supports images. If a model stops being available (for example "not a valid model", "No endpoints found"), the service pauses and notifies through ntfy once, without marking the links `jr:error`.
If vision cost is high: `REEL_KEYFRAMES_ENABLED=false`.

## Instagram cookies
When `jr:error` appears with "login required": export the instagram.com cookies (Netscape format) from a browser using a **secondary account** to `secrets/instagram_cookies.txt`, set `INSTAGRAM_COOKIES_FILE=/secrets/instagram_cookies.txt` in `.env`, run `docker compose up -d` and reprocess the failed ones with `reprocess <id> --from fetch`. The service works on a copy: the original file is never modified.
To avoid Instagram's rate limits, at least `INSTAGRAM_MIN_INTERVAL_SECONDS` (20 s by default) pass between two Instagram downloads. A "rate-limit reached" does not mark `jr:error`: it is retried after a wait.

## Importing your Instagram history
1. Instagram → Accounts Center → Your information and permissions → Download your information → only "Saved", **JSON** format.
2. Copy the .zip, the folder or just `saved_collections.json` to the server, for example into `data/instagram/`.
3. Dry run (only reads Karakeep, writes nothing): `docker compose exec tohoku tohoku import-instagram /data/instagram/saved_collections.json --collection "<collection name>" --limit 20 --dry-run`
4. Import in batches: the same command without `--dry-run`. `--limit N` counts only **new** links, from the **oldest to the newest**; running it again imports the next batch (already imported ones are detected with `check-url` and skipped). The final line shows `Pendientes` (pending).
5. Recommended pace: a batch of 50-100 a day, adjusting `OPENROUTER_DAILY_BUDGET_USD` and `PLACES_DAILY_LIMIT`. Each Reel takes ~2 min of CPU (Whisper large-v3).

Supported `saved_collections.json` formats: the classic one (a collection header followed by its posts) and the 2026 one (a list of collections with the posts nested in `label_values`). Instagram's mojibake (`OpciÃ³n`) is fixed when reading collection names.
Note: if a link was already in Karakeep with a different URL form (for example with `?igsh=`), a second bookmark may be created; the Trilium note is not duplicated.

## Error "Hay N notas que cumplen '#jrX'"

There are two notes with the same structure label as direct children of the same root (for example two `#jrRevision`); delete one or remove its label. Roots of other destinations nested inside do not count: the structure is looked up only among direct children.

## Notifications (ntfy)
Set `NTFY_URL`, `NTFY_TOPIC` and, if the server needs it, `NTFY_TOKEN`. Notifications are sent for: a definitive error on a link, a configuration error (the service pauses until it is fixed) and a daily limit reached (one notification per quota and day). When a quota is exhausted the queue does not stop: only the jobs that need it wait, and the rest keep downloading, transcribing and publishing. With `NTFY_DAILY_SUMMARY=true`, a summary is sent from 21:00.

## Costs and quotas
- Google Cloud Console → APIs → Places API (New) → Quotas: limit "SearchTextRequest per day" to the same value as `PLACES_DAILY_LIMIT` as a safety net. Google counts the day and the month in Pacific time; the service does too (quota counters and quota retries). The free Text Search Pro allowance is 5,000 a month.
- OpenRouter: `OPENROUTER_DAILY_BUDGET_USD`. `status` shows the day's usage.

## Cleanup
Optional key in `config/destinos.yaml`: `limpieza: {retencion_dias: N}` (default 30; integer >= 0; 0 = delete all stage results as soon as a job finishes).

- **When a job finishes** with any result except `error`: its `data/jobs/<id>/` directory (audio, frames, images) is deleted. Its `fetch` result is **not deleted**: the metadata (title, author, caption, URL, used by `publish`) is kept and marked `files_purged: true`. With `retencion_dias: 0` all its stage results are deleted instead.
- **On every service pass** (`purge`): the stage results of finished (`done`) jobs whose last update (`jobs.updated_at`) is older than `retencion_dias` are deleted, together with any `done` job directories still on disk (their `fetch` is marked `files_purged`, as on completion). Pending jobs and `error` jobs are never touched (their files are kept for diagnosis until a reprocess finishes them), nor are the `jobs` table or `published`.
- Safety: only simple ids, only direct children of `data/jobs`, symbolic links are not followed.
- The first pass after enabling it removes the directories of all finished jobs at once and writes a `limpieza jobs=N` line. Check with `du -sh data/jobs` before and after.

**Warning: consequences for `reprocess`.** A cleaned-up job keeps its `fetch` with `files_purged: true`. The pipeline only downloads again when it is going to run a stage that needs the files (`transcribe` or `extract`, flagged `needs_files`; `classify` only if it will classify with images: several candidates and no caption or transcript), and at most once per job (in the log: `bookmark=<id> re-descarga: los ficheros se limpiaron`):

| Command on a cleaned-up job | What it downloads or repeats |
|---|---|
| `reprocess --from geocode`, `--from resolve` or `--from publish` (within the retention) | Downloads nothing, and does not fail even if the Reel no longer exists: it uses the stored transcript and extraction |
| `reprocess --from extract` or `--from classify` | Downloads again (it needs frames and images); if the Reel was deleted or restricted, it ends in `jr:error` |
| `reprocess --from fetch` | As always: downloads and repeats everything |
| After the retention (`retencion_dias`), or with `retencion_dias: 0` | No stage result remains: everything is redone (download, Whisper, LLM and Places, with their quota and cost) |

`transcribe` also needs the files, but it is not a valid `--from`: it is repeated with `--from fetch`. Jobs in `error` keep their files (they are not cleaned) until a reprocess finishes them. Recommendation: reprocess from `extract`/`classify` in small batches, so as not to hit Instagram's rate limits (`INSTAGRAM_MIN_INTERVAL_SECONDS`).

## Backups
`data/state.db` holds the queue state. If it is lost, bookmarks already tagged `jr:*` are not reprocessed; the Trilium notes have their own `tohoku.json` attachment.
