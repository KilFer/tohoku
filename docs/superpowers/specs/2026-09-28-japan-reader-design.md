# japan-reader — Diseño

- **Fecha:** 2026-09-28
- **Estado:** Aprobado en conversación, pendiente de revisión del spec escrito
- **Autor:** Fernando + Claude

## 1. Propósito

Convertir contenido corto de redes (YouTube Shorts, Instagram Reels y posts de Instagram de imagen/carrusel) guardado durante el día a día en una **base de datos de planificación de viaje a Japón** dentro de Trilium, sin trabajo manual más allá de guardar el enlace.

- **Uso principal:** planificar un viaje. La inmensa mayoría del contenido serán **lugares que visitar** o **cosas que comprar/comer**.
- **Uso secundario:** archivo de conocimiento sobre Japón (cultura, curiosidades). Menos frecuente, menos estructurado.

### Criterios de éxito

1. Guardar un enlace en la lista "Japón" de Karakeep es la única acción manual necesaria.
2. Cada lugar concreto acaba como **una única nota** en un Geo Map de Trilium, con coordenadas correctas, enlace a Google Maps y todas las fuentes (vídeos o posts) que lo mencionan.
3. Productos, platos y cadenas sin ubicación concreta acaban en "Comprar y comer", también deduplicados.
4. Lo dudoso no contamina el mapa en silencio: aparece en una bandeja de revisión.
5. Los enlaces procesados (vídeos y posts) desaparecen de la Home de Karakeep (archivados).
6. Cada etapa del proceso está documentada de forma independiente.

### Fuera de alcance

- Leer directamente las colecciones de guardados de Instagram (API no oficial, frágil, riesgo de bloqueo).
- Procesamiento en tiempo real; la latencia de minutos u horas es aceptable.
- Interfaz web propia; Trilium y Karakeep son la interfaz.
- Datos volátiles de Google (horarios, valoraciones): el enlace a Google Maps los cubre.

## 2. Contexto e infraestructura existente

Servidor actual (Delfos):

- CPU Intel Xeon E5-2620 v3 (6c/12t), 16 GB RAM (~10 GB disponibles), **sin GPU**.
- Contenedores ya desplegados relevantes: `karakeep-web` 0.33.2 (+ `karakeep-chrome`, `karakeep-meilisearch`), `trilium` v0.106 (con tipo de nota Geo Map).
- Servidor **ntfy** propio operativo (canal de alertas). Home Assistant existe pero es entorno de laboratorio: **no** se usa.

Decisiones derivadas:

- LLM local no viable → LLM vía **OpenRouter** (API compatible OpenAI, modelo configurable). No se usa la API de Claude directamente.
- Transcripción local con **faster-whisper `large-v3`** en CPU (int8). Se prioriza calidad sobre velocidad; `large-v3-turbo` queda como alternativa configurable.
- Geocodificación con **Google Places API (New) – Text Search Pro**.

## 3. Decisiones tomadas

| Tema | Decisión |
|---|---|
| Bandeja de entrada | Karakeep, lista única "Japón". Único punto de entrada. |
| Histórico de Instagram | Exportación oficial de Instagram ("Descargar tu información" → Guardado, JSON) + comando de importación a Karakeep. Una sola vez. |
| Orquestación | Servicio propio en Python (un contenedor). n8n descartado por consumo de recursos y porque la lógica (deduplicación, fusión, umbrales) necesita tests. |
| Unidad en Trilium | Una nota por **lugar** (y una por **cosa**). Vídeos nuevos se suman a notas existentes. |
| Fusión | El resumen de la nota se **reescribe** integrando la nueva fuente. |
| Autonomía | Automático con red de seguridad: lo dudoso va a una bandeja de revisión. |
| Geocodificación | Google Places Text Search Pro, `FieldMask` restringido a campos Pro, cuota diaria limitada. |
| Tras procesar | Bookmark etiquetado y **archivado** en Karakeep (salvo errores). |
| Alertas | ntfy. |
| Idioma de las notas | Español; nombres propios y nombre japonés original conservados. |
| Posts de Instagram | Incluidos (imagen y carrusel). Descarga con gallery-dl; las imágenes se envían a un LLM multimodal. |
| Texto en pantalla de Reels/Shorts | Fotogramas clave enviados al LLM junto a la transcripción. Desactivable (`REEL_KEYFRAMES_ENABLED=false`) si el coste es alto; en ese caso los vídeos usan solo audio + texto y los posts siguen con visión. |

