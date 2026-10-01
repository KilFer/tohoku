# Operación de Tohoku

## Día a día
- Guarda el enlace (Short, Reel o post) en una lista de Karakeep que figure en `config/destinos.yaml` (hoy, la lista **Japón**). Nada más.
- En ≤10 minutos se procesa. Los Reels tardan unos minutos más (Whisper en CPU).
- Resultado en Karakeep: `jr:procesado` / `jr:revisar` / `jr:descartado` (archivados) o `jr:error` (visible en la Home), más `jr:destino:<destino>` con el destino elegido. `jr:no-japon` es la etiqueta antigua de descartado y se sigue reconociendo.

## Revisar la bandeja
En Trilium, `Ideas de Japón › Bandeja de revisión`. Cada nota lleva `#revisar=<motivos>`:
- `geocodificacion-fallida` / `geocodificacion-ambigua`: corrige `#geolocation` (lat,lng) y `#googleMaps` si hace falta.
- `posible-duplicado`: si es la misma cosa que otra nota, copia lo útil a la otra y borra esta.
- `clasificacion-dudosa`: el clasificador dudó entre dos destinos; si la nota no está donde debe, `reprocess <id> --destino X`.
- `baja-confianza` / `clasificacion-incierta`: comprueba que el contenido tiene sentido.
- `extraccion-fallida`: la nota trae caption y transcripción; crea la nota a mano o reprocesa.
Al terminar: quita `#revisar` y quita el clon de la bandeja (clic derecho → "Eliminar" solo en la rama de la bandeja).

## Destinos: `config/destinos.yaml`
Qué listas de Karakeep se procesan y cómo se publica cada una. Una lista puede tener varios destinos candidatos; entonces `classify` elige uno con un LLM. Estructura:

    listas:
      seo5xdpquppqfy4hmzzeekfh: [japon]   # id de la lista de Karakeep → destinos candidatos
    destinos:
      japon:
        flujo: viaje                      # viaje | receta (docs/flujos/receta.md)
        raiz: jrRoot                      # etiqueta de la nota raíz en Trilium
        descripcion: "Viaje a Japón: ..."
        prompt: prompts/japon.md          # relativo a config/
        pais: JP                          # ISO 3166-1; regionCode de Places
        # opcionales (por defecto, los de Japón): nombres_pais, latitud, longitud,
        # categorias_lugar, categorias_cosa, alias_ciudad
    clasificador:                         # opcional
      modelo: ...                         # por defecto OPENROUTER_TEXT_MODEL
      modo: json_schema                   # o etiqueta
      confianza_minima: 0.5               # por debajo → descartado
      margen_revision: 0.15               # alternativa más cerca → clasificacion-dudosa
    destino_legado: japon                 # jobs anteriores a la fase 3; obligatorio con varios destinos

