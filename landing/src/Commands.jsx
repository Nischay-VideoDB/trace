function Commands() {
  const cmds = [
    {
      name: "trace start",
      sig: "trace start --project <path> [--live]",
      desc: "Begin a capture session. wf-recorder grabs the screen, ffmpeg+pulse grabs the mic. With --live, a 15s chunk uploader streams each segment to VideoDB as you type.",
      term: [
        { p: "$", c: "uv run trace start --project ~/code/repo --live" },
        { o: "session 7a2f-… created in ~/.trace/sessions/" },
        { o: "capture started · 1080p screen + 48k audio" },
        { o: "live indexer thread: chunk every 15s" },
        { o: "watchers: inotify saves + hyprctl window poll" },
        { ok: "recording" },
      ],
      bullets: [
        "Active-session lock prevents two captures at once",
        "Heartbeat written every 5s for crash recovery",
        "Live mode lights up index_scenes + index_spoken_words per chunk",
      ],
    },
    {
      name: "trace stop",
      sig: "trace stop",
      desc: "Finalize capture, mux audio into mp4, upload to VideoDB, run index_spoken_words(sentence) + index_scenes(time_based) with a custom classifier prompt, build the tagged timeline.",
      term: [
        { p: "$", c: "uv run trace stop" },
        { o: "muxing audio · 02:47.3" },
        { o: "Collection.upload(session.mp4) → vid_… " },
        { o: "index_spoken_words: 412 segments · 18.4 wpm avg" },
        { o: "index_scenes(prompt=classifier.txt): 78 scenes" },
        { o: "timeline: stuck=4 progress=12 speech=7 research=3" },
        { ok: "ready: trace generate 7a2f <pr_url>" },
      ],
      bullets: [
        "Timeline merges boundaries from 4 classifiers (stuck/progress/speech/research)",
        "Transcript fetched and persisted to ~/.trace/sessions/<id>/",
        "Falls back to chunk-based upload on Linux (no CaptureSession wheel)",
      ],
    },
    {
      name: "trace generate",
      sig: "trace generate <session_id> <pr_url>",
      desc: "Select clips per diff file, prompt Collection.generate_text for narration grounded in the scene index + transcript, synthesize each narration with generate_voice, assemble on videodb.editor.Timeline with three tracks (video, audio, text badges), post HLS to the PR.",
      term: [
        { p: "$", c: "uv run trace generate 7a2f https://github.com/you/repo/pull/12" },
        { o: "selector: 9 clips matching auth.py, jwt.py, tests/" },
        { o: "generate_text(model=pro): scene-grounded narration × 9" },
        { o: "generate_voice: parallel TTS · ~600ms p50" },
        { o: "editor.Timeline · VideoAsset · AudioAsset · TextAsset" },
        { o: "Timeline.generate_stream() → https://stream…/master.m3u8" },
        { ok: "PR commented · description appended · contrib map posted" },
      ],
      bullets: [
        "Anti-hallucination prompt: narration must reference scene labels + transcript only",
        "TextAsset badges show category + filename top-left of each clip",
        "Posts What / Why / Struggles / Follow-ups PR description",
      ],
    },
    {
      name: "trace replay",
      sig: "trace replay <session_id> <file> <start> <end>",
      desc: "One-shot CLI for Decision Replay. Given a file and line range, returns bounded HLS clips of every moment that edited those lines.",
      term: [
        { p: "$", c: "uv run trace replay 7a2f auth.py 40 88" },
        { o: "matching edits: 3 windows" },
        { o: "[14:02-14:35]  stuck: re-reading jwt spec" },
        { o: "[18:11-18:44]  progress: switched to PyJWT" },
        { o: "[26:07-26:52]  speech: \"why we kept the leeway\"" },
      ],
      bullets: [
        "Backed by Video.search(IndexType.spoken_word + scene)",
        "Returns Video.generate_stream(timeline=[(s,e)]) intervals",
        "Same engine as the web /replay UI",
      ],
    },
    {
      name: "trace serve",
      sig: "trace serve [--host 127.0.0.1] [--port 8000]",
      desc: "Run the FastAPI Decision Replay UI. Pick a session + file + line range and get bounded HLS clips for every edit moment.",
      term: [
        { p: "$", c: "uv run trace serve" },
        { o: "uvicorn running on http://127.0.0.1:8000" },
        { o: "GET /         → landing" },
        { o: "GET /replay   → Decision Replay UI" },
        { o: "GET /docs     → docs page" },
      ],
      bullets: [
        "Single FastAPI app, served from trace_cli/web/app.py",
        "/api/sessions and /api/replay JSON endpoints for tooling",
      ],
    },
    {
      name: "trace qa-poll",
      sig: "trace qa-poll <pr_url> <session_id>",
      desc: "Long-running poller for @trace mentions in PR review comments. Runs semantic search across spoken_word + scene indexes and replies with up to 3 bounded clip URLs.",
      term: [
        { p: "$", c: "uv run trace qa-poll https://github.com/you/repo/pull/12 7a2f" },
        { o: "polling every 30s..." },
        { o: "comment #4824: @trace why did you drop pyjwt?" },
        { o: "Video.search(spoken_word, semantic) → 3 hits" },
        { o: "Video.generate_stream(timeline=[(1085,1112),...])" },
        { ok: "replied with 3 clip URLs + paraphrase" },
      ],
      bullets: [
        "Up to 3 clips per question, deduped against prior replies",
        "Paraphrase comes from generate_text grounded in retrieved transcripts",
      ],
    },
    {
      name: "trace focus",
      sig: "trace focus <session_id> <pr_url>",
      desc: "Reviewer Focus Mode: compress the PR into a ranked list of files that drove the actual decisions in the session, with one-line rationale per file.",
      term: [
        { p: "$", c: "uv run trace focus 7a2f https://github.com/you/repo/pull/12" },
        { o: "diff: 14 files · 612 ± lines" },
        { o: "scored against timeline · stuck/research weighted ×3" },
        { o: "auth.py        ·  primary decision surface" },
        { o: "jwt.py         ·  library swap (pyjwt → authlib)" },
        { o: "tests/test_au… ·  regression net" },
        { ok: "review the rest at your own risk." },
      ],
      bullets: [
        "Ranking lives in trace_cli/focus_mode/builder.py",
        "Designed to make 20-file PRs reviewable in 5 minutes",
      ],
    },
  ];

  const [i, setI] = React.useState(0);
  const c = cmds[i];

  return (
    <section id="commands" className="section">
      <div className="wrap">
        <div className="section-head">
          <div>
            <span className="section-tag">The CLI</span>
            <h2 className="section-title">Seven verbs. One pipeline.</h2>
          </div>
          <p className="section-sub">
            Every command runs against the same session store and the same VideoDB collection. Start records, stop indexes, generate decorates the PR, the rest are surfaces over the index.
          </p>
        </div>

        <div className="cmd-tabs">
          {cmds.map((x, j) => (
            <button key={x.name} className={"cmd-tab " + (i === j ? "on" : "")} onClick={() => setI(j)}>
              {x.name}
            </button>
          ))}
        </div>

        <div className="cmd-grid">
          <div className="card cmd-panel card-bracket">
            <div className="cmd-name">{c.name}</div>
            <div className="cmd-note-k">Signature</div>
            <div className="cmd-note-v">{c.sig}</div>
            <p className="cmd-desc">{c.desc}</p>
            <div className="cmd-note-k">What it does</div>
            <ul className="cmd-bullets">
              {c.bullets.map((b, k) => <li key={k}>{b}</li>)}
            </ul>
          </div>
          <div className="term">
            <div className="term-head">
              <div className="term-dots"><i /><i /><i /></div>
              <span>{c.name}</span>
              <span className="mono">demo</span>
            </div>
            <div className="term-body">
              {c.term.map((l, k) => (
                <div key={k} className="line">
                  {l.c && <><span className="prompt">$</span> <span className="cmd">{l.c}</span></>}
                  {l.o && <span className="dim">{l.o}</span>}
                  {l.ok && <span className="green">✓ {l.ok}</span>}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
window.Commands = Commands;
