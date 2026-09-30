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
        flujo: viaje                      # único flujo por ahora
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
- El clasificador solo se usa con varios candidatos; el preflight comprueba su modelo solo en ese caso (en modo `json_schema` también que admita salida estructurada). Con un candidato no hay llamada al LLM.
- `init-trilium [--destino X]` crea la estructura bajo la raíz de ese destino (por defecto, el único; con varios destinos `--destino` es obligatorio). `eval --destino X` evalúa con el prompt de ese destino. `import-instagram ... [--lista ID]` elige la lista de Karakeep destino (por defecto, la única del YAML; con varias hay que indicarla).

## Comandos
    docker compose exec tohoku tohoku status
    docker compose run --rm tohoku tohoku run-once   # solo con el servicio parado (candado)
    docker compose exec tohoku tohoku reprocess <bookmarkId> [<bookmarkId>...] --from extract
    docker compose exec tohoku tohoku reprocess --all-errors --from fetch
    docker compose logs -f tohoku

`run` y `run-once` toman un candado exclusivo en `DATA_DIR/tohoku.lock`: si ya hay otra instancia en marcha (p. ej. el contenedor), `run-once` sale con código 3 y un mensaje claro, y `run` lo registra en el log y sale con código 3. El resto de comandos (`status`, `reprocess`...) no lo necesitan.

`reprocess --from`: `fetch` (vuelve a descargar), `classify` (decide otra vez el destino), `extract` (nuevo prompt o modelo, sin re-transcribir), `geocode`, `resolve`, `publish`. El bookmarkId está en la URL del bookmark en Karakeep. Admite varios ids a la vez; `--all-errors` vuelve a poner en cola **todos** los jobs en error (útil tras corregir cookies o el modelo).

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

## Copias de seguridad
`data/state.db` guarda el estado de la cola. Si se pierde, no se reprocesan los bookmarks ya etiquetados `jr:*`; las notas de Trilium tienen su propio adjunto `japan-reader.json`.
