import logging
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from tohoku.config import Settings
from tohoku.errors import ConfigError
from tohoku.evaluation import EvalRunner, format_table, load_cases
from tohoku.instagram_export import filter_collection, format_import_report, import_items, parse_export
from tohoku.lock import AlreadyRunning, single_instance
from tohoku.log import setup_logging
from tohoku.service import REPROCESS_FROM, format_status, reprocess
from tohoku.stages.extract import ExtractStage
from tohoku.stages.fetch import FetchStage
from tohoku.trilium_layout import init_layout
from tohoku.wiring import App, build_app

app = typer.Typer(no_args_is_help=True, help="tohoku: de Karakeep a Trilium (notas a partir de Shorts, Reels y posts).")


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


def _already_running_exit(exc: AlreadyRunning) -> typer.Exit:
    logging.getLogger(__name__).error("%s", exc)
    typer.echo(f"{exc}. No se arranca otra.", err=True)
    return typer.Exit(3)


@app.command()
def run() -> None:
    """Bucle principal: sondea Karakeep y procesa la cola."""
    loaded = _load()
    try:
        with single_instance(loaded.settings.data_dir):
            loaded.service.run_forever()
    except AlreadyRunning as exc:
        raise _already_running_exit(exc) from exc


@app.command("run-once")
def run_once() -> None:
    """Un único ciclo de sondeo y procesamiento."""
    loaded = _load()
    try:
        with single_instance(loaded.settings.data_dir):
            loaded.service.tick()
    except AlreadyRunning as exc:
        raise _already_running_exit(exc) from exc
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
    bookmark_ids: Annotated[list[str] | None, typer.Argument(help="Uno o varios bookmarkId")] = None,
    from_stage: Annotated[str, typer.Option("--from", help=" | ".join(REPROCESS_FROM))] = "fetch",
    all_errors: Annotated[bool, typer.Option("--all-errors", help="Reprocesar todos los jobs en error")] = False,
) -> None:
    """Vuelve a poner uno o varios bookmarks en la cola desde una etapa."""
    if from_stage not in REPROCESS_FROM:
        typer.echo(f"etapa no válida: {from_stage}. Opciones: {', '.join(REPROCESS_FROM)}")
        raise typer.Exit(1)
    loaded = _load()
    ids = list(dict.fromkeys([*(bookmark_ids or []), *(loaded.state.error_job_ids() if all_errors else [])]))
    if not ids:
        typer.echo("Indica uno o varios bookmarkId o usa --all-errors." if not all_errors else "No hay jobs en error.")
        raise typer.Exit(1 if not all_errors else 0)
    for bookmark_id in ids:
        try:
            job = reprocess(loaded.state, loaded.karakeep, bookmark_id, from_stage)
        except ValueError as exc:
            typer.echo(str(exc))
            raise typer.Exit(1) from exc
        typer.echo(f"{job.bookmark_id} en cola desde '{from_stage}'.")
    typer.echo(f"{len(ids)} bookmark(s) en cola; se procesarán en el próximo ciclo.")


@app.command("import-instagram")
def import_instagram(
    path: Path,
    collection: Annotated[str | None, typer.Option(help="Importar solo esta colección (p. ej. 'Japón')")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Solo contar, sin crear nada")] = False,
    limit: Annotated[int | None, typer.Option(help="Máximo de enlaces NUEVOS en esta tanda (relanzar = siguiente tanda)")] = None,
) -> None:
    """Importa a la lista de Karakeep los enlaces de la exportación de Instagram, del más antiguo al más reciente."""
    loaded = _load()
    items = parse_export(path)
    if collection:
        items = filter_collection(items, collection)
    report = import_items(items, loaded.karakeep, loaded.settings.karakeep_list_id, dry_run, limit)
    typer.echo(format_import_report(report, dry_run))


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
    extract = ExtractStage(settings, loaded.llm, loaded.llm_budget, loaded.destination.prompt)
    scores = runner.run(load_cases(cases), extract, settings.thresholds, keyframes)
    typer.echo(format_table(scores, settings.openrouter_model, keyframes))