- El servicio sondea **todas** las listas del YAML. `KARAKEEP_LIST_ID` y `TRILIUM_ROOT_LABEL` ya no se leen de `.env` (si siguen ahí, se ignoran). La ruta del YAML es `DESTINOS_FILE` (por defecto `config/destinos.yaml`).
- Un fichero inválido (YAML mal formado, clave desconocida o mal escrita, `#` en la raíz, prompt inexistente, lista que apunta a un destino que no existe) da `Error de configuración` con el nombre de la clave y sale con código 2.
- La imagen lleva `config/` dentro (`COPY config ./config`) y el compose lo monta de solo lectura (`./config:/app/config:ro`): **editar `config/` no requiere reconstruir**, basta `docker compose restart tohoku`.
- Tras editar `config/` y reiniciar, mira `docker compose logs tohoku`: un error de configuración hace que el contenedor salga al arrancar (código 2) **sin aviso por ntfy**.
- Vuelta atrás: desde la fase 2 los resultados nuevos de `extract` se guardan como `relacionado_destino`/`confianza_destino`, que el código anterior a la fase 2 no sabe leer. Si haces rollback, ejecuta `reprocess --from extract` sobre los jobs pendientes más allá de `extract`.
- El prompt de Japón es `config/prompts/japon.md`. Solo se sustituyen los marcadores `{{categorias_lugar}}` y `{{categorias_cosa}}` (las categorías del destino); el resto del texto es tuyo. Si el LLM devuelve una categoría que no es del destino, se reintenta una vez con el error.
- `destino_legado` (por defecto, el único destino) es el destino de los jobs creados antes de la fase 3 y de un `reprocess` de un bookmark que no está en `state.db`. Un destino quitado del YAML no para la cola: `classify` ignora esos candidatos (cae en `destino_legado`) y solo falla (`jr:error`) el job cuyo destino ya decidido o forzado no existe.
- El clasificador solo se monta si algún bookmark puede tener varios candidatos (una lista con varios destinos o listas con destinos distintos, porque la ingesta une los candidatos de todas sus listas) y solo se llama con varios candidatos; el preflight comprueba su modelo solo en ese caso (en modo `json_schema` también que admita salida estructurada). Con un candidato no hay llamada al LLM. Si no hay caption ni transcripción, se clasifica con imágenes usando `OPENROUTER_MODEL` (multimodal) en lugar de `clasificador.modelo`.
- Dos destinos cuyo nombre solo difiere en mayúsculas, acentos o separadores (`japon`/`Japón`) son un error de configuración: el clasificador no los distinguiría.
- Vuelta atrás desde las fases 3/4: el código anterior a la fase 3 no sabe leer el resultado `descartado` (antes `no-japon`) ni la marca `files_purged` de `fetch`. Antes de desplegar haz una copia de `state.db` con el servicio parado (`sudo sqlite3 data/state.db ".backup data/state-antes-fase3.db"`; el fichero es de root); para volver atrás más allá de la fase 3 hay que restaurar esa copia (se pierde lo procesado después) o no retroceder más allá de la fase 3.
- `init-trilium [--destino X]` crea la estructura bajo la raíz de ese destino (por defecto, el único; con varios destinos `--destino` es obligatorio). `eval --destino X` evalúa con el prompt de ese destino (solo destinos de flujo `viaje`; con otro flujo falla con un error de configuración). `import-instagram ... [--lista ID]` elige la lista de Karakeep destino (por defecto, la única del YAML; con varias hay que indicarla).

### Activar Recetas (fase 5, sin desplegar)

1. En Trilium, crea la nota raíz del Recetario y márcala con `#jrRootRecetas` (para pruebas, `#jrRootRecetasTest`).
2. En `config/destinos.yaml` descomenta el bloque `recetas`, añade en `listas` la lista de Karakeep de recetas (`<id>: [recetas]`) y descomenta `destino_legado: japon` (con varios destinos es obligatorio). Con una lista que lleve solo `recetas` y otra solo `japon`, un bookmark en ambas pasa por `classify` (hay clasificador desde que existen dos destinos).
3. `docker compose exec tohoku tohoku init-trilium --destino recetas` (`./config` está montado de solo lectura en el contenedor, así que `exec` ya ve el YAML editado). Es idempotente, pero no añade atributos promovidos nuevos a una plantilla `Receta` que ya exista: si cambias `atributos`, añade los promovidos a mano en Trilium.
4. `docker compose restart tohoku` (el primer arranque comprueba el modelo del clasificador). El orden importa: si reinicias antes de `init-trilium`, el preflight falla en `refresh()` y se pausan **todas** las colas (también Japón) con un aviso de error de configuración en ntfy.
5. Ver `docs/flujos/receta.md`.

### Cómo añadir un destino

Un destino de viaje nuevo (Nueva Zelanda, Portugal...) es solo configuración: no se toca `src/`. El ejemplo completo está comentado al final de `config/destinos.yaml` (`nueva_zelanda`) y probado en `tests/unit/test_destino_nz.py` con `tests/fixtures/destinos_tres.yaml`.

1. En Karakeep, crea la lista del destino y anota su id.
2. En Trilium, crea la nota raíz del destino y márcala con su etiqueta (`#jrRootNZ`; en pruebas, la variante `Test`).
3. Escribe el prompt en `config/prompts/<destino>.md`: copia `config/prompts/japon.md` y adapta país, ciudades y regiones; conserva los campos y los marcadores `{{categorias_lugar}}` y `{{categorias_cosa}}`.
4. En `config/destinos.yaml`: añade el bloque del destino (`flujo: viaje`, `raiz`, `descripcion`, `prompt`, `pais` ISO-2, `nombres_pais`, `latitud`/`longitud` [mín, máx] del país, `categorias_lugar`, `categorias_cosa`, `alias_ciudad`), su lista en `listas` y, si es el segundo destino, `destino_legado: japon` (obligatorio con varios destinos). El YAML se valida al cargar: un error se ve con `docker compose exec tohoku tohoku init-trilium --destino <nombre>`.
5. `docker compose exec tohoku tohoku init-trilium --destino <nombre>` crea el Mapa, "Comprar y comer", "Cultura y curiosidades" y la Bandeja bajo la raíz (idempotente).
6. `docker compose restart tohoku`. **Siempre después de `init-trilium`**: si el servicio arranca con un destino sin estructura, el preflight falla en `refresh()` y se pausan todas las colas (también las de Japón) con un aviso de error de configuración en ntfy.
7. Prueba con unos pocos enlaces (`import-instagram ... --lista <id> --limit 5`) y revisa la Bandeja antes de importar más.

Particularidades (decisión 6 de las fases 5-6): la caché de búsquedas de Places lleva el prefijo `<PAIS>|` salvo en Japón; `palabras_genericas` es global (no distingue destinos); las categorías sin icono usan el pin genérico; los umbrales `JAPAN_*_CONFIDENCE` del `.env` valen para todos los destinos de viaje (el nombre no se cambió para no obligar a editar `.env`). Si al procesar enlaces reales algo de esto molesta, se abre una tarea aparte.

Asimetría de código: el flujo `viaje` vive en `src/tohoku/stages/` (+ `geo.py`, `trilium_layout.py`, `notes.py`) y el flujo `receta` en `src/tohoku/flows/receta/`; no se movieron los módulos del viaje (decisión de las fases 5-6, hoja de ruta). Las utilidades comunes están en módulos neutros (`publishing.py`, `llm_json.py`). `reprocess --from extract` también repite `cover` en recetas (orden canónico de etapas).

## Comandos
    docker compose exec tohoku tohoku status
    docker compose run --rm tohoku tohoku run-once   # solo con el servicio parado (candado)
    docker compose exec tohoku tohoku reprocess <bookmarkId> [<bookmarkId>...] --from extract
    docker compose exec tohoku tohoku reprocess --all-errors --from fetch
    docker compose logs -f tohoku

`run` y `run-once` toman un candado exclusivo en `DATA_DIR/tohoku.lock`: si ya hay otra instancia en marcha (p. ej. el contenedor), `run-once` sale con código 3 y un mensaje claro, y `run` lo registra en el log y sale con código 3. El resto de comandos (`status`, `reprocess`...) no lo necesitan.

`reprocess --from`: `fetch` (vuelve a descargar), `classify` (decide otra vez el destino), `extract` (nuevo prompt o modelo, sin re-transcribir), `geocode`, `resolve`, `publish`. En un job de receta no hay etapa `geocode` ni existe `--from cover`: `--from geocode` actúa como "desde `cover`" (repite `cover`, `resolve` y `publish`, y vuelve a descargar si los ficheros ya se limpiaron). El bookmarkId está en la URL del bookmark en Karakeep. Admite varios ids a la vez; `--all-errors` vuelve a poner en cola **todos** los jobs en error (útil tras corregir cookies o el modelo).

