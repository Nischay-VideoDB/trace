# trace

`trace start` -> code -> `trace stop` -> your PR explains itself.

trace watches a coding session (screen + mic), indexes everything through VideoDB, and decorates the resulting GitHub PR with a narrated walkthrough video, a context-aware description, a reviewer Q&A bot, and a human vs AI contribution map. All powered by one vendor: VideoDB.

Built for the VideoDB "Give Agents Eyes and Ears" hackathon (May 16 to 18, 2026).

## What it does

```
trace start --project /path/to/repo
    captures screen with wf-recorder, mic with ffmpeg+pulse
    streams 15s chunks live to VideoDB (--live) for real-time indexing
    watches inotify saves + hyprctl active window during session

trace stop
    finalizes capture, muxes audio into mp4
    uploads to VideoDB, runs index_spoken_words + index_scenes with a
    custom classifier prompt
    builds a tagged timeline (stuck, research, progress, speech moments)

trace generate <session_id> <pr_url>
    selects the right clips from the timeline based on PR diff files
    asks VideoDB-hosted LLM (generate_text) for per-clip narration
    grounded in scene index + spoken transcript so it does not hallucinate
    synthesizes narration audio via VideoDB-hosted TTS (generate_voice)
    assembles the PR video on a videodb.editor.Timeline with three tracks:
        video clips, narration audio, TextAsset badges
    posts the HLS URL to the PR
    posts a Human vs Agent contribution map scanned from Claude Code logs
    appends a What / Why / Struggles / Follow-ups PR description

trace serve
    runs a FastAPI web server: serves the landing page, docs, and the
    /webhook/github endpoint for the @trace reviewer bot

trace qa-poll <pr_url> <session_id>
    polls the PR for @trace mentions
    runs semantic search across the indexed spoken_word + scene indexes
    replies with up to 3 bounded clip URLs + paraphrased answers
```

## VideoDB usage map (the depth-of-VideoDB scorer)

Every VideoDB API surface used, and where:

| API | File | Purpose |
|---|---|---|
| `videodb.connect` | `trace_cli/videodb/client.py` | Auth |
| `Collection.upload(file_path)` | `trace_cli/indexing/pipeline.py` + `capture/live_indexer.py` | Session video + 15s live chunks |
| `Collection.connect_rtstream` | `trace_cli/videodb/client.py` (helper available) | Live ingest path |
| `Collection.generate_text(prompt, model='pro')` | `trace_cli/pr_video/narration.py`, `trace_cli/pr_description/generator.py` | Narration script + PR description Why section |
| `Collection.generate_voice(text)` | `trace_cli/pr_video/render.py` | Per-clip TTS narration |
| `Video.index_spoken_words(SegmentationType.sentence)` | `trace_cli/indexing/pipeline.py` | Transcript for narration + Q&A |
| `Video.index_scenes(SceneExtractionType.time_based, prompt=...)` | `trace_cli/indexing/pipeline.py` | Visual classification with custom prompt |
| `Video.get_scene_index(scene_index_id)` | `trace_cli/videodb/client.py` | Scene grounding for narration |
| `Video.search(IndexType.spoken_word, semantic)` | `trace_cli/web/qa.py` | Reviewer Q&A search |
| `Video.search(IndexType.scene, semantic)` | `trace_cli/web/qa.py` | Visual semantic search |
| `Video.generate_stream(timeline=[(s,e)])` | `trace_cli/web/qa.py` | Bounded HLS clip URLs |
| `videodb.editor.Timeline + Track + Clip` | `trace_cli/pr_video/render.py` | PR video assembly |
| `videodb.editor.VideoAsset` | `trace_cli/pr_video/render.py` | Source clips, muted, on track z=0 |
| `videodb.editor.AudioAsset` | `trace_cli/pr_video/render.py` | Narration on track z=1 |
| `videodb.editor.TextAsset + Font + Background + Position` | `trace_cli/pr_video/render.py` | Category + filename badges on track z=2 |
| `Timeline.generate_stream()` | `trace_cli/pr_video/render.py` | Final HLS m3u8 to post on PR |

15 distinct VideoDB calls across 8 files.

## Install

```
git clone https://github.com/crypticsaiyan/trace
cd trace
uv sync
```

Required environment variables in `.env` at the repo root:

```
VIDEODB_API_KEY=...
GITHUB_TOKEN=...
```

