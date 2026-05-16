# Trace — Spec

## What it does
Trace watches a coding session (screen + mic) and auto-generates 
a narrated PR video with session memory for reviewers.

## Core requirements
1. CLI: `trace start` begins screen + audio capture via VideoDB RTStream
2. CLI: `trace stop` ends session, triggers processing pipeline
3. CLI: `trace generate` assembles PR video and posts to GitHub

## Features in priority order
1. Session capture — screen + mic → VideoDB
2. Timeline builder — tag stuck/research/progress/speech moments
3. PR video — 90 sec narrated video from session clips
4. Decision Replay — click code block, see its full evolution
5. Reviewer Q&A — @trace answers questions with session clips
6. Human vs Agent map — AI vs human contribution overlay
7. Reviewer Focus Mode — compress PR to key review areas
8. PR Description — context-aware, includes why not just what

## APIs used
- VideoDB: CaptureSession, RTStream, indexing, semantic search, Timeline API
- OpenAI: TTS for narration, Whisper for transcription
- GitHub API: post PR comments, descriptions, video links
- Anthropic API: intent extraction, uncertainty detection

## Stack
- Python 3.11+
- FastAPI for the web UI
- mss + pyaudio for screen/audio capture fallback