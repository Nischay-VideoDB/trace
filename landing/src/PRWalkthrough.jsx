// PRWalkthrough.jsx — mocked GitHub PR with scrubbable narrated walkthrough video
const PR_CLIPS = [
  {
    start: 0, end: 10,
    file: "capture/service.py",
    range: "L42–L68",
    tag: "EDIT",
    tagCls: "b",
    narration: "Wiring up wf-recorder and ffmpeg+pulse. Heartbeat every 5s so a crash mid-session doesn't lose the capture.",
    transcript: "starting screen capture, need to mux audio separately on wayland…",
    diff: [
      { sign: "+", text: "proc = Popen([\"wf-recorder\", \"-f\", str(out)])" },
      { sign: "+", text: "audio = Popen([\"ffmpeg\", \"-f\", \"pulse\", \"-i\", \"default\", ...])" },
      { sign: "+", text: "heartbeat.start(session_id, interval=5)" },
    ],
  },
  {
    start: 10, end: 20,
    file: "indexing/pipeline.py",
    range: "L55",
    tag: "STUCK",
    tagCls: "r",
    narration: "CaptureSession has no Linux wheel. 12 minutes on this before switching to chunked upload — same VideoDB surfaces, no RTSP tunnel.",
    transcript: "pip error, no wheel for linux… switching to collection.upload",
    diff: [
      { sign: "-", text: "from videodb.capture import CaptureSession" },
      { sign: "+", text: "# no Linux wheel — chunked upload instead" },
      { sign: "+", text: "video = collection.upload(file_path=str(mp4))" },
    ],
  },
  {
    start: 20, end: 31,
    file: "indexing/pipeline.py",
    range: "L91–L110",
    tag: "PROGRESS",
    tagCls: "g",
    narration: "Indexing with both spoken_words and scene classification. Custom classifier prompt tags moments as stuck, research, progress, or speech.",
    transcript: "index_scenes with a custom prompt so it knows what stuck looks like…",
    diff: [
      { sign: "+", text: "video.index_spoken_words(SegmentationType.sentence)" },
      { sign: "+", text: "video.index_scenes(SceneExtractionType.time_based," },
      { sign: "+", text: "    prompt=CLASSIFIER_PROMPT)" },
    ],
  },
  {
    start: 31, end: 40,
    file: "pr_video/narration.py",
    range: "L88–L110",
    tag: "EDIT",
    tagCls: "b",
    narration: "Passing scene index + transcript into the narration prompt. Without this the LLM was inventing function names that were never on screen.",
    transcript: "need to pass the scene context or it just makes stuff up…",
    diff: [
      { sign: "+", text: "scene_hint = f\"On screen: {scene_text}\" if scene_text else \"\"" },
      { sign: "+", text: "# only describe what the scene index + transcript show" },
    ],
  },
  {
    start: 40, end: 47,
    file: "pr_video/render.py",
    range: "L180–L210",
    tag: "PROGRESS",
    tagCls: "g",
    narration: "Three-track Timeline: video muted on z=0, narration audio on z=1, TextAsset badges on z=2. generate_stream() returns the HLS m3u8.",
    transcript: "three tracks, video muted, narration on top… generate_stream",
    diff: [
      { sign: "+", text: "video_track.add_clip(Clip(VideoAsset(id=video_id, volume=0), ...))" },
      { sign: "+", text: "narration_track.add_clip(Clip(AudioAsset(id=audio_id), ...))" },
      { sign: "+", text: "url = tl.generate_stream()  # → HLS m3u8" },
    ],
  },
];

const PR_DURATION = 47;

