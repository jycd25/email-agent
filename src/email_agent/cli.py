from __future__ import annotations

import json
import logging
from pathlib import Path

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
def ui(host: str | None = None, port: int | None = None, open_browser: bool = True) -> None:
    """Start the web UI and the background worker."""
    import threading
    import webbrowser

    import uvicorn

    from .api import create_api

    ctx = _ctx()
    host = host or ctx.config.host
    port = port or ctx.config.port
    url = f"http://{host}:{port}"
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    typer.echo(f"email-agent {__version__} -> {url}")
    uvicorn.run(create_api(ctx), host=host, port=port, log_level=ctx.config.log_level.lower())


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
def auth(
    provider: str = typer.Argument("gmail", help="gmail or outlook"),
) -> None:
    """Authorize a mail account. Gmail opens a browser; Outlook prints a device-sign-in code."""
    ctx = _ctx()
    if provider == "gmail":
        ctx.gmail.authorize(interactive=True)
        typer.echo(f"Gmail authorized. Token saved to {ctx.config.token_path}")
    elif provider == "outlook":
        ctx.outlook.authorize(interactive=True, prompt=typer.echo)
        typer.echo(f"Outlook authorized. Token saved to {ctx.config.outlook_token_path}")
    else:
        raise typer.BadParameter("provider must be 'gmail' or 'outlook'")


@app.command()
def analyze(
    prompt: str = typer.Argument("", help='e.g. "is this urgent: {server is down}"'),
    file: Path | None = typer.Option(
        None, "--file", "-f", help="Analyze an .eml file (or - for stdin)"
    ),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Analyze one email. Give a prompt, or --file message.eml, or pipe an email to --file -."""
    import sys

    from .agent import EmailAgent
    from .sources.parse import parse_raw

    if file is not None:
        raw = sys.stdin.buffer.read() if str(file) == "-" else file.read_bytes()
        p = parse_raw(raw)
        body = f"Subject: {p.subject}\nFrom: {p.from_addr}\n\n{p.body_text}"
        prompt = (prompt or "full analysis") + ": {" + body + "}"
        if p.from_addr:
            prompt += f" from {p.from_addr}"
    if not prompt:
        raise typer.BadParameter("give a prompt or --file")
    ctx = _ctx()
    agent = EmailAgent(ctx.store, ctx.settings(), ctx.make_llm(), ctx.selector_client())
    result = agent.process(prompt)
    typer.echo(json.dumps(result, indent=2, default=str) if as_json else agent.format(result))


@app.command()
def status() -> None:
    """Show queue, alerts and connection status."""
    ctx = _ctx()
    typer.echo(json.dumps(ctx.status(), indent=2, default=str))


@app.command()
def fetch() -> None:
    """Fetch and process once, then exit."""
    import asyncio

    ctx = _ctx()

    async def main() -> None:
        ctx.bus.bind(asyncio.get_running_loop())
        typer.echo(json.dumps(await ctx.worker.tick()))

    asyncio.run(main())


if __name__ == "__main__":
    app()
