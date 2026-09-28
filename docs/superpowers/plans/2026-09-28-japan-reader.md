# japan-reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Servicio Python que sondea una lista de Karakeep, procesa cada enlace (YouTube Shorts, Instagram Reels y posts) con yt-dlp/gallery-dl, faster-whisper, un LLM multimodal vía OpenRouter y Google Places, y publica lugares y cosas deduplicados en Trilium (Geo Map + "Comprar y comer"), archivando el bookmark al terminar.

**Architecture:** Un único proceso (`japan-reader run`) con un pipeline por etapas (`fetch → transcribe → extract → geocode → resolve → publish → mark`). Cada etapa es un módulo con entrada/salida Pydantic; el resultado de cada etapa se persiste en SQLite para reanudar y reprocesar. Los servicios externos están detrás de clientes pequeños sustituibles por *fakes* en tests.

**Tech Stack:** Python 3.12, uv, httpx, Pydantic v2 + pydantic-settings, Typer, yt-dlp, gallery-dl, faster-whisper, Pillow, ffmpeg, SQLite, pytest + respx. Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-28-japan-reader-design.md`

## Global Constraints

- Python `>=3.12` (fijado a 3.12 con `uv python pin 3.12`; faster-whisper/ctranslate2 no garantizan ruedas para 3.14). Dependencias con uv; tests con `uv run pytest`.
- Tests unitarios **sin red**: HTTP con `respx`, servicios con *fakes* de `tests/fakes.py`. Tests contra servicios reales solo con marca `integration` (excluida por defecto).
- Idioma: textos visibles para el usuario, prompts y contenido de notas en **español**; identificadores de código en inglés; los campos del JSON del LLM son los del spec §5.4 (en español).
- Etiquetas de Karakeep exactas: `jr:procesado`, `jr:revisar`, `jr:no-japon`, `jr:error`. Solo `jr:error` **no** archiva.
- Motivos de revisión exactos: `geocodificacion-fallida`, `geocodificacion-ambigua`, `posible-duplicado`, `baja-confianza`, `clasificacion-incierta`, `extraccion-fallida`.
- Etiquetas de estructura en Trilium: `#jrRoot` (configurable con `TRILIUM_ROOT_LABEL`), `#jrMapa`, `#jrComprar`, `#jrCultura`, `#jrRevision`, `#jrPlantillas`, `#jrCategoria=<souvenirs|comida|cadenas|cosmetica|otros>`.
- Geo Map en Trilium v0.106 = nota tipo `book` con relación `~template=_template_geo_map` (verificado en el contenedor `trilium`: migración `0233__migrate_geo_map_to_collection`). Los hijos con `#geolocation="lat,lng"` aparecen en el mapa.
- Google Places: `POST https://places.googleapis.com/v1/places:searchText`, `X-Goog-FieldMask: places.id,places.displayName,places.formattedAddress,places.location,places.googleMapsUri,places.types`, `regionCode=JP`, `languageCode=es`.
- Valores por defecto: `POLL_INTERVAL_MINUTES=10`, `WHISPER_MODEL=large-v3`, `WHISPER_COMPUTE_TYPE=int8`, `REEL_KEYFRAMES_ENABLED=true`, `KEYFRAMES_MAX=6`, `POST_IMAGES_MAX=10`, `IMAGE_MAX_SIDE=1024`, `MAX_VIDEO_DURATION_MIN=15`, umbrales `0.4 / 0.7 / 0.7`, similitud de duplicado de cosa `0.85`, `PLACES_DAILY_LIMIT=150`.
- Un solo job a la vez. Contenedor limitado a 6 CPU / 6 GB. Red Docker externa `pangolin` (Karakeep en `http://karakeep-web:3000`, Trilium en `http://trilium:8080`).
- Secretos solo en `.env` (no versionado). Alertas por ntfy; nunca Home Assistant.
- Cada etapa tiene su documento en `docs/pipeline/0N-<etapa>.md` con las secciones: Qué hace · Entrada · Salida · Dependencias · Configuración · Fallos · Cómo probarla.

### Precisiones respecto al spec (decididas al planificar)

- **Subtítulos:** solo se descargan subtítulos **manuales**; los automáticos se ignoran porque Whisper large-v3 da mejor resultado.
- **Geocodificación ambigua:** el lugar se publica con las coordenadas del mejor resultado **y** va a revisión. "Fallida" (sin coordenadas) solo cuando ningún resultado está en Japón. Si hay resultados en Japón pero ninguno en la ciudad esperada, se trata como ambigua.
- **Reintentos:** hasta 5 reintentos (esperas 1 min, 5 min, 30 min, 2 h, 2 h); el sexto fallo transitorio marca `jr:error`.
- **Esquema de extracción:** `Lugar` incluye además `que_hacer` (alimenta la sección "Qué hacer / comer" de la nota).
- **Contenido japonés sin elementos:** si el LLM no devuelve lugares, cosas ni otros, se crea una nota "Otro" con `resumen_fuente`.
- **Datos estructurados de cada nota:** se guardan en un adjunto `japan-reader.json` de la propia nota, para que Trilium sea la fuente de verdad en las fusiones.
- **Nota sin encabezado "Mis notas"** (el usuario lo borró): en la fusión se conserva el contenido anterior entero bajo "Mis notas", para no perder datos.
- **Eval:** la opción es `--keyframes/--no-keyframes` (convención de Typer) en lugar de `--keyframes on|off`.

## Review Focus

1. **El usuario edita la nota en Trilium** (escribe en "Mis notas"; el editor reescribe el encabezado como `<h2><strong>Mis notas</strong></h2>`) → la siguiente fusión conserva su texto. Test en la Tarea 13.
2. **El mismo lugar aparece dos veces en una fuente** con nombres distintos (p. ej. "Fushimi Inari" y "伏見稲荷大社", mismo `place_id`) → una sola nota, sin duplicado. Test en la Tarea 14.
3. **Reprocesar un bookmark ya publicado** → no se duplica la fuente, `#fuentes` no aumenta y no se llama al LLM de fusión. Test en la Tarea 15.
4. **Fichero de cookies de Instagram montado en solo lectura** → yt-dlp/gallery-dl trabajan con una copia y nunca escriben el original. Test en la Tarea 7.
5. **`state.db` perdido o recreado** → los bookmarks que ya tienen una etiqueta `jr:*` no se vuelven a procesar. Test en la Tarea 5.

## File Structure

```
japan-reader/
  pyproject.toml, uv.lock, .python-version, .gitignore, .env.example
  Dockerfile, docker-compose.yml, README.md
  src/japan_reader/
    __init__.py
    config.py            # Settings (.env) + Thresholds
    errors.py            # TransientError, PermanentError, ApiError, ConfigError, QuotaExceeded
    log.py               # setup_logging
    sources.py           # Platform, ContentHint, classify_url, canonical_url
    models.py            # modelos Pydantic compartidos (resultados de etapa, extracción, geo)
    text.py              # normalize_name, similarity, strip_fences
    rules.py             # japan_decision, decide_outcome
    state.py             # StateStore (SQLite), Job, JobStatus, utcnow
    quota.py             # DailyQuota
    context.py           # JobContext
    notes.py             # datos de nota (LugarData/CosaData/OtroData), render HTML, etiquetas
    trilium_layout.py    # Layout, init_layout, resolve_layout, LayoutCache
    pipeline.py          # Pipeline, STAGE_ORDER, BACKOFF
    service.py           # Service (bucle), reprocess, format_status
    ingest.py            # ingest()
    instagram_export.py  # parse_export, import_items
    evaluation.py        # batería de evaluación
    wiring.py            # build_app, preflight
    cli.py               # Typer: run, run-once, init-trilium, status, reprocess, import-instagram, eval
    clients/
      __init__.py
      http.py            # send(), check_status()
      karakeep.py        # KarakeepClient, Bookmark
      trilium.py         # TriliumClient, TNote, TAttr, TAttachment
      openrouter.py      # OpenRouterClient, ChatResult, image_part
      places.py          # PlacesClient
      ntfy.py            # Notifier
    media/
      __init__.py
      audio.py           # extract_audio, has_audio, probe_duration
      keyframes.py       # extract_keyframes, dedupe_similar, pick_evenly
      images.py          # resize_image
      subtitles.py       # vtt_to_text
      downloaders.py     # DownloadedMedia, YtDlpDownloader, GalleryDlDownloader
    stages/
      __init__.py
      fetch.py, transcribe.py, extract.py, geocode.py, resolve.py, publish.py, mark.py
    prompts/
      __init__.py        # load_prompt
      extract.md, merge.md
  tests/
    conftest.py, helpers.py, fakes.py, builders.py
    unit/test_*.py
    integration/test_live.py
  eval/cases.yaml
  docs/pipeline/01-ingest.md … 08-mark.md, docs/trilium-model.md, docs/operations.md
```

---

### Task 1: Esqueleto del proyecto, configuración y errores

**Files:**
- Create: `pyproject.toml`, `.python-version` (lo genera uv), `src/japan_reader/__init__.py`, `src/japan_reader/config.py`, `src/japan_reader/errors.py`, `src/japan_reader/log.py`, `tests/conftest.py`
- Modify: `.gitignore`
- Test: `tests/unit/test_config.py`

**Interfaces:**
- Produces: `Settings` (campos en el paso 3; propiedades `text_model: str`, `thresholds: Thresholds`), `Thresholds(japan_min, japan_review, item_review, cosa_duplicate)`, excepciones `JapanReaderError`, `TransientError`, `PermanentError`, `ApiError(service, status, body)` (`.status: int`), `ConfigError`, `QuotaExceeded`; `setup_logging(level="INFO")`; fixture pytest `settings`.

- [ ] **Step 1: Identidad git local y dependencias base**

La máquina no tiene identidad git global. Configúrala solo en este repositorio:

```bash
cd /media/1tb-disk/japan-reader
git config user.name "Fernando"
git config user.email "fjbelaza@gmail.com"
uv python pin 3.12
```

Crea `pyproject.toml`:

```toml
[project]
name = "japan-reader"
version = "0.1.0"
description = "De Karakeep a Trilium: lugares y cosas de Japón extraídos de Shorts, Reels y posts"
requires-python = ">=3.12"
dependencies = [
  "httpx>=0.27",
  "pydantic>=2.8",
  "pydantic-settings>=2.4",
  "typer>=0.12",
  "pyyaml>=6.0",
  "pillow>=10.4",
  "yt-dlp>=2025.1.1",
  "gallery-dl>=1.28",
  "faster-whisper>=1.1",
]

[project.scripts]
japan-reader = "japan_reader.cli:app"

[dependency-groups]
dev = ["pytest>=8.3", "respx>=0.21"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/japan_reader"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["tests"]
markers = ["integration: pruebas contra servicios reales (opt-in)"]
addopts = "-m 'not integration'"
```

Añade a `.gitignore`:

```
eval/.cache/
secrets/
.pytest_cache/
```

Crea `src/japan_reader/__init__.py`:

```python
__version__ = "0.1.0"
```

Run: `uv sync`
Expected: crea `.venv` y `uv.lock` sin errores.

- [ ] **Step 2: Write the failing test**

`tests/unit/test_config.py`:

```python
import pytest
from pydantic import ValidationError

from japan_reader.config import Settings, Thresholds

REQUIRED = {
    "KARAKEEP_URL": "http://kk",
    "KARAKEEP_API_KEY": "k",
    "KARAKEEP_LIST_ID": "L",
    "TRILIUM_URL": "http://tr",
    "TRILIUM_ETAPI_TOKEN": "t",
    "OPENROUTER_API_KEY": "o",
    "OPENROUTER_MODEL": "vision/model",
    "GOOGLE_PLACES_API_KEY": "g",
}


def _set_required(monkeypatch):
    for key, value in REQUIRED.items():
        monkeypatch.setenv(key, value)


def test_settings_read_from_environment_with_defaults(monkeypatch):
    _set_required(monkeypatch)
    monkeypatch.setenv("REEL_KEYFRAMES_ENABLED", "false")

    s = Settings(_env_file=None)

    assert s.reel_keyframes_enabled is False
    assert s.whisper_model == "large-v3"
    assert s.whisper_compute_type == "int8"
    assert (s.keyframes_max, s.post_images_max, s.image_max_side) == (6, 10, 1024)
    assert s.max_video_duration_min == 15
    assert s.poll_interval_minutes == 10
    assert s.places_daily_limit == 150
    assert s.trilium_root_label == "jrRoot"
    assert s.text_model == "vision/model"
    assert s.thresholds == Thresholds(
        japan_min=0.4, japan_review=0.7, item_review=0.7, cosa_duplicate=0.85
    )


def test_text_model_can_be_overridden(monkeypatch):
    _set_required(monkeypatch)
    monkeypatch.setenv("OPENROUTER_TEXT_MODEL", "cheap/text")

    assert Settings(_env_file=None).text_model == "cheap/text"


def test_missing_required_setting_fails(monkeypatch):
    for key in REQUIRED:
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_config.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'japan_reader.config'`

- [ ] **Step 4: Write minimal implementation**

`src/japan_reader/config.py`:

```python
from dataclasses import dataclass
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True)
class Thresholds:
    """Umbrales de la red de seguridad (spec §7)."""

    japan_min: float = 0.4
    japan_review: float = 0.7
    item_review: float = 0.7
    cosa_duplicate: float = 0.85


class Settings(BaseSettings):
    """Configuración del servicio, leída de variables de entorno o de `.env`."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    karakeep_url: str
    karakeep_api_key: str
    karakeep_list_id: str

    trilium_url: str
    trilium_etapi_token: str
    trilium_root_label: str = "jrRoot"

    openrouter_api_key: str
    openrouter_model: str
    openrouter_text_model: str | None = None
    openrouter_daily_budget_usd: float = 1.0

    google_places_api_key: str
    places_daily_limit: int = 150

    whisper_model: str = "large-v3"
    whisper_compute_type: str = "int8"
    whisper_threads: int = 6
    whisper_download_root: Path = Path("models")

    reel_keyframes_enabled: bool = True
    keyframes_max: int = 6
    post_images_max: int = 10
    image_max_side: int = 1024
    max_video_duration_min: int = 15

    instagram_cookies_file: Path | None = None

    ntfy_url: str | None = None
    ntfy_topic: str | None = None
    ntfy_token: str | None = None
    ntfy_daily_summary: bool = False

    poll_interval_minutes: int = 10
    data_dir: Path = Path("data")

    japan_min_confidence: float = 0.4
    japan_review_confidence: float = 0.7
    item_review_confidence: float = 0.7
    cosa_duplicate_similarity: float = 0.85

    @property
    def text_model(self) -> str:
        """Modelo para llamadas sin imágenes (contenido sin imágenes y fusiones)."""
        return self.openrouter_text_model or self.openrouter_model

    @property
    def thresholds(self) -> Thresholds:
        return Thresholds(
            japan_min=self.japan_min_confidence,
            japan_review=self.japan_review_confidence,
            item_review=self.item_review_confidence,
            cosa_duplicate=self.cosa_duplicate_similarity,
        )
```

`src/japan_reader/errors.py`:

```python
class JapanReaderError(Exception):
    """Base de los errores del servicio."""


class TransientError(JapanReaderError):
    """Fallo pasajero (timeout, 5xx, 429): se reintenta la etapa con espera creciente."""


class PermanentError(JapanReaderError):
    """La fuente no se puede procesar (borrada, privada, demasiado larga): jr:error."""


class ApiError(PermanentError):
    """Respuesta 4xx inesperada de un servicio externo."""

    def __init__(self, service: str, status: int, body: str) -> None:
        super().__init__(f"{service}: HTTP {status}: {body[:300]}")
        self.service = service
        self.status = status


class ConfigError(JapanReaderError):
    """Configuración inválida: se detiene el procesamiento y se avisa. No consume reintentos."""


class QuotaExceeded(JapanReaderError):
    """Límite diario alcanzado: el job espera al día siguiente sin consumir reintentos."""
```

`src/japan_reader/log.py`:

```python
import logging
import sys


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
        force=True,
    )
    for noisy in ("httpx", "httpcore", "faster_whisper"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
```

`tests/conftest.py`:

```python
import pytest

from japan_reader.config import Settings


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        karakeep_url="http://karakeep.test",
        karakeep_api_key="kk",
        karakeep_list_id="L1",
        trilium_url="http://trilium.test",
        trilium_etapi_token="tt",
        openrouter_api_key="or",
        openrouter_model="vision/model",
        openrouter_text_model="text/model",
        google_places_api_key="gp",
        data_dir=tmp_path / "data",
        whisper_download_root=tmp_path / "models",
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_config.py -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock .python-version .gitignore src tests
git commit -m "chore: project skeleton, settings and error types"
```

---

### Task 2: Modelos compartidos, clasificación de URLs y reglas

**Files:**
- Create: `src/japan_reader/sources.py`, `src/japan_reader/models.py`, `src/japan_reader/text.py`, `src/japan_reader/rules.py`
- Test: `tests/unit/test_sources.py`, `tests/unit/test_text_rules.py`

**Interfaces:**
- Consumes: `Thresholds` (Tarea 1).
- Produces:
  - `sources.Platform` (`YOUTUBE="youtube"`, `INSTAGRAM="instagram"`), `sources.ContentHint` (`VIDEO="video"`, `POST="post"`), `classify_url(url: str) -> tuple[Platform, ContentHint] | None`, `canonical_url(url: str) -> str`.
  - `models`: `ContentType`, `SourceMeta`, `FetchResult`, `Transcript`, `Lugar`, `Cosa`, `Otro`, `Extraction`, `ExtractResult`, `GeoMatch`, `GeoOutcome`, `GeocodeResult`, `ItemKind`, `PlannedItem`, `ResolveResult`, `Outcome`, `PublishedNote`, `PublishResult`, `MarkResult`, `MergeOutput`, `LUGAR_CATEGORIAS`, `COSA_CATEGORIAS` (campos en el paso 3).
  - `text.fold(text: str) -> str` (minúsculas y sin acentos), `text.normalize_name(text: str) -> str`, `text.similarity(a: str, b: str) -> float`, `text.strip_fences(text: str) -> str`.
  - `rules.japan_decision(extraction: Extraction, th: Thresholds) -> Literal["no", "uncertain", "yes"]`, `rules.decide_outcome(decision, notes: list[PublishedNote]) -> Outcome`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_sources.py`:

```python
import pytest

from japan_reader.sources import ContentHint, Platform, canonical_url, classify_url


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.youtube.com/shorts/abc123", (Platform.YOUTUBE, ContentHint.VIDEO)),
        ("https://youtube.com/watch?v=abc123", (Platform.YOUTUBE, ContentHint.VIDEO)),
        ("https://youtu.be/abc123", (Platform.YOUTUBE, ContentHint.VIDEO)),
        ("https://m.youtube.com/shorts/abc123?feature=share", (Platform.YOUTUBE, ContentHint.VIDEO)),
        ("https://www.instagram.com/reel/C1x2y3/", (Platform.INSTAGRAM, ContentHint.VIDEO)),
        ("https://www.instagram.com/reels/C1x2y3/", (Platform.INSTAGRAM, ContentHint.VIDEO)),
        ("https://www.instagram.com/some.user/reel/C1x2y3/", (Platform.INSTAGRAM, ContentHint.VIDEO)),
        ("https://instagram.com/p/C9z8/?igsh=xyz", (Platform.INSTAGRAM, ContentHint.POST)),
        ("https://www.instagram.com/some_user/p/C9z8/", (Platform.INSTAGRAM, ContentHint.POST)),
        ("https://www.tiktok.com/@u/video/1", None),
        ("https://www.instagram.com/some_user/", None),
    ],
)
def test_classify_url(url, expected):
    assert classify_url(url) == expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://youtu.be/abc123", "https://www.youtube.com/watch?v=abc123"),
        ("https://m.youtube.com/shorts/abc123?feature=share", "https://www.youtube.com/shorts/abc123"),
        ("https://www.youtube.com/watch?v=abc123&t=10", "https://www.youtube.com/watch?v=abc123"),
        ("https://instagram.com/p/C9z8/?igsh=xyz", "https://www.instagram.com/p/C9z8/"),
        ("https://www.instagram.com/u/reels/C1x2y3", "https://www.instagram.com/reel/C1x2y3/"),
    ],
)
def test_canonical_url(url, expected):
    assert canonical_url(url) == expected
```

`tests/unit/test_text_rules.py`:

```python
import pytest

from japan_reader.config import Thresholds
from japan_reader.models import Extraction, Outcome, PublishedNote
from japan_reader.rules import decide_outcome, japan_decision
from japan_reader.text import fold, normalize_name, similarity, strip_fences


def test_fold_keeps_words():
    assert fold("Japón, ÑANDÚ") == "japon, nandu"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Ichiran  Shibuya!", "ichiran shibuya"),
        ("Tienda Don Quijote", "don quijote"),
        ("Kiyomizu-dera", "kiyomizu dera"),
        ("Café Ñandú", "cafe nandu"),
        ("CoCo Ichibanya (Japan)", "coco ichibanya"),
    ],
)
def test_normalize_name(raw, expected):
    assert normalize_name(raw) == expected


def test_similarity_bounds():
    assert similarity("coco ichibanya", "coco ichibanya") == 1.0
    assert similarity("coco ichibanya", "coco ichiban ya") > 0.85
    assert similarity("yoshinoya", "matsuya") < 0.7


