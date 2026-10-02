# Tohoku

**English** · [Español](README.es.md)

A cataloguer for travel videos. Tohoku turns the videos and posts you save in [Karakeep](https://karakeep.app) (YouTube Shorts, Instagram Reels and Instagram posts) into structured notes in [Trilium Notes](https://github.com/TriliumNext/Trilium): places on a map, things to buy or eat, curiosities… or cooking recipes with ingredients and steps.

Each Karakeep list is assigned to one or more **destinations** (a trip, a recipe book…) in `config/destinos.yaml`. Tohoku downloads the content, transcribes it, passes it to a multimodal LLM, geolocates the places, deduplicates against what you already have and publishes to Trilium. Anything it is unsure about goes to a **review tray**.

Japan is the reference example throughout this documentation: the project was built to plan a trip to Japan from hundreds of saved Reels, and the default settings (country, cities, categories, prompt) describe Japan. A new trip destination (New Zealand, Portugal…) is just configuration.

<!-- CAPTURE: Geo Map of a trip with its places (docs/img/geo-map.png) -->

> **Name.** The project used to be called *japan-reader*. The `jr` prefix of labels (`jr:*` in Karakeep) and attributes (`#jr*` in Trilium) is kept on purpose: it stands for *Japan Reader* and for **JR**, the company that runs the Tohoku Shinkansen.

> **Language of the generated notes.** The notes Tohoku writes to Trilium (section names, headings such as "Mis notas", review reasons), the YAML configuration keys (`listas`, `destinos`, `flujo`…), the CLI and log messages and the extraction prompts in `config/prompts/` are in Spanish. The documentation uses those literal names, with a translation where it helps. The prompts are plain text files you adapt per destination: write them in the language you want the notes in.

## What you get

**`viaje` flow** (one destination per country; Japan is the reference example):
- A **Geo Map** with one note per place (address, coordinates and Google Places card, category, sources, "Mis notas" for your own notes).
- **Comprar y comer** (things to buy and eat): products, dishes and chains, grouped by category.
- **Cultura y curiosidades** (culture and curiosities): whatever is neither a place nor a purchase.

<!-- CAPTURE: a place note with its sources (docs/img/lugar.png) -->
<!-- CAPTURE: the "Comprar y comer" section (docs/img/comprar.png) -->

**`receta` flow**:
- A **recipe book** in Table view with columns for dish type, cuisine, time, servings, difficulty, and `probada` (tried) / `valoracion` (rating) for you.
- Each recipe has a cover (a frame or image from the post), summary, grouped ingredients, numbered steps, tips and sources.

<!-- CAPTURE: recipe book in Table view (docs/img/recetario-tabla.png) -->
<!-- CAPTURE: recipe book in Grid view with covers (docs/img/recetario-cuadricula.png) -->
<!-- CAPTURE: a recipe note (docs/img/receta.png) -->

**In every destination:**
- **Review tray** (`Bandeja de revisión`): low confidence, doubtful geolocation, possible duplicates or uncertain classification.
- **Your edits are respected**: reprocessing a link regenerates the generated content, but never touches "Mis notas", the attributes you corrected or a title you changed.
- **Classifier**: if a list feeds several destinations, an LLM decides where each link goes (or discards it).
- Optional notifications through [ntfy](https://ntfy.sh).

<!-- CAPTURE: review tray (docs/img/bandeja.png) -->

## How it works

```
Karakeep (lists)
  → ingest      new links from the configured lists
  → fetch       yt-dlp / gallery-dl + ffmpeg (audio, key frames, images)
  → transcribe  faster-whisper (CPU)
  → classify    only if the link has several possible destinations
  → destination flow
      viaje:  extract (LLM) → geocode (Google Places) → resolve (deduplication) → publish
      receta: extract (LLM) → cover → resolve → publish
  → mark        jr:* tag in Karakeep, and the bookmark is archived
```

Every stage stores its result in SQLite: a transient failure is retried from where it stopped, and `reprocess --from <stage>` repeats only what is needed. Each stage is described in [`docs/pipeline/`](docs/pipeline/).

## Requirements

- **Docker** and Docker Compose (or Python 3.12 with [uv](https://docs.astral.sh/uv/) for development).
- **Karakeep** with an API key.
- **Trilium Notes** ≥ 0.106 with an ETAPI token.
- **OpenRouter**: an API key and a multimodal model (one that accepts images).
- **Google Places API (New)**: only for `viaje` destinations (Text Search Pro).
- **ntfy** (optional) for notifications.
- **CPU and memory**: Whisper `large-v3` on CPU takes ~90 s per Reel; the reference deployment is limited to 6 CPUs / 6 GB. Small Whisper models get proper nouns wrong.

### Approximate costs

Measured with ~1,400 real links:
- **LLM**: ~$0.001 per link.
- **Google Places**: ~1.2 calls per place and ~3 places per link for travel content. With the free Text Search Pro allowance (5,000 a month) and the 30-day search cache, about 150 links a day fit comfortably. Cap the spend with `PLACES_DAILY_LIMIT` and with a daily quota in Google Cloud Console.
- **Time**: ~1-2 min per Reel (mostly transcription).

## Getting started

1. Copy the example configuration and fill it in:
   ```
   cp .env.example .env
   cp config/destinos.example.yaml config/destinos.yaml   # TODO: example file not created yet (see docs/publicacion.md)
   ```
2. **Docker network**: `docker-compose.yml` uses an external network to reach Karakeep and Trilium by container name. Set the network name, and `KARAKEEP_URL` / `TRILIUM_URL` in `.env`, to match your installation. <!-- TODO: make the network configurable -->
3. In `config/destinos.yaml`, assign each Karakeep list to its destinations and define each destination (flow, label of the root note in Trilium, prompt). See [Destinations](#destinations).
4. In Trilium, add the root label (for example `#jrRoot`) to the note under which you want the destination's structure.
5. Create the structure and start:
   ```
   docker compose build
   docker compose run --rm tohoku tohoku init-trilium --destino <name>
   docker compose up -d
   docker compose logs -f tohoku
   ```

The service polls Karakeep every `POLL_INTERVAL_MINUTES` (10 by default).

## Destinations

```yaml
listas:
  <karakeep-list-id>: [japon]            # one list → one destination
  <karakeep-tray-list-id>: [japon, recetas]   # several → the classifier decides
destino_por_defecto: japon                    # required with several destinations
destinos:
  japon:
    flujo: viaje
    raiz: jrRoot                         # label of the root note in Trilium
    descripcion: "Trip to Japan: places, food, shopping and culture"
    prompt: prompts/japon.md
    pais: JP
  recetas:
    flujo: receta
    raiz: jrRootRecetas
    descripcion: "Cooking recipes: dishes and drinks with ingredients and steps"
    prompt: prompts/recetas.md
```

- A new trip destination (for example New Zealand) is added **with configuration only**: a block in the YAML and a prompt. A commented example is included in `config/destinos.example.yaml`.
- To activate a destination: edit the YAML → `init-trilium --destino <name>` → restart the service.
- Root notes of two destinations of **different types** can be nested one inside the other; two of the same type cannot.

Full guide: [`docs/operations.md`](docs/operations.md) ("Destinations", "Adding a destination").

## Commands

Inside the container: `docker compose exec tohoku tohoku <command>`.

| Command | Purpose |
|---|---|
| `run` | The service loop (what the container starts). |
| `run-once` | A single cycle (with the service stopped: they share a lock). |
| `init-trilium [--destino X]` | Creates the destination's structure in Trilium (idempotent). |
| `status` | Jobs by state, the day's usage, retries and latest errors. |
| `reprocess <id>... \| --all-errors [--from <stage>] [--destino X]` | Processes links again from a given stage. |
| `import-instagram <export.json> [--collection] [--lista ID] [--limit N] [--dry-run]` | Imports your saved posts from an Instagram data export into Karakeep, in batches. |
| `eval [--model] [--keyframes/--no-keyframes] [--destino X]` | Compares models or settings on real cases (`viaje` destinations only). |

## Documentation

- Pipeline stages: [`docs/pipeline/`](docs/pipeline/) (`01-ingest.md` … `08-mark.md`, `02b-classify.md`).
- Recipe flow: [`docs/flujos/receta.md`](docs/flujos/receta.md).
- Structure in Trilium (notes, labels, templates): [`docs/trilium-model.md`](docs/trilium-model.md).
- Daily operation, destinations, reprocessing, cleanup and common errors: [`docs/operations.md`](docs/operations.md).

Every document has a Spanish version next to it, with the `.es.md` suffix.

## Development

```
uv sync
uv run pytest                  # unit tests, no network
uv run pytest -m integration   # against real services (see tests/integration/test_live.py)
```

## Notice

Tohoku downloads content from Instagram and YouTube with yt-dlp and gallery-dl for personal use: organising what you yourself have saved. Downloading content may go against those platforms' terms of service; use it at your own risk and respect the rights of the authors. Notes always keep the link and the author of the source.

## License

[MIT](LICENSE).
