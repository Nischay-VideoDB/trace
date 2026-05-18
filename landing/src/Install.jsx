function QuickstartTerminal() {
  const steps = [
    {
      head: "01 · clone + start",
      lines: [
        { p: "$", c: "git clone https://github.com/crypticsaiyan/trace && cd trace" },
        { o: "Cloning into 'trace'... done." },
        { p: "$", c: "uv sync" },
        { o: "Resolved 24 packages in 1.2s · installed in 0.8s" },
        { p: "$", c: "cp .env.example .env  # add your VIDEODB_API_KEY + GITHUB_TOKEN" },
        { p: "$", c: "uv run trace start --project ~/code/my-repo --live" },
        { o: "session_id: 7a2f-e831" },
        { o: "session_dir: ~/.trace/sessions/7a2f-e831/" },
        { o: "live indexer: chunk every 15s → VideoDB" },
        { o: "watchers: inotify saves + hyprctl window poll" },
        { ok: "recording. talk out loud while you code." },
      ],
    },
    {
      head: "02 · stop + index",
      lines: [
        { p: "$", c: "uv run trace stop" },
        { o: "stop signal sent to session 7a2f-e831" },
        { o: "muxing audio · 03:12.4" },
        { o: "Collection.upload(session.mp4) → vid_9kXp..." },
        { o: "index_spoken_words(sentence) · 412 segments" },
        { o: "index_scenes(time_based, prompt=...) · 78 scenes" },
        { o: "timeline: stuck=4 progress=12 speech=7 research=3" },
        { ok: "indexed. run: trace generate 7a2f-e831 <pr_url>" },
      ],
    },
    {
      head: "03 · generate PR video",
      lines: [
        { p: "$", c: "uv run trace generate 7a2f-e831 https://github.com/you/repo/pull/12" },
        { o: "fetching PR diff · 6 files +312 −47" },
        { o: "selector: 9 clips matching auth.py, jwt.py, tests/" },
        { o: "generate_image(FLUX): intro title card 16:9" },
        { o: "generate_text(pro): scene-grounded narration × 9" },
        { o: "generate_voice(OmniVoice): ref + 9 cloned clips parallel" },
        { o: "generate_music: ambient background 120s" },
        { o: "editor.Timeline: intro · video · narration · badges · music" },
        { ok: "PR #12 commented · description appended · contrib map posted" },
      ],
    },
    {
      head: "04 · auto-ship (no PR yet)",
      lines: [
        { p: "$", c: "uv run trace generate 7a2f-e831" },
        { o: "auto-committing 4 changed files..." },
        { o: "pushing branch trace/session-7a2f-e831" },
        { o: "opening PR: feat(auth): jwt validation + scene narration" },
        { o: "running full generate pipeline..." },
        { ok: "PR #13 · video posted · description appended" },
      ],
    },
    {
      head: "05 · reviewer Q&A bot",
      lines: [
        { p: "$", c: "uv run trace qa-poll https://github.com/you/repo/pull/12 7a2f-e831" },
        { o: "polling every 30s for /trace mentions..." },
        { o: "comment #4824: /trace why did you drop pyjwt?" },
        { o: "Video.search(spoken_word, semantic) → 2 hits" },
        { o: "Video.search(scene, semantic) → 1 hit" },
        { o: "generating 2 bounded clip URLs..." },
        { ok: "replied with 2 clips + paraphrase" },
      ],
    },
  ];

  const [idx, setIdx] = React.useState(0);
  const [line, setLine] = React.useState(0);
  const [char, setChar] = React.useState(0);

  React.useEffect(() => {
    const s = steps[idx];
    if (line >= s.lines.length) {
      const t = setTimeout(() => {
        setIdx((idx + 1) % steps.length);
        setLine(0);
        setChar(0);
      }, 2200);
      return () => clearTimeout(t);
    }
    const cur = s.lines[line];
    const txt = cur.c || cur.o || cur.ok || "";
    if (char < txt.length) {
      const speed = cur.c ? 22 : 6;
      const t = setTimeout(() => setChar(char + 1), speed);
      return () => clearTimeout(t);
    }
    const t = setTimeout(() => { setLine(line + 1); setChar(0); }, cur.c ? 180 : 60);
    return () => clearTimeout(t);
  }, [idx, line, char]);

  const s = steps[idx];
  return (
    <div className="term" style={{ marginTop: 32 }}>
      <div className="term-head">
        <div className="term-dots"><i /><i /><i /></div>
        <span>~/your-repo · {s.head}</span>
        <div style={{ display: "flex", gap: 8 }}>
          {steps.map((st, i) => (
            <span
              key={i}
              onClick={() => { setIdx(i); setLine(0); setChar(0); }}
              style={{
                width: 6, height: 6, borderRadius: "50%", cursor: "pointer",
                background: i === idx ? "var(--accent)" : "var(--line-strong)",
                display: "inline-block",
              }}
            />
          ))}
        </div>
      </div>
      <div className="term-body" style={{ minHeight: 200 }}>
        {s.lines.slice(0, line).map((l, i) => (
          <div key={i} className="line">
            {l.c && <><span className="prompt">$</span> <span className="cmd">{l.c}</span></>}
            {l.o && <span className="dim">{l.o}</span>}
            {l.ok && <span className="green">✓ {l.ok}</span>}
          </div>
        ))}
        {line < s.lines.length && (
          <div className="line">
            {s.lines[line].c && <><span className="prompt">$</span> <span className="cmd">{s.lines[line].c.slice(0, char)}</span></>}
            {s.lines[line].o && <span className="dim">{s.lines[line].o.slice(0, char)}</span>}
            {s.lines[line].ok && <span className="green">✓ {s.lines[line].ok.slice(0, char)}</span>}
            <span className="caret" />
          </div>
        )}
      </div>
    </div>
  );
}

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
      h: "System deps",
      code: "# Arch Linux + Hyprland\nsudo pacman -S --needed \\\n  ffmpeg wf-recorder inotify-tools\n\n# macOS (uses VideoDB Capture SDK)\nuv sync --extra macos\n\n# Windows (uses VideoDB Capture SDK)\nuv sync --extra windows",
      note: "Linux: wf-recorder is Wayland-only. macOS + Windows: the official VideoDB Capture SDK handles screen + mic natively.",
    },
  ];

  return (
    <section id="install" className="section">
      <div className="wrap">
        <div className="section-head">
          <div>
            <span className="section-tag">Install</span>
            <h2 className="section-title">Record. Stop. Ship.</h2>
          </div>
          <p className="section-sub">
            Arch + Hyprland is the verified path. macOS and Windows are also supported via the official VideoDB Capture SDK.
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

        <QuickstartTerminal />
      </div>
    </section>
  );
}
function Features() {
  const feats = [
    { n: "01", name: "Session capture", desc: "Screen + mic streamed to VideoDB as 15s chunks during the session, or muxed and uploaded on stop.", chip: "VideoDB · Collection.upload" },
    { n: "02", name: "Timeline builder", desc: "Four classifiers tag every second of the session: stuck, research, progress, speech.", chip: "trace_cli/timeline" },
    { n: "03", name: "PR video", desc: "FLUX intro card, voice-cloned narration per clip (OmniVoice), ambient music, fade transitions. Assembled on editor.Timeline with 4 tracks. Posted as HLS to the PR.", chip: "editor.Timeline · generate_stream" },
    { n: "04", name: "Reviewer Q&A", desc: "/trace in a PR comment triggers semantic search across spoken_word + scene indexes. Replies with an LLM-synthesized answer and up to 3 bounded clip URLs.", chip: "Video.search (semantic)" },
    { n: "05", name: "Human vs Agent map", desc: "Classifies each PR diff file as human, agent, mixed, or unknown using session evidence: screen activity (ai_assistant scenes), voice transcript (AI invocation keywords), and file save timing.", chip: "trace_cli/contribution_map" },
    { n: "06", name: "Focus Mode", desc: "Compress a 20-file PR into a ranked list of files that drove the actual decisions, with rationale.", chip: "trace_cli/focus_mode" },
    { n: "07", name: "PR Description", desc: "Auto-generated What / Why / Struggles / Follow-ups / Test plan. Fetches the repo's own PR template and fills it in if one exists. Grounded in session, not the diff.", chip: "trace_cli/pr_description" },
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
              Built for the VideoDB Hackathon.<br></br>MIT licensed.
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
          </div>
          <div className="footer-col">
            <div className="footer-h">Stack</div>
            <a href="https://videodb.io" target="_blank" rel="noreferrer">VideoDB ↗</a>
            <a href="https://github.com/crypticsaiyan/trace" target="_blank" rel="noreferrer">GitHub ↗</a>
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
window.Features = Features;
window.Footer = Footer;
