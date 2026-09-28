# Etapa 3 — transcribe

**Qué hace:** obtiene el texto hablado del contenido.

**Entrada:** `FetchResult.audio_files` y `FetchResult.subtitles`.
**Salida:** `Transcript {text, language, origin: subtitulos|whisper|none}`.

**Reglas:**
- Si hay subtítulos manuales con al menos 5 palabras, se usan y no se ejecuta Whisper.
- Sin audio (posts de imagen o carrusel sin vídeos) → `origin=none`, texto vacío.
- Carruseles con varios vídeos: cada pista se transcribe por separado y se etiqueta `[Elemento N]`.
- Al terminar se borran los WAV (se conservan imágenes y fotogramas para poder reprocesar desde `extract`).

**Dependencias:** faster-whisper (CTranslate2, CPU). El modelo (~3 GB para `large-v3`) se descarga una vez en `WHISPER_DOWNLOAD_ROOT` (volumen `/models` en Docker).
**Configuración:** `WHISPER_MODEL` (`large-v3` por defecto; `large-v3-turbo` más rápido), `WHISPER_COMPUTE_TYPE` (`int8`), `WHISPER_THREADS` (6), VAD activado, `beam_size=5`.

**Rendimiento esperado:** en el Xeon E5-2620 v3, unos pocos minutos por minuto de audio con `large-v3`. La cola es secuencial.

**Fallos:** errores de la librería o de lectura → reintento del job (el audio no se borra hasta terminar bien).

**Cómo probarla:** `uv run pytest tests/unit/test_transcribe.py`. Con modelo real: `uv run pytest -m integration -k whisper`.
