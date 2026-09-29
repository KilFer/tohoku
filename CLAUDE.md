# CLAUDE.md — japan-reader

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

- Contenedor `japan-reader` (compose en este repo), red Docker externa `pangolin`. Límite 6 CPU / 6 GB.
- Desde el contenedor: Karakeep `http://karakeep-web:3000`, Trilium `http://trilium:8080`.
- Desde el host (scripts/tests): Karakeep `http://localhost:3088`, Trilium `http://localhost:8750`.
- Volúmenes: `./data → /data` (state.db, jobs, `data/instagram/`), `whisper-models → /models` (large-v3 ya copiado), `./secrets → /secrets:ro`.
- `data/state.db` lo crea el contenedor como root: usar la CLI dentro del contenedor, no `uv run` sobre `data/`.
- `data/models/` (~3,5 GB) es una copia del host de las pruebas; el contenedor usa el volumen `/models`. Se puede borrar si hace falta espacio.
- No hay remoto git: todo se commitea en `master` local.

## Reglas de trabajo

- **Nunca** crear ni editar `.env`, ni mostrar secretos. Para comprobar credenciales, leer `.env` con `dotenv_values` e imprimir solo presencia/longitud y el resultado de la llamada.
- TDD: test primero (sin red; `tests/fakes.py`, `tests/builders.py`, respx), luego código. `uv run pytest -q` debe quedar en verde.
- Tests de integración solo a mano: `JR_TEST_ROOT_LABEL=... TRILIUM_URL=http://localhost:8750 KARAKEEP_URL=http://localhost:3088 uv run pytest -m integration -k ...`. Requieren una nota con `#jrRootTest` en Trilium (hoy no existe).
- Cada cambio de comportamiento actualiza su doc de etapa / `operations.md`.
- Tras cambiar código: `docker compose build` y `docker compose up -d` (recrea el contenedor). La CLI dentro: `docker compose exec japan-reader japan-reader <cmd>`. `run-once` choca con el lock del servicio en marcha: usar `docker compose run --rm` con el servicio parado.
- Acciones sobre servicios reales (Trilium, Karakeep, importaciones, llamadas de pago) se confirman con el usuario antes; trabaja paso a paso y se detiene para revisión manual entre bloques.
- Commits terminan con `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Estado (2026-09-28)

- En producción: `docker compose up -d`, sondeo cada 10 min. Prueba de humo con 3 enlaces OK (2 lugares en el mapa, 4 cosas, 1 otro; todos `jr:procesado` y archivados).
- `.env` completo: Karakeep (lista "Japón" = `seo5xdpquppqfy4hmzzeekfh`), Trilium v0.106, OpenRouter `openai/gpt-6-luna` (key con límite 8 $, presupuesto 2 $/día), Google Places (cuota diaria ~200 en Cloud Console, `PLACES_DAILY_LIMIT=150`), ntfy `https://ntfy.belaza.me` topic `kamo`. Sin cookies de Instagram (de momento no hacen falta).
- Medidas reales: ~2 min por Reel (Whisper large-v3 ~90 s), ~0,001 $ de LLM por enlace. `small` de Whisper no basta (confundió "Miki Jet" con "Mickey Jet").

### Correcciones hechas en la puesta en marcha (no estaban en el plan)
- `e3c64ad` Places: con `regionCode=JP` Google omite el país en `formattedAddress` → se pide `places.postalAddress` (Pro) y se usa `regionCode` y la prefectura.
- `6e1f9b0` Geocode: entre varios resultados válidos gana el de nombre más parecido, no el primero.
- `ab99cc3` OpenRouter: `temperature` solo si el modelo la admite (modelos de razonamiento no; con `require_parameters` daba 404).
- `659102c` Posts de Instagram: gallery-dl sin cookies recibe "redirect to login" en todos los posts → plan B con yt-dlp (caption + imágenes a tamaño original); la redirección a login es error permanente (antes quemaba 5 h de reintentos).
- `8e1a8fe` Geocode de áreas: ciudades, barrios e islas llegan sin `postalAddress` y se descartaban (`geocodificacion-fallida`, una nota repetida por fuente) → país y ciudad también de `addressComponents` (Pro); los lugares que sigan sin ficha se deduplican por `#jrNombreNorm`.
- `17950b7` Importador: formato de exportación 2026 (lista de colecciones con posts anidados, mojibake), del más antiguo al más reciente, `--limit N` por tandas.

## Importación del historial de Instagram (EN CURSO)

- Fichero: `data/instagram/saved_collections.json` (en el contenedor: `/data/instagram/saved_collections.json`). Colección a importar: **"Cosas de Japon"** = 2.288 enlaces (2.166 Reels, 122 posts). Otras colecciones (Recetas, Para la casa, Boda) no se importan.
- Comando de cada tanda (relanzarlo importa la siguiente; `--dry-run` primero para ver qué entraría):
  `docker compose exec japan-reader japan-reader import-instagram /data/instagram/saved_collections.json --collection "Cosas de Japon" --limit N`
