# CLAUDE.md — Tohoku (antes japan-reader)

Contexto y reglas para futuras sesiones. Idioma de trabajo con el usuario (Fernando): **español**.

## Qué es

Servicio Python 3.12 (uv, Docker) que convierte Shorts de YouTube, Reels y posts de Instagram guardados en la lista **"Japón"** de Karakeep en notas de Trilium bajo `Home › Viajes › Ideas de Japón` (`#jrRoot`): Geo Map de lugares, "Comprar y comer", "Cultura y curiosidades" y "Bandeja de revisión". Objetivo: planificar un viaje a Japón.

Pipeline: `ingest → fetch (yt-dlp/gallery-dl + ffmpeg) → transcribe (faster-whisper large-v3, CPU) → extract (LLM multimodal vía OpenRouter) → geocode (Google Places Text Search Pro) → resolve (deduplicación) → publish (Trilium ETAPI) → mark (etiqueta jr:* + archivar en Karakeep)`. Avisos por ntfy.

Documentación de referencia (leer antes de cambiar comportamiento):
- Diseño: `docs/superpowers/specs/2026-09-28-japan-reader-design.md` (autoridad).
- Plan original (histórico, ya ejecutado): `docs/superpowers/plans/2026-09-28-japan-reader.md`.
- Etapas: `docs/pipeline/01-ingest.md` … `08-mark.md` (cada una con 7 secciones: Qué hace · Entrada · Salida · Dependencias · Configuración · Fallos · Cómo probarla).
- Modelo de Trilium: `docs/trilium-model.md`. Operación diaria: `docs/operations.md`.

## Entorno (servidor Delfos)

- Contenedor `tohoku` (proyecto Compose `tohoku`, en este repo), red Docker externa `pangolin`. Límite 6 CPU / 6 GB.
- Desde el contenedor: Karakeep `http://karakeep-web:3000`, Trilium `http://trilium:8080`.
- Desde el host (scripts/tests): Karakeep `http://localhost:3088`, Trilium `http://localhost:8750`.
- Volúmenes: `./data → /data` (state.db, jobs, `data/instagram/`), `tohoku_whisper-models → /models` (large-v3; antes `japan-reader_whisper-models`), `./secrets → /secrets:ro`.
- Configuración de destinos: `config/destinos.yaml` (+ `config/prompts/`), copiada a la imagen y montada `./config:/app/config:ro` (ver `docs/operations.md`).
- `data/state.db` lo crea el contenedor como root: usar la CLI dentro del contenedor, no `uv run` sobre `data/`.
- `data/models/` (~3,5 GB) es una copia del host de las pruebas; el contenedor usa el volumen `/models`. Se puede borrar si hace falta espacio.
- No hay remoto git. `master` = lo desplegado o desplegable. La rama `feat/tohoku` (fases 2-6 multidestino) se cerró el 2026-10-01: integrada en `master` y borrada. El trabajo nuevo va en una rama `feat/<tema>` que se integra en `master` con fast-forward.
- Desplegar siempre desde `master` con el árbol limpio (el compose monta `./data` relativo a este directorio): `git switch master && docker compose build && docker compose up -d` (y volver a la rama de trabajo si la hay).

## Reglas de trabajo

