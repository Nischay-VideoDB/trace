#!/usr/bin/env bash
# Interactive 10-min demo pacer for trace.
# Drives a real coding session that exercises all 9 features:
#   capture, timeline (progress/research/speech/stuck), PR video,
#   decision replay, Q&A, contribution map, focus mode, PR description, bug replay.
#
# Flow:
#   1. Clones/refreshes trace-test repo in /tmp.
#   2. Creates a feature branch.
#   3. Walks YOU through 10 timed beats. Press ENTER to advance each beat.
#   4. After session: pushes branch, opens PR, runs `trace stop` + `trace generate`.
#
# You must SPEAK the prompted lines out loud during voice beats — narration
# quality depends on real audio.

set -euo pipefail

REPO_URL="${REPO_URL:-git@github.com:crypticsaiyan/trace-test.git}"
REPO_HTTPS="${REPO_HTTPS:-https://github.com/crypticsaiyan/trace-test.git}"
WORK_DIR="${WORK_DIR:-/tmp/trace-demo}"
BRANCH="demo-$(date +%H%M%S)"
TRACE_BIN="${TRACE_BIN:-uv run --project /home/cryptosaiyan/Documents/trace trace}"
DOCS_URL="https://docs.python.org/3/library/dataclasses.html"

bold()  { printf "\033[1m%s\033[0m\n" "$*"; }
green() { printf "\033[32m%s\033[0m\n" "$*"; }
cyan()  { printf "\033[36m%s\033[0m\n" "$*"; }
yellow(){ printf "\033[33m%s\033[0m\n" "$*"; }
red()   { printf "\033[31m%s\033[0m\n" "$*"; }

beat() {
  local n="$1" title="$2"
  echo
  cyan "──────────────────────────────────────────────"
  bold "BEAT $n — $title"
  cyan "──────────────────────────────────────────────"
}

wait_enter() {
  yellow "$*"
  read -r -p "  [press ENTER when done] " _
}

speak() {
  green "🎙  SAY OUT LOUD:"
  echo "    \"$*\""
}

# ────────────────────────────────────────────────────────────
# Setup
# ────────────────────────────────────────────────────────────
bold "trace demo pacer — 10 min walkthrough"
echo
echo "Repo:    $REPO_URL"
echo "Work:    $WORK_DIR"
echo "Branch:  $BRANCH"
echo "trace:   $TRACE_BIN"
echo
wait_enter "Mic + speakers ready? Headphones in (avoid feedback)?"

rm -rf "$WORK_DIR"
mkdir -p "$WORK_DIR"
cd "$WORK_DIR"
green "cloning…"
if ! git clone "$REPO_URL" repo 2>/dev/null; then
  yellow "ssh clone failed; trying https"
  git clone "$REPO_HTTPS" repo
fi
cd repo
git checkout -b "$BRANCH"

# ────────────────────────────────────────────────────────────
# Start capture
# ────────────────────────────────────────────────────────────
beat 0 "start capture"
echo "Run in another terminal (or this one if you prefer):"
bold "    $TRACE_BIN start"
echo
echo "Note the session id it prints. You'll need it at the end."
wait_enter "trace start running?"