function fmtPRTime(s) {
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${String(sec).padStart(2, "0")}`;
}

function PRWalkthrough() {
  const [t, setT] = React.useState(0);
  const [playing, setPlaying] = React.useState(false);
  const lastRef = React.useRef(performance.now());
  const dragRef = React.useRef(false);
  const trackRef = React.useRef(null);

  // play loop
  React.useEffect(() => {
    let raf;
    function step(now) {
      const dt = (now - lastRef.current) / 1000;
      lastRef.current = now;
      if (playing) {
        setT((prev) => {
          const next = prev + dt;
          if (next >= PR_DURATION) return 0;
          return next;
        });
      }
      raf = requestAnimationFrame(step);
    }
    lastRef.current = performance.now();
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [playing]);

  function scrubTo(clientX) {
    if (!trackRef.current) return;
    const r = trackRef.current.getBoundingClientRect();
    const pct = Math.max(0, Math.min(1, (clientX - r.left) / r.width));
    setT(pct * PR_DURATION);
  }
  function onDown(e) {
    dragRef.current = true;
    scrubTo(e.clientX);
    setPlaying(false);
  }
  React.useEffect(() => {
    function move(e) { if (dragRef.current) scrubTo(e.clientX); }
    function up() { dragRef.current = false; }
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
    return () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    };
  }, []);

  const clip = PR_CLIPS.find((c) => t >= c.start && t < c.end) || PR_CLIPS[PR_CLIPS.length - 1];
  const pct = (t / PR_DURATION) * 100;

  return (
    <section className="section pr" id="walkthrough">
      <div className="wrap">
        <div className="section-head">
          <div>
            <span className="section-tag">Output</span>
            <h2 className="section-title">Your PR,<br/>narrated.</h2>
          </div>
          <p className="section-sub">
            After <span className="acc">trace generate</span>, reviewers see this. Scrub the timeline — narration, diff, and badges swap per clip. Every word is grounded in the scene index + transcript. No hallucination.
          </p>
        </div>

        {/* Mock GitHub PR */}
        <div className="pr-shell crosshair">
          <span className="ch-tr"></span><span className="ch-bl"></span>
          <div className="pr-shell-head">
            <div className="pr-shell-l">
              <span className="pr-repo">you / your-repo</span>
              <span className="mute">·</span>
              <span className="pr-num">PR #38</span>
              <span className="pr-state">OPEN</span>
            </div>
            <div className="pr-shell-r mute">
              6 files · +312 −47 · session 7a2f
            </div>
          </div>
          <div className="pr-title">
            <span className="mono">feat(capture):</span> chunked upload + scene-grounded narration
          </div>

          <div className="pr-body">
            {/* @trace comment with embedded video */}
            <div className="pr-comment">
              <div className="pr-comment-head">
                <div className="pr-avatar">@</div>
                <div>
                  <div className="pr-comment-name">
                    trace-bot <span className="mute">commented · auto-generated walkthrough</span>
                  </div>
                  <div className="mute" style={{ fontSize: 11 }}>posted 3 minutes ago · session b7f3e2</div>
                </div>
                <span className="pill" style={{ marginLeft: "auto" }}><span className="dot"></span>HLS · m3u8</span>
              </div>

              {/* "Video" player */}
              <div className="pr-video">
                <div className="pr-video-stage">
                  {/* Scene placeholder (simulated screen content) */}
                  <div className="pr-scene">
                    <div className="pr-scene-grid"></div>
                    <div className="pr-scene-editor">
                      <div className="pr-scene-tab">
                        <span className="dim">●</span>
                        <span>{clip.file.split("/").pop()}</span>
                      </div>
                      <div className="pr-scene-code">
                        {clip.diff.map((d, i) => (
                          <div key={i} className={"pr-line " + (d.sign === "+" ? "plus" : d.sign === "-" ? "minus" : "")}>
                            <span className="pr-ln mute">{String(80 + i).padStart(3, " ")}</span>
                            <span className="pr-sign">{d.sign}</span>
                            <span className="pr-code">{d.text}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                    {/* Narration badge (TextAsset on track z=2) */}
                    <div className="pr-badge">
                      <span className={"chip " + clip.tagCls}>{clip.tag}</span>
                      <span className="pr-badge-file">{clip.file}</span>
                      <span className="mute">·</span>
                      <span className="mute">{clip.range}</span>
                    </div>
                    {/* Waveform of narration */}
                    <div className="pr-wave">
                      {Array.from({ length: 56 }).map((_, i) => {
                        const phase = (t * 4 + i * 0.2);
                        const h = 30 + Math.abs(Math.sin(phase) * 60) + (i % 3) * 8;
                        return <span key={i} style={{ height: `${Math.min(96, h)}%` }} />;
                      })}
                    </div>
                  </div>

                  {/* Caption / narration text */}
                  <div className="pr-caption">
                    <div className="mute" style={{ fontSize: 10.5, letterSpacing: "0.18em" }}>NARRATION · generate_voice</div>
                    <div className="pr-caption-text">{clip.narration}</div>
                    <div className="pr-caption-tx mute">
                      transcript: <span style={{ color: "var(--fg-dim)" }}>&ldquo;{clip.transcript}&rdquo;</span>
                    </div>
                  </div>
                </div>

                {/* Controls */}
                <div className="pr-controls">
                  <button
                    className="pr-play"
                    onClick={() => setPlaying((p) => !p)}
                    aria-label={playing ? "pause" : "play"}
                  >
                    {playing ? "❙❙" : "▶"}
                  </button>
                  <span className="pr-time mono">{fmtPRTime(t)} / {fmtPRTime(PR_DURATION)}</span>

                  <div className="pr-track-wrap" ref={trackRef} onMouseDown={onDown}>
                    <div className="pr-track">
                      {PR_CLIPS.map((c, i) => {
                        const w = ((c.end - c.start) / PR_DURATION) * 100;
                        const left = (c.start / PR_DURATION) * 100;
                        return (
                          <div
                            key={i}
                            className={"pr-seg seg-" + c.tagCls}
                            style={{ left: `${left}%`, width: `${w}%` }}
                            title={`${c.tag} · ${c.file}`}
                          >
                            <span className="pr-seg-label">{c.tag}</span>
                          </div>
                        );
                      })}
                      <div className="pr-progress" style={{ width: `${pct}%` }}></div>
                      <div className="pr-playhead" style={{ left: `${pct}%` }}>
                        <div className="pr-playhead-ts mono">{fmtPRTime(t)}</div>
                      </div>
                    </div>
                    {/* Tracks label */}
                    <div className="pr-tracks-meta">
                      <span>z0 VideoAsset</span>
                      <span>z1 AudioAsset</span>
                      <span>z2 TextAsset</span>
                    </div>
                  </div>

                  <div className="pr-cluster">
                    <span className="pill mono" style={{ borderColor: "var(--accent-line)", color: "var(--accent)" }}>
                      editor.Timeline
                    </span>
                  </div>
                </div>
              </div>

              {/* Auto-generated description */}
              <div className="pr-desc">
                <div className="pr-desc-tabs">
                  <span className="pr-desc-tab is-active">Description</span>
                  <span className="pr-desc-tab">Contribution map</span>
                  <span className="pr-desc-tab">Q&amp;A</span>
                </div>
                <div className="pr-desc-body">
                  <div className="pr-desc-section">
                    <div className="pr-desc-h"># What</div>
                    <p>Replace <code>CaptureSession</code> (macOS/Windows only) with 15s chunked <code>collection.upload</code>. Add scene grounding to narration so the LLM only describes what the index actually shows.</p>
                  </div>
                  <div className="pr-desc-section">
                    <div className="pr-desc-h"># Why</div>
                    <p>No Linux Wayland wheel for the capture SDK — see the stuck moment at <a className="lnk" href="#">01:34</a>. Scene grounding added after narration invented function names that were never on screen.</p>
                  </div>
                  <div className="pr-desc-section">
                    <div className="pr-desc-h"># Struggles</div>
                    <p>12 min on <code>videodb[capture]</code> install failure. Switched to <code>LiveIndexer</code> thread — same API surfaces, no RTSP tunnel needed.</p>
                  </div>
                  <div className="pr-desc-section">
                    <div className="pr-desc-h"># Follow-ups</div>
                    <p>Cache the voice clone ref audio per session instead of regenerating each run. Filed as <a className="lnk" href="#">#39</a>.</p>
                  </div>
                </div>
              </div>
            </div>

            {/* Reviewer Q&A example */}
            <div className="pr-comment small">
              <div className="pr-comment-head">
                <div className="pr-avatar gh">A</div>
                <div>
                  <div className="pr-comment-name">alex · <span className="mute">reviewer</span></div>
                  <div className="mute" style={{ fontSize: 11 }}>2 minutes ago</div>
                </div>
              </div>
              <div className="pr-comment-body">
                <span className="acc">@trace</span> why not use the official <code>CaptureSession</code> API?
              </div>
            </div>

            <div className="pr-comment small bot">
              <div className="pr-comment-head">
                <div className="pr-avatar">@</div>
                <div>
                  <div className="pr-comment-name">trace-bot · <span className="mute">replying to @alex</span></div>
                  <div className="mute" style={{ fontSize: 11 }}>3 clips · semantic search across session</div>
                </div>
              </div>
              <div className="pr-comment-body">
                <p>No Linux Wayland wheel — <code>pip install videodb[capture]</code> fails on Arch. From the session:</p>
                <p className="mute" style={{ paddingLeft: 12, borderLeft: "2px solid var(--accent-line)" }}>
                  &ldquo;pip error, no wheel for linux — switching to collection.upload, same surfaces light up anyway.&rdquo;
                </p>
                <div className="pr-qa-clips">
                  <a className="pr-qa-clip" href="#">▶ 01:34 → 02:10 · stuck on CaptureSession install</a>
                  <a className="pr-qa-clip" href="#">▶ 02:11 → 02:48 · reads VideoDB upload docs</a>
                  <a className="pr-qa-clip" href="#">▶ 02:49 → 03:22 · wires LiveIndexer thread</a>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <style>{`
        .pr-shell {
          border: 1px solid var(--line-strong);
          background: linear-gradient(180deg, rgba(255,255,255,0.012), transparent);
        }
        .pr-shell-head {
          display: flex; justify-content: space-between; align-items: center;
          padding: 16px 24px;
          border-bottom: 1px solid var(--line);
          font-size: 12px;
          font-family: var(--mono);
        }
        .pr-shell-l { display: flex; gap: 10px; align-items: center; }
        .pr-repo { color: var(--fg-dim); }
        .pr-num { font-weight: 600; }
        .pr-state {
          margin-left: 6px;
          padding: 3px 10px;
          background: var(--accent-bright);
          color: #1a0800;
          font-weight: 600;
          font-size: 10px;
          letter-spacing: 0.08em;
        }
        .pr-title {
          padding: 24px;
          font-family: var(--display);
          font-style: var(--display-style, italic);
          font-size: 26px;
          font-weight: var(--display-weight, 500);
          letter-spacing: -0.005em;
          border-bottom: 1px solid var(--line);
          line-height: 1.25;
          margin: 0;
        }
        .pr-title .mono {
          font-family: var(--mono);
          font-style: normal;
          color: var(--accent);
          font-size: 13.5px;
          margin-right: 8px;
          letter-spacing: 0;
        }
        .pr-body { padding: 24px; display: grid; gap: 20px; }

        .pr-comment {
          border: 1px solid var(--line);
          background: rgba(255,255,255,0.012);
        }
        .pr-comment-head {
          display: flex; gap: 12px; align-items: center;
          padding: 14px 20px;
          border-bottom: 1px solid var(--line);
        }
        .pr-avatar {
          width: 28px; height: 28px;
          background: var(--accent); color: #0a0a0b;
          display: flex; align-items: center; justify-content: center;
          font-weight: 700; font-size: 13px;
          flex-shrink: 0;
        }
        .pr-avatar.gh { background: #3a3a40; color: var(--fg); }
        .pr-comment-name { font-size: 12.5px; font-weight: 600; }
        .pr-comment-body {
          padding: 18px 20px;
          font-size: 13px; line-height: 1.65;
        }
        .pr-comment-body p { margin: 0 0 10px; }
        .pr-comment-body p:last-child { margin-bottom: 0; }
        .pr-comment-body code {
          font-family: var(--mono); font-size: 12px;
          padding: 1px 6px;
          background: rgba(255,91,31,0.08);
          color: var(--accent);
          border: 1px solid var(--accent-line);
        }

        /* Video player */
        .pr-video {
          padding: 0;
          background: #060608;
        }
        .pr-video-stage {
          position: relative;
          display: grid;
          grid-template-columns: 1.4fr 1fr;
          gap: 0;
          border-bottom: 1px solid var(--line);
        }
        @media (max-width: 900px) {
          .pr-video-stage { grid-template-columns: 1fr; }
        }
        .pr-scene {
          position: relative;
          aspect-ratio: 16 / 9;
          background:
            radial-gradient(ellipse at 50% 0%, rgba(255,91,31,0.05), transparent 60%),
            #08080a;
          overflow: hidden;
          border-right: 1px solid var(--line);
        }
        .pr-scene-grid {
          position: absolute; inset: 0;
          background-image:
            linear-gradient(rgba(255,255,255,0.04) 1px, transparent 1px),
            linear-gradient(90deg, rgba(255,255,255,0.04) 1px, transparent 1px);
          background-size: 32px 32px;
          opacity: 0.5;
        }
        .pr-scene-editor {
          position: absolute;
          top: 14%; left: 8%; right: 12%; bottom: 26%;
          border: 1px solid var(--line-strong);
          background: #0a0a0c;
          display: flex; flex-direction: column;
          font-family: var(--mono);
          font-size: 11px;
        }
        .pr-scene-tab {
          display: flex; gap: 8px; align-items: center;
          padding: 6px 10px;
          border-bottom: 1px solid var(--line);
          color: var(--fg-dim);
          background: rgba(255,255,255,0.018);
        }
        .pr-scene-code { padding: 8px 10px; flex: 1; overflow: hidden; }
        .pr-line { display: flex; gap: 8px; line-height: 1.65; }
        .pr-ln { width: 24px; text-align: right; }
        .pr-sign { width: 10px; }
        .pr-line.plus { background: rgba(255,122,69,0.07); }
        .pr-line.plus .pr-sign, .pr-line.plus .pr-code { color: var(--accent-bright); }
        .pr-line.minus { background: rgba(204,61,10,0.07); }
        .pr-line.minus .pr-sign, .pr-line.minus .pr-code { color: var(--accent-mid); }

        .pr-badge {
          position: absolute;
          top: 14px; left: 14px;
          display: flex; gap: 8px; align-items: center;
          background: rgba(0,0,0,0.55);
          backdrop-filter: blur(6px);
          -webkit-backdrop-filter: blur(6px);
          padding: 6px 10px;
          border: 1px solid var(--line-strong);
          font-size: 11px;
          font-family: var(--mono);
        }
        .pr-badge-file { color: var(--fg); font-family: var(--mono); }

        .pr-wave {
          position: absolute;
          left: 0; right: 0; bottom: 0;
          height: 26%;
          display: flex; align-items: flex-end; gap: 2px;
          padding: 8px 14px;
          background: linear-gradient(180deg, transparent, rgba(255,91,31,0.05));
          pointer-events: none;
        }
        .pr-wave span {
          flex: 1;
          background: var(--accent);
          opacity: 0.55;
          min-height: 4%;
          transition: height 80ms linear;
        }

        .pr-caption {
          padding: 24px;
          display: flex; flex-direction: column; gap: 14px;
          background: #08080a;
          font-family: var(--mono);
        }
        .pr-caption-text {
          font-family: var(--display);
          font-style: var(--display-style, italic);
          font-size: 20px;
          font-weight: var(--display-weight, 500);
          letter-spacing: -0.005em;
          line-height: 1.4;
          color: var(--fg);
        }
        .pr-caption-tx { font-size: 11.5px; font-style: italic; }

        .pr-controls {
          display: grid;
          grid-template-columns: auto auto 1fr auto;
          gap: 16px;
          align-items: center;
          padding: 18px 24px 22px;
        }
        .pr-play {
          appearance: none;
          width: 36px; height: 36px;
          background: var(--accent);
          color: #0a0a0b;
          border: 0;
          font-size: 12px;
          cursor: pointer;
          display: inline-flex; align-items: center; justify-content: center;
        }
        .pr-play:hover { filter: brightness(1.1); }
        .pr-time { color: var(--fg-dim); font-size: 12px; min-width: 80px; }

        .pr-track-wrap { position: relative; padding-bottom: 14px; }
        .pr-track {
          position: relative;
          height: 28px;
          background: #0d0d10;
          border: 1px solid var(--line);
          cursor: pointer;
          user-select: none;
        }
        .pr-seg {
          position: absolute; top: 0; bottom: 0;
          border-right: 1px solid #0a0a0b;
          display: flex; align-items: center; padding: 0 6px;
          overflow: hidden;
          pointer-events: none;
        }
        .pr-seg-label {
          font-family: var(--mono);
          font-size: 9.5px; letter-spacing: 0.1em;
          color: rgba(255,255,255,0.65);
          text-transform: uppercase;
        }
        .seg-b { background: rgba(255,179,138,0.15); }
        .seg-g { background: rgba(255,122,69,0.15); }
        .seg-r { background: rgba(204,61,10,0.2); }
        .seg-y { background: rgba(255,154,92,0.15); }
        .pr-progress {
          position: absolute; top: 0; bottom: 0; left: 0;
          background: rgba(255,91,31,0.18);
          pointer-events: none;
        }
        .pr-playhead {
          position: absolute; top: -4px; bottom: -4px;
          width: 2px;
          background: var(--accent);
          box-shadow: 0 0 14px var(--accent);
          pointer-events: none;
        }
        .pr-playhead-ts {
          position: absolute; bottom: -22px; left: 50%; transform: translateX(-50%);
          font-size: 10px;
          color: var(--accent);
          background: #0a0a0b;
          padding: 1px 4px;
          white-space: nowrap;
        }
        .pr-tracks-meta {
          display: flex; gap: 16px;
          margin-top: 6px;
          font-family: var(--mono);
          font-size: 10px;
          color: var(--fg-mute);
          letter-spacing: 0.12em;
          text-transform: uppercase;
        }
        .pr-cluster { display: flex; gap: 8px; }

        /* Description */
        .pr-desc {
          border-top: 1px solid var(--line);
        }
        .pr-desc-tabs {
          display: flex; gap: 0;
          border-bottom: 1px solid var(--line);
          font-family: var(--mono);
        }
        .pr-desc-tab {
          padding: 14px 20px;
          font-size: 11.5px;
          color: var(--fg-dim);
          border-right: 1px solid var(--line);
          cursor: pointer;
          letter-spacing: 0.04em;
        }
        .pr-desc-tab.is-active {
          color: var(--accent);
          border-bottom: 1px solid var(--accent);
          margin-bottom: -1px;
          background: var(--accent-soft);
        }
        .pr-desc-body {
          padding: 24px;
          display: grid;
          grid-template-columns: repeat(2, 1fr);
          gap: 24px;
        }
        @media (max-width: 700px) { .pr-desc-body { grid-template-columns: 1fr; } }
        .pr-desc-h {
          font-family: var(--mono);
          font-size: 11.5px;
          color: var(--accent);
          letter-spacing: 0.02em;
          margin-bottom: 10px;
        }
        .pr-desc-section p { margin: 0; font-size: 12.5px; line-height: 1.7; color: var(--fg-dim); }
        .pr-desc-section p code {
          font-family: var(--mono); font-size: 11.5px;
          padding: 1px 5px;
          background: rgba(255,91,31,0.08);
          color: var(--accent);
          border: 1px solid var(--accent-line);
        }

        .pr-qa-clips { display: grid; gap: 6px; margin-top: 12px; }
        .pr-qa-clip {
          display: block;
          padding: 10px 14px;
          border: 1px solid var(--line);
          color: var(--fg-dim);
          text-decoration: none;
          font-family: var(--mono);
          font-size: 11.5px;
        }
        .pr-qa-clip:hover { border-color: var(--accent); color: var(--accent); }

        /* Responsive */
        @media (max-width: 900px) {
          .pr-video-stage { grid-template-columns: 1fr; }
          .pr-scene { border-right: 0; border-bottom: 1px solid var(--line); }
          .pr-controls {
            grid-template-columns: auto auto 1fr;
            grid-template-rows: auto auto;
            row-gap: 14px;
          }
          .pr-cluster { grid-column: 1 / -1; justify-content: flex-end; }
        }
        @media (max-width: 600px) {
          .pr-shell-head { padding: 12px 16px; flex-wrap: wrap; gap: 8px; }
          .pr-shell-r { font-size: 10.5px; }
          .pr-title { padding: 18px 16px; font-size: 22px; }
          .pr-title .mono { display: block; margin-bottom: 4px; font-size: 12px; }
          .pr-body { padding: 16px; gap: 16px; }
          .pr-comment-head { padding: 12px 14px; }
          .pr-comment-body { padding: 14px; font-size: 12.5px; }
          .pr-scene-editor { left: 6%; right: 6%; top: 10%; bottom: 30%; }
          .pr-scene-code { font-size: 10px; }
          .pr-badge { top: 8px; left: 8px; font-size: 9.5px; padding: 4px 8px; gap: 6px; }
          .pr-caption { padding: 16px; }
          .pr-caption-text { font-size: 17px; }
          .pr-caption-tx { font-size: 10.5px; }
          .pr-controls {
            grid-template-columns: auto 1fr;
            padding: 14px 16px 18px;
            gap: 12px 14px;
          }
          .pr-time { font-size: 11px; min-width: 64px; }
          .pr-track-wrap { grid-column: 1 / -1; }
          .pr-cluster { grid-column: 1 / -1; }
          .pr-desc-tabs { flex-wrap: wrap; }
          .pr-desc-tab { padding: 12px 14px; font-size: 11px; flex: 1; text-align: center; }
          .pr-desc-body { padding: 16px; gap: 18px; }
          .pr-desc-section p { font-size: 12px; }
          .pr-qa-clip { font-size: 11px; padding: 10px 12px; }
        }
      `}</style>
    </section>
  );
}
window.PRWalkthrough = PRWalkthrough;
