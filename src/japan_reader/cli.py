from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from japan_reader.config import Settings
from japan_reader.errors import ConfigError
from japan_reader.evaluation import EvalRunner, format_table, load_cases
from japan_reader.instagram_export import filter_collection, format_import_report, import_items, parse_export
from japan_reader.log import setup_logging
from japan_reader.service import REPROCESS_FROM, format_status, reprocess
from japan_reader.stages.extract import ExtractStage
from japan_reader.stages.fetch import FetchStage
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