`reprocess --destino X` fuerza el destino (debe estar configurado en `destinos.yaml`) y repite desde `classify`; `classify` respeta el destino guardado y no llama al LLM. Las notas ya publicadas en Trilium **no se borran**: si el destino cambia, bórralas a mano. Sin `--destino`, `--from fetch|classify` olvida el destino y se reclasifica; `--from extract` o posterior lo conserva. Si la clasificación quedó dudosa, las notas llevan el motivo `clasificacion-dudosa`.

## Cambiar de modelo
1. Rellena `eval/cases.yaml` con 10-15 casos reales.
2. `docker compose run --rm -v ./eval:/app/eval tohoku tohoku eval --model <modelo>` y lo mismo con `--no-keyframes`.
3. Elige por aciertos (columna Lugares) y coste; cambia `OPENROUTER_MODEL` en `.env` y `docker compose up -d`.
Al arrancar se comprueba que `OPENROUTER_MODEL` y `OPENROUTER_TEXT_MODEL` existen en OpenRouter y admiten salida JSON estructurada (`response_format`/`structured_outputs`), y que `OPENROUTER_MODEL` admite imágenes. Si un modelo deja de estar disponible (p. ej. "not a valid model", "No endpoints found"), el servicio se pausa y avisa por ntfy una vez, sin marcar `jr:error` en los enlaces.
Si el coste de visión es alto: `REEL_KEYFRAMES_ENABLED=false`.

## Cookies de Instagram
Cuando aparezcan `jr:error` con "login required": exporta las cookies de instagram.com (formato Netscape) desde un navegador con una **cuenta secundaria** a `secrets/instagram_cookies.txt`, pon `INSTAGRAM_COOKIES_FILE=/secrets/instagram_cookies.txt` en `.env`, `docker compose up -d` y reprocesa los fallidos con `reprocess <id> --from fetch`. El servicio trabaja con una copia: el fichero original no se modifica.
Para no disparar los límites de ritmo de Instagram, entre dos descargas de Instagram pasan al menos `INSTAGRAM_MIN_INTERVAL_SECONDS` (20 s por defecto). Un "rate-limit reached" no marca `jr:error`: se reintenta con espera.

## Importar el historial de Instagram
1. Instagram → Centro de cuentas → Tu información y permisos → Descargar tu información → solo "Guardado", formato **JSON**.
2. Copia al servidor el .zip, la carpeta o solo `saved_collections.json`, p. ej. en `data/instagram/`.
3. Simulación (solo lee Karakeep, no escribe): `docker compose exec tohoku tohoku import-instagram /data/instagram/saved_collections.json --collection "Cosas de Japon" --limit 20 --dry-run`
4. Importa por tandas: el mismo comando sin `--dry-run`. `--limit N` cuenta solo enlaces **nuevos**, del **más antiguo al más reciente**; relanzarlo importa la siguiente tanda (los ya importados se detectan con `check-url` y se saltan). La línea final indica `Pendientes`.
5. Ritmo recomendado: una tanda de 50-100 al día, ajustando `OPENROUTER_DAILY_BUDGET_USD` y `PLACES_DAILY_LIMIT`. Cada Reel ocupa ~2 min de CPU (Whisper large-v3).

Formatos admitidos de `saved_collections.json`: el clásico (cabecera de colección seguida de sus posts) y el de 2026 (lista de colecciones con los posts anidados en `label_values`). El mojibake de Instagram (`OpciÃ³n`) se corrige al leer los nombres de colección.
Nota: si un enlace ya estaba en Karakeep con otra forma de URL (p. ej. con `?igsh=`), puede crearse un segundo bookmark; la nota de Trilium no se duplica.

## Avisos (ntfy)
Llegan avisos por: error definitivo de un enlace, error de configuración (el servicio se pausa hasta que se corrija), límite diario alcanzado (un aviso por cuota y día). Con una cuota agotada la cola no se para: solo esperan los jobs que la necesitan, y el resto sigue descargando, transcribiendo y publicando. Con `NTFY_DAILY_SUMMARY=true`, resumen a partir de las 21:00.

