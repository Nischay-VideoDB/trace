# Implementation Plan: trace-cli

## Overview

This plan converts the design into an incremental, end-to-end testable build aligned to the 48-hour hackathon schedule in `BUILD_PLAN.md`. The demo spine ships first — `trace start` → indexed session → `Timeline` → narrated `PR_Video` posted to GitHub — before the differentiator features (Decision Replay, Reviewer Q&A, Contribution Map, Focus Mode, PR Description) layer onto the same `Session_Store` and the same VideoDB-indexed session.

Convert the feature design into a series of prompts for a code-generation LLM that will implement each step with incremental progress. Make sure that each prompt builds on the previous prompts, and ends with wiring things together. There should be no hanging or orphaned code that isn't integrated into a previous step. Focus ONLY on tasks that involve writing, modifying, or testing code.

Implementation language: **Python 3.11+** (specified in design). Stack: `typer`, `pydantic` v2, `httpx`, `hypothesis`, `fastapi`, `uvicorn`, `pyaudio`, `mss`, `ffmpeg-python`, `videodb`, `openai`, `anthropic`, `PyGithub`.

Schedule alignment (from `BUILD_PLAN.md`):

| Hours  | Tasks                                  |
|--------|-----------------------------------------|
| 0–2    | 1.x — project setup, VideoDB connected |
| 2–7    | 2.x — Feature 1: Session Capture (R1, R2, R10, R11) |
| 7–14   | 4.x — Feature 2: Timeline (R3)         |
| 14–22  | 6.x — Feature 3: PR Video (R4)         |
| 22–28  | 8.x — Feature 4: Decision Replay (R5)  |
| 28–32  | 9.x — Feature 5: Reviewer Q&A (R6)     |
| 32–36  | 11.x — Feature 6: Human vs Agent Map (R7) |
| 36–38  | 12.x — Feature 7: Reviewer Focus Mode (R8) |
| 38–40  | 13.x — Feature 8: PR Description (R9)  |
| 40–44  | 14.x — Polish                          |

Property tests use `hypothesis` with `@settings(max_examples=200, deadline=None)` and each test header tags the property number per the design's testing strategy.

## Tasks

- [ ] 1. Project scaffolding, external clients, and credentials
  - [ ] 1.1 Create `pyproject.toml` and lockfile
    - Pin Python `>=3.11`
    - Add runtime deps: `typer`, `pydantic>=2`, `httpx`, `fastapi`, `uvicorn[standard]`, `pyaudio`, `mss`, `ffmpeg-python`, `videodb`, `openai`, `anthropic`, `PyGithub`, `jinja2`
    - Add dev deps: `hypothesis`, `pytest`, `pytest-asyncio`, `pytest-mock`, `respx`
    - Configure `pytest` paths: `tests/unit`, `tests/property`, `tests/integration`; mark `integration` as opt-in
    - Configure `[project.scripts] trace = "trace_cli.cli:app"`
    - _Requirements: 11.1_

  - [ ] 1.2 Scaffold the `trace_cli` package layout
    - Create the directory tree from the design's File / Module Layout (`session/`, `capture/`, `indexing/`, `timeline/`, `pr_video/`, `decision_replay/`, `contribution_map/`, `focus_mode/`, `pr_description/`, `github/`, `videodb/`, `openai_clients/`, `anthropic_client/`, `web/`, `utils/`)
    - Create empty `__init__.py` files and a `trace_cli/__main__.py` that delegates to `cli.app`
    - Create the `tests/{unit,property,integration}` tree with empty `conftest.py` files
    - _Requirements: 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11_

  - [ ] 1.3 Implement `trace_cli/credentials.py`
    - `Credentials.is_missing(value)` returns True for `None`, empty, or whitespace-only
    - `Credentials.collect_missing(required)` returns the subset of names whose env value `is_missing`
    - `Credentials.redact(value)` matches Property 24 exactly: `len < 8` → `"********"`; otherwise prefix `len-4` `*` then last 4 chars
    - `Credentials.require(*names)` exits with code 2 listing every missing name on stderr (single message, no external calls before checking) and constructs a redacting `RedactingFormatter` for the `logging` package
    - _Requirements: 11.1, 11.2, 11.3_

  - [ ]* 1.4 Write property test for credential env var detection
    - **Property 23: Env var missingness detection**
    - Hypothesis strategy: arbitrary mappings of the four required env names to `None` / `""` / whitespace / non-empty strings; assert `collect_missing` returns exactly the missing subset
    - Header tag: `# Feature: trace-cli, Property 23: Env var missingness detection`
    - **Validates: Requirements 11.1, 11.2**

  - [ ]* 1.5 Write property test for credential redaction
    - **Property 24: Credential redaction**
    - Hypothesis strategy: `text()` of arbitrary length; assert length-8 stars when input shorter than 8; otherwise `len(out) == len(s)`, prefix all `*`, suffix `s[-4:]`
    - Header tag: `# Feature: trace-cli, Property 24: Credential redaction`
    - **Validates: Requirements 11.3**

  - [ ] 1.6 Implement `trace_cli/videodb/client.py` facade
    - Async wrappers for: `open_capture_session`, `stream_screen`, `stream_audio`, `close_capture_session`, `submit_for_indexing`, `index_status`, `semantic_search(query, scope, *, timeout)`, `register_timeline`, `assemble_video(clips, narration, *, w, h, fps, mix)`, `upload_video`
    - Inject the `VIDEODB_API_KEY` via `Credentials.require`
    - All methods must accept a `timeout` and surface vendor errors as typed exceptions (`VideoDBTimeout`, `VideoDBAuthError`, `VideoDBError`)
    - _Requirements: 1.2, 2.3, 3.7, 4.4, 4.5, 4.6, 5.1, 6.2_

  - [ ] 1.7 Implement `trace_cli/openai_clients/whisper.py` and `tts.py`
    - `WhisperClient.transcribe(audio_path)` returns a `Transcript`
    - `TTSClient.synthesize(text)` returns an `mp3` byte stream
    - Both honor a configurable timeout and propagate auth errors as `OpenAIAuthError`
    - _Requirements: 2.4, 2.7, 4.4_

  - [ ] 1.8 Implement `trace_cli/anthropic_client/client.py`
    - `AnthropicClient.flag_uncertainty(segments)` annotates `TranscriptSegment.uncertainty`
    - `AnthropicClient.extract_intents(transcript, screen_activity)` returns intent summaries
    - On failure, raise `AnthropicError` with a `category` field used by R3.3 fallback and R9.5 placeholder logic
    - _Requirements: 3.3, 4.3, 9.3, 9.5_

  - [ ] 1.9 Implement `trace_cli/github/client.py`
    - `GitHubClient.get_pr_diff(pr_url)` returns a `PRDiff`
    - `GitHubClient.post_comment(pr_url, body)` returns the comment URL
    - `GitHubClient.update_description(pr_url, new_description)` performs a read-modify-write that preserves the existing description for R9.8/R9.9
    - Distinguish auth errors (R4.10) from network/server errors (R9.10) via typed exceptions
    - _Requirements: 4.6, 4.10, 6.3, 7.6, 7.7, 8.4, 9.8, 9.9, 9.10_