### Cuota de Google Places (verificado sept. 2026)

Tope gratuito mensual por SKU: Text Search Pro = 5.000 llamadas/mes (después 32 $/1.000). Con 1–2 llamadas por lugar ≈ 2.500–5.000 lugares/mes gratis. Suficiente para uso normal e importación inicial; si el histórico lo superase, la importación se reparte en varios meses mediante el límite diario. Fuente: https://developers.google.com/maps/billing-and-pricing/pricing

## 4. Arquitectura

Un servicio, `japan-reader`, en un contenedor Docker en la misma red que `karakeep-web` y `trilium`.

```
scheduler (cada N min, por defecto 10)
  1. ingest      ← Karakeep API: bookmarks de la lista "Japón" no vistos
  2. fetch       ← yt-dlp (vídeo) / gallery-dl (post): medios + metadatos + subtítulos
                   + fotogramas clave de vídeo (ffmpeg, desactivable)
  3. transcribe  ← faster-whisper large-v3 (si hay audio y no hay subtítulos útiles)
  4. extract     → OpenRouter multimodal: texto + imágenes → JSON validado
  5. geocode     → Google Places Text Search Pro (solo lugares)
  6. resolve     ← deduplicación contra Trilium (placeId / nombre normalizado)
  7. publish     → Trilium ETAPI: crear/fusionar notas, clones a revisión
  8. mark        → Karakeep: etiqueta de estado + archivar
  (notify)       → ntfy en errores y resumen opcional

state.db (SQLite): jobs, resultado por etapa, intentos, errores, contadores de cuota
```

### Principios

- **Sondeo, no webhook.** Robusto frente a caídas del servicio, no expone endpoints. Webhook de Karakeep = mejora futura opcional.
- **Pipeline por etapas con estado persistido.** Cada bookmark es un *job*; el resultado de cada etapa se guarda (JSON en SQLite, audio/transcripción en disco). Un fallo reanuda desde la etapa fallida. Se puede reprocesar desde cualquier etapa (p. ej. re-extraer con un prompt nuevo sin re-transcribir).
- **Un módulo por etapa**, con entrada/salida tipadas (Pydantic). Cada etapa se puede ejecutar y probar de forma aislada.
- **Clientes externos aislados** (`karakeep`, `trilium`, `openrouter`, `places`, `ntfy`) detrás de interfaces pequeñas, sustituibles por *fakes* en tests.
- **Un job a la vez** (Whisper satura la CPU). Límites de CPU/RAM en Compose (orientativo: 6 CPUs, 6 GB).

### Estructura del repositorio (orientativa)

```
japan-reader/
  src/japan_reader/
    config.py          # settings desde .env
    state.py           # SQLite: jobs, etapas, cuotas
    pipeline.py        # orquestación de etapas y reintentos
    stages/            # ingest, fetch, transcribe, extract, geocode, resolve, publish, mark
    clients/           # karakeep, trilium, openrouter, places, ntfy
    templates/         # HTML de notas Lugar / Cosa / Fuente
    prompts/           # prompts de extracción y fusión
    cli.py             # run, init-trilium, import-instagram, reprocess, status, eval
  tests/  (unit/, integration/, fixtures/)
  eval/   (casos de evaluación del LLM)
  docs/   (pipeline/, trilium-model.md, operations.md)
  Dockerfile, docker-compose.yml, .env.example, README.md
```

## 5. Etapas del pipeline

### 5.1 ingest
- **Entrada:** lista de Karakeep configurada (`KARAKEEP_LIST_ID`).
- **Proceso:** pagina los bookmarks de la lista; crea un job por cada bookmark de tipo enlace cuyo `bookmarkId` no exista en `state.db`. Ignora dominios no soportados (marca `jr:error` con motivo "fuente no soportada").
- **Salida:** job `{bookmark_id, url, plataforma}` en estado `pending`.

### 5.2 fetch
Tres tipos de contenido, detectados por URL y confirmados por los metadatos:

| Tipo | Herramienta | Medios obtenidos |
|---|---|---|
| Vídeo (YouTube Short, Instagram Reel) | `yt-dlp` (librería) | Vídeo, audio, subtítulos (manuales > automáticos) |
| Post de imagen | `gallery-dl` | Imagen |
| Carrusel | `gallery-dl` | Todas las imágenes; los elementos de vídeo del carrusel se tratan como vídeos (audio + fotogramas) |

- **Metadatos comunes:** título (si existe), descripción/caption, hashtags, autor, fecha, duración.
- **Fotogramas clave** (solo vídeos, si `REEL_KEYFRAMES_ENABLED=true`): ffmpeg con detección de cambio de escena; se conservan como máximo `KEYFRAMES_MAX` (por defecto 6), repartidos a lo largo del vídeo y descartando los casi idénticos. Si el vídeo no tiene cambios de escena, muestreo uniforme.
- **Límites de imagen:** como máximo `POST_IMAGES_MAX` imágenes por post (por defecto 10) y redimensionado a `IMAGE_MAX_SIDE` px (por defecto 1024) antes de enviarlas al LLM, para controlar el coste.
- **Instagram:** yt-dlp y gallery-dl usan el mismo fichero de cookies (`INSTAGRAM_COOKIES_FILE`, preferiblemente de una cuenta secundaria). Fallback: si Karakeep tiene archivados los medios del bookmark (asset de vídeo o captura), se descargan desde Karakeep.
- **Salida:** `FetchResult {tipo, metadatos, audio?, imagenes[], fotogramas[], subtitulos?}` + ficheros en `data/jobs/<id>/`.

### 5.3 transcribe
- **Se omite** si el contenido no tiene audio (posts de imagen o carrusel sin vídeos).
- **Proceso:** si hay subtítulos manuales útiles, se usan; si no, faster-whisper (`WHISPER_MODEL=large-v3`, `compute_type=int8`, detección automática de idioma, VAD activado).
- **Salida:** `Transcript {texto, idioma, origen: subtitulos|whisper}`.
- El modelo se cachea en un volumen (~3 GB).

### 5.4 extract
- **Entrada al LLM:** plataforma, tipo de contenido, título, descripción/caption, hashtags, autor, transcripción (si existe) e **imágenes** (imágenes del post o fotogramas clave). El prompt indica que se lea el texto que aparece en las imágenes (rótulos, nombres de locales, texto sobreimpreso) y que se contraste con la transcripción.
- **Modelo:** `OPENROUTER_MODEL` debe ser **multimodal** (admitir imágenes); se valida al arrancar. Si se desea, `OPENROUTER_TEXT_MODEL` permite un modelo más barato solo para contenidos sin imágenes y para la llamada de fusión.
- **Salida:** JSON validado contra `Extraction` (Pydantic). Si no valida, un reintento incluyendo el error de validación; si vuelve a fallar → job a revisión con la transcripción adjunta.

```json
{
  "relacionado_japon": true,
  "confianza_japon": 0.95,
  "idioma": "es",
  "resumen_video": "…",
  "lugares": [{
    "nombre": "Ichiran Shibuya",
    "nombre_local": "一蘭 渋谷店",
    "consulta_busqueda": "Ichiran Shibuya Tokyo",
    "ciudad": "Tokio", "region": "Kanto",
    "categoria": "comida",
    "que_es": "…", "consejos": ["…"], "precio_aprox": "¥1000-1500",
    "confianza": 0.9
  }],
  "cosas": [{
    "nombre": "CoCo Ichibanya", "categoria": "cadenas",
    "que_es": "…", "consejos": ["…"], "donde": ["…"],
    "confianza": 0.85
  }],
  "otros": [{ "titulo": "…", "contenido": "…" }]
}
```

- `categoria` de lugar: enumeración cerrada (templo, santuario, comida, cafe, bar, tienda, mercado, mirador, barrio, museo, parque, onsen, alojamiento, transporte, otro).
- `categoria` de cosa: souvenirs, comida, cadenas, cosmetica, otros.
- Modelo en `OPENROUTER_MODEL`; prompt versionado en `prompts/`. Salida siempre en español.
- `confianza_japon` es la probabilidad (0–1) de que el vídeo trate sobre Japón; `relacionado_japon` es solo informativo. Las decisiones se toman con `confianza_japon` según los umbrales de §7 (< 0.4 → `no-japon`).

### 5.5 geocode
- Solo para `lugares`. Text Search Pro con `consulta_busqueda`, `regionCode=JP`, `languageCode=es`, `FieldMask` = `places.id,places.displayName,places.formattedAddress,places.location,places.googleMapsUri,places.types`.
- **Validación:** resultado dentro de Japón y, si hay `ciudad`, coherente con la dirección. Si no hay resultado o no valida → segundo intento con `nombre_local`. Si tampoco → lugar marcado para revisión (sin coordenadas).
- Varios resultados plausibles con nombres distintos → revisión (ambiguo).
- Contador diario propio (`PLACES_DAILY_LIMIT`); al alcanzarlo, los jobs esperan al día siguiente.

### 5.6 resolve
- **Lugar:** busca en Trilium nota con `#googlePlaceId=<id>`. Existe → `merge`; no existe → `create`.
- **Cosa:** busca por nombre normalizado (minúsculas, sin acentos, sin sufijos genéricos) dentro de la rama `#jrComprar`. Coincidencia exacta → `merge`; similitud alta pero no exacta → `create` + revisión por posible duplicado.
- **Otros:** siempre `create` en la rama `#jrCultura`.
- Calcula qué elementos van a revisión según umbrales (§7).

### 5.7 publish
- Crea o actualiza notas vía ETAPI usando las plantillas (§6).
- En `merge`: añade bloque de fuente (si ese `bookmarkId` no está ya), incrementa `#fuentes`, y una segunda llamada al LLM reescribe la sección "Resumen" integrando la nueva información. La sección "Mis notas" nunca se modifica.
- Elementos dudosos: se crean en su sitio normal **y** se clonan en la nota `#jrRevision` con `#revisar=<motivo>`.
- Registra en `state.db` los `noteId` creados/actualizados (idempotencia).

### 5.8 mark
| Resultado | Etiqueta Karakeep | Archivar |
|---|---|---|
| Procesado | `jr:procesado` | Sí |
| Procesado con elementos en revisión | `jr:revisar` | Sí |
| No relacionado con Japón | `jr:no-japon` | Sí |
| Error definitivo | `jr:error` | No |

Archivar = `PATCH /bookmarks/{id}` con `archived: true`. El estado real vive en `state.db`; que la lista siga devolviendo archivados no afecta.

## 6. Modelo de datos en Trilium

La raíz es la nota existente **`Home › Viajes › Ideas de Japón`**. El servicio localiza todo por atributos, no por rutas.

```
Ideas de Japón                    #jrRoot
 ├── Mapa de lugares              #jrMapa        (tipo Geo Map)
 │    └── <Lugar>…
 ├── Comprar y comer              #jrComprar
 │    ├── Souvenirs / Comida / Cadenas / Cosmética / Otros   #jrCategoria=<x>
 │    │    └── <Cosa>…
 ├── Cultura y curiosidades       #jrCultura
 ├── Bandeja de revisión          #jrRevision
 └── Plantillas                   #jrPlantillas
      ├── Lugar                   #template
      └── Cosa                    #template
```

`japan-reader init-trilium` crea bajo `#jrRoot` lo que falte (la raíz se marca a mano con `#jrRoot` una vez).

### Nota Lugar (hija de `#jrMapa`)
- **Atributos:** `#geolocation="lat,lng"`, `#ciudad`, `#region`, `#categoria`, `#googlePlaceId`, `#googleMaps=<url>`, `#nombreLocal`, `#fuentes=<n>`, `#iconClass` (según categoría), `~template=Lugar`. Manuales del usuario: `#visitado`, `#prioridad`.
- **Cuerpo HTML:** Resumen · Qué hacer/comer · Consejos prácticos (precio, horario recomendado, reservas) · Fuentes · Mis notas.
- **Bloque de fuente:** enlace al vídeo, título, autor, fecha, plataforma, resumen de 1–2 líneas de lo que aporta ese vídeo; marcador oculto con `bookmarkId`.

