# Etapa 2 — fetch

**Qué hace:** descarga el contenido y sus metadatos y prepara los medios para las etapas siguientes.

**Entrada:** job (`url`, `platform`, `hint`).
**Salida:** `FetchResult {meta, audio_files, subtitles, images, keyframes}`; ficheros en `data/jobs/<bookmark_id>/` (`audio/NN.wav`, `images/NN.jpg`, `frames/VV_NN.jpg`). El vídeo original se borra al terminar la etapa.

**Atención (limpieza y reprocesado):** cuando el job termina (salvo `error`, que conserva los ficheros hasta que un reprocesado lo termine) se borra `data/jobs/<id>/`, pero el resultado de `fetch` **se conserva** con sus metadatos (título, autor, caption, URL, que usa `publish`) y la marca `files_purged: true` (los resultados antiguos sin la clave se leen como `false`). El pipeline vuelve a ejecutar `fetch` solo si va a ejecutar una etapa que necesita los ficheros (`needs_files`: `transcribe`, `classify` y `extract`) y el `fetch` guardado tiene `files_purged`; como mucho una vez por job.
- `reprocess --from geocode`, `--from resolve` o `--from publish`: no descarga nada ni falla si el Reel ya no existe (dentro de la retención).
- `--from extract`, `--from classify` o `--from transcribe`: vuelve a descargar (necesita audio o fotogramas); falla si el original ya no está disponible.
- `--from fetch`: como siempre.
- Pasada la retención (`retencion_dias`), o con `retencion_dias: 0`: no quedan resultados de etapa y se rehace todo (descarga, Whisper, LLM y Places).

Ver la sección "Limpieza" de `docs/operations.md`.

| Tipo | Herramienta | Qué se obtiene |
|---|---|---|
| Vídeo (Short, Reel) | yt-dlp | vídeo ≤720p, subtítulos **manuales** (es > en > ja), metadatos |
| Post de imagen / carrusel | gallery-dl; si falla de forma permanente, yt-dlp | imágenes (y vídeos del carrusel), caption, autor, fecha |

- Audio: WAV mono 16 kHz con ffmpeg (si el vídeo tiene audio).
- Fotogramas clave (si `REEL_KEYFRAMES_ENABLED=true`): primer fotograma + cambios de escena (umbral 0.3), completado con muestreo uniforme, sin casi-duplicados, máximo `KEYFRAMES_MAX`.
- Imágenes: máximo `POST_IMAGES_MAX`, redimensionadas a `IMAGE_MAX_SIDE` px (JPEG).
- Vídeos de más de `MAX_VIDEO_DURATION_MIN` se rechazan antes de descargar.
- Instagram: entre dos descargas consecutivas (yt-dlp o gallery-dl) pasan al menos `INSTAGRAM_MIN_INTERVAL_SECONDS` segundos (por defecto 20); si hace falta, la etapa espera.
- El directorio temporal `raw/` (vídeo original y copia de las cookies) se borra siempre al terminar, también si la descarga falla.

**Plan B para posts:** sin cookies, gallery-dl recibe "HTTP redirect to login page" en cualquier post (comprobado el 2026-09-29). Ante un error permanente de gallery-dl se prueba yt-dlp con `ignore_no_formats_error`: devuelve el caption y, por cada elemento del carrusel, la miniatura a tamaño original (p. ej. 1440×1800), que se descarga como imagen; los elementos con vídeo se descargan como vídeo. Solo pide una petición extra a Instagram por post.

**Respaldo:** si Instagram falla de forma permanente (p. ej. requiere login), se usan el vídeo o la imagen que Karakeep archivó del bookmark. No se usa cuando el vídeo se rechaza por demasiado largo.

**Dependencias:** yt-dlp, gallery-dl, ffmpeg/ffprobe, Pillow, Karakeep (respaldo).
**Configuración:** `INSTAGRAM_COOKIES_FILE` (se usa una copia; el original nunca se modifica), `REEL_KEYFRAMES_ENABLED`, `KEYFRAMES_MAX`, `POST_IMAGES_MAX`, `IMAGE_MAX_SIDE`, `MAX_VIDEO_DURATION_MIN`, `INSTAGRAM_MIN_INTERVAL_SECONDS`. `INSTAGRAM_COOKIES_FILE=` vacío equivale a no configurarlo.

**Fallos:** privado/borrado/login requerido/redirección a login/restricción de audiencia ("isn't available to everyone")/404/demasiado largo → `PermanentError` (`jr:error`); timeouts, 5xx, 429 y límites de ritmo ("rate-limit", "too many requests", "please wait", aunque el mensaje también diga "login required") → `TransientError` (reintento); fichero de cookies inexistente → `ConfigError`.

**Cómo probarla:** `uv run pytest tests/unit/test_fetch.py tests/unit/test_downloaders.py tests/unit/test_media.py`. Descarga real: `uv run pytest -m integration -k ytdlp`.
