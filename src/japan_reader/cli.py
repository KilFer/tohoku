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
