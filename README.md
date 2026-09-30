# Tohoku

Antes *japan-reader*. El prefijo `jr` de etiquetas (`jr:*` en Karakeep), atributos (`#jr*` en Trilium) y del adjunto `japan-reader.json` se mantiene a propósito: son las siglas de *Japan Reader*, el nombre original, y de **JR**, la compañía de la Tohoku Shinkansen.


Convierte YouTube Shorts, Instagram Reels y posts de Instagram guardados en Karakeep en una base de datos de viaje a Japón en Trilium: un **Geo Map** con una nota por lugar y una sección **Comprar y comer** para productos, platos y cadenas.

    Karakeep (lista "Japón") → yt-dlp / gallery-dl → faster-whisper → LLM (OpenRouter, multimodal)
      → Google Places → deduplicación → Trilium → etiqueta + archivo en Karakeep

## Puesta en marcha
1. `cp .env.example .env` y rellénalo.
2. En Trilium, añade la etiqueta `#jrRoot` a `Home › Viajes › Ideas de Japón`.
3. `docker compose build && docker compose run --rm tohoku tohoku init-trilium`
4. `docker compose up -d` y `docker compose logs -f tohoku`.

## Comandos
`run` · `run-once` · `init-trilium` · `status` · `reprocess <id>... | --all-errors [--from <etapa>]` · `import-instagram <export> [--collection] [--limit N] [--dry-run]` · `eval [--model] [--keyframes/--no-keyframes]`

## Documentación
- Diseño: `docs/superpowers/specs/2026-09-28-japan-reader-design.md`
- Etapas: `docs/pipeline/01-ingest.md` … `08-mark.md`
- Modelo de Trilium: `docs/trilium-model.md`
- Operación: `docs/operations.md`
- Estado actual, entorno y pendientes (para retomar el trabajo): `CLAUDE.md`

## Desarrollo
    uv sync
    uv run pytest                 # unitarios, sin red
    uv run pytest -m integration  # contra servicios reales (ver tests/integration/test_live.py)