def test_strip_fences():
    assert strip_fences('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert strip_fences('  {"a": 1} ') == '{"a": 1}'


def _extraction(conf: float) -> Extraction:
    return Extraction(relacionado_japon=conf >= 0.5, confianza_japon=conf, idioma="es", resumen_fuente="x")


@pytest.mark.parametrize(("conf", "expected"), [(0.1, "no"), (0.39, "no"), (0.4, "uncertain"), (0.69, "uncertain"), (0.7, "yes"), (1.0, "yes")])
def test_japan_decision(conf, expected):
    assert japan_decision(_extraction(conf), Thresholds()) == expected


def test_decide_outcome():
    ok = PublishedNote(key="lugar:0", note_id="n1", action="create", review_reasons=[])
    review = PublishedNote(key="cosa:0", note_id="n2", action="create", review_reasons=["baja-confianza"])
    assert decide_outcome("no", []) == Outcome.NO_JAPON
    assert decide_outcome("yes", [ok]) == Outcome.PROCESADO
    assert decide_outcome("yes", [ok, review]) == Outcome.REVISAR
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_sources.py tests/unit/test_text_rules.py -v`
Expected: FAIL con `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

`src/japan_reader/sources.py`:

```python
import re
from enum import StrEnum
from urllib.parse import parse_qs, urlsplit, urlunsplit


class Platform(StrEnum):
    YOUTUBE = "youtube"
    INSTAGRAM = "instagram"


class ContentHint(StrEnum):
    """Pista por URL; `fetch` confirma el tipo real con los metadatos."""

    VIDEO = "video"
    POST = "post"


_YOUTUBE = re.compile(r"^https?://(?:www\.|m\.)?(?:youtube\.com/(?:shorts/|watch\?)|youtu\.be/)", re.I)
_IG_VIDEO = re.compile(r"^https?://(?:www\.)?instagram\.com/(?:[\w.]+/)?(?:reels?|tv)/[\w-]+", re.I)
_IG_POST = re.compile(r"^https?://(?:www\.)?instagram\.com/(?:[\w.]+/)?p/[\w-]+", re.I)


def classify_url(url: str) -> tuple[Platform, ContentHint] | None:
    if _YOUTUBE.match(url):
        return Platform.YOUTUBE, ContentHint.VIDEO
    if _IG_VIDEO.match(url):
        return Platform.INSTAGRAM, ContentHint.VIDEO
    if _IG_POST.match(url):
        return Platform.INSTAGRAM, ContentHint.POST
    return None


def canonical_url(url: str) -> str:
    """Forma canónica para deduplicar enlaces (sin parámetros de seguimiento)."""
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.").removeprefix("m.")
    if host == "youtu.be":
        return f"https://www.youtube.com/watch?v={parts.path.strip('/')}"
    if host == "youtube.com":
        if parts.path.startswith("/shorts/"):
            return f"https://www.youtube.com/shorts/{parts.path.split('/')[2]}"
        video = parse_qs(parts.query).get("v")
        if video:
            return f"https://www.youtube.com/watch?v={video[0]}"
    if host == "instagram.com":
        segments = [s for s in parts.path.split("/") if s]
        for i, segment in enumerate(segments):
            if segment in ("p", "reel", "reels", "tv") and i + 1 < len(segments):
                kind = "p" if segment == "p" else "reel"
                return f"https://www.instagram.com/{kind}/{segments[i + 1]}/"
    return urlunsplit((parts.scheme or "https", host, parts.path, parts.query, ""))
```

`src/japan_reader/models.py`:

```python
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from japan_reader.sources import Platform

LUGAR_CATEGORIAS = (
    "templo", "santuario", "comida", "cafe", "bar", "tienda", "mercado", "mirador",
    "barrio", "museo", "parque", "onsen", "alojamiento", "transporte", "otro",
)
COSA_CATEGORIAS = ("souvenirs", "comida", "cadenas", "cosmetica", "otros")

LugarCategoria = Literal[
    "templo", "santuario", "comida", "cafe", "bar", "tienda", "mercado", "mirador",
    "barrio", "museo", "parque", "onsen", "alojamiento", "transporte", "otro",
]
CosaCategoria = Literal["souvenirs", "comida", "cadenas", "cosmetica", "otros"]


class ContentType(StrEnum):
    VIDEO = "video"
    IMAGE = "image"
    CAROUSEL = "carousel"


class SourceMeta(BaseModel):
    url: str
    platform: Platform
    content_type: ContentType
    title: str | None = None
    description: str | None = None
    hashtags: list[str] = []
    author: str | None = None
    published: str | None = None
    duration_s: float | None = None


class FetchResult(BaseModel):
    """Salida de `fetch`. Las rutas son relativas al directorio del job."""

    meta: SourceMeta
    audio_files: list[str] = []
    subtitles: str | None = None
    images: list[str] = []
    keyframes: list[str] = []


class Transcript(BaseModel):
    text: str = ""
    language: str | None = None
    origin: Literal["subtitulos", "whisper", "none"] = "none"


class Lugar(BaseModel):
    nombre: str
    nombre_local: str | None = None
    consulta_busqueda: str
    ciudad: str | None = None
    region: str | None = None
    categoria: LugarCategoria
    que_es: str
    que_hacer: str = ""
    consejos: list[str] = []
    precio_aprox: str | None = None
    confianza: float = Field(ge=0, le=1)


class Cosa(BaseModel):
    nombre: str
    categoria: CosaCategoria
    que_es: str
    consejos: list[str] = []
    donde: list[str] = []
    donde_lugares: list[str] = []
    confianza: float = Field(ge=0, le=1)


class Otro(BaseModel):
    titulo: str
    contenido: str


class Extraction(BaseModel):
    relacionado_japon: bool
    confianza_japon: float = Field(ge=0, le=1)
    idioma: str
    resumen_fuente: str
    lugares: list[Lugar] = []
    cosas: list[Cosa] = []
    otros: list[Otro] = []


class ExtractResult(BaseModel):
    extraction: Extraction | None = None
    error: str | None = None
    cost_usd: float = 0.0


class GeoMatch(BaseModel):
    place_id: str
    name: str
    address: str
    lat: float
    lng: float
    maps_url: str
    types: list[str] = []


class GeoOutcome(BaseModel):
    lugar_index: int
    match: GeoMatch | None = None
    review_reason: str | None = None


class GeocodeResult(BaseModel):
    outcomes: list[GeoOutcome] = []


class ItemKind(StrEnum):
    LUGAR = "lugar"
    COSA = "cosa"
    OTRO = "otro"
    FALLO = "fallo"


class PlannedItem(BaseModel):
    """Decisión de `resolve` para un elemento. `index=-1` en OTRO = nota sintética del resumen."""

    key: str
    kind: ItemKind
    index: int
    action: Literal["create", "merge", "alias"]
    existing_note_id: str | None = None
    alias_of: str | None = None
    review_reasons: list[str] = []


class ResolveResult(BaseModel):
    items: list[PlannedItem] = []


class Outcome(StrEnum):
    PROCESADO = "procesado"
    REVISAR = "revisar"
    NO_JAPON = "no-japon"
    ERROR = "error"


class PublishedNote(BaseModel):
    key: str
    note_id: str
    action: Literal["create", "merge", "alias"]
    review_reasons: list[str] = []


class PublishResult(BaseModel):
    notes: list[PublishedNote] = []
    outcome: Outcome


class MarkResult(BaseModel):
    tag: str
    archived: bool


class MergeOutput(BaseModel):
    resumen: str
    que_hacer: str = ""
    consejos: list[str] = []
```

`src/japan_reader/text.py`:

```python
import re
import unicodedata
from difflib import SequenceMatcher

_GENERIC_WORDS = {"japan", "japon", "tienda", "store", "shop", "the"}
_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.S)


def fold(text: str) -> str:
    """Minúsculas y sin acentos, conservando todas las palabras y la puntuación."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_name(text: str) -> str:
    """Minúsculas, sin acentos ni puntuación y sin palabras genéricas (clave de deduplicación)."""
    cleaned = re.sub(r"[^\w\s]", " ", fold(text))
    return " ".join(word for word in cleaned.split() if word not in _GENERIC_WORDS)


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def strip_fences(text: str) -> str:
    """Quita un bloque ```json ... ``` si el modelo lo añade alrededor del JSON."""
    stripped = text.strip()
    match = _FENCE.match(stripped)
    return match.group(1) if match else stripped
```

`src/japan_reader/rules.py`:

```python
from typing import Literal

from japan_reader.config import Thresholds
from japan_reader.models import Extraction, Outcome, PublishedNote

JapanDecision = Literal["no", "uncertain", "yes"]


def japan_decision(extraction: Extraction, th: Thresholds) -> JapanDecision:
    """Clasifica con `confianza_japon` (spec §7)."""
    if extraction.confianza_japon < th.japan_min:
        return "no"
    if extraction.confianza_japon < th.japan_review:
        return "uncertain"
    return "yes"


def decide_outcome(decision: JapanDecision, notes: list[PublishedNote]) -> Outcome:
    if decision == "no":
        return Outcome.NO_JAPON
    if any(note.review_reasons for note in notes):
        return Outcome.REVISAR
    return Outcome.PROCESADO
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_sources.py tests/unit/test_text_rules.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add src/japan_reader tests/unit
git commit -m "feat: shared models, URL classification, text helpers and review rules"
```

---

### Task 3: Estado persistente (SQLite), cuotas diarias y contexto de job

**Files:**
- Create: `src/japan_reader/state.py`, `src/japan_reader/quota.py`, `src/japan_reader/context.py`
- Test: `tests/unit/test_state.py`

**Interfaces:**
- Consumes: `Platform`, `ContentHint`, `Outcome`, `PublishedNote` (Tarea 2); `QuotaExceeded` (Tarea 1).
- Produces:
  - `state.utcnow() -> datetime`, `JobStatus` (`PENDING`, `DONE`, `ERROR`), `Job` (campos: `bookmark_id, url, platform, hint, status, attempts, next_attempt_at, last_error, outcome, created_at, updated_at`).
  - `StateStore(path: Path, clock=utcnow)` con: `add_job(bookmark_id, url, platform, hint) -> bool`, `has_job(bookmark_id) -> bool`, `get_job(bookmark_id) -> Job | None`, `due_jobs() -> list[Job]`, `list_jobs(status=None, limit=20) -> list[Job]`, `save_stage(bookmark_id, stage, result)`, `load_stage(bookmark_id, stage, model) -> model | None`, `clear_stages_from(bookmark_id, from_stage, order)`, `schedule_retry(bookmark_id, when, error, count_attempt=True)`, `finish(bookmark_id, outcome, error=None)`, `reset(bookmark_id)`, `record_publish(bookmark_id, note: PublishedNote)`, `published(bookmark_id) -> dict[str, PublishedNote]`, `add_counter(key, amount) -> float`, `get_counter(key) -> float`, `today() -> str`, `status_counts() -> dict[str, int]`, `finished_today() -> dict[str, int]`.
  - `quota.DailyQuota(state, key, limit)` con `check()` (lanza `QuotaExceeded`) y `add(amount)`.
  - `context.JobContext(job, workdir, results={})` con `result(name, cls)`.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_state.py`:

```python
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import BaseModel

from japan_reader.errors import QuotaExceeded
from japan_reader.models import Outcome, PublishedNote
from japan_reader.quota import DailyQuota
from japan_reader.sources import ContentHint, Platform
from japan_reader.state import JobStatus, StateStore


class Clock:
    def __init__(self):
        self.now = datetime(2026, 9, 28, 10, 0, tzinfo=UTC)

    def __call__(self):
        return self.now


class Dummy(BaseModel):
    value: int


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def state(tmp_path, clock):
    return StateStore(tmp_path / "state.db", clock=clock)


def test_add_job_is_idempotent(state):
    assert state.add_job("b1", "https://youtu.be/x", Platform.YOUTUBE, ContentHint.VIDEO) is True
    assert state.add_job("b1", "https://youtu.be/x", Platform.YOUTUBE, ContentHint.VIDEO) is False
    job = state.get_job("b1")
    assert job.status == JobStatus.PENDING
    assert job.platform == Platform.YOUTUBE and job.hint == ContentHint.VIDEO
    assert state.has_job("b1") and not state.has_job("nope")


def test_unsupported_job_has_no_platform(state):
    state.add_job("b2", "https://tiktok.com/x", None, None)
    assert state.get_job("b2").platform is None


def test_due_jobs_respects_next_attempt(state, clock):
    state.add_job("b1", "u1", Platform.YOUTUBE, ContentHint.VIDEO)
    state.add_job("b2", "u2", Platform.YOUTUBE, ContentHint.VIDEO)
    state.schedule_retry("b2", clock.now + timedelta(minutes=5), "timeout")
    assert [j.bookmark_id for j in state.due_jobs()] == ["b1"]
    clock.now += timedelta(minutes=6)
    assert [j.bookmark_id for j in state.due_jobs()] == ["b1", "b2"]
    job = state.get_job("b2")
    assert job.attempts == 1 and job.last_error == "timeout"


def test_retry_without_counting_attempt(state, clock):
    state.add_job("b1", "u1", Platform.YOUTUBE, ContentHint.VIDEO)
    state.schedule_retry("b1", clock.now, "quota", count_attempt=False)
    assert state.get_job("b1").attempts == 0


def test_stage_results_roundtrip_and_clear(state):
    state.add_job("b1", "u1", Platform.YOUTUBE, ContentHint.VIDEO)
    for name in ("fetch", "transcribe", "extract"):
        state.save_stage("b1", name, Dummy(value=1))
    state.record_publish("b1", PublishedNote(key="lugar:0", note_id="n1", action="create"))
    assert state.load_stage("b1", "fetch", Dummy) == Dummy(value=1)

    state.clear_stages_from("b1", "transcribe", ["fetch", "transcribe", "extract", "publish"])

    assert state.load_stage("b1", "fetch", Dummy) is not None
    assert state.load_stage("b1", "transcribe", Dummy) is None
    assert state.load_stage("b1", "extract", Dummy) is None
    assert state.published("b1") == {}


def test_finish_and_reset(state):
    state.add_job("b1", "u1", Platform.YOUTUBE, ContentHint.VIDEO)
    state.finish("b1", Outcome.ERROR, "privado")
    job = state.get_job("b1")
    assert job.status == JobStatus.ERROR and job.outcome == Outcome.ERROR and job.last_error == "privado"
    state.finish("b1", Outcome.PROCESADO)
    assert state.get_job("b1").status == JobStatus.DONE
    state.reset("b1")
    job = state.get_job("b1")
    assert job.status == JobStatus.PENDING and job.attempts == 0 and job.outcome is None


def test_counters_are_daily(state, clock):
    assert state.add_counter("places_calls", 1) == 1
    assert state.add_counter("places_calls", 2) == 3
    clock.now += timedelta(days=1)
    assert state.get_counter("places_calls") == 0


def test_status_counts(state):
    state.add_job("b1", "u1", Platform.YOUTUBE, ContentHint.VIDEO)
    state.add_job("b2", "u2", Platform.YOUTUBE, ContentHint.VIDEO)
    state.finish("b2", Outcome.REVISAR)
    assert state.status_counts() == {"pendiente": 1, "revisar": 1}
    assert state.finished_today() == {"revisar": 1}


def test_daily_quota(state):
    quota = DailyQuota(state, "places_calls", limit=2)
    quota.check()
    quota.add(2)
    with pytest.raises(QuotaExceeded):
        quota.check()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_state.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'japan_reader.state'`

- [ ] **Step 3: Write minimal implementation**

`src/japan_reader/state.py`:

```python
import sqlite3
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel

from japan_reader.models import Outcome, PublishedNote
from japan_reader.sources import ContentHint, Platform


def utcnow() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds")


class JobStatus(StrEnum):
    PENDING = "pending"
    DONE = "done"
    ERROR = "error"


class Job(BaseModel):
    bookmark_id: str
    url: str
    platform: Platform | None
    hint: ContentHint | None
    status: JobStatus
    attempts: int
    next_attempt_at: datetime | None
    last_error: str | None
    outcome: Outcome | None
    created_at: datetime
    updated_at: datetime


_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    bookmark_id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    platform TEXT,
    hint TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    last_error TEXT,
    outcome TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stage_results (
    bookmark_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (bookmark_id, stage)
);
CREATE TABLE IF NOT EXISTS published (
    bookmark_id TEXT NOT NULL,
    item_key TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (bookmark_id, item_key)
);
CREATE TABLE IF NOT EXISTS counters (
    day TEXT NOT NULL,
    key TEXT NOT NULL,
    value REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (day, key)
);
"""


class StateStore:
    """Estado del servicio: jobs, resultados por etapa, publicaciones y contadores diarios."""

    def __init__(self, path: Path, clock: Callable[[], datetime] = utcnow) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_SCHEMA)
        self._clock = clock

    def _now(self) -> str:
        return _iso(self._clock())

    def today(self) -> str:
        return self._clock().astimezone(UTC).date().isoformat()

    # --- jobs -------------------------------------------------------------

    def add_job(self, bookmark_id: str, url: str, platform: Platform | None, hint: ContentHint | None) -> bool:
        now = self._now()
        cursor = self._db.execute(
            "INSERT OR IGNORE INTO jobs (bookmark_id, url, platform, hint, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (bookmark_id, url, platform.value if platform else None, hint.value if hint else None, now, now),
        )
        return cursor.rowcount == 1

    def has_job(self, bookmark_id: str) -> bool:
        return self._db.execute("SELECT 1 FROM jobs WHERE bookmark_id = ?", (bookmark_id,)).fetchone() is not None

    def get_job(self, bookmark_id: str) -> Job | None:
        row = self._db.execute("SELECT * FROM jobs WHERE bookmark_id = ?", (bookmark_id,)).fetchone()
        return Job.model_validate(dict(row)) if row else None

    def due_jobs(self) -> list[Job]:
        rows = self._db.execute(
            "SELECT * FROM jobs WHERE status = 'pending'"
            " AND (next_attempt_at IS NULL OR next_attempt_at <= ?)"
            " ORDER BY created_at, bookmark_id",
            (self._now(),),
        ).fetchall()
        return [Job.model_validate(dict(row)) for row in rows]

    def list_jobs(self, status: JobStatus | None = None, limit: int = 20) -> list[Job]:
        if status is None:
            rows = self._db.execute("SELECT * FROM jobs ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
        else:
            rows = self._db.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY updated_at DESC LIMIT ?", (status.value, limit)
            ).fetchall()
        return [Job.model_validate(dict(row)) for row in rows]

    def schedule_retry(self, bookmark_id: str, when: datetime, error: str, count_attempt: bool = True) -> None:
        self._db.execute(
            "UPDATE jobs SET attempts = attempts + ?, next_attempt_at = ?, last_error = ?, updated_at = ?"
            " WHERE bookmark_id = ?",
            (1 if count_attempt else 0, _iso(when), error, self._now(), bookmark_id),
        )

    def finish(self, bookmark_id: str, outcome: Outcome, error: str | None = None) -> None:
        status = JobStatus.ERROR if outcome == Outcome.ERROR else JobStatus.DONE
        self._db.execute(
            "UPDATE jobs SET status = ?, outcome = ?, last_error = ?, next_attempt_at = NULL, updated_at = ?"
            " WHERE bookmark_id = ?",
            (status.value, outcome.value, error, self._now(), bookmark_id),
        )

    def reset(self, bookmark_id: str) -> None:
        self._db.execute(
            "UPDATE jobs SET status = 'pending', attempts = 0, next_attempt_at = NULL, last_error = NULL,"
            " outcome = NULL, updated_at = ? WHERE bookmark_id = ?",
            (self._now(), bookmark_id),
        )

    # --- resultados por etapa ------------------------------------------------

    def save_stage(self, bookmark_id: str, stage: str, result: BaseModel) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO stage_results (bookmark_id, stage, data, created_at) VALUES (?, ?, ?, ?)",
            (bookmark_id, stage, result.model_dump_json(), self._now()),
        )

    def load_stage[T: BaseModel](self, bookmark_id: str, stage: str, model: type[T]) -> T | None:
        row = self._db.execute(
            "SELECT data FROM stage_results WHERE bookmark_id = ? AND stage = ?", (bookmark_id, stage)
        ).fetchone()
        return model.model_validate_json(row["data"]) if row else None

    def clear_stages_from(self, bookmark_id: str, from_stage: str, order: Sequence[str]) -> None:
        names = list(order[list(order).index(from_stage):])
        placeholders = ",".join("?" for _ in names)
        self._db.execute(
            f"DELETE FROM stage_results WHERE bookmark_id = ? AND stage IN ({placeholders})",
            (bookmark_id, *names),
        )
        if "publish" in names:
            self._db.execute("DELETE FROM published WHERE bookmark_id = ?", (bookmark_id,))

    # --- publicaciones (idempotencia de publish) ------------------------------

    def record_publish(self, bookmark_id: str, note: PublishedNote) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO published (bookmark_id, item_key, data) VALUES (?, ?, ?)",
            (bookmark_id, note.key, note.model_dump_json()),
        )

    def published(self, bookmark_id: str) -> dict[str, PublishedNote]:
        rows = self._db.execute("SELECT data FROM published WHERE bookmark_id = ?", (bookmark_id,)).fetchall()
        notes = [PublishedNote.model_validate_json(row["data"]) for row in rows]
        return {note.key: note for note in notes}

    # --- contadores diarios -------------------------------------------------

    def add_counter(self, key: str, amount: float) -> float:
        self._db.execute(
            "INSERT INTO counters (day, key, value) VALUES (?, ?, ?)"
            " ON CONFLICT(day, key) DO UPDATE SET value = value + excluded.value",
            (self.today(), key, amount),
        )
        return self.get_counter(key)

    def get_counter(self, key: str) -> float:
        row = self._db.execute("SELECT value FROM counters WHERE day = ? AND key = ?", (self.today(), key)).fetchone()
        return float(row["value"]) if row else 0.0

    # --- informes -----------------------------------------------------------

    def status_counts(self) -> dict[str, int]:
        rows = self._db.execute("SELECT status, outcome, COUNT(*) AS n FROM jobs GROUP BY status, outcome").fetchall()
        counts: dict[str, int] = {}
        for row in rows:
            key = "pendiente" if row["status"] == JobStatus.PENDING else row["outcome"]
            counts[key] = counts.get(key, 0) + row["n"]
        return counts

    def finished_today(self) -> dict[str, int]:
        rows = self._db.execute(
            "SELECT outcome, COUNT(*) AS n FROM jobs WHERE status != 'pending' AND substr(updated_at, 1, 10) = ?"
            " GROUP BY outcome",
            (self.today(),),
        ).fetchall()
        return {row["outcome"]: row["n"] for row in rows}
```

`src/japan_reader/quota.py`:

```python
from japan_reader.errors import QuotaExceeded
from japan_reader.state import StateStore


class DailyQuota:
    """Límite diario de gasto o llamadas guardado en `counters`."""

    def __init__(self, state: StateStore, key: str, limit: float) -> None:
        self._state = state
        self.key = key
        self.limit = limit

    def check(self) -> None:
        if self._state.get_counter(self.key) >= self.limit:
            raise QuotaExceeded(f"límite diario alcanzado: {self.key} ({self.limit})")

    def add(self, amount: float) -> None:
        self._state.add_counter(self.key, amount)
```

`src/japan_reader/context.py`:

```python
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel

from japan_reader.state import Job


@dataclass
class JobContext:
    """Lo que ve cada etapa: el job, su directorio de trabajo y los resultados previos."""

    job: Job
    workdir: Path
    results: dict[str, BaseModel] = field(default_factory=dict)

    def result[T: BaseModel](self, name: str, cls: type[T]) -> T:
        value = self.results[name]
        if not isinstance(value, cls):
            raise TypeError(f"resultado '{name}' es {type(value).__name__}, se esperaba {cls.__name__}")
        return value
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_state.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add src/japan_reader tests/unit/test_state.py
git commit -m "feat: SQLite state store, daily quotas and job context"
```

---

### Task 4: Cliente HTTP base y cliente de Karakeep

**Files:**
- Create: `src/japan_reader/clients/__init__.py` (vacío), `src/japan_reader/clients/http.py`, `src/japan_reader/clients/karakeep.py`
- Test: `tests/unit/test_karakeep_client.py`

**Interfaces:**
- Consumes: errores (Tarea 1).
- Produces:
  - `clients.http.check_status(resp, service)`, `clients.http.send(client, method, url, service, **kwargs) -> httpx.Response`. Mapeo: transporte → `TransientError`; 401/402/403 → `ConfigError`; 429/5xx → `TransientError`; otro 4xx → `ApiError`.
  - `Bookmark(id, url, title, description, author, archived, tags: list[str], video_asset_id, image_asset_id)` con `Bookmark.from_api(dict)`.
  - `KarakeepClient(base_url, api_key, http=None)`: `list_bookmarks(list_id) -> Iterator[Bookmark]`, `get_bookmark(bookmark_id) -> Bookmark`, `attach_tags(bookmark_id, names)`, `detach_tags(bookmark_id, names)`, `set_archived(bookmark_id, archived)`, `download_asset(asset_id, dest: Path) -> Path`, `find_by_url(url) -> str | None`, `create_link(url) -> str`, `add_to_list(list_id, bookmark_id)`.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_karakeep_client.py`:

```python
import json

import httpx
import pytest
import respx

from japan_reader.clients.karakeep import KarakeepClient
from japan_reader.errors import ApiError, ConfigError, TransientError

HOST = "karakeep.test"


def _bookmark(bid, url, tags=(), archived=False, video=None):
    return {
        "id": bid,
        "title": None,
        "archived": archived,
        "tags": [{"id": f"t-{t}", "name": t, "attachedBy": "human"} for t in tags],
        "content": {"type": "link", "url": url, "title": f"T {bid}", "description": "desc", "videoAssetId": video},
    }


@pytest.fixture
def client():
    return KarakeepClient("http://karakeep.test/", "secret")


@respx.mock
def test_list_bookmarks_paginates(client):
    route = respx.get(host=HOST, path="/api/v1/lists/L1/bookmarks").mock(
        side_effect=[
            httpx.Response(200, json={"bookmarks": [_bookmark("b1", "https://youtu.be/a")], "nextCursor": "c2"}),
            httpx.Response(200, json={"bookmarks": [_bookmark("b2", "https://youtu.be/b", tags=["jr:procesado"])], "nextCursor": None}),
        ]
    )

    bookmarks = list(client.list_bookmarks("L1"))

    assert [b.id for b in bookmarks] == ["b1", "b2"]
    assert bookmarks[0].url == "https://youtu.be/a"
    assert bookmarks[0].title == "T b1"
    assert bookmarks[1].tags == ["jr:procesado"]
    assert route.calls[0].request.headers["Authorization"] == "Bearer secret"
    assert route.calls[1].request.url.params["cursor"] == "c2"


@respx.mock
def test_tags_archive_and_lists(client):
    attach = respx.post(host=HOST, path="/api/v1/bookmarks/b1/tags").mock(return_value=httpx.Response(200, json={"attached": []}))
    detach = respx.delete(host=HOST, path="/api/v1/bookmarks/b1/tags").mock(return_value=httpx.Response(200, json={"detached": []}))
    patch = respx.patch(host=HOST, path="/api/v1/bookmarks/b1").mock(return_value=httpx.Response(200, json={"id": "b1"}))
    add = respx.put(host=HOST, path="/api/v1/lists/L1/bookmarks/b1").mock(return_value=httpx.Response(204))

    client.attach_tags("b1", ["jr:procesado"])
    client.detach_tags("b1", ["jr:error"])
    client.set_archived("b1", True)
    client.add_to_list("L1", "b1")

    assert json.loads(attach.calls[0].request.content) == {"tags": [{"tagName": "jr:procesado"}]}
    assert json.loads(detach.calls[0].request.content) == {"tags": [{"tagName": "jr:error"}]}
    assert json.loads(patch.calls[0].request.content) == {"archived": True}
    assert add.called


@respx.mock
def test_find_and_create(client):
    respx.get(host=HOST, path="/api/v1/bookmarks/check-url").mock(return_value=httpx.Response(200, json={"bookmarkId": None}))
    create = respx.post(host=HOST, path="/api/v1/bookmarks").mock(return_value=httpx.Response(201, json=_bookmark("new", "https://youtu.be/z")))

    assert client.find_by_url("https://youtu.be/z") is None
    assert client.create_link("https://youtu.be/z") == "new"
    assert json.loads(create.calls[0].request.content) == {"type": "link", "url": "https://youtu.be/z", "source": "import"}


@respx.mock
def test_download_asset(client, tmp_path):
    respx.get(host=HOST, path="/api/v1/assets/a1").mock(return_value=httpx.Response(200, content=b"video-bytes"))
    dest = client.download_asset("a1", tmp_path / "v.mp4")
    assert dest.read_bytes() == b"video-bytes"


@respx.mock
@pytest.mark.parametrize(("status", "error"), [(401, ConfigError), (500, TransientError), (429, TransientError), (404, ApiError)])
def test_status_mapping(client, status, error):
    respx.get(host=HOST, path="/api/v1/bookmarks/b1").mock(return_value=httpx.Response(status, text="boom"))
    with pytest.raises(error):
        client.get_bookmark("b1")


@respx.mock
def test_transport_error_is_transient(client):
    respx.get(host=HOST, path="/api/v1/bookmarks/b1").mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(TransientError):
        client.get_bookmark("b1")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_karakeep_client.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'japan_reader.clients'`

- [ ] **Step 3: Write minimal implementation**

`src/japan_reader/clients/__init__.py`: fichero vacío.

`src/japan_reader/clients/http.py`:

```python
import httpx

from japan_reader.errors import ApiError, ConfigError, TransientError


def check_status(resp: httpx.Response, service: str) -> None:
    code = resp.status_code
    if code < 400:
        return
    if code in (401, 402, 403):
        raise ConfigError(f"{service}: credenciales o saldo rechazados (HTTP {code})")
    if code == 429 or code >= 500:
        raise TransientError(f"{service}: HTTP {code}")
    raise ApiError(service, code, resp.text)


def send(client: httpx.Client, method: str, url: str, service: str, **kwargs) -> httpx.Response:
    try:
        resp = client.request(method, url, **kwargs)
    except httpx.TransportError as exc:
        raise TransientError(f"{service}: {exc!r}") from exc
    check_status(resp, service)
    return resp
```

`src/japan_reader/clients/karakeep.py`:

```python
from collections.abc import Iterator
from pathlib import Path

import httpx
from pydantic import BaseModel

from japan_reader.clients.http import send


class Bookmark(BaseModel):
    id: str
    url: str | None = None
    title: str | None = None
    description: str | None = None
    author: str | None = None
    archived: bool = False
    tags: list[str] = []
    video_asset_id: str | None = None
    image_asset_id: str | None = None

    @classmethod
    def from_api(cls, data: dict) -> "Bookmark":
        content = data.get("content") or {}
        is_link = content.get("type") == "link"
        return cls(
            id=data["id"],
            url=content.get("url") if is_link else None,
            title=data.get("title") or content.get("title"),
            description=content.get("description"),
            author=content.get("author"),
            archived=bool(data.get("archived", False)),
            tags=[tag["name"] for tag in data.get("tags", [])],
            video_asset_id=content.get("videoAssetId"),
            image_asset_id=content.get("imageAssetId"),
        )


class KarakeepClient:
    """Cliente mínimo de la API REST de Karakeep (`/api/v1`)."""

    SERVICE = "karakeep"

    def __init__(self, base_url: str, api_key: str, http: httpx.Client | None = None) -> None:
        self._http = http or httpx.Client(timeout=60)
        self._base = base_url.rstrip("/") + "/api/v1"
        self._headers = {"Authorization": f"Bearer {api_key}"}

    def _req(self, method: str, path: str, **kwargs) -> httpx.Response:
        return send(self._http, method, self._base + path, self.SERVICE, headers=self._headers, **kwargs)

    def list_bookmarks(self, list_id: str) -> Iterator[Bookmark]:
        cursor: str | None = None
        while True:
            params = {"limit": 100, "includeContent": "false"}
            if cursor:
                params["cursor"] = cursor
            data = self._req("GET", f"/lists/{list_id}/bookmarks", params=params).json()
            for item in data.get("bookmarks", []):
                yield Bookmark.from_api(item)
            cursor = data.get("nextCursor")
            if not cursor:
                return

    def get_bookmark(self, bookmark_id: str) -> Bookmark:
        return Bookmark.from_api(self._req("GET", f"/bookmarks/{bookmark_id}").json())

    def attach_tags(self, bookmark_id: str, names: list[str]) -> None:
        self._req("POST", f"/bookmarks/{bookmark_id}/tags", json={"tags": [{"tagName": n} for n in names]})

    def detach_tags(self, bookmark_id: str, names: list[str]) -> None:
        self._req("DELETE", f"/bookmarks/{bookmark_id}/tags", json={"tags": [{"tagName": n} for n in names]})

    def set_archived(self, bookmark_id: str, archived: bool) -> None:
        self._req("PATCH", f"/bookmarks/{bookmark_id}", json={"archived": archived})

    def download_asset(self, asset_id: str, dest: Path) -> Path:
        resp = self._req("GET", f"/assets/{asset_id}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)
        return dest

    def find_by_url(self, url: str) -> str | None:
        return self._req("GET", "/bookmarks/check-url", params={"url": url}).json().get("bookmarkId")

    def create_link(self, url: str) -> str:
        return self._req("POST", "/bookmarks", json={"type": "link", "url": url, "source": "import"}).json()["id"]

    def add_to_list(self, list_id: str, bookmark_id: str) -> None:
        self._req("PUT", f"/lists/{list_id}/bookmarks/{bookmark_id}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_karakeep_client.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add src/japan_reader/clients tests/unit/test_karakeep_client.py
git commit -m "feat: HTTP error mapping and Karakeep client"
```

---

### Task 5: Etapas `ingest` y `mark` (+ documentación 01 y 08)

**Files:**
- Create: `src/japan_reader/ingest.py`, `src/japan_reader/stages/__init__.py` (vacío), `src/japan_reader/stages/mark.py`, `tests/fakes.py`, `docs/pipeline/01-ingest.md`, `docs/pipeline/08-mark.md`
- Test: `tests/unit/test_ingest_mark.py`

**Interfaces:**
- Consumes: `KarakeepClient`, `Bookmark` (Tarea 4); `StateStore` (Tarea 3); `classify_url` (Tarea 2); `Outcome`, `MarkResult`.
- Produces:
  - `ingest.IngestReport(new: list[str], unsupported: list[str])`, `ingest.JR_TAG_PREFIX = "jr:"`, `ingest.ingest(karakeep, state, list_id) -> IngestReport`. Las fuentes no soportadas se registran como job **sin plataforma**; el pipeline (Tarea 16) las marca `jr:error`.
  - `stages.mark.OUTCOME_TAGS: dict[Outcome, str]`, `MarkStage(karakeep)` con `run(bookmark_id: str, outcome: Outcome) -> MarkResult`.
  - `tests/fakes.py`: `FakeKarakeep` (se amplía en tareas posteriores).

- [ ] **Step 1: Write the fake and the failing test**

`tests/fakes.py`:

```python
from pathlib import Path

from japan_reader.clients.karakeep import Bookmark


class FakeKarakeep:
    """Karakeep en memoria con la misma interfaz pública que KarakeepClient."""

    def __init__(self, bookmarks: list[Bookmark] | None = None) -> None:
        self.bookmarks: dict[str, Bookmark] = {b.id: b for b in bookmarks or []}
        self.lists: dict[str, list[str]] = {"L1": [b.id for b in bookmarks or []]}
        self.assets: dict[str, bytes] = {}
        self.calls: list[tuple] = []

    def list_bookmarks(self, list_id: str):
        yield from (self.bookmarks[bid] for bid in self.lists.get(list_id, []))

    def get_bookmark(self, bookmark_id: str) -> Bookmark:
        return self.bookmarks[bookmark_id]

    def attach_tags(self, bookmark_id: str, names: list[str]) -> None:
        self.calls.append(("attach", bookmark_id, tuple(names)))
        bookmark = self.bookmarks[bookmark_id]
        bookmark.tags = sorted(set(bookmark.tags) | set(names))

    def detach_tags(self, bookmark_id: str, names: list[str]) -> None:
        self.calls.append(("detach", bookmark_id, tuple(names)))
        bookmark = self.bookmarks[bookmark_id]
        bookmark.tags = [t for t in bookmark.tags if t not in names]

    def set_archived(self, bookmark_id: str, archived: bool) -> None:
        self.calls.append(("archive", bookmark_id, archived))
        self.bookmarks[bookmark_id].archived = archived

    def download_asset(self, asset_id: str, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.assets[asset_id])
        return dest

    def find_by_url(self, url: str) -> str | None:
        return next((b.id for b in self.bookmarks.values() if b.url == url), None)

    def create_link(self, url: str) -> str:
        bid = f"new{len(self.bookmarks) + 1}"
        self.bookmarks[bid] = Bookmark(id=bid, url=url)
        return bid

    def add_to_list(self, list_id: str, bookmark_id: str) -> None:
        self.lists.setdefault(list_id, [])
        if bookmark_id not in self.lists[list_id]:
            self.lists[list_id].append(bookmark_id)
```

`tests/unit/test_ingest_mark.py`:

```python
import pytest

from fakes import FakeKarakeep
from japan_reader.clients.karakeep import Bookmark
from japan_reader.ingest import ingest
from japan_reader.models import Outcome
from japan_reader.sources import ContentHint, Platform
from japan_reader.stages.mark import MarkStage
from japan_reader.state import StateStore


@pytest.fixture
def state(tmp_path):
    return StateStore(tmp_path / "state.db")


def test_ingest_creates_jobs_for_new_supported_bookmarks(state):
    karakeep = FakeKarakeep([
        Bookmark(id="b1", url="https://www.youtube.com/shorts/abc"),
        Bookmark(id="b2", url="https://www.instagram.com/p/XYZ/"),
    ])

    report = ingest(karakeep, state, "L1")

    assert report.new == ["b1", "b2"]
    assert state.get_job("b2").platform == Platform.INSTAGRAM
    assert state.get_job("b2").hint == ContentHint.POST


def test_ingest_is_idempotent(state):
    karakeep = FakeKarakeep([Bookmark(id="b1", url="https://youtu.be/abc")])
    ingest(karakeep, state, "L1")
    assert ingest(karakeep, state, "L1").new == []


def test_ingest_registers_unsupported_without_platform(state):
    karakeep = FakeKarakeep([Bookmark(id="b1", url="https://www.tiktok.com/@u/video/1"), Bookmark(id="b2", url=None)])

    report = ingest(karakeep, state, "L1")

    assert report.unsupported == ["b1", "b2"]
    assert state.get_job("b1").platform is None


def test_ingest_skips_bookmarks_already_tagged_when_state_was_lost(state):
    """Review Focus 5: state.db recreado no reprocesa lo ya marcado."""
    karakeep = FakeKarakeep([
        Bookmark(id="b1", url="https://youtu.be/a", tags=["jr:procesado"], archived=True),
        Bookmark(id="b2", url="https://youtu.be/b", tags=["jr:error"]),
        Bookmark(id="b3", url="https://youtu.be/c", tags=["viaje"]),
    ])

    report = ingest(karakeep, state, "L1")

    assert report.new == ["b3"]
    assert not state.has_job("b1") and not state.has_job("b2")


@pytest.mark.parametrize(
    ("outcome", "tag", "archived"),
    [
        (Outcome.PROCESADO, "jr:procesado", True),
        (Outcome.REVISAR, "jr:revisar", True),
        (Outcome.NO_JAPON, "jr:no-japon", True),
        (Outcome.ERROR, "jr:error", False),
    ],
)
def test_mark_tags_and_archives(outcome, tag, archived):
    karakeep = FakeKarakeep([Bookmark(id="b1", url="https://youtu.be/a", tags=["jr:error", "viaje"])])

    result = MarkStage(karakeep).run("b1", outcome)

    bookmark = karakeep.bookmarks["b1"]
    assert result.tag == tag and result.archived is archived
    assert bookmark.archived is archived
    assert tag in bookmark.tags and "viaje" in bookmark.tags
    assert [t for t in bookmark.tags if t.startswith("jr:")] == [tag]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_ingest_mark.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'japan_reader.ingest'`

- [ ] **Step 3: Write minimal implementation**

`src/japan_reader/ingest.py`:

```python
import logging
from dataclasses import dataclass, field

from japan_reader.clients.karakeep import KarakeepClient
from japan_reader.errors import ApiError, ConfigError
from japan_reader.sources import classify_url
from japan_reader.state import StateStore

log = logging.getLogger(__name__)

JR_TAG_PREFIX = "jr:"


@dataclass
class IngestReport:
    new: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)


def ingest(karakeep: KarakeepClient, state: StateStore, list_id: str) -> IngestReport:
    """Crea un job por cada bookmark nuevo de la lista. Etapa 1 del pipeline."""
    try:
        bookmarks = list(karakeep.list_bookmarks(list_id))
    except ApiError as exc:
        if exc.status == 404:
            raise ConfigError(f"No existe la lista de Karakeep {list_id} (KARAKEEP_LIST_ID)") from exc
        raise

    report = IngestReport()
    for bookmark in bookmarks:
        if state.has_job(bookmark.id) or any(tag.startswith(JR_TAG_PREFIX) for tag in bookmark.tags):
            continue
        classified = classify_url(bookmark.url) if bookmark.url else None
        if classified is None:
            state.add_job(bookmark.id, bookmark.url or "", None, None)
            report.unsupported.append(bookmark.id)
            log.info("bookmark=%s fuente no soportada url=%s", bookmark.id, bookmark.url)
            continue
        state.add_job(bookmark.id, bookmark.url, *classified)
        report.new.append(bookmark.id)
        log.info("bookmark=%s nuevo job url=%s", bookmark.id, bookmark.url)
    return report
```

`src/japan_reader/stages/__init__.py`: fichero vacío.

`src/japan_reader/stages/mark.py`:

```python
from japan_reader.clients.karakeep import KarakeepClient
from japan_reader.models import MarkResult, Outcome

OUTCOME_TAGS: dict[Outcome, str] = {
    Outcome.PROCESADO: "jr:procesado",
    Outcome.REVISAR: "jr:revisar",
    Outcome.NO_JAPON: "jr:no-japon",
    Outcome.ERROR: "jr:error",
}


class MarkStage:
    """Etapa 8: etiqueta el bookmark con el resultado y lo archiva (salvo error)."""

    name = "mark"

    def __init__(self, karakeep: KarakeepClient) -> None:
        self._karakeep = karakeep

    def run(self, bookmark_id: str, outcome: Outcome) -> MarkResult:
        tag = OUTCOME_TAGS[outcome]
        bookmark = self._karakeep.get_bookmark(bookmark_id)
        stale = [t for t in bookmark.tags if t.startswith("jr:") and t != tag]
        if stale:
            self._karakeep.detach_tags(bookmark_id, stale)
        self._karakeep.attach_tags(bookmark_id, [tag])
        archive = outcome != Outcome.ERROR
        if archive:
            self._karakeep.set_archived(bookmark_id, True)
        return MarkResult(tag=tag, archived=archive)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_ingest_mark.py -v`
Expected: all passed

- [ ] **Step 5: Write stage docs**

`docs/pipeline/01-ingest.md`:

```markdown
# Etapa 1 — ingest

**Qué hace:** lee la lista de Karakeep configurada y crea un *job* en `state.db` por cada bookmark nuevo.

**Entrada:** `KARAKEEP_LIST_ID` (lista "Japón").
**Salida:** filas en la tabla `jobs` (`bookmark_id`, `url`, `platform`, `hint`, `status=pending`).
**Dependencias:** API de Karakeep (`GET /api/v1/lists/{id}/bookmarks`, paginada con `cursor`).
**Configuración:** `KARAKEEP_URL`, `KARAKEEP_API_KEY`, `KARAKEEP_LIST_ID`, `POLL_INTERVAL_MINUTES`.

**Reglas:**
- Se ignoran los bookmarks que ya tienen job o que ya llevan una etiqueta `jr:*` (protege frente a pérdida de `state.db`).
- URLs soportadas: YouTube (`/shorts/`, `watch`, `youtu.be`) e Instagram (`/reel/`, `/reels/`, `/tv/`, `/p/`, también con usuario delante).
- Las no soportadas (u otros tipos de bookmark) se registran sin plataforma; el pipeline las marca `jr:error` con motivo "fuente no soportada".

**Fallos:** lista inexistente → `ConfigError` (se detiene y avisa por ntfy); 401/403 → `ConfigError`; red/5xx → se reintenta en el siguiente sondeo.

**Cómo probarla:** `uv run pytest tests/unit/test_ingest_mark.py -k ingest`. En real: `japan-reader run-once` y `japan-reader status`.
```

`docs/pipeline/08-mark.md`:

```markdown
# Etapa 8 — mark

**Qué hace:** deja constancia del resultado en Karakeep y limpia la Home.

**Entrada:** `bookmark_id` y el resultado (`Outcome`) calculado por `publish`, o `error`.
**Salida:** `MarkResult {tag, archived}`.
**Dependencias:** Karakeep (`GET /bookmarks/{id}`, `POST/DELETE /bookmarks/{id}/tags`, `PATCH /bookmarks/{id}`).

| Resultado | Etiqueta | Archivar |
|---|---|---|
| procesado | `jr:procesado` | sí |
| revisar | `jr:revisar` | sí |
| no-japon | `jr:no-japon` | sí |
| error | `jr:error` | no |

Quita cualquier otra etiqueta `jr:*` anterior (útil al reprocesar). El resto de etiquetas del usuario no se tocan.

**Fallos:** red/5xx → reintento del job (las etapas anteriores no se repiten); si falla marcando un error definitivo, el job queda en error igualmente y se registra en el log.

**Cómo probarla:** `uv run pytest tests/unit/test_ingest_mark.py -k mark`.
```

- [ ] **Step 6: Commit**

```bash
git add src/japan_reader tests docs/pipeline
git commit -m "feat: ingest and mark stages with Karakeep tagging and archiving"
```

---

### Task 6: Utilidades de medios (audio, fotogramas clave, imágenes, subtítulos)

**Files:**
- Create: `src/japan_reader/media/__init__.py` (vacío), `src/japan_reader/media/audio.py`, `src/japan_reader/media/keyframes.py`, `src/japan_reader/media/images.py`, `src/japan_reader/media/subtitles.py`, `tests/helpers.py`
- Test: `tests/unit/test_media.py`

**Interfaces:**
- Produces:
  - `media.audio.has_audio(video: Path) -> bool`, `extract_audio(video: Path, dest: Path) -> Path | None` (WAV mono 16 kHz; `None` si no hay pista de audio), `probe_duration(path: Path) -> float | None`.
  - `media.keyframes.extract_keyframes(video: Path, out_dir: Path, max_frames: int) -> list[Path]`, `dedupe_similar(paths: list[Path], threshold=8.0) -> list[Path]`, `pick_evenly[T](items: list[T], n: int) -> list[T]`.
  - `media.images.resize_image(src: Path, dest: Path, max_side: int) -> Path` (JPEG, lado mayor ≤ `max_side`).
  - `media.subtitles.vtt_to_text(vtt: str) -> str`.
  - `tests/helpers.py`: `make_video(path, colors=("red","blue","green"), seconds=1, with_audio=True) -> Path`, `make_image(path, size=(2000, 1500), color="red") -> Path`.
- Requiere `ffmpeg` y `ffprobe` en el PATH (ya instalados en el host; el Dockerfile los instala).

- [ ] **Step 1: Write the helpers and the failing test**

`tests/helpers.py`:

```python
import subprocess
from pathlib import Path

from PIL import Image


def make_video(path: Path, colors=("red", "blue", "green"), seconds: int = 1, with_audio: bool = True) -> Path:
    """Vídeo sintético: un tramo de color liso por cada color (cambios de escena bruscos)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-v", "error"]
    for color in colors:
        cmd += ["-f", "lavfi", "-i", f"color=c={color}:s=320x240:d={seconds}:r=10"]
    n = len(colors)
    if with_audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds * n}"]
    video_inputs = "".join(f"[{i}:v]" for i in range(n))
    cmd += ["-filter_complex", f"{video_inputs}concat=n={n}:v=1:a=0[v]", "-map", "[v]"]
    if with_audio:
        cmd += ["-map", f"{n}:a", "-c:a", "aac", "-shortest"]
    cmd += ["-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, check=True, capture_output=True)
    return path


def make_image(path: Path, size=(2000, 1500), color: str = "red") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return path
```

`tests/unit/test_media.py`:

```python
from PIL import Image

from helpers import make_image, make_video
from japan_reader.media.audio import extract_audio, has_audio, probe_duration
from japan_reader.media.images import resize_image
from japan_reader.media.keyframes import dedupe_similar, extract_keyframes, pick_evenly
from japan_reader.media.subtitles import vtt_to_text


def test_extract_audio(tmp_path):
    video = make_video(tmp_path / "v.mp4")
    wav = extract_audio(video, tmp_path / "out" / "a.wav")
    assert wav is not None and wav.exists()
    assert has_audio(video)
    assert 2.5 <= probe_duration(video) <= 3.5


def test_extract_audio_without_audio_track(tmp_path):
    video = make_video(tmp_path / "v.mp4", with_audio=False)
    assert extract_audio(video, tmp_path / "a.wav") is None


def test_keyframes_one_per_scene(tmp_path):
    video = make_video(tmp_path / "v.mp4", colors=("red", "blue", "green"))
    frames = extract_keyframes(video, tmp_path / "frames", max_frames=6)
    colors = {Image.open(f).convert("RGB").resize((1, 1)).getpixel((0, 0)) for f in frames}
    assert len(frames) == 3
    assert len(colors) == 3


def test_keyframes_static_video_collapses_duplicates(tmp_path):
    video = make_video(tmp_path / "v.mp4", colors=("red",), seconds=3)
    assert len(extract_keyframes(video, tmp_path / "frames", max_frames=6)) == 1


def test_keyframes_respect_max(tmp_path):
    video = make_video(tmp_path / "v.mp4", colors=("red", "blue", "green", "yellow", "white", "black", "purple", "orange"))
    assert len(extract_keyframes(video, tmp_path / "frames", max_frames=4)) == 4


def test_pick_evenly():
    assert pick_evenly(list(range(10)), 3) == [0, 4, 9]
    assert pick_evenly([1, 2], 5) == [1, 2]
    assert pick_evenly([1, 2, 3], 1) == [1]


def test_dedupe_similar(tmp_path):
    a = make_image(tmp_path / "a.png", size=(64, 64), color="red")
    b = make_image(tmp_path / "b.png", size=(64, 64), color="red")
    c = make_image(tmp_path / "c.png", size=(64, 64), color="blue")
    assert dedupe_similar([a, b, c]) == [a, c]


def test_resize_image(tmp_path):
    src = make_image(tmp_path / "big.png", size=(2000, 1500))
    out = resize_image(src, tmp_path / "small" / "x.jpg", 1024)
    with Image.open(out) as im:
        assert im.format == "JPEG"
        assert max(im.size) == 1024


def test_vtt_to_text():
    vtt = """WEBVTT
Kind: captions
Language: es

00:00:00.000 --> 00:00:01.500
Hoy vamos a <c>Fushimi Inari</c>

00:00:01.500 --> 00:00:03.000
Hoy vamos a <c>Fushimi Inari</c>

2
00:03.000 --> 00:04.000
en Kioto
"""
    assert vtt_to_text(vtt) == "Hoy vamos a Fushimi Inari en Kioto"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_media.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'japan_reader.media'`

- [ ] **Step 3: Write minimal implementation**

`src/japan_reader/media/__init__.py`: fichero vacío.

`src/japan_reader/media/audio.py`:

```python
import subprocess
from pathlib import Path


def _probe(args: list[str]) -> str:
    return subprocess.run(["ffprobe", "-v", "error", *args], capture_output=True, text=True, check=True).stdout.strip()


def has_audio(video: Path) -> bool:
    return bool(_probe(["-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(video)]))


def probe_duration(path: Path) -> float | None:
    try:
        return float(_probe(["-show_entries", "format=duration", "-of", "csv=p=0", str(path)]))
    except ValueError:
        return None


def extract_audio(video: Path, dest: Path) -> Path | None:
    """Pista de audio en WAV mono 16 kHz (formato ideal para Whisper)."""
    if not has_audio(video):
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", str(dest)],
        check=True,
        capture_output=True,
    )
    return dest
```

`src/japan_reader/media/keyframes.py`:

```python
import subprocess
from pathlib import Path

from PIL import Image

from japan_reader.media.audio import probe_duration

SCENE_THRESHOLD = 0.3
DUPLICATE_THRESHOLD = 8.0


def _ffmpeg(args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-y", "-v", "error", *args], check=True, capture_output=True)


def extract_keyframes(video: Path, out_dir: Path, max_frames: int) -> list[Path]:
    """Primer fotograma + cambios de escena; si no llegan a `max_frames`, completa con muestreo uniforme.

    Después descarta los casi idénticos y reparte los restantes a lo largo del vídeo.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    _ffmpeg([
        "-i", str(video),
        "-vf", f"select=eq(n\\,0)+gt(scene\\,{SCENE_THRESHOLD})",
        "-fps_mode", "vfr",
        str(out_dir / "scene_%03d.jpg"),
    ])
    frames = sorted(out_dir.glob("scene_*.jpg"))
    if len(frames) < max_frames:
        duration = probe_duration(video) or 1.0
        _ffmpeg(["-i", str(video), "-vf", f"fps={max_frames / duration:.4f}", str(out_dir / "uniform_%03d.jpg")])
        frames += sorted(out_dir.glob("uniform_*.jpg"))
    return pick_evenly(dedupe_similar(frames), max_frames)


def _signature(path: Path) -> bytes:
    # En color: en escala de grises el rojo y el verde puros casi coinciden.
    with Image.open(path) as im:
        return im.convert("RGB").resize((8, 8)).tobytes()


def dedupe_similar(paths: list[Path], threshold: float = DUPLICATE_THRESHOLD) -> list[Path]:
    kept: list[Path] = []
    signatures: list[bytes] = []
    for path in paths:
        sig = _signature(path)
        if all(sum(abs(a - b) for a, b in zip(sig, other)) / len(sig) > threshold for other in signatures):
            kept.append(path)
            signatures.append(sig)
    return kept


def pick_evenly[T](items: list[T], n: int) -> list[T]:
    if len(items) <= n:
        return list(items)
    if n == 1:
        return [items[0]]
    return [items[round(i * (len(items) - 1) / (n - 1))] for i in range(n)]
```

`src/japan_reader/media/images.py`:

```python
from pathlib import Path

from PIL import Image, ImageOps


def resize_image(src: Path, dest: Path, max_side: int) -> Path:
    """Convierte a JPEG con el lado mayor limitado, para abaratar las llamadas de visión."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        image = ImageOps.exif_transpose(im).convert("RGB")
        image.thumbnail((max_side, max_side))
        image.save(dest, "JPEG", quality=85)
    return dest
```

`src/japan_reader/media/subtitles.py`:

```python
import re

_TIMESTAMP = re.compile(r"^(\d{2}:)?\d{2}:\d{2}\.\d{3} --> ")
_TAG = re.compile(r"<[^>]+>")
_HEADERS = ("WEBVTT", "Kind:", "Language:", "NOTE", "STYLE")


def vtt_to_text(vtt: str) -> str:
    """Texto plano de un WebVTT, sin marcas de tiempo, etiquetas ni líneas repetidas seguidas."""
    lines: list[str] = []
    for raw in vtt.splitlines():
        line = raw.strip()
        if not line or line.startswith(_HEADERS) or _TIMESTAMP.match(line) or line.isdigit():
            continue
        line = _TAG.sub("", line).strip()
        if line and (not lines or lines[-1] != line):
            lines.append(line)
    return " ".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_media.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add src/japan_reader/media tests/helpers.py tests/unit/test_media.py
git commit -m "feat: media helpers for audio, keyframes, images and subtitles"
```

---

### Task 7: Descargadores (yt-dlp para vídeos, gallery-dl para posts)

**Files:**
- Create: `src/japan_reader/media/downloaders.py`
- Test: `tests/unit/test_downloaders.py`

**Interfaces:**
- Consumes: `SourceMeta`, `ContentType` (Tarea 2); `Platform`; errores; `vtt_to_text` (Tarea 6).
- Produces:
  - `DownloadedMedia(meta: SourceMeta, videos: list[Path] = [], images: list[Path] = [], subtitles: str | None = None)`.
  - `classify_download_error(message: str) -> type[JapanReaderError]` (`PermanentError` o `TransientError`).
  - `prepare_cookies(src: Path | None, dest_dir: Path) -> Path | None` (copia de trabajo; `ConfigError` si `src` no existe).
  - `YtDlpDownloader(cookies_file: Path | None, max_duration_s: int, ydl_factory=yt_dlp.YoutubeDL)` con `download(url, platform, dest: Path) -> DownloadedMedia`.
  - `GalleryDlDownloader(cookies_file: Path | None, binary="gallery-dl", runner=subprocess.run)` con `download(url, dest: Path) -> DownloadedMedia`.
  - `meta_from_ytdlp(info, url, platform) -> SourceMeta`, `meta_from_gallerydl(data, url, content_type) -> SourceMeta`.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_downloaders.py`:

```python
import json
import stat
import subprocess
from pathlib import Path

import pytest
from yt_dlp.utils import DownloadError

from japan_reader.errors import ConfigError, PermanentError, TransientError
from japan_reader.media.downloaders import (
    GalleryDlDownloader,
    YtDlpDownloader,
    classify_download_error,
    prepare_cookies,
)
from japan_reader.models import ContentType
from japan_reader.sources import Platform

VTT = "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nBienvenidos a Kioto\n"


def ydl_factory(info: dict, error: str | None = None, subtitles: bool = True):
    created = []

    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts
            created.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            cookie = self.opts.get("cookiefile")
            if cookie:
                Path(cookie).write_text("rewritten by yt-dlp")
            return False

        def extract_info(self, url, download=False):
            if error:
                raise DownloadError(error)
            return dict(info)

        def process_ie_result(self, result, download=True):
            dest = Path(self.opts["outtmpl"]).parent
            (dest / "video.mp4").write_bytes(b"video")
            if subtitles:
                (dest / "video.es.vtt").write_text(VTT)
            return result

    FakeYDL.created = created
    return FakeYDL


INFO = {
    "title": "Fushimi Inari al amanecer",
    "description": "Consejos para evitar colas #kyoto #japon",
    "uploader": "viajero",
    "upload_date": "20260801",
    "duration": 45,
    "tags": ["travel"],
}


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("ERROR: Private video", PermanentError),
        ("ERROR: This video is unavailable", PermanentError),
        ("Requested content is not available, rate-limit reached or login required", PermanentError),
        ("HTTP Error 404: Not Found", PermanentError),
        ("Read timed out", TransientError),
        ("HTTP Error 503: Service Unavailable", TransientError),
    ],
)
def test_classify_download_error(message, expected):
    assert classify_download_error(message) is expected


def test_ytdlp_download_returns_video_meta_and_subtitles(tmp_path):
    factory = ydl_factory(INFO)
    media = YtDlpDownloader(None, 900, ydl_factory=factory).download("https://youtu.be/x", Platform.YOUTUBE, tmp_path / "raw")

    assert media.videos == [tmp_path / "raw" / "video.mp4"]
    assert media.subtitles == "Bienvenidos a Kioto"
    assert media.meta.title == "Fushimi Inari al amanecer"
    assert media.meta.author == "viajero"
    assert media.meta.published == "2026-08-01"
    assert media.meta.content_type == ContentType.VIDEO
    assert set(media.meta.hashtags) == {"kyoto", "japon", "travel"}
    opts = factory.created[0].opts
    assert opts["writesubtitles"] is True and opts["writeautomaticsub"] is False


def test_ytdlp_rejects_long_videos(tmp_path):
    with pytest.raises(PermanentError, match="demasiado largo"):
        YtDlpDownloader(None, 900, ydl_factory=ydl_factory(INFO | {"duration": 3600})).download(
            "https://youtu.be/x", Platform.YOUTUBE, tmp_path / "raw"
        )


def test_ytdlp_maps_errors(tmp_path):
    with pytest.raises(PermanentError):
        YtDlpDownloader(None, 900, ydl_factory=ydl_factory(INFO, error="Private video")).download(
            "https://youtu.be/x", Platform.YOUTUBE, tmp_path / "raw"
        )


def test_cookies_file_is_never_written(tmp_path):
    """Review Focus 4: el fichero original (montado solo lectura) no se modifica."""
    original = tmp_path / "cookies.txt"
    original.write_text("# Netscape HTTP Cookie File\n")
    original.chmod(stat.S_IRUSR)
    factory = ydl_factory(INFO)

    YtDlpDownloader(original, 900, ydl_factory=factory).download("https://instagram.com/reel/x", Platform.INSTAGRAM, tmp_path / "raw")

    used = Path(factory.created[0].opts["cookiefile"])
    assert used != original
    assert original.read_text() == "# Netscape HTTP Cookie File\n"


def test_prepare_cookies_missing_file(tmp_path):
    with pytest.raises(ConfigError):
        prepare_cookies(tmp_path / "missing.txt", tmp_path)
    assert prepare_cookies(None, tmp_path) is None


def gallery_runner(files: dict[str, bytes], meta: dict, returncode: int = 0, stderr: str = ""):
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        dest = Path(cmd[cmd.index("--directory") + 1])
        dest.mkdir(parents=True, exist_ok=True)
        for name, data in files.items():
            (dest / name).write_bytes(data)
            (dest / f"{name}.json").write_text(json.dumps(meta))
        return subprocess.CompletedProcess(cmd, returncode, stdout="", stderr=stderr)

    run.calls = calls
    return run


POST_META = {"description": "Qué comprar en Don Quijote #souvenirs", "username": "tokyoshop", "date": "2026-07-01 10:00:00", "tags": ["#souvenirs"]}


def test_gallery_carousel(tmp_path):
    runner = gallery_runner({"01.jpg": b"a", "02.jpg": b"b"}, POST_META)

    media = GalleryDlDownloader(None, runner=runner).download("https://www.instagram.com/p/X/", tmp_path / "raw")

    assert media.meta.content_type == ContentType.CAROUSEL
    assert [p.name for p in media.images] == ["01.jpg", "02.jpg"]
    assert media.videos == []
    assert media.meta.author == "tokyoshop"
    assert media.meta.published == "2026-07-01"
    assert media.meta.hashtags == ["souvenirs"]


def test_gallery_single_video_post(tmp_path):
    media = GalleryDlDownloader(None, runner=gallery_runner({"01.mp4": b"v"}, POST_META)).download(
        "https://www.instagram.com/p/X/", tmp_path / "raw"
    )
    assert media.meta.content_type == ContentType.VIDEO
    assert [p.name for p in media.videos] == ["01.mp4"]


def test_gallery_errors(tmp_path):
    with pytest.raises(PermanentError):
        GalleryDlDownloader(None, runner=gallery_runner({}, {}, 1, "HttpError: '404 Not Found'")).download("u", tmp_path / "a")
    with pytest.raises(TransientError):
        GalleryDlDownloader(None, runner=gallery_runner({}, {}, 1, "Read timed out")).download("u", tmp_path / "b")
    with pytest.raises(PermanentError, match="no contiene medios"):
        GalleryDlDownloader(None, runner=gallery_runner({}, {})).download("u", tmp_path / "c")


def test_gallery_uses_cookie_copy(tmp_path):
    original = tmp_path / "cookies.txt"
    original.write_text("c")
    runner = gallery_runner({"01.jpg": b"a"}, POST_META)

    GalleryDlDownloader(original, runner=runner).download("https://www.instagram.com/p/X/", tmp_path / "raw")

    cmd = runner.calls[0]
    assert Path(cmd[cmd.index("--cookies") + 1]) != original
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_downloaders.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'japan_reader.media.downloaders'`

- [ ] **Step 3: Write minimal implementation**

`src/japan_reader/media/downloaders.py`:

```python
import json
import re
import shutil
import subprocess
from pathlib import Path

import yt_dlp
from pydantic import BaseModel
from yt_dlp.utils import DownloadError

from japan_reader.errors import ConfigError, JapanReaderError, PermanentError, TransientError
from japan_reader.media.subtitles import vtt_to_text
from japan_reader.models import ContentType, SourceMeta
from japan_reader.sources import Platform

VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
SUBTITLE_LANGS = ("es", "en", "ja")
_PERMANENT_MARKERS = (
    "private", "unavailable", "removed", "not available", "login required", "log in",
    "does not exist", "copyright", "sign in to confirm", "404",
)
_HASHTAG = re.compile(r"#(\w+)")


class DownloadedMedia(BaseModel):
    meta: SourceMeta
    videos: list[Path] = []
    images: list[Path] = []
    subtitles: str | None = None


def classify_download_error(message: str) -> type[JapanReaderError]:
    lowered = message.lower()
    return PermanentError if any(marker in lowered for marker in _PERMANENT_MARKERS) else TransientError


def prepare_cookies(src: Path | None, dest_dir: Path) -> Path | None:
    """Copia de trabajo de las cookies: yt-dlp y gallery-dl reescriben el fichero que usan."""
    if src is None:
        return None
    if not src.exists():
        raise ConfigError(f"No existe el fichero de cookies de Instagram: {src}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    copy = dest_dir / "cookies.txt"
    shutil.copyfile(src, copy)
    return copy


def meta_from_ytdlp(info: dict, url: str, platform: Platform) -> SourceMeta:
    description = info.get("description") or ""
    hashtags = sorted(set(info.get("tags") or []) | set(_HASHTAG.findall(description)))
    upload = info.get("upload_date")
    return SourceMeta(
        url=url,
        platform=platform,
        content_type=ContentType.VIDEO,
        title=info.get("title"),
        description=description or None,
        hashtags=hashtags,
        author=info.get("uploader") or info.get("channel"),
        published=f"{upload[:4]}-{upload[4:6]}-{upload[6:8]}" if upload else None,
        duration_s=info.get("duration"),
    )


def meta_from_gallerydl(data: dict, url: str, content_type: ContentType) -> SourceMeta:
    description = data.get("description") or ""
    tags = [t.lstrip("#") for t in data.get("tags") or []] or _HASHTAG.findall(description)
    date = data.get("date")
    return SourceMeta(
        url=url,
        platform=Platform.INSTAGRAM,
        content_type=content_type,
        description=description or None,
        hashtags=sorted(set(tags)),
        author=data.get("username") or data.get("fullname"),
        published=str(date)[:10] if date else None,
    )


class YtDlpDownloader:
    """Vídeos de YouTube e Instagram Reels."""

    def __init__(self, cookies_file: Path | None, max_duration_s: int, ydl_factory=yt_dlp.YoutubeDL) -> None:
        self._cookies = cookies_file
        self._max_duration = max_duration_s
        self._factory = ydl_factory

    def download(self, url: str, platform: Platform, dest: Path) -> DownloadedMedia:
        dest.mkdir(parents=True, exist_ok=True)
        cookies = prepare_cookies(self._cookies, dest)
        opts = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "outtmpl": str(dest / "video.%(ext)s"),
            "format": "bv*[height<=720]+ba/b[height<=720]/b",
            "merge_output_format": "mp4",
            "writesubtitles": True,
            "writeautomaticsub": False,
            "subtitleslangs": list(SUBTITLE_LANGS),
            "subtitlesformat": "vtt",
            "cookiefile": str(cookies) if cookies else None,
        }
        try:
            with self._factory(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                duration = info.get("duration")
                if duration and duration > self._max_duration:
                    raise PermanentError(f"demasiado largo ({duration:.0f} s > {self._max_duration} s)")
                ydl.process_ie_result(info, download=True)
        except DownloadError as exc:
            raise classify_download_error(str(exc))(f"yt-dlp: {exc}") from exc
        videos = [p for p in sorted(dest.glob("video.*")) if p.suffix in VIDEO_EXTS]
        if not videos:
            raise PermanentError("yt-dlp: no se descargó ningún vídeo")
        return DownloadedMedia(meta=meta_from_ytdlp(info, url, platform), videos=videos[:1], subtitles=self._subtitles(dest))

    @staticmethod
    def _subtitles(dest: Path) -> str | None:
        for lang in SUBTITLE_LANGS:
            path = dest / f"video.{lang}.vtt"
            if path.exists():
                return vtt_to_text(path.read_text(encoding="utf-8")) or None
        return None


class GalleryDlDownloader:
    """Posts de Instagram (imagen o carrusel; los elementos de vídeo se devuelven como vídeos)."""

    def __init__(self, cookies_file: Path | None, binary: str = "gallery-dl", runner=subprocess.run) -> None:
        self._cookies = cookies_file
        self._binary = binary
        self._run = runner

    def download(self, url: str, dest: Path) -> DownloadedMedia:
        dest.mkdir(parents=True, exist_ok=True)
        cmd = [self._binary, "--directory", str(dest), "--filename", "{num:>02}.{extension}", "--write-metadata", "--no-part"]
        cookies = prepare_cookies(self._cookies, dest.parent / "cookies")
        if cookies:
            cmd += ["--cookies", str(cookies)]
        cmd.append(url)
        try:
            proc = self._run(cmd, capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired as exc:
            raise TransientError("gallery-dl: tiempo de espera agotado") from exc
        files = sorted(p for p in dest.iterdir() if p.suffix.lower() in IMAGE_EXTS | VIDEO_EXTS)
        if proc.returncode != 0 and not files:
            message = (proc.stderr or "").strip()[-500:]
            raise classify_download_error(message)(f"gallery-dl: {message}")
        if not files:
            raise PermanentError("gallery-dl: el post no contiene medios")
        metadata_files = sorted(dest.glob("*.json"))
        data = json.loads(metadata_files[0].read_text(encoding="utf-8")) if metadata_files else {}
        images = [p for p in files if p.suffix.lower() in IMAGE_EXTS]
        videos = [p for p in files if p.suffix.lower() in VIDEO_EXTS]
        if len(files) > 1:
            content_type = ContentType.CAROUSEL
        else:
            content_type = ContentType.VIDEO if videos else ContentType.IMAGE
        return DownloadedMedia(meta=meta_from_gallerydl(data, url, content_type), images=images, videos=videos)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_downloaders.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add src/japan_reader/media/downloaders.py tests/unit/test_downloaders.py
git commit -m "feat: yt-dlp and gallery-dl downloaders with error mapping and cookie copies"
```

---

### Task 8: Etapa `fetch` (+ builders de test y documentación 02)

**Files:**
- Create: `src/japan_reader/stages/fetch.py`, `tests/builders.py`, `docs/pipeline/02-fetch.md`
- Test: `tests/unit/test_fetch.py`

**Interfaces:**
- Consumes: `Settings`; `YtDlpDownloader`, `GalleryDlDownloader`, `DownloadedMedia` (Tarea 7); `extract_audio`, `extract_keyframes`, `resize_image` (Tarea 6); `KarakeepClient` (Tarea 4); `JobContext` (Tarea 3).
- Produces:
  - `FetchStage(settings, ytdlp, gallery, karakeep, keyframer=extract_keyframes, audio_extractor=extract_audio)`; atributos `name = "fetch"`, `result_model = FetchResult`; `run(ctx) -> FetchResult`. Estructura en disco: `images/NN.jpg`, `frames/VV_NN.jpg`, `audio/NN.wav`; borra el vídeo descargado (`raw/`) al terminar.
  - `tests/builders.py`: `make_job`, `make_ctx`, `make_meta`, `make_fetch`, `make_lugar`, `make_cosa`, `make_extraction`, `make_geo` (usados en tareas posteriores).

- [ ] **Step 1: Write the builders and the failing test**

`tests/builders.py`:

```python
from datetime import UTC, datetime
from pathlib import Path

from japan_reader.context import JobContext
from japan_reader.models import ContentType, Cosa, Extraction, FetchResult, GeoMatch, Lugar, Otro, SourceMeta
from japan_reader.sources import ContentHint, Platform
from japan_reader.state import Job, JobStatus


def make_job(bookmark_id="b1", url="https://www.youtube.com/shorts/abc", platform=Platform.YOUTUBE, hint=ContentHint.VIDEO) -> Job:
    now = datetime(2026, 9, 28, tzinfo=UTC)
    return Job(
        bookmark_id=bookmark_id, url=url, platform=platform, hint=hint, status=JobStatus.PENDING, attempts=0,
        next_attempt_at=None, last_error=None, outcome=None, created_at=now, updated_at=now,
    )


def make_ctx(tmp_path: Path, job: Job | None = None, **results) -> JobContext:
    job = job or make_job()
    workdir = tmp_path / "jobs" / job.bookmark_id
    workdir.mkdir(parents=True, exist_ok=True)
    return JobContext(job=job, workdir=workdir, results=dict(results))


def make_meta(**overrides) -> SourceMeta:
    base = {
        "url": "https://www.youtube.com/shorts/abc", "platform": Platform.YOUTUBE, "content_type": ContentType.VIDEO,
        "title": "Ramen en Tokio", "author": "viajero", "published": "2026-08-01",
    }
    return SourceMeta(**(base | overrides))


def make_fetch(**overrides) -> FetchResult:
    return FetchResult(**({"meta": make_meta()} | overrides))


def make_lugar(nombre="Ichiran Shibuya", **overrides) -> Lugar:
    base = {
        "nombre": nombre, "nombre_local": None, "consulta_busqueda": f"{nombre} Tokyo", "ciudad": "Tokio",
        "region": "Kanto", "categoria": "comida", "que_es": f"Ramen en {nombre}", "que_hacer": "Pedir tonkotsu",
        "consejos": ["Ir pronto"], "precio_aprox": "¥1000", "confianza": 0.9,
    }
    return Lugar(**(base | overrides))


def make_cosa(nombre="CoCo Ichibanya", **overrides) -> Cosa:
    base = {
        "nombre": nombre, "categoria": "cadenas", "que_es": "Curry japonés", "consejos": ["Elige el picante"],
        "donde": ["Por todo Japón"], "donde_lugares": [], "confianza": 0.9,
    }
    return Cosa(**(base | overrides))


def make_extraction(confianza_japon=0.95, lugares=(), cosas=(), otros=()) -> Extraction:
    return Extraction(
        relacionado_japon=confianza_japon >= 0.5, confianza_japon=confianza_japon, idioma="es",
        resumen_fuente="Un vídeo sobre Tokio", lugares=list(lugares), cosas=list(cosas),
        otros=[o if isinstance(o, Otro) else Otro(**o) for o in otros],
    )


def make_geo(place_id="P1", name="Ichiran Shibuya", address="Jinnan, Shibuya, Tokio 150-0041, Japón", lat=35.66, lng=139.70) -> GeoMatch:
    return GeoMatch(place_id=place_id, name=name, address=address, lat=lat, lng=lng, maps_url=f"https://maps.google.com/?cid={place_id}")
```

`tests/unit/test_fetch.py`:

```python
import pytest
from PIL import Image

from builders import make_ctx, make_job
from fakes import FakeKarakeep
from helpers import make_image, make_video
from japan_reader.clients.karakeep import Bookmark
from japan_reader.errors import PermanentError, TransientError
from japan_reader.media.downloaders import DownloadedMedia
from japan_reader.models import ContentType, SourceMeta
from japan_reader.sources import ContentHint, Platform
from japan_reader.stages.fetch import FetchStage


class StubVideo:
    def __init__(self, error=None):
        self.error = error

    def download(self, url, platform, dest):
        if self.error:
            raise self.error
        video = make_video(dest / "video.mp4")
        meta = SourceMeta(url=url, platform=platform, content_type=ContentType.VIDEO, title="Vídeo")
        return DownloadedMedia(meta=meta, videos=[video], subtitles="hola")


class StubPost:
    def __init__(self, count=3):
        self.count = count

    def download(self, url, dest):
        images = [make_image(dest / f"{i:02}.jpg") for i in range(self.count)]
        meta = SourceMeta(url=url, platform=Platform.INSTAGRAM, content_type=ContentType.CAROUSEL, description="caption")
        return DownloadedMedia(meta=meta, images=images)


IG_REEL = make_job(url="https://www.instagram.com/reel/X/", platform=Platform.INSTAGRAM, hint=ContentHint.VIDEO)
IG_POST = make_job(url="https://www.instagram.com/p/X/", platform=Platform.INSTAGRAM, hint=ContentHint.POST)


def test_video_produces_audio_and_keyframes_and_removes_video(tmp_path, settings):
    ctx = make_ctx(tmp_path)

    result = FetchStage(settings, StubVideo(), StubPost(), FakeKarakeep()).run(ctx)

    assert result.audio_files == ["audio/00.wav"]
    assert len(result.keyframes) == 3
    assert all((ctx.workdir / f).exists() for f in result.keyframes)
    assert result.subtitles == "hola"
    assert result.images == []
    assert not (ctx.workdir / "raw").exists()


def test_keyframes_can_be_disabled(tmp_path, settings):
    s = settings.model_copy(update={"reel_keyframes_enabled": False})
    result = FetchStage(s, StubVideo(), StubPost(), FakeKarakeep()).run(make_ctx(tmp_path))
    assert result.keyframes == []
    assert result.audio_files == ["audio/00.wav"]


def test_post_images_are_capped_and_resized(tmp_path, settings):
    ctx = make_ctx(tmp_path, job=IG_POST)

    result = FetchStage(settings, StubVideo(), StubPost(count=12), FakeKarakeep()).run(ctx)

    assert len(result.images) == 10
    with Image.open(ctx.workdir / result.images[0]) as im:
        assert max(im.size) == 1024
    assert result.meta.content_type == ContentType.CAROUSEL


def test_instagram_falls_back_to_karakeep_video(tmp_path, settings):
    video_bytes = make_video(tmp_path / "src.mp4").read_bytes()
    karakeep = FakeKarakeep([Bookmark(id="b1", url=IG_REEL.url, title="Desde Karakeep", video_asset_id="a1")])
    karakeep.assets["a1"] = video_bytes

    result = FetchStage(settings, StubVideo(PermanentError("login required")), StubPost(), karakeep).run(make_ctx(tmp_path, job=IG_REEL))

    assert result.meta.title == "Desde Karakeep"
    assert result.audio_files == ["audio/00.wav"]


def test_instagram_without_fallback_reraises(tmp_path, settings):
    karakeep = FakeKarakeep([Bookmark(id="b1", url=IG_REEL.url)])
    with pytest.raises(PermanentError):
        FetchStage(settings, StubVideo(PermanentError("login required")), StubPost(), karakeep).run(make_ctx(tmp_path, job=IG_REEL))


def test_youtube_permanent_error_has_no_fallback(tmp_path, settings):
    with pytest.raises(PermanentError):
        FetchStage(settings, StubVideo(PermanentError("Private video")), StubPost(), FakeKarakeep()).run(make_ctx(tmp_path))


def test_transient_error_is_not_masked_by_fallback(tmp_path, settings):
    karakeep = FakeKarakeep([Bookmark(id="b1", url=IG_REEL.url, video_asset_id="a1")])
    with pytest.raises(TransientError):
        FetchStage(settings, StubVideo(TransientError("timeout")), StubPost(), karakeep).run(make_ctx(tmp_path, job=IG_REEL))


def test_job_without_platform_is_permanent_error(tmp_path, settings):
    job = make_job(url="https://tiktok.com/x", platform=None, hint=None)
    with pytest.raises(PermanentError, match="no soportada"):
        FetchStage(settings, StubVideo(), StubPost(), FakeKarakeep()).run(make_ctx(tmp_path, job=job))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_fetch.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'japan_reader.stages.fetch'`

- [ ] **Step 3: Write minimal implementation**

`src/japan_reader/stages/fetch.py`:

```python
import logging
import shutil
from pathlib import Path

from japan_reader.clients.karakeep import KarakeepClient
from japan_reader.config import Settings
from japan_reader.context import JobContext
from japan_reader.errors import JapanReaderError, PermanentError
from japan_reader.media.audio import extract_audio
from japan_reader.media.downloaders import DownloadedMedia, GalleryDlDownloader, YtDlpDownloader
from japan_reader.media.images import resize_image
from japan_reader.media.keyframes import extract_keyframes
from japan_reader.models import ContentType, FetchResult, SourceMeta
from japan_reader.sources import ContentHint, Platform
from japan_reader.state import Job

log = logging.getLogger(__name__)


class FetchStage:
    """Etapa 2: descarga medios y metadatos y los deja listos para transcribir y extraer."""

    name = "fetch"
    result_model = FetchResult

    def __init__(
        self,
        settings: Settings,
        ytdlp: YtDlpDownloader,
        gallery: GalleryDlDownloader,
        karakeep: KarakeepClient,
        keyframer=extract_keyframes,
        audio_extractor=extract_audio,
    ) -> None:
        self._settings = settings
        self._ytdlp = ytdlp
        self._gallery = gallery
        self._karakeep = karakeep
        self._keyframer = keyframer
        self._audio = audio_extractor

    def run(self, ctx: JobContext) -> FetchResult:
        for sub in ("raw", "images", "frames", "audio"):
            shutil.rmtree(ctx.workdir / sub, ignore_errors=True)
        raw = ctx.workdir / "raw"
        media = self._download(ctx.job, raw)
        s = self._settings

        images = [
            resize_image(path, ctx.workdir / "images" / f"{i:02}.jpg", s.image_max_side)
            for i, path in enumerate(media.images[: s.post_images_max])
        ]
        audio: list[Path] = []
        frames: list[Path] = []
        for i, video in enumerate(media.videos):
            track = self._audio(video, ctx.workdir / "audio" / f"{i:02}.wav")
            if track:
                audio.append(track)
            if s.reel_keyframes_enabled:
                for j, frame in enumerate(self._keyframer(video, raw / f"frames{i:02}", s.keyframes_max)):
                    frames.append(resize_image(frame, ctx.workdir / "frames" / f"{i:02}_{j:02}.jpg", s.image_max_side))
        shutil.rmtree(raw, ignore_errors=True)

        def rel(path: Path) -> str:
            return str(path.relative_to(ctx.workdir))

        log.info(
            "bookmark=%s fetch tipo=%s imagenes=%d fotogramas=%d audios=%d",
            ctx.job.bookmark_id, media.meta.content_type, len(images), len(frames), len(audio),
        )
        return FetchResult(
            meta=media.meta,
            audio_files=[rel(p) for p in audio],
            subtitles=media.subtitles,
            images=[rel(p) for p in images],
            keyframes=[rel(p) for p in frames],
        )

    def _download(self, job: Job, raw: Path) -> DownloadedMedia:
        if job.platform is None or job.hint is None:
            raise PermanentError("fuente no soportada")
        try:
            if job.hint == ContentHint.VIDEO:
                return self._ytdlp.download(job.url, job.platform, raw)
            return self._gallery.download(job.url, raw)
        except PermanentError as exc:
            if job.platform != Platform.INSTAGRAM:
                raise
            fallback = self._from_karakeep(job, raw)
            if fallback is None:
                raise
            log.warning("bookmark=%s descarga fallida (%s); uso los medios archivados por Karakeep", job.bookmark_id, exc)
            return fallback

    def _from_karakeep(self, job: Job, raw: Path) -> DownloadedMedia | None:
        try:
            bookmark = self._karakeep.get_bookmark(job.bookmark_id)

            def meta(content_type: ContentType) -> SourceMeta:
                return SourceMeta(
                    url=job.url, platform=job.platform, content_type=content_type,
                    title=bookmark.title, description=bookmark.description, author=bookmark.author,
                )

            if bookmark.video_asset_id:
                video = self._karakeep.download_asset(bookmark.video_asset_id, raw / "karakeep_video.mp4")
                return DownloadedMedia(meta=meta(ContentType.VIDEO), videos=[video])
            if bookmark.image_asset_id:
                image = self._karakeep.download_asset(bookmark.image_asset_id, raw / "karakeep_image.jpg")
                return DownloadedMedia(meta=meta(ContentType.IMAGE), images=[image])
        except JapanReaderError as exc:
            log.warning("bookmark=%s no se pudo usar el respaldo de Karakeep: %s", job.bookmark_id, exc)
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_fetch.py -v`
Expected: all passed

- [ ] **Step 5: Write stage doc**

`docs/pipeline/02-fetch.md`:

```markdown
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
```

- [ ] **Step 6: Commit**

```bash
git add src/japan_reader/stages/fetch.py tests/builders.py tests/unit/test_fetch.py docs/pipeline/02-fetch.md
git commit -m "feat: fetch stage with keyframes, image limits and Karakeep fallback"
```

---

### Task 9: Etapa `transcribe` (+ documentación 03)

**Files:**
- Create: `src/japan_reader/stages/transcribe.py`, `docs/pipeline/03-transcribe.md`
- Test: `tests/unit/test_transcribe.py`

**Interfaces:**
- Consumes: `FetchResult`, `Transcript` (Tarea 2); `JobContext`.
- Produces: `Transcriber` (Protocol: `transcribe(audio: Path) -> tuple[str, str | None]`), `WhisperTranscriber(model_name, compute_type, download_root: Path, threads: int)`, `TranscribeStage(transcriber)` con `name = "transcribe"`, `result_model = Transcript`, `run(ctx) -> Transcript`, `MIN_SUBTITLE_WORDS = 5`.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_transcribe.py`:

```python
from builders import make_ctx, make_fetch
from japan_reader.stages.transcribe import TranscribeStage


class FakeTranscriber:
    def __init__(self):
        self.calls = []

    def transcribe(self, audio):
        self.calls.append(audio.name)
        return f"texto de {audio.name}", "ja"


def _ctx_with_audio(tmp_path, names, **fetch_kwargs):
    ctx = make_ctx(tmp_path)
    for name in names:
        path = ctx.workdir / "audio" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"wav")
    ctx.results["fetch"] = make_fetch(audio_files=[f"audio/{n}" for n in names], **fetch_kwargs)
    return ctx


def test_manual_subtitles_are_used_when_long_enough(tmp_path):
    transcriber = FakeTranscriber()
    ctx = _ctx_with_audio(tmp_path, ["00.wav"], subtitles="uno dos tres cuatro cinco seis")

    result = TranscribeStage(transcriber).run(ctx)

    assert result.origin == "subtitulos"
    assert result.text == "uno dos tres cuatro cinco seis"
    assert transcriber.calls == []
    assert not (ctx.workdir / "audio" / "00.wav").exists()


def test_whisper_when_no_useful_subtitles(tmp_path):
    ctx = _ctx_with_audio(tmp_path, ["00.wav"], subtitles="hola")

    result = TranscribeStage(FakeTranscriber()).run(ctx)

    assert result.origin == "whisper"
    assert result.text == "texto de 00.wav"
    assert result.language == "ja"
    assert not (ctx.workdir / "audio" / "00.wav").exists()


def test_carousel_with_several_videos_is_labelled(tmp_path):
    ctx = _ctx_with_audio(tmp_path, ["00.wav", "01.wav"])

    result = TranscribeStage(FakeTranscriber()).run(ctx)

    assert result.text == "[Elemento 1] texto de 00.wav\n[Elemento 2] texto de 01.wav"


def test_no_audio_is_skipped(tmp_path):
    ctx = make_ctx(tmp_path, fetch=make_fetch(images=["images/00.jpg"]))
    result = TranscribeStage(FakeTranscriber()).run(ctx)
    assert result.origin == "none" and result.text == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_transcribe.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'japan_reader.stages.transcribe'`

- [ ] **Step 3: Write minimal implementation**

`src/japan_reader/stages/transcribe.py`:

```python
import logging
from pathlib import Path
from typing import Protocol

from japan_reader.context import JobContext
from japan_reader.models import FetchResult, Transcript

log = logging.getLogger(__name__)

MIN_SUBTITLE_WORDS = 5


class Transcriber(Protocol):
    def transcribe(self, audio: Path) -> tuple[str, str | None]: ...


class WhisperTranscriber:
    """faster-whisper en CPU. El modelo se carga la primera vez que se usa."""

    def __init__(self, model_name: str, compute_type: str, download_root: Path, threads: int) -> None:
        self._name = model_name
        self._compute_type = compute_type
        self._download_root = download_root
        self._threads = threads
        self._model = None

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            log.info("cargando modelo whisper %s (%s)", self._name, self._compute_type)
            self._model = WhisperModel(
                self._name,
                device="cpu",
                compute_type=self._compute_type,
                cpu_threads=self._threads,
                download_root=str(self._download_root),
            )
        return self._model

    def transcribe(self, audio: Path) -> tuple[str, str | None]:
        segments, info = self._load().transcribe(str(audio), vad_filter=True, beam_size=5)
        text = " ".join(segment.text.strip() for segment in segments).strip()
        return text, info.language


class TranscribeStage:
    """Etapa 3: texto del audio (subtítulos manuales o Whisper). Borra el audio al terminar."""

    name = "transcribe"
    result_model = Transcript

    def __init__(self, transcriber: Transcriber) -> None:
        self._transcriber = transcriber

    def run(self, ctx: JobContext) -> Transcript:
        fetch = ctx.result("fetch", FetchResult)
        audio = [ctx.workdir / rel for rel in fetch.audio_files]
        if fetch.subtitles and len(fetch.subtitles.split()) >= MIN_SUBTITLE_WORDS:
            result = Transcript(text=fetch.subtitles, origin="subtitulos")
        elif not audio:
            result = Transcript(origin="none")
        else:
            parts: list[str] = []
            language: str | None = None
            for i, path in enumerate(audio):
                text, lang = self._transcriber.transcribe(path)
                language = language or lang
                parts.append(f"[Elemento {i + 1}] {text}" if len(audio) > 1 else text)
            result = Transcript(text="\n".join(parts).strip(), language=language, origin="whisper")
        for path in audio:
            path.unlink(missing_ok=True)
        log.info("bookmark=%s transcripcion origen=%s palabras=%d", ctx.job.bookmark_id, result.origin, len(result.text.split()))
        return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_transcribe.py -v`
Expected: all passed

- [ ] **Step 5: Write stage doc**

`docs/pipeline/03-transcribe.md`:

```markdown
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
```

- [ ] **Step 6: Commit**

```bash
git add src/japan_reader/stages/transcribe.py tests/unit/test_transcribe.py docs/pipeline/03-transcribe.md
git commit -m "feat: transcribe stage with subtitles preference and faster-whisper"
```

---

### Task 10: Cliente OpenRouter, prompts y etapa `extract` (+ documentación 04)

**Files:**
- Create: `src/japan_reader/clients/openrouter.py`, `src/japan_reader/prompts/__init__.py`, `src/japan_reader/prompts/extract.md`, `src/japan_reader/prompts/merge.md`, `src/japan_reader/stages/extract.py`, `docs/pipeline/04-extract.md`
- Modify: `tests/fakes.py` (añadir `FakeLLM`)
- Test: `tests/unit/test_openrouter_client.py`, `tests/unit/test_extract.py`

**Interfaces:**
- Consumes: `send` (Tarea 4); `Extraction`, `ExtractResult`, `FetchResult`, `Transcript` (Tarea 2); `DailyQuota` (Tarea 3); `strip_fences` (Tarea 2).
- Produces:
  - `ChatResult(content: str, cost_usd: float)`; `OpenRouterClient(api_key, http=None)` con `chat_json(model, messages, schema, schema_name) -> ChatResult` y `model_supports_images(model) -> bool`; `image_part(path: Path) -> dict`.
  - `prompts.load_prompt(name: str) -> str` (`"extract"`, `"merge"`).
  - `ExtractStage(settings, llm, budget)` con `name = "extract"`, `result_model = ExtractResult`, `run(ctx) -> ExtractResult`; `build_user_text(fetch, transcript) -> str`.
  - `tests/fakes.py`: `FakeLLM(responses: list[str], cost=0.001, images=True)` con `.calls: list[dict]`.

- [ ] **Step 1: Write the failing client test**

`tests/unit/test_openrouter_client.py`:

```python
import json

import httpx
import respx

from helpers import make_image
from japan_reader.clients.openrouter import OpenRouterClient, image_part

HOST = "openrouter.ai"


@respx.mock
def test_chat_json_sends_schema_and_returns_cost():
    route = respx.post(host=HOST, path="/api/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": '{"a": 1}'}}], "usage": {"cost": 0.0123}})
    )

    result = OpenRouterClient("key").chat_json("vision/model", [{"role": "user", "content": "hola"}], {"type": "object"}, "extraction")

    assert result.content == '{"a": 1}'
    assert result.cost_usd == 0.0123
    body = json.loads(route.calls[0].request.content)
    assert body["model"] == "vision/model"
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["name"] == "extraction"
    assert body["provider"] == {"require_parameters": True}
    assert body["usage"] == {"include": True}
    assert route.calls[0].request.headers["Authorization"] == "Bearer key"


