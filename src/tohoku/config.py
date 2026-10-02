from dataclasses import dataclass
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True)
class Thresholds:
    """Umbrales de la red de seguridad."""

    destination_min: float = 0.4
    destination_review: float = 0.7
    item_review: float = 0.7
    cosa_duplicate: float = 0.85


class Settings(BaseSettings):
    """Configuración del servicio, leída de variables de entorno o de `.env`."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    karakeep_url: str
    karakeep_api_key: str

    trilium_url: str
    trilium_etapi_token: str

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
    instagram_min_interval_seconds: int = 20

    ntfy_url: str | None = None
    ntfy_topic: str | None = None
    ntfy_token: str | None = None
    ntfy_daily_summary: bool = False

    poll_interval_minutes: int = 10
    data_dir: Path = Path("data")
    destinos_file: Path = Path("config/destinos.yaml")

    destination_min_confidence: float = 0.4
    destination_review_confidence: float = 0.7
    item_review_confidence: float = 0.7
    cosa_duplicate_similarity: float = 0.85

    @field_validator("instagram_cookies_file", mode="before")
    @classmethod
    def _empty_path_is_none(cls, value: object) -> object:
        """`INSTAGRAM_COOKIES_FILE=` (vacío) significa "sin cookies", no `Path('.')`."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def text_model(self) -> str:
        """Modelo para llamadas sin imágenes (contenido sin imágenes y fusiones)."""
        return self.openrouter_text_model or self.openrouter_model

    @property
    def thresholds(self) -> Thresholds:
        return Thresholds(
            destination_min=self.destination_min_confidence,
            destination_review=self.destination_review_confidence,
            item_review=self.item_review_confidence,
            cosa_duplicate=self.cosa_duplicate_similarity,
        )
