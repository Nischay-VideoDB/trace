function HeroTerminal() {
  const sessions = React.useMemo(
    () => [
      {
        head: "trace start",
        lines: [
          { p: "$", c: "uv run trace start --project /tmp/demo --live" },
          { o: "session 7a2f..  capture: wf-recorder + ffmpeg/pulse" },
          { o: "live indexer: 15s chunks → VideoDB collection" },
          { o: "watchers: inotify saves + hyprctl active window" },
          { o: "heartbeat 5s · audio rate 48k · video 1080p" },
          { ok: "recording. talk out loud while you code." },
        ],
      },
      {
        head: "trace stop",
        lines: [
          { p: "$", c: "uv run trace stop" },
          { o: "muxing pulse audio into session.mp4" },
          { o: "upload → Collection.upload(session.mp4)" },
          { o: "index_spoken_words(sentence)  · 412 segments" },
          { o: "index_scenes(time_based, prompt=...) · 78 scenes" },
          { o: "timeline: 4 stuck · 12 progress · 7 speech · 3 research" },
          { ok: "session indexed. ready: trace generate <sid> <pr>" },
        ],
      },
      {
        head: "trace generate",
        lines: [
          { p: "$", c: "uv run trace generate 7a2f https://github.com/you/repo/pull/12" },
          { o: "selector: 9 clips picked from diff (auth.py, jwt.py)" },
          { o: "generate_image(FLUX): intro title card 16:9" },
          { o: "generate_text(pro): scene-grounded narration × 9" },
          { o: "generate_voice(OmniVoice): reference + 9 cloned clips" },
          { o: "generate_music: ambient background 120s" },
          { o: "editor.Timeline: intro · video · narration · badges · music" },
          { o: "Timeline.generate_stream() → HLS m3u8" },
          { ok: "posted to PR · description appended · contrib map up" },
        ],
      },
    ],
    [],
  );

  const [idx, setIdx] = React.useState(0);
  const [line, setLine] = React.useState(0);
  const [char, setChar] = React.useState(0);

  React.useEffect(() => {
    const s = sessions[idx];
    if (line >= s.lines.length) {
      const t = setTimeout(() => {
        setIdx((idx + 1) % sessions.length);
        setLine(0);
        setChar(0);
      }, 1800);
      return () => clearTimeout(t);
    }
    const cur = s.lines[line];
    const txt = cur.c || cur.o || cur.ok || "";
    if (char < txt.length) {
      const speed = cur.c ? 28 : 8;
      const t = setTimeout(() => setChar(char + 1), speed);
      return () => clearTimeout(t);
    }
    const t = setTimeout(() => {
      setLine(line + 1);
      setChar(0);
    }, cur.c ? 220 : 80);
    return () => clearTimeout(t);
  }, [idx, line, char, sessions]);

  const s = sessions[idx];
  return (
    <div className="term">
      <div className="term-head">
        <div className="term-dots"><i /><i /><i /></div>
        <span>~/repo · {s.head}</span>
        <span className="mono">●REC</span>
      </div>
      <div className="term-body">
        {s.lines.slice(0, line).map((l, i) => (
          <div key={i} className="line">
            {l.c && <><span className="prompt">$</span> <span className="cmd">{l.c}</span></>}
            {l.o && <span className="dim">{l.o}</span>}
            {l.ok && <span className="green">✓ {l.ok}</span>}
          </div>
        ))}
        {line < s.lines.length && (
          <div className="line">
            {s.lines[line].c && (
              <>
                <span className="prompt">$</span>{" "}
                <span className="cmd">{s.lines[line].c.slice(0, char)}</span>
              </>
            )}
            {s.lines[line].o && <span className="dim">{s.lines[line].o.slice(0, char)}</span>}
            {s.lines[line].ok && <span className="green">✓ {s.lines[line].ok.slice(0, char)}</span>}
            <span className="caret" />
          </div>
        )}
      </div>
    </div>
  );
}

function Hero() {
  return (
    <section className="hero wrap">
      <div className="hero-grid">
        <div className="hero-left">
          <div className="hero-eyebrow">
            <span className="dot" />
            <span>powered by VideoDB</span>
          </div>
          <h1 className="hero-title">
            code<span style={{ color: "#fff" }}>,</span><br />
            <span className="acc">narrated</span><span className="acc">.</span>
          </h1>
          <p className="hero-sub">
            record a coding session. get a PR that explains itself: narrated walkthrough video, /trace Q&amp;A bot, focus mode, contribution map. one vendor, twenty-four API calls.
          </p>
          <div className="hero-ctas">
            <a className="btn primary" href="#handoff">Create desktop handoff →</a>
            <a className="btn" href="#examples">Explore prepared examples</a>
            <a className="btn" href="#features">Features</a>
          </div>
          <div className="hero-stats">
            <div>
              <div className="hero-stat-k">VideoDB calls</div>
              <div className="hero-stat-v">24</div>
              <div className="hero-stat-n">across 8 files</div>
            </div>
            <div>
              <div className="hero-stat-k">CLI commands</div>
              <div className="hero-stat-v">15</div>
              <div className="hero-stat-n">capture · index · inspect · generate · review</div>
            </div>
            <div>
              <div className="hero-stat-k">Vendors</div>
              <div className="hero-stat-v">1</div>
              <div className="hero-stat-n">VideoDB only · no Whisper, no OpenAI</div>
            </div>
          </div>
        </div>
        <div className="hero-term">
          <HeroTerminal />
        </div>
      </div>
    </section>
  );
}
window.Hero = Hero;