@respx.mock
def test_model_supports_images():
    respx.get(host=HOST, path="/api/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [
            {"id": "vision/model", "architecture": {"input_modalities": ["text", "image"]}},
            {"id": "text/model", "architecture": {"input_modalities": ["text"]}},
        ]})
    )
    client = OpenRouterClient("key")
    assert client.model_supports_images("vision/model") is True
    assert client.model_supports_images("text/model") is False
    assert client.model_supports_images("missing/model") is False


def test_image_part_is_data_url(tmp_path):
    part = image_part(make_image(tmp_path / "a.jpg", size=(10, 10)))
    assert part["type"] == "image_url"
    assert part["image_url"]["url"].startswith("data:image/jpeg;base64,")
```

- [ ] **Step 2: Add `FakeLLM` and write the failing stage test**

Añade a `tests/fakes.py` (el import junto a los demás, arriba; la clase al final):

```python
from japan_reader.clients.openrouter import ChatResult


class FakeLLM:
    """OpenRouter falso: devuelve las respuestas en orden y registra las llamadas."""

    def __init__(self, responses: list[str], cost: float = 0.001, images: bool = True) -> None:
        self.responses = list(responses)
        self.cost = cost
        self.images = images
        self.calls: list[dict] = []

    def chat_json(self, model, messages, schema, schema_name) -> ChatResult:
        self.calls.append({"model": model, "messages": messages, "schema_name": schema_name})
        return ChatResult(content=self.responses.pop(0), cost_usd=self.cost)

    def model_supports_images(self, model: str) -> bool:
        return self.images
