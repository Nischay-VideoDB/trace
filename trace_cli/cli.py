"""Trace CLI entry point. Subcommands: start, stop, generate, replay, serve, qa-poll."""
from __future__ import annotations

import typer
from rich.console import Console

from trace_cli.credentials import Credentials, install_redacting_logging

install_redacting_logging()

app = typer.Typer(
    name="trace",
    help="Capture coding sessions and generate narrated PR videos via VideoDB.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


@app.command()
def start() -> None:
    """Start a new capture session (screen + mic → VideoDB RTStream)."""
    Credentials.require("VIDEODB_API_KEY")
    console.print("[yellow]TODO: implement start (capture wave)[/yellow]")
    raise typer.Exit(code=1)


@app.command()
def stop() -> None:
    """Stop the active capture session and finalize indexing."""
    Credentials.require("VIDEODB_API_KEY")
    console.print("[yellow]TODO: implement stop[/yellow]")
    raise typer.Exit(code=1)


@app.command()
def generate(
    session_id: str = typer.Argument(..., help="Session id (from `trace start` output)"),
    pr_url: str = typer.Argument(..., help="GitHub PR URL"),
    focus: bool = typer.Option(False, "--focus", help="Also post Focus Mode comment"),
) -> None:
    """Generate narrated PR video + post artifacts to GitHub PR."""
    Credentials.require("VIDEODB_API_KEY", "GITHUB_TOKEN")
    console.print(f"[yellow]TODO: generate for {session_id} -> {pr_url} (focus={focus})[/yellow]")
    raise typer.Exit(code=1)


@app.command()
def replay(
    session_id: str = typer.Option(..., "--session"),
    file: str = typer.Option(..., "--file"),
    start: int = typer.Option(..., "--start"),
    end: int = typer.Option(..., "--end"),
) -> None:
    """Decision Replay: show edit history for a file/line range."""
    Credentials.require("VIDEODB_API_KEY")
    console.print(f"[yellow]TODO: replay {session_id} {file}:{start}-{end}[/yellow]")
    raise typer.Exit(code=1)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port"),
) -> None:
    """Run FastAPI app: /replay UI + /webhook/github."""
    Credentials.require("VIDEODB_API_KEY", "GITHUB_TOKEN")
    import uvicorn
    uvicorn.run("trace_cli.web.app:app", host=host, port=port, reload=False)


@app.command("qa-poll")
def qa_poll(
    pr_url: str = typer.Argument(..., help="PR to poll for @trace comments"),
    session_id: str = typer.Argument(..., help="Session bound to this PR"),
    interval: int = typer.Option(30, "--interval", help="Poll interval seconds"),
) -> None:
    """Poll GitHub PR comments and answer @trace mentions."""
    Credentials.require("VIDEODB_API_KEY", "GITHUB_TOKEN")
    console.print(f"[yellow]TODO: qa-poll {pr_url} session={session_id} every {interval}s[/yellow]")
    raise typer.Exit(code=1)