- **Nunca** crear ni editar `.env`, ni mostrar secretos. Para comprobar credenciales, leer `.env` con `dotenv_values` e imprimir solo presencia/longitud y el resultado de la llamada.
- TDD: test primero (sin red; `tests/fakes.py`, `tests/builders.py`, respx), luego código. `uv run pytest -q` debe quedar en verde.
- Tests de integración solo a mano: `JR_TEST_ROOT_LABEL=... TRILIUM_URL=http://localhost:8750 KARAKEEP_URL=http://localhost:3088 uv run pytest -m integration -k ...`. Requieren una nota con `#jrRootTest` en Trilium (hoy no existe). Para probar con servicios reales sin tocar producción, el patrón de la Task 7: imagen aparte, config y `DATA_DIR` en el scratchpad, raíces `#jrRoot<Destino>Test` **fuera** de las raíces reales (ver "Raíces de destino anidadas").
- Cada cambio de comportamiento actualiza su doc de etapa / `operations.md`.
- Tras cambiar código: `docker compose build` y `docker compose up -d` (recrea el contenedor). La CLI dentro: `docker compose exec tohoku tohoku <cmd>`. `run-once` choca con el lock del servicio en marcha: usar `docker compose run --rm` con el servicio parado.
- Acciones sobre servicios reales (Trilium, Karakeep, importaciones, llamadas de pago) se confirman con el usuario antes; trabaja paso a paso y se detiene para revisión manual entre bloques.
- El prefijo `jr` (Karakeep `jr:*`, Trilium `#jr*`, raíces `jrRoot<Destino>`) es intencionado (Japan Reader / JR, Tohoku Shinkansen) y no se renombra.
- Commits terminan con `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Estado (2026-09-28)

- En producción: `docker compose up -d`, sondeo cada 10 min. Prueba de humo con 3 enlaces OK (2 lugares en el mapa, 4 cosas, 1 otro; todos `jr:procesado` y archivados).
- **2026-10-01: fases 0-4 desplegadas** (`master` = `feat/tohoku` en `a24166b`). ~07:54 renombrado a Tohoku (contenedor `tohoku`, volumen `tohoku_whisper-models`; borrados el volumen y la imagen `japan-reader`). ~08:40 fases 2-4: migración de `state.db` OK (columnas `candidates`/`destination`; los jobs antiguos con destino NULL = `destino_por_defecto` japon; `no-japon` se muestra como `descartado`), primera limpieza: 1.311 jobs, `data/jobs` de 320 MB a 100 KB. Copia previa para volver atrás: `data/state-pre-fase3-2026-10-01.db` (el código de las fases 0+1 no lee la base migrada). `PLACES_DAILY_LIMIT=150` otra vez (cupo de octubre: 5.000/mes; Cloud Console a 150 tras las 09:00 del 1/10). Repo en `/media/1tb-disk/tohoku` (antes `japan-reader`).
- Config en `config/destinos.yaml` (prompt en `config/prompts/japon.md`); `KARAKEEP_LIST_ID` y `TRILIUM_ROOT_LABEL` ya no se leen de `.env`; editar `config/` solo pide `docker compose restart tohoku`. Fases 5 (recetas) y 6 (Nueva Zelanda): ver más abajo.
- Limpieza (fase 4): el resultado de `fetch` se conserva con `files_purged` y un `reprocess` de un job limpiado solo vuelve a descargar si repite `transcribe`/`extract`, o `classify` con imágenes (`--from geocode`/`resolve`/`publish` no descargan, tampoco en jobs anteriores a la fase 3; pasada la retención se rehace todo). Ver `docs/operations.md`, "Limpieza".
- `.env` completo: Karakeep (lista "Japón" = `seo5xdpquppqfy4hmzzeekfh`), Trilium v0.106, OpenRouter `openai/gpt-6-luna` (key con límite 8 $, presupuesto 2 $/día), Google Places (desde 2026-10-01: `PLACES_DAILY_LIMIT=150` y la misma cuota diaria en Cloud Console; del 29 al 30/09 fueron 2.000/2.200 para gastar el cupo de septiembre), presupuesto con alertas de 5 $; el límite real es el cupo gratuito de 5.000/mes, que se renueva el día 1 en hora del Pacífico), ntfy `https://ntfy.belaza.me` topic `kamo`. Sin cookies de Instagram (de momento no hacen falta).
- Medidas reales: ~2 min por Reel (Whisper large-v3 ~90 s), ~0,001 $ de LLM por enlace. `small` de Whisper no basta (confundió "Miki Jet" con "Mickey Jet").

