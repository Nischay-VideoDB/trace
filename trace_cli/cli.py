"""Trace CLI entry point. Subcommands: start, stop, generate, serve, qa-poll."""
# generate without pr_url: auto-commit + push + open PR + generate (formerly `ship`)
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
    no_args_is_help=False,
    add_completion=False,
)
console = Console()

# ASCII art banner — "small" figlet font
_TRACE_BANNER = (
    "\n"
    "[bold white] _                       \n"
    "| |_ _ __ __ _  ___ ___ \n"
    "| __| '__/ _` |/ __/ _ \\\n"
    "| |_| | | (_| | (_|  __/\n"
    " \\__|_|  \\__,_|\\___\\___|[/bold white]\n"
)


@app.callback(invoke_without_command=True)
def _banner(ctx: typer.Context) -> None:
    """Print the trace banner before any subcommand."""
    console.print(_TRACE_BANNER)
    if ctx.invoked_subcommand is None:
        # Show help when called with no args
        console.print(ctx.get_help())


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
    live: bool = typer.Option(
        False,
        "--live",
        help="Pseudo-live: stream chunks to VideoDB every 15s during capture",
    ),
    chunk_seconds: int = typer.Option(15, "--chunk-seconds", help="Live chunk size"),
) -> None:
    """Start a new capture session (screen + mic). Blocks until SIGINT or `trace stop`."""
    Credentials.require("VIDEODB_API_KEY")
    from trace_cli.capture.heartbeat import HeartbeatThread
    from trace_cli.capture.live_indexer import LiveIndexer
    from trace_cli.capture.platform import SaveWatcher, WindowPoller, start_capture, stop_capture
    from trace_cli.session.manager import ActiveSessionError, SessionManager
    from trace_cli.session.store import SessionStore

    if not (project / ".git").exists():
        console.print(f"[yellow]warning: {project} has no .git — file saves won't be tracked correctly. cd into your project repo before running trace start.[/yellow]")

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
    ino = SaveWatcher(meta.session_id, store, project)
    ino.start()
    hypr = WindowPoller(meta.session_id, store)
    hypr.start()

    live_indexer = None
    if live:
        live_indexer = LiveIndexer(
            meta.session_id, store, screen_path, audio_path,
            chunk_seconds=chunk_seconds,
        )
        live_indexer.start()
        store.update_metadata(meta.session_id, capture_mode="rtstream")
        console.print(f"[magenta]live mode: indexing chunks every {chunk_seconds}s via VideoDB[/magenta]")

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
        if live_indexer is not None:
            live_indexer.stop()
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
def stop(
    skip_index: bool = typer.Option(False, "--skip-index", help="Skip VideoDB upload + indexing"),
) -> None:
    """Signal the active capture session to finalize and run indexing pipeline."""
    Credentials.require("VIDEODB_API_KEY")
    from trace_cli.indexing.pipeline import IndexingError, run_indexing
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
    console.print(f"[green]capture finalized: status={final.status}[/green]")

    if skip_index:
        console.print("[yellow]--skip-index set; not uploading to VideoDB[/yellow]")
        return

    if final.status not in ("processing", "transcription_failed", "indexed"):
        console.print(f"[yellow]capture status is {final.status}; not indexing[/yellow]")
        return

    console.print("[cyan]uploading to VideoDB and indexing...[/cyan]")
    try:
        indexed = run_indexing(final.session_id)
    except IndexingError as e:
        console.print(f"[red]indexing failed: {e}[/red]")
        sys.exit(1)
    console.print(
        f"[green]indexed: video_id={indexed.video_id} scene_index_id={getattr(indexed, 'model_extra', {}).get('scene_index_id') or indexed.model_dump().get('scene_index_id')}[/green]"
    )

    # Build timeline from indexed session.
    from trace_cli.timeline.build_for_session import build_timeline_for_session
    try:
        tl = build_timeline_for_session(indexed.session_id)
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]timeline build failed: {e}[/red]")
        sys.exit(1)
    counts = {k: 0 for k in ("progress", "stuck", "research", "speech")}
    for m in tl.moments:
        counts[m.category] = counts.get(m.category, 0) + 1
    console.print(
        f"[green]timeline: {len(tl.moments)} moments "
        f"(progress={counts['progress']} stuck={counts['stuck']} "
        f"research={counts['research']} speech={counts['speech']})[/green]"
    )
    console.print(f"[green]final status: {indexed.status}[/green]")


# ---------- generate ------------------------------------------------------

