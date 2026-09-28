# Etapa 6 — resolve

**Qué hace:** compara lo extraído con lo que ya hay en Trilium y decide, elemento a elemento, crear, fusionar o marcar como alias; además calcula los motivos de revisión.

**Entrada:** `ExtractResult`, `GeocodeResult`, estructura de Trilium.

**Salida:** `ResolveResult {items: [PlannedItem {key, kind, index, action, existing_note_id, alias_of, review_reasons}]}`.

**Dependencias:** Trilium ETAPI (búsqueda de notas por atributos bajo la raíz `#jrRoot`), resultados de `extract` y `geocode`.

**Reglas:**
- Extracción fallida → un único elemento `fallo` con `extraccion-fallida`.
- `confianza_japon` < 0.4 → sin elementos (resultado `no-japon`).
- 0.4 ≤ `confianza_japon` < 0.7 → todos los elementos con `clasificacion-incierta`.
- Elemento con `confianza` < 0.7 → `baja-confianza`.
- Lugar: busca `#googlePlaceId` bajo la raíz → `merge` o `create`. Sin coordenadas → `create` + motivo de geocodificación. Mismo `place_id` dos veces en la misma fuente → `alias` del primero.
- Cosa: busca `#jrTipo=cosa #jrNombreNorm="<normalizado>"` en "Comprar y comer" → `merge`; si no, compara con todas las cosas y, si alguna tiene similitud ≥ 0.85, `create` + `posible-duplicado`. Mismo nombre normalizado dos veces → `alias`.
- Otros → siempre `create`. Si el contenido es de Japón pero no hay ningún elemento → `otro:resumen` con el resumen de la fuente.

**Configuración:** `JAPAN_MIN_CONFIDENCE`, `JAPAN_REVIEW_CONFIDENCE`, `ITEM_REVIEW_CONFIDENCE`, `COSA_DUPLICATE_SIMILARITY`.

**Fallos:** errores de Trilium → reintento; estructura ausente → `ConfigError`.

**Cómo probarla:** `uv run pytest tests/unit/test_resolve.py`.