```

`tests/unit/test_extract.py`:

```python
import json

import pytest

from builders import make_ctx, make_fetch, make_lugar
from fakes import FakeLLM
from helpers import make_image
from japan_reader.errors import QuotaExceeded
from japan_reader.models import Transcript
from japan_reader.quota import DailyQuota
from japan_reader.stages.extract import ExtractStage, build_user_text
from japan_reader.state import StateStore

VALID = json.dumps({
    "relacionado_japon": True,
    "confianza_japon": 0.9,
    "idioma": "es",
    "resumen_fuente": "Ramen en Shibuya",
    "lugares": [make_lugar().model_dump()],
    "cosas": [],
    "otros": [],
})


@pytest.fixture
def state(tmp_path):
    return StateStore(tmp_path / "state.db")


def _ctx(tmp_path, images=0, frames=0):
    ctx = make_ctx(tmp_path)
    image_paths = [f"images/{i:02}.jpg" for i in range(images)]
    frame_paths = [f"frames/00_{i:02}.jpg" for i in range(frames)]
    for rel in image_paths + frame_paths:
        make_image(ctx.workdir / rel, size=(10, 10))
    ctx.results["fetch"] = make_fetch(images=image_paths, keyframes=frame_paths)
    ctx.results["transcribe"] = Transcript(text="Hoy comemos en Ichiran", origin="whisper")
    return ctx


def _stage(settings, llm, state, limit=1.0):
    return ExtractStage(settings, llm, DailyQuota(state, "openrouter_usd", limit))


def test_valid_extraction_with_images_uses_vision_model(tmp_path, settings, state):
    llm = FakeLLM([VALID], cost=0.01)

    result = _stage(settings, llm, state).run(_ctx(tmp_path, images=1, frames=2))

    assert result.extraction.lugares[0].nombre == "Ichiran Shibuya"
    assert result.cost_usd == 0.01
    assert llm.calls[0]["model"] == "vision/model"
    user_content = llm.calls[0]["messages"][1]["content"]
    assert sum(1 for part in user_content if part["type"] == "image_url") == 3
    assert state.get_counter("openrouter_usd") == 0.01


def test_without_images_uses_text_model(tmp_path, settings, state):
    llm = FakeLLM([VALID])
    _stage(settings, llm, state).run(_ctx(tmp_path))
    assert llm.calls[0]["model"] == "text/model"


def test_fenced_json_is_accepted(tmp_path, settings, state):
    result = _stage(settings, FakeLLM([f"```json\n{VALID}\n```"]), state).run(_ctx(tmp_path))
    assert result.extraction is not None


def test_invalid_then_valid_retries_once_with_error(tmp_path, settings, state):
    llm = FakeLLM(['{"relacionado_japon": true}', VALID])

    result = _stage(settings, llm, state).run(_ctx(tmp_path))

    assert result.extraction is not None
    assert len(llm.calls) == 2
    retry_messages = llm.calls[1]["messages"]
    assert retry_messages[-2]["role"] == "assistant"
    assert "no cumple el esquema" in retry_messages[-1]["content"]


def test_invalid_twice_returns_error(tmp_path, settings, state):
    result = _stage(settings, FakeLLM(["no json", "tampoco"]), state).run(_ctx(tmp_path))
    assert result.extraction is None
    assert result.error


def test_budget_exceeded_blocks_call(tmp_path, settings, state):
    state.add_counter("openrouter_usd", 5)
    llm = FakeLLM([VALID])
    with pytest.raises(QuotaExceeded):
        _stage(settings, llm, state, limit=1.0).run(_ctx(tmp_path))
    assert llm.calls == []


def test_build_user_text_mentions_everything():
    fetch = make_fetch(images=["images/00.jpg"], keyframes=["frames/00_00.jpg", "frames/00_01.jpg"])
    fetch.meta.hashtags = ["tokyo"]
    fetch.meta.description = "Mi caption"
    text = build_user_text(fetch, Transcript(text="audio", origin="whisper"))
    assert "Mi caption" in text and "audio" in text and "#tokyo" in text
    assert "1 imágenes del post" in text and "2 fotogramas" in text
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_openrouter_client.py tests/unit/test_extract.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'japan_reader.clients.openrouter'`

- [ ] **Step 4: Write the client and prompts**

`src/japan_reader/clients/openrouter.py`:

```python
import base64
from pathlib import Path

import httpx
from pydantic import BaseModel

from japan_reader.clients.http import send
from japan_reader.errors import TransientError

BASE_URL = "https://openrouter.ai/api/v1"


class ChatResult(BaseModel):
    content: str
    cost_usd: float


def image_part(path: Path) -> dict:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}}


class OpenRouterClient:
    SERVICE = "openrouter"

    def __init__(self, api_key: str, http: httpx.Client | None = None) -> None:
        self._http = http or httpx.Client(timeout=180)
        self._headers = {"Authorization": f"Bearer {api_key}", "X-Title": "japan-reader"}

    def chat_json(self, model: str, messages: list[dict], schema: dict, schema_name: str) -> ChatResult:
        body = {
            "model": model,
            "messages": messages,
            "temperature": 0.2,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": False, "schema": schema},
            },
            "provider": {"require_parameters": True},
            "usage": {"include": True},
        }
        data = send(self._http, "POST", f"{BASE_URL}/chat/completions", self.SERVICE, headers=self._headers, json=body).json()
        if data.get("error"):
            raise TransientError(f"openrouter: {data['error']}")
        content = data["choices"][0]["message"].get("content") or ""
        cost = float((data.get("usage") or {}).get("cost") or 0.0)
        return ChatResult(content=content, cost_usd=cost)

    def model_supports_images(self, model: str) -> bool:
        data = send(self._http, "GET", f"{BASE_URL}/models", self.SERVICE, headers=self._headers).json()
        for entry in data.get("data", []):
            if entry.get("id") == model:
                return "image" in (entry.get("architecture") or {}).get("input_modalities", [])
        return False
```

`src/japan_reader/prompts/__init__.py`:

```python
from importlib.resources import files


def load_prompt(name: str) -> str:
    return files("japan_reader.prompts").joinpath(f"{name}.md").read_text(encoding="utf-8")
```

`src/japan_reader/prompts/extract.md`:

```markdown
Eres un asistente que analiza contenido corto de redes sociales (YouTube Shorts, Reels y posts de Instagram) para construir una base de datos con la que planificar un viaje a Japón.

Recibirás: metadatos (plataforma, tipo, título, autor, hashtags), la descripción o caption, la transcripción del audio (puede estar vacía) y, a veces, imágenes (imágenes del post o fotogramas clave del vídeo).

Tu tarea:

1. Decide si el contenido trata sobre Japón (lugares, comida, compras o cultura de Japón). `confianza_japon` es la probabilidad (0-1) de que trate sobre Japón. `relacionado_japon` = `confianza_japon` >= 0.5.
2. Extrae cada LUGAR concreto que se pueda visitar: un sitio con ubicación física identificable (templo, santuario, restaurante concreto, tienda concreta, mirador, barrio, onsen, museo...).
   - `nombre`: nombre habitual en alfabeto latino. `nombre_local`: nombre en japonés si aparece o si lo conoces con seguridad; si no, null.
   - `consulta_busqueda`: la mejor consulta para encontrarlo en Google Maps: nombre + barrio o ciudad (p. ej. "Ichiran Shibuya Tokyo").
   - `ciudad` en español (Tokio, Kioto, Osaka, Nara...), `region` (Kanto, Kansai...), `categoria` (una de la lista de abajo).
   - `que_es`: 1-2 frases. `que_hacer`: qué hacer, ver o pedir allí (vacío si no se dice). `consejos`: consejos prácticos mencionados (horario, reservas, colas, cómo llegar). `precio_aprox` si se menciona.
   - `confianza`: tu seguridad (0-1) de que el lugar está bien identificado.
3. Extrae cada COSA sin ubicación concreta: productos, souvenirs, platos, cadenas de comida o de tiendas con muchos locales (Yoshinoya, CoCo Ichibanya, Don Quijote en general...).
   - `categoria`: souvenirs | comida | cadenas | cosmetica | otros. `donde`: dónde se consigue, en texto libre ("cualquier konbini", "Don Quijote").
   - Si el contenido recomienda un local CONCRETO para esa cosa (p. ej. "el Don Quijote de Shibuya"), añade ese local también a `lugares` y pon su `nombre` exacto en `donde_lugares`.
4. Lo que no sea lugar ni cosa (cultura, costumbres, curiosidades, consejos generales de viaje) va a `otros`, con `titulo` y `contenido`.
5. `resumen_fuente`: 1-3 frases sobre lo que cuenta el contenido.

Reglas:

- Lee el texto que aparece en las imágenes (rótulos, nombres de locales, texto sobreimpreso) y contrástalo con la transcripción y la caption. A menudo el nombre del lugar solo aparece escrito en pantalla.
- No inventes lugares ni datos. Si algo no aparece y no lo sabes con seguridad, usa null o una lista vacía y baja la `confianza`.
- Cada lugar y cada cosa, una sola vez.
- Escribe en español, salvo los nombres propios y `nombre_local`.
- Si el contenido trata sobre Japón, incluye al menos un elemento en `lugares`, `cosas` u `otros`.
- Responde únicamente con el JSON que cumple el esquema, sin texto adicional.

Categorías de lugar: templo, santuario, comida, cafe, bar, tienda, mercado, mirador, barrio, museo, parque, onsen, alojamiento, transporte, otro.
```

`src/japan_reader/prompts/merge.md`:

```markdown
Mantienes las notas de una base de datos para un viaje a Japón. Recibirás un JSON con el contenido actual de una nota ("actual": resumen, que_hacer, consejos) y la información de una nueva fuente sobre el mismo elemento ("nuevo").

Devuelve un JSON con `resumen`, `que_hacer` y `consejos` actualizados:

- Integra la información nueva sin perder la existente. No repitas ideas.
- `resumen`: 2-4 frases. `que_hacer`: texto breve (vacío si no aplica). `consejos`: lista sin duplicados, frases cortas.
- No inventes nada que no esté en "actual" o en "nuevo". Escribe en español.
- Responde únicamente con el JSON.
```

- [ ] **Step 5: Write the stage**

`src/japan_reader/stages/extract.py`:

```python
import logging

from pydantic import ValidationError

from japan_reader.clients.openrouter import OpenRouterClient, image_part
from japan_reader.config import Settings
from japan_reader.context import JobContext
from japan_reader.models import Extraction, ExtractResult, FetchResult, Transcript
from japan_reader.prompts import load_prompt
from japan_reader.quota import DailyQuota
from japan_reader.text import strip_fences

log = logging.getLogger(__name__)


def build_user_text(fetch: FetchResult, transcript: Transcript) -> str:
    meta = fetch.meta
    lines = [f"Plataforma: {meta.platform}", f"Tipo de contenido: {meta.content_type}"]
    if meta.title:
        lines.append(f"Título: {meta.title}")
    if meta.author:
        lines.append(f"Autor: {meta.author}")
    if meta.published:
        lines.append(f"Fecha: {meta.published}")
    if meta.hashtags:
        lines.append("Hashtags: " + " ".join(f"#{tag}" for tag in meta.hashtags))
    lines.append("Descripción / caption:\n" + (meta.description or "(vacía)"))
    lines.append("Transcripción del audio:\n" + (transcript.text or "(sin audio o sin transcripción)"))
    if fetch.images or fetch.keyframes:
        lines.append(
            f"Se adjuntan {len(fetch.images)} imágenes del post y {len(fetch.keyframes)} fotogramas clave del vídeo. "
            "Lee el texto que aparezca en ellas."
        )
    return "\n\n".join(lines)


class ExtractStage:
    """Etapa 4: clasificación y extracción estructurada con un LLM multimodal."""

    name = "extract"
    result_model = ExtractResult

    def __init__(self, settings: Settings, llm: OpenRouterClient, budget: DailyQuota) -> None:
        self._settings = settings
        self._llm = llm
        self._budget = budget

    def run(self, ctx: JobContext) -> ExtractResult:
        fetch = ctx.result("fetch", FetchResult)
        transcript = ctx.result("transcribe", Transcript)
        image_paths = [ctx.workdir / rel for rel in fetch.images + fetch.keyframes]
        model = self._settings.openrouter_model if image_paths else self._settings.text_model
        content = [{"type": "text", "text": build_user_text(fetch, transcript)}] + [image_part(p) for p in image_paths]
        messages: list[dict] = [
            {"role": "system", "content": load_prompt("extract")},
            {"role": "user", "content": content},
        ]
        schema = Extraction.model_json_schema()
        cost = 0.0
        error = ""
        for _ in range(2):
            self._budget.check()
            result = self._llm.chat_json(model, messages, schema, "extraction")
            self._budget.add(result.cost_usd)
            cost += result.cost_usd
            try:
                extraction = Extraction.model_validate_json(strip_fences(result.content))
            except ValidationError as exc:
                error = str(exc)
                messages = [
                    *messages,
                    {"role": "assistant", "content": result.content},
                    {"role": "user", "content": f"La respuesta no cumple el esquema:\n{error}\nDevuelve únicamente el JSON corregido."},
                ]
                continue
            log.info(
                "bookmark=%s extraccion japon=%.2f lugares=%d cosas=%d otros=%d coste=%.4f",
                ctx.job.bookmark_id, extraction.confianza_japon, len(extraction.lugares),
                len(extraction.cosas), len(extraction.otros), cost,
            )
            return ExtractResult(extraction=extraction, cost_usd=cost)
        log.warning("bookmark=%s extraccion fallida: %s", ctx.job.bookmark_id, error[:200])
        return ExtractResult(extraction=None, error=error, cost_usd=cost)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_openrouter_client.py tests/unit/test_extract.py -v`
Expected: all passed

- [ ] **Step 7: Write stage doc**

`docs/pipeline/04-extract.md`:

```markdown
# Etapa 4 — extract

**Qué hace:** decide si el contenido es de Japón y extrae lugares, cosas y otros datos en JSON estructurado.

**Entrada:** metadatos, caption, hashtags, transcripción, imágenes del post y fotogramas clave.
**Salida:** `ExtractResult {extraction | None, error, cost_usd}`. Esquema `Extraction` (spec §5.4, más `que_hacer` en cada lugar).

**Modelo:** `OPENROUTER_MODEL` (multimodal; se comprueba al arrancar) si hay imágenes; `OPENROUTER_TEXT_MODEL` (o el mismo) si no las hay. Petición con `response_format=json_schema`, `provider.require_parameters=true` y `usage.include=true` para conocer el coste real.

**Prompt:** `src/japan_reader/prompts/extract.md` (versionado con el código). Pide leer el texto de las imágenes y contrastarlo con el audio.

**Validación:** Pydantic. Si el JSON no valida, un reintento con el error incluido. Si vuelve a fallar → `extraction=None` y `resolve` crea una nota de revisión `extraccion-fallida`.

**Coste:** cada llamada suma su coste al contador diario `openrouter_usd`; si se supera `OPENROUTER_DAILY_BUDGET_USD`, el job espera al día siguiente (`QuotaExceeded`) y se avisa por ntfy.

**Fallos:** 401/402/403 → `ConfigError` (clave inválida o sin saldo); 429/5xx/timeout → reintento.

**Cómo probarla:** `uv run pytest tests/unit/test_extract.py tests/unit/test_openrouter_client.py`. Con modelos reales: `japan-reader eval` (ver `docs/operations.md`).
```

- [ ] **Step 8: Commit**

```bash
git add src/japan_reader tests docs/pipeline/04-extract.md
git commit -m "feat: OpenRouter client, extraction prompt and extract stage"
```

---

### Task 11: Cliente de Google Places y etapa `geocode` (+ documentación 05)

**Files:**
- Create: `src/japan_reader/clients/places.py`, `src/japan_reader/geo.py`, `src/japan_reader/stages/geocode.py`, `docs/pipeline/05-geocode.md`
- Test: `tests/unit/test_places_client.py`, `tests/unit/test_geocode.py`

**Interfaces:**
- Consumes: `send`, `ApiError`; `GeoMatch`, `GeoOutcome`, `GeocodeResult`, `Lugar`, `ExtractResult`; `DailyQuota`; `japan_decision`; `fold`, `normalize_name`, `similarity`; `Thresholds`.
- Produces:
  - `PlacesClient(api_key, http=None)` con `search(query: str) -> list[GeoMatch]`; constante `FIELD_MASK`.
  - `geo.in_japan(match) -> bool`, `geo.city_matches(match, ciudad) -> bool`, `geo.name_matches(match, lugar) -> bool`.
  - `GeocodeStage(places, quota, thresholds)` con `name = "geocode"`, `result_model = GeocodeResult`, `run(ctx) -> GeocodeResult`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_places_client.py`:

```python
import json

import httpx
import pytest
import respx

from japan_reader.clients.places import FIELD_MASK, PlacesClient
from japan_reader.errors import ApiError, ConfigError

HOST = "places.googleapis.com"
PLACE = {
    "id": "ChIJ123",
    "displayName": {"text": "Ichiran Shibuya", "languageCode": "es"},
    "formattedAddress": "1-22-7 Jinnan, Shibuya, Tokio 150-0041, Japón",
    "location": {"latitude": 35.6614, "longitude": 139.7005},
    "googleMapsUri": "https://maps.google.com/?cid=1",
    "types": ["ramen_restaurant", "restaurant"],
}


@respx.mock
def test_search_request_and_parsing():
    route = respx.post(host=HOST, path="/v1/places:searchText").mock(return_value=httpx.Response(200, json={"places": [PLACE, {"id": "no-location"}]}))

    results = PlacesClient("gkey").search("Ichiran Shibuya Tokyo")

    assert len(results) == 1
    match = results[0]
    assert (match.place_id, match.name, match.lat, match.lng) == ("ChIJ123", "Ichiran Shibuya", 35.6614, 139.7005)
    request = route.calls[0].request
    assert request.headers["X-Goog-Api-Key"] == "gkey"
    assert request.headers["X-Goog-FieldMask"] == FIELD_MASK
    assert json.loads(request.content) == {"textQuery": "Ichiran Shibuya Tokyo", "regionCode": "JP", "languageCode": "es", "pageSize": 5}


def test_field_mask_only_pro_fields():
    assert FIELD_MASK == "places.id,places.displayName,places.formattedAddress,places.location,places.googleMapsUri,places.types"


@respx.mock
def test_empty_response():
    respx.post(host=HOST, path="/v1/places:searchText").mock(return_value=httpx.Response(200, json={}))
    assert PlacesClient("gkey").search("nada") == []


@respx.mock
def test_invalid_key_is_config_error():
    respx.post(host=HOST, path="/v1/places:searchText").mock(
        return_value=httpx.Response(400, json={"error": {"message": "API key not valid. Please pass a valid API key."}})
    )
    with pytest.raises(ConfigError):
        PlacesClient("bad").search("x")


@respx.mock
def test_other_400_is_api_error():
    respx.post(host=HOST, path="/v1/places:searchText").mock(return_value=httpx.Response(400, json={"error": {"message": "bad query"}}))
    with pytest.raises(ApiError):
        PlacesClient("gkey").search("x")
```

`tests/unit/test_geocode.py`:

```python
import pytest

from builders import make_ctx, make_extraction, make_geo, make_lugar
from japan_reader.config import Thresholds
from japan_reader.errors import QuotaExceeded
from japan_reader.models import ExtractResult
from japan_reader.quota import DailyQuota
from japan_reader.stages.geocode import GeocodeStage
from japan_reader.state import StateStore

SHIBUYA = make_geo("P1", "Ichiran Shibuya", "Jinnan, Shibuya, Tokio 150-0041, Japón")
OSAKA = make_geo("P2", "Ichiran Dotonbori", "Chuo Ward, Osaka, 542-0084, Japón", lat=34.66, lng=135.50)
OTHER_TOKYO = make_geo("P3", "Ramen Nagi", "Shinjuku, Tokio, Japón")
PARIS = make_geo("P4", "Ichiran Paris", "Rue X, 75001 Paris, Francia", lat=48.85, lng=2.35)


class FakePlaces:
    def __init__(self, answers: dict[str, list]):
        self.answers = answers
        self.queries: list[str] = []

    def search(self, query):
        self.queries.append(query)
        return self.answers.get(query, [])


@pytest.fixture
def state(tmp_path):
    return StateStore(tmp_path / "state.db")


def _run(tmp_path, state, places, lugares, confianza=0.95, limit=150):
    ctx = make_ctx(tmp_path, extract=ExtractResult(extraction=make_extraction(confianza, lugares=lugares)))
    return GeocodeStage(places, DailyQuota(state, "places_calls", limit), Thresholds()).run(ctx)


def test_direct_match(tmp_path, state):
    places = FakePlaces({"Ichiran Shibuya Tokyo": [SHIBUYA]})
    result = _run(tmp_path, state, places, [make_lugar()])
    assert result.outcomes[0].match.place_id == "P1"
    assert result.outcomes[0].review_reason is None
    assert state.get_counter("places_calls") == 1


def test_filters_by_country_and_city(tmp_path, state):
    places = FakePlaces({"Ichiran Shibuya Tokyo": [PARIS, OSAKA, SHIBUYA]})
    result = _run(tmp_path, state, places, [make_lugar()])
    assert result.outcomes[0].match.place_id == "P1"


def test_city_aliases(tmp_path, state):
    kyoto = make_geo("K1", "Fushimi Inari Taisha", "68 Fukakusa Yabunouchicho, Fushimi Ward, Kyoto, 612-0882, Japan")
    places = FakePlaces({"Fushimi Inari Kyoto": [kyoto]})
    lugar = make_lugar("Fushimi Inari", consulta_busqueda="Fushimi Inari Kyoto", ciudad="Kioto")
    assert _run(tmp_path, state, places, [lugar]).outcomes[0].match.place_id == "K1"


def test_falls_back_to_local_name(tmp_path, state):
    places = FakePlaces({"一蘭 渋谷店": [SHIBUYA]})
    lugar = make_lugar(nombre_local="一蘭 渋谷店")
    result = _run(tmp_path, state, places, [lugar])
    assert places.queries == ["Ichiran Shibuya Tokyo", "一蘭 渋谷店"]
    assert result.outcomes[0].match.place_id == "P1"
    assert state.get_counter("places_calls") == 2


def test_ambiguous_when_several_unrelated_names(tmp_path, state):
    places = FakePlaces({"Tonkotsu oculto Tokyo": [OTHER_TOKYO, SHIBUYA]})
    lugar = make_lugar("Tonkotsu oculto", consulta_busqueda="Tonkotsu oculto Tokyo")
    outcome = _run(tmp_path, state, places, [lugar]).outcomes[0]
    assert outcome.match.place_id == "P3"
    assert outcome.review_reason == "geocodificacion-ambigua"


def test_japan_but_other_city_is_ambiguous(tmp_path, state):
    places = FakePlaces({"Ichiran Shibuya Tokyo": [OSAKA]})
    outcome = _run(tmp_path, state, places, [make_lugar()]).outcomes[0]
    assert outcome.match.place_id == "P2"
    assert outcome.review_reason == "geocodificacion-ambigua"


def test_nothing_in_japan_fails(tmp_path, state):
    places = FakePlaces({"Ichiran Shibuya Tokyo": [PARIS]})
    outcome = _run(tmp_path, state, places, [make_lugar()]).outcomes[0]
    assert outcome.match is None
    assert outcome.review_reason == "geocodificacion-fallida"


def test_not_japan_skips_geocoding(tmp_path, state):
    places = FakePlaces({})
    assert _run(tmp_path, state, places, [make_lugar()], confianza=0.1).outcomes == []
    assert places.queries == []


def test_quota_exceeded(tmp_path, state):
    state.add_counter("places_calls", 150)
    with pytest.raises(QuotaExceeded):
        _run(tmp_path, state, FakePlaces({}), [make_lugar()])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_places_client.py tests/unit/test_geocode.py -v`
Expected: FAIL con `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

`src/japan_reader/clients/places.py`:

```python
import httpx

from japan_reader.clients.http import send
from japan_reader.errors import ApiError, ConfigError
from japan_reader.models import GeoMatch

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
# Solo campos del SKU "Text Search Pro" (5.000 llamadas gratis al mes). No añadir campos Enterprise.
FIELD_MASK = "places.id,places.displayName,places.formattedAddress,places.location,places.googleMapsUri,places.types"


class PlacesClient:
    SERVICE = "google-places"

    def __init__(self, api_key: str, http: httpx.Client | None = None) -> None:
        self._http = http or httpx.Client(timeout=30)
        self._headers = {"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": FIELD_MASK}

    def search(self, query: str) -> list[GeoMatch]:
        body = {"textQuery": query, "regionCode": "JP", "languageCode": "es", "pageSize": 5}
        try:
            resp = send(self._http, "POST", SEARCH_URL, self.SERVICE, headers=self._headers, json=body)
        except ApiError as exc:
            if exc.status == 400 and "api key" in str(exc).lower():
                raise ConfigError("google-places: API key inválida") from exc
            raise
        matches = []
        for place in resp.json().get("places", []):
            if "location" not in place:
                continue
            matches.append(
                GeoMatch(
                    place_id=place["id"],
                    name=(place.get("displayName") or {}).get("text", ""),
                    address=place.get("formattedAddress", ""),
                    lat=place["location"]["latitude"],
                    lng=place["location"]["longitude"],
                    maps_url=place.get("googleMapsUri", ""),
                    types=place.get("types", []),
                )
            )
        return matches
```

`src/japan_reader/geo.py`:

```python
from japan_reader.models import GeoMatch, Lugar
from japan_reader.text import fold, normalize_name, similarity

_LAT_RANGE = (20.0, 46.0)
_LNG_RANGE = (122.0, 154.0)
_JAPAN_WORDS = ("japon", "japan", "日本")
CITY_ALIASES: dict[str, list[str]] = {
    "tokio": ["tokyo", "東京"],
    "kioto": ["kyoto", "京都"],
    "osaka": ["大阪"],
    "nara": ["奈良"],
    "hiroshima": ["広島"],
    "sapporo": ["札幌"],
    "fukuoka": ["福岡"],
    "kobe": ["神戸"],
    "yokohama": ["横浜"],
    "nagoya": ["名古屋"],
    "kanazawa": ["金沢"],
    "hakone": ["箱根"],
    "nikko": ["日光"],
    "kamakura": ["鎌倉"],
}
NAME_SIMILARITY = 0.6


def in_japan(match: GeoMatch) -> bool:
    # fold y no normalize_name: normalize_name elimina "japon"/"japan" por ser palabras genéricas.
    inside = _LAT_RANGE[0] <= match.lat <= _LAT_RANGE[1] and _LNG_RANGE[0] <= match.lng <= _LNG_RANGE[1]
    address = fold(match.address)
    return inside and any(word in address for word in _JAPAN_WORDS)


def city_matches(match: GeoMatch, ciudad: str | None) -> bool:
    if not ciudad:
        return True
    city = fold(ciudad).strip()
    address = fold(match.address)
    return any(fold(name) in address for name in [city, *CITY_ALIASES.get(city, [])])


def name_matches(match: GeoMatch, lugar: Lugar) -> bool:
    found = normalize_name(match.name)
    wanted = [normalize_name(lugar.nombre)] + ([normalize_name(lugar.nombre_local)] if lugar.nombre_local else [])
    return any(w and (w in found or found in w or similarity(w, found) >= NAME_SIMILARITY) for w in wanted)
```

`src/japan_reader/stages/geocode.py`:

```python
import logging

from japan_reader.clients.places import PlacesClient
from japan_reader.config import Thresholds
from japan_reader.context import JobContext
from japan_reader.geo import city_matches, in_japan, name_matches
from japan_reader.models import ExtractResult, GeocodeResult, GeoMatch, GeoOutcome, Lugar
from japan_reader.quota import DailyQuota
from japan_reader.rules import japan_decision

log = logging.getLogger(__name__)


class GeocodeStage:
    """Etapa 5: coordenadas y ficha de Google para cada lugar."""

    name = "geocode"
    result_model = GeocodeResult

    def __init__(self, places: PlacesClient, quota: DailyQuota, thresholds: Thresholds) -> None:
        self._places = places
        self._quota = quota
        self._th = thresholds

    def run(self, ctx: JobContext) -> GeocodeResult:
        extraction = ctx.result("extract", ExtractResult).extraction
        if extraction is None or japan_decision(extraction, self._th) == "no":
            return GeocodeResult()
        outcomes = [self._geocode(i, lugar) for i, lugar in enumerate(extraction.lugares)]
        for outcome in outcomes:
            log.info(
                "bookmark=%s geocode lugar=%d place=%s revision=%s", ctx.job.bookmark_id, outcome.lugar_index,
                outcome.match.place_id if outcome.match else None, outcome.review_reason,
            )
        return GeocodeResult(outcomes=outcomes)

    def _geocode(self, index: int, lugar: Lugar) -> GeoOutcome:
        queries = list(dict.fromkeys(q for q in (lugar.consulta_busqueda, lugar.nombre_local) if q))
        japan_only: GeoMatch | None = None
        for query in queries:
            self._quota.check()
            results = self._places.search(query)
            self._quota.add(1)
            in_jp = [r for r in results if in_japan(r)]
            valid = [r for r in in_jp if city_matches(r, lugar.ciudad)]
            if valid:
                top = valid[0]
                if len(valid) == 1 or name_matches(top, lugar):
                    return GeoOutcome(lugar_index=index, match=top)
                return GeoOutcome(lugar_index=index, match=top, review_reason="geocodificacion-ambigua")
            if in_jp and japan_only is None:
                japan_only = in_jp[0]
        if japan_only:
            return GeoOutcome(lugar_index=index, match=japan_only, review_reason="geocodificacion-ambigua")
        return GeoOutcome(lugar_index=index, review_reason="geocodificacion-fallida")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_places_client.py tests/unit/test_geocode.py -v`
Expected: all passed

- [ ] **Step 5: Write stage doc**

`docs/pipeline/05-geocode.md`:

```markdown
# Etapa 5 — geocode

**Qué hace:** busca cada lugar extraído en Google Places y obtiene coordenadas, dirección, `place_id` y enlace a Google Maps.

**Entrada:** `Extraction.lugares` (solo si el contenido no se descartó como "no Japón").
**Salida:** `GeocodeResult {outcomes: [GeoOutcome {lugar_index, match, review_reason}]}`.

**Petición:** `POST places:searchText` con `regionCode=JP`, `languageCode=es`, `pageSize=5` y `X-Goog-FieldMask` limitado a campos Pro (`id, displayName, formattedAddress, location, googleMapsUri, types`). No se piden horarios ni valoraciones (Enterprise).

**Validación y decisión:**
1. Consulta `consulta_busqueda`; si no hay resultado válido, segunda consulta con `nombre_local`.
2. Válido = dentro de Japón (caja de coordenadas + "Japón/Japan/日本" en la dirección) y en la ciudad esperada (con alias: Tokio/Tokyo/東京, Kioto/Kyoto/京都...).
3. Un único válido, o el primero con nombre parecido → aceptado.
4. Varios válidos con nombres distintos, o solo resultados en Japón pero en otra ciudad → se usa el primero y va a revisión (`geocodificacion-ambigua`).
5. Nada en Japón → sin coordenadas y a revisión (`geocodificacion-fallida`).