# ────────────────────────────────────────────────────────────
# BEAT 1 (0:00–1:00) — initial scaffolding (progress)
# ────────────────────────────────────────────────────────────
beat 1 "scaffold greeter module (progress)"
speak "I'm building a small CLI greeter with config loading and validation."
echo
echo "Creating greeter.py with a basic Greeter class…"
cat > greeter.py <<'EOF'
"""Tiny CLI greeter — loads config, formats greetings."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class GreeterConfig:
    name: str
    style: str = "friendly"
    times: int = 1


def load_config(path: Path) -> GreeterConfig:
    data = json.loads(path.read_text(encoding="utf-8"))
    return GreeterConfig(**data)


def greet(cfg: GreeterConfig) -> str:
    prefix = {"friendly": "Hey", "formal": "Good day", "casual": "Yo"}[cfg.style]
    return "\n".join(f"{prefix}, {cfg.name}!" for _ in range(cfg.times))
EOF
git add greeter.py
wait_enter "greeter.py created. Save it in your editor if open."

# ────────────────────────────────────────────────────────────
# BEAT 2 (1:00–2:00) — research (browser)
# ────────────────────────────────────────────────────────────
beat 2 "open docs in browser (research)"
echo "Opening Python dataclasses docs in browser…"
xdg-open "$DOCS_URL" >/dev/null 2>&1 || yellow "xdg-open failed; open $DOCS_URL manually"
speak "Let me check the dataclasses docs to remember the field defaults syntax."
echo
yellow "Scroll the docs page for ~30 seconds. Read a heading or two aloud."
wait_enter "done reading docs?"

# ────────────────────────────────────────────────────────────
# BEAT 3 (2:00–3:30) — add config file + tests (progress)
# ────────────────────────────────────────────────────────────
beat 3 "add config + tests (progress, multi-file)"
speak "I'll add a sample config and a tiny test so I can run it end to end."
mkdir -p tests
cat > greeter_config.json <<'EOF'
{
  "name": "World",
  "style": "friendly",
  "times": 2
}
EOF
cat > tests/test_greeter.py <<'EOF'
from pathlib import Path

from greeter import GreeterConfig, greet, load_config


def test_greet_friendly():
    cfg = GreeterConfig(name="Alice", style="friendly", times=1)
    assert greet(cfg) == "Hey, Alice!"


def test_load_config(tmp_path: Path):
    p = tmp_path / "c.json"
    p.write_text('{"name": "Bob", "style": "formal", "times": 2}')
    cfg = load_config(p)
    assert cfg.style == "formal"
    assert cfg.times == 2
EOF
git add greeter_config.json tests/test_greeter.py
wait_enter "config + tests added."

# ────────────────────────────────────────────────────────────
# BEAT 4 (3:30–4:30) — RUN, hit bug (stuck → speech)
# ────────────────────────────────────────────────────────────
beat 4 "run tests, hit KeyError bug (stuck)"
speak "Let me run the tests."
echo
red "About to run pytest — this WILL fail. That's the bug arc for Replay the Bug."
echo
( cd "$WORK_DIR/repo" && python -m pytest tests/ -x 2>&1 | tail -20 ) || true
echo
speak "Hmm, KeyError on style. The config uses a value my dict doesn't know — wait, no, it's the default. Let me trace through."
echo
yellow "Stare at terminal output for ~20s. Say things like 'why is this failing'."
wait_enter "vented enough?"

# ────────────────────────────────────────────────────────────
# BEAT 5 (4:30–5:30) — speech-only debugging
# ────────────────────────────────────────────────────────────
beat 5 "talk through the bug (speech)"
speak "Okay so the prefix dict only handles three styles. If someone passes anything else it KeyErrors. I should handle unknown styles gracefully — fall back to friendly with a warning."
echo
wait_enter "spoke the diagnosis?"

# ────────────────────────────────────────────────────────────
# BEAT 6 (5:30–7:00) — fix the bug (progress)
# ────────────────────────────────────────────────────────────
beat 6 "apply fix (progress, the FIX in bug arc)"
speak "Applying the fix now — fallback to friendly for unknown styles."
cat > greeter.py <<'EOF'
"""Tiny CLI greeter — loads config, formats greetings."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

_PREFIXES = {"friendly": "Hey", "formal": "Good day", "casual": "Yo"}


@dataclass
class GreeterConfig:
    name: str
    style: str = "friendly"
    times: int = 1


def load_config(path: Path) -> GreeterConfig:
    data = json.loads(path.read_text(encoding="utf-8"))
    return GreeterConfig(**data)


def greet(cfg: GreeterConfig) -> str:
    prefix = _PREFIXES.get(cfg.style)
    if prefix is None:
        log.warning("unknown style %r; falling back to friendly", cfg.style)
        prefix = _PREFIXES["friendly"]
    return "\n".join(f"{prefix}, {cfg.name}!" for _ in range(cfg.times))