- Plan: primera tanda de 20 → revisar tiempos, coste, Bandeja de revisión y calidad → tandas de 50-100/día ajustando `OPENROUTER_DAILY_BUDGET_USD` y `PLACES_DAILY_LIMIT`. Estimación total: ~75-80 h de CPU, 3-5 $ de LLM, 2.000-4.000 búsquedas de Places.
- Progreso: consultar con `--dry-run` (línea `Ya existían / Pendientes`) y `docker compose exec japan-reader japan-reader status`.
  - 2026-09-28: dry-run de la primera tanda → 20 nuevos, 0 existentes, 2.268 pendientes.
  - 2026-09-28 ~23:55: **tanda 1 importada** (20 creados, 2.268 pendientes). Revisión prevista a la mañana siguiente: `status`, logs, Bandeja de revisión, coste del día, calidad de notas.
  - 2026-09-29: revisión tanda 1 → 16 procesados, 7 revisar, 1 no-Japón. El único post falló (gallery-dl exige login) → arreglado con `659102c` y reprocesado (6 torres, 4 nuevas + 2 fusionadas). Revisar: 1 baja confianza, 4 ciudades sin punto exacto (aceptable para el usuario), 1 cosa genérica ("Comida preparada refrigerada", el usuario la borrará si no se enriquece), 1 geocodificación ambigua.
  - 2026-09-29 ~08:45: **tanda 2 importada** (50 creados, 20 ya existían, 2.218 pendientes).
  - 2026-09-29: tanda 2 terminada (84 búsquedas de Places en 50 enlaces). Total: 49 procesados, 24 revisar, 1 no-Japón; hoy 0,046 $ de LLM y 113 llamadas a Places.
  - 2026-09-29: **tanda 3 importada** (40 creados, 70 ya existían, 2.178 pendientes). Con 113/150 de Places gastados, parte se geocodificará al día siguiente (la cola espera sola).
  - 2026-09-29 ~10:30: desplegado `8e1a8fe` (la tanda 3 ya se procesa con él). Pendiente: el usuario borra en Trilium las 26 notas de áreas en la Bandeja y después se reprocesan desde `geocode` estos 13 jobs (~68 llamadas a Places):
    `reprocess --from geocode dhsw4ldl3khzd145e9385sl7 juv01lhqf91wby9ozcvfxkec mo91h0rd3jg7ccc2q7o6dmc7 rc7gk19vmlmwoyv07zb4ubk6 kveqwi6kyzy2qhcvszcij9i1 t7yi0nvsouv6yll97muff1b0 cnvwjfo8jqz4edavehnqlz43 j9o6xkshwsb59d18uskhjydk nrlo70v8zi5llfcsa6i9dorl pcw1o9bw3676298ddec7s8an dw92dzjxj8c7yf7y5mhqbis2 leixw9zvipkmbklu5uzzlnzj x1kiqes6t6i3s6igdd8orywg`
  - 2026-09-29 ~11:30: 26 notas borradas por ETAPI (borrar en la Bandeja solo quita el clon; la nota sigue en el Mapa). Contador de Places de ese día bajado a mano a 87 (quedaban 63 en Google Cloud, excepción puntual). Reprocesados 10 de 13; quedan `dw92dz`, `leixw9`, `x1kiqe` en espera de cuota (se reanudan solos). 58 geocodificaciones, 56 sin revisión. Kioto = 1 nota con 2 fuentes. Huérfana: "Koyasan" `EUCc4I9K6WoF` (Google devolvió otro placeId al reprocesar; la vigente es `0j3tghMvbFK0`).

## Pendientes y mejoras conocidas

- **Duplicados por URL con parámetros**: Karakeep guarda la URL compartida (`?igsh=`, `?stkn=`) y `check-url` compara exacto; un post guardado en Karakeep y también en la exportación no se detecta como existente. Solo afecta a posts recientes (final de la importación). Mejora propuesta: comparar contra URLs canónicas de toda la lista.
- `TNote` (cliente Trilium) no filtra atributos heredados de plantillas (ETAPI los devuelve con otro `noteId`). Hoy sin efecto porque no hay nombres en común; conviene filtrar por `noteId`.
- Fotogramas: con `KEYFRAMES_MAX=6` se pueden perder carteles breves. Decidir con `japan-reader eval` (rellenar `eval/cases.yaml` con casos reales) si subirlo o bajar el umbral de escena; también para comparar modelos.
- **Reprocesar desde `geocode` puede dejar huérfanas**: si Google devuelve otro `placeId` para el mismo lugar, la identidad `#jrItem` cambia y se crea otra nota; la anterior queda con la misma fuente. Revisar títulos repetidos tras un reprocesado.
- **Reels con restricción de audiencia** ("This content isn't available to everyone"): corregido para que sea error permanente → respaldo de Karakeep o `jr:error` directo. El caso `pxf0p8pbuma24g7fqxtgsos5` queda pendiente: el usuario lo procesará a mano más adelante.
- Menores abiertos: un 400 de OpenRouter que cite el modelo podría parar la cola (ConfigError); nota vacía huérfana tras crash+carrera; `geocode` no reanuda lugar a lugar.
