# Stage 5 — geocode

**English** · [Español](05-geocode.es.md)

**What it does:** looks up every extracted place in Google Places and gets coordinates, address, `place_id` and a Google Maps link.

**Input:** `Extraction.lugares` (only if the content was not discarded for not belonging to the destination).
**Output:** `GeocodeResult {outcomes: [GeoOutcome {lugar_index, match, review_reason}]}`.

**Dependencies:** Google Places API (New) — Text Search Pro; daily `places_calls` counter in `state.db`.

**Configuration:** `GOOGLE_PLACES_API_KEY`, `PLACES_DAILY_LIMIT` (150 by default). From the destination (`config/destinos.yaml`, `viaje` flow): `pais` (ISO code, `JP`; it is also the request's `regionCode`), `nombres_pais`, `latitud`/`longitud` (coordinate box) and `alias_ciudad`; all of them are required except `alias_ciudad` (there are no per-country defaults; see the `japon` block of `config/destinos.example.yaml`). The examples on this page describe Japan.

**Request:** `POST places:searchText` with `regionCode=JP`, `languageCode=es`, `pageSize=5` and an `X-Goog-FieldMask` limited to Pro fields (`id, displayName, formattedAddress, location, googleMapsUri, types, postalAddress, addressComponents`). Opening hours and ratings (Enterprise) are not requested.

**Validation and decision:**
1. Query `consulta_busqueda`; if there is no valid result, a second query with `nombre_local`.
2. Valid = inside Japan (coordinate box + country `JP`, taken from `postalAddress.regionCode` or, if missing, from the `country` component of `addressComponents`: areas — cities, neighbourhoods, islands — come without `postalAddress`; with `regionCode=JP` Google omits the country from `formattedAddress`, so the text "Japón/Japan/日本" is only used if both are missing) and in the expected city, searched in the address and in the prefecture/locality of `postalAddress` and `addressComponents` (with aliases: Tokio/Tokyo/東京, Kioto/Kyoto/京都…).
3. A single valid result → accepted. If there are several, the one with the **most similar name** to the extracted one is chosen (not necessarily Google's first): equal > one contains the other > similarity ≥ 0.6. "Equal" allows a different word order, translated generic words (shrine/santuario/jinja/jingu, tower/torre, lake/lago, station/estación/eki, temple/templo, park/parque…) and city aliases (Kioto/Kyoto): "Torre de Kioto" = "Kyoto Tower". This equivalence is only used to compare names, not in the `#jrNombreNorm` keys. If that best match is unique, it is accepted without review; if it ties with others within 300 m (`SAME_PLACE_RADIUS_M`: the area and its point of interest, the building and the tower; measured on real cases: 4-165 m), it is accepted too, because they are the same place.
3b. No valid results in the expected city but a result in Japan with an **equal name** → accepted by applying rule 3 to those results (the LLM gets the city wrong for places on the outskirts: Tokyo DisneySea is in Chiba).
4. Several valid results with no similar name (the first is used), or a tie between the best ones more than 300 m apart (for example two branches), or only results in Japan in another city and no equal name → goes to review (`geocodificacion-ambigua`).
5. Nothing in Japan → no coordinates and goes to review (`geocodificacion-fallida`).

**Quota:** the daily `places_calls` counter is limited by `PLACES_DAILY_LIMIT` (150 by default ≈ 4,500 a month, below the 5,000 free). The quota counters' "day" is the **Pacific time** one, like Google's (it renews at Pacific midnight): this way the service does not call Google when its quota for the day is already exhausted. On reaching the limit the job is rescheduled to the next Pacific midnight + 5 min and the pass continues with the other jobs: those reaching `geocode` with new searches are parked the same way without calling Google; those that have everything cached, or are in earlier stages, advance. Also set a daily quota in Google Cloud Console (APIs → Places API (New) → Quotas) equal to `PLACES_DAILY_LIMIT`.

**Search cache:** the key includes the destination's country: Japan's go without a prefix and another country's carry the prefix `<COUNTRY>|`, so a New Zealand search never reuses a Japan one. Every Places query (normalized: lowercase and spaces) is stored in the `places_cache` table of `state.db` for 30 days (`CACHE_MAX_AGE`), including those that return nothing. A repeated query ("dotonbori osaka" appears in 18 videos) is resolved without calling Google or spending quota. Measured on a real import: 31% of queries were repeats. If the Places client changes (requested fields or their interpretation), empty the table: `DELETE FROM places_cache`.

**Failures:** invalid API key → `ConfigError`; 429/5xx → retry.

**How to test it:** `uv run pytest tests/unit/test_geocode.py tests/unit/test_places_client.py`.

**Areas:** cities, neighbourhoods and islands (Kyoto, Akihabara, Hokkaido…) are geocoded like any place: a pin at the central point Google gives and deduplication by `googlePlaceId`.