### Correcciones hechas en la puesta en marcha (no estaban en el plan)
- `e3c64ad` Places: con `regionCode=JP` Google omite el país en `formattedAddress` → se pide `places.postalAddress` (Pro) y se usa `regionCode` y la prefectura.
- `6e1f9b0` Geocode: entre varios resultados válidos gana el de nombre más parecido, no el primero.
- `ab99cc3` OpenRouter: `temperature` solo si el modelo la admite (modelos de razonamiento no; con `require_parameters` daba 404).
- `659102c` Posts de Instagram: gallery-dl sin cookies recibe "redirect to login" en todos los posts → plan B con yt-dlp (caption + imágenes a tamaño original); la redirección a login es error permanente (antes quemaba 5 h de reintentos).
- `8e1a8fe` Geocode de áreas: ciudades, barrios e islas llegan sin `postalAddress` y se descartaban (`geocodificacion-fallida`, una nota repetida por fuente) → país y ciudad también de `addressComponents` (Pro); los lugares que sigan sin ficha se deduplican por `#jrNombreNorm`.
- `6077526` Geocode menos "ambiguo": empates a <300 m = mismo sitio; nombre exacto en Japón se acepta aunque la ciudad del LLM no cuadre; al comparar nombres, palabras genéricas traducidas (shrine/santuario…), alias de ciudad y orden de palabras cuentan como iguales (las claves `#jrNombreNorm` no cambian).
- `67690dd` Mismo sitio con dos fichas de Google (Omoide Yokocho, dos placeId a 45 m): si no hay nota con ese placeId, se fusiona con un lugar del mismo `#jrNombreNorm` a <300 m. Migración puntual `data/backfill_jrnombrenorm.py` (42 lugares antiguos sin `#jrNombreNorm`, aplicada 2026-09-29).
- `b269073` Bandeja sincronizada: `#revisar` = unión de motivos vigentes de todas las fuentes (de `published` en state.db), sin acumular resueltos; la nota sale de la Bandeja si ya no queda ninguno; no se vuelve a meter una nota que el usuario sacó salvo que llegue una fuente con motivos.
- `204488d` Caché de búsquedas de Places (`places_cache` en state.db, 30 días; el 31 % de consultas se repetía) y día de cuota en hora del Pacífico, como Google (antes el contador local se reiniciaba a 00:00 UTC y habría llamado a Google con su cuota del día agotada).
- `17950b7` Importador: formato de exportación 2026 (lista de colecciones con posts anidados, mojibake), del más antiguo al más reciente, `--limit N` por tandas.

- Clasificador (fase 3): solo se ejecuta si un job tiene más de un destino candidato; con imágenes usa `OPENROUTER_MODEL`; `descartado` sin `jr:destino`. Ver `docs/pipeline/02b-classify.md`.

## Importación del historial de Instagram (EN CURSO)

- Fichero: `data/instagram/saved_collections.json` (en el contenedor: `/data/instagram/saved_collections.json`). Colección a importar: **"Cosas de Japon"** = 2.288 enlaces (2.166 Reels, 122 posts). Otras colecciones (Recetas, Para la casa, Boda) no se importan.
- Comando de cada tanda (relanzarlo importa la siguiente; `--dry-run` primero para ver qué entraría):
  `docker compose exec tohoku tohoku import-instagram /data/instagram/saved_collections.json --collection "Cosas de Japon" --limit N`
