from dataclasses import dataclass

from japan_reader.clients.karakeep import KarakeepClient
from japan_reader.clients.ntfy import Notifier
from japan_reader.clients.openrouter import OpenRouterClient, supports_images, supports_structured_output
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
    """Comprobaciones antes de procesar: Trilium accesible y estructurado, modelos válidos, cookies."""
    trilium.app_info()
    layout.refresh()
    models = [("OPENROUTER_MODEL", settings.openrouter_model)]
    if settings.text_model != settings.openrouter_model:
        models.append(("OPENROUTER_TEXT_MODEL", settings.text_model))
    infos: dict[str, dict] = {}
    for variable, model in models:
        info = llm.model_info(model)
        if info is None:
            raise ConfigError(f"{variable}={model} no existe en OpenRouter (revisa el nombre del modelo)")
        if not supports_structured_output(info):
            raise ConfigError(
                f"{variable}={model} no admite salida JSON estructurada (response_format/structured_outputs); elige otro modelo"
            )
        infos[model] = info
    if not supports_images(infos[settings.openrouter_model]):
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