System dependencies (Arch Linux + Hyprland verified):

```
sudo pacman -S --needed ffmpeg wf-recorder inotify-tools
```

For VideoDB credit: claim sandbox credit at https://hackday.videodb.io/sandbox.html.

## Quickstart

Record a 2 to 3 minute coding session on a real project:

```
mkdir -p /tmp/demo && cd /tmp/demo
git init && echo "def hello(): pass" > greet.py

# Terminal 1 — start recording (--live streams 15s chunks to VideoDB as you code)
uv run trace start --project /tmp/demo --live

# code in another window, talk out loud while editing, save with :w

# Terminal 2 when done
uv run trace stop
```

Generate the PR video against a real GitHub PR (push your branch, open the PR, then run):

```
uv run trace generate <session_id_from_start_output> https://github.com/you/repo/pull/N
```

Or do it all in one shot — auto-commit, push, open PR, and generate:

```
uv run trace ship <session_id_from_start_output>
```

Run the @trace reviewer bot (long-running):

```
uv run trace qa-poll https://github.com/you/repo/pull/N <session_id>
```

Any reviewer comment containing `@trace what about X` triggers a semantic search against the indexed session and posts a reply with up to 3 bounded clips.

## Architecture choices

**Why pseudo-live chunked upload instead of CaptureSession.** VideoDB's official Capture SDK (`videodb[capture]`) only ships wheels for macOS and Windows. On Linux Wayland (Hyprland) the SDK is uninstallable. Instead, trace runs a `LiveIndexer` thread (`--live` flag) that cuts the in-progress mp4 every 15 seconds, uploads each chunk via `Collection.upload`, and indexes each one with `index_scenes` + `index_spoken_words`. Same VideoDB surfaces light up, no public RTSP tunnel required.

**Why VideoDB-only stack.** Hackathon judging weights 30% on depth of VideoDB usage. We dropped the planned OpenAI Whisper, OpenRouter LLM, and OpenAI TTS dependencies in favor of `Video.index_spoken_words` for transcript, `Collection.generate_text` (3 model tiers: basic, pro, ultra) for narration script, and `Collection.generate_voice` for TTS. One vendor, max API surface.

**Why scene-grounded narration.** Earlier versions had the narration LLM hallucinate technical details ("run_until_complete deadlock") that the developer never said and the screen never showed. We now pass the per-clip slice of the VideoDB scene index (label, files, errors, summary) into the prompt with explicit anti-hallucination rules, so narration only describes what the eyes-and-ears layer actually saw.

## Repo layout

```
trace_cli/
  cli.py                     typer entry (start, stop, generate, ship, serve, qa-poll, focus, contribution-map, pr-description, ask)
  credentials.py             env var loading + key redaction
  videodb/client.py          single VideoDB facade
  github/client.py           PR URL validator + comment / diff / description ops
  session/
    models.py                pydantic SessionMetadata, Heartbeat, Transcript, Timeline
    store.py                 ~/.trace/sessions/ on-disk layout
    manager.py               start / stop lifecycle, active-session lock
    ids.py                   UUID v4 helpers
  capture/
    service.py               wf-recorder + ffmpeg pulse subprocesses
    heartbeat.py             5s heartbeat writer
    watchers.py              inotify file save watcher + hyprctl window poller
    live_indexer.py          15s chunk upload + index thread (--live mode)
  indexing/
    pipeline.py              mux audio + upload + spoken/scene index + transcript fetch
  timeline/
    builder.py               boundary merger + priority resolution
    classifiers/__init__.py  progress / speech / research / stuck
    build_for_session.py     glue: load session data, run classifiers, persist
  pr_video/
    selector.py              per-moment clip selection
    narration.py             single-pass deduplicated scripts with scene + transcript grounding
    render.py                editor.Timeline with 3 tracks: video / audio / badges
    generator.py             end to end orchestration
    ship.py                  auto-commit + push + open PR + generate end-to-end
  focus_mode/
    builder.py               reviewer Focus Mode ranking
  contribution_map/
    scanner.py               read Claude Code session logs in the capture window
    mapper.py                classify diff lines as human / agent / mixed / unknown
  pr_description/
    generator.py             What / Why / Struggles / Follow-ups
  web/
    app.py                   FastAPI web server + landing mount
    qa.py                    @trace polling bot
```

## License

MIT.
