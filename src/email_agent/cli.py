from __future__ import annotations

import logging

import typer

from . import __version__
from .core.config import AppConfig
from .core.logging import setup_logging

app = typer.Typer(help="Local email monitoring agent.", no_args_is_help=True, add_completion=False)
log = logging.getLogger(__name__)


def _ctx():
    from .app import App

    cfg = AppConfig()
    setup_logging(cfg.log_level)
    return App(cfg)


@app.command()
def version() -> None:
    typer.echo(__version__)


@app.command()
def run() -> None:
    """Run the worker headless (no UI)."""
    import asyncio

    ctx = _ctx()

    async def main() -> None:
        await ctx.start()
        try:
            while True:
                await asyncio.sleep(3600)
        finally:
            await ctx.stop()

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


@app.command()
def auth() -> None:
    """Authorize Gmail. Opens a browser once; the token is saved locally."""
    ctx = _ctx()
    ctx.gmail.authorize(interactive=True)
    typer.echo(f"Gmail authorized. Token saved to {ctx.config.token_path}")


if __name__ == "__main__":
    app()
