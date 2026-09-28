# Etapa 5 — geocode

**Qué hace:** busca cada lugar extraído en Google Places y obtiene coordenadas, dirección, `place_id` y enlace a Google Maps.

**Entrada:** `Extraction.lugares` (solo si el contenido no se descartó como "no Japón").
**Salida:** `GeocodeResult {outcomes: [GeoOutcome {lugar_index, match, review_reason}]}`.

**Dependencias:** Google Places API (New) — Text Search Pro; contador diario `places_calls` en `state.db`.

**Configuración:** `GOOGLE_PLACES_API_KEY`, `PLACES_DAILY_LIMIT` (150 por defecto).

**Petición:** `POST places:searchText` con `regionCode=JP`, `languageCode=es`, `pageSize=5` y `X-Goog-FieldMask` limitado a campos Pro (`id, displayName, formattedAddress, location, googleMapsUri, types`). No se piden horarios ni valoraciones (Enterprise).

**Validación y decisión:**
1. Consulta `consulta_busqueda`; si no hay resultado válido, segunda consulta con `nombre_local`.
2. Válido = dentro de Japón (caja de coordenadas + "Japón/Japan/日本" en la dirección) y en la ciudad esperada (con alias: Tokio/Tokyo/東京, Kioto/Kyoto/京都...).
3. Un único válido, o el primero con nombre parecido → aceptado.
4. Varios válidos con nombres distintos, o solo resultados en Japón pero en otra ciudad → se usa el primero y va a revisión (`geocodificacion-ambigua`).
5. Nada en Japón → sin coordenadas y a revisión (`geocodificacion-fallida`).

**Cuota:** contador diario `places_calls` limitado por `PLACES_DAILY_LIMIT` (150 por defecto ≈ 4.500/mes, por debajo de las 5.000 gratis). Al llegar al límite el job espera al día siguiente. Configura además una cuota diaria en Google Cloud Console (APIs → Places API (New) → Cuotas).

**Fallos:** API key inválida → `ConfigError`; 429/5xx → reintento.

**Cómo probarla:** `uv run pytest tests/unit/test_geocode.py tests/unit/test_places_client.py`.
