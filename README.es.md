# Tohoku

[English](README.md) · **Español**

Catalogador de vídeos de viaje. Tohoku convierte los vídeos y posts que guardas en [Karakeep](https://karakeep.app) (YouTube Shorts, Instagram Reels y posts de Instagram) en notas estructuradas de [Trilium Notes](https://github.com/TriliumNext/Trilium): lugares en un mapa, cosas que comprar o comer, curiosidades… o recetas de cocina con ingredientes y pasos.

Cada lista de Karakeep se asigna a uno o varios **destinos** (un viaje, un recetario…) en `config/destinos.yaml`. Tohoku descarga el contenido, lo transcribe, se lo pasa a un LLM multimodal, geolocaliza los lugares, deduplica contra lo que ya tienes y publica en Trilium. Lo que no tiene claro va a una **Bandeja de revisión**.

Japón es el ejemplo de referencia en toda la documentación: el proyecto nació para planificar un viaje a Japón a partir de cientos de Reels guardados, y los valores por defecto (país, ciudades, categorías, prompt) describen Japón. Un destino de viaje nuevo (Nueva Zelanda, Portugal…) es solo configuración.

<!-- CAPTURA: Geo Map de un viaje con los lugares (docs/img/geo-map.png) -->

> **Nombre.** Antes se llamaba *japan-reader*. El prefijo `jr` de etiquetas (`jr:*` en Karakeep), atributos (`#jr*` en Trilium) y del adjunto `japan-reader.json` se mantiene a propósito: son las siglas de *Japan Reader* y de **JR**, la compañía de la Tohoku Shinkansen.

> **Idioma de las notas generadas.** Las notas que Tohoku escribe en Trilium (nombres de secciones, encabezados como «Mis notas», motivos de revisión) están hoy en español.

## Qué obtienes

**Flujo `viaje`** (un destino por país; Japón es el ejemplo de referencia):
- **Geo Map** con una nota por lugar (dirección, coordenadas y ficha de Google Places, categoría, fuentes, "Mis notas").
- **Comprar y comer**: productos, platos y cadenas, agrupados por categoría.
- **Cultura y curiosidades**: lo que no es ni un lugar ni una compra.

<!-- CAPTURA: nota de un lugar con sus fuentes (docs/img/lugar.png) -->
<!-- CAPTURA: sección "Comprar y comer" (docs/img/comprar.png) -->

**Flujo `receta`**:
- **Recetario** en vista Tabla con columnas para tipo de plato, cocina, tiempo, raciones, dificultad, y `probada`/`valoracion` para ti.
- Cada receta lleva portada (un fotograma o imagen del post), resumen, ingredientes agrupados, pasos numerados, consejos y fuentes.

<!-- CAPTURA: Recetario en vista Tabla (docs/img/recetario-tabla.png) -->
<!-- CAPTURA: Recetario en vista Cuadrícula con portadas (docs/img/recetario-cuadricula.png) -->
<!-- CAPTURA: nota de una receta (docs/img/receta.png) -->

**En todos los destinos:**
- **Bandeja de revisión**: baja confianza, geolocalización dudosa, posibles duplicados o clasificación incierta.
- **Tus cambios se respetan**: al reprocesar un enlace se regenera el contenido generado, pero no se tocan "Mis notas", los atributos que hayas corregido ni el título si lo cambiaste.
- **Clasificador**: si una lista alimenta varios destinos, un LLM decide a cuál va cada enlace (o lo descarta).
- **Avisos** opcionales por [ntfy](https://ntfy.sh).

<!-- CAPTURA: Bandeja de revisión (docs/img/bandeja.png) -->

## Cómo funciona

```
Karakeep (listas)
  → ingest      enlaces nuevos de las listas configuradas
  → fetch       yt-dlp / gallery-dl + ffmpeg (audio, fotogramas clave, imágenes)
  → transcribe  faster-whisper (CPU)
  → classify    solo si el enlace tiene varios destinos posibles
  → flujo del destino
      viaje:  extract (LLM) → geocode (Google Places) → resolve (deduplicación) → publish
      receta: extract (LLM) → cover (portada) → resolve → publish
  → mark        etiqueta jr:* en Karakeep y archiva el marcador
```

Cada etapa guarda su resultado en SQLite: un fallo transitorio se reintenta desde donde se quedó y `reprocess --from <etapa>` repite solo lo necesario. Detalle de cada etapa en [`docs/pipeline/`](docs/pipeline/).

## Requisitos

- **Docker** y Docker Compose (o Python 3.12 con [uv](https://docs.astral.sh/uv/) para desarrollo).
- **Karakeep** con una clave de API.
- **Trilium Notes** ≥ 0.106 con un token de ETAPI.
- **OpenRouter**: clave de API y un modelo multimodal (acepta imágenes).
- **Google Places API (New)**: solo para destinos de tipo `viaje` (Text Search Pro).
- **ntfy** (opcional) para avisos.
- **CPU y memoria**: Whisper `large-v3` en CPU tarda ~90 s por Reel; el contenedor está limitado a 6 CPU / 6 GB. Los modelos pequeños de Whisper fallan con nombres propios.

### Costes orientativos

Medidos con ~1.400 enlaces reales:
- **LLM**: ~0,001 $ por enlace.
- **Google Places**: ~1,2 llamadas por lugar y ~3 lugares por enlace en contenido de viajes. Con el cupo gratuito de Text Search Pro (5.000 al mes) y la caché de búsquedas de 30 días, unos 150 enlaces al día caben de sobra. Limita el gasto con `PLACES_DAILY_LIMIT` y con la cuota diaria en Google Cloud Console.
- **Tiempo**: ~1-2 min por Reel (sobre todo la transcripción).

## Puesta en marcha

1. Copia la configuración de ejemplo y rellénala:
   ```
   cp .env.example .env
   cp config/destinos.example.yaml config/destinos.yaml   # TODO: ejemplo aún sin crear (ver docs/publicacion.md)
   ```
2. **Red de Docker**: `docker-compose.yml` usa una red externa para llegar a Karakeep y Trilium por nombre de contenedor. Ajusta el nombre de la red y `KARAKEEP_URL` / `TRILIUM_URL` en `.env` a tu instalación. <!-- TODO: hacer la red configurable -->
3. En `config/destinos.yaml`, asigna cada lista de Karakeep a sus destinos y define cada destino (flujo, etiqueta de la nota raíz en Trilium, prompt). Ver [Destinos](#destinos).
4. En Trilium, añade la etiqueta de la raíz (p. ej. `#jrRoot`) a la nota bajo la que quieres la estructura del destino.
5. Crea la estructura y arranca:
   ```
   docker compose build
   docker compose run --rm tohoku tohoku init-trilium --destino <nombre>
   docker compose up -d
   docker compose logs -f tohoku
   ```

El servicio consulta Karakeep cada `POLL_INTERVAL_MINUTES` (10 por defecto).

## Destinos

```yaml
listas:
  <id-lista-karakeep>: [japon]            # una lista → un destino
  <id-lista-bandeja>: [japon, recetas]    # varios → decide el clasificador
destino_legado: japon                     # obligatorio con varios destinos
destinos:
  japon:
    flujo: viaje
    raiz: jrRoot                          # etiqueta de la nota raíz en Trilium
    descripcion: "Viaje a Japón: lugares, comida, compras y cultura"
    prompt: prompts/japon.md
    pais: JP
  recetas:
    flujo: receta
    raiz: jrRootRecetas
    descripcion: "Recetas de cocina: platos y bebidas con ingredientes y pasos"
    prompt: prompts/recetas.md
```

- Un destino de viaje nuevo (p. ej. Nueva Zelanda) se añade **solo con configuración**: un bloque en el YAML y un prompt. Hay un ejemplo comentado en `config/destinos.example.yaml`.
- Orden para activar un destino: editar el YAML → `init-trilium --destino <nombre>` → reiniciar el servicio.
- Las raíces de dos destinos **de distinto tipo** pueden ir una dentro de otra; dos del mismo tipo, no.

Guía completa: [`docs/operations.md`](docs/operations.md) ("Destinos", "Cómo añadir un destino").

## Comandos

Dentro del contenedor: `docker compose exec tohoku tohoku <comando>`.

| Comando | Para qué |
|---|---|
| `run` | Servicio en bucle (lo que arranca el contenedor). |
| `run-once` | Un solo ciclo (con el servicio parado: comparten candado). |
| `init-trilium [--destino X]` | Crea la estructura del destino en Trilium (idempotente). |
| `status` | Trabajos por estado, consumo del día, reintentos y últimos errores. |
| `reprocess <id>... \| --all-errors [--from <etapa>] [--destino X]` | Vuelve a procesar enlaces desde una etapa. |
| `import-instagram <export.json> [--collection] [--lista ID] [--limit N] [--dry-run]` | Importa a Karakeep tus guardados de una exportación de Instagram, por tandas. |
| `eval [--model] [--keyframes/--no-keyframes] [--destino X]` | Compara modelos o ajustes con casos reales (solo destinos `viaje`). |

## Documentación

- Etapas del pipeline: [`docs/pipeline/`](docs/pipeline/) (`01-ingest.md` … `08-mark.md`, `02b-classify.md`).
- Flujo de recetas: [`docs/flujos/receta.md`](docs/flujos/receta.md).
- Estructura en Trilium (notas, etiquetas, plantillas): [`docs/trilium-model.md`](docs/trilium-model.md).
- Operación diaria, destinos, reprocesados, limpieza y errores frecuentes: [`docs/operations.md`](docs/operations.md).

Cada documento tiene su versión en inglés (la principal) y su versión en español, con el sufijo `.es.md`. Las rutas de arriba apuntan a la versión inglesa; la española está al lado.

## Desarrollo

```
uv sync
uv run pytest                  # unitarios, sin red
uv run pytest -m integration   # contra servicios reales (ver tests/integration/test_live.py)
```

## Aviso

Tohoku descarga contenido de Instagram y YouTube con yt-dlp y gallery-dl para uso personal: organizar lo que tú mismo has guardado. Descargar contenido puede ir contra las condiciones de uso de esas plataformas; úsalo bajo tu responsabilidad y respeta los derechos de los autores. Las notas guardan siempre el enlace y el autor de la fuente.

## Licencia

[MIT](LICENSE).
