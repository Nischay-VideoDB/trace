# trace demo cheat-sheet (~10 min)

Read on phone. Don't open on box. Recording shows only editor + terminal + browser.

**Contribution map needs Claude Code edits** — beats 3, 6, 8 use `claude` CLI so logs land in `~/.claude/projects/`. Beats 1, 5, 7 you type yourself. Result: map shows human/agent/mixed split per file.

---

## Pre-flight (NOT recorded)

```bash
# clean workspace
rm -rf /tmp/trace-demo && mkdir -p /tmp/trace-demo && cd /tmp/trace-demo
git clone https://github.com/crypticsaiyan/trace-test.git repo
cd repo
git checkout -b demo-$(date +%H%M%S)
```

- Headphones in.
- One terminal + editor + Firefox visible.
- Verify `claude` CLI on PATH: `which claude`
- Test mic: `arecord -d 2 t.wav && aplay t.wav && rm t.wav`
- Hit screen recorder.

---

## Beat 0 — start (0:00 – 0:20)

Terminal:
```
cd /home/cryptosaiyan/Documents/trace
uv run trace start
```

Note session id.

🎙 "Starting trace. Building a CLI greeter — mix of human code, Claude Code edits, and docs lookup."

---

## Beat 1 — HUMAN: scaffold (0:20 – 1:30)

🎙 "I'll write the core class myself first."