- Plan: primera tanda de 20 → revisar tiempos, coste, Bandeja de revisión y calidad → tandas de 50-100/día ajustando `OPENROUTER_DAILY_BUDGET_USD` y `PLACES_DAILY_LIMIT`. Estimación total: ~75-80 h de CPU, 3-5 $ de LLM, 2.000-4.000 búsquedas de Places.
- Progreso: consultar con `--dry-run` (línea `Ya existían / Pendientes`) y `docker compose exec tohoku tohoku status`.
  - 2026-09-28: dry-run de la primera tanda → 20 nuevos, 0 existentes, 2.268 pendientes.
  - 2026-09-28 ~23:55: **tanda 1 importada** (20 creados, 2.268 pendientes). Revisión prevista a la mañana siguiente: `status`, logs, Bandeja de revisión, coste del día, calidad de notas.
  - 2026-09-29: revisión tanda 1 → 16 procesados, 7 revisar, 1 no-Japón. El único post falló (gallery-dl exige login) → arreglado con `659102c` y reprocesado (6 torres, 4 nuevas + 2 fusionadas). Revisar: 1 baja confianza, 4 ciudades sin punto exacto (aceptable para el usuario), 1 cosa genérica ("Comida preparada refrigerada", el usuario la borrará si no se enriquece), 1 geocodificación ambigua.
  - 2026-09-29 ~08:45: **tanda 2 importada** (50 creados, 20 ya existían, 2.218 pendientes).
  - 2026-09-29: tanda 2 terminada (84 búsquedas de Places en 50 enlaces). Total: 49 procesados, 24 revisar, 1 no-Japón; hoy 0,046 $ de LLM y 113 llamadas a Places.
  - 2026-09-29: **tanda 3 importada** (40 creados, 70 ya existían, 2.178 pendientes). Con 113/150 de Places gastados, parte se geocodificará al día siguiente (la cola espera sola).
  - 2026-09-29 ~10:30: desplegado `8e1a8fe` (la tanda 3 ya se procesa con él). Pendiente: el usuario borra en Trilium las 26 notas de áreas en la Bandeja y después se reprocesan desde `geocode` estos 13 jobs (~68 llamadas a Places):
    `reprocess --from geocode dhsw4ldl3khzd145e9385sl7 juv01lhqf91wby9ozcvfxkec mo91h0rd3jg7ccc2q7o6dmc7 rc7gk19vmlmwoyv07zb4ubk6 kveqwi6kyzy2qhcvszcij9i1 t7yi0nvsouv6yll97muff1b0 cnvwjfo8jqz4edavehnqlz43 j9o6xkshwsb59d18uskhjydk nrlo70v8zi5llfcsa6i9dorl pcw1o9bw3676298ddec7s8an dw92dzjxj8c7yf7y5mhqbis2 leixw9zvipkmbklu5uzzlnzj x1kiqes6t6i3s6igdd8orywg`
  - 2026-09-29 ~11:30: 26 notas borradas por ETAPI (borrar en la Bandeja solo quita el clon; la nota sigue en el Mapa). Contador de Places de ese día bajado a mano a 87 (quedaban 63 en Google Cloud, excepción puntual). Reprocesados 10 de 13; quedan `dw92dz`, `leixw9`, `x1kiqe` en espera de cuota (se reanudan solos). 58 geocodificaciones, 56 sin revisión. Kioto = 1 nota con 2 fuentes. Huérfana: "Koyasan" `EUCc4I9K6WoF` (Google devolvió otro placeId al reprocesar; la vigente es `0j3tghMvbFK0`). Huérfana borrada. Desplegado `bfd4eb5` (restricción de audiencia = error permanente).
  - 2026-09-29 tarde: límite diario de Places subido a 2.000 (aprovechar las ~4.700 gratuitas que quedan de septiembre; el cupo de octubre da para el resto). **Tanda 4 importada: 200 creados**, 110 ya existían, 1.978 pendientes. Criterio del usuario: si la Bandeja crece, revisar antes de seguir; si se mantiene estable, subir el tamaño de tanda.
  - 2026-09-29 ~16:00: tanda 4 terminada (~1 min/enlace, más rápido que lo estimado). Bandeja 56: 39 lugares "ambiguos" (~30 con pin correcto), 20 baja confianza, 9 posibles duplicados, 5 fallidos, 4 clasificación incierta. Desplegado `6077526` y reprocesados desde `geocode` los 36 enlaces ambiguos (estado previo en `data/ambiguous-snapshot-2026-09-29.json`) y 3 más de estaciones → Bandeja 42, ambiguos 20. Huérfanas borradas (10): Kyoto Tower, Enoshima Shrine, Shibuya Station, Starbucks Shibuya, Trader Akihabara, Atami promenade, Tokyo Station y Shinjuku Station viejas (sus fuentes ya están en "Estación de Tokio"/"Shinjuku Station"), KITTE Garden, Cocoon Tower. 509 lugares, 504 con pin, sin placeId repetidos. Places ese día: 923.
  - 2026-09-29 ~17:30: desplegado `67690dd` + migración de `#jrNombreNorm`. Omoide Yokocho unificado (`dKEjUYyoDIqs`, 2 fuentes). Huérfana "Yurakucho Alley" `GkNJeHpaUo5c` borrada (al reprocesar Google dio otra ficha a ~400 m: la vigente es `R2bkiO4Libcs` "The Alley - Yurakucho"; la vieja era 有楽町産直横丁 — revisar a mano cuál es la buena). Estado limpio: 507 lugares, 502 con pin, sin títulos ni placeId repetidos; Bandeja 42.
  - 2026-09-29 ~18:00: **tanda 5 importada: 400 creados**, 310 ya existían, 1.578 pendientes. Punto de partida: 43 en revisión de ~318 procesados. Revisión prevista esa noche.
  - 2026-09-29 noche: tabla de la Bandeja en `data/bandeja-2026-09-29.json` (67 notas: 54 con motivo vigente, 13 ya resueltas por reprocesados). Desplegado `b269073` y quitados los 13 clones obsoletos → Bandeja 54. El usuario revisa a mano el resto. Nota: las 54 pueden tener en `#revisar` motivos antiguos acumulados (se refrescan solos si su enlace se reprocesa).
  - 2026-09-29 ~23:00: tanda 5 parada en 56 pendientes al llegar a 2.000 llamadas de Places. Medido: 3,2 lugares/enlace en la tanda 5 (mediana 1; 64 enlaces con ≥5 lugares, máx. 57), ~1,2 llamadas/lugar. Proyección de lo que queda (~1.630 enlaces): 5.500-6.000 llamadas sin caché, ~3.800-4.200 con caché. Plan de cupo: día PT 30/09 con 2.200 (cupo de septiembre, que acaba el 1/10 a las 09:00 en España) y el resto con las 5.000 de octubre. **Tanda 6 importada: 600 creados**, 710 ya existían, 978 pendientes de importar; 472 en cola esperando a la cuota de Places (09:05 hora de España).
  - Procedimiento para reprocesar sin huérfanas: guardar antes nota+placeId de cada lugar; después, notas viejas no reutilizadas con 1 fuente y sin "Mis notas" → borrar; con varias fuentes → reprocesar también los enlaces de sus otras fuentes y borrar cuando la nota nueva las contenga todas.
  - 2026-09-30/10-01: tanda 6 terminada (01:18). Las comprobaciones programadas de las 00:02/02:03 no llegaron a ejecutarse (eran de la sesión de Claude, que estaba inactiva): despliegue hecho a mano el 1/10 por la mañana. Reprocesados los 17 errores: 9 OK, 1 restricción de audiencia (`lz568a2m2rost8xqewtm5d93`, a mano como `pxf0p8…`), 7 con "empty media" de Instagram reintentando (Instagram corta tras varias descargas seguidas). Prueba de 5 enlaces importada y procesada (1.310 ya existían, 973 pendientes de importar). Total: 1.056 procesados, 217 revisar, 38 descartados.
  - 2026-10-01 ~08:55: **tanda 7 importada: 20 creados** (verificación en vivo de las fases 2-4), 1.315 ya existían, 953 pendientes. Lanzada antes de las 09:00 (aún día PT 30/09, 1.210/2.200 de Places): parte se geocodifica con la cuota de septiembre.
  - Siguiente: revisar la tanda 7 (destino, clasificador, limpieza, Bandeja); después, tandas normales con el límite de 150/día.
