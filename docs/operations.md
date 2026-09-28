# Operación de japan-reader

## Día a día
- Guarda el enlace (Short, Reel o post) en la lista **Japón** de Karakeep. Nada más.
- En ≤10 minutos se procesa. Los Reels tardan unos minutos más (Whisper en CPU).
- Resultado en Karakeep: `jr:procesado` / `jr:revisar` / `jr:no-japon` (archivados) o `jr:error` (visible en la Home).

## Revisar la bandeja
En Trilium, `Ideas de Japón › Bandeja de revisión`. Cada nota lleva `#revisar=<motivos>`:
- `geocodificacion-fallida` / `geocodificacion-ambigua`: corrige `#geolocation` (lat,lng) y `#googleMaps` si hace falta.
- `posible-duplicado`: si es la misma cosa que otra nota, copia lo útil a la otra y borra esta.
- `baja-confianza` / `clasificacion-incierta`: comprueba que el contenido tiene sentido.
- `extraccion-fallida`: la nota trae caption y transcripción; crea la nota a mano o reprocesa.
Al terminar: quita `#revisar` y quita el clon de la bandeja (clic derecho → "Eliminar" solo en la rama de la bandeja).

## Comandos
    docker compose exec japan-reader japan-reader status
    docker compose run --rm japan-reader japan-reader run-once   # solo con el servicio parado (candado)
    docker compose exec japan-reader japan-reader reprocess <bookmarkId> [<bookmarkId>...] --from extract
    docker compose exec japan-reader japan-reader reprocess --all-errors --from fetch
    docker compose logs -f japan-reader

`run` y `run-once` toman un candado exclusivo en `DATA_DIR/japan-reader.lock`: si ya hay otra instancia en marcha (p. ej. el contenedor), `run-once` sale con código 3 y un mensaje claro, y `run` lo registra en el log y sale con código 3. El resto de comandos (`status`, `reprocess`...) no lo necesitan.

`reprocess --from`: `fetch` (vuelve a descargar), `extract` (nuevo prompt o modelo, sin re-transcribir), `geocode`, `resolve`, `publish`. El bookmarkId está en la URL del bookmark en Karakeep. Admite varios ids a la vez; `--all-errors` vuelve a poner en cola **todos** los jobs en error (útil tras corregir cookies o el modelo).

## Cambiar de modelo
1. Rellena `eval/cases.yaml` con 10-15 casos reales.
2. `docker compose run --rm -v ./eval:/app/eval japan-reader japan-reader eval --model <modelo>` y lo mismo con `--no-keyframes`.
3. Elige por aciertos (columna Lugares) y coste; cambia `OPENROUTER_MODEL` en `.env` y `docker compose up -d`.
Al arrancar se comprueba que `OPENROUTER_MODEL` y `OPENROUTER_TEXT_MODEL` existen en OpenRouter y admiten salida JSON estructurada (`response_format`/`structured_outputs`), y que `OPENROUTER_MODEL` admite imágenes. Si un modelo deja de estar disponible (p. ej. "not a valid model", "No endpoints found"), el servicio se pausa y avisa por ntfy una vez, sin marcar `jr:error` en los enlaces.
Si el coste de visión es alto: `REEL_KEYFRAMES_ENABLED=false`.

## Cookies de Instagram
Cuando aparezcan `jr:error` con "login required": exporta las cookies de instagram.com (formato Netscape) desde un navegador con una **cuenta secundaria** a `secrets/instagram_cookies.txt`, pon `INSTAGRAM_COOKIES_FILE=/secrets/instagram_cookies.txt` en `.env`, `docker compose up -d` y reprocesa los fallidos con `reprocess <id> --from fetch`. El servicio trabaja con una copia: el fichero original no se modifica.
Para no disparar los límites de ritmo de Instagram, entre dos descargas de Instagram pasan al menos `INSTAGRAM_MIN_INTERVAL_SECONDS` (20 s por defecto). Un "rate-limit reached" no marca `jr:error`: se reintenta con espera.

## Importar el historial de Instagram
1. Instagram → Centro de cuentas → Tu información y permisos → Descargar tu información → solo "Guardado", formato **JSON**.
2. Copia al servidor el .zip, la carpeta o solo `saved_collections.json`, p. ej. en `data/instagram/`.
3. Simulación (solo lee Karakeep, no escribe): `docker compose exec japan-reader japan-reader import-instagram /data/instagram/saved_collections.json --collection "Cosas de Japon" --limit 20 --dry-run`
4. Importa por tandas: el mismo comando sin `--dry-run`. `--limit N` cuenta solo enlaces **nuevos**, del **más antiguo al más reciente**; relanzarlo importa la siguiente tanda (los ya importados se detectan con `check-url` y se saltan). La línea final indica `Pendientes`.
5. Ritmo recomendado: una tanda de 50-100 al día, ajustando `OPENROUTER_DAILY_BUDGET_USD` y `PLACES_DAILY_LIMIT`. Cada Reel ocupa ~2 min de CPU (Whisper large-v3).

Formatos admitidos de `saved_collections.json`: el clásico (cabecera de colección seguida de sus posts) y el de 2026 (lista de colecciones con los posts anidados en `label_values`). El mojibake de Instagram (`OpciÃ³n`) se corrige al leer los nombres de colección.
Nota: si un enlace ya estaba en Karakeep con otra forma de URL (p. ej. con `?igsh=`), puede crearse un segundo bookmark; la nota de Trilium no se duplica.

## Avisos (ntfy)
Llegan avisos por: error definitivo de un enlace, error de configuración (el servicio se pausa hasta que se corrija), límite diario alcanzado (en cuanto se alcanza, la pasada se detiene y el resto de enlaces siguen pendientes hasta la siguiente). Con `NTFY_DAILY_SUMMARY=true`, resumen a partir de las 21:00.

## Costes y cuotas
- Google Cloud Console → APIs → Places API (New) → Cuotas: limita "SearchTextRequest per day" a ~200 como red de seguridad.
- OpenRouter: `OPENROUTER_DAILY_BUDGET_USD`. `status` muestra el consumo del día.

## Copias de seguridad
`data/state.db` guarda el estado de la cola. Si se pierde, no se reprocesan los bookmarks ya etiquetados `jr:*`; las notas de Trilium tienen su propio adjunto `japan-reader.json`.
