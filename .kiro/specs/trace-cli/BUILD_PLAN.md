# Trace — Hackathon Build Plan (Context)

> Project name is **trace** (not "preel" as the source plan called it). All CLI
> commands use `trace` (e.g. `trace start`, `trace stop`, `trace generate`).

## Hackathon Context

- **Event:** VideoDB "Give Agents Eyes and Ears" — 48-hour solo hackathon
- **Window:** May 16, 2026 10:00 IST → May 18, 2026 10:00 IST
- **Prizes:** $1,500 1st / $1,000 2nd
- **Mandatory VideoDB usage:**
  - CaptureSession / RTStream — capture screen, audio, camera, agent activity
  - Search / Memory / Context — convert capture to searchable agent context
- **Judging:**
  - Technical execution — 40%
  - Creativity & originality — 30%
  - Depth of VideoDB usage — 30%
- **Submission:** working demo (video walkthrough or live link) + public GitHub repo + 200-word description

## One-Liner

Trace watches you code, understands your reasoning, and auto-generates a narrated video walkthrough for your PR — with session memory that answers reviewer questions.

## Features in Priority Order

### 🔴 CORE — Must ship

1. **Session Capture** — RTStream records screen + mic for the entire coding session, stored in VideoDB. CLI: `trace start` / `trace stop`.
2. **Session Intelligence Timeline** — Process the session into tagged moments:
   - 🔴 Stuck (long pauses, repeated edits, same file opened 3x)
   - 🟡 Researching (browser opened, Stack Overflow on screen)
   - 🟢 Progress (file saved, terminal shows success)
   - 🎤 Speaking (voice detected, transcribed)
   - This is the depth-of-VideoDB-usage scorer.
3. **PR Video Generation** — Pull key clips via VideoDB search, write narration from spoken words + timeline context, OpenAI TTS voiceover, assemble via VideoDB Timeline API. 90 seconds max, streamable link.

### 🟡 STRONG — Differentiators

4. **Decision Replay** — Click any code block, see initial attempt → failed test → fix → final, including terminal errors and spoken reasoning.
5. **Reviewer Q&A** — `@trace` mention in PR comment triggers semantic search over session memory, replies with text + timestamped clip.
6. **Human vs Agent Contribution Map** — Per-line classification (AI generated / human edited / human verified), summary card on the PR.

### 🟢 POLISH — If time allows

7. **Reviewer Focus Mode** — Compress 2000 LOC PR → "Review these 4 areas carefully" with session-evidence.
8. **Context-Aware PR Description** — What changed (diff) + Why (voice) + What you struggled with (stuck moments) + What needs follow-up (verbal flags).
9. **Replay the Bug** — Failing behavior → terminal error → fix as a mini clip embedded in the PR.

## Tech Stack

| Layer            | Tool                                       |
|------------------|--------------------------------------------|
| Capture          | VideoDB CaptureSession + RTStream          |
| Storage + Search | VideoDB indexing + semantic search         |
| Video Assembly   | VideoDB Timeline API                       |
| Voiceover        | OpenAI TTS                                 |
| Diff Analysis    | GitHub API                                 |
| AI Contributions | Detect via Claude Code session logs        |
| PR Integration   | GitHub API — comments, descriptions        |
| Interface        | Simple CLI + minimal web UI for Decision Replay |

## 48-Hour Schedule

| Hours  | Task                                                          |
|--------|---------------------------------------------------------------|
| 0–2    | Project setup, VideoDB connected, Claude Code ready           |
| 2–7    | Feature 1 — Session Capture working end to end                |
| 7–14   | Feature 2 — Timeline builder, all 4 moment types tagged       |
| 14–22  | Feature 3 — PR Video generated, narrated, streamable          |
| 22–28  | Feature 4 — Decision Replay                                   |
| 28–32  | Feature 5 — Reviewer Q&A                                      |
| 32–36  | Feature 6 — Human vs Agent Map                                |
| 36–38  | Feature 7 — Reviewer Focus Mode                               |
| 38–40  | Feature 8 — PR Description auto-generated                     |
| 40–44  | Polish — output video quality, UI, edge cases                 |
| 44–46  | Record demo walkthrough video                                 |
| 46–48  | README, 200-word description, GitHub repo, submit             |

## Demo Script (≤4 mins, win the room)

| Minute | What happens                                                                |
|--------|------------------------------------------------------------------------------|
| 0:00   | "Trace watches you code." Hit `trace start`                                  |
| 0:10   | Code a small feature live — hit a bug, google it, speak reasoning            |
| 2:00   | Hit `trace stop` — "Now watch what happened."                                |
| 2:05   | Show Session Timeline — red/yellow/green moments visualized                  |
| 2:20   | Play the 90-second PR video — narrated, clips, real voice                    |
| 2:50   | Show PR on GitHub — video link + description already posted                  |
| 3:10   | Click a code block → Decision Replay shows full thought history              |
| 3:30   | Reviewer asks `@trace` question → Trace answers with a session clip          |
| 3:45   | Show Human vs Agent map — "78% AI, 100% human verified"                      |
| 4:00   | Done                                                                          |

## 200-Word Submission Description (draft)

Trace gives your pull requests a memory. It watches your entire coding session — screen, voice, terminal, AI interactions — and builds a living record of how your code was actually written.

When you open a PR, Trace automatically generates a narrated 90-second video walkthrough using clips from your real session and your own spoken reasoning — not just the diff. It posts this directly to your PR alongside a context-aware description that explains not just what changed, but why.

The session memory stays alive. Reviewers can click any code block to see Decision Replay — the full evolution of that code, including failed attempts, terminal errors, AI suggestions, and human corrections. They can ask `@trace` any question and get an answer backed by a timestamped clip from your session.

Trace also generates a Human vs Agent Contribution Map, showing exactly which parts of the code were AI-generated vs human-edited vs human-verified — trust infrastructure for the age of agentic coding.

Built on VideoDB's CaptureSession, RTStream, semantic search, and Timeline API.

Start with `trace start`. Everything else follows.

## Design Priorities Driven By This Plan

1. **VideoDB-first architecture.** Every capture/index/search/assembly path goes through VideoDB; the depth-of-VideoDB-usage score (30%) depends on this being visible across multiple components, not just capture.
2. **Vertical slice for the demo.** The CORE three features (capture → timeline → PR video) must be the primary integration path — every other component plugs into the same pipeline rather than creating parallel paths.
3. **48-hour buildability.** Prefer single-process Python with a thin async layer; defer service decomposition. Web UI for Decision Replay is minimal (FastAPI + a single page).
4. **Submission artifacts.** The design must support producing the streamable PR video link, GitHub PR comment, and a working `@trace` webhook by hour 32.
5. **Solo build.** No multi-process orchestration, no message queues, no auth complexity beyond API keys.