@app.command()
def generate(
    session_id: str = typer.Argument(..., help="Session id (from `trace start` output)"),
    pr_url: str = typer.Argument(None, help="GitHub PR URL. Omit to auto-commit, push, and open PR."),
    base: str = typer.Option(None, "--base", help="Base branch for auto PR (default: repo default)"),
    no_commit: bool = typer.Option(False, "--no-commit", help="Skip auto-commit when pr_url is omitted"),
    repo: Path = typer.Option(None, "--repo", help="Repo dir to use for auto PR (overrides session project_dir)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Render but do not post PR comment"),
) -> None:
    """Generate narrated PR video and post it to the GitHub PR.

    With a PR URL:   trace generate <session_id> <pr_url>
    Without one:     trace generate <session_id>
                     Auto-commits staged changes, pushes branch, opens PR, then generates.
    """
    Credentials.require("VIDEODB_API_KEY", "GITHUB_TOKEN")
    from trace_cli.pr_video.selector import InsufficientContent

    if pr_url:
        from trace_cli.pr_video.generator import generate_pr_video
        try:
            result = generate_pr_video(session_id, pr_url, dry_run=dry_run)
        except InsufficientContent as e:
            console.print(f"[red]not enough session content: {e}[/red]")
            sys.exit(1)
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]generate failed: {e}[/red]")
            sys.exit(1)
        console.print(f"[green]HLS URL:[/green] {result.hls_url}")
        console.print(f"[green]clips:[/green] {result.clip_count} totaling {result.total_seconds:.1f}s")
        if dry_run:
            console.print("[yellow]dry-run; no PR comment posted[/yellow]")
        else:
            console.print("[green]posted comment to PR[/green]")
    else:
        # Auto-ship: commit + push + open PR + generate
        from trace_cli.pr_video.ship import ShipError, ship as ship_fn
        try:
            ship_result = ship_fn(
                session_id,
                base=base,
                auto_commit=not no_commit,
                repo_override=repo,
            )
        except ShipError as e:
            console.print(f"[red]generate failed: {e}[/red]")
            sys.exit(1)
        except InsufficientContent as e:
            console.print(f"[red]not enough session content: {e}[/red]")
            sys.exit(1)
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]generate failed: {e}[/red]")
            sys.exit(1)
        console.print(f"[green]PR:[/green] {ship_result.pr_url}")
        console.print(f"[green]branch:[/green] {ship_result.branch}")
        if ship_result.commit_sha:
            console.print(f"[green]commit:[/green] {ship_result.commit_sha[:10]}")
        console.print(f"[green]video:[/green] {ship_result.render.hls_url}")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port"),
) -> None:
    """Run FastAPI app: /webhook/github."""
    Credentials.require("VIDEODB_API_KEY", "GITHUB_TOKEN")
    import uvicorn
    uvicorn.run("trace_cli.web.app:app", host=host, port=port, reload=False)


@app.command("qa-poll")
def qa_poll(
    pr_url: str = typer.Argument(..., help="PR to poll for /trace comments"),
    session_id: str = typer.Argument(..., help="Session bound to this PR"),
    interval: int = typer.Option(30, "--interval", help="Poll interval seconds"),
    stop_after: int = typer.Option(0, "--stop-after", help="Exit after N seconds (0 = run forever)"),
) -> None:
    """Poll GitHub PR comments and answer /trace mentions."""
    Credentials.require("VIDEODB_API_KEY", "GITHUB_TOKEN")
    from trace_cli.web.qa import poll_loop
    console.print(f"[cyan]polling {pr_url} for /trace every {interval}s (session={session_id})[/cyan]")
    poll_loop(
        pr_url=pr_url,
        session_id=session_id,
        interval=float(interval),
        stop_after=float(stop_after) if stop_after > 0 else None,
    )


# ---------- inspection commands ------------------------------------------

@app.command()
def sessions() -> None:
    """List all known capture sessions."""
    from trace_cli.session.store import SessionStore
    store = SessionStore()
    sids = store.list_sessions()
    if not sids:
        console.print("[yellow]no sessions found in ~/.trace/sessions[/yellow]")
        return
    for sid in sids:
        try:
            meta = store.read_metadata(sid)
            console.print(
                f"[green]{sid}[/green]  status={meta.status}  "
                f"video_id={meta.video_id or '-'}  started={meta.started_at.isoformat()}"
            )
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]{sid}  unreadable: {e}[/red]")