- **2026-10-01: fases 5 y 6 desplegadas** (`master` en `fe509ff`, ~11:27). Recetas y Nueva Zelanda siguen **comentadas** en `config/destinos.yaml`: producción solo procesa Japón. ~11:18 la Bandeja de recetas de prueba ("Recetas (test)" estaba dentro de "Ideas de Japón") paró la cola de Japón ("Hay 2 notas que cumplen '#jrRevision'"); arreglado con `24a323a` (estructura buscada solo como hija directa de la raíz) y notas de prueba borradas.
- **Fase 5 (recetas)** (flujo `receta` registrado, bloque `recetas` comentado en `config/destinos.yaml`, doc `docs/flujos/receta.md`). Integración real (Task 7) OK el 2026-10-01 en contenedor de prueba `tohoku:fase56` (config y DATA_DIR en el scratchpad, lista Karakeep de prueba `z4kz2h6hhdlng7hjsgce071v`, raíces `#jrRootRecetasTest` y `#jrRootJaponTest`): 5 recetas publicadas (Tabla, Cuadrícula con portada, Mis notas) por 0,006 $; vídeo sin `portada` → último fotograma (`70625c9`); clasificador con la lista en [recetas, japon]: 7/7 correctos (3 recetas incl. furikake japonés, 3 Japón, 1 descartado), confianza 0,94-0,99, 0,0076 $ y 6 llamadas a Places. 

### Plan acordado (2026-10-01)

- Importación: tandas de 150 enlaces con `PLACES_DAILY_LIMIT=150` (lo que no quepa en la cuota espera al día siguiente solo). **Tanda 8 (150)** lanzada el 1/10 ~11:45 (dry-run: 150 nuevos, 1.335 ya existían, 803 pendientes de importar).
- Los 7 Reels con "empty media" de Instagram quedan **aparcados** (se reintentan solos; no se investigan de momento).
- **Activar Recetas** cuando queden pocos pendientes de importar (en un par de días): el usuario crea la raíz real `#jrRootRecetas` (puede ir dentro de "Ideas de Japón": tipos distintos) y elige la lista de Karakeep; después, por este orden: descomentar `recetas`, su lista y `destino_por_defecto: japon` → `init-trilium --destino recetas` → `docker compose restart tohoku` (ver `docs/operations.md`).
- **Nueva Zelanda (Task 9)**, sin prioridad, sin código pendiente: (1) el usuario crea "Viaje a Nueva Zelanda" con `#jrRootNZ` **fuera** de "Ideas de Japón" (dos viajes anidados mezclarían lugares) y una lista de Karakeep (o una bandeja con varios destinos y clasificador); (2) prueba aislada con `#jrRootNZTest` y 2-3 enlaces reales; (3) activar en producción (descomentar bloque + lista + `destino_por_defecto`, `init-trilium --destino nueva_zelanda`, reiniciar); (4) decidir con enlaces reales si hace falta algo de la decisión 6 (palabras genéricas, iconos, umbrales `JAPAN_*`, ejemplos maoríes del prompt) → tarea aparte. Comparte con Japón el límite de 150 llamadas de Places/día: mejor tras terminar la importación.
- Pendiente del usuario: un plan de documentación (siguiente sesión).
- **Publicación en GitHub** (rama `feat/publicacion`, revisión prevista la tarde del 1/10): README nuevo ya escrito con huecos para capturas (`<!-- CAPTURA -->`, las pone el usuario en `docs/img/`) y lista completa en `docs/publicacion.md`. Decisiones pendientes: idioma, licencia, historial (recomendado: repo nuevo con historial limpio), autoría, qué se publica de `docs/superpowers/`. `CLAUDE.md` no se publica.

