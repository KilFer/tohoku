# Etapa 2 — fetch

**Qué hace:** descarga el contenido y sus metadatos y prepara los medios para las etapas siguientes.

**Entrada:** job (`url`, `platform`, `hint`).
**Salida:** `FetchResult {meta, audio_files, subtitles, images, keyframes}`; ficheros en `data/jobs/<bookmark_id>/` (`audio/NN.wav`, `images/NN.jpg`, `frames/VV_NN.jpg`). El vídeo original se borra al terminar.

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

**Fallos:** privado/borrado/login requerido/redirección a login/404/demasiado largo → `PermanentError` (`jr:error`); timeouts, 5xx, 429 y límites de ritmo ("rate-limit", "too many requests", "please wait", aunque el mensaje también diga "login required") → `TransientError` (reintento); fichero de cookies inexistente → `ConfigError`.

**Cómo probarla:** `uv run pytest tests/unit/test_fetch.py tests/unit/test_downloaders.py tests/unit/test_media.py`. Descarga real: `uv run pytest -m integration -k ytdlp`.
