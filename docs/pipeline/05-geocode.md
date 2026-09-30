# Etapa 5 — geocode

**Qué hace:** busca cada lugar extraído en Google Places y obtiene coordenadas, dirección, `place_id` y enlace a Google Maps.

**Entrada:** `Extraction.lugares` (solo si el contenido no se descartó como "no Japón").
**Salida:** `GeocodeResult {outcomes: [GeoOutcome {lugar_index, match, review_reason}]}`.

**Dependencias:** Google Places API (New) — Text Search Pro; contador diario `places_calls` en `state.db`.

**Configuración:** `GOOGLE_PLACES_API_KEY`, `PLACES_DAILY_LIMIT` (150 por defecto).

**Petición:** `POST places:searchText` con `regionCode=JP`, `languageCode=es`, `pageSize=5` y `X-Goog-FieldMask` limitado a campos Pro (`id, displayName, formattedAddress, location, googleMapsUri, types, postalAddress, addressComponents`). No se piden horarios ni valoraciones (Enterprise).

**Validación y decisión:**
1. Consulta `consulta_busqueda`; si no hay resultado válido, segunda consulta con `nombre_local`.
2. Válido = dentro de Japón (caja de coordenadas + país `JP`, tomado de `postalAddress.regionCode` o, si falta, del componente `country` de `addressComponents`: las áreas —ciudades, barrios, islas— no traen `postalAddress`; con `regionCode=JP` Google omite el país en `formattedAddress`, así que el texto "Japón/Japan/日本" solo se usa si faltan ambos) y en la ciudad esperada, buscada en la dirección y en la prefectura/localidad de `postalAddress` y `addressComponents` (con alias: Tokio/Tokyo/東京, Kioto/Kyoto/京都...).
3. Un único válido → aceptado. Si hay varios, se elige el de **nombre más parecido** al extraído (no necesariamente el primero de Google): igual > uno contiene al otro > similitud ≥ 0.6. "Igual" admite otro orden de palabras, palabras genéricas traducidas (shrine/santuario/jinja/jingu, tower/torre, lake/lago, station/estación/eki, temple/templo, park/parque...) y alias de ciudad (Kioto/Kyoto): "Torre de Kioto" = "Kyoto Tower". Esta equivalencia solo se usa para comparar nombres, no en las claves `#jrNombreNorm`. Si ese mejor es único, se acepta sin revisión; si empata con otros que están a menos de 300 m (`SAME_PLACE_RADIUS_M`: la zona y su punto de interés, el edificio y la torre; medido en casos reales: 4-165 m), también, porque son el mismo sitio.
3b. Sin válidos en la ciudad esperada pero con un resultado en Japón de **nombre igual** → se acepta aplicando la regla 3 a esos resultados (el LLM equivoca la ciudad de sitios de las afueras: Tokyo DisneySea está en Chiba).
4. Varios válidos sin ningún nombre parecido (se usa el primero), o empate entre los mejores a más de 300 m (p. ej. dos sucursales), o solo resultados en Japón en otra ciudad y sin nombre igual → va a revisión (`geocodificacion-ambigua`).
5. Nada en Japón → sin coordenadas y a revisión (`geocodificacion-fallida`).

**Cuota:** contador diario `places_calls` limitado por `PLACES_DAILY_LIMIT` (150 por defecto ≈ 4.500/mes, por debajo de las 5.000 gratis). El "día" de los contadores de cuota es el de **hora del Pacífico**, como el de Google (renueva a medianoche PT = 09:00 en España en verano): así el servicio no llama a Google cuando su cuota del día ya está agotada. Al llegar al límite el job se reprograma a la siguiente medianoche del Pacífico + 5 min y la pasada sigue con los demás jobs: los que lleguen a `geocode` con búsquedas nuevas se aparcan igual sin llamar a Google; los que lo tengan todo en caché, o estén en etapas anteriores, avanzan. Configura además una cuota diaria en Google Cloud Console (APIs → Places API (New) → Cuotas) igual a `PLACES_DAILY_LIMIT`.

**Caché de búsquedas:** cada consulta a Places (normalizada: minúsculas y espacios) se guarda en la tabla `places_cache` de `state.db` durante 30 días (`CACHE_MAX_AGE`), también las que no devuelven nada. Una consulta repetida ("dotonbori osaka" aparece en 18 vídeos) se resuelve sin llamar a Google ni gastar cuota. Medido el 2026-09-29: el 31 % de las consultas eran repetidas. Si cambia el cliente de Places (campos pedidos o su interpretación), vaciar la tabla: `DELETE FROM places_cache`.

**Fallos:** API key inválida → `ConfigError`; 429/5xx → reintento.

**Cómo probarla:** `uv run pytest tests/unit/test_geocode.py tests/unit/test_places_client.py`.

**Áreas (2026-09-29):** ciudades, barrios e islas (Kioto, Akihabara, Hokkaido…) se geocodifican como cualquier lugar: pin en el punto central que da Google y deduplicación por `googlePlaceId`. Antes se descartaban por no traer `postalAddress` y acababan en la Bandeja como `geocodificacion-fallida`, repetidas en cada fuente.
