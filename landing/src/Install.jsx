function Install() {
  const steps = [
    {
      n: "01",
      h: "Clone + sync",
      code: "git clone https://github.com/crypticsaiyan/trace\ncd trace\nuv sync",
      note: "Python 3.12. uv manages the virtualenv and installs all dependencies.",
    },
    {
      n: "02",
      h: "Set keys",
      code: "# .env at repo root\nVIDEODB_API_KEY=...\nGITHUB_TOKEN=...",
      note: "VIDEODB_API_KEY: claim $1,000 sandbox credit at hackday.videodb.io/sandbox.html. GITHUB_TOKEN: needs repo + pull_request scopes.",
    },
    {
      n: "03",
      h: "System deps (Arch + Hyprland verified)",
      code: "sudo pacman -S --needed \\\n  ffmpeg wf-recorder inotify-tools",
      note: "wf-recorder is Wayland-only. X11 hosts can swap in ffmpeg -f x11grab. Mic capture uses PulseAudio or pipewire-pulse compat shim.",
    },
  ];

  const quick = [
    "mkdir -p /tmp/demo && cd /tmp/demo",
    "git init && echo 'def hello(): pass' > greet.py",
    "",
    "# terminal 1 — start recording",
    "uv run trace start --project /tmp/demo --live",
    "",
    "# code in another window, talk out loud while editing, save with :w",
    "",
    "# terminal 2 — stop + index",
    "uv run trace stop",
    "",
    "# generate narrated PR video (push + open PR first)",
    "uv run trace generate <session_id> https://github.com/you/repo/pull/N",
    "",
    "# OR: auto-commit + push + open PR + generate in one shot",
    "uv run trace ship <session_id>",
    "",
    "# run the @trace reviewer bot (long-running)",
    "uv run trace qa-poll https://github.com/you/repo/pull/N <session_id>",
  ].join("\n");

  return (
    <section id="install" className="section">
      <div className="wrap">
        <div className="section-head">
          <div>
            <span className="section-tag">Install</span>
            <h2 className="section-title">Sixty seconds to a narrated PR.</h2>
          </div>
          <p className="section-sub">
            Arch + Hyprland is the verified path. Linux Wayland in general should work — the Capture SDK doesn't ship a Linux wheel, so trace uses chunked uploads under the hood instead.
          </p>
        </div>

        <div className="install-steps">
          {steps.map((s) => (
            <div key={s.n} className="card install-step card-bracket">
              <div className="install-num">{s.n}</div>
              <div className="install-h">{s.h}</div>
              <pre className="install-code">{s.code}</pre>
              <div className="install-note">{s.note}</div>
            </div>
          ))}
        </div>

        <div style={{ marginTop: 32 }} className="card pr-side-card crosshair">
          <div className="pr-side-h">▸ Quickstart</div>
          <pre className="pr-diff" style={{ whiteSpace: "pre" }}>{quick}</pre>
        </div>
      </div>
    </section>
  );
}

