# Data model in Trilium

**English** · [Español](trilium-model.es.md)

The root is a note of yours (in the reference example, **`Home › Viajes › Ideas de Japón`**), marked by hand once with `#jrRoot`. Each destination's root label is the `raiz` key of `config/destinos.yaml` (Japan: `jrRoot`; a new destination would use `jrRoot<Destination>`, for example `jrRootNZ`). The structure below it is created with `tohoku init-trilium [--destino X]`. The service finds everything by attributes, so you can move or rename the notes.

The `jr` prefix of all labels and attributes (`#jr*`, and `jr:*` in Karakeep) is kept on purpose: it stands for *Japan Reader*, the project's original name, and for **JR**, the company that runs the Tohoku Shinkansen.

Note titles are generated in Spanish (the English meaning is in parentheses).

    Ideas de Japón                    #jrRoot
     ├── Mapa de lugares              #jrMapa   (book + ~template=_template_geo_map → Geo Map)
     ├── Comprar y comer              #jrComprar   (things to buy and eat)
     │    └── Souvenirs · Comida · Cadenas · Cosmética · Otros   #jrCategoria=<key>
     ├── Cultura y curiosidades       #jrCultura   (culture and curiosities)
     ├── Bandeja de revisión          #jrRevision  (review tray)
     └── Plantillas                   #jrPlantillas (templates)
          ├── Lugar                   #template (+ promoted definitions: visitado, prioridad, ciudad, categoria)
          └── Cosa                    #template (+ comprado, categoria)

`tohoku init-trilium` creates whatever is missing (idempotent). Structure notes are looked up only as direct children of the destination's root (categories, of "Comprar y comer"), so one destination's root can be nested inside another's without their sections getting mixed up.

## Lugar note (place; child of "Mapa de lugares")

- **Managed attributes:** `#jrItem="<bookmark_id>:<identity>"` (the item's identity **by content**, not by position: `b1:lugar:<place_id>` if it has a Google card, `b1:lugar:n:<normalized name>` if not; the first attribute written, so an interrupted creation can be resumed without duplicating), `#geolocation="lat,lng"`, `#googlePlaceId`, `#googleMaps`, `#ciudad`, `#region`, `#categoria`, `#nombreLocal`, `#fuentes`, `#iconClass`, `#jrTipo=lugar`, `#jrNombreNorm` (normalized name; the deduplication key for places without a Google card), `~template=Lugar`.
- **Your attributes (never touched):** `#visitado`, `#prioridad` and any other you add.
- **Body:** Resumen (summary) · Qué hacer / comer (what to do / eat) · Consejos prácticos (practical tips) · Google Maps link · Fuentes (sources) · **Mis notas** (your notes).

## Cosa note (thing; child of its category in "Comprar y comer")

- **Attributes:** `#jrItem="<bookmark_id>:cosa:<normalized name>"`, `#jrTipo=cosa`, `#jrNombreNorm` (normalized name, deduplication key), `#categoria`, `#fuentes`, `#iconClass`, `~template=Cosa`, `~dondeComprar` (where to buy) → Lugar notes when the source recommends a specific shop.
- **Body:** Resumen · Dónde conseguirlo (where to get it) · Consejos · Fuentes · **Mis notas**.

## Otro note (other; child of "Cultura y curiosidades")

Title + content + sources. No deduplication. It carries `#jrItem="<bookmark_id>:otro:<normalized title>"`. The synthetic note (destination content without items) is titled with the source's title; if that is empty, with the first line of the description (max. 80 characters); if there is none either, "Sin título" (untitled).

## Failed-extraction note (in "Bandeja de revisión")

It carries `#jrItem="<bookmark_id>:fallo"` and `#jrTipo=fallo`. Body: link, error, description and transcript.

## Structured data

Every note carries a `tohoku.json` attachment with its data (summary, tips, sources, Google card). It is the source of truth for merges: do not delete it.

## Merge rules

- **Lugar:** same `#googlePlaceId` → same note; otherwise same `#jrNombreNorm` with the pin within 300 m (two Google cards for the same place) → same note; without a Google card, same `#jrNombreNorm`. The source is added, `#fuentes` goes up and the LLM rewrites Resumen, Qué hacer and Consejos to integrate the new material.
- **Cosa:** same `#jrNombreNorm` → same note. If there is a similar but not identical one (similarity ≥ 0.85), a new note is created and sent to review (`posible-duplicado`).
- **Same source again** (reprocessing): its entry is updated; it is not duplicated and the LLM is not called. If the note has **only** that source, it is regenerated entirely with the new extraction (keeping the Google card if the new one lacks it, and always "Mis notas"). If other sources also contributed, only this source's entry is replaced.
- **Natural key before creating:** even if the plan says `create`, if a note with the same `#googlePlaceId` (place) or `#jrNombreNorm` (thing) already exists, it is merged into it.
- **Managed attributes you correct:** if you change or correct a managed attribute (`#geolocation`, `#googleMaps`, `#categoria`, `#ciudad`, `#iconClass`…), later merges respect it: it is rewritten only if it is missing or still has the value the service wrote. `#fuentes` and `#jrTipo` are always written.
- **Mis notas:** everything under the "Mis notas" heading is always kept. If you delete the heading, on the next merge all the previous content moves under a new "Mis notas".

## Review tray

Doubtful notes are **cloned** into the tray (they also stay in their place) with `#revisar=<reasons>`: `geocodificacion-fallida`, `geocodificacion-ambigua`, `posible-duplicado`, `baja-confianza`, `clasificacion-incierta`, `clasificacion-dudosa` (the classifier hesitated between two destinations: check that the note is in the right destination; if not, `reprocess --destino`), `extraccion-fallida`. Reviewing = fixing the note, removing `#revisar` and removing the clone from the tray. The service does not put a note back in the tray if you took it out, unless a new source with reasons arrives; and it takes the note out itself if a reprocess resolves all its reasons.

## `receta` flow: recipe book and Receta note

A destination with `flujo: receta` (for example root `#jrRootRecetas`; see `docs/flujos/receta.md`):

    Recetas                           #jrRootRecetas
     ├── Recetario                    #jrColeccion (book, #viewType=table|grid|list)
     ├── Bandeja de revisión          #jrRevision
     └── Plantillas                   #jrPlantillas
          └── Receta                  #template + #label:<attribute>=promoted,single,<type>

**Receta note** (child of the Recetario, with `~template=Receta`):
- Attributes: `#jrTipo=receta`, `#jrItem="<bookmark_id>:receta:<normalized title>"`, `#jrNombreNorm`, `#fuentes`, `#iconClass`, plus the promoted ones the service writes: `tipo_plato` (dish type), `cocina` (cuisine), `tiempo_min` (minutes), `raciones` (servings), `dificultad` (difficulty) (those you correct are respected).
- `probada` (tried) and `valoracion` (rating) (and any attribute in `atributos_usuario` or added by hand) are yours: the service never writes them.
- Body: cover, Resumen, Ingredientes (grouped by `grupo`), Preparación, Consejos, Fuentes and, under "Mis notas", your own content (always kept).
- Cover: an image attachment `portada.jpg` (JPEG, longest side `IMAGE_MAX_SIDE`) embedded with `<img src="api/attachments/<id>/image/portada.jpg">` (format verified on Trilium 0.106).
- A `tohoku.json` attachment with the structured data (source of truth; do not delete it).
- No merging between sources: one link = one recipe. If another one with a similar title exists, the new one is cloned into the tray with `posible-duplicado`.