@app.command()
def inspect(
    session_id: str = typer.Argument(..., help="Session id"),
) -> None:
    """Show metadata, timeline summary, transcript head for a session."""
    from collections import Counter

    from trace_cli.session.models import Transcript
    from trace_cli.session.store import SessionStore
    from trace_cli.timeline.builder import from_json as tj

    store = SessionStore()
    meta = store.read_metadata(session_id)
    console.print(f"[bold]session[/bold] {session_id}")
    console.print(f"  status: {meta.status}")
    console.print(f"  video_id: {meta.video_id}")
    console.print(f"  capture_mode: {meta.capture_mode}, mic: {meta.mic_status}")
    console.print(f"  started: {meta.started_at.isoformat()}")
    if meta.stopped_at:
        console.print(f"  stopped: {meta.stopped_at.isoformat()}")
    console.print(f"  project_dir: {meta.project_dir}")

    tl_path = store.timeline_path(session_id)
    if tl_path.exists():
        tl = tj(tl_path.read_text(encoding="utf-8"))
        cats = Counter(m.category for m in tl.moments)
        console.print(f"\n[bold]timeline[/bold]: {len(tl.moments)} moments, "
                      f"{tl.session_end_seconds:.1f}s total, categories: {dict(cats)}")
    tr_path = store.transcript_path(session_id)
    if tr_path.exists():
        tr = Transcript.model_validate_json(tr_path.read_text(encoding="utf-8"))
        console.print(f"\n[bold]transcript[/bold]: {len(tr.segments)} segments")
        for seg in tr.segments[:5]:
            console.print(f"  [{seg.start_seconds:6.1f}-{seg.end_seconds:6.1f}] {seg.text!r}")
        if len(tr.segments) > 5:
            console.print(f"  ... +{len(tr.segments) - 5} more")


@app.command()
def timeline(
    session_id: str = typer.Argument(..., help="Session id"),
) -> None:
    """Print the full tagged timeline for a session."""
    from trace_cli.session.store import SessionStore
    from trace_cli.timeline.builder import from_json as tj

    tl = tj(SessionStore().timeline_path(session_id).read_text(encoding="utf-8"))
    console.print(f"[bold]{len(tl.moments)} moments[/bold] (session_end={tl.session_end_seconds:.1f}s)")
    for m in tl.moments:
        color = {"progress": "green", "research": "yellow",
                 "speech": "cyan", "stuck": "red"}.get(m.category, "white")
        console.print(
            f"  [{m.start_seconds:6.1f}-{m.end_seconds:6.1f}] "
            f"[{color}]{m.category:9s}[/{color}] conf={m.confidence:.2f} "
            f"ev={m.evidence[:80]!r}"
        )


@app.command()
def transcript(
    session_id: str = typer.Argument(..., help="Session id"),
) -> None:
    """Print full spoken-word transcript for a session."""
    from trace_cli.session.models import Transcript
    from trace_cli.session.store import SessionStore
    tr = Transcript.model_validate_json(
        SessionStore().transcript_path(session_id).read_text(encoding="utf-8")
    )
    console.print(f"[bold]{len(tr.segments)} segments[/bold]")
    for seg in tr.segments:
        console.print(f"  [{seg.start_seconds:6.1f}-{seg.end_seconds:6.1f}] {seg.text}")


def _load_pr_files(pr_url: str | None, fake_path: str | None, fake_changes: int) -> list[dict]:
    """Helper: real PR diff if pr_url given, else a synthetic single-file diff."""
    if pr_url:
        from trace_cli.github.client import GitHubClient
        return GitHubClient().get_pr_files(pr_url)
    if fake_path:
        return [{
            "path": fake_path,
            "additions": fake_changes,
            "deletions": 0,
            "changes": fake_changes,
            "patch": f"@@ -0,0 +1,{fake_changes} @@\n" + "\n".join(f"+line {i}" for i in range(fake_changes)),
        }]
    return []


@app.command()
def focus(
    session_id: str = typer.Argument(..., help="Session id"),
    pr_url: str = typer.Option(None, "--pr", help="Real PR URL to pull diff from"),
    fake_file: str = typer.Option("auth.py", "--fake-file", help="Used when --pr not given"),
    fake_changes: int = typer.Option(60, "--fake-changes", help="Synthetic line count"),
    post: bool = typer.Option(False, "--post", help="Post comment to PR (needs --pr)"),
) -> None:
    """Generate Reviewer Focus Mode for a session against a PR diff."""
    from trace_cli.focus_mode.builder import build_focus, render_comment
    from trace_cli.session.models import Transcript
    from trace_cli.session.store import SessionStore
    from trace_cli.timeline.builder import from_json as tj

    store = SessionStore()
    tl = tj(store.timeline_path(session_id).read_text(encoding="utf-8"))
    tr = Transcript.model_validate_json(store.transcript_path(session_id).read_text(encoding="utf-8"))
    files = _load_pr_files(pr_url, fake_file, fake_changes)
    entries = build_focus(files, tl, tr)
    body = render_comment(entries)
    console.print(body)
    if post and pr_url:
        Credentials.require("GITHUB_TOKEN")
        from trace_cli.github.client import GitHubClient
        url = GitHubClient().post_comment(pr_url, body)
        console.print(f"\n[green]posted: {url}[/green]")


