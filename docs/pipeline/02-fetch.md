# Etapa 2 — fetch

**Qué hace:** descarga el contenido y sus metadatos y prepara los medios para las etapas siguientes.

**Entrada:** job (`url`, `platform`, `hint`).
**Salida:** `FetchResult {meta, audio_files, subtitles, images, keyframes}`; ficheros en `data/jobs/<bookmark_id>/` (`audio/NN.wav`, `images/NN.jpg`, `frames/VV_NN.jpg`). El vídeo original se borra al terminar.

| Tipo | Herramienta | Qué se obtiene |
|---|---|---|
| Vídeo (Short, Reel) | yt-dlp | vídeo ≤720p, subtítulos **manuales** (es > en > ja), metadatos |
| Post de imagen / carrusel | gallery-dl | imágenes (y vídeos del carrusel), caption, autor, fecha |

- Audio: WAV mono 16 kHz con ffmpeg (si el vídeo tiene audio).
- Fotogramas clave (si `REEL_KEYFRAMES_ENABLED=true`): primer fotograma + cambios de escena (umbral 0.3), completado con muestreo uniforme, sin casi-duplicados, máximo `KEYFRAMES_MAX`.
- Imágenes: máximo `POST_IMAGES_MAX`, redimensionadas a `IMAGE_MAX_SIDE` px (JPEG).
- Vídeos de más de `MAX_VIDEO_DURATION_MIN` se rechazan antes de descargar.

**Respaldo:** si Instagram falla de forma permanente (p. ej. requiere login), se usan el vídeo o la imagen que Karakeep archivó del bookmark.

**Dependencias:** yt-dlp, gallery-dl, ffmpeg/ffprobe, Pillow, Karakeep (respaldo).
**Configuración:** `INSTAGRAM_COOKIES_FILE` (se usa una copia; el original nunca se modifica), `REEL_KEYFRAMES_ENABLED`, `KEYFRAMES_MAX`, `POST_IMAGES_MAX`, `IMAGE_MAX_SIDE`, `MAX_VIDEO_DURATION_MIN`.

**Fallos:** privado/borrado/login requerido/404/demasiado largo → `PermanentError` (`jr:error`); timeouts y 5xx → `TransientError` (reintento); fichero de cookies inexistente → `ConfigError`.

**Cómo probarla:** `uv run pytest tests/unit/test_fetch.py tests/unit/test_downloaders.py tests/unit/test_media.py`. Descarga real: `uv run pytest -m integration -k ytdlp`.
