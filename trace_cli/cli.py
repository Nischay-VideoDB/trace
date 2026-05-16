"""Trace CLI entry point. Subcommands: start, stop, generate, replay, serve, qa-poll."""
from __future__ import annotations

import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import typer
from rich.console import Console

from trace_cli.credentials import Credentials, install_redacting_logging

install_redacting_logging()
log = logging.getLogger("trace.cli")

app = typer.Typer(
    name="trace",
    help="Capture coding sessions and generate narrated PR videos via VideoDB.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


# ---------- start ---------------------------------------------------------

@app.command()
def start(
    project: Path = typer.Option(
        Path.cwd(),
        "--project",
        "-p",
        help="Project directory to watch for file save events",
    ),
    no_mic: bool = typer.Option(False, "--no-mic", help="Disable microphone capture"),
) -> None:
    """Start a new capture session (screen + mic). Blocks until SIGINT or `trace stop`."""
    Credentials.require("VIDEODB_API_KEY")
    from trace_cli.capture.heartbeat import HeartbeatThread
    from trace_cli.capture.service import start_capture, stop_capture
    from trace_cli.capture.watchers import HyprctlPoller, InotifyWatcher
    from trace_cli.session.manager import ActiveSessionError, SessionManager
    from trace_cli.session.store import SessionStore

    mgr = SessionManager()
    try:
        meta = mgr.create(project_dir=project)
    except ActiveSessionError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)

    store = mgr.store
    sd = store.session_dir(meta.session_id)
    screen_path = store.screen_path(meta.session_id)

    console.print(f"[green]session_id:[/green] {meta.session_id}")
    console.print(f"[green]session_dir:[/green] {sd}")

    try:
        handles = start_capture(screen_path, mic=not no_mic)
    except Exception as e:
        console.print(f"[red]capture failed: {e}[/red]")
        store.update_metadata(meta.session_id, status="failed")
        sys.exit(1)

    audio_path = getattr(handles, "audio_path", None)
    if no_mic:
        store.update_metadata(meta.session_id, mic_status="denied")

    mgr.mark_active(meta.session_id, os.getpid())

    hb = HeartbeatThread(meta.session_id, store, screen_path, audio_path)
    hb.start()
    ino = InotifyWatcher(meta.session_id, store, project)
    ino.start()
    hypr = HyprctlPoller(meta.session_id, store)
    hypr.start()

    stop_requested = {"flag": False}

    def _on_sig(signum, frame):  # noqa: ARG001
        stop_requested["flag"] = True
        console.print("\n[yellow]stop signal received; finalizing...[/yellow]")

    signal.signal(signal.SIGINT, _on_sig)
    signal.signal(signal.SIGTERM, _on_sig)

    console.print("[cyan]recording. Ctrl-C or `trace stop` to finish.[/cyan]")
    try:
        while not stop_requested["flag"]:
            time.sleep(0.5)
            if handles.process.poll() is not None:
                console.print("[red]wf-recorder exited unexpectedly[/red]")
                break
    finally:
        hb.stop()
        ino.stop()
        hypr.stop()
        try:
            video_path, real_audio_path = stop_capture(handles)
        except Exception as e:
            console.print(f"[red]stop_capture failed: {e}[/red]")
            store.update_metadata(meta.session_id, status="failed")
            store.clear_active()
            sys.exit(1)
        store.update_metadata(
            meta.session_id,
            status="processing",
            stopped_at=datetime.now(timezone.utc),
        )
        store.clear_active()

    console.print(f"[green]video:[/green] {video_path}")
    if real_audio_path:
        console.print(f"[green]audio:[/green] {real_audio_path}")
    console.print(f"[cyan]session {meta.session_id} ready for indexing. run `trace stop`'s indexing pipeline next (TODO).[/cyan]")


# ---------- stop ----------------------------------------------------------

@app.command()
def stop() -> None:
    """Signal the active capture session to finalize."""
    from trace_cli.session.manager import NoActiveSession, SessionManager

    mgr = SessionManager()
    try:
        meta = mgr.signal_stop()
    except NoActiveSession as e:
        console.print(f"[red]{e}[/red]", style="bold")
        sys.exit(1)
    console.print(f"[yellow]stop signal sent to session {meta.session_id}[/yellow]")
    try:
        final = mgr.wait_for_stop(meta.session_id, timeout=60.0)
    except Exception as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)
    console.print(f"[green]session {final.session_id} status={final.status}[/green]")


# ---------- generate ------------------------------------------------------

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
