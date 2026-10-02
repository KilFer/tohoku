# Etapa 2b — classify

[English](02b-classify.md) · **Español**

**Qué hace:** decide a qué destino de `config/destinos.yaml` va el enlace entre los candidatos de su lista. Va entre `transcribe` y `extract` (orden: fetch, transcribe, classify, extract, geocode, resolve, publish). El resto del pipeline usa el flujo del destino elegido.

**Entrada:** `job.candidates` (destinos de las listas donde está el bookmark), `job.destination` (si ya hay uno forzado), y los resultados de `fetch` y `transcribe`.

**Salida:** `Classification {destino | None, confianza, alternativa, confianza_alternativa, dudosa, omitido, cost_usd}`. Se guarda el resultado de la etapa y `jobs.destination`. `destino=None` significa `ninguno` y el job termina como `descartado`.

**Dependencias:** OpenRouter (solo si hay varios candidatos; con imágenes, `OPENROUTER_MODEL`), contador diario `openrouter_usd`, `src/tohoku/prompts/classify.md`, `src/tohoku/classify/` (clasificadores `json_schema` y `etiqueta`, registro `CLASSIFIERS`).

**Configuración:** en `config/destinos.yaml`:
- `clasificador.modelo` (por defecto `OPENROUTER_TEXT_MODEL`, o `OPENROUTER_MODEL`) para clasificar con texto; con imágenes se usa siempre `OPENROUTER_MODEL` (multimodal, comprobado en el preflight) en el mismo `modo`, porque el modelo de texto puede no admitir imágenes. El clasificador se monta si algún bookmark puede tener varios candidatos: una lista con varios destinos **o** listas con destinos distintos (la ingesta une los candidatos de todas las listas del bookmark). `clasificador.modo` (`json_schema` | `etiqueta`, por defecto `json_schema`), `clasificador.confianza_minima` (0,5), `clasificador.margen_revision` (0,15).
- `destino_legado`: destino de reserva para los jobs sin candidatos (`candidates` NULL). Opcional si solo hay un destino; obligatorio con varios.
- `OPENROUTER_DAILY_BUDGET_USD`.

**Reglas:**
- Con destino ya guardado (`reprocess --destino`) o con un solo candidato: no hay llamada al LLM (`omitido=true`).
- Los candidatos que ya no existen en `destinos.yaml` se descartan; si no queda ninguno se usa `destino_legado`.
- Con varios candidatos: se pasa al clasificador la descripción de cada destino, el texto (caption, hashtags, transcripción) y, si no hay texto (caption y transcripción vacíos), hasta 2 imágenes, que van al clasificador de `OPENROUTER_MODEL`. Si la respuesta no es válida o nombra un destino que no es candidato, un reintento con el error; si vuelve a fallar, `TransientError`.
- `ninguno` o `confianza` < `confianza_minima` → `destino=None` (`descartado`, etiqueta `jr:descartado`).
- Si hay una alternativa candidata distinta y `confianza - confianza_alternativa` < `margen_revision` → `dudosa=true`; el `resolve` del flujo `viaje` añade el motivo de revisión `clasificacion-dudosa`.
- Los nombres de destino se comparan sin distinguir mayúsculas, acentos ni separadores: espacios, guiones y guiones bajos son equivalentes (`Nueva Zelanda` = `nueva-zelanda` = `nueva_zelanda`); una `alternativa` desconocida se ignora. Por eso `destinos.yaml` rechaza (`ConfigError` con los dos nombres) dos destinos que solo difieren en eso (`japon` y `Japón`).
- Ficheros: la etapa solo necesita `data/jobs/<id>/` si va a mandar imágenes. Tras la limpieza (`files_purged`) el pipeline solo vuelve a descargar por `classify` en ese caso; un job sin resultado de `classify` reprocesado desde `geocode`/`resolve`/`publish` toma `destino_legado` sin descargar.
- Modo `etiqueta`: confianza 1,0 y sin alternativa (no hay logprobs). Los adaptadores específicos quedan abiertos (registro `CLASSIFIERS`).

**Fallos:** varios candidatos sin clasificador → `ConfigError`; respuesta inválida tras el reintento o 429/5xx → reintento del job; presupuesto agotado → `QuotaExceeded` (espera al día siguiente). Un destino decidido o forzado que ya no existe en el YAML hace fallar solo ese job (`jr:error`), no la cola.

**Ejemplo con dos flujos** (`japon` con flujo `viaje`, `recetas` con flujo `receta`):

    listas:
      L_JAPON: [japon]
      L_RECETAS: [recetas]
    destinos: {japon: {flujo: viaje, ...}, recetas: {flujo: receta, ...}}
    destino_legado: japon

- Un bookmark solo en `L_RECETAS` tiene un candidato (`recetas`): no hay llamada al LLM y sigue el flujo `receta`. Uno solo en `L_JAPON` sigue el flujo `viaje`. Uno en las dos listas tiene dos candidatos y lo decide el clasificador (hay clasificador porque hay más de un destino en total, aunque cada lista tenga uno solo).
- Un Reel que el clasificador manda a `recetas` pero no es una receta termina `descartado`: sin nota y sin `jr:destino`.

**Cómo probarla:** `uv run pytest tests/unit/test_classify.py`. Con casos reales: `tohoku eval --destino X`. Para forzar: `tohoku reprocess <id> --destino X` (ver `docs/operations.md`).
