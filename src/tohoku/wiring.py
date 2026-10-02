from dataclasses import dataclass

from tohoku.classify import CLASSIFIERS
from tohoku.classify.base import Classifier
from tohoku.cleanup import Cleaner

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
from tohoku.stages.classify import ClassifyStage
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
    destination: Destination  # el destino por defecto
    runtimes: dict[str, FlowRuntime]
    classifier: Classifier | None  # None si ningún bookmark puede tener varios candidatos
    vision_classifier: Classifier | None = None  # mismo modo con OPENROUTER_MODEL: solo cuando se mandan imágenes


def preflight(
    settings: Settings,
    trilium: TriliumClient,
    llm: OpenRouterClient,
    *layouts: FlowRuntime | LayoutCache,
    classifier_model: str | None = None,
    classifier_mode: str = "json_schema",
) -> None:
    """Comprobaciones antes de procesar: Trilium accesible y estructurado, modelos válidos, cookies.

    `classifier_model` solo se indica si alguna lista tiene varios destinos (hay clasificador).
    """
    trilium.app_info()
    for layout in layouts:
        layout.refresh()
    models = [("OPENROUTER_MODEL", settings.openrouter_model, True)]
    if settings.text_model != settings.openrouter_model:
        models.append(("OPENROUTER_TEXT_MODEL", settings.text_model, True))
    if classifier_model is not None:
        models.append(("clasificador.modelo", classifier_model, classifier_mode == "json_schema"))
    infos: dict[str, dict] = {}
    for variable, model, structured in models:
        info = llm.model_info(model)
        if info is None:
            raise ConfigError(f"{variable}={model} no existe en OpenRouter (revisa el nombre del modelo)")
        if structured and not supports_structured_output(info):
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
    destination = destinations.destinos[destinations.destino_por_defecto]
    deps = FlowDeps(settings=settings, state=state, trilium=trilium, llm=llm, places=places,
                    llm_budget=llm_budget, places_quota=places_quota)
    runtimes = {name: FLOWS[d.flujo].build(d, deps) for name, d in destinations.destinos.items()}
    cfg = destinations.clasificador
    classifier_model = (cfg.modelo or settings.text_model) if destinations.needs_classifier() else None
    classifier = CLASSIFIERS[cfg.modo](llm, classifier_model) if classifier_model else None
    # Sin caption ni transcripción se clasifica con imágenes: con el modelo multimodal (preflight lo comprueba),
    # porque clasificador.modelo / OPENROUTER_TEXT_MODEL puede ser solo de texto.
    vision_classifier = CLASSIFIERS[cfg.modo](llm, settings.openrouter_model) if classifier_model else None
    common: list[Stage] = [
        FetchStage(settings, ytdlp, gallery, karakeep), transcribe,
        ClassifyStage(destinations, classifier, llm_budget, vision_classifier=vision_classifier),
    ]
    cleaner = Cleaner(state, settings.data_dir, destinations.limpieza.retencion_dias)
    pipeline = Pipeline(state, common, MarkStage(karakeep), notifier, settings.data_dir,
                        flows={name: runtime.stages for name, runtime in runtimes.items()}, cleaner=cleaner)
    service = Service(
        karakeep, state, pipeline, notifier, settings,
        lambda: preflight(settings, trilium, llm, *runtimes.values(), classifier_model=classifier_model, classifier_mode=cfg.modo),
        lists=destinations.listas, cleaner=cleaner,
    )
    default = runtimes[destinations.destino_por_defecto]
    return App(
        settings=settings, state=state, karakeep=karakeep, trilium=trilium, llm=llm, notifier=notifier,
        layout=default.layout, llm_budget=llm_budget, ytdlp=ytdlp, gallery=gallery, transcribe=transcribe,
        stages=[*common, *default.stages], pipeline=pipeline, service=service,
        destinations=destinations, destination=destination, runtimes=runtimes, classifier=classifier,
        vision_classifier=vision_classifier,
    )
