# `receta` flow

**English** · [Español](receta.es.md)

**What it does:** turns a cooking Reel, Short or Instagram post into **a recipe note** (ingredients, steps, tips, cover) inside the Trilium recipe book. One link = one recipe. There is no merging between sources: two links with the same recipe give two notes, and if the titles are very similar the new one goes to the tray as `posible-duplicado`.

It is enabled with a destination in `config/destinos.yaml` with `flujo: receta`. The common stages (`fetch`, `transcribe`, `classify`) are the usual ones; the flow's own stages are `extract → cover → resolve → publish`. It is disabled by default: the `recetas` block is commented out in `config/destinos.example.yaml`.

## Structure in Trilium

    Recetas                           #jrRootRecetas (you create the root by hand)
     ├── Recetario                    #jrColeccion (book, #viewType=<view>)
     │    └── <Receta>                #jrTipo=receta #jrItem #jrNombreNorm (~template=Receta)
     ├── Bandeja de revisión          #jrRevision
     └── Plantillas                   #jrPlantillas
          └── Receta                  #template + promoted attributes

Note details are in `docs/trilium-model.md`. `tohoku init-trilium --destino recetas` creates whatever is missing (idempotent).

## Stages

| Stage | What it does |
|---|---|
| `extract` | Multimodal LLM (`config/prompts/recetas.md`, no markers): relevance (`relacionado_destino`, `confianza_destino`), title, summary, ingredients (with `grupo`), steps, tips, attributes and `portada` (an index among images + frames). It needs the job's files. |
| `cover` | Chooses the cover image and stores it as `cover.jpg` (longest side `IMAGE_MAX_SIDE`). If the LLM gives no `portada`, a post uses its first image and a video its last frame (usually the finished dish); with no images or frames there is no cover. |
| `resolve` | Decides: not a recipe → no items (`descartado`); otherwise a single item with review reasons (`clasificacion-incierta`, `clasificacion-dudosa`, `baja-confianza`, `posible-duplicado`). Failed extraction → a failure note in the tray. |
| `publish` | Creates or updates the note (identity `#jrItem="<bookmark>:receta:<name_key(title)>"`; on reprocessing the note of the same link is reused even if the title changes; the title is only updated if the user has not renamed the note), uploads the cover as an attachment, keeps "Mis notas" and syncs the tray. |

## Configuration

    recetas:
      flujo: receta
      raiz: jrRootRecetas
      descripcion: "Cooking recipes: ..."
      prompt: prompts/recetas.md
      vista: table                  # table | grid | list
      # optional; defaults: tipo_plato, cocina, tiempo_min, raciones, dificultad, probada, valoracion
      atributos: {tipo_plato: text, cocina: text, probada: boolean}   # promoted on the template (text|number|boolean)
      atributos_usuario: [probada]                                    # never written by the service

- The service only **writes** the attributes that are extraction fields (`tipo_plato`, `cocina`, `tiempo_min`, `raciones`, `dificultad`), and respects those you correct (same rule as in `viaje`). `atributos_usuario` are never written. Any other attribute you add by hand is yours.
- `atributos` only applies when the template is created: `init-trilium` does **not add** new promoted attributes to an existing `Receta` template (add them by hand in Trilium).
- How to enable it: see "Activating recipes" in `docs/operations.md`.

## Failures

- Something in the recipe book is missing → `ConfigError` in the preflight ("run `tohoku init-trilium --destino …`").
- Invalid extraction after the retry → a `jrTipo=fallo` note in the tray, reason `extraccion-fallida`.
- Content that is not a recipe → `descartado`: no note and no `jr:destino:<d>` tag.
- The cover fails to upload (transient error) → the job is retried; the note is not duplicated (idempotent through `#jrItem`).
- Instagram Reels with audience restriction or "empty media": same as in the `viaje` flow (docs/pipeline/02-fetch.md).

## How to test it

- Offline: `uv run pytest tests/unit/test_flow_receta.py tests/unit/test_receta_*.py`.
- Manual integration (real services, ask first): a `#jrRootRecetasTest` note, `init-trilium --destino recetas` and 2-3 recipe Reels; check the Table view and the cover by hand. Reprocess with `reprocess <id> --from extract` (it also repeats `cover`).