**Cuota:** contador diario `places_calls` limitado por `PLACES_DAILY_LIMIT` (150 por defecto ≈ 4.500/mes, por debajo de las 5.000 gratis). Al llegar al límite el job espera al día siguiente. Configura además una cuota diaria en Google Cloud Console (APIs → Places API (New) → Cuotas).

**Fallos:** API key inválida → `ConfigError`; 429/5xx → reintento.

**Cómo probarla:** `uv run pytest tests/unit/test_geocode.py tests/unit/test_places_client.py`.
```

- [ ] **Step 6: Commit**

```bash
git add src/japan_reader tests/unit/test_places_client.py tests/unit/test_geocode.py docs/pipeline/05-geocode.md
git commit -m "feat: Google Places client and geocode stage with validation and quota"
```

---

### Task 12: Cliente de Trilium (ETAPI), `FakeTrilium` y estructura de notas (`init-trilium`)

**Files:**
- Create: `src/japan_reader/clients/trilium.py`, `src/japan_reader/trilium_layout.py`
- Modify: `tests/fakes.py` (añadir `FakeTrilium`)
- Test: `tests/unit/test_trilium_client.py`, `tests/unit/test_trilium_layout.py`

**Interfaces:**
- Consumes: `send` (Tarea 4); `ConfigError`.
- Produces:
  - `TAttr(attribute_id, type, name, value)`, `TNote(note_id, title, type, attributes, parent_note_ids, parent_branch_ids)` con `label(name) -> str | None`, `attr(type, name) -> TAttr | None`, `relations(name) -> list[str]`; `TAttachment(attachment_id, title, mime, role)`.
  - `TriliumClient(base_url, token, http=None)`: `app_info() -> dict`, `search(query, ancestor=None, ancestor_depth=None, limit=None) -> list[TNote]`, `get_note(note_id) -> TNote`, `create_note(parent_id, title, type="text", content="") -> TNote`, `get_content(note_id) -> str`, `set_content(note_id, content)`, `add_label(note_id, name, value="") -> str`, `add_relation(note_id, name, target_id) -> str`, `update_attribute(attribute_id, value)`, `delete_attribute(attribute_id)`, `clone(note_id, parent_id) -> str`, `create_attachment(owner_id, title, mime, content, role="file") -> str`, `list_attachments(note_id) -> list[TAttachment]`, `get_attachment_content(attachment_id) -> str`, `set_attachment_content(attachment_id, content)`.
  - `trilium_layout`: `CATEGORIES: dict[str, str]`, `GEO_MAP_TEMPLATE = "_template_geo_map"`, `Layout` (dataclass: `root, mapa, comprar, cultura, revision, plantillas, plantilla_lugar, plantilla_cosa, categorias`), `init_layout(trilium, root_label="jrRoot") -> Layout`, `resolve_layout(trilium, root_label="jrRoot") -> Layout`, `LayoutCache(loader)` (invocable; `refresh()`).
  - `tests/fakes.py`: `FakeTrilium` con la misma interfaz pública que `TriliumClient` más `add_note(parent, title, labels=None, type="text", content="") -> str` y `labels(note_id) -> dict[str, str]`.

- [ ] **Step 1: Write the failing client test**

`tests/unit/test_trilium_client.py`:

```python
import json

import httpx
import pytest
import respx

from japan_reader.clients.trilium import TriliumClient

HOST = "trilium.test"
NOTE = {
    "noteId": "n1", "title": "Ichiran", "type": "text",
    "attributes": [
        {"attributeId": "a1", "noteId": "n1", "type": "label", "name": "ciudad", "value": "Tokio"},
        {"attributeId": "a2", "noteId": "n1", "type": "relation", "name": "dondeComprar", "value": "n9"},
    ],
    "parentNoteIds": ["p1"], "parentBranchIds": ["p1_n1"],
}


@pytest.fixture
def client():
    return TriliumClient("http://trilium.test/", "etapi-token")


@respx.mock
def test_search_params_and_parsing(client):
    route = respx.get(host=HOST, path="/etapi/notes").mock(return_value=httpx.Response(200, json={"results": [NOTE]}))

    notes = client.search('#googlePlaceId="X"', ancestor="root1", ancestor_depth="eq1", limit=5)

    params = route.calls[0].request.url.params
    assert params["search"] == '#googlePlaceId="X"'
    assert params["ancestorNoteId"] == "root1"
    assert params["ancestorDepth"] == "eq1"
    assert params["limit"] == "5"
    assert route.calls[0].request.headers["Authorization"] == "etapi-token"
    note = notes[0]
    assert note.label("ciudad") == "Tokio"
    assert note.relations("dondeComprar") == ["n9"]
    assert note.parent_note_ids == ["p1"]


@respx.mock
def test_create_note_and_content(client):
    create = respx.post(host=HOST, path="/etapi/create-note").mock(return_value=httpx.Response(201, json={"note": NOTE, "branch": {}}))
    put = respx.put(host=HOST, path="/etapi/notes/n1/content").mock(return_value=httpx.Response(204))

    note = client.create_note("p1", "Ichiran", "text", "<p>x</p>")
    client.set_content("n1", "<p>nuevo</p>")

    assert note.note_id == "n1"
    assert json.loads(create.calls[0].request.content) == {"parentNoteId": "p1", "title": "Ichiran", "type": "text", "content": "<p>x</p>"}
    assert put.calls[0].request.content == "<p>nuevo</p>".encode()
    assert put.calls[0].request.headers["Content-Type"].startswith("text/plain")


@respx.mock
def test_attributes_branches_and_attachments(client):
    attr = respx.post(host=HOST, path="/etapi/attributes").mock(return_value=httpx.Response(201, json={"attributeId": "a9"}))
    patch = respx.patch(host=HOST, path="/etapi/attributes/a9").mock(return_value=httpx.Response(200, json={}))
    branch = respx.post(host=HOST, path="/etapi/branches").mock(return_value=httpx.Response(201, json={"branchId": "b9"}))
    attach = respx.post(host=HOST, path="/etapi/attachments").mock(return_value=httpx.Response(201, json={"attachmentId": "x9"}))
    respx.get(host=HOST, path="/etapi/notes/n1/attachments").mock(
        return_value=httpx.Response(200, json=[{"attachmentId": "x9", "title": "japan-reader.json", "mime": "application/json", "role": "file"}])
    )

    assert client.add_label("n1", "ciudad", "Tokio") == "a9"
    assert client.add_relation("n1", "template", "t1") == "a9"
    client.update_attribute("a9", "Kioto")
    assert client.clone("n1", "rev") == "b9"
    assert client.create_attachment("n1", "japan-reader.json", "application/json", "{}") == "x9"
    assert client.list_attachments("n1")[0].title == "japan-reader.json"

    assert json.loads(attr.calls[0].request.content) == {"noteId": "n1", "type": "label", "name": "ciudad", "value": "Tokio", "isInheritable": False}
    assert json.loads(attr.calls[1].request.content)["type"] == "relation"
    assert json.loads(patch.calls[0].request.content) == {"value": "Kioto"}
    assert json.loads(branch.calls[0].request.content) == {"noteId": "n1", "parentNoteId": "rev"}
    assert json.loads(attach.calls[0].request.content) == {
        "ownerId": "n1", "role": "file", "mime": "application/json", "title": "japan-reader.json", "content": "{}", "position": 10,
    }
```

- [ ] **Step 2: Add `FakeTrilium` and write the failing layout test**

Añade a `tests/fakes.py` (imports arriba, el resto al final):

```python
import itertools
import re

from japan_reader.clients.trilium import TAttachment, TAttr, TNote

_CONDITION = re.compile(r'#([\w:]+)(?:=(?:"([^"]*)"|(\S+)))?')


class FakeTrilium:
    """Trilium en memoria. Soporta búsquedas `#etiqueta` y `#etiqueta=valor` combinadas (AND)."""

    def __init__(self) -> None:
        self._ids = itertools.count(1)
        self.notes: dict[str, dict] = {"root": {"title": "root", "type": "text", "content": "", "parents": []}}
        self.attrs: dict[str, dict] = {}
        self.attachments: dict[str, dict] = {}

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}{next(self._ids)}"

    # --- utilidades de test ---
    def add_note(self, parent: str, title: str, labels: dict | None = None, type: str = "text", content: str = "") -> str:
        note_id = self._new_id("n")
        self.notes[note_id] = {"title": title, "type": type, "content": content, "parents": [parent]}
        for name, value in (labels or {}).items():
            self.add_label(note_id, name, value)
        return note_id

    def labels(self, note_id: str) -> dict[str, str]:
        return {a["name"]: a["value"] for a in self.attrs.values() if a["note"] == note_id and a["type"] == "label"}

    def children(self, parent: str) -> list[str]:
        return [nid for nid, n in self.notes.items() if parent in n["parents"]]

    # --- interfaz de TriliumClient ---
    def app_info(self) -> dict:
        return {"appVersion": "fake"}

    def get_note(self, note_id: str) -> TNote:
        note = self.notes[note_id]
        attributes = [
            TAttr(attributeId=aid, type=a["type"], name=a["name"], value=a["value"])
            for aid, a in self.attrs.items() if a["note"] == note_id
        ]
        return TNote(
            noteId=note_id, title=note["title"], type=note["type"], attributes=attributes,
            parentNoteIds=list(note["parents"]), parentBranchIds=[f"{p}_{note_id}" for p in note["parents"]],
        )

    def create_note(self, parent_id: str, title: str, type: str = "text", content: str = "") -> TNote:
        return self.get_note(self.add_note(parent_id, title, type=type, content=content))

    def get_content(self, note_id: str) -> str:
        return self.notes[note_id]["content"]

    def set_content(self, note_id: str, content: str) -> None:
        self.notes[note_id]["content"] = content

    def add_label(self, note_id: str, name: str, value: str = "") -> str:
        attr_id = self._new_id("a")
        self.attrs[attr_id] = {"note": note_id, "type": "label", "name": name, "value": value}
        return attr_id

    def add_relation(self, note_id: str, name: str, target_id: str) -> str:
        attr_id = self._new_id("a")
        self.attrs[attr_id] = {"note": note_id, "type": "relation", "name": name, "value": target_id}
        return attr_id

    def update_attribute(self, attribute_id: str, value: str) -> None:
        self.attrs[attribute_id]["value"] = value

    def delete_attribute(self, attribute_id: str) -> None:
        del self.attrs[attribute_id]

    def clone(self, note_id: str, parent_id: str) -> str:
        self.notes[note_id]["parents"].append(parent_id)
        return f"{parent_id}_{note_id}"

    def create_attachment(self, owner_id: str, title: str, mime: str, content: str, role: str = "file") -> str:
        attachment_id = self._new_id("x")
        self.attachments[attachment_id] = {"owner": owner_id, "title": title, "mime": mime, "role": role, "content": content}
        return attachment_id

    def list_attachments(self, note_id: str) -> list[TAttachment]:
        return [
            TAttachment(attachmentId=aid, title=a["title"], mime=a["mime"], role=a["role"])
            for aid, a in self.attachments.items() if a["owner"] == note_id
        ]

    def get_attachment_content(self, attachment_id: str) -> str:
        return self.attachments[attachment_id]["content"]

    def set_attachment_content(self, attachment_id: str, content: str) -> None:
        self.attachments[attachment_id]["content"] = content

    def search(self, query: str, ancestor: str | None = None, ancestor_depth: str | None = None, limit: int | None = None) -> list[TNote]:
        conditions = [(m.group(1), m.group(2) if m.group(2) is not None else m.group(3)) for m in _CONDITION.finditer(query)]
        found = []
        for note_id in self.notes:
            if note_id == "root" or (ancestor and not self._under(note_id, ancestor, ancestor_depth)):
                continue
            labels = [(a["name"], a["value"]) for a in self.attrs.values() if a["note"] == note_id and a["type"] == "label"]
            if all(any(n == name and (value is None or v == value) for n, v in labels) for name, value in conditions):
                found.append(self.get_note(note_id))
        return found[:limit] if limit else found

    def _under(self, note_id: str, ancestor: str, depth: str | None) -> bool:
        frontier, level = {note_id}, 0
        while frontier:
            level += 1
            parents = {p for n in frontier for p in self.notes[n]["parents"]}
            if ancestor in parents and (depth is None or depth == f"eq{level}"):
                return True
            frontier = parents
        return False
```

`tests/unit/test_trilium_layout.py`:

```python
import pytest

from fakes import FakeTrilium
from japan_reader.errors import ConfigError
from japan_reader.trilium_layout import CATEGORIES, GEO_MAP_TEMPLATE, LayoutCache, init_layout, resolve_layout


@pytest.fixture
def trilium():
    fake = FakeTrilium()
    viajes = fake.add_note("root", "Viajes")
    fake.add_note(viajes, "Ideas de Japón", labels={"jrRoot": ""})
    return fake


def test_init_creates_structure(trilium):
    layout = init_layout(trilium)

    mapa = trilium.get_note(layout.mapa)
    assert mapa.type == "book"
    assert mapa.relations("template") == [GEO_MAP_TEMPLATE]
    assert trilium.get_note(layout.comprar).parent_note_ids == [layout.root]
    assert set(layout.categorias) == set(CATEGORIES)
    assert all(trilium.get_note(nid).parent_note_ids == [layout.comprar] for nid in layout.categorias.values())
    lugar = trilium.get_note(layout.plantilla_lugar)
    assert lugar.title == "Lugar" and lugar.label("template") == ""
    assert lugar.label("label:visitado") == "promoted,single,boolean"
    assert trilium.get_note(layout.plantilla_cosa).title == "Cosa"


def test_init_is_idempotent(trilium):
    first = init_layout(trilium)
    count = len(trilium.notes)
    second = init_layout(trilium)
    assert first == second
    assert len(trilium.notes) == count


def test_resolve_requires_init(trilium):
    with pytest.raises(ConfigError, match="init-trilium"):
        resolve_layout(trilium)


def test_missing_root(trilium):
    with pytest.raises(ConfigError, match="#jrRoot"):
        resolve_layout(FakeTrilium())


def test_duplicate_root(trilium):
    trilium.add_note("root", "Otra", labels={"jrRoot": ""})
    with pytest.raises(ConfigError, match="solo una"):
        init_layout(trilium)


def test_custom_root_label(trilium):
    trilium.add_note("root", "Pruebas", labels={"jrRootTest": ""})
    layout = init_layout(trilium, "jrRootTest")
    assert trilium.get_note(layout.root).title == "Pruebas"


def test_layout_cache(trilium):
    init_layout(trilium)
    calls = []

    def loader():
        calls.append(1)
        return resolve_layout(trilium)

    cache = LayoutCache(loader)
    assert cache() == cache()
    assert len(calls) == 1
    cache.refresh()
    assert len(calls) == 2
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_trilium_client.py tests/unit/test_trilium_layout.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'japan_reader.clients.trilium'`

- [ ] **Step 4: Write minimal implementation**

`src/japan_reader/clients/trilium.py`:

```python
import httpx
from pydantic import BaseModel, ConfigDict, Field

from japan_reader.clients.http import send