function APIMap() {
  const rows = [
    ["videodb.connect", "videodb/client.py", "Auth"],
    ["Collection.upload", "indexing/pipeline.py + capture/live_indexer.py", "Session video + 15s live chunks"],
    ["Collection.connect_rtstream", "videodb/client.py (helper)", "Live ingest path"],
    ["Collection.generate_text", "pr_video/narration.py · pr_description/generator.py", "Narration + PR Why section"],
    ["Collection.generate_voice", "pr_video/render.py", "Per-clip TTS narration"],
    ["Video.index_spoken_words", "indexing/pipeline.py", "Transcript (sentence segmentation)"],
    ["Video.index_scenes", "indexing/pipeline.py", "Visual classification (custom prompt)"],
    ["Video.get_scene_index", "videodb/client.py", "Scene grounding for narration"],
    ["Video.search (spoken_word)", "web/qa.py", "Reviewer Q&A search"],
    ["Video.search (scene)", "web/qa.py", "Visual semantic search"],
    ["Video.generate_stream", "web/qa.py", "Bounded HLS clip URLs"],
    ["editor.Timeline + Track + Clip", "pr_video/render.py", "PR video assembly"],
    ["editor.VideoAsset", "pr_video/render.py", "Source clips, muted, track z=0"],
    ["editor.AudioAsset", "pr_video/render.py", "Narration, track z=1"],
    ["editor.TextAsset", "pr_video/render.py", "Category + filename badges, track z=2"],
  ];

  return (
    <section id="api" className="section">
      <div className="wrap">
        <div className="section-head">
          <div>
            <span className="section-tag">VideoDB usage map</span>
            <h2 className="api-map-title">15 calls. 8 files. One vendor.</h2>
          </div>
          <p className="section-sub">
            Every VideoDB API surface used, and where. Hackathon scorer weights 30% on depth of VideoDB usage — this is the receipt.
          </p>
        </div>

        <div className="card api-map crosshair">
          <table className="api-table">
            <thead>
              <tr><th>API</th><th>File</th><th>Purpose</th></tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  <td className="api">{r[0]}</td>
                  <td className="file">trace_cli/{r[1]}</td>
                  <td className="purpose">{r[2]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

function Features() {
  const feats = [
    { n: "01", name: "Session capture", desc: "Screen + mic streamed to VideoDB as 15s chunks during the session, or muxed and uploaded on stop.", chip: "VideoDB · Collection.upload" },
    { n: "02", name: "Timeline builder", desc: "Four classifiers tag every second of the session: stuck, research, progress, speech.", chip: "trace_cli/timeline" },
    { n: "03", name: "PR video", desc: "Narrated walkthrough assembled on editor.Timeline with three tracks. Posted as HLS to the PR.", chip: "editor.Timeline · generate_stream" },
    { n: "04", name: "Reviewer Q&A", desc: "@trace in a PR comment → semantic search across spoken_word + scene indexes, up to 3 clip URLs.", chip: "Video.search (semantic)" },
    { n: "05", name: "Human vs Agent map", desc: "Scan Claude Code session logs in the capture window. Classify diff lines as human, agent, mixed, or unknown.", chip: "trace_cli/contribution_map" },
    { n: "06", name: "Focus Mode", desc: "Compress a 20-file PR into a ranked list of files that drove the actual decisions, with rationale.", chip: "trace_cli/focus_mode" },
    { n: "07", name: "PR Description", desc: "Auto-appended What / Why / Struggles / Follow-ups, grounded in the session not the diff.", chip: "trace_cli/pr_description" },
  ];
  return (
    <section id="features" className="section">
      <div className="wrap">
        <div className="section-head">
          <div>
            <span className="section-tag">Features</span>
            <h2 className="section-title">Seven surfaces. All grounded.</h2>
          </div>
          <p className="section-sub">
            Every feature reads from the same indexed session. Narration cannot invent details the eyes-and-ears layer didn't see.
          </p>
        </div>
        <div className="feat-grid">
          {feats.map((f) => (
            <div key={f.n} className="card feat-card card-bracket">
              <div className="feat-num">{f.n}</div>
              <div className="feat-name">{f.name}</div>
              <div className="feat-desc">{f.desc}</div>
              <div className="feat-chip"><span className="chip acc">{f.chip}</span></div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function Footer() {
  const ascii =
" _                       \n" +
"| |_ _ __ __ _  ___ ___ \n" +
"| __| '__/ _` |/ __/ _ \\\n" +
"| |_| | | (_| | (_|  __/\n" +
" \\__|_|  \\__,_|\\___\\___|";

  return (
    <footer className="footer">
      <div className="wrap">
        <div className="footer-cols">
          <div className="footer-col">
            <pre className="footer-brand-ascii">{ascii}</pre>
            <div className="dim" style={{ fontSize: 12, lineHeight: 1.65 }}>
              Built for the VideoDB "Give Agents Eyes and Ears" hackathon, May 16–18 2026. MIT licensed.
            </div>
          </div>
          <div className="footer-col">
            <div className="footer-h">Product</div>
            <a href="#commands">CLI</a>
            <a href="#walkthrough">PR walkthrough</a>
            <a href="#features">Features</a>
            <a href="#install">Install</a>
          </div>
          <div className="footer-col">
            <div className="footer-h">Surfaces</div>
            <a href="/docs">Docs</a>
            <a href="#api">VideoDB map</a>
          </div>
          <div className="footer-col">
            <div className="footer-h">Stack</div>
            <a href="https://videodb.io" target="_blank" rel="noreferrer">VideoDB ↗</a>
            <a href="https://github.com" target="_blank" rel="noreferrer">GitHub ↗</a>
            <a href="https://hackday.videodb.io/sandbox.html" target="_blank" rel="noreferrer">Sandbox ↗</a>
          </div>
        </div>
        <hr className="rule" />
        <div className="footer-bottom" style={{ paddingTop: 20 }}>
          <span>trace · v0.1 · {new Date().getFullYear()}</span>
          <span>made by crypticsaiyan</span>
        </div>
      </div>
    </footer>
  );
}

window.Install = Install;
window.APIMap = APIMap;
window.Features = Features;
window.Footer = Footer;