## Publicación en GitHub: cambios ya desplegados (2026-10-02)

- **Compatibilidad previa eliminada** (`223a591`, desplegado ~12:00; `master` = `feat/publicacion`): fuera `no-japon`, los alias `*_japon`, la migración de esquema de `state.db` y el nombre `japan-reader.json`. Lo único histórico que queda es el prefijo `jr`. Antes se migraron los datos: `state.db` (copia en `data/state-pre-compat-2026-10-02.db`: 38 `no-japon`→`descartado`, 1.311 extracts, 1.312 jobs sin candidatos → `["japon"]`), 5.035 adjuntos de Trilium `japan-reader.json`→`tohoku.json` y 38 marcadores de Karakeep `jr:no-japon`→`jr:descartado`. Scripts de una sola vez en el scratchpad de la sesión (no están en el repo).
- `destino_legado` se llama ahora `destino_por_defecto` (clave del YAML).
- `ViajeParams` ya no tiene valores por defecto de país: `pais`, `nombres_pais`, `latitud`, `longitud`, `categorias_lugar` y `categorias_cosa` son obligatorios (`alias_ciudad` opcional). Los valores de Japón están explícitos en `config/destinos.yaml` y `config/destinos.example.yaml`.
- Documentación pública en inglés (base) y español (`.es.md`); decisiones y pendientes en `docs/publicacion.md`.

## Pendientes y mejoras conocidas

- **Duplicados por URL con parámetros**: Karakeep guarda la URL compartida (`?igsh=`, `?stkn=`) y `check-url` compara exacto; un post guardado en Karakeep y también en la exportación no se detecta como existente. Solo afecta a posts recientes (final de la importación). Mejora propuesta: comparar contra URLs canónicas de toda la lista.
- `TNote` (cliente Trilium) no filtra atributos heredados de plantillas (ETAPI los devuelve con otro `noteId`). Hoy sin efecto porque no hay nombres en común; conviene filtrar por `noteId`.
- Fotogramas: con `KEYFRAMES_MAX=6` se pueden perder carteles breves. Decidir con `tohoku eval` (rellenar `eval/cases.yaml` con casos reales) si subirlo o bajar el umbral de escena; también para comparar modelos.
- **Reprocesar desde `geocode` puede dejar huérfanas**: si Google devuelve otro `placeId` para el mismo lugar, la identidad `#jrItem` cambia y se crea otra nota; la anterior queda con la misma fuente. Revisar títulos repetidos tras un reprocesado.
- **Reels con restricción de audiencia** ("This content isn't available to everyone"): corregido para que sea error permanente → respaldo de Karakeep o `jr:error` directo. El caso `pxf0p8pbuma24g7fqxtgsos5` queda pendiente: el usuario lo procesará a mano más adelante.
- **Raíces de destino anidadas** (desde `24a323a`): las notas de estructura se buscan solo como hijas directas de la raíz, así que anidar destinos de tipo distinto (recetas dentro de un viaje) es seguro. Anidar dos del mismo tipo (un viaje dentro de otro, o recetas dentro de recetas) no: las búsquedas de elementos (`#jrItem`, `#googlePlaceId`, `#jrNombreNorm`, `#jrTipo=receta`) siguen siendo a cualquier profundidad y deduplicarían entre ambos. No hacerlo.
- Menores abiertos: un 400 de OpenRouter que cite el modelo podría parar la cola (ConfigError); nota vacía huérfana tras crash+carrera; `geocode` no reanuda lugar a lugar.