## Costes y cuotas
- Google Cloud Console → APIs → Places API (New) → Cuotas: limita "SearchTextRequest per day" al mismo valor que `PLACES_DAILY_LIMIT` como red de seguridad. Google cuenta el día y el mes en hora del Pacífico; el servicio también (contadores de cuota y reintentos por cuota). El cupo gratuito de Text Search Pro es de 5.000 al mes.
- OpenRouter: `OPENROUTER_DAILY_BUDGET_USD`. `status` muestra el consumo del día.

## Limpieza
Clave opcional del YAML `config/destinos.yaml`: `limpieza: {retencion_dias: N}` (por defecto 30; entero >= 0; 0 = borrar todos los resultados de etapa nada más terminar).

- **Al terminar un job** con cualquier resultado salvo `error`: se borra su directorio `data/jobs/<id>/` (audio, fotogramas, imágenes). Su resultado de `fetch` **no se borra**: se conservan los metadatos (título, autor, caption, URL, que usa `publish`) y se marca `files_purged: true`. Con `retencion_dias: 0` se borran en cambio todos sus resultados de etapa.
- **En cada pasada del servicio** (`purge`): se borran los resultados de etapa de jobs terminados (`done`) cuya última actualización (`jobs.updated_at`) es anterior a `retencion_dias`; y los directorios de jobs `done` que sigan en disco (su `fetch` queda marcado `files_purged`, como al terminar). Nunca se tocan los jobs pendientes ni los `error` (sus ficheros se conservan para diagnosticar hasta que un reprocesado los termine), ni la tabla `jobs`, ni `published`.
- Seguridad: solo ids simples, solo hijos directos de `data/jobs`, sin seguir enlaces simbólicos.
- **Primera pasada tras desplegar**: elimina de golpe todos los directorios de jobs terminados y escribe una línea `limpieza jobs=N`. Con la copia de prueba del 2026-09-30: 969 directorios borrados, `data/jobs` de 230 MB a 12 MB (quedan los de pendientes y error). Al desplegar habrá bastantes más (~2.300). Comprobar con `du -sh data/jobs` antes y después.

**Atención: consecuencias para `reprocess`.** Un job limpiado conserva su `fetch` con `files_purged: true`. El pipeline solo vuelve a descargar cuando va a ejecutar una etapa que necesita los ficheros (`transcribe` o `extract`, marcadas `needs_files`; `classify` solo si va a clasificar con imágenes: varios candidatos y sin caption ni transcripción), y como mucho una vez por job (en el log: `bookmark=<id> re-descarga: los ficheros se limpiaron`):

| Comando sobre un job limpiado | Qué descarga o repite |
|---|---|
| `reprocess --from geocode`, `--from resolve` o `--from publish` (dentro de la retención) | No descarga nada, y no falla aunque el Reel ya no exista: usa la transcripción y la extracción guardadas (un job anterior a la fase 3, sin `classify`, toma `destino_legado` sin descargar) |
| `reprocess --from extract` o `--from classify` | Vuelve a descargar (necesita fotogramas e imágenes); si el Reel se ha borrado o restringido, acaba en `jr:error` |
| `reprocess --from fetch` | Como siempre: descarga y lo repite todo |
| Pasada la retención (`retencion_dias`), o con `retencion_dias: 0` | No queda ningún resultado de etapa: se rehace todo (descarga, Whisper, LLM y Places, con su cuota y su coste) |

`transcribe` también necesita los ficheros, pero no es un `--from` válido: se repite con `--from fetch`. Los jobs en `error` conservan sus ficheros (no se limpian) hasta que un reprocesado los termina. Recomendación: reprocesar desde `extract`/`classify` en tandas pequeñas, para no chocar con los límites de ritmo de Instagram (`INSTAGRAM_MIN_INTERVAL_SECONDS`).

## Copias de seguridad
`data/state.db` guarda el estado de la cola. Si se pierde, no se reprocesan los bookmarks ya etiquetados `jr:*`; las notas de Trilium tienen su propio adjunto `japan-reader.json`.