EOF
git add greeter.py
wait_enter "fix applied + saved."

# ────────────────────────────────────────────────────────────
# BEAT 7 (7:00–7:45) — rerun tests, green (progress)
# ────────────────────────────────────────────────────────────
beat 7 "re-run tests, green"
speak "Running tests again to confirm the fix."
( cd "$WORK_DIR/repo" && python -m pytest tests/ 2>&1 | tail -10 ) || true
speak "Green. Now I'll also add a test for the unknown-style path."
cat >> tests/test_greeter.py <<'EOF'


def test_unknown_style_falls_back():
    cfg = GreeterConfig(name="Eve", style="grumpy")
    assert greet(cfg) == "Hey, Eve!"
EOF
git add tests/test_greeter.py
( cd "$WORK_DIR/repo" && python -m pytest tests/ 2>&1 | tail -5 ) || true
wait_enter "regression test added + green?"

# ────────────────────────────────────────────────────────────
# BEAT 8 (7:45–8:30) — followup voice line (PR description fodder)
# ────────────────────────────────────────────────────────────
beat 8 "leave a TODO + voice follow-up"
speak "TODO: come back and add YAML config support later, and a colorized output mode would be nice as a follow-up."
echo
echo "Adding a TODO comment too…"
cat >> greeter.py <<'EOF'

# TODO: support YAML configs in addition to JSON (follow-up)
EOF
git add greeter.py
wait_enter "todo line added."

# ────────────────────────────────────────────────────────────
# BEAT 9 (8:30–9:30) — commit + push
# ────────────────────────────────────────────────────────────
beat 9 "commit + push branch"
git -c user.email=demo@trace.dev -c user.name="trace demo" commit -m "add greeter module with style fallback"
green "pushing branch $BRANCH…"
git push -u origin "$BRANCH"
wait_enter "branch pushed?"

# ────────────────────────────────────────────────────────────
# BEAT 10 (9:30–10:00) — open PR
# ────────────────────────────────────────────────────────────
beat 10 "open PR"
PR_URL=""
if command -v gh >/dev/null 2>&1; then
  green "creating PR via gh…"
  PR_URL=$(gh pr create --title "Add greeter module with style fallback" \
    --body "Demo PR. Adds greeter.py + tests. Fixes KeyError on unknown styles by falling back to friendly. TODO: YAML configs." \
    --head "$BRANCH" --base main 2>&1 | grep -oE 'https://github.com/[^ ]+/pull/[0-9]+' | head -1) || true
fi
if [[ -z "$PR_URL" ]]; then
  yellow "gh failed or not installed. Open this URL in browser to create PR:"
  bold "  https://github.com/crypticsaiyan/trace-test/compare/main...$BRANCH"
  read -r -p "  paste the PR URL once created: " PR_URL
fi
green "PR: $PR_URL"
echo "$PR_URL" > "$WORK_DIR/pr_url.txt"

# ────────────────────────────────────────────────────────────
# Stop capture
# ────────────────────────────────────────────────────────────
beat 11 "stop capture + generate"
echo "In the trace start terminal, hit Ctrl+C OR run in a NEW terminal:"
bold "    $TRACE_BIN stop"
echo
echo "Wait until indexing completes (status=indexed). Then:"
read -r -p "  paste the session id: " SESSION_ID

echo
green "Running: trace generate $SESSION_ID $PR_URL"
$TRACE_BIN generate "$SESSION_ID" "$PR_URL"

echo
bold "Done. Check the PR: $PR_URL"
echo "Expected on the PR:"
echo "  • appended description with thumbnail + What/Why/Struggles/Follow-ups"
echo "  • contribution map comment"
echo "  • focus mode comment"
echo "  • bug replay comment (if arc detected)"
echo
echo "For Q&A: comment '@trace why did you fall back to friendly?' on the PR,"
echo "then in another terminal:"
bold "  $TRACE_BIN qa-poll $PR_URL $SESSION_ID"
