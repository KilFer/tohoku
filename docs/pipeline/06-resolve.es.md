# Etapa 6 — resolve

[English](06-resolve.md) · **Español**

**Qué hace:** compara lo extraído con lo que ya hay en Trilium y decide, elemento a elemento, crear, fusionar o marcar como alias; además calcula los motivos de revisión.

**Entrada:** `ExtractResult`, `GeocodeResult`, estructura de Trilium.

**Salida:** `ResolveResult {items: [PlannedItem {key, kind, index, action, existing_note_id, alias_of, review_reasons}]}`.

**Dependencias:** Trilium ETAPI (búsqueda de notas por atributos bajo la raíz `#jrRoot`), resultados de `extract` y `geocode`.

**Reglas:**
- Extracción fallida → un único elemento `fallo` con `extraccion-fallida`.
- `confianza_destino` < 0.4 → sin elementos (resultado `descartado`).
- 0.4 ≤ `confianza_destino` < 0.7 → todos los elementos con `clasificacion-incierta`.
- Si `classify` marcó la clasificación como dudosa (alternativa cercana), todos los elementos llevan además `clasificacion-dudosa`.
- Elemento con `confianza` < 0.7 → `baja-confianza`.
- Lugar: busca `#googlePlaceId` bajo la raíz; si no hay, un lugar con el mismo `#jrNombreNorm` cuyo `#geolocation` esté a menos de 300 m (Google a veces tiene dos fichas para el mismo sitio: "Omoide Yokocho", dos placeId a 45 m) → `merge` (conserva la ficha de la nota existente) o `create`. Sin coordenadas → busca `#jrTipo=lugar #jrNombreNorm="<normalizado>"` bajo la raíz → `merge` o `create`, siempre con el motivo de geocodificación (así un lugar que Google no encuentra no se repite en cada fuente). Mismo `place_id` (o, sin ficha, mismo nombre normalizado) dos veces en la misma fuente → `alias` del primero.
- Cosa: busca `#jrTipo=cosa #jrNombreNorm="<normalizado>"` en "Comprar y comer" → `merge`; si no, compara con todas las cosas y, si alguna tiene similitud ≥ 0.85, `create` + `posible-duplicado`. Mismo nombre normalizado dos veces → `alias`.
- Otros → siempre `create`. Si el contenido es del destino pero no hay ningún elemento → `otro:resumen` con el resumen de la fuente.

**Configuración:** `DESTINATION_MIN_CONFIDENCE`, `DESTINATION_REVIEW_CONFIDENCE`, `ITEM_REVIEW_CONFIDENCE`, `COSA_DUPLICATE_SIMILARITY`.

**Fallos:** errores de Trilium → reintento; estructura ausente → `ConfigError`.

**Cómo probarla:** `uv run pytest tests/unit/test_resolve.py`.