class TAttr(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    attribute_id: str = Field(alias="attributeId")
    type: str
    name: str
    value: str = ""


class TNote(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    note_id: str = Field(alias="noteId")
    title: str
    type: str = "text"
    attributes: list[TAttr] = []
    parent_note_ids: list[str] = Field(default=[], alias="parentNoteIds")
    parent_branch_ids: list[str] = Field(default=[], alias="parentBranchIds")

    def attr(self, type: str, name: str) -> TAttr | None:
        return next((a for a in self.attributes if a.type == type and a.name == name), None)

    def label(self, name: str) -> str | None:
        found = self.attr("label", name)
        return found.value if found else None

    def relations(self, name: str) -> list[str]:
        return [a.value for a in self.attributes if a.type == "relation" and a.name == name]


class TAttachment(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    attachment_id: str = Field(alias="attachmentId")
    title: str
    mime: str = ""
    role: str = ""


class TriliumClient:
    """Cliente mínimo de ETAPI (Trilium v0.106)."""

    SERVICE = "trilium"

    def __init__(self, base_url: str, token: str, http: httpx.Client | None = None) -> None:
        self._http = http or httpx.Client(timeout=60)
        self._base = base_url.rstrip("/") + "/etapi"
        self._headers = {"Authorization": token}

    def _req(self, method: str, path: str, **kwargs) -> httpx.Response:
        headers = self._headers | kwargs.pop("headers", {})
        return send(self._http, method, self._base + path, self.SERVICE, headers=headers, **kwargs)

    def app_info(self) -> dict:
        return self._req("GET", "/app-info").json()

    def search(self, query: str, ancestor: str | None = None, ancestor_depth: str | None = None, limit: int | None = None) -> list[TNote]:
        params: dict[str, str | int] = {"search": query}
        if ancestor:
            params["ancestorNoteId"] = ancestor
        if ancestor_depth:
            params["ancestorDepth"] = ancestor_depth
        if limit:
            params["limit"] = limit
        return [TNote.model_validate(n) for n in self._req("GET", "/notes", params=params).json()["results"]]

    def get_note(self, note_id: str) -> TNote:
        return TNote.model_validate(self._req("GET", f"/notes/{note_id}").json())

    def create_note(self, parent_id: str, title: str, type: str = "text", content: str = "") -> TNote:
        body = {"parentNoteId": parent_id, "title": title, "type": type, "content": content}
        return TNote.model_validate(self._req("POST", "/create-note", json=body).json()["note"])

    def get_content(self, note_id: str) -> str:
        return self._req("GET", f"/notes/{note_id}/content").text

    def set_content(self, note_id: str, content: str) -> None:
        self._req("PUT", f"/notes/{note_id}/content", content=content.encode("utf-8"), headers={"Content-Type": "text/plain; charset=utf-8"})

    def _add_attribute(self, note_id: str, type: str, name: str, value: str) -> str:
        body = {"noteId": note_id, "type": type, "name": name, "value": value, "isInheritable": False}
        return self._req("POST", "/attributes", json=body).json()["attributeId"]

    def add_label(self, note_id: str, name: str, value: str = "") -> str:
        return self._add_attribute(note_id, "label", name, value)

    def add_relation(self, note_id: str, name: str, target_id: str) -> str:
        return self._add_attribute(note_id, "relation", name, target_id)

    def update_attribute(self, attribute_id: str, value: str) -> None:
        self._req("PATCH", f"/attributes/{attribute_id}", json={"value": value})

    def delete_attribute(self, attribute_id: str) -> None:
        self._req("DELETE", f"/attributes/{attribute_id}")

    def clone(self, note_id: str, parent_id: str) -> str:
        return self._req("POST", "/branches", json={"noteId": note_id, "parentNoteId": parent_id}).json()["branchId"]

    def create_attachment(self, owner_id: str, title: str, mime: str, content: str, role: str = "file") -> str:
        body = {"ownerId": owner_id, "role": role, "mime": mime, "title": title, "content": content, "position": 10}
        return self._req("POST", "/attachments", json=body).json()["attachmentId"]

    def list_attachments(self, note_id: str) -> list[TAttachment]:
        return [TAttachment.model_validate(a) for a in self._req("GET", f"/notes/{note_id}/attachments").json()]

    def get_attachment_content(self, attachment_id: str) -> str:
        return self._req("GET", f"/attachments/{attachment_id}/content").text

    def set_attachment_content(self, attachment_id: str, content: str) -> None:
        self._req(
            "PUT", f"/attachments/{attachment_id}/content",
            content=content.encode("utf-8"), headers={"Content-Type": "text/plain; charset=utf-8"},
        )
```

`src/japan_reader/trilium_layout.py`:

```python
from collections.abc import Callable
from dataclasses import dataclass

from japan_reader.clients.trilium import TNote, TriliumClient
from japan_reader.errors import ConfigError

CATEGORIES: dict[str, str] = {
    "souvenirs": "Souvenirs",
    "comida": "Comida",
    "cadenas": "Cadenas",
    "cosmetica": "Cosmética",
    "otros": "Otros",
}
GEO_MAP_TEMPLATE = "_template_geo_map"
_SECTIONS = {
    "jrMapa": "Mapa de lugares",
    "jrComprar": "Comprar y comer",
    "jrCultura": "Cultura y curiosidades",
    "jrRevision": "Bandeja de revisión",
    "jrPlantillas": "Plantillas",
}
TEMPLATE_LUGAR = "Lugar"
TEMPLATE_COSA = "Cosa"
_TEMPLATE_LABELS = {
    TEMPLATE_LUGAR: {
        "label:visitado": "promoted,single,boolean",
        "label:prioridad": "promoted,single,number",
        "label:ciudad": "promoted,single,text",
        "label:categoria": "promoted,single,text",
    },
    TEMPLATE_COSA: {
        "label:comprado": "promoted,single,boolean",
        "label:categoria": "promoted,single,text",
    },
}


@dataclass(frozen=True)
class Layout:
    root: str
    mapa: str
    comprar: str
    cultura: str
    revision: str
    plantillas: str
    plantilla_lugar: str
    plantilla_cosa: str
    categorias: dict[str, str]


def _find_one(trilium: TriliumClient, query: str, ancestor: str | None = None, depth: str | None = None) -> TNote | None:
    found = trilium.search(query, ancestor=ancestor, ancestor_depth=depth)
    if len(found) > 1:
        raise ConfigError(f"Hay {len(found)} notas que cumplen '{query}' en Trilium; debe haber solo una")
    return found[0] if found else None


def _find_template(trilium: TriliumClient, plantillas: str, title: str) -> TNote | None:
    # Las plantillas se buscan por título: sus atributos se heredan a las notas que las usan.
    return next((n for n in trilium.search("#template", ancestor=plantillas, ancestor_depth="eq1") if n.title == title), None)


def _root(trilium: TriliumClient, root_label: str) -> TNote:
    root = _find_one(trilium, f"#{root_label}")
    if root is None:
        raise ConfigError(f"No se encuentra la nota raíz con #{root_label}. Añade esa etiqueta a 'Ideas de Japón' en Trilium.")
    return root


def resolve_layout(trilium: TriliumClient, root_label: str = "jrRoot") -> Layout:
    root = _root(trilium, root_label)
    ids: dict[str, str] = {}
    for label in _SECTIONS:
        note = _find_one(trilium, f"#{label}", root.note_id)
        if note is None:
            raise ConfigError(f"Falta la nota #{label} en Trilium; ejecuta 'japan-reader init-trilium'")
        ids[label] = note.note_id
    categorias: dict[str, str] = {}
    for key in CATEGORIES:
        note = _find_one(trilium, f"#jrCategoria={key}", ids["jrComprar"])
        if note is None:
            raise ConfigError(f"Falta la categoría '{key}' en Trilium; ejecuta 'japan-reader init-trilium'")
        categorias[key] = note.note_id
    templates = {}
    for title in (TEMPLATE_LUGAR, TEMPLATE_COSA):
        note = _find_template(trilium, ids["jrPlantillas"], title)
        if note is None:
            raise ConfigError(f"Falta la plantilla '{title}' en Trilium; ejecuta 'japan-reader init-trilium'")
        templates[title] = note.note_id
    return Layout(
        root=root.note_id,
        mapa=ids["jrMapa"],
        comprar=ids["jrComprar"],
        cultura=ids["jrCultura"],
        revision=ids["jrRevision"],
        plantillas=ids["jrPlantillas"],
        plantilla_lugar=templates[TEMPLATE_LUGAR],
        plantilla_cosa=templates[TEMPLATE_COSA],
        categorias=categorias,
    )


def init_layout(trilium: TriliumClient, root_label: str = "jrRoot") -> Layout:
    """Crea bajo la raíz lo que falte. Idempotente."""
    root = _root(trilium, root_label).note_id

    def ensure(query: str, ancestor: str, parent: str, title: str, labels: dict[str, str], **kwargs) -> str:
        existing = _find_one(trilium, query, ancestor)
        if existing:
            return existing.note_id
        note = trilium.create_note(parent, title, kwargs.get("type", "text"), "")
        for name, value in labels.items():
            trilium.add_label(note.note_id, name, value)
        for name, target in kwargs.get("relations", {}).items():
            trilium.add_relation(note.note_id, name, target)
        return note.note_id

    ensure("#jrMapa", root, root, _SECTIONS["jrMapa"], {"jrMapa": ""}, type="book", relations={"template": GEO_MAP_TEMPLATE})
    comprar = ensure("#jrComprar", root, root, _SECTIONS["jrComprar"], {"jrComprar": ""})
    for key, title in CATEGORIES.items():
        ensure(f"#jrCategoria={key}", comprar, comprar, title, {"jrCategoria": key})
    ensure("#jrCultura", root, root, _SECTIONS["jrCultura"], {"jrCultura": ""})
    ensure("#jrRevision", root, root, _SECTIONS["jrRevision"], {"jrRevision": ""})
    plantillas = ensure("#jrPlantillas", root, root, _SECTIONS["jrPlantillas"], {"jrPlantillas": ""})
    for title, labels in _TEMPLATE_LABELS.items():
        if _find_template(trilium, plantillas, title) is None:
            note = trilium.create_note(plantillas, title, "text", "")
            trilium.add_label(note.note_id, "template", "")
            for name, value in labels.items():
                trilium.add_label(note.note_id, name, value)
    return resolve_layout(trilium, root_label)


class LayoutCache:
    """Resuelve la estructura una vez y la reutiliza; `refresh()` fuerza releerla."""

    def __init__(self, loader: Callable[[], Layout]) -> None:
        self._loader = loader
        self._layout: Layout | None = None

    def __call__(self) -> Layout:
        if self._layout is None:
            self._layout = self._loader()
        return self._layout

    def refresh(self) -> Layout:
        self._layout = self._loader()
        return self._layout
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_trilium_client.py tests/unit/test_trilium_layout.py -v`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add src/japan_reader tests
git commit -m "feat: Trilium ETAPI client and idempotent note structure (init-trilium)"
```

---

### Task 13: Datos de nota y renderizado HTML (+ `docs/trilium-model.md`)

**Files:**
- Create: `src/japan_reader/notes.py`, `docs/trilium-model.md`
- Test: `tests/unit/test_notes.py`

**Interfaces:**
- Consumes: `GeoMatch`, `SourceMeta` (Tarea 2); `normalize_name`.
- Produces:
  - `SourceEntry(bookmark_id, url, platform, content_type, title, author, published, aporte)`.
  - `LugarData(kind="lugar", nombre, nombre_local, ciudad, region, categoria, resumen, que_hacer, consejos, precio_aprox, place: GeoMatch | None, fuentes)`, `CosaData(kind="cosa", nombre, categoria, resumen, consejos, donde, fuentes)`, `OtroData(kind="otro", titulo, contenido, fuentes)`, alias `NoteData`.
  - `DATA_ATTACHMENT_TITLE = "japan-reader.json"`, `MIS_NOTAS_HEADING = "<h2>Mis notas</h2>"`, `ICONS: dict[str, str]`, `COSA_ICON`, `OTRO_ICON`.
  - `dump_data(data) -> str`, `load_data(raw) -> NoteData`, `note_title(data) -> str`, `source_entry(bookmark_id, meta, aporte) -> SourceEntry`, `add_source(data, entry) -> bool` (True si es nueva; si el bookmark ya estaba, reemplaza su entrada), `labels_for(data) -> dict[str, str]`, `render_generated(data) -> str`, `compose_content(generated, existing: str | None) -> str`, `render_failure(meta, transcript, error) -> str`.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_notes.py`:

```python
from builders import make_geo, make_meta
from japan_reader.notes import (
    CosaData,
    LugarData,
    OtroData,
    add_source,
    compose_content,
    dump_data,
    labels_for,
    load_data,
    render_failure,
    render_generated,
    source_entry,
)


def _lugar(**overrides):
    base = dict(
        nombre="Ichiran Shibuya", nombre_local="一蘭 渋谷店", ciudad="Tokio", region="Kanto", categoria="comida",
        resumen="Ramen <b>tonkotsu</b> en cubículos", que_hacer="Pedir extra de cerdo", consejos=["Ir antes de las 11"],
        precio_aprox="¥1000", place=make_geo(), fuentes=[source_entry("b1", make_meta(), "Primer vídeo")],
    )
    return LugarData(**(base | overrides))


def test_render_lugar_sections_and_escaping():
    html = render_generated(_lugar())
    assert "<h2>Resumen</h2>" in html
    assert "Ramen &lt;b&gt;tonkotsu&lt;/b&gt;" in html
    assert "<h2>Qué hacer / comer</h2>" in html
    assert "<li>Precio aproximado: ¥1000</li>" in html
    assert 'href="https://maps.google.com/?cid=P1"' in html
    assert "<h2>Fuentes</h2>" in html and "viajero" in html and "Primer vídeo" in html


def test_render_cosa_and_otro():
    cosa = CosaData(nombre="Kit Kat matcha", categoria="souvenirs", resumen="Chocolatina", donde=["Konbini"], fuentes=[])
    assert "<h2>Dónde conseguirlo</h2>" in render_generated(cosa)
    otro = OtroData(titulo="Propinas", contenido="En Japón no se dan propinas", fuentes=[])
    assert "no se dan propinas" in render_generated(otro)


def test_compose_new_note_has_empty_user_section():
    assert compose_content("<p>gen</p>", None) == "<p>gen</p><h2>Mis notas</h2><p></p>"


def test_compose_keeps_user_notes_even_if_editor_rewrote_heading():
    """Review Focus 1."""
    existing = "<p>viejo</p><h2><strong>Mis notas</strong></h2><p>Reservar el martes</p>"
    assert compose_content("<p>nuevo</p>", existing) == "<p>nuevo</p><h2>Mis notas</h2><p>Reservar el martes</p>"


def test_compose_without_heading_keeps_everything():
    assert compose_content("<p>nuevo</p>", "<p>todo lo que había</p>") == "<p>nuevo</p><h2>Mis notas</h2><p>todo lo que había</p>"


def test_add_source_appends_or_replaces():
    data = _lugar()
    assert add_source(data, source_entry("b2", make_meta(url="https://youtu.be/2"), "Segundo")) is True
    assert add_source(data, source_entry("b1", make_meta(), "Primero actualizado")) is False
    assert [f.aporte for f in data.fuentes] == ["Primero actualizado", "Segundo"]


def test_dump_and_load_roundtrip():
    for data in (_lugar(), CosaData(nombre="X", categoria="otros", resumen="r"), OtroData(titulo="t", contenido="c")):
        assert load_data(dump_data(data)) == data


def test_labels_for_lugar_and_cosa():
    labels = labels_for(_lugar())
    assert labels["geolocation"] == "35.66,139.7"
    assert labels["googlePlaceId"] == "P1"
    assert labels["googleMaps"] == "https://maps.google.com/?cid=P1"
    assert labels["jrTipo"] == "lugar" and labels["fuentes"] == "1"
    assert labels["iconClass"] == "bx bx-bowl-hot"
    assert labels["nombreLocal"] == "一蘭 渋谷店"
    assert "geolocation" not in labels_for(_lugar(place=None))
    cosa = labels_for(CosaData(nombre="CoCo Ichibanya", categoria="cadenas", resumen="r"))
    assert cosa["jrTipo"] == "cosa" and cosa["jrNombreNorm"] == "coco ichibanya" and cosa["categoria"] == "cadenas"


def test_render_failure():
    html = render_failure(make_meta(description="caption <x>"), "transcripción", "JSON inválido")
    assert "caption &lt;x&gt;" in html and "transcripción" in html and "JSON inválido" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_notes.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'japan_reader.notes'`

- [ ] **Step 3: Write minimal implementation**

`src/japan_reader/notes.py`:

```python
import re
from html import escape
from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter

from japan_reader.models import GeoMatch, SourceMeta
from japan_reader.text import normalize_name

DATA_ATTACHMENT_TITLE = "japan-reader.json"
MIS_NOTAS_HEADING = "<h2>Mis notas</h2>"
_MIS_NOTAS = re.compile(r"<h2[^>]*>(?:\s|<[^>]+>)*Mis notas(?:\s|<[^>]+>)*</h2>", re.I)
_EMPTY_PARAGRAPH = "<p></p>"

ICONS: dict[str, str] = {
    "templo": "bx bx-buildings",
    "santuario": "bx bx-buildings",
    "comida": "bx bx-bowl-hot",
    "cafe": "bx bx-coffee",
    "bar": "bx bx-drink",
    "tienda": "bx bx-shopping-bag",
    "mercado": "bx bx-store",
    "mirador": "bx bx-landscape",
    "barrio": "bx bx-map-alt",
    "museo": "bx bx-palette",
    "parque": "bx bx-leaf",
    "onsen": "bx bx-water",
    "alojamiento": "bx bx-bed",
    "transporte": "bx bx-train",
    "otro": "bx bx-map-pin",
}
COSA_ICON = "bx bx-shopping-bag"
OTRO_ICON = "bx bx-bulb"


class SourceEntry(BaseModel):
    bookmark_id: str
    url: str
    platform: str
    content_type: str
    title: str | None = None
    author: str | None = None
    published: str | None = None
    aporte: str = ""


class LugarData(BaseModel):
    kind: Literal["lugar"] = "lugar"
    nombre: str
    nombre_local: str | None = None
    ciudad: str | None = None
    region: str | None = None
    categoria: str
    resumen: str
    que_hacer: str = ""
    consejos: list[str] = []
    precio_aprox: str | None = None
    place: GeoMatch | None = None
    fuentes: list[SourceEntry] = []


class CosaData(BaseModel):
    kind: Literal["cosa"] = "cosa"
    nombre: str
    categoria: str
    resumen: str
    consejos: list[str] = []
    donde: list[str] = []
    fuentes: list[SourceEntry] = []


class OtroData(BaseModel):
    kind: Literal["otro"] = "otro"
    titulo: str
    contenido: str
    fuentes: list[SourceEntry] = []


NoteData = LugarData | CosaData | OtroData
_ADAPTER: TypeAdapter[NoteData] = TypeAdapter(Annotated[NoteData, Field(discriminator="kind")])


def dump_data(data: NoteData) -> str:
    return data.model_dump_json(indent=2)


def load_data(raw: str) -> NoteData:
    return _ADAPTER.validate_json(raw)


def note_title(data: NoteData) -> str:
    return data.titulo if isinstance(data, OtroData) else data.nombre


def source_entry(bookmark_id: str, meta: SourceMeta, aporte: str) -> SourceEntry:
    return SourceEntry(
        bookmark_id=bookmark_id, url=meta.url, platform=str(meta.platform), content_type=str(meta.content_type),
        title=meta.title, author=meta.author, published=meta.published, aporte=aporte,
    )


def add_source(data: NoteData, entry: SourceEntry) -> bool:
    for i, existing in enumerate(data.fuentes):
        if existing.bookmark_id == entry.bookmark_id:
            data.fuentes[i] = entry
            return False
    data.fuentes.append(entry)
    return True


def labels_for(data: NoteData) -> dict[str, str]:
    """Atributos que el servicio gestiona. Nunca incluye los manuales (#visitado, #prioridad, #revisar)."""
    if isinstance(data, LugarData):
        labels = {
            "jrTipo": "lugar",
            "categoria": data.categoria,
            "fuentes": str(len(data.fuentes)),
            "iconClass": ICONS.get(data.categoria, ICONS["otro"]),
        }
        if data.ciudad:
            labels["ciudad"] = data.ciudad
        if data.region:
            labels["region"] = data.region
        if data.nombre_local:
            labels["nombreLocal"] = data.nombre_local
        if data.place:
            labels["geolocation"] = f"{data.place.lat},{data.place.lng}"
            labels["googlePlaceId"] = data.place.place_id
            labels["googleMaps"] = data.place.maps_url
        return labels
    if isinstance(data, CosaData):
        return {
            "jrTipo": "cosa",
            "jrNombreNorm": normalize_name(data.nombre) or data.nombre.casefold(),
            "categoria": data.categoria,
            "fuentes": str(len(data.fuentes)),
            "iconClass": COSA_ICON,
        }
    return {"jrTipo": "otro", "fuentes": str(len(data.fuentes)), "iconClass": OTRO_ICON}


def _p(text: str | None) -> str:
    return f"<p>{escape(text)}</p>" if text else ""


def _ul(items: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{escape(item)}</li>" for item in items) + "</ul>" if items else ""


def _sources(fuentes: list[SourceEntry]) -> str:
    items = []
    for f in fuentes:
        details = " · ".join(escape(x) for x in (f.author, f.platform, f.content_type, f.published) if x)
        aporte = f"<br>{escape(f.aporte)}" if f.aporte else ""
        items.append(f'<li><a href="{escape(f.url, quote=True)}">{escape(f.title or f.url)}</a> — {details}{aporte}</li>')
    return "<h2>Fuentes</h2><ul>" + "".join(items) + "</ul>"


def render_generated(data: NoteData) -> str:
    """Parte de la nota que genera el servicio (todo lo anterior a "Mis notas")."""
    parts: list[str] = []
    if isinstance(data, LugarData):
        parts += ["<h2>Resumen</h2>", _p(data.resumen)]
        if data.que_hacer:
            parts += ["<h2>Qué hacer / comer</h2>", _p(data.que_hacer)]
        consejos = [*data.consejos, *([f"Precio aproximado: {data.precio_aprox}"] if data.precio_aprox else [])]
        if consejos:
            parts += ["<h2>Consejos prácticos</h2>", _ul(consejos)]
        if data.place:
            parts.append(f'<p><a href="{escape(data.place.maps_url, quote=True)}">Abrir en Google Maps</a> · {escape(data.place.address)}</p>')
    elif isinstance(data, CosaData):
        parts += ["<h2>Resumen</h2>", _p(data.resumen)]
        if data.donde:
            parts += ["<h2>Dónde conseguirlo</h2>", _ul(data.donde)]
        if data.consejos:
            parts += ["<h2>Consejos</h2>", _ul(data.consejos)]
    else:
        parts.append(_p(data.contenido))
    parts.append(_sources(data.fuentes))
    return "".join(parts)


def compose_content(generated: str, existing: str | None) -> str:
    """Contenido generado + encabezado "Mis notas" + lo que el usuario tenga debajo (nunca se pierde)."""
    kept = _EMPTY_PARAGRAPH
    if existing and existing.strip():
        match = _MIS_NOTAS.search(existing)
        kept = (existing[match.end():] if match else existing) or _EMPTY_PARAGRAPH
    return generated + MIS_NOTAS_HEADING + kept


def render_failure(meta: SourceMeta, transcript: str, error: str) -> str:
    return (
        f'<p><a href="{escape(meta.url, quote=True)}">{escape(meta.url)}</a> — {escape(meta.author or "")}</p>'
        f"<h2>Error</h2>{_p(error)}"
        f"<h2>Descripción</h2>{_p(meta.description or '(vacía)')}"
        f"<h2>Transcripción</h2>{_p(transcript or '(sin transcripción)')}"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_notes.py -v`
Expected: all passed

- [ ] **Step 5: Write `docs/trilium-model.md`**

```markdown
# Modelo de datos en Trilium

La raíz es la nota **`Home › Viajes › Ideas de Japón`**, marcada a mano una vez con `#jrRoot`. El servicio encuentra todo por atributos, así que puedes mover o renombrar las notas.

    Ideas de Japón                    #jrRoot
     ├── Mapa de lugares              #jrMapa   (book + ~template=_template_geo_map → Geo Map)
     ├── Comprar y comer              #jrComprar
     │    └── Souvenirs · Comida · Cadenas · Cosmética · Otros   #jrCategoria=<clave>
     ├── Cultura y curiosidades       #jrCultura
     ├── Bandeja de revisión          #jrRevision
     └── Plantillas                   #jrPlantillas
          ├── Lugar                   #template (+ definiciones promovidas: visitado, prioridad, ciudad, categoria)
          └── Cosa                    #template (+ comprado, categoria)

`japan-reader init-trilium` crea lo que falte (idempotente).

## Nota Lugar (hija de "Mapa de lugares")

- **Atributos gestionados:** `#geolocation="lat,lng"`, `#googlePlaceId`, `#googleMaps`, `#ciudad`, `#region`, `#categoria`, `#nombreLocal`, `#fuentes`, `#iconClass`, `#jrTipo=lugar`, `~template=Lugar`.
- **Atributos tuyos (nunca se tocan):** `#visitado`, `#prioridad` y cualquier otro que añadas.
- **Cuerpo:** Resumen · Qué hacer / comer · Consejos prácticos · enlace a Google Maps · Fuentes · **Mis notas**.

## Nota Cosa (hija de su categoría en "Comprar y comer")

- **Atributos:** `#jrTipo=cosa`, `#jrNombreNorm` (nombre normalizado, clave de deduplicación), `#categoria`, `#fuentes`, `#iconClass`, `~template=Cosa`, `~dondeComprar` → notas Lugar cuando la fuente recomienda un local concreto.
- **Cuerpo:** Resumen · Dónde conseguirlo · Consejos · Fuentes · **Mis notas**.

## Nota Otro (hija de "Cultura y curiosidades")

Título + contenido + fuentes. Sin deduplicación.

## Datos estructurados

Cada nota lleva un adjunto `japan-reader.json` con sus datos (resumen, consejos, fuentes, ficha de Google). Es la fuente de verdad para las fusiones: no lo borres.

## Reglas de fusión

- **Lugar:** mismo `#googlePlaceId` → misma nota. Se añade la fuente, `#fuentes` sube y el LLM reescribe Resumen, Qué hacer y Consejos integrando lo nuevo.
- **Cosa:** mismo `#jrNombreNorm` → misma nota. Si hay una parecida pero no idéntica (similitud ≥ 0.85), se crea una nota nueva y se manda a revisión (`posible-duplicado`).
- **Misma fuente otra vez** (reprocesado): su entrada se actualiza; no se duplica ni se llama al LLM.
- **Mis notas:** todo lo que haya debajo del encabezado "Mis notas" se conserva siempre. Si borras el encabezado, en la siguiente fusión todo el contenido anterior pasa debajo de un "Mis notas" nuevo.

## Bandeja de revisión

Las notas dudosas se **clonan** en la bandeja (siguen también en su sitio) con `#revisar=<motivos>`: `geocodificacion-fallida`, `geocodificacion-ambigua`, `posible-duplicado`, `baja-confianza`, `clasificacion-incierta`, `extraccion-fallida`. Revisar = corregir la nota, quitar `#revisar` y quitar el clon de la bandeja.
```

- [ ] **Step 6: Commit**

```bash
git add src/japan_reader/notes.py tests/unit/test_notes.py docs/trilium-model.md
git commit -m "feat: note data model, HTML rendering and user-notes preservation"
```

---

### Task 14: Etapa `resolve` (+ documentación 06)

**Files:**
- Create: `src/japan_reader/stages/resolve.py`, `docs/pipeline/06-resolve.md`
- Test: `tests/unit/test_resolve.py`

**Interfaces:**
- Consumes: `TriliumClient` / `FakeTrilium`, `Layout`, `init_layout` (Tarea 12); `ExtractResult`, `GeocodeResult`, `GeoOutcome`, `PlannedItem`, `ItemKind`, `ResolveResult`; `japan_decision`; `normalize_name`, `similarity`; `Thresholds`.
- Produces: `ResolveStage(trilium, layout: Callable[[], Layout], thresholds)` con `name = "resolve"`, `result_model = ResolveResult`, `run(ctx) -> ResolveResult`. Claves de elemento: `lugar:<i>`, `cosa:<i>`, `otro:<i>`, `otro:resumen`, `fallo`.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_resolve.py`:

```python
import pytest

from builders import make_ctx, make_cosa, make_extraction, make_geo, make_lugar
from fakes import FakeTrilium
from japan_reader.config import Thresholds
from japan_reader.models import ExtractResult, GeocodeResult, GeoOutcome, ItemKind
from japan_reader.stages.resolve import ResolveStage
from japan_reader.trilium_layout import init_layout


@pytest.fixture
def env():
    trilium = FakeTrilium()
    trilium.add_note("root", "Ideas de Japón", labels={"jrRoot": ""})
    return trilium, init_layout(trilium)


def _run(tmp_path, env, extraction, outcomes=()):
    trilium, layout = env
    ctx = make_ctx(tmp_path, extract=ExtractResult(extraction=extraction), geocode=GeocodeResult(outcomes=list(outcomes)))
    return ResolveStage(trilium, lambda: layout, Thresholds()).run(ctx).items


def test_failed_extraction_becomes_review_item(tmp_path, env):
    trilium, layout = env
    ctx = make_ctx(tmp_path, extract=ExtractResult(extraction=None, error="x"))
    items = ResolveStage(trilium, lambda: layout, Thresholds()).run(ctx).items
    assert [(i.key, i.kind, i.review_reasons) for i in items] == [("fallo", ItemKind.FALLO, ["extraccion-fallida"])]


def test_not_japan_has_no_items(tmp_path, env):
    assert _run(tmp_path, env, make_extraction(0.1, lugares=[make_lugar()])) == []


def test_new_and_existing_places(tmp_path, env):
    trilium, layout = env
    existing = trilium.add_note(layout.mapa, "Ichiran", labels={"jrTipo": "lugar", "googlePlaceId": "P1"})
    extraction = make_extraction(lugares=[make_lugar(), make_lugar("Nuevo sitio")])
    outcomes = [GeoOutcome(lugar_index=0, match=make_geo("P1")), GeoOutcome(lugar_index=1, match=make_geo("P2", "Nuevo sitio"))]

    items = _run(tmp_path, env, extraction, outcomes)

    assert (items[0].action, items[0].existing_note_id) == ("merge", existing)
    assert (items[1].action, items[1].existing_note_id) == ("create", None)
    assert items[0].review_reasons == [] and items[1].review_reasons == []


def test_same_place_twice_in_one_source_is_aliased(tmp_path, env):
    """Review Focus 2."""
    extraction = make_extraction(lugares=[make_lugar("Fushimi Inari"), make_lugar("伏見稲荷大社")])
    outcomes = [GeoOutcome(lugar_index=0, match=make_geo("F1")), GeoOutcome(lugar_index=1, match=make_geo("F1"))]

    items = _run(tmp_path, env, extraction, outcomes)

    assert [(i.key, i.action, i.alias_of) for i in items] == [("lugar:0", "create", None), ("lugar:1", "alias", "lugar:0")]


def test_review_reasons(tmp_path, env):
    extraction = make_extraction(0.5, lugares=[make_lugar(confianza=0.5), make_lugar("Otro")])
    outcomes = [GeoOutcome(lugar_index=0, review_reason="geocodificacion-fallida"), GeoOutcome(lugar_index=1, match=make_geo("P9"), review_reason="geocodificacion-ambigua")]

    items = _run(tmp_path, env, extraction, outcomes)

    assert items[0].review_reasons == ["clasificacion-incierta", "baja-confianza", "geocodificacion-fallida"]
    assert items[1].review_reasons == ["clasificacion-incierta", "geocodificacion-ambigua"]
    assert items[0].action == "create"


def test_cosas_merge_duplicate_and_alias(tmp_path, env):
    trilium, layout = env
    existing = trilium.add_note(layout.categorias["cadenas"], "CoCo", labels={"jrTipo": "cosa", "jrNombreNorm": "coco ichibanya"})
    extraction = make_extraction(cosas=[
        make_cosa("CoCo Ichibanya"),
        make_cosa("CoCo Ichiban-ya"),
        make_cosa("Kit Kat matcha", categoria="souvenirs"),
        make_cosa("kit-kat MATCHA", categoria="souvenirs"),
    ])

    items = _run(tmp_path, env, extraction)

    assert (items[0].action, items[0].existing_note_id) == ("merge", existing)
    assert items[1].action == "create" and items[1].review_reasons == ["posible-duplicado"]
    assert items[2].action == "create" and items[2].review_reasons == []
    assert (items[3].action, items[3].alias_of) == ("alias", "cosa:2")


def test_otros_and_synthetic_summary(tmp_path, env):
    items = _run(tmp_path, env, make_extraction(otros=[{"titulo": "Propinas", "contenido": "No se dan"}]))
    assert [(i.key, i.kind, i.index) for i in items] == [("otro:0", ItemKind.OTRO, 0)]

    items = _run(tmp_path, env, make_extraction())
    assert [(i.key, i.kind, i.index) for i in items] == [("otro:resumen", ItemKind.OTRO, -1)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_resolve.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'japan_reader.stages.resolve'`

- [ ] **Step 3: Write minimal implementation**

`src/japan_reader/stages/resolve.py`:

```python
import logging
from collections.abc import Callable

from japan_reader.clients.trilium import TriliumClient
from japan_reader.config import Thresholds
from japan_reader.context import JobContext
from japan_reader.models import (
    Extraction,
    ExtractResult,
    GeocodeResult,
    GeoOutcome,
    ItemKind,
    PlannedItem,
    ResolveResult,
)
from japan_reader.rules import japan_decision
from japan_reader.text import normalize_name, similarity
from japan_reader.trilium_layout import Layout

log = logging.getLogger(__name__)


class ResolveStage:
    """Etapa 6: decide qué se crea, qué se fusiona con notas existentes y qué va a revisión."""

    name = "resolve"
    result_model = ResolveResult

    def __init__(self, trilium: TriliumClient, layout: Callable[[], Layout], thresholds: Thresholds) -> None:
        self._t = trilium
        self._layout = layout
        self._th = thresholds

    def run(self, ctx: JobContext) -> ResolveResult:
        extraction = ctx.result("extract", ExtractResult).extraction
        if extraction is None:
            item = PlannedItem(key="fallo", kind=ItemKind.FALLO, index=0, action="create", review_reasons=["extraccion-fallida"])
            return ResolveResult(items=[item])
        decision = japan_decision(extraction, self._th)
        if decision == "no":
            return ResolveResult()
        layout = self._layout()
        common = ["clasificacion-incierta"] if decision == "uncertain" else []
        items = [
            *self._lugares(extraction, ctx.result("geocode", GeocodeResult), layout, common),
            *self._cosas(extraction, layout, common),
            *(
                PlannedItem(key=f"otro:{i}", kind=ItemKind.OTRO, index=i, action="create", review_reasons=list(common))
                for i in range(len(extraction.otros))
            ),
        ]
        if not items:
            items.append(PlannedItem(key="otro:resumen", kind=ItemKind.OTRO, index=-1, action="create", review_reasons=list(common)))
        log.info(
            "bookmark=%s resolve crear=%d fusionar=%d revision=%d", ctx.job.bookmark_id,
            sum(i.action == "create" for i in items), sum(i.action == "merge" for i in items),
            sum(bool(i.review_reasons) for i in items),
        )
        return ResolveResult(items=items)

    def _reasons(self, common: list[str], confianza: float, *extra: str | None) -> list[str]:
        reasons = list(common)
        if confianza < self._th.item_review:
            reasons.append("baja-confianza")
        reasons += [reason for reason in extra if reason]
        return list(dict.fromkeys(reasons))

    def _lugares(self, extraction: Extraction, geo: GeocodeResult, layout: Layout, common: list[str]) -> list[PlannedItem]:
        outcomes = {o.lugar_index: o for o in geo.outcomes}
        seen: dict[str, str] = {}
        items: list[PlannedItem] = []
        for i, lugar in enumerate(extraction.lugares):
            key = f"lugar:{i}"
            outcome = outcomes.get(i) or GeoOutcome(lugar_index=i, review_reason="geocodificacion-fallida")
            match = outcome.match
            if match and match.place_id in seen:
                items.append(PlannedItem(key=key, kind=ItemKind.LUGAR, index=i, action="alias", alias_of=seen[match.place_id]))
                continue
            existing = self._t.search(f'#googlePlaceId="{match.place_id}"', ancestor=layout.root) if match else []
            if match:
                seen[match.place_id] = key
            items.append(
                PlannedItem(
                    key=key, kind=ItemKind.LUGAR, index=i,
                    action="merge" if existing else "create",
                    existing_note_id=existing[0].note_id if existing else None,
                    review_reasons=self._reasons(common, lugar.confianza, outcome.review_reason),
                )
            )
        return items

    def _cosas(self, extraction: Extraction, layout: Layout, common: list[str]) -> list[PlannedItem]:
        seen: dict[str, str] = {}
        known: list[str] | None = None
        items: list[PlannedItem] = []
        for i, cosa in enumerate(extraction.cosas):
            key = f"cosa:{i}"
            norm = normalize_name(cosa.nombre) or cosa.nombre.casefold().replace('"', "").strip()
            if norm in seen:
                items.append(PlannedItem(key=key, kind=ItemKind.COSA, index=i, action="alias", alias_of=seen[norm]))
                continue
            seen[norm] = key
            reasons = self._reasons(common, cosa.confianza)
            exact = self._t.search(f'#jrTipo=cosa #jrNombreNorm="{norm}"', ancestor=layout.comprar)
            if exact:
                items.append(PlannedItem(key=key, kind=ItemKind.COSA, index=i, action="merge", existing_note_id=exact[0].note_id, review_reasons=reasons))
                continue
            if known is None:
                known = [n.label("jrNombreNorm") or "" for n in self._t.search("#jrTipo=cosa", ancestor=layout.comprar)]
            if any(k and similarity(norm, k) >= self._th.cosa_duplicate for k in known):
                reasons.append("posible-duplicado")
            items.append(PlannedItem(key=key, kind=ItemKind.COSA, index=i, action="create", review_reasons=reasons))
        return items
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_resolve.py -v`
Expected: all passed ("CoCo Ichiban-ya" se normaliza a `coco ichiban ya`, similitud ≈ 0.97 con `coco ichibanya`).

- [ ] **Step 5: Write stage doc**

`docs/pipeline/06-resolve.md`:

```markdown
# Etapa 6 — resolve

**Qué hace:** compara lo extraído con lo que ya hay en Trilium y decide, elemento a elemento, crear, fusionar o marcar como alias; además calcula los motivos de revisión.

**Entrada:** `ExtractResult`, `GeocodeResult`, estructura de Trilium.
**Salida:** `ResolveResult {items: [PlannedItem {key, kind, index, action, existing_note_id, alias_of, review_reasons}]}`.

**Reglas:**
- Extracción fallida → un único elemento `fallo` con `extraccion-fallida`.
- `confianza_japon` < 0.4 → sin elementos (resultado `no-japon`).
- 0.4 ≤ `confianza_japon` < 0.7 → todos los elementos con `clasificacion-incierta`.
- Elemento con `confianza` < 0.7 → `baja-confianza`.
- Lugar: busca `#googlePlaceId` bajo la raíz → `merge` o `create`. Sin coordenadas → `create` + motivo de geocodificación. Mismo `place_id` dos veces en la misma fuente → `alias` del primero.
- Cosa: busca `#jrTipo=cosa #jrNombreNorm="<normalizado>"` en "Comprar y comer" → `merge`; si no, compara con todas las cosas y, si alguna tiene similitud ≥ 0.85, `create` + `posible-duplicado`. Mismo nombre normalizado dos veces → `alias`.
- Otros → siempre `create`. Si el contenido es de Japón pero no hay ningún elemento → `otro:resumen` con el resumen de la fuente.

**Configuración:** `JAPAN_MIN_CONFIDENCE`, `JAPAN_REVIEW_CONFIDENCE`, `ITEM_REVIEW_CONFIDENCE`, `COSA_DUPLICATE_SIMILARITY`.
**Fallos:** errores de Trilium → reintento; estructura ausente → `ConfigError`.
**Cómo probarla:** `uv run pytest tests/unit/test_resolve.py`.
```

- [ ] **Step 6: Commit**

```bash
git add src/japan_reader/stages/resolve.py tests/unit/test_resolve.py docs/pipeline/06-resolve.md
git commit -m "feat: resolve stage with place/thing deduplication and review reasons"
```

---

### Task 15: Etapa `publish` (+ documentación 07)

**Files:**
- Create: `src/japan_reader/stages/publish.py`, `docs/pipeline/07-publish.md`
- Test: `tests/unit/test_publish.py`

**Interfaces:**
- Consumes: todo lo de las Tareas 10–14 (`OpenRouterClient`/`FakeLLM`, `TriliumClient`/`FakeTrilium`, `Layout`, `notes.*`, `load_prompt("merge")`, `MergeOutput`, `DailyQuota`, `StateStore.published/record_publish`, `japan_decision`, `decide_outcome`).
- Produces: `PublishStage(trilium, layout: Callable[[], Layout], llm, settings, budget, state)` con `name = "publish"`, `result_model = PublishResult`, `run(ctx) -> PublishResult`; `upsert_labels(trilium, note, labels)`.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_publish.py`:

```python
import json
from types import SimpleNamespace

import pytest

from builders import make_cosa, make_ctx, make_extraction, make_fetch, make_geo, make_job, make_lugar, make_meta
from fakes import FakeLLM, FakeTrilium
from japan_reader.models import (
    ExtractResult,
    GeocodeResult,
    GeoOutcome,
    ItemKind,
    Outcome,
    PlannedItem,
    PublishedNote,
    ResolveResult,
    Transcript,
)
from japan_reader.quota import DailyQuota
from japan_reader.stages.publish import PublishStage
from japan_reader.state import StateStore
from japan_reader.trilium_layout import init_layout

MERGED = json.dumps({"resumen": "Resumen fusionado", "que_hacer": "Pedir extra de cerdo", "consejos": ["Ir pronto", "Pagar en la máquina"]})
GEO = [GeoOutcome(lugar_index=0, match=make_geo())]


@pytest.fixture
def env(tmp_path, settings):
    trilium = FakeTrilium()
    viajes = trilium.add_note("root", "Viajes")
    trilium.add_note(viajes, "Ideas de Japón", labels={"jrRoot": ""})
    return SimpleNamespace(trilium=trilium, layout=init_layout(trilium), state=StateStore(tmp_path / "state.db"), settings=settings, tmp=tmp_path)


def _stage(env, llm=None):
    return PublishStage(env.trilium, lambda: env.layout, llm or FakeLLM([]), env.settings, DailyQuota(env.state, "openrouter_usd", 10), env.state)


def _ctx(env, bookmark_id, extraction, outcomes, items):
    job = make_job(bookmark_id=bookmark_id, url=f"https://youtu.be/{bookmark_id}")
    return make_ctx(
        env.tmp, job=job,
        fetch=make_fetch(meta=make_meta(url=job.url)),
        transcribe=Transcript(text="texto hablado", origin="whisper"),
        extract=ExtractResult(extraction=extraction),
        geocode=GeocodeResult(outcomes=list(outcomes)),
        resolve=ResolveResult(items=list(items)),
    )


def _item(kind=ItemKind.LUGAR, index=0, action="create", existing=None, reasons=(), key=None, alias_of=None):
    return PlannedItem(
        key=key or f"{kind.value}:{index}", kind=kind, index=index, action=action,
        existing_note_id=existing, alias_of=alias_of, review_reasons=list(reasons),
    )


def test_create_lugar(env):
    result = _stage(env).run(_ctx(env, "b1", make_extraction(lugares=[make_lugar()]), GEO, [_item()]))

    note_id = result.notes[0].note_id
    note = env.trilium.get_note(note_id)
    labels = env.trilium.labels(note_id)
    assert note.parent_note_ids == [env.layout.mapa]
    assert note.relations("template") == [env.layout.plantilla_lugar]
    assert labels["geolocation"] == "35.66,139.7"
    assert labels["googlePlaceId"] == "P1" and labels["fuentes"] == "1" and labels["jrTipo"] == "lugar"
    content = env.trilium.get_content(note_id)
    assert "Ramen en Ichiran Shibuya" in content and "https://youtu.be/b1" in content and "Mis notas" in content
    assert [a.title for a in env.trilium.list_attachments(note_id)] == ["japan-reader.json"]
    assert result.outcome == Outcome.PROCESADO
    assert env.state.published("b1")["lugar:0"].note_id == note_id


def test_merge_adds_source_rewrites_summary_and_keeps_user_notes(env):
    extraction = make_extraction(lugares=[make_lugar()])
    note_id = _stage(env).run(_ctx(env, "b1", extraction, GEO, [_item()])).notes[0].note_id
    content = env.trilium.get_content(note_id)
    env.trilium.set_content(note_id, content.replace("<h2>Mis notas</h2><p></p>", "<h2><strong>Mis notas</strong></h2><p>Reservar el martes</p>"))
    llm = FakeLLM([MERGED])

    result = _stage(env, llm).run(_ctx(env, "b2", extraction, GEO, [_item(action="merge", existing=note_id)]))

    assert result.notes[0].note_id == note_id
    assert env.trilium.labels(note_id)["fuentes"] == "2"
    content = env.trilium.get_content(note_id)
    assert "Resumen fusionado" in content and "Pagar en la máquina" in content
    assert "Reservar el martes" in content
    assert "https://youtu.be/b1" in content and "https://youtu.be/b2" in content
    assert llm.calls[0]["model"] == "text/model"
    assert len(env.trilium.children(env.layout.mapa)) == 1


def test_republishing_same_bookmark_does_not_duplicate(env):
    """Review Focus 3."""
    extraction = make_extraction(lugares=[make_lugar()])
    note_id = _stage(env).run(_ctx(env, "b1", extraction, GEO, [_item()])).notes[0].note_id
    env.state.clear_stages_from("b1", "publish", ["publish"])
    llm = FakeLLM([])

    _stage(env, llm).run(_ctx(env, "b1", extraction, GEO, [_item(action="merge", existing=note_id)]))

    assert llm.calls == []
    assert env.trilium.labels(note_id)["fuentes"] == "1"
    assert env.trilium.get_content(note_id).count("https://youtu.be/b1") == 1


def test_review_items_are_cloned_to_inbox(env):
    items = [_item(reasons=["geocodificacion-ambigua"])]

    result = _stage(env).run(_ctx(env, "b1", make_extraction(lugares=[make_lugar()]), GEO, items))

    note = env.trilium.get_note(result.notes[0].note_id)
    assert set(note.parent_note_ids) == {env.layout.mapa, env.layout.revision}
    assert note.label("revisar") == "geocodificacion-ambigua"
    assert result.outcome == Outcome.REVISAR


def test_cosa_goes_to_category_and_links_store(env):
    extraction = make_extraction(
        lugares=[make_lugar("Don Quijote Shibuya", categoria="tienda")],
        cosas=[make_cosa("Kit Kat matcha", categoria="souvenirs", donde_lugares=["Don Quijote Shibuya"])],
    )
    items = [_item(), _item(kind=ItemKind.COSA)]

    result = _stage(env).run(_ctx(env, "b1", extraction, GEO, items))

    lugar_id, cosa_id = (n.note_id for n in result.notes)
    cosa = env.trilium.get_note(cosa_id)
    assert cosa.parent_note_ids == [env.layout.categorias["souvenirs"]]
    assert cosa.relations("dondeComprar") == [lugar_id]
    assert cosa.relations("template") == [env.layout.plantilla_cosa]
    assert env.trilium.labels(cosa_id)["jrNombreNorm"] == "kit kat matcha"


def test_failed_extraction_creates_review_note(env):
    items = [PlannedItem(key="fallo", kind=ItemKind.FALLO, index=0, action="create", review_reasons=["extraccion-fallida"])]

    result = _stage(env).run(_ctx(env, "b1", None, [], items))

    note_id = result.notes[0].note_id
    assert env.trilium.get_note(note_id).parent_note_ids == [env.layout.revision]
    assert env.trilium.labels(note_id)["revisar"] == "extraccion-fallida"
    assert "texto hablado" in env.trilium.get_content(note_id)
    assert result.outcome == Outcome.REVISAR


def test_not_japan(env):
    result = _stage(env).run(_ctx(env, "b1", make_extraction(0.1), [], []))
    assert result.notes == [] and result.outcome == Outcome.NO_JAPON


def test_resume_skips_already_published_items(env):
    env.state.record_publish("b1", PublishedNote(key="lugar:0", note_id="nX", action="create"))
    before = len(env.trilium.notes)

    result = _stage(env).run(_ctx(env, "b1", make_extraction(lugares=[make_lugar()]), GEO, [_item()]))

    assert len(env.trilium.notes) == before
    assert result.notes[0].note_id == "nX"


def test_synthetic_summary_note_and_alias(env):
    items = [_item(kind=ItemKind.OTRO, index=-1, key="otro:resumen")]
    result = _stage(env).run(_ctx(env, "b1", make_extraction(), [], items))
    note_id = result.notes[0].note_id
    assert env.trilium.get_note(note_id).parent_note_ids == [env.layout.cultura]
    assert env.trilium.get_note(note_id).title == "Ramen en Tokio"
    assert "Un vídeo sobre Tokio" in env.trilium.get_content(note_id)

    items = [_item(), _item(index=1, action="alias", alias_of="lugar:0")]
    result = _stage(env).run(_ctx(env, "b2", make_extraction(lugares=[make_lugar(), make_lugar("伏見")]), GEO, items))
    assert len(result.notes) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_publish.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'japan_reader.stages.publish'`

- [ ] **Step 3: Write minimal implementation**

`src/japan_reader/stages/publish.py`:

```python
import json
import logging
from collections.abc import Callable

from pydantic import ValidationError

from japan_reader.clients.openrouter import OpenRouterClient
from japan_reader.clients.trilium import TNote, TriliumClient
from japan_reader.config import Settings
from japan_reader.context import JobContext
from japan_reader.models import (
    Extraction,
    ExtractResult,
    FetchResult,
    GeocodeResult,
    ItemKind,
    MergeOutput,
    PlannedItem,
    PublishedNote,
    PublishResult,
    ResolveResult,
    Transcript,
)
from japan_reader.notes import (
    DATA_ATTACHMENT_TITLE,
    CosaData,
    LugarData,
    NoteData,
    OtroData,
    add_source,
    compose_content,
    dump_data,
    labels_for,
    load_data,
    note_title,
    render_failure,
    render_generated,
    source_entry,
)
from japan_reader.prompts import load_prompt
from japan_reader.quota import DailyQuota
from japan_reader.rules import decide_outcome, japan_decision
from japan_reader.state import StateStore
from japan_reader.text import normalize_name, strip_fences
from japan_reader.trilium_layout import Layout

log = logging.getLogger(__name__)


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def upsert_labels(trilium: TriliumClient, note: TNote, labels: dict[str, str]) -> None:
    for name, value in labels.items():
        current = note.attr("label", name)
        if current is None:
            trilium.add_label(note.note_id, name, value)
        elif current.value != value:
            trilium.update_attribute(current.attribute_id, value)


class PublishStage:
    """Etapa 7: crea o fusiona notas en Trilium y manda lo dudoso a la bandeja de revisión."""

    name = "publish"
    result_model = PublishResult

    def __init__(
        self,
        trilium: TriliumClient,
        layout: Callable[[], Layout],
        llm: OpenRouterClient,
        settings: Settings,
        budget: DailyQuota,
        state: StateStore,
    ) -> None:
        self._t = trilium
        self._layout = layout
        self._llm = llm
        self._settings = settings
        self._budget = budget
        self._state = state

    def run(self, ctx: JobContext) -> PublishResult:
        layout = self._layout()
        extraction = ctx.result("extract", ExtractResult).extraction
        plan = ctx.result("resolve", ResolveResult)
        done = self._state.published(ctx.job.bookmark_id)
        by_key: dict[str, PublishedNote] = {}
        for item in plan.items:
            if item.action == "alias":
                continue
            note = done.get(item.key)
            if note is None:
                note = self._publish_item(item, ctx, layout)
                self._state.record_publish(ctx.job.bookmark_id, note)
            by_key[item.key] = note
        if extraction is not None:
            self._link_donde(extraction, plan, by_key)
        notes = [by_key[item.key] for item in plan.items if item.action != "alias"]
        decision = japan_decision(extraction, self._settings.thresholds) if extraction else "yes"
        outcome = decide_outcome(decision, notes)
        log.info("bookmark=%s publish notas=%d resultado=%s", ctx.job.bookmark_id, len(notes), outcome)
        return PublishResult(notes=notes, outcome=outcome)

    def _publish_item(self, item: PlannedItem, ctx: JobContext, layout: Layout) -> PublishedNote:
        if item.kind == ItemKind.FALLO:
            note_id = self._create_failure(ctx, layout)
        else:
            data = self._build_data(item, ctx)
            if item.action == "merge" and item.existing_note_id:
                note_id = self._merge(item.existing_note_id, data)
            else:
                note_id = self._create(data, layout)
        if item.review_reasons:
            self._send_to_review(note_id, item.review_reasons, layout)
        return PublishedNote(key=item.key, note_id=note_id, action=item.action, review_reasons=item.review_reasons)

    def _build_data(self, item: PlannedItem, ctx: JobContext) -> NoteData:
        fetch = ctx.result("fetch", FetchResult)
        extraction = ctx.result("extract", ExtractResult).extraction
        if extraction is None:
            raise ValueError("no hay extracción para construir la nota")

        def entry(aporte: str):
            return source_entry(ctx.job.bookmark_id, fetch.meta, aporte)

        if item.kind == ItemKind.LUGAR:
            lugar = extraction.lugares[item.index]
            geo = ctx.result("geocode", GeocodeResult)
            match = next((o.match for o in geo.outcomes if o.lugar_index == item.index), None)
            return LugarData(
                nombre=lugar.nombre, nombre_local=lugar.nombre_local, ciudad=lugar.ciudad, region=lugar.region,
                categoria=lugar.categoria, resumen=lugar.que_es, que_hacer=lugar.que_hacer, consejos=lugar.consejos,
                precio_aprox=lugar.precio_aprox, place=match, fuentes=[entry(lugar.que_es)],
            )
        if item.kind == ItemKind.COSA:
            cosa = extraction.cosas[item.index]
            return CosaData(
                nombre=cosa.nombre, categoria=cosa.categoria, resumen=cosa.que_es, consejos=cosa.consejos,
                donde=cosa.donde, fuentes=[entry(cosa.que_es)],
            )
        if item.index == -1:
            return OtroData(
                titulo=fetch.meta.title or "Sin título", contenido=extraction.resumen_fuente,
                fuentes=[entry(extraction.resumen_fuente)],
            )
        otro = extraction.otros[item.index]
        return OtroData(titulo=otro.titulo, contenido=otro.contenido, fuentes=[entry(otro.contenido[:200])])

    def _create(self, data: NoteData, layout: Layout) -> str:
        if isinstance(data, LugarData):
            parent, template = layout.mapa, layout.plantilla_lugar
        elif isinstance(data, CosaData):
            parent, template = layout.categorias[data.categoria], layout.plantilla_cosa
        else:
            parent, template = layout.cultura, None
        note = self._t.create_note(parent, note_title(data), "text", compose_content(render_generated(data), None))
        for name, value in labels_for(data).items():
            self._t.add_label(note.note_id, name, value)
        if template:
            self._t.add_relation(note.note_id, "template", template)
        self._t.create_attachment(note.note_id, DATA_ATTACHMENT_TITLE, "application/json", dump_data(data))
        return note.note_id

    def _merge(self, note_id: str, new: NoteData) -> str:
        note = self._t.get_note(note_id)
        attachment = next((a for a in self._t.list_attachments(note_id) if a.title == DATA_ATTACHMENT_TITLE), None)
        if attachment is None:
            log.warning("nota %s sin %s; se regenera con la fuente nueva", note_id, DATA_ATTACHMENT_TITLE)
            data = new
        else:
            data = load_data(self._t.get_attachment_content(attachment.attachment_id))
            if add_source(data, new.fuentes[0]):
                self._merge_text(data, new)
            if isinstance(data, LugarData) and isinstance(new, LugarData) and data.place is None:
                data.place = new.place
            if isinstance(data, CosaData) and isinstance(new, CosaData):
                data.donde = _unique(data.donde + new.donde)
        self._t.set_content(note_id, compose_content(render_generated(data), self._t.get_content(note_id)))
        upsert_labels(self._t, note, labels_for(data))
        if attachment is None:
            self._t.create_attachment(note_id, DATA_ATTACHMENT_TITLE, "application/json", dump_data(data))
        else:
            self._t.set_attachment_content(attachment.attachment_id, dump_data(data))
        return note_id

    def _merge_text(self, data: NoteData, new: NoteData) -> None:
        if isinstance(data, OtroData) or isinstance(new, OtroData):
            return
        current = {"resumen": data.resumen, "que_hacer": getattr(data, "que_hacer", ""), "consejos": data.consejos}
        incoming = {"resumen": new.resumen, "que_hacer": getattr(new, "que_hacer", ""), "consejos": new.consejos}
        messages = [
            {"role": "system", "content": load_prompt("merge")},
            {"role": "user", "content": json.dumps({"actual": current, "nuevo": incoming}, ensure_ascii=False)},
        ]
        self._budget.check()
        result = self._llm.chat_json(self._settings.text_model, messages, MergeOutput.model_json_schema(), "merge")
        self._budget.add(result.cost_usd)
        try:
            merged = MergeOutput.model_validate_json(strip_fences(result.content))
        except ValidationError:
            log.warning("fusión con LLM inválida; se conservan los textos y se unen los consejos")
            merged = MergeOutput(resumen=data.resumen, que_hacer=current["que_hacer"], consejos=_unique(data.consejos + new.consejos))
        data.resumen = merged.resumen
        data.consejos = merged.consejos
        if isinstance(data, LugarData):
            data.que_hacer = merged.que_hacer

    def _create_failure(self, ctx: JobContext, layout: Layout) -> str:
        fetch = ctx.result("fetch", FetchResult)
        transcript = ctx.result("transcribe", Transcript)
        extract = ctx.result("extract", ExtractResult)
        meta = fetch.meta
        note = self._t.create_note(
            layout.revision, f"Extracción fallida: {meta.title or meta.url}", "text",
            render_failure(meta, transcript.text, extract.error or ""),
        )
        self._t.add_label(note.note_id, "jrTipo", "fallo")
        return note.note_id

    def _send_to_review(self, note_id: str, reasons: list[str], layout: Layout) -> None:
        note = self._t.get_note(note_id)
        if layout.revision not in note.parent_note_ids:
            self._t.clone(note_id, layout.revision)
        previous = (note.label("revisar") or "").split(",")
        upsert_labels(self._t, note, {"revisar": ",".join(_unique([r for r in previous + reasons if r]))})

    def _link_donde(self, extraction: Extraction, plan: ResolveResult, by_key: dict[str, PublishedNote]) -> None:
        lugar_notes: dict[str, str] = {}
        for item in plan.items:
            if item.kind != ItemKind.LUGAR:
                continue
            key = item.alias_of if item.action == "alias" else item.key
            if key in by_key:
                lugar_notes[normalize_name(extraction.lugares[item.index].nombre)] = by_key[key].note_id
        for item in plan.items:
            if item.kind != ItemKind.COSA or item.action == "alias" or item.key not in by_key:
                continue
            cosa = extraction.cosas[item.index]
            if not cosa.donde_lugares:
                continue
            note = self._t.get_note(by_key[item.key].note_id)
            linked = set(note.relations("dondeComprar"))
            for name in cosa.donde_lugares:
                target = lugar_notes.get(normalize_name(name))
                if target and target not in linked:
                    self._t.add_relation(note.note_id, "dondeComprar", target)
                    linked.add(target)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_publish.py -v`
Expected: all passed

- [ ] **Step 5: Write stage doc**

`docs/pipeline/07-publish.md`:

```markdown
# Etapa 7 — publish

**Qué hace:** escribe en Trilium según el plan de `resolve` y calcula el resultado final del job.

**Entrada:** resultados de `fetch`, `transcribe`, `extract`, `geocode` y `resolve`.
**Salida:** `PublishResult {notes: [PublishedNote], outcome}`. `outcome`: `no-japon` si se descartó; `revisar` si algún elemento tiene motivos de revisión; si no, `procesado`.

**Crear:** nota de texto en su sitio (Lugar → Mapa; Cosa → su categoría; Otro → Cultura), atributos gestionados, `~template` y adjunto `japan-reader.json`.
**Fusionar:** lee el adjunto, añade la fuente (o la actualiza si es el mismo bookmark), una llamada al LLM (`OPENROUTER_TEXT_MODEL`, prompt `prompts/merge.md`) reescribe Resumen, Qué hacer y Consejos, y se regenera el HTML conservando "Mis notas". Si el LLM devuelve algo inválido, se conservan los textos y se unen los consejos.
**Revisión:** clon en la Bandeja de revisión + `#revisar=<motivos>` (se acumulan).
**Extracción fallida:** nota en la Bandeja con caption, transcripción, error y enlace.
**Cosa con local concreto:** relación `~dondeComprar` hacia la nota Lugar del local.

**Idempotencia:** cada elemento publicado se registra en `state.db` (`published`). Si el job se reintenta, los elementos ya publicados no se repiten. Reprocesar la misma fuente no duplica la entrada de "Fuentes" ni llama al LLM.

**Fallos:** errores de Trilium → reintento; presupuesto de OpenRouter agotado → espera al día siguiente.
**Cómo probarla:** `uv run pytest tests/unit/test_publish.py`. Contra Trilium real: `uv run pytest -m integration -k trilium`.
```

- [ ] **Step 6: Commit**

```bash
git add src/japan_reader/stages/publish.py tests/unit/test_publish.py docs/pipeline/07-publish.md
git commit -m "feat: publish stage with merge, review inbox and store relations"
```

---

### Task 16: Pipeline, reintentos, avisos ntfy y servicio (bucle, reprocesado, estado)

**Files:**
- Create: `src/japan_reader/clients/ntfy.py`, `src/japan_reader/pipeline.py`, `src/japan_reader/service.py`
- Test: `tests/unit/test_ntfy.py`, `tests/unit/test_pipeline.py`, `tests/unit/test_service.py`

**Interfaces:**
- Consumes: `StateStore`, `Job`, `JobStatus`, `utcnow`; `JobContext`; `MarkStage`; `ingest`; errores; `Outcome`, `PublishResult`; `classify_url`; `KarakeepClient`.
- Produces:
  - `Notifier(url, topic, token, http=None)` con `enabled: bool` y `send(title, message, priority=3, tags=())` (nunca lanza).
  - `pipeline.STAGE_ORDER = ("fetch", "transcribe", "extract", "geocode", "resolve", "publish")`, `pipeline.BACKOFF` (5 esperas), `Stage` (Protocol), `Pipeline(state, stages, mark, notifier, data_dir, clock=utcnow)` con `run_due() -> int`, `run_job(job)`, `mark_failed(bookmark_id, reason)`, `notify_once(key, title, message)`.
  - `service.Service(karakeep, state, pipeline, notifier, settings, preflight, clock=...)` con `tick()`, `run_forever(sleep=time.sleep)`; `service.REPROCESS_FROM = ("fetch", "extract", "geocode", "resolve", "publish")`; `service.reprocess(state, karakeep, bookmark_id, from_stage) -> Job`; `service.format_status(state) -> str`; `service.SUMMARY_HOUR = 21`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_ntfy.py`:

```python
import json

import httpx
import respx

from japan_reader.clients.ntfy import Notifier


@respx.mock
def test_send_posts_json_with_token():
    route = respx.post("https://ntfy.example.com").mock(return_value=httpx.Response(200))

    Notifier("https://ntfy.example.com/", "japan", "tk").send("japan-reader: error", "Vídeo privado", priority=4, tags=["warning"])

    body = json.loads(route.calls[0].request.content)
    assert body == {"topic": "japan", "title": "japan-reader: error", "message": "Vídeo privado", "priority": 4, "tags": ["warning"]}
    assert route.calls[0].request.headers["Authorization"] == "Bearer tk"


def test_disabled_without_url():
    notifier = Notifier(None, None, None)
    assert notifier.enabled is False
    notifier.send("t", "m")


@respx.mock
def test_failures_never_raise():
    respx.post("https://ntfy.example.com").mock(side_effect=httpx.ConnectError("down"))
    Notifier("https://ntfy.example.com", "japan", None).send("t", "m")
```

`tests/unit/test_pipeline.py`:

```python
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import BaseModel

from japan_reader.errors import ConfigError, PermanentError, QuotaExceeded, TransientError
from japan_reader.models import MarkResult, Outcome, PublishResult
from japan_reader.pipeline import BACKOFF, Pipeline
from japan_reader.sources import ContentHint, Platform
from japan_reader.state import JobStatus, StateStore

NOW = datetime(2026, 9, 28, 10, 0, tzinfo=UTC)


class Dummy(BaseModel):
    value: int = 1


class Step:
    def __init__(self, name, error=None, result=None):
        self.name = name
        self.error = error
        self.result = result or Dummy()
        self.result_model = type(self.result)
        self.calls = 0

    def run(self, ctx):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


class FakeMark:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def run(self, bookmark_id, outcome):
        self.calls.append((bookmark_id, outcome))
        if self.error:
            raise self.error
        return MarkResult(tag=f"jr:{outcome.value}", archived=outcome != Outcome.ERROR)


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def send(self, title, message, priority=3, tags=()):
        self.sent.append((title, message))


@pytest.fixture
def state(tmp_path):
    return StateStore(tmp_path / "state.db", clock=lambda: NOW)


def _pipeline(tmp_path, state, fetch_error=None, mark=None):
    fetch = Step("fetch", fetch_error)
    publish = Step("publish", result=PublishResult(outcome=Outcome.PROCESADO))
    notifier = FakeNotifier()
    mark = mark or FakeMark()
    pipeline = Pipeline(state, [fetch, publish], mark, notifier, tmp_path / "data", clock=lambda: NOW)
    return pipeline, fetch, publish, mark, notifier


def _add(state, bid="b1", platform=Platform.YOUTUBE):
    state.add_job(bid, f"https://youtu.be/{bid}", platform, ContentHint.VIDEO if platform else None)


def test_success_runs_all_stages_and_marks(tmp_path, state):
    _add(state)
    pipeline, fetch, publish, mark, _ = _pipeline(tmp_path, state)

    assert pipeline.run_due() == 1

    job = state.get_job("b1")
    assert job.status == JobStatus.DONE and job.outcome == Outcome.PROCESADO
    assert mark.calls == [("b1", Outcome.PROCESADO)]
    assert state.load_stage("b1", "fetch", Dummy) == Dummy()


def test_resume_skips_saved_stages(tmp_path, state):
    _add(state)
    state.save_stage("b1", "fetch", Dummy(value=7))
    pipeline, fetch, *_ = _pipeline(tmp_path, state)
    pipeline.run_due()
    assert fetch.calls == 0


def test_transient_error_schedules_retry(tmp_path, state):
    _add(state)
    pipeline, _, _, mark, _ = _pipeline(tmp_path, state, TransientError("timeout"))

    pipeline.run_due()

    job = state.get_job("b1")
    assert job.status == JobStatus.PENDING and job.attempts == 1
    assert job.next_attempt_at == NOW + BACKOFF[0]
    assert mark.calls == []


def test_unexpected_exception_is_retried(tmp_path, state):
    _add(state)
    pipeline, *_ = _pipeline(tmp_path, state, ValueError("bug"))
    pipeline.run_due()
    assert state.get_job("b1").attempts == 1


def test_retries_exhausted_marks_error_and_notifies(tmp_path, state):
    _add(state)
    for _ in range(len(BACKOFF)):
        state.schedule_retry("b1", NOW - timedelta(minutes=1), "timeout")
    pipeline, _, _, mark, notifier = _pipeline(tmp_path, state, TransientError("timeout"))

    pipeline.run_due()

    job = state.get_job("b1")
    assert job.status == JobStatus.ERROR and "agotados los reintentos" in job.last_error
    assert mark.calls == [("b1", Outcome.ERROR)]
    assert len(notifier.sent) == 1


def test_permanent_error(tmp_path, state):
    _add(state)
    pipeline, _, _, mark, notifier = _pipeline(tmp_path, state, PermanentError("Private video"))

    pipeline.run_due()

    assert state.get_job("b1").last_error == "Private video"
    assert mark.calls == [("b1", Outcome.ERROR)]
    assert "Private video" in notifier.sent[0][1]


def test_quota_waits_until_tomorrow_and_notifies_once(tmp_path, state):
    _add(state, "b1")
    _add(state, "b2")
    pipeline, _, _, _, notifier = _pipeline(tmp_path, state, QuotaExceeded("límite diario alcanzado: places_calls (150)"))

    pipeline.run_due()

    job = state.get_job("b1")
    assert job.attempts == 0
    assert job.next_attempt_at == datetime(2026, 9, 29, 0, 5, tzinfo=UTC)
    assert len(notifier.sent) == 1


def test_config_error_propagates_without_touching_job(tmp_path, state):
    _add(state)
    pipeline, *_ = _pipeline(tmp_path, state, ConfigError("API key"))
    with pytest.raises(ConfigError):
        pipeline.run_due()
    job = state.get_job("b1")
    assert job.status == JobStatus.PENDING and job.attempts == 0


def test_unsupported_source_is_failed_without_stages(tmp_path, state):
    _add(state, platform=None)
    pipeline, fetch, _, mark, _ = _pipeline(tmp_path, state)

    pipeline.run_due()

    assert fetch.calls == 0
    assert state.get_job("b1").last_error == "fuente no soportada"
    assert mark.calls == [("b1", Outcome.ERROR)]


def test_failing_to_mark_error_still_finishes_job(tmp_path, state):
    _add(state)
    pipeline, *_ = _pipeline(tmp_path, state, PermanentError("borrado"), mark=FakeMark(TransientError("karakeep caído")))
    pipeline.run_due()
    assert state.get_job("b1").status == JobStatus.ERROR
```

`tests/unit/test_service.py`:

```python
from datetime import UTC, datetime

import pytest
from pydantic import BaseModel

from fakes import FakeKarakeep
from japan_reader.clients.karakeep import Bookmark
from japan_reader.errors import ConfigError
from japan_reader.models import Outcome
from japan_reader.pipeline import STAGE_ORDER
from japan_reader.service import Service, format_status, reprocess
from japan_reader.sources import ContentHint, Platform
from japan_reader.state import JobStatus, StateStore


class FakePipeline:
    def __init__(self, error=None):
        self.error = error
        self.runs = 0
        self.alerts = []

    def run_due(self):
        self.runs += 1
        if self.error:
            raise self.error
        return 0

    def notify_once(self, key, title, message):
        self.alerts.append(key)


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def send(self, title, message, priority=3, tags=()):
        self.sent.append((title, message))


class Stop(Exception):
    pass


class Saved(BaseModel):
    value: int = 1


@pytest.fixture
def state(tmp_path):
    return StateStore(tmp_path / "state.db")


def _service(state, settings, pipeline, preflight=lambda: None, clock=None, notifier=None):
    karakeep = FakeKarakeep([Bookmark(id="b1", url="https://youtu.be/a")])
    return Service(karakeep, state, pipeline, notifier or FakeNotifier(), settings, preflight,
                   clock=clock or (lambda: datetime(2026, 9, 28, 10, tzinfo=UTC)))


def test_tick_runs_preflight_once_ingests_and_processes(state, settings):
    calls = []
    pipeline = FakePipeline()
    service = _service(state, settings, pipeline, preflight=lambda: calls.append(1))

    service.tick()
    service.tick()

    assert calls == [1]
    assert state.has_job("b1")
    assert pipeline.runs == 2


def test_run_forever_survives_config_errors(state, settings):
    pipeline = FakePipeline(ConfigError("Trilium sin #jrRoot"))
    service = _service(state, settings, pipeline)
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise Stop

    with pytest.raises(Stop):
        service.run_forever(sleep=sleep)

    assert sleeps == [600, 600]
    assert pipeline.alerts == ["config:Trilium sin #jrRoot", "config:Trilium sin #jrRoot"]


def test_daily_summary_sent_once_after_hour(state, settings):
    s = settings.model_copy(update={"ntfy_daily_summary": True})
    notifier = FakeNotifier()
    state.add_job("b9", "u", Platform.YOUTUBE, ContentHint.VIDEO)
    state.finish("b9", Outcome.PROCESADO)
    service = _service(state, s, FakePipeline(), clock=lambda: datetime(2026, 9, 28, 21, 30, tzinfo=UTC), notifier=notifier)

    service.tick()
    service.tick()

    assert notifier.sent == [("japan-reader: resumen del día", "procesado: 1")]


def test_reprocess_existing_job(state):
    state.add_job("b1", "https://youtu.be/a", Platform.YOUTUBE, ContentHint.VIDEO)
    for stage in STAGE_ORDER:
        state.save_stage("b1", stage, Saved())
    state.finish("b1", Outcome.PROCESADO)

    job = reprocess(state, FakeKarakeep(), "b1", "extract")

    assert job.status == JobStatus.PENDING
    assert state.load_stage("b1", "transcribe", Saved) is not None
    assert state.load_stage("b1", "extract", Saved) is None


def test_reprocess_unknown_job_is_created_from_karakeep(state):
    job = reprocess(state, FakeKarakeep([Bookmark(id="b7", url="https://www.instagram.com/p/X/")]), "b7", "fetch")
    assert job.platform == Platform.INSTAGRAM and job.hint == ContentHint.POST


def test_reprocess_rejects_invalid_stage(state):
    with pytest.raises(ValueError):
        reprocess(state, FakeKarakeep(), "b1", "transcribe")


def test_format_status(state):
    state.add_job("b1", "https://youtu.be/a", Platform.YOUTUBE, ContentHint.VIDEO)
    state.add_job("b2", "https://youtu.be/b", Platform.YOUTUBE, ContentHint.VIDEO)
    state.finish("b2", Outcome.ERROR, "Private video")
    state.add_counter("openrouter_usd", 0.1234)
    state.add_counter("places_calls", 3)

    text = format_status(state)

    assert "pendiente: 1" in text and "error: 1" in text
    assert "OpenRouter 0.1234 USD" in text and "Places 3 llamadas" in text
    assert "b2 https://youtu.be/b — Private video" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_ntfy.py tests/unit/test_pipeline.py tests/unit/test_service.py -v`
Expected: FAIL con `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

`src/japan_reader/clients/ntfy.py`:

```python
import logging
from collections.abc import Sequence

import httpx

log = logging.getLogger(__name__)


class Notifier:
    """Avisos por ntfy (publicación JSON en la raíz del servidor). Nunca interrumpe el servicio."""

    def __init__(self, url: str | None, topic: str | None, token: str | None, http: httpx.Client | None = None) -> None:
        self._url = url.rstrip("/") if url else None
        self._topic = topic
        self._token = token
        self._http = http or httpx.Client(timeout=15)

    @property
    def enabled(self) -> bool:
        return bool(self._url and self._topic)

    def send(self, title: str, message: str, priority: int = 3, tags: Sequence[str] = ()) -> None:
        if not self.enabled:
            log.info("ntfy desactivado; aviso no enviado: %s", title)
            return
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        body = {"topic": self._topic, "title": title, "message": message, "priority": priority, "tags": list(tags)}
        try:
            self._http.post(self._url, json=body, headers=headers).raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("no se pudo enviar el aviso ntfy '%s': %s", title, exc)
```

`src/japan_reader/pipeline.py`:

```python
import logging
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from japan_reader.clients.ntfy import Notifier
from japan_reader.context import JobContext
from japan_reader.errors import ConfigError, JapanReaderError, PermanentError, QuotaExceeded
from japan_reader.models import Outcome, PublishResult
from japan_reader.stages.mark import MarkStage
from japan_reader.state import Job, StateStore, utcnow

log = logging.getLogger(__name__)

STAGE_ORDER = ("fetch", "transcribe", "extract", "geocode", "resolve", "publish")
BACKOFF = (
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=30),
    timedelta(hours=2),
    timedelta(hours=2),
)


class Stage(Protocol):
    name: str
    result_model: type[BaseModel]

    def run(self, ctx: JobContext) -> BaseModel: ...


class Pipeline:
    """Ejecuta las etapas de cada job en orden, persistiendo cada resultado y aplicando la política de errores."""

    def __init__(
        self,
        state: StateStore,
        stages: Sequence[Stage],
        mark: MarkStage,
        notifier: Notifier,
        data_dir: Path,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._state = state
        self._stages = list(stages)
        self._mark = mark
        self._notifier = notifier
        self._data_dir = data_dir
        self._clock = clock

    def run_due(self) -> int:
        jobs = self._state.due_jobs()
        for job in jobs:
            self.run_job(job)
        return len(jobs)

    def run_job(self, job: Job) -> None:
        if job.platform is None:
            self.mark_failed(job.bookmark_id, "fuente no soportada")
            return
        ctx = JobContext(job=job, workdir=self._data_dir / "jobs" / job.bookmark_id)
        ctx.workdir.mkdir(parents=True, exist_ok=True)
        try:
            for stage in self._stages:
                result = self._state.load_stage(job.bookmark_id, stage.name, stage.result_model)
                if result is None:
                    log.info("bookmark=%s etapa=%s", job.bookmark_id, stage.name)
                    result = stage.run(ctx)
                    self._state.save_stage(job.bookmark_id, stage.name, result)
                ctx.results[stage.name] = result
            outcome = ctx.result("publish", PublishResult).outcome
            self._mark.run(job.bookmark_id, outcome)
            self._state.finish(job.bookmark_id, outcome)
            log.info("bookmark=%s terminado resultado=%s", job.bookmark_id, outcome)
        except ConfigError:
            raise
        except QuotaExceeded as exc:
            self._state.schedule_retry(job.bookmark_id, self._tomorrow(), str(exc), count_attempt=False)
            self.notify_once(f"quota:{exc}", "japan-reader: límite diario alcanzado", f"{exc}. Se reanuda mañana.")
        except PermanentError as exc:
            self.mark_failed(job.bookmark_id, str(exc))
        except Exception as exc:
            log.exception("bookmark=%s fallo en el intento %d", job.bookmark_id, job.attempts + 1)
            attempt = job.attempts + 1
            if attempt > len(BACKOFF):
                self.mark_failed(job.bookmark_id, f"agotados los reintentos: {exc}")
            else:
                self._state.schedule_retry(job.bookmark_id, self._clock() + BACKOFF[attempt - 1], str(exc))

    def mark_failed(self, bookmark_id: str, reason: str) -> None:
        job = self._state.get_job(bookmark_id)
        try:
            self._mark.run(bookmark_id, Outcome.ERROR)
        except JapanReaderError as exc:
            log.warning("bookmark=%s no se pudo etiquetar jr:error: %s", bookmark_id, exc)
        self._state.finish(bookmark_id, Outcome.ERROR, reason)
        url = job.url if job else bookmark_id
        log.warning("bookmark=%s error definitivo: %s", bookmark_id, reason)
        self._notifier.send("japan-reader: error", f"{url}\n{reason}", priority=4, tags=["warning"])

    def notify_once(self, key: str, title: str, message: str) -> None:
        """Un aviso por clave y día."""
        counter = f"alert:{key}"
        if self._state.get_counter(counter) == 0:
            self._state.add_counter(counter, 1)
            self._notifier.send(title, message, priority=4, tags=["warning"])

    def _tomorrow(self) -> datetime:
        return (self._clock() + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
```

`src/japan_reader/service.py`:

```python
import logging
import time
from collections.abc import Callable
from datetime import datetime

from japan_reader.clients.karakeep import KarakeepClient
from japan_reader.clients.ntfy import Notifier
from japan_reader.config import Settings
from japan_reader.errors import ConfigError
from japan_reader.ingest import ingest
from japan_reader.pipeline import STAGE_ORDER, Pipeline
from japan_reader.sources import classify_url
from japan_reader.state import Job, JobStatus, StateStore

log = logging.getLogger(__name__)

REPROCESS_FROM = ("fetch", "extract", "geocode", "resolve", "publish")
SUMMARY_HOUR = 21


def _local_now() -> datetime:
    return datetime.now().astimezone()


class Service:
    """Bucle principal: preflight, ingest, procesar la cola y resumen diario opcional."""

    def __init__(
        self,
        karakeep: KarakeepClient,
        state: StateStore,
        pipeline: Pipeline,
        notifier: Notifier,
        settings: Settings,
        preflight: Callable[[], None],
        clock: Callable[[], datetime] = _local_now,
    ) -> None:
        self._karakeep = karakeep
        self._state = state
        self._pipeline = pipeline
        self._notifier = notifier
        self._settings = settings
        self._preflight = preflight
        self._clock = clock
        self._ready = False

    def tick(self) -> None:
        if not self._ready:
            self._preflight()
            self._ready = True
        report = ingest(self._karakeep, self._state, self._settings.karakeep_list_id)
        processed = self._pipeline.run_due()
        if report.new or report.unsupported or processed:
            log.info("sondeo nuevos=%d no_soportados=%d procesados=%d", len(report.new), len(report.unsupported), processed)
        self._maybe_daily_summary()

    def run_forever(self, sleep: Callable[[float], None] = time.sleep) -> None:
        log.info("japan-reader en marcha; sondeo cada %d min", self._settings.poll_interval_minutes)
        while True:
            try:
                self.tick()
            except ConfigError as exc:
                self._ready = False
                log.error("error de configuración: %s", exc)
                self._pipeline.notify_once(f"config:{exc}", "japan-reader: error de configuración", str(exc))
            sleep(self._settings.poll_interval_minutes * 60)

    def _maybe_daily_summary(self) -> None:
        if not self._settings.ntfy_daily_summary or self._clock().hour < SUMMARY_HOUR:
            return
        if self._state.get_counter("summary_sent") > 0:
            return
        self._state.add_counter("summary_sent", 1)
        counts = self._state.finished_today()
        if counts:
            message = ", ".join(f"{key}: {value}" for key, value in sorted(counts.items()))
            self._notifier.send("japan-reader: resumen del día", message, priority=2)


def reprocess(state: StateStore, karakeep: KarakeepClient, bookmark_id: str, from_stage: str) -> Job:
    """Vuelve a poner un bookmark en la cola desde la etapa indicada."""
    if from_stage not in REPROCESS_FROM:
        raise ValueError(f"etapa no válida: {from_stage}. Opciones: {', '.join(REPROCESS_FROM)}")
    if not state.has_job(bookmark_id):
        bookmark = karakeep.get_bookmark(bookmark_id)
        classified = classify_url(bookmark.url) if bookmark.url else None
        platform, hint = classified if classified else (None, None)
        state.add_job(bookmark_id, bookmark.url or "", platform, hint)
    state.reset(bookmark_id)
    state.clear_stages_from(bookmark_id, from_stage, STAGE_ORDER)
    job = state.get_job(bookmark_id)
    assert job is not None
    return job


def format_status(state: StateStore) -> str:
    lines = ["Trabajos:"]
    lines += [f"  {key}: {value}" for key, value in sorted(state.status_counts().items())]
    lines.append(
        f"Consumo de hoy: OpenRouter {state.get_counter('openrouter_usd'):.4f} USD · "
        f"Places {int(state.get_counter('places_calls'))} llamadas"
    )
    retrying = [j for j in state.list_jobs(JobStatus.PENDING, limit=10) if j.last_error]
    if retrying:
        lines.append("Reintentando:")
        lines += [f"  {j.bookmark_id} {j.url} — intento {j.attempts}: {j.last_error}" for j in retrying]
    errors = state.list_jobs(JobStatus.ERROR, limit=10)
    if errors:
        lines.append("Últimos errores:")
        lines += [f"  {j.bookmark_id} {j.url} — {j.last_error}" for j in errors]
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_ntfy.py tests/unit/test_pipeline.py tests/unit/test_service.py -v`
Expected: all passed

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest`
Expected: all passed (sin tests de integración)

- [ ] **Step 6: Commit**

```bash
git add src/japan_reader tests/unit
git commit -m "feat: pipeline with retries and quotas, ntfy alerts and service loop"
```

---

### Task 17: Cableado (`wiring.py`), comprobaciones de arranque y CLI base

**Files:**
- Create: `src/japan_reader/wiring.py`, `src/japan_reader/cli.py`
- Test: `tests/unit/test_wiring_cli.py`

**Interfaces:**
- Consumes: todas las piezas anteriores.
- Produces:
  - `wiring.App` (dataclass: `settings, state, karakeep, trilium, llm, notifier, layout, llm_budget, ytdlp, gallery, transcribe, stages, pipeline, service`), `wiring.build_app(settings) -> App`, `wiring.preflight(settings, trilium, llm, layout)`.
  - `cli.app` (Typer) con comandos `run`, `run-once`, `init-trilium`, `status`, `reprocess BOOKMARK_ID --from STAGE`. Las Tareas 18 y 19 añaden `import-instagram` y `eval`.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_wiring_cli.py`:

```python
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from fakes import FakeKarakeep, FakeLLM, FakeTrilium
from japan_reader import cli
from japan_reader.errors import ConfigError
from japan_reader.pipeline import STAGE_ORDER
from japan_reader.state import StateStore
from japan_reader.trilium_layout import LayoutCache, init_layout, resolve_layout
from japan_reader.wiring import build_app, preflight


def test_build_app_orders_stages(settings):
    app = build_app(settings)
    assert [stage.name for stage in app.stages] == list(STAGE_ORDER)


@pytest.fixture
def trilium():
    fake = FakeTrilium()
    fake.add_note("root", "Ideas de Japón", labels={"jrRoot": ""})
    return fake


def test_preflight_ok(settings, trilium):
    init_layout(trilium)
    preflight(settings, trilium, FakeLLM([]), LayoutCache(lambda: resolve_layout(trilium)))


def test_preflight_requires_multimodal_model(settings, trilium):
    init_layout(trilium)
    with pytest.raises(ConfigError, match="multimodal"):
        preflight(settings, trilium, FakeLLM([], images=False), LayoutCache(lambda: resolve_layout(trilium)))


def test_preflight_requires_layout(settings, trilium):
    with pytest.raises(ConfigError, match="init-trilium"):
        preflight(settings, trilium, FakeLLM([]), LayoutCache(lambda: resolve_layout(trilium)))


def test_preflight_requires_existing_cookies(settings, trilium, tmp_path):
    init_layout(trilium)
    s = settings.model_copy(update={"instagram_cookies_file": tmp_path / "nope.txt"})
    with pytest.raises(ConfigError, match="cookies"):
        preflight(s, trilium, FakeLLM([]), LayoutCache(lambda: resolve_layout(trilium)))


@pytest.fixture
def fake_app(monkeypatch, tmp_path, settings):
    app = SimpleNamespace(settings=settings, state=StateStore(tmp_path / "state.db"), karakeep=FakeKarakeep())
    monkeypatch.setattr(cli, "_load", lambda: app)
    return app


def test_cli_help_lists_commands():
    result = CliRunner().invoke(cli.app, ["--help"])
    assert result.exit_code == 0
    for command in ("run", "run-once", "init-trilium", "status", "reprocess"):
        assert command in result.output


def test_cli_status(fake_app):
    result = CliRunner().invoke(cli.app, ["status"])
    assert result.exit_code == 0 and "Consumo de hoy" in result.output


def test_cli_reprocess_rejects_invalid_stage(fake_app):
    result = CliRunner().invoke(cli.app, ["reprocess", "b1", "--from", "transcribe"])
    assert result.exit_code == 1 and "etapa no válida" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_wiring_cli.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'japan_reader.wiring'`

- [ ] **Step 3: Write minimal implementation**

`src/japan_reader/wiring.py`:

```python
from dataclasses import dataclass

from japan_reader.clients.karakeep import KarakeepClient
from japan_reader.clients.ntfy import Notifier
from japan_reader.clients.openrouter import OpenRouterClient
from japan_reader.clients.places import PlacesClient
from japan_reader.clients.trilium import TriliumClient
from japan_reader.config import Settings
from japan_reader.errors import ConfigError
from japan_reader.media.downloaders import GalleryDlDownloader, YtDlpDownloader
from japan_reader.pipeline import Pipeline, Stage
from japan_reader.quota import DailyQuota
from japan_reader.service import Service
from japan_reader.stages.extract import ExtractStage
from japan_reader.stages.fetch import FetchStage
from japan_reader.stages.geocode import GeocodeStage
from japan_reader.stages.mark import MarkStage
from japan_reader.stages.publish import PublishStage
from japan_reader.stages.resolve import ResolveStage
from japan_reader.stages.transcribe import TranscribeStage, WhisperTranscriber
from japan_reader.state import StateStore
from japan_reader.trilium_layout import LayoutCache, resolve_layout


@dataclass
class App:
    settings: Settings
    state: StateStore
    karakeep: KarakeepClient
    trilium: TriliumClient
    llm: OpenRouterClient
    notifier: Notifier
    layout: LayoutCache
    llm_budget: DailyQuota
    ytdlp: YtDlpDownloader
    gallery: GalleryDlDownloader
    transcribe: TranscribeStage
    stages: list[Stage]
    pipeline: Pipeline
    service: Service


def preflight(settings: Settings, trilium: TriliumClient, llm: OpenRouterClient, layout: LayoutCache) -> None:
    """Comprobaciones antes de procesar: Trilium accesible y estructurado, modelo multimodal, cookies."""
    trilium.app_info()
    layout.refresh()
    if not llm.model_supports_images(settings.openrouter_model):
        raise ConfigError(f"OPENROUTER_MODEL={settings.openrouter_model} no es multimodal (no admite imágenes)")
    if settings.instagram_cookies_file and not settings.instagram_cookies_file.exists():
        raise ConfigError(f"No existe el fichero de cookies de Instagram: {settings.instagram_cookies_file}")


def build_app(settings: Settings) -> App:
    state = StateStore(settings.data_dir / "state.db")
    karakeep = KarakeepClient(settings.karakeep_url, settings.karakeep_api_key)
    trilium = TriliumClient(settings.trilium_url, settings.trilium_etapi_token)
    llm = OpenRouterClient(settings.openrouter_api_key)
    places = PlacesClient(settings.google_places_api_key)
    notifier = Notifier(settings.ntfy_url, settings.ntfy_topic, settings.ntfy_token)
    layout = LayoutCache(lambda: resolve_layout(trilium, settings.trilium_root_label))
    llm_budget = DailyQuota(state, "openrouter_usd", settings.openrouter_daily_budget_usd)
    places_quota = DailyQuota(state, "places_calls", settings.places_daily_limit)
    ytdlp = YtDlpDownloader(settings.instagram_cookies_file, settings.max_video_duration_min * 60)
    gallery = GalleryDlDownloader(settings.instagram_cookies_file)
    transcribe = TranscribeStage(
        WhisperTranscriber(settings.whisper_model, settings.whisper_compute_type, settings.whisper_download_root, settings.whisper_threads)
    )
    thresholds = settings.thresholds
    stages: list[Stage] = [
        FetchStage(settings, ytdlp, gallery, karakeep),
        transcribe,
        ExtractStage(settings, llm, llm_budget),
        GeocodeStage(places, places_quota, thresholds),
        ResolveStage(trilium, layout, thresholds),
        PublishStage(trilium, layout, llm, settings, llm_budget, state),
    ]
    pipeline = Pipeline(state, stages, MarkStage(karakeep), notifier, settings.data_dir)
    service = Service(karakeep, state, pipeline, notifier, settings, lambda: preflight(settings, trilium, llm, layout))
    return App(
        settings=settings, state=state, karakeep=karakeep, trilium=trilium, llm=llm, notifier=notifier,
        layout=layout, llm_budget=llm_budget, ytdlp=ytdlp, gallery=gallery, transcribe=transcribe,
        stages=stages, pipeline=pipeline, service=service,
    )
```

`src/japan_reader/cli.py`:

```python
from typing import Annotated

import typer
from pydantic import ValidationError

from japan_reader.config import Settings
from japan_reader.errors import ConfigError
from japan_reader.log import setup_logging
from japan_reader.service import REPROCESS_FROM, format_status, reprocess
from japan_reader.trilium_layout import init_layout
from japan_reader.wiring import App, build_app

app = typer.Typer(no_args_is_help=True, help="japan-reader: de Karakeep a Trilium (lugares y cosas de Japón).")


def _load() -> App:
    setup_logging()
    try:
        return build_app(Settings())
    except ValidationError as exc:
        typer.echo(f"Configuración incompleta (revisa .env):\n{exc}", err=True)
        raise typer.Exit(2) from exc


def _config_exit(exc: ConfigError) -> typer.Exit:
    typer.echo(f"Error de configuración: {exc}", err=True)
    return typer.Exit(2)


@app.command()
def run() -> None:
    """Bucle principal: sondea Karakeep y procesa la cola."""
    _load().service.run_forever()


@app.command("run-once")
def run_once() -> None:
    """Un único ciclo de sondeo y procesamiento."""
    try:
        _load().service.tick()
    except ConfigError as exc:
        raise _config_exit(exc) from exc


@app.command("init-trilium")
def init_trilium() -> None:
    """Crea bajo la nota #jrRoot la estructura que falte (idempotente)."""
    loaded = _load()
    try:
        layout = init_layout(loaded.trilium, loaded.settings.trilium_root_label)
    except ConfigError as exc:
        raise _config_exit(exc) from exc
    typer.echo(f"Estructura lista. Mapa={layout.mapa} Comprar={layout.comprar} Revisión={layout.revision}")


@app.command()
def status() -> None:
    """Cola, errores y consumo del día."""
    typer.echo(format_status(_load().state))


@app.command("reprocess")
def reprocess_cmd(
    bookmark_id: str,
    from_stage: Annotated[str, typer.Option("--from", help=" | ".join(REPROCESS_FROM))] = "fetch",
) -> None:
    """Vuelve a poner un bookmark en la cola desde una etapa."""
    loaded = _load()
    try:
        job = reprocess(loaded.state, loaded.karakeep, bookmark_id, from_stage)
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(1) from exc
    typer.echo(f"{job.bookmark_id} en cola desde '{from_stage}'; se procesará en el próximo ciclo.")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_wiring_cli.py -v`
Expected: all passed

- [ ] **Step 5: Check the installed entry point**

Run: `uv run japan-reader --help`
Expected: ayuda de Typer con `run`, `run-once`, `init-trilium`, `status`, `reprocess`.

- [ ] **Step 6: Commit**

```bash
git add src/japan_reader/wiring.py src/japan_reader/cli.py tests/unit/test_wiring_cli.py
git commit -m "feat: application wiring, startup checks and CLI"
```

---

### Task 18: Importación del historial de Instagram

**Files:**
- Create: `src/japan_reader/instagram_export.py`
- Modify: `src/japan_reader/cli.py` (comando `import-instagram`)
- Test: `tests/unit/test_instagram_export.py`

**Interfaces:**
- Consumes: `canonical_url`; `fold` (Tarea 2); `KarakeepClient.find_by_url/create_link/add_to_list`.
- Produces: `ExportedItem(url, collection)`, `parse_export(path: Path) -> list[ExportedItem]` (directorio, `.zip` o fichero JSON), `filter_collection(items, name) -> list[ExportedItem]`, `ImportReport(total, created, existing, by_collection)`, `import_items(items, karakeep, list_id, dry_run=False) -> ImportReport`, `format_import_report(report, dry_run) -> str`.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_instagram_export.py`:

```python
import json
import zipfile

import pytest

from fakes import FakeKarakeep
from japan_reader.clients.karakeep import Bookmark
from japan_reader.instagram_export import filter_collection, format_import_report, import_items, parse_export

COLLECTIONS = {"saved_saved_collections": [
    {"title": "Collection", "string_map_data": {"Name": {"value": "Japón"}, "Creation Time": {"timestamp": 1700000000}}},
    {"title": "user1", "string_map_data": {"Name": {"href": "https://www.instagram.com/reel/AAA/?igsh=1", "value": "user1"}, "Added Time": {"timestamp": 1}}},
    {"title": "user2", "string_map_data": {"Name": {"href": "https://www.instagram.com/p/BBB/", "value": "user2"}}},
    {"title": "Collection", "string_map_data": {"Name": {"value": "Recetas"}}},
    {"title": "user3", "string_map_data": {"Name": {"href": "https://www.instagram.com/reel/CCC/", "value": "user3"}}},
]}
POSTS = {"saved_saved_media": [
    {"title": "user1", "string_map_data": {"Saved on": {"href": "https://www.instagram.com/reel/AAA/", "timestamp": 1}}},
    {"title": "user4", "string_map_data": {"Saved on": {"href": "https://www.instagram.com/p/DDD/", "timestamp": 2}}},
    {"label_values": [{"label": "URL", "value": "https://www.instagram.com/reel/EEE/", "href": "https://www.instagram.com/reel/EEE/"}]},
]}


def _write_dir(root):
    saved = root / "your_instagram_activity" / "saved"
    saved.mkdir(parents=True)
    (saved / "saved_collections.json").write_text(json.dumps(COLLECTIONS), encoding="utf-8")
    (saved / "saved_posts.json").write_text(json.dumps(POSTS), encoding="utf-8")
    return root


EXPECTED = [
    ("https://www.instagram.com/reel/AAA/", "Japón"),
    ("https://www.instagram.com/p/BBB/", "Japón"),
    ("https://www.instagram.com/reel/CCC/", "Recetas"),
    ("https://www.instagram.com/p/DDD/", None),
    ("https://www.instagram.com/reel/EEE/", None),
]


def test_parse_directory(tmp_path):
    items = parse_export(_write_dir(tmp_path / "export"))
    assert [(i.url, i.collection) for i in items] == EXPECTED


def test_parse_zip(tmp_path):
    root = _write_dir(tmp_path / "export")
    archive = tmp_path / "instagram.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for path in root.rglob("*.json"):
            zf.write(path, path.relative_to(root))
    assert [(i.url, i.collection) for i in parse_export(archive)] == EXPECTED


def test_missing_files(tmp_path):
    with pytest.raises(FileNotFoundError):
        parse_export(tmp_path)


def test_filter_collection_ignores_case_and_accents(tmp_path):
    items = parse_export(_write_dir(tmp_path / "export"))
    assert [i.url for i in filter_collection(items, "japon")] == [
        "https://www.instagram.com/reel/AAA/",
        "https://www.instagram.com/p/BBB/",
    ]


def test_import_items_creates_or_reuses_and_adds_to_list(tmp_path):
    items = filter_collection(parse_export(_write_dir(tmp_path / "export")), "Japón")
    karakeep = FakeKarakeep([Bookmark(id="old", url="https://www.instagram.com/reel/AAA/")])
    karakeep.lists["L1"] = []

    report = import_items(items, karakeep, "L1")

    assert (report.total, report.created, report.existing) == (2, 1, 1)
    assert len(karakeep.lists["L1"]) == 2 and "old" in karakeep.lists["L1"]
    assert "Creados: 1" in format_import_report(report, dry_run=False)


def test_dry_run_does_not_touch_karakeep(tmp_path):
    items = parse_export(_write_dir(tmp_path / "export"))
    karakeep = FakeKarakeep()

    report = import_items(items, karakeep, "L1", dry_run=True)

    assert report.total == 5 and report.created == 0
    assert report.by_collection == {"Japón": 2, "Recetas": 1, "(sin colección)": 2}
    assert karakeep.bookmarks == {}
    assert "simulación" in format_import_report(report, dry_run=True)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_instagram_export.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'japan_reader.instagram_export'`

- [ ] **Step 3: Write minimal implementation**

`src/japan_reader/instagram_export.py`:

```python
import json
import re
import zipfile
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from japan_reader.clients.karakeep import KarakeepClient
from japan_reader.sources import canonical_url
from japan_reader.text import fold

_WANTED = ("saved_collections.json", "saved_posts.json")
_IG_URL = re.compile(r"https?://(?:www\.)?instagram\.com/(?:[\w.]+/)?(?:p|reels?|tv)/[\w-]+", re.I)
NO_COLLECTION = "(sin colección)"


@dataclass(frozen=True)
class ExportedItem:
    url: str
    collection: str | None


@dataclass
class ImportReport:
    total: int = 0
    created: int = 0
    existing: int = 0
    by_collection: dict[str, int] = field(default_factory=dict)


def _load_files(path: Path) -> list[tuple[str, object]]:
    found: list[tuple[str, object]] = []
    if path.is_file() and path.suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            for name in sorted(archive.namelist()):
                if name.endswith(_WANTED):
                    found.append((name, json.loads(archive.read(name))))
    elif path.is_dir():
        for file in sorted(path.rglob("*.json")):
            if file.name in _WANTED:
                found.append((file.name, json.loads(file.read_text(encoding="utf-8"))))
    elif path.is_file():
        found.append((path.name, json.loads(path.read_text(encoding="utf-8"))))
    if not found:
        raise FileNotFoundError(f"No encuentro {' ni '.join(_WANTED)} en {path}")
    return found


def _entries(data: object) -> list[dict]:
    if isinstance(data, list):
        return [e for e in data if isinstance(e, dict)]
    if isinstance(data, dict):
        for value in data.values():
            if isinstance(value, list):
                return [e for e in value if isinstance(e, dict)]
    return []


def _strings(obj: object) -> Iterator[str]:
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for value in obj.values():
            yield from _strings(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _strings(value)


def _collection_name(entry: dict) -> str | None:
    for value in (entry.get("string_map_data") or {}).values():
        if isinstance(value, dict) and value.get("value") and not value.get("href"):
            return value["value"]
    for value in entry.get("label_values") or []:
        if isinstance(value, dict) and value.get("value") and not value.get("href"):
            return value["value"]
    return entry.get("title")


def parse_export(path: Path) -> list[ExportedItem]:
    """Lee la exportación oficial de Instagram (carpeta, .zip o JSON suelto).

    En `saved_collections.json` cada colección empieza con una entrada sin URL (su nombre) seguida de sus posts.
    Un post guardado en una colección y también en `saved_posts.json` se queda con la colección.
    """
    by_url: dict[str, ExportedItem] = {}
    for name, data in _load_files(path):
        in_collections = "collections" in name
        current: str | None = None
        for entry in _entries(data):
            urls = list(dict.fromkeys(canonical_url(m.group(0)) for s in _strings(entry) if (m := _IG_URL.match(s))))
            if not urls:
                if in_collections:
                    current = _collection_name(entry)
                continue
            for url in urls:
                item = ExportedItem(url=url, collection=current if in_collections else None)
                previous = by_url.get(url)
                if previous is None or (previous.collection is None and item.collection):
                    by_url[url] = item
    return list(by_url.values())


def filter_collection(items: list[ExportedItem], name: str) -> list[ExportedItem]:
    wanted = fold(name).strip()
    return [item for item in items if item.collection and fold(item.collection).strip() == wanted]


def import_items(items: list[ExportedItem], karakeep: KarakeepClient, list_id: str, dry_run: bool = False) -> ImportReport:
    report = ImportReport(total=len(items), by_collection=dict(Counter(i.collection or NO_COLLECTION for i in items)))
    if dry_run:
        return report
    for item in items:
        bookmark_id = karakeep.find_by_url(item.url)
        if bookmark_id:
            report.existing += 1
        else:
            bookmark_id = karakeep.create_link(item.url)
            report.created += 1
        karakeep.add_to_list(list_id, bookmark_id)
    return report


def format_import_report(report: ImportReport, dry_run: bool) -> str:
    lines = [f"Enlaces encontrados: {report.total}" + (" (simulación, no se ha tocado Karakeep)" if dry_run else "")]
    lines += [f"  {name}: {count}" for name, count in sorted(report.by_collection.items())]
    if not dry_run:
        lines.append(f"Creados: {report.created} · Ya existían: {report.existing}")
    return "\n".join(lines)
```

Añade a `src/japan_reader/cli.py` (imports arriba; comando al final):

```python
from pathlib import Path

from japan_reader.instagram_export import filter_collection, format_import_report, import_items, parse_export


@app.command("import-instagram")
def import_instagram(
    path: Path,
    collection: Annotated[str | None, typer.Option(help="Importar solo esta colección (p. ej. 'Japón')")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Solo contar, sin crear nada")] = False,
) -> None:
    """Importa a la lista de Karakeep los enlaces de la exportación de Instagram."""
    loaded = _load()
    items = parse_export(path)
    if collection:
        items = filter_collection(items, collection)
    report = import_items(items, loaded.karakeep, loaded.settings.karakeep_list_id, dry_run)
    typer.echo(format_import_report(report, dry_run))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_instagram_export.py tests/unit/test_wiring_cli.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add src/japan_reader/instagram_export.py src/japan_reader/cli.py tests/unit/test_instagram_export.py
git commit -m "feat: import saved Instagram links from the official data export"
```

> **Verificación con datos reales (antes de importar en serio):** cuando Fernando tenga su exportación, ejecutar `japan-reader import-instagram <ruta> --dry-run` y comparar los recuentos por colección con lo que ve en Instagram. Si el formato real difiere de los fixtures, añadir un fixture con la estructura real (sin datos personales) a `test_instagram_export.py` y ajustar `parse_export` hasta que pase.

---

### Task 19: Batería de evaluación del LLM (`eval`)

**Files:**
- Create: `src/japan_reader/evaluation.py`, `eval/cases.yaml`
- Modify: `src/japan_reader/cli.py` (comando `eval`)
- Test: `tests/unit/test_evaluation.py`

**Interfaces:**
- Consumes: `FetchStage`, `TranscribeStage`, `ExtractStage`; `JobContext`, `Job`, `JobStatus`, `utcnow`; `classify_url`; `japan_decision`; `normalize_name`, `similarity`; `Thresholds`.
- Produces: `Expect(japan, lugares, cosas)`, `EvalCase(id, url, expect)`, `CaseScore(...)`, `load_cases(path) -> list[EvalCase]`, `count_matches(expected, got) -> int`, `score_case(case, result, thresholds) -> CaseScore`, `format_table(scores, model, keyframes) -> str`, `EvalRunner(fetch, transcribe, cache_dir)` con `run(cases, extract, thresholds, keyframes) -> list[CaseScore]`.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_evaluation.py`:

```python
from builders import make_extraction, make_fetch, make_lugar, make_cosa
from japan_reader.config import Thresholds
from japan_reader.evaluation import EvalCase, EvalRunner, count_matches, format_table, load_cases, score_case
from japan_reader.models import ExtractResult, Transcript

CASE = EvalCase.model_validate({
    "id": "ramen", "url": "https://www.youtube.com/shorts/abc",
    "expect": {"japan": True, "lugares": ["Ichiran Shibuya", "Fushimi Inari"], "cosas": ["CoCo Ichibanya"]},
})


def test_count_matches_is_tolerant():
    assert count_matches(["Ichiran Shibuya", "Fushimi Inari"], ["ICHIRAN Shibuya", "Fushimi Inari Taisha"]) == 2
    assert count_matches(["Kinkaku-ji"], ["Tokyo Tower", "Nara Park"]) == 0


def test_score_case():
    extraction = make_extraction(lugares=[make_lugar(), make_lugar("Tokyo Tower")], cosas=[make_cosa()])
    score = score_case(CASE, ExtractResult(extraction=extraction, cost_usd=0.02), Thresholds())
    assert score.japan_ok is True
    assert (score.lugares_found, score.lugares_expected) == (1, 2)
    assert (score.cosas_found, score.cosas_expected) == (1, 1)
    assert score.extra == 1
    assert score.cost_usd == 0.02


def test_score_failed_extraction():
    score = score_case(CASE, ExtractResult(extraction=None, error="JSON"), Thresholds())
    assert score.japan_ok is False and score.error == "JSON"


def test_format_table_totals():
    extraction = make_extraction(lugares=[make_lugar()])
    table = format_table([score_case(CASE, ExtractResult(extraction=extraction, cost_usd=0.01), Thresholds())], "vision/model", True)
    assert "vision/model" in table and "fotogramas: sí" in table
    assert "ramen | ok | 1/2 | 0/1" in table
    assert "Lugares 1/2" in table


def test_load_cases(tmp_path):
    path = tmp_path / "cases.yaml"
    path.write_text("- id: a\n  url: https://youtu.be/x\n  expect: {japan: false}\n", encoding="utf-8")
    assert load_cases(path)[0].expect.japan is False
    path.write_text("# vacío\n", encoding="utf-8")
    assert load_cases(path) == []


class StubStage:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def run(self, ctx):
        self.calls += 1
        return self.result


class RecordingExtract:
    def __init__(self):
        self.keyframes_seen = []

    def run(self, ctx):
        self.keyframes_seen.append(list(ctx.results["fetch"].keyframes))
        return ExtractResult(extraction=make_extraction(lugares=[make_lugar()]))


def test_runner_caches_media_and_can_drop_keyframes(tmp_path):
    fetch = StubStage(make_fetch(keyframes=["frames/00_00.jpg"]))
    transcribe = StubStage(Transcript(text="hola", origin="whisper"))
    runner = EvalRunner(fetch, transcribe, tmp_path / "cache")
    extract = RecordingExtract()

    runner.run([CASE], extract, Thresholds(), keyframes=True)
    runner.run([CASE], extract, Thresholds(), keyframes=False)

    assert fetch.calls == 1 and transcribe.calls == 1
    assert extract.keyframes_seen == [["frames/00_00.jpg"], []]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_evaluation.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'japan_reader.evaluation'`

- [ ] **Step 3: Write minimal implementation**

`src/japan_reader/evaluation.py`:

```python
from pathlib import Path

import yaml
from pydantic import BaseModel

from japan_reader.config import Thresholds
from japan_reader.context import JobContext
from japan_reader.errors import JapanReaderError
from japan_reader.models import ExtractResult, FetchResult, Transcript
from japan_reader.rules import japan_decision
from japan_reader.sources import classify_url
from japan_reader.state import Job, JobStatus, utcnow
from japan_reader.text import normalize_name, similarity

NAME_MATCH = 0.8


class Expect(BaseModel):
    japan: bool
    lugares: list[str] = []
    cosas: list[str] = []


class EvalCase(BaseModel):
    id: str
    url: str
    expect: Expect


class CaseScore(BaseModel):
    id: str
    japan_ok: bool
    lugares_found: int = 0
    lugares_expected: int = 0
    cosas_found: int = 0
    cosas_expected: int = 0
    extra: int = 0
    cost_usd: float = 0.0
    error: str | None = None


def load_cases(path: Path) -> list[EvalCase]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return [EvalCase.model_validate(case) for case in data]


def count_matches(expected: list[str], got: list[str]) -> int:
    found = [normalize_name(g) for g in got if g]
    hits = 0
    for name in expected:
        wanted = normalize_name(name)
        if any(g and (wanted in g or g in wanted or similarity(wanted, g) >= NAME_MATCH) for g in found):
            hits += 1
    return hits


def score_case(case: EvalCase, result: ExtractResult, thresholds: Thresholds) -> CaseScore:
    expected_l, expected_c = len(case.expect.lugares), len(case.expect.cosas)
    extraction = result.extraction
    if extraction is None:
        return CaseScore(
            id=case.id, japan_ok=False, lugares_expected=expected_l, cosas_expected=expected_c,
            cost_usd=result.cost_usd, error=result.error or "extracción fallida",
        )
    is_japan = japan_decision(extraction, thresholds) != "no"
    lugar_names = [l.nombre for l in extraction.lugares] + [l.nombre_local for l in extraction.lugares if l.nombre_local]
    found_l = count_matches(case.expect.lugares, lugar_names)
    found_c = count_matches(case.expect.cosas, [c.nombre for c in extraction.cosas])
    return CaseScore(
        id=case.id, japan_ok=is_japan == case.expect.japan,
        lugares_found=found_l, lugares_expected=expected_l, cosas_found=found_c, cosas_expected=expected_c,
        extra=max(0, len(extraction.lugares) + len(extraction.cosas) - found_l - found_c), cost_usd=result.cost_usd,
    )


def format_table(scores: list[CaseScore], model: str, keyframes: bool) -> str:
    lines = [f"Modelo: {model} · fotogramas: {'sí' if keyframes else 'no'}", "caso | japón | lugares | cosas | extra | coste USD | error"]
    for s in scores:
        lines.append(
            f"{s.id} | {'ok' if s.japan_ok else 'FALLO'} | {s.lugares_found}/{s.lugares_expected} | "
            f"{s.cosas_found}/{s.cosas_expected} | {s.extra} | {s.cost_usd:.4f} | {s.error or ''}"
        )
    lines.append(
        f"TOTAL · Japón {sum(s.japan_ok for s in scores)}/{len(scores)} · "
        f"Lugares {sum(s.lugares_found for s in scores)}/{sum(s.lugares_expected for s in scores)} · "
        f"Cosas {sum(s.cosas_found for s in scores)}/{sum(s.cosas_expected for s in scores)} · "
        f"Extra {sum(s.extra for s in scores)} · Coste {sum(s.cost_usd for s in scores):.4f} USD"
    )
    return "\n".join(lines)


class EvalRunner:
    """Descarga y transcribe cada caso una vez (caché en disco) y solo repite la extracción."""

    def __init__(self, fetch, transcribe, cache_dir: Path) -> None:
        self._fetch = fetch
        self._transcribe = transcribe
        self._cache = cache_dir

    def _prepare(self, case: EvalCase) -> JobContext:
        classified = classify_url(case.url)
        if classified is None:
            raise ValueError(f"URL no soportada en el caso {case.id}: {case.url}")
        now = utcnow()
        job = Job(
            bookmark_id=f"eval-{case.id}", url=case.url, platform=classified[0], hint=classified[1],
            status=JobStatus.PENDING, attempts=0, next_attempt_at=None, last_error=None, outcome=None,
            created_at=now, updated_at=now,
        )
        ctx = JobContext(job=job, workdir=self._cache / case.id)
        ctx.workdir.mkdir(parents=True, exist_ok=True)
        fetch_file, transcript_file = ctx.workdir / "fetch.json", ctx.workdir / "transcript.json"
        if fetch_file.exists():
            ctx.results["fetch"] = FetchResult.model_validate_json(fetch_file.read_text(encoding="utf-8"))
        else:
            ctx.results["fetch"] = self._fetch.run(ctx)
            fetch_file.write_text(ctx.results["fetch"].model_dump_json(), encoding="utf-8")
        if transcript_file.exists():
            ctx.results["transcribe"] = Transcript.model_validate_json(transcript_file.read_text(encoding="utf-8"))
        else:
            ctx.results["transcribe"] = self._transcribe.run(ctx)
            transcript_file.write_text(ctx.results["transcribe"].model_dump_json(), encoding="utf-8")
        return ctx

    def run(self, cases: list[EvalCase], extract, thresholds: Thresholds, keyframes: bool) -> list[CaseScore]:
        scores = []
        for case in cases:
            try:
                ctx = self._prepare(case)
                if not keyframes:
                    ctx.results["fetch"] = ctx.result("fetch", FetchResult).model_copy(update={"keyframes": []})
                scores.append(score_case(case, extract.run(ctx), thresholds))
            except (JapanReaderError, ValueError) as exc:
                scores.append(CaseScore(id=case.id, japan_ok=False, error=str(exc)))
        return scores
```

`eval/cases.yaml`:

```yaml
# Casos de evaluación del LLM. Rellenar con 10-15 enlaces REALES guardados por Fernando.
# Incluir: Reels con el lugar solo escrito en pantalla, carruseles con texto en las imágenes,
# posts de una sola imagen, algún Short sin relación con Japón y alguno de "cosas" (souvenirs, cadenas).
#
# Formato de cada caso:
# - id: ramen-shibuya
#   url: https://www.instagram.com/reel/XXXXXXXX/
#   expect:
#     japan: true
#     lugares: ["Ichiran Shibuya"]
#     cosas: []
[]
```

Añade a `src/japan_reader/cli.py` (imports arriba; comando al final):

```python
from japan_reader.evaluation import EvalRunner, format_table, load_cases
from japan_reader.stages.extract import ExtractStage
from japan_reader.stages.fetch import FetchStage


@app.command("eval")
def eval_cmd(
    cases: Annotated[Path, typer.Option(help="Fichero YAML de casos")] = Path("eval/cases.yaml"),
    model: Annotated[str | None, typer.Option(help="Modelo de OpenRouter a evaluar (por defecto OPENROUTER_MODEL)")] = None,
    keyframes: Annotated[bool, typer.Option("--keyframes/--no-keyframes", help="Enviar fotogramas clave de los vídeos")] = True,
) -> None:
    """Compara modelos y el uso de fotogramas con casos reales (el coste cuenta en el presupuesto diario)."""
    loaded = _load()
    updates: dict = {"reel_keyframes_enabled": True}
    if model:
        updates |= {"openrouter_model": model, "openrouter_text_model": model}
    settings = loaded.settings.model_copy(update=updates)
    runner = EvalRunner(FetchStage(settings, loaded.ytdlp, loaded.gallery, loaded.karakeep), loaded.transcribe, Path("eval/.cache"))
    scores = runner.run(load_cases(cases), ExtractStage(settings, loaded.llm, loaded.llm_budget), settings.thresholds, keyframes)
    typer.echo(format_table(scores, settings.openrouter_model, keyframes))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_evaluation.py tests/unit/test_wiring_cli.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add src/japan_reader/evaluation.py src/japan_reader/cli.py eval/cases.yaml tests/unit/test_evaluation.py
git commit -m "feat: LLM evaluation harness with media cache and keyframes toggle"
```

---

### Task 20: Docker, Compose, `.env.example` y documentación de operación

**Files:**
- Create: `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `.env.example`, `README.md`, `docs/operations.md`

**Interfaces:**
- Consumes: CLI `japan-reader` (Tareas 17–19); red Docker externa `pangolin`.
- Produces: imagen `japan-reader:local`, servicio Compose `japan-reader`.

- [ ] **Step 1: Write the container files**

`Dockerfile`:

```dockerfile
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg ca-certificates tzdata \
 && rm -rf /var/lib/apt/lists/*
# Fija esta etiqueta a la versión de `uv --version` usada en desarrollo.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH" \
    DATA_DIR=/data \
    WHISPER_DOWNLOAD_ROOT=/models \
    TZ=Europe/Madrid
VOLUME ["/data", "/models"]
CMD ["japan-reader", "run"]
```

`.dockerignore`:

```
.venv
data
secrets
eval/.cache
.env
.git
.pytest_cache
**/__pycache__
```

`docker-compose.yml`:

```yaml
services:
  japan-reader:
    build: .
    image: japan-reader:local
    container_name: japan-reader
    restart: unless-stopped
    env_file: .env
    environment:
      DATA_DIR: /data
      WHISPER_DOWNLOAD_ROOT: /models
      TZ: Europe/Madrid
    volumes:
      - ./data:/data
      - whisper-models:/models
      - ./secrets:/secrets:ro
    networks:
      - pangolin
    deploy:
      resources:
        limits:
          cpus: "6"
          memory: 6g

networks:
  pangolin:
    external: true

volumes:
  whisper-models:
```

`.env.example`:

```bash
# --- Karakeep (misma red Docker "pangolin") ---
KARAKEEP_URL=http://karakeep-web:3000
KARAKEEP_API_KEY=            # Karakeep → Ajustes → API Keys
KARAKEEP_LIST_ID=            # id de la lista "Japón" (aparece en la URL de la lista)

# --- Trilium ---
TRILIUM_URL=http://trilium:8080
TRILIUM_ETAPI_TOKEN=         # Trilium → Opciones → ETAPI → Crear token
TRILIUM_ROOT_LABEL=jrRoot    # etiqueta puesta a mano en "Ideas de Japón"

# --- OpenRouter ---
OPENROUTER_API_KEY=
OPENROUTER_MODEL=            # multimodal (acepta imágenes); elegir con `japan-reader eval`
# OPENROUTER_TEXT_MODEL=     # opcional, más barato, para contenido sin imágenes y fusiones
OPENROUTER_DAILY_BUDGET_USD=1.0

# --- Google Places API (New) ---
GOOGLE_PLACES_API_KEY=       # restringida a "Places API (New)"
PLACES_DAILY_LIMIT=150       # ~4.500/mes < 5.000 gratis de Text Search Pro

# --- Whisper ---
WHISPER_MODEL=large-v3       # large-v3-turbo si hace falta más velocidad
WHISPER_COMPUTE_TYPE=int8
WHISPER_THREADS=6

# --- Medios ---
REEL_KEYFRAMES_ENABLED=true  # false = solo audio+texto en vídeos (los posts siguen con visión)
KEYFRAMES_MAX=6
POST_IMAGES_MAX=10
IMAGE_MAX_SIDE=1024
MAX_VIDEO_DURATION_MIN=15
# INSTAGRAM_COOKIES_FILE=/secrets/instagram_cookies.txt   # formato Netscape, cuenta secundaria

# --- Avisos ntfy ---
NTFY_URL=                    # p. ej. https://ntfy.tudominio
NTFY_TOPIC=japan-reader
NTFY_TOKEN=
NTFY_DAILY_SUMMARY=false

# --- Funcionamiento ---
POLL_INTERVAL_MINUTES=10
JAPAN_MIN_CONFIDENCE=0.4
JAPAN_REVIEW_CONFIDENCE=0.7
ITEM_REVIEW_CONFIDENCE=0.7
COSA_DUPLICATE_SIMILARITY=0.85
```

- [ ] **Step 2: Build and smoke-test the image**

Run:

```bash
docker compose build
docker compose run --rm --no-deps japan-reader japan-reader --help
```

Expected: la imagen se construye y la ayuda lista `run`, `run-once`, `init-trilium`, `status`, `reprocess`, `import-instagram`, `eval`.
(No ejecutes `docker compose up`: el despliegue lo hace Fernando en la Tarea 21.)

- [ ] **Step 3: Write `docs/operations.md`**

```markdown
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
    docker compose exec japan-reader japan-reader run-once
    docker compose exec japan-reader japan-reader reprocess <bookmarkId> --from extract
    docker compose logs -f japan-reader

`reprocess --from`: `fetch` (vuelve a descargar), `extract` (nuevo prompt o modelo, sin re-transcribir), `geocode`, `resolve`, `publish`. El bookmarkId está en la URL del bookmark en Karakeep.

## Cambiar de modelo
1. Rellena `eval/cases.yaml` con 10-15 casos reales.
2. `docker compose run --rm -v ./eval:/app/eval japan-reader japan-reader eval --model <modelo>` y lo mismo con `--no-keyframes`.
3. Elige por aciertos (columna Lugares) y coste; cambia `OPENROUTER_MODEL` en `.env` y `docker compose up -d`.
Si el coste de visión es alto: `REEL_KEYFRAMES_ENABLED=false`.

## Cookies de Instagram
Cuando aparezcan `jr:error` con "login required": exporta las cookies de instagram.com (formato Netscape) desde un navegador con una **cuenta secundaria** a `secrets/instagram_cookies.txt`, pon `INSTAGRAM_COOKIES_FILE=/secrets/instagram_cookies.txt` en `.env`, `docker compose up -d` y reprocesa los fallidos con `reprocess <id> --from fetch`. El servicio trabaja con una copia: el fichero original no se modifica.

## Importar el historial de Instagram
1. Instagram → Centro de cuentas → Tu información y permisos → Descargar tu información → solo "Guardado", formato **JSON**.
2. Copia el .zip al servidor, p. ej. `data/instagram.zip`.
3. `docker compose exec japan-reader japan-reader import-instagram /data/instagram.zip --collection "Japón" --dry-run`
4. Si los recuentos cuadran, repite sin `--dry-run`. El pipeline los procesa poco a poco respetando `PLACES_DAILY_LIMIT` y `OPENROUTER_DAILY_BUDGET_USD`.
Nota: si un enlace ya estaba en Karakeep con otra forma de URL (p. ej. con `?igsh=`), puede crearse un segundo bookmark; la nota de Trilium no se duplica.

## Avisos (ntfy)
Llegan avisos por: error definitivo de un enlace, error de configuración (el servicio se pausa hasta que se corrija), límite diario alcanzado. Con `NTFY_DAILY_SUMMARY=true`, resumen a partir de las 21:00.

## Costes y cuotas
- Google Cloud Console → APIs → Places API (New) → Cuotas: limita "SearchTextRequest per day" a ~200 como red de seguridad.
- OpenRouter: `OPENROUTER_DAILY_BUDGET_USD`. `status` muestra el consumo del día.

## Copias de seguridad
`data/state.db` guarda el estado de la cola. Si se pierde, no se reprocesan los bookmarks ya etiquetados `jr:*`; las notas de Trilium tienen su propio adjunto `japan-reader.json`.
```

- [ ] **Step 4: Write `README.md`**

```markdown
# japan-reader

Convierte YouTube Shorts, Instagram Reels y posts de Instagram guardados en Karakeep en una base de datos de viaje a Japón en Trilium: un **Geo Map** con una nota por lugar y una sección **Comprar y comer** para productos, platos y cadenas.

    Karakeep (lista "Japón") → yt-dlp / gallery-dl → faster-whisper → LLM (OpenRouter, multimodal)
      → Google Places → deduplicación → Trilium → etiqueta + archivo en Karakeep

## Puesta en marcha
1. `cp .env.example .env` y rellénalo.
2. En Trilium, añade la etiqueta `#jrRoot` a `Home › Viajes › Ideas de Japón`.
3. `docker compose build && docker compose run --rm japan-reader japan-reader init-trilium`
4. `docker compose up -d` y `docker compose logs -f japan-reader`.

## Comandos
`run` · `run-once` · `init-trilium` · `status` · `reprocess <id> --from <etapa>` · `import-instagram <export> [--collection] [--dry-run]` · `eval [--model] [--keyframes/--no-keyframes]`

## Documentación
- Diseño: `docs/superpowers/specs/2026-09-28-japan-reader-design.md`
- Etapas: `docs/pipeline/01-ingest.md` … `08-mark.md`
- Modelo de Trilium: `docs/trilium-model.md`
- Operación: `docs/operations.md`

## Desarrollo
    uv sync
    uv run pytest                 # unitarios, sin red
    uv run pytest -m integration  # contra servicios reales (ver tests/integration/test_live.py)
```

- [ ] **Step 5: Commit**

```bash
git add Dockerfile .dockerignore docker-compose.yml .env.example README.md docs/operations.md
git commit -m "chore: container image, compose service, env template and operations docs"
```

---

### Task 21: Pruebas de integración opt-in y puesta en marcha real

**Files:**
- Create: `tests/integration/test_live.py`

**Interfaces:**
- Consumes: `Settings`, clientes reales, `init_layout`, `YtDlpDownloader`, `WhisperTranscriber`, `extract_audio`.
- Variables de entorno de prueba: `JR_TEST_ROOT_LABEL` (p. ej. `jrRootTest`), `JR_TEST_LIST_ID`, `JR_TEST_SHORT_URL`, opcional `JR_TEST_WHISPER_MODEL` (por defecto `small`). Desde el host, Karakeep y Trilium se alcanzan en `http://localhost:3088` y `http://localhost:8750` (sobrescribe `KARAKEEP_URL` y `TRILIUM_URL` al lanzar las pruebas).

- [ ] **Step 1: Write the integration tests**

`tests/integration/test_live.py`:

```python
import os

import pytest

from japan_reader.clients.karakeep import KarakeepClient
from japan_reader.clients.trilium import TriliumClient
from japan_reader.config import Settings
from japan_reader.media.audio import extract_audio
from japan_reader.media.downloaders import YtDlpDownloader
from japan_reader.sources import Platform
from japan_reader.stages.transcribe import WhisperTranscriber
from japan_reader.trilium_layout import GEO_MAP_TEMPLATE, init_layout

pytestmark = pytest.mark.integration


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"falta la variable {name}")
    return value


@pytest.fixture
def live() -> Settings:
    return Settings()


def test_trilium_test_tree_and_geomap(live):
    label = _env("JR_TEST_ROOT_LABEL")
    trilium = TriliumClient(live.trilium_url, live.trilium_etapi_token)

    layout = init_layout(trilium, label)

    mapa = trilium.get_note(layout.mapa)
    assert mapa.type == "book"
    assert GEO_MAP_TEMPLATE in mapa.relations("template")


def test_karakeep_test_list_is_readable(live):
    list_id = _env("JR_TEST_LIST_ID")
    list(KarakeepClient(live.karakeep_url, live.karakeep_api_key).list_bookmarks(list_id))


def test_ytdlp_downloads_public_short(tmp_path):
    media = YtDlpDownloader(None, 900).download(_env("JR_TEST_SHORT_URL"), Platform.YOUTUBE, tmp_path)
    assert media.videos and media.videos[0].stat().st_size > 0


def test_whisper_transcribes_short(tmp_path, live):
    media = YtDlpDownloader(None, 900).download(_env("JR_TEST_SHORT_URL"), Platform.YOUTUBE, tmp_path / "raw")
    audio = extract_audio(media.videos[0], tmp_path / "a.wav")
    model = os.environ.get("JR_TEST_WHISPER_MODEL", "small")
    text, _ = WhisperTranscriber(model, "int8", live.whisper_download_root, 6).transcribe(audio)
    assert text.strip()
```

- [ ] **Step 2: Verify they are skipped by default**

Run: `uv run pytest`
Expected: todos los unitarios pasan; los de integración no se ejecutan (excluidos por `-m 'not integration'`).

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_live.py
git commit -m "test: opt-in integration tests against Trilium, Karakeep, yt-dlp and Whisper"
```

- [ ] **Step 4: Puesta en marcha (con Fernando; cada paso lo confirma él)**

1. **Trilium (pruebas):** crear una nota `Ideas de Japón (test)` con `#jrRootTest`, crear token ETAPI y ejecutar:
   `JR_TEST_ROOT_LABEL=jrRootTest TRILIUM_URL=http://localhost:8750 KARAKEEP_URL=http://localhost:3088 uv run pytest -m integration -k trilium`
   Abrir en Trilium la nota "Mapa de lugares" de pruebas y comprobar que se ve como mapa. Después, borrar el árbol de pruebas.
2. **Karakeep:** crear la lista "Japón" (y una lista de pruebas), API key; `JR_TEST_LIST_ID=<id> ... -k karakeep`.
3. **yt-dlp y Whisper:** `JR_TEST_SHORT_URL=<un Short público> ... -k "ytdlp or whisper"`.
4. **Google Cloud:** activar "Places API (New)", crear API key restringida a esa API y fijar la cuota diaria (~200).
5. **OpenRouter:** crear key; rellenar `eval/cases.yaml` con 10-15 casos reales; ejecutar `japan-reader eval` con 2-3 modelos multimodales, con y sin fotogramas; fijar `OPENROUTER_MODEL` (y `REEL_KEYFRAMES_ENABLED`) según resultados.
6. **ntfy:** topic y token en `.env`.
7. **Producción:** poner `#jrRoot` en `Home › Viajes › Ideas de Japón`; `docker compose run --rm japan-reader japan-reader init-trilium`; `docker compose up -d`.
8. **Prueba de humo:** guardar en la lista "Japón" un Reel de un lugar conocido y un post de souvenirs; en ≤15 min comprobar las notas en Trilium (mapa y "Comprar y comer"), las etiquetas `jr:*` y el archivado en Karakeep, y `japan-reader status`.
9. **Histórico:** `import-instagram ... --dry-run`, revisar recuentos, importar.