### Nota Cosa (hija de la categoría en `#jrComprar`)
- Igual que Lugar sin `#geolocation`/`#googlePlaceId`; con `#categoria` y relaciones `~dondeComprar` hacia notas Lugar cuando el vídeo menciona un local concreto (que se crea también como Lugar).

### Nota Otros (hija de `#jrCultura`)
- Título + contenido + fuente. Sin deduplicación.

### Bandeja de revisión
- Clones de las notas dudosas con `#revisar=<motivo>` (`geocodificacion-fallida`, `geocodificacion-ambigua`, `posible-duplicado`, `baja-confianza`, `clasificacion-incierta`, `extraccion-fallida`). Revisar = corregir la nota, quitar `#revisar` y el clon.

## 7. Red de seguridad (umbrales configurables)

| Condición | Resultado |
|---|---|
| `confianza_japon` < 0.4 | No es de Japón → `jr:no-japon` |
| 0.4 ≤ `confianza_japon` < 0.7 | Se procesa, todo el vídeo a revisión (`clasificacion-incierta`) |
| `confianza` de un elemento < 0.7 | Ese elemento a revisión (`baja-confianza`) |
| Geocodificación sin resultado válido | Lugar a revisión sin coordenadas |
| Geocodificación ambigua | Lugar a revisión |
| Cosa parecida pero no idéntica a una existente | Nueva nota + revisión (`posible-duplicado`) |
| JSON del LLM inválido tras reintento | Job a revisión con transcripción (`extraccion-fallida`) |

## 8. Errores, reintentos y alertas

| Tipo | Ejemplos | Respuesta |
|---|---|---|
| Transitorio | Timeout, 5xx, 429 | Reintento de la etapa con backoff 1 min → 5 min → 30 min → 2 h → 2 h (5 intentos); luego `jr:error` |
| Permanente del vídeo | Vídeo borrado/privado, login requerido sin cookies válidas | `jr:error` inmediato con motivo |
| De contenido | Ver §7 | Revisión, no error |
| Configuración | API key inválida, `#jrRoot` inexistente | Se detiene el procesamiento, alerta ntfy, no consume reintentos ni cuota |

- **Idempotencia:** cada etapa comprueba si su efecto ya existe (noteIds en `state.db`, `bookmarkId` en bloques de fuente).
- **Límites de gasto:** `PLACES_DAILY_LIMIT`, `OPENROUTER_DAILY_BUDGET_USD` (según coste devuelto por OpenRouter), además de la cuota configurada en Google Cloud Console.
- **Alertas ntfy** (`NTFY_URL`, `NTFY_TOPIC`, `NTFY_TOKEN`): job en `jr:error`, error de configuración, límite de gasto alcanzado. Opcional: resumen diario (procesados / revisión / errores).
- **Observabilidad:** logs estructurados (`docker logs`) y `japan-reader status` (cola, fallos, revisión, consumo del día).

## 9. Importación inicial de Instagram

1. El usuario solicita la exportación en Instagram (Centro de cuentas → Descargar tu información → "Guardado", formato JSON).
2. `japan-reader import-instagram <ruta> [--collection <nombre>] [--dry-run]` lee `saved_collections.json` / `saved_posts.json`, extrae URLs de Reels/posts, muestra recuento y crea los bookmarks en la lista "Japón" de Karakeep (evitando duplicados por URL).
3. El pipeline normal los procesa a su ritmo, respetando los límites diarios.

El formato exacto del JSON de exportación se verificará con una exportación real antes de implementar el parser.

## 10. Configuración (`.env`)