Open `greeter.py` in editor. **Type yourself** (don't paste — show keystrokes):

```python
"""Tiny CLI greeter."""
from dataclasses import dataclass


@dataclass
class GreeterConfig:
    name: str
    style: str = "friendly"
    times: int = 1


def greet(cfg: GreeterConfig) -> str:
    prefix = {"friendly": "Hey", "formal": "Good day", "casual": "Yo"}[cfg.style]
    return "\n".join(f"{prefix}, {cfg.name}!" for _ in range(cfg.times))
```

Save.

---

## Beat 2 — RESEARCH: browser (1:30 – 2:10)

🎙 "Let me check dataclasses field defaults."

Firefox → `https://docs.python.org/3/library/dataclasses.html`. Scroll ~30s. Read aloud:

🎙 "Right, mutable defaults need `field(default_factory=...)`. Good."

---

## Beat 3 — CLAUDE CODE: add config loader (2:10 – 3:30)

🎙 "Now let me have Claude Code add the JSON config loader and a config file."

Terminal in `/tmp/trace-demo/repo`:
```
claude
```

In Claude Code prompt, type:
```
Add a load_config(path: Path) -> GreeterConfig function to greeter.py that reads JSON. Also create greeter_config.json with name=World, style=friendly, times=2. Don't change the existing greet() function.
```

Wait for Claude Code to apply edits. Approve writes.

🎙 "Claude's adding the loader and config file. It'll touch greeter.py and create a new JSON."

Exit Claude Code (Ctrl+D or `/exit`).

---

## Beat 4 — HUMAN: run + hit bug (3:30 – 4:30)

🎙 "Let me test with an unknown style."

Terminal:
```
python -c "from greeter import greet, GreeterConfig; print(greet(GreeterConfig(name='Eve', style='grumpy')))"
```

→ **KeyError: 'grumpy'**.

🎙 "KeyError. Dict lookup crashes on unknown styles. Bug."

Stare at output ~15s.

---

## Beat 5 — HUMAN: diagnose aloud + tests (4:30 – 5:30)

🎙 "I need a fallback. Default to friendly with a warning if the style is unknown."

Create `tests/test_greeter.py` **by typing yourself**:

```python
from greeter import GreeterConfig, greet


def test_greet_friendly():
    cfg = GreeterConfig(name="Alice", style="friendly", times=1)
    assert greet(cfg) == "Hey, Alice!"


def test_unknown_style_falls_back():
    cfg = GreeterConfig(name="Eve", style="grumpy")
    assert greet(cfg) == "Hey, Eve!"
```

Save. Run:
```
python -m pytest tests/ -x
```

→ test_unknown_style_falls_back FAILS. Confirms bug.

---

## Beat 6 — CLAUDE CODE: apply fix (5:30 – 6:45)

🎙 "Let me have Claude fix the greet function."

Terminal:
```
claude
```

Prompt:
```
In greeter.py, fix greet() so unknown styles fall back to "friendly" with a logging.warning. Don't change function signature. Keep it minimal.
```

Approve edits.

🎙 "Claude's pulling the dict to module level, using .get() with a fallback, adding a warning log."

Exit Claude Code.

Run tests:
```
python -m pytest tests/
```

→ all green.

🎙 "Green."

---

## Beat 7 — HUMAN: add TODO (6:45 – 7:15)

🎙 "Leaving a follow-up for later."

In editor, append to `greeter.py`:
```python

# TODO: support YAML configs in addition to JSON (follow-up)
```

🎙 "TODO — YAML config support, and colorized output mode would be nice later too."

Save.

---

## Beat 8 — CLAUDE CODE: add CLI entry (7:15 – 8:30)

🎙 "One last thing — Claude, add a CLI entry point."

Terminal:
```
claude
```

Prompt:
```
Add a __main__ block to greeter.py that loads greeter_config.json and prints greet(cfg). Use argparse with --config defaulting to greeter_config.json.
```

Approve.

Exit Claude Code. Test:
```
python greeter.py
```

→ prints `Hey, World!\nHey, World!`.

🎙 "Works."

---

## Beat 9 — stop capture (8:30 – 9:00)

🎙 "Stopping. trace handles the rest — commit, push, PR, walkthrough, all comments."

```
cd /home/cryptosaiyan/Documents/trace
uv run trace stop
```

Wait `status=indexed`. Copy session id.

Make sure you're on a feature branch (not main):
```
cd /tmp/trace-demo/repo && git status
```

---

## Beat 10 — ship it (9:00 – end)

One command. Auto-commits with AI-generated message, pushes branch, opens PR with AI title+body, runs full generate (walkthrough + map + focus + bug replay + description).

```
uv run trace ship <SESSION_ID>
```

Wait ~3-4 min. Watch logs:
- `auto-commit: <AI message>`
- `pushing <branch> -> origin`
- `creating PR: <AI title>`
- `running generate against <pr_url>`
- HLS URL printed at end

---

## Browser tour (money shot)

PR in browser. Show:
1. PR description — thumbnail at top, click → narrated walkthrough
2. What/Why/Struggles/Follow-ups sections
3. **Contribution map comment** — should show `greeter.py = mixed` (human + Claude), `tests/test_greeter.py = human`, `greeter_config.json = agent`
4. Focus mode comment
5. Bug replay comment — click → failure → fix arc

🎙 "Every comment generated by trace from the session. Map distinguishes my edits from Claude's."

---

## Q&A demo (optional)

PR comment:
```
@trace why did you fall back to friendly instead of raising?
```

Terminal:
```
uv run trace qa-poll <PR_URL> <SESSION_ID>
```

Wait ≤60s for bot reply.

---

## Why this mix matters

| Beat | Who | File touched | Map classification |
|---|---|---|---|
| 1 | human | greeter.py (initial) | mixed (Claude edits later) |
| 3 | claude | greeter.py + greeter_config.json | mixed / agent |
| 5 | human | tests/test_greeter.py | human |
| 6 | claude | greeter.py | mixed |
| 7 | human | greeter.py | mixed |
| 8 | claude | greeter.py | mixed |

Contribution map has real signal to show. If all human or all Claude, map looks broken.

---

## If something breaks

- `claude` not on PATH: `which claude` first. If missing, fall back to typing the changes yourself but flag that the map will only show human.
- `trace stop` hangs: Ctrl+C, files stay in `~/.trace/sessions/<id>/`.
- `generate` voice quota: auto-sandbox now, just works.
- PR comment missing: re-run `trace generate <id> <pr_url>` — idempotent.