@app.command("contribution-map")
def contribution_map(
    session_id: str = typer.Argument(..., help="Session id"),
    pr_url: str = typer.Option(None, "--pr", help="Real PR URL to pull diff from"),
    fake_file: str = typer.Option("trace_cli/web/qa.py", "--fake-file"),
    fake_changes: int = typer.Option(5, "--fake-changes"),
    post: bool = typer.Option(False, "--post", help="Post comment to PR (needs --pr)"),
) -> None:
    """Classify each PR diff line as human/agent/mixed/unknown."""
    from trace_cli.contribution_map.mapper import classify, render_comment
    from trace_cli.contribution_map.scanner import collect_agent_edits
    from trace_cli.session.store import SessionStore

    store = SessionStore()
    meta = store.read_metadata(session_id)
    files = _load_pr_files(pr_url, fake_file, fake_changes)
    if not files:
        console.print("[red]no files to classify; pass --pr or --fake-file[/red]")
        sys.exit(1)
    edits = collect_agent_edits(
        Path(meta.project_dir) if meta.project_dir else Path.cwd(),
        started_at=meta.started_at,
        stopped_at=meta.stopped_at or datetime.now(timezone.utc),
    )
    console.print(f"[dim]agent-touched files in window: {len(edits)}[/dim]\n")
    body = render_comment(classify(files, edits))
    console.print(body)
    if post and pr_url:
        Credentials.require("GITHUB_TOKEN")
        from trace_cli.github.client import GitHubClient
        url = GitHubClient().post_comment(pr_url, body)
        console.print(f"\n[green]posted: {url}[/green]")


@app.command("pr-description")
def pr_description(
    session_id: str = typer.Argument(..., help="Session id"),
    pr_url: str = typer.Option(None, "--pr", help="Real PR URL"),
    fake_file: str = typer.Option("auth.py", "--fake-file"),
    fake_changes: int = typer.Option(12, "--fake-changes"),
    video_url: str = typer.Option("", "--video-url", help="HLS URL to include"),
    contribution_url: str = typer.Option("", "--contribution-url"),
    post: bool = typer.Option(False, "--post", help="Append to PR description (needs --pr)"),
    title: str = typer.Option("this change", "--title"),
) -> None:
    """Generate the What/Why/Struggles/Follow-ups PR description."""
    Credentials.require("VIDEODB_API_KEY")
    from trace_cli.pr_description.generator import build
    from trace_cli.session.models import Transcript
    from trace_cli.session.store import SessionStore
    from trace_cli.timeline.builder import from_json as tj
    from trace_cli.videodb.client import VideoDBClient

    store = SessionStore()
    tl = tj(store.timeline_path(session_id).read_text(encoding="utf-8"))
    tr = Transcript.model_validate_json(store.transcript_path(session_id).read_text(encoding="utf-8"))
    files = _load_pr_files(pr_url, fake_file, fake_changes)
    client = VideoDBClient()
    desc = build(
        client, files, tr, tl,
        pr_title=title,
        video_url=video_url or None,
        contribution_url=contribution_url or None,
    )
    console.print(desc.body)
    if post and pr_url:
        Credentials.require("GITHUB_TOKEN")
        from trace_cli.github.client import GitHubClient
        GitHubClient().append_description(pr_url, desc.body)
        console.print(f"\n[green]appended to {pr_url}[/green]")


@app.command()
def ask(
    session_id: str = typer.Argument(..., help="Session id"),
    question: str = typer.Argument(..., help="Question to ask the session"),
    top: int = typer.Option(3, "--top", help="Max hits"),
) -> None:
    """One-shot Q&A: search the session for a question and print clip URLs."""
    Credentials.require("VIDEODB_API_KEY")
    from trace_cli.session.store import SessionStore
    from trace_cli.videodb.client import VideoDBClient
    from trace_cli.web.qa import _dedupe_by_window, _scene_hits, _spoken_hits, build_reply

    store = SessionStore()
    meta = store.read_metadata(session_id)
    client = VideoDBClient()
    video = client.get_video(meta.video_id)
    hits = _spoken_hits(client, video, question) + _scene_hits(client, video, question)
    hits = _dedupe_by_window(hits)[:top]
    urls: list[str] = []
    for h in hits:
        try:
            urls.append(client.video_clip_url(video, h.start, h.end))
        except Exception as e:  # noqa: BLE001
            urls.append(f"(clip unavailable: {e})")
    console.print(build_reply(question, hits, urls))