`KARAKEEP_URL`, `KARAKEEP_API_KEY`, `KARAKEEP_LIST_ID` · `TRILIUM_URL`, `TRILIUM_ETAPI_TOKEN` · `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `OPENROUTER_DAILY_BUDGET_USD` · `GOOGLE_PLACES_API_KEY`, `PLACES_DAILY_LIMIT` · `OPENROUTER_TEXT_MODEL` (opcional) · `WHISPER_MODEL`, `WHISPER_COMPUTE_TYPE` · `REEL_KEYFRAMES_ENABLED` (por defecto `true`), `KEYFRAMES_MAX`, `POST_IMAGES_MAX`, `IMAGE_MAX_SIDE` · `INSTAGRAM_COOKIES_FILE` · `NTFY_URL`, `NTFY_TOPIC`, `NTFY_TOKEN` · `POLL_INTERVAL_MINUTES` · umbrales de §7.

Secretos solo en `.env` (fuera de git); `.env.example` documentado.

## 11. Testing

- **Unitarios (sin red):** cada etapa con *fixtures* grabadas de Karakeep, Places, OpenRouter y Trilium. Cubren normalización de nombres, reglas de fusión, umbrales de revisión, validación de geocodificación, plantillas HTML, idempotencia y reintentos.
- **Integración (manual, opt-in):** contra Trilium y Karakeep reales usando una rama `Ideas de Japón (test)` y una lista de pruebas.
- **Evaluación del LLM:** `eval/` con 10–15 casos reales y su resultado esperado (lugares, cosas, categorías). Deben incluir Reels con el lugar **solo en texto en pantalla**, carruseles con texto en las imágenes y posts de una sola imagen. `japan-reader eval --model <m> [--keyframes on|off]` produce una tabla comparativa (aciertos de clasificación, lugares encontrados, coste). Sirve para elegir modelo, ajustar prompts y decidir con datos si los fotogramas clave compensan su coste.

## 12. Despliegue

- Repositorio en `/media/1tb-disk/japan-reader`, `Dockerfile` + `docker-compose.yml` propios, unido a la(s) red(es) Docker de Karakeep y Trilium.
- Volúmenes: `data/` (state.db, audio, transcripciones), caché del modelo Whisper, cookies (solo lectura).
- Límites de recursos en Compose. Un solo worker.
- El despliegue lo ejecuta el usuario (`docker compose up -d`); el proyecto lo documenta.

## 13. Documentación (requisito explícito)

- `README.md`: qué es, instalación, configuración, comandos.
- `docs/pipeline/01-ingest.md` … `08-mark.md`: por etapa — entrada, salida, dependencias, configuración, modos de fallo, cómo ejecutarla y probarla aislada.
- `docs/trilium-model.md`: estructura, atributos, plantillas, reglas de fusión.
- `docs/operations.md`: revisar la bandeja, reprocesar, rotar cookies de Instagram, cambiar de modelo, importación de Instagram, alertas ntfy.

## 14. Orden de construcción

1. Esqueleto del proyecto, configuración, `state.db`, CLI base.
2. Cliente Karakeep: `ingest` y `mark` (etiquetar + archivar).
3. `fetch` (yt-dlp para vídeos, gallery-dl para posts, fotogramas clave con ffmpeg, cookies, fallback Karakeep) y `transcribe` (faster-whisper).
4. `extract` (OpenRouter multimodal, esquema, prompt) + batería `eval`.
5. `geocode` (Places, validación, límites).
6. Cliente Trilium: `init-trilium`, `resolve`, `publish` (creación, fusión, revisión).
7. Alertas ntfy, límites de gasto, `status`, `reprocess`.
8. `import-instagram`.
9. Docker, Compose y documentación completa.

## 15. Riesgos

| Riesgo | Mitigación |
|---|---|
| Instagram bloquea descargas sin login | Cookies de cuenta secundaria; fallback al vídeo archivado por Karakeep; `jr:error` claro para rotar cookies |
| Coste de visión (fotogramas clave) elevado | `REEL_KEYFRAMES_ENABLED=false` (modo solo posts), `KEYFRAMES_MAX`, redimensionado; `eval --keyframes on|off` para medirlo |
| Whisper large-v3 lento/pesado en CPU | Cola secuencial, límites de recursos; `large-v3-turbo` configurable |
| Geocodificación errónea en el mapa | Validación de país/ciudad, `googlePlaceId` como clave, revisión ante ambigüedad |
| Coste inesperado | Campos Pro únicamente, límite diario propio + cuota en Google Cloud, presupuesto diario OpenRouter |
| Cambios en APIs de Karakeep/Trilium | Clientes aislados y tests con fixtures; versiones de contenedor fijadas |
| Sobrescribir notas manuales | La sección "Mis notas" y atributos manuales (`#visitado`, `#prioridad`) nunca se tocan |