- [ ] 2. Session lifecycle, capture, and indexing — Feature 1 (R1, R2, R10, R11)
  - [ ] 2.1 Define pydantic v2 models in `trace_cli/session/models.py`
    - `SessionMetadata`, `Heartbeat`, `Transcript`, `TranscriptSegment` exactly per design's Data Models
    - `SessionMetadata.session_id` validator enforcing the R10.1 alphabet and length, defaulting to UUID v4
    - `started_at` and `stopped_at` serialize as ISO 8601 UTC strings
    - _Requirements: 1.1, 10.1, 10.2, 10.3_

  - [ ] 2.2 Implement `trace_cli/session/store.py`
    - `SessionStore.session_dir(session_id)` rooted at `~/.trace/sessions/`
    - `write_metadata` / `update_metadata` are atomic (write-temp-then-rename) and preserve all previously written fields on update (R10.3)
    - `write_artifact(name, blob)` for `screen.mp4`, `audio.wav`, `transcript.json`, `timeline.json`, etc.
    - On missing parent path: create with `0o700` and retry the write exactly once within 5 seconds (R10.7)
    - On non-recoverable failure: emit error message naming the file + cause category, retain partial siblings, set `status=failed` (R10.6, R10.8)
    - `find_active()` scans status `active` or `recording`
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8_

  - [ ]* 2.3 Write property test for `SessionStore` partial-write durability
    - **Property 22: Partial-write durability**
    - Strategy: arbitrary `(write_A, write_B)` pairs of artifact names + blobs; inject a fault into one; assert the surviving sibling stays on disk and the error names the failed artifact
    - Header tag: `# Feature: trace-cli, Property 22: Partial-write durability`
    - **Validates: Requirements 10.6**

  - [ ]* 2.4 Write property test for metadata field preservation
    - **Property 4: Metadata transitions preserve fields**
    - Strategy: arbitrary existing metadata dicts + arbitrary update dicts; assert the result contains every original key-value plus exactly the new keys, no original removed/altered
    - Header tag: `# Feature: trace-cli, Property 4: Metadata transitions preserve fields`
    - **Validates: Requirements 2.2, 10.3**

  - [ ] 2.5 Implement `trace_cli/session/ids.py`
    - `new_session_id()` returns a UUID v4 lowercased with hyphens (36 chars, alphabet `[a-z0-9-]`, fits R10.1's 8–64)
    - `is_valid_session_id(s)` validator used by `SessionMetadata`
    - _Requirements: 1.1, 10.1_

  - [ ]* 2.6 Write property test for session metadata invariants
    - **Property 1: Session metadata invariants**
    - Strategy: invoke a fake `SessionManager.start` over many runs; assert UUID v4 format, length 8–64, alphabet, ISO 8601 UTC `started_at`, `status == "active"`, `capture_mode` and `mic_status` in their `Literal` sets
    - Header tag: `# Feature: trace-cli, Property 1: Session metadata invariants`
    - **Validates: Requirements 1.1, 10.1, 10.2**

  - [ ] 2.7 Implement `trace_cli/capture/service.py`
    - `CaptureService.start(session)` opens a VideoDB CaptureSession + RTStream with a 10-second connect budget; on success records `capture_mode="videodb"` and streams ≥15 FPS / ≥16 kHz
    - On VideoDB unreachable / timeout, switch to `FallbackCapture` and record `capture_mode="fallback"`
    - On microphone permission denied, continue screen capture and record `mic_status="denied"`, plus a stderr warning
    - `stop(timeout_seconds=30.0)` flushes within 30 s (R2.1)
    - _Requirements: 1.2, 1.5, 1.6, 2.1_

  - [ ] 2.8 Implement `trace_cli/capture/fallback.py`
    - `mss` screen frames piped through `ffmpeg-python` to `screen.mp4`
    - `pyaudio` + `wave` writes `audio.wav` (skipped when `mic_status="denied"`)
    - Same async surface as `CaptureService` so the two are interchangeable
    - _Requirements: 1.5, 1.6, 10.4_

  - [ ]* 2.9 Write property test for capture mode decision
    - **Property 2: Capture mode decision**
    - Strategy: parametrize over `(videodb_outcome, mic_outcome)` ∈ `{success_within_10s, timeout, error} × {granted, denied}`; assert `capture_mode == "videodb"` iff success-within-10s, `mic_status == "denied"` iff denied
    - Header tag: `# Feature: trace-cli, Property 2: Capture mode decision`
    - **Validates: Requirements 1.5, 1.6**

  - [ ] 2.10 Implement `trace_cli/capture/heartbeat.py`
    - `HeartbeatWriter` appends to `heartbeats.jsonl` at intervals ≤ 5 s with `elapsed_seconds`, `screen_bytes`, `audio_bytes`, `timestamp`
    - Writes are append-only and crash-safe (flush + fsync each line)
    - _Requirements: 1.7_

  - [ ]* 2.11 Write property test for heartbeat monotonicity
    - **Property 3: Heartbeat monotonicity**
    - Strategy: simulate capture runs of varying lengths and stream byte rates; assert every consecutive timestamp gap ≤ 5 s, and `elapsed_seconds`, `screen_bytes`, `audio_bytes` are non-decreasing
    - Header tag: `# Feature: trace-cli, Property 3: Heartbeat monotonicity`
    - **Validates: Requirements 1.7**

  - [ ] 2.12 Implement `trace_cli/capture/worker.py`
    - Detached background entry point that owns `CaptureService` + `HeartbeatWriter` until `stop.flag` is touched or SIGTERM is received
    - Writes `pid.lock` containing pid + start time, and `error.log` on unhandled exceptions
    - _Requirements: 1.7, 2.1_

  - [ ] 2.13 Implement `trace_cli/session/manager.py`
    - `SessionManager.start()` enforces no-active-session (R1.4), checks `SessionStore.ensure_writable()` within 5 s (R1.8), creates metadata, spawns the worker
    - `SessionManager.stop()` finds the active session, signals the worker, flushes within 30 s, and updates `metadata.json` with `stopped_at` UTC + `status="processing"` (R2.1, R2.2). Raises `NoActiveSession` for R2.6
    - _Requirements: 1.1, 1.4, 1.8, 2.1, 2.2, 2.6_

  - [ ] 2.14 Implement `trace_cli/utils/retry.py`
    - `async def retry(fn, *, max_attempts, base_delay, multiplier)` returns the first successful result; otherwise raises after `max_attempts` total attempts
    - Delay sequence: i-th delay (0-indexed) is `base_delay * multiplier ** i`; supports a separate `min_gap` policy for R7.7
    - _Requirements: 2.7, 7.7_

  - [ ]* 2.15 Write property test for retry helper attempts and backoff
    - **Property 6: Retry helper attempt and backoff invariants**
    - Strategy: arbitrary `(max_attempts, base_delay, multiplier)` and arbitrary outcome sequences; assert ≤ `max_attempts` calls, immediate success-termination, delay sequence equals `base_delay × multiplier ** i`; verify R2.7's `[1, 2, 4]` prefix and R7.7's `min_gap ≥ 2 s`
    - Header tag: `# Feature: trace-cli, Property 6: Retry helper attempt and backoff invariants`
    - **Validates: Requirements 2.7, 7.7**

  - [ ] 2.16 Implement `trace_cli/indexing/pipeline.py` and `transcripts.py`
    - `IndexingPipeline.run(session)` runs VideoDB indexing + Whisper transcription concurrently
    - Whisper transcription wrapped with `retry(max_attempts=4, base_delay=1.0, multiplier=2.0)` (1 initial + 3 retries) per R2.7
    - On both successes → `status="indexed"` + stdout confirmation (R2.5)
    - On indexing failure → `status="indexing_failed"`, print VideoDB error to stderr, exit non-zero (R2.8)
    - On transcription exhaustion → `status="transcription_failed"`, print error (R2.7)
    - _Requirements: 2.3, 2.4, 2.5, 2.7, 2.8_

  - [ ]* 2.17 Write property test for post-processing state transitions
    - **Property 5: Post-processing state transitions**
    - Strategy: enumerate `(indexing_outcome, transcription_outcome_after_0..3_retries)`; assert resulting `status ∈ {indexed, transcription_failed, indexing_failed}` per the truth table
    - Header tag: `# Feature: trace-cli, Property 5: Post-processing state transitions`
    - **Validates: Requirements 2.5, 2.7, 2.8**

  - [ ] 2.18 Wire `trace start` subcommand in `trace_cli/cli.py`
    - `Credentials.require("VIDEODB_API_KEY", "OPENAI_API_KEY")`
    - On success print `session_id` and absolute `Session_Store` path on separate lines, exit 0 (R1.3)
    - Active-session collision exits non-zero with active id on stderr (R1.4)
    - Unwritable store path exits non-zero within 5 s, never opening any capture stream (R1.8)
    - _Requirements: 1.1, 1.3, 1.4, 1.6, 1.8, 11.1, 11.2_

  - [ ] 2.19 Wire `trace stop` subcommand in `trace_cli/cli.py`
    - Triggers `SessionManager.stop()` then `IndexingPipeline.run()`
    - No-active-session exits non-zero with stderr message (R2.6)
    - On success prints confirmation identifying the session (R2.5)
    - _Requirements: 2.1, 2.2, 2.5, 2.6, 2.7, 2.8, 11.1, 11.2_

  - [ ]* 2.20 Write CLI example tests for start/stop
    - Cover R1.3 (stdout format), R1.4 (active-session collision), R1.8 (unwritable path within 5 s), R2.6 (no active), R10.4 (`screen.mp4` + `audio.wav` exist after stop)
    - _Requirements: 1.3, 1.4, 1.8, 2.6, 10.4, 10.5_

- [ ] 3. Checkpoint — capture pipeline end-to-end
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. Timeline builder — Feature 2 (R3)
  - [ ] 4.1 Define `TaggedMoment` and `Timeline` pydantic models in `trace_cli/timeline/models.py`
    - `TaggedMoment` fields per design with `Field(ge=0)` on `start_seconds`, `Field(ge=0.0, le=1.0)` on `confidence`, and a `model_validator` enforcing `end_seconds > start_seconds` (R3.8)
    - `Timeline` carries `session_id`, `session_end_seconds`, ordered `moments`
    - _Requirements: 3.2, 3.8_

  - [ ] 4.2 Implement progress classifier in `trace_cli/timeline/classifiers/progress.py`
    - For each editor file save event at time `T`, emit `progress` over `[max(0, T-5), min(session_end, T+5)]` (R3.5)
    - _Requirements: 3.5_

  - [ ] 4.3 Implement stuck classifier in `trace_cli/timeline/classifiers/stuck.py`
    - Use `AnthropicClient.flag_uncertainty` to mark uncertain transcript segments
    - Emit `stuck` for any contiguous interval of duration ∈ `[90 s, 1800 s]` with no save event AND ≥1 uncertainty-flagged segment (R3.3)
    - On Anthropic failure, drop candidates so the merger still produces a timeline (per design Error Handling)
    - _Requirements: 3.3_

  - [ ] 4.4 Implement research classifier in `trace_cli/timeline/classifiers/research.py`
    - Consume VideoDB index labels for the foreground window per interval; emit `research` when interval ≥ 15 s and label ∈ `{documentation, browser_search, reference_material}` and the foreground window is not the editor (R3.4)
    - _Requirements: 3.4_

  - [ ] 4.5 Implement speech classifier in `trace_cli/timeline/classifiers/speech.py`
    - For transcript segments of duration ∈ `[1 s, 60 s]` containing ≥ 3 words, emit `speech` with `evidence` set to the transcript text (R3.6)
    - _Requirements: 3.6_

  - [ ]* 4.6 Write property test for classifier well-formedness
    - **Property 7: Classifier well-formedness**
    - Strategy: `indexed_session_strategy()` from `tests/property/strategies.py`; for each candidate emitted by each classifier assert its rule's preconditions per design Property 7
    - Header tag: `# Feature: trace-cli, Property 7: Classifier well-formedness`
    - **Validates: Requirements 3.3, 3.4, 3.5, 3.6**

  - [ ] 4.7 Implement timeline merger in `trace_cli/timeline/builder.py` (with helpers in `coverage.py` and `priority.py`)
    - Boundary-pair sweep over the union of candidate boundaries plus `{0, session_end}`
    - For each `[a, b)` interval, pick the highest-priority candidate covering it under `progress > stuck > research > speech`; if no candidate covers it, emit `progress` with `confidence == 0.0` (R3.10, R3.11)
    - Coalesce adjacent intervals sharing `(category, evidence)` to keep moments minimal
    - Validate disjoint, contiguous, gap-free coverage from `0` to `session_end_seconds` (R3.1)
    - _Requirements: 3.1, 3.2, 3.10, 3.11_

  - [ ]* 4.8 Write property test for timeline contiguity and priority merge
    - **Property 8: Timeline contiguity and priority merge**
    - Strategy: `timeline_candidates_strategy()` over arbitrary overlapping candidate sets and arbitrary `session_end`; assert `moments[0].start == 0`, contiguous chain, `moments[-1].end == session_end`, every category in the literal set, every point's category equals the highest-priority covering candidate (fallback `progress` confidence 0.0 when none)
    - Use `@settings(max_examples=200, deadline=None)`
    - Header tag: `# Feature: trace-cli, Property 8: Timeline contiguity and priority merge`
    - **Validates: Requirements 3.1, 3.2, 3.10, 3.11**

  - [ ] 4.9 Implement Timeline JSON serialization in `trace_cli/timeline/builder.py`
    - `TimelineBuilder.to_json(timeline)` and `from_json(raw)` using pydantic `model_dump_json` / `model_validate_json` with stable field ordering and float formatting
    - _Requirements: 3.8, 3.9_

  - [ ]* 4.10 Write property test for timeline JSON round-trip
    - **Property 9: Timeline JSON round-trip**
    - Strategy: `timeline_strategy()` produces valid `Timeline` values; assert `from_json(to_json(t)) == t` for arbitrary timelines
    - Header tag: `# Feature: trace-cli, Property 9: Timeline JSON round-trip`
    - **Validates: Requirements 3.9**

  - [ ] 4.11 Wire `TimelineBuilder` into `IndexingPipeline`
    - After indexing + transcription succeed, run all four classifiers, merge, validate, persist `timeline.json` via `SessionStore`, register the timeline with `VideoDBClient.register_timeline`
    - On either persist or register failure, do not advertise the timeline as available and surface an error identifying which step failed (R3.12)
    - _Requirements: 3.7, 3.12, 10.5_

- [ ] 5. Checkpoint — timeline coverage validated
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 6. PR Video generator — Feature 3 (R4)
  - [ ] 6.1 Implement PR URL validator in `trace_cli/pr_video/url.py`
    - `validate_pr_url(s)` succeeds iff `s` matches `https://github.com/{owner}/{repo}/pull/{number}` with non-empty owner/repo of GitHub identifier characters and positive integer number
    - Returns a structured error identifying the invalid value and expected format on failure (R4.7)
    - _Requirements: 4.7_

  - [ ]* 6.2 Write property test for PR URL validator
    - **Property 12: PR URL validator**
    - Strategy: arbitrary strings + a generator of valid PR URLs; assert success iff the URL matches the pattern
    - Header tag: `# Feature: trace-cli, Property 12: PR URL validator`
    - **Validates: Requirements 4.7**

  - [ ] 6.3 Implement `PRDiff` model and GitHub diff loader
    - `PRDiff`, `FileDiff`, `DiffHunk` pydantic models per design
    - `GitHubClient.get_pr_diff(pr_url)` returns a `PRDiff` with 1-indexed `added_lines` / `modified_lines` and a `changed_line_count` property
    - _Requirements: 4.1, 4.2, 7.1, 9.2_

  - [ ] 6.4 Implement `ClipSelector` in `trace_cli/pr_video/selector.py`
    - Eligible = `progress` moments whose evidence file ∈ `diff.files`
    - Total > 90 s → descending-timestamp dedup, keeping at least one clip per such file when achievable within 90 s (R4.2)
    - Total < 30 s → pad with adjacent moments to reach ≥ 30 s; if cannot reach 30 s raise `InsufficientContent` (R4.9)
    - _Requirements: 4.1, 4.2, 4.9_

  - [ ]* 6.5 Write property test for clip selection budget
    - **Property 10: Clip selection budget**
    - Strategy: `pr_diff_strategy()` × `timeline_strategy()`; assert either total in `[30, 90]` seconds with file coverage and tie-breaking, or `InsufficientContent` exactly when qualifying duration < 30 s
    - Header tag: `# Feature: trace-cli, Property 10: Clip selection budget`
    - **Validates: Requirements 4.1, 4.2, 4.9**

  - [ ] 6.6 Implement `NarrationBuilder` in `trace_cli/pr_video/narration.py`
    - Pull transcript segments overlapping each selected clip
    - Call `AnthropicClient.extract_intents`, then summarize/truncate the script to ≤ 1500 characters (R4.3)
    - _Requirements: 4.3_

  - [ ]* 6.7 Write property test for narration script length cap
    - **Property 11: Narration script length cap**
    - Strategy: arbitrary clip lists + arbitrary indexed sessions; assert `len(script) ≤ 1500`
    - Header tag: `# Feature: trace-cli, Property 11: Narration script length cap`
    - **Validates: Requirements 4.3**

  - [ ] 6.8 Implement `Renderer` in `trace_cli/pr_video/render.py`
    - Synthesize narration via `TTSClient.synthesize`
    - Assemble via `VideoDBClient.assemble_video(clips, narration, w=1920, h=1080, fps=30, mix={"narration":1.0,"clip":0.3})` (R4.4, R4.5)
    - Returns a `RenderedVideo` with local path + playback URL after upload
    - _Requirements: 4.4, 4.5_

  - [ ] 6.9 Implement `PRVideoGenerator` orchestration in `trace_cli/pr_video/generator.py`
    - Validate PR URL (R4.7), load session (R4.8), fetch diff, run `ClipSelector` (R4.1, R4.2, R4.9), build narration, render, upload, post PR comment with playback URL within 60 s of render completion (R4.6)
    - On GitHub auth error → exit non-zero, preserve `pr_video.mp4` (R4.10)
    - On VideoDB upload or TTS failure → exit non-zero, preserve `pr_video.mp4` and `narration_script.txt` (R4.11)
    - _Requirements: 4.6, 4.7, 4.8, 4.10, 4.11_

  - [ ] 6.10 Wire `trace generate <session_id> <pr_url> [--focus]` in `trace_cli/cli.py`
    - `Credentials.require("VIDEODB_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GITHUB_TOKEN")`
    - Calls `PRVideoGenerator.generate` first (demo spine); contribution map / focus / description tasks plug into this command in later phases
    - _Requirements: 4.6, 4.7, 4.8, 4.9, 4.10, 4.11, 11.1, 11.2_

  - [ ]* 6.11 Write CLI example tests for `trace generate` happy path and error paths
    - Cover R4.7 (invalid PR URL message + non-zero exit), R4.8 (missing session id message + non-zero), R4.9 (insufficient content), R4.10 (auth error preserves PR video), R4.11 (TTS / VideoDB upload failure preserves artifacts)
    - _Requirements: 4.7, 4.8, 4.9, 4.10, 4.11_

- [ ] 7. Checkpoint — demo spine working (`start` → `stop` → `generate` → PR video posted)
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 8. Decision Replay — Feature 4 (R5)
  - [ ] 8.1 Implement line-range validator in `trace_cli/decision_replay/range.py`
    - `validate_line_range(start, end)` succeeds iff both are integers ≥ 1 and `start ≤ end`; otherwise structured error per R5.6
    - _Requirements: 5.6_

  - [ ]* 8.2 Write property test for line-range validator
    - **Property 14: Line-range validator**
    - Strategy: arbitrary integer pairs (including negatives, zeros, swaps); assert success iff `start ≥ 1 ∧ end ≥ 1 ∧ start ≤ end`
    - Header tag: `# Feature: trace-cli, Property 14: Line-range validator`
    - **Validates: Requirements 5.6**

  - [ ] 8.3 Define `ReplayInterval` model and per-line diff slicer
    - `ReplayInterval` per design (`start_seconds`, `end_seconds > start_seconds`, `diff`, `clip_url`)
    - `decision_replay/diff.py` slices the file diff to lines within the requested range
    - _Requirements: 5.2_

  - [ ] 8.4 Implement `DecisionReplayService.query` in `trace_cli/decision_replay/service.py`
    - Validate range first (R5.6); raise `FileNotInSession` (R5.5) when `file_path` absent from any recorded session
    - Resolve VideoDB clips and editor edit events whose touched lines intersect the range
    - Return intervals sorted by ascending `start_seconds` then ascending `end_seconds` (R5.4); empty list with informational message when no edits found (R5.3)
    - 10-second total time budget enforced via `asyncio.wait_for` (R5.1)
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [ ]* 8.5 Write property test for decision replay ordering and shape
    - **Property 13: Decision replay ordering and shape**
    - Strategy: arbitrary indexed sessions + valid `(file_path, start_line, end_line)` queries; assert sorted ascending start then end, every interval `end > start`, non-empty `diff` and `clip_url`, and empty list iff no interval recorded an edit affecting any line in `[start_line, end_line]`
    - Header tag: `# Feature: trace-cli, Property 13: Decision replay ordering and shape`
    - **Validates: Requirements 5.2, 5.3, 5.4**

  - [ ] 8.6 Wire `trace replay --session <id> --file <path> --start <n> --end <n>` in `trace_cli/cli.py`
    - On invalid range, print error message identifying the invalid range and exit non-zero (R5.6)
    - On `FileNotInSession`, print the R5.5 message and exit non-zero
    - _Requirements: 5.1, 5.5, 5.6_

  - [ ] 8.7 Implement FastAPI replay UI and JSON API
    - `trace_cli/web/app.py` exposes `GET /replay/ui` (Jinja2 template with paste form + embedded VideoDB clip players) and `GET /replay/api?session_id&path&start&end` returning JSON intervals from `DecisionReplayService.query`
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

- [ ] 9. Reviewer Q&A — Feature 5 (R6)
  - [ ] 9.1 Implement `extract_question(comment)` in `trace_cli/web/qa_extract.py`
    - Take everything after the first literal `@trace` token, strip leading/trailing whitespace, truncate to 1000 characters (R6.1)
    - _Requirements: 6.1_

  - [ ]* 9.2 Write property test for `@trace` question extraction
    - **Property 15: `@trace` question extraction**
    - Strategy: arbitrary comment strings (including no `@trace`, multiple `@trace`, trailing whitespace, very long tails); assert the result equals the substring after the first `@trace`, stripped, truncated to ≤ 1000 chars
    - Header tag: `# Feature: trace-cli, Property 15: @trace question extraction`
    - **Validates: Requirements 6.1**

  - [ ] 9.3 Implement `ReviewerQA.build_reply` in `trace_cli/web/qa_reply.py`
    - Filter hits by `relevance ≥ 0.3`, take top 3 in descending relevance (R6.3, R6.4)
    - Compose a single reply with text ≤ 500 characters and up to 3 clip URLs; if zero hits ≥ 0.3, reply with text only stating no matching content (R6.4)
    - _Requirements: 6.3, 6.4_

  - [ ]* 9.4 Write property test for reviewer reply structure
    - **Property 16: Reviewer reply structure**
    - Strategy: arbitrary lists of `(score, clip_url)` hits; assert text length ≤ 500, ≤ 3 clip URLs ordered by descending relevance, only hits with `relevance ≥ 0.3` included, and zero clips when none meet the threshold
    - Header tag: `# Feature: trace-cli, Property 16: Reviewer reply structure`
    - **Validates: Requirements 6.3, 6.4**

  - [ ] 9.5 Implement `POST /webhook/github` handler in `trace_cli/web/webhook.py`
    - Pipeline: `extract_question` → empty? reply per R6.6 → lookup session by PR URL → none? reply per R6.5 → `VideoDBClient.semantic_search(query, scope, timeout=30.0)` → timeout/error? reply per R6.7 → `build_reply` → `GitHubClient.post_comment`
    - Always return HTTP 200 to GitHub once the reply attempt completes (per design)
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7_

  - [ ] 9.6 Wire `trace serve [--host] [--port]` in `trace_cli/cli.py`
    - `Credentials.require("VIDEODB_API_KEY", "GITHUB_TOKEN")`
    - Runs `uvicorn` against `trace_cli.web.app:app` (replay UI + webhook)
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 11.1, 11.2_

- [ ] 10. Checkpoint — interactive features online
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 11. Human vs Agent Contribution Map — Feature 6 (R7)
  - [ ] 11.1 Implement evidence extractor in `trace_cli/contribution_map/evidence.py`
    - Read keystroke events, AI-completion events, and paste events (with source-window labels) from the indexed session
    - Bucket events per `(file_path, line_number)` for fast lookup by the mapper
    - _Requirements: 7.2, 7.3, 7.4, 7.5_

  - [ ] 11.2 Implement `ContributionMapper.classify` in `trace_cli/contribution_map/mapper.py`
    - For every added or modified line in the diff:
      - Only AI-source paste/completion → `agent` (R7.2)
      - Only human keystroke evidence → `human` (R7.3)
      - Both kinds overlap the line in the same session → `mixed` (R7.4)
      - No evidence or insufficient → `unknown` (R7.5)
    - Output `ContributionMap` covers 100% of added + modified lines (R7.1)
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

  - [ ]* 11.3 Write property test for contribution map classification correctness
    - **Property 17: Contribution map classification correctness**
    - Strategy: arbitrary `(indexed_session, pr_diff)` pairs with synthesized event traces; assert 100% diff coverage, exactly one label per line, and the label↔evidence mapping per design Property 17
    - Header tag: `# Feature: trace-cli, Property 17: Contribution map classification correctness`
    - **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5**

  - [ ] 11.4 Implement comment renderer in `trace_cli/contribution_map/comment.py`
    - For each `FileContribution`, emit the file path and integer counts for `human`, `agent`, `mixed`, `unknown` (R7.6)
    - _Requirements: 7.6_

  - [ ]* 11.5 Write property test for comment rendering
    - **Property 18: Contribution map comment rendering**
    - Strategy: arbitrary `ContributionMap` values; assert the rendered comment contains every file path and the four integer counts for each file
    - Header tag: `# Feature: trace-cli, Property 18: Contribution map comment rendering`
    - **Validates: Requirements 7.6**

  - [ ] 11.6 Implement contribution map posting with retry
    - Use `retry(max_attempts=3, base_delay=2.0, multiplier=1.0)` (with `min_gap=2.0`) per R7.7; on exhaustion exit non-zero with PR-comment-failure error message
    - _Requirements: 7.6, 7.7_

  - [ ] 11.7 Wire `ContributionMapper` into `trace generate`
    - After PR video posts, call `ContributionMapper.classify` then post the per-file summary via the retry-aware poster
    - _Requirements: 7.1, 7.6, 7.7_

- [ ] 12. Reviewer Focus Mode — Feature 7 (R8)
  - [ ] 12.1 Implement `FocusModeBuilder.build` in `trace_cli/focus_mode/builder.py`
    - Rule A: include every file referenced by ≥ 1 `stuck` Tagged_Moment, with `reason="stuck Tagged_Moment"` and ranges from those moments — even if 0 changed lines in the diff (R8.2)
    - Rule B: include every diff file with `changed_line_count ≥ 50`, with `reason="large change"` and ranges from diff hunks (R8.3)
    - Each entry has 1-indexed inclusive `(start_line, end_line)` ranges with `start_line ≤ end_line` (R8.1)
    - _Requirements: 8.1, 8.2, 8.3_

  - [ ]* 12.2 Write property test for focus mode coverage
    - **Property 19: Focus mode coverage**
    - Strategy: arbitrary `(timeline, pr_diff)` pairs; assert every stuck-referenced file appears with `stuck Tagged_Moment` reason (regardless of diff), every diff file with ≥ 50 changed lines appears with `large change` reason, and every entry has non-empty 1-indexed ranges with `start_line ≤ end_line`
    - Header tag: `# Feature: trace-cli, Property 19: Focus mode coverage`
    - **Validates: Requirements 8.2, 8.3**

  - [ ] 12.3 Wire `--focus` flag in `trace generate`
    - When set: build the focus artifact, persist to `focus_mode.json`, post a single PR comment listing files / ranges / reasons (R8.4)
    - When focus artifact has zero entries, post the R8.5 "no files met focus criteria" comment and exit success
    - On post failure, retain `focus_mode.json` locally, emit error message, exit non-zero (R8.6)
    - _Requirements: 8.1, 8.4, 8.5, 8.6_

- [ ] 13. Context-Aware PR Description — Feature 8 (R9)
  - [ ] 13.1 Implement `PRDescriptionGenerator.render` in `trace_cli/pr_description/generator.py`
    - `## What changed` precedes `## Why` (R9.1)
    - `What changed`: one bullet per changed file, max 50 bullets followed by a single overflow bullet stating the count of additional files when diff has > 50 (R9.2)
    - `Why` from `AnthropicClient.extract_intents`; placeholder when transcript and screen activity are both empty (R9.4); placeholder + surfaced error when extraction fails (R9.5)
    - Append video link iff video artifact present (R9.6); append contribution-map comment link iff present (R9.7)
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7_

  - [ ]* 13.2 Write property test for PR description structure
    - **Property 20: PR description structure**
    - Strategy: arbitrary `(pr_diff, indexed_session, video?, contribution_url?)`; assert `## What changed` precedes `## Why`, ≤ 50 file bullets + exactly one overflow bullet when diff > 50 files, video link present iff video provided, contribution link present iff URL provided
    - Header tag: `# Feature: trace-cli, Property 20: PR description structure`
    - **Validates: Requirements 9.1, 9.2, 9.6, 9.7**

  - [ ] 13.3 Implement `apply_description(existing, generated)` in `trace_cli/pr_description/apply.py`
    - Empty existing → `final == generated` (R9.9)
    - Non-empty existing → `final == existing + "\n\n" + generated` (R9.8)
    - Never modifies any character of `existing`
    - _Requirements: 9.8, 9.9_

  - [ ]* 13.4 Write property test for PR description append-only
    - **Property 21: PR description append-only**
    - Strategy: arbitrary `(existing, generated)` strings; assert `final.startswith(existing)`, `existing + "\n\n" + generated` for non-empty existing, `existing + generated` (which equals `generated`) when empty, no character of `existing` mutated
    - Header tag: `# Feature: trace-cli, Property 21: PR description append-only`
    - **Validates: Requirements 9.8, 9.9**

  - [ ] 13.5 Wire PR description update into `trace generate`
    - Call `GitHubClient.update_description` using `apply_description`; on network/auth failure preserve existing PR description unchanged and surface an error indication identifying the failure category (R9.10)
    - _Requirements: 9.1, 9.6, 9.7, 9.8, 9.9, 9.10_

- [ ] 14. Polish
  - [ ] 14.1 Wire `RedactingFormatter` into the global logging config and `safe_print` helpers
    - Apply to stdout, stderr, and any log handlers; ensure no vendor SDK log path bypasses the redactor (R11.3)
    - _Requirements: 11.3_

  - [ ] 14.2 Write `README.md` documenting the CLI surface and configuration
    - `trace start` / `stop` / `generate` / `replay` / `serve`, required env vars, Session_Store layout
    - _Requirements: 1, 2, 4, 5, 6, 8, 9, 10, 11_

  - [ ]* 14.3 Add integration smoke tests under `tests/integration/`
    - `test_capture_smoke.py` — VideoDB CaptureSession configured at ≥ 15 FPS / 16 kHz (R1.2)
    - `test_pr_video_render_smoke.py` — VideoDB Timeline assemble at 1920×1080 @ 30 fps with mix `1.0:0.3` (R4.4, R4.5)
    - `test_webhook_smoke.py` — FastAPI webhook against a fixture GitHub PR comment payload
    - All tagged `@pytest.mark.integration`, skipped unless required env vars are set
    - _Requirements: 1.2, 4.4, 4.5, 6.1_

- [ ] 15. Final checkpoint — full demo spine + features green
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP, but the property-based tests collectively exercise all 24 design properties and are the centerpiece of correctness coverage. Skip them only if the 48-hour clock forces it.
- Each property test header MUST tag the property number (`# Feature: trace-cli, Property N: <title>`) and use `@settings(max_examples=200, deadline=None)` so coverage is auditable from the test files alone.
- The demo spine is `1.x → 2.x → 4.x → 6.x` (Hours 0–22 of the build plan); ship it green before starting feature 4.
- All vendor SDK calls go through `trace_cli/videodb/`, `trace_cli/openai_clients/`, `trace_cli/anthropic_client/`, `trace_cli/github/` so the rest of the codebase stays unmocked in tests.
- Coverage of the 24 properties: P1 → 2.6 · P2 → 2.9 · P3 → 2.11 · P4 → 2.4 · P5 → 2.17 · P6 → 2.15 · P7 → 4.6 · P8 → 4.8 · P9 → 4.10 · P10 → 6.5 · P11 → 6.7 · P12 → 6.2 · P13 → 8.5 · P14 → 8.2 · P15 → 9.2 · P16 → 9.4 · P17 → 11.3 · P18 → 11.5 · P19 → 12.2 · P20 → 13.2 · P21 → 13.4 · P22 → 2.3 · P23 → 1.4 · P24 → 1.5.
- Coverage of the 11 requirements: R1 → 2.1, 2.5, 2.7, 2.8, 2.10, 2.12, 2.13, 2.18, 2.20 · R2 → 2.13, 2.16, 2.19 · R3 → 4.1–4.11 · R4 → 6.1–6.11 · R5 → 8.1, 8.3, 8.4, 8.6, 8.7 · R6 → 9.1, 9.3, 9.5, 9.6 · R7 → 11.1, 11.2, 11.4, 11.6, 11.7 · R8 → 12.1, 12.3 · R9 → 13.1, 13.3, 13.5 · R10 → 2.1, 2.2, 2.20, 4.11 · R11 → 1.3, 2.18, 2.19, 6.10, 9.6, 14.1.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["1.3", "1.6", "1.7", "1.8", "1.9", "2.1", "2.5", "2.14"] },
    { "id": 3, "tasks": ["1.4", "1.5", "2.2", "2.6", "2.15"] },
    { "id": 4, "tasks": ["2.3", "2.4", "2.7", "2.8", "2.10", "2.16"] },
    { "id": 5, "tasks": ["2.9", "2.11", "2.12", "2.17"] },
    { "id": 6, "tasks": ["2.13"] },
    { "id": 7, "tasks": ["2.18"] },
    { "id": 8, "tasks": ["2.19", "4.1"] },
    { "id": 9, "tasks": ["2.20", "4.2", "4.3", "4.4", "4.5", "4.9"] },
    { "id": 10, "tasks": ["4.6", "4.7", "4.10"] },
    { "id": 11, "tasks": ["4.8", "4.11", "6.1", "6.3"] },
    { "id": 12, "tasks": ["6.2", "6.4", "6.6", "6.8"] },
    { "id": 13, "tasks": ["6.5", "6.7", "6.9"] },
    { "id": 14, "tasks": ["6.10"] },
    { "id": 15, "tasks": ["6.11", "8.1", "8.3", "9.1", "11.1", "12.1", "13.1", "13.3"] },
    { "id": 16, "tasks": ["8.2", "8.4", "9.2", "9.3", "11.2", "11.4", "12.2", "13.2", "13.4"] },
    { "id": 17, "tasks": ["8.5", "8.7", "9.4", "9.5", "11.3", "11.5", "11.6"] },
    { "id": 18, "tasks": ["8.6", "11.7"] },
    { "id": 19, "tasks": ["9.6", "12.3"] },
    { "id": 20, "tasks": ["13.5"] },
    { "id": 21, "tasks": ["14.1", "14.2", "14.3"] }
  ]
}
```
