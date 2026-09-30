from dataclasses import dataclass

from tohoku.clients.karakeep import KarakeepClient
from tohoku.clients.ntfy import Notifier
from tohoku.clients.openrouter import OpenRouterClient, supports_images, supports_structured_output
from tohoku.clients.places import PlacesClient
from tohoku.clients.trilium import TriliumClient
from tohoku.config import Settings
from tohoku.destinations import Destination, DestinationsConfig, load_destinations
from tohoku.errors import ConfigError
from tohoku.flows.base import FlowDeps, FlowRuntime
from tohoku.flows.registry import FLOWS
from tohoku.media.downloaders import GalleryDlDownloader, YtDlpDownloader
from tohoku.pipeline import Pipeline, Stage
from tohoku.quota import DailyQuota
from tohoku.service import Service
from tohoku.stages.fetch import FetchStage
from tohoku.stages.mark import MarkStage
from tohoku.stages.transcribe import TranscribeStage, WhisperTranscriber
from tohoku.state import StateStore
from tohoku.trilium_layout import LayoutCache


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
    destinations: DestinationsConfig
    destination: Destination
    runtime: FlowRuntime


def preflight(settings: Settings, trilium: TriliumClient, llm: OpenRouterClient, layout: FlowRuntime | LayoutCache) -> None:
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
    llm_budget = DailyQuota(state, "openrouter_usd", settings.openrouter_daily_budget_usd)
    places_quota = DailyQuota(state, "places_calls", settings.places_daily_limit)
    ytdlp = YtDlpDownloader(settings.instagram_cookies_file, settings.max_video_duration_min * 60)
    gallery = GalleryDlDownloader(settings.instagram_cookies_file)
    transcribe = TranscribeStage(
        WhisperTranscriber(settings.whisper_model, settings.whisper_compute_type, settings.whisper_download_root, settings.whisper_threads)
    )
    destinations = load_destinations(settings.destinos_file, FLOWS)
    destination = destinations.single_destination()
    deps = FlowDeps(settings=settings, state=state, trilium=trilium, llm=llm, places=places,
                    llm_budget=llm_budget, places_quota=places_quota)
    runtime = FLOWS[destination.flujo].build(destination, deps)
    stages: list[Stage] = [FetchStage(settings, ytdlp, gallery, karakeep), transcribe, *runtime.stages]
    pipeline = Pipeline(state, stages, MarkStage(karakeep), notifier, settings.data_dir)
    service = Service(karakeep, state, pipeline, notifier, settings, lambda: preflight(settings, trilium, llm, runtime))
    return App(
        settings=settings, state=state, karakeep=karakeep, trilium=trilium, llm=llm, notifier=notifier,
        layout=runtime.layout, llm_budget=llm_budget, ytdlp=ytdlp, gallery=gallery, transcribe=transcribe,
        stages=stages, pipeline=pipeline, service=service,
        destinations=destinations, destination=destination, runtime=runtime,
    )
