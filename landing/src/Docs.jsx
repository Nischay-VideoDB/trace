function Docs() {
  const tree = [
    ["dir", "trace_cli/", ""],
    ["file", "  cli.py", "typer entry (start, stop, generate, replay, serve, qa-poll, focus)"],
    ["file", "  credentials.py", "env var loading + key redaction"],
    ["file", "  videodb/client.py", "single VideoDB facade"],
    ["file", "  github/client.py", "PR URL validator + comment / diff / description ops"],
    ["dir",  "  session/", ""],
    ["file", "    models.py", "pydantic SessionMetadata, Heartbeat, Transcript, Timeline"],
    ["file", "    store.py", "~/.trace/sessions/ on-disk layout"],
    ["file", "    manager.py", "start / stop lifecycle, active-session lock"],
    ["file", "    ids.py", "UUID v4 helpers"],
    ["dir",  "  capture/", ""],
    ["file", "    service.py", "wf-recorder + ffmpeg pulse subprocesses"],
    ["file", "    heartbeat.py", "5s heartbeat writer"],
    ["file", "    watchers.py", "inotify file save watcher + hyprctl window poller"],
    ["file", "    live_indexer.py", "15s chunk upload + index thread (--live mode)"],
    ["dir",  "  indexing/", ""],
    ["file", "    pipeline.py", "mux audio + upload + spoken/scene index + transcript fetch"],
    ["dir",  "  timeline/", ""],
    ["file", "    builder.py", "boundary merger + priority resolution"],
    ["file", "    classifiers/__init__.py", "progress / speech / research / stuck"],
    ["file", "    build_for_session.py", "glue: load session data, run classifiers, persist"],
    ["dir",  "  pr_video/", ""],
    ["file", "    selector.py", "per-moment clip selection (ranked, paged transcript summary)"],
    ["file", "    narration.py", "batched, scene + transcript grounded"],
    ["file", "    render.py", "editor.Timeline with 3 tracks: video / audio / badges"],
    ["file", "    generator.py", "end-to-end orchestration"],
    ["file", "    bug_replay.py", "stack trace → session moments"],
    ["dir",  "  focus_mode/", ""],
    ["file", "    builder.py", "reviewer Focus Mode ranking"],
    ["dir",  "  decision_replay/", ""],
    ["file", "    service.py", "file + line range -> bounded HLS clip intervals"],
    ["dir",  "  contribution_map/", ""],
    ["file", "    scanner.py", "read Claude Code session logs in capture window"],
    ["file", "    mapper.py", "classify diff lines as human / agent / mixed / unknown"],
    ["dir",  "  pr_description/", ""],
    ["file", "    generator.py", "What / Why / Struggles / Follow-ups"],
    ["dir",  "  web/", ""],
    ["file", "    app.py", "FastAPI Decision Replay UI + landing mount"],
    ["file", "    qa.py", "@trace polling bot"],
  ];

  const env = [
    ["VIDEODB_API_KEY", "Required. Get one from videodb.io or claim sandbox credit."],
    ["GITHUB_TOKEN", "Required for trace generate / qa-poll. Needs repo + pull_request scopes."],
    ["TRACE_HOME", "Optional. Default ~/.trace · session store root."],
    ["TRACE_NARRATION_MODEL", "Optional. basic | pro | ultra. Default pro."],
  ];

  const adrs = [
    {
      h: "Pseudo-live chunked upload instead of CaptureSession",
      p: "VideoDB's Capture SDK ships wheels for macOS and Windows only. On Linux Wayland (Hyprland) it's uninstallable. trace's --live mode cuts the in-progress mp4 every 15s, uploads each chunk via Collection.upload, and indexes each one. Same VideoDB surfaces light up; no public RTSP tunnel required.",
    },
    {
      h: "VideoDB-only stack",
      p: "Earlier drafts used OpenAI Whisper for transcription, OpenRouter for LLM, and OpenAI TTS for narration. We dropped all three: Video.index_spoken_words covers transcript, Collection.generate_text covers narration scripting, Collection.generate_voice covers TTS. One vendor, max API surface.",
    },
    {
      h: "Scene-grounded narration",
      p: "An earlier version hallucinated technical details (\"run_until_complete deadlock\") the developer never said. We now pass the per-clip slice of the scene index (label, files, errors, summary) into the prompt with explicit anti-hallucination rules.",
    },
    {
      h: "Long-session resilience",
      p: "Ranked clip selection, batched narration prompts, parallel TTS, paged transcript summary, retry + backoff at every VideoDB boundary. Three-hour sessions don't blow up the context window.",
    },
  ];

  const limits = [
    "Linux Wayland + Hyprland is the verified host. X11 needs an x11grab swap-in.",
    "CaptureSession SDK has no Linux wheel — chunked upload is the workaround.",
    "Mic capture defaults to pulse; pipewire works via the pulse compat shim.",
    "trace serve binds 127.0.0.1 by default. Don't expose without auth.",
  ];

  const sections = [
    { id: "overview", label: "Overview" },
    { id: "pipeline", label: "Pipeline" },
    { id: "tree", label: "Repo tree" },
    { id: "env", label: "Env vars" },
    { id: "adrs", label: "ADRs" },
    { id: "limits", label: "Limits" },
  ];

  return (
    <>
      <div className="grid-bg" />
      <div className="page">
        <Nav active="Docs" />
        <section className="section">
          <div className="wrap">
            <div className="section-head">
              <div>
                <span className="section-tag">trace · reference</span>
                <h2 className="section-title">Docs.</h2>
              </div>
              <p className="section-sub">
                What trace does, in what order, against which VideoDB surfaces. If something on the landing page is unclear, it's spelled out here.
              </p>
            </div>

            <div className="docs-grid">
              <aside className="docs-side">
                <div className="docs-side-h">On this page</div>
                {sections.map((s) => <a key={s.id} href={"#" + s.id}>{s.label}</a>)}
                <div className="docs-side-h" style={{ marginTop: 24 }}>Related</div>
                <a href="/">Landing</a>
                <a href="/replay">Decision Replay</a>
              </aside>

              <div>
                <div id="overview" className="docs-block">
                  <h3 className="docs-h2">Overview</h3>
                  <p>
                    trace is a CLI plus a small FastAPI app. The CLI runs locally, captures your screen and mic during a coding session, and indexes the result through VideoDB. The FastAPI app exposes Decision Replay and serves this site. There is no managed backend.
                  </p>
                  <pre>{`trace start  →  trace stop  →  trace generate  →  PR decorated.
                              ↓
                  trace serve · trace replay · trace qa-poll · trace focus`}</pre>
                </div>

                <div id="pipeline" className="docs-block">
                  <h3 className="docs-h2">Pipeline</h3>
                  <p>The capture-to-PR flow, in order:</p>
                  <pre>{`1. capture/service.py        wf-recorder + ffmpeg/pulse subprocesses
2. capture/live_indexer.py   15s chunks → Collection.upload (when --live)
3. capture/watchers.py       inotify saves + hyprctl active window samples
4. indexing/pipeline.py      mux audio · upload · index_spoken_words · index_scenes
5. timeline/builder.py       merge classifier boundaries · resolve priority
6. pr_video/selector.py      pick clips per diff file (ranked)
7. pr_video/narration.py     batched generate_text grounded in scene + transcript
8. pr_video/render.py        editor.Timeline · video · audio · badge tracks
9. pr_description/generator  What / Why / Struggles / Follow-ups
10. github/client.py         post HLS + description + contribution map to PR`}</pre>
                </div>

                <div id="tree" className="docs-block">
                  <h3 className="docs-h2">Repo tree</h3>
                  <pre className="repo-tree">
                    {tree.map(function (row, i) {
                      const [kind, path, note] = row;
                      const pad = Math.max(0, 36 - path.length);
                      return (
                        <div key={i}>
                          <span className={kind === "dir" ? "tree-dir" : "tree-file"}>{path}</span>
                          {note ? <><span>{" ".repeat(pad)}</span><span className="tree-note">{note}</span></> : null}
                        </div>
                      );
                    })}
                  </pre>
                </div>

                <div id="env" className="docs-block">
                  <h3 className="docs-h2">Env vars</h3>
                  <table className="api-table" style={{ marginTop: 12 }}>
                    <thead><tr><th>Name</th><th>Purpose</th></tr></thead>
                    <tbody>
                      {env.map((r) => (
                        <tr key={r[0]}><td className="api">{r[0]}</td><td className="purpose">{r[1]}</td></tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <div id="adrs" className="docs-block">
                  <h3 className="docs-h2">Architecture decisions</h3>
                  {adrs.map((a, i) => (
                    <div key={i} style={{ marginBottom: 24 }}>
                      <div style={{ color: "var(--accent)", fontFamily: "var(--mono)", fontSize: 12, letterSpacing: "0.08em", marginBottom: 8 }}>
                        ADR-{String(i + 1).padStart(2, "0")}
                      </div>
                      <div style={{ fontFamily: "var(--display)", fontStyle: "italic", fontSize: 22, marginBottom: 8 }}>{a.h}</div>
                      <p>{a.p}</p>
                    </div>
                  ))}
                </div>

                <div id="limits" className="docs-block">
                  <h3 className="docs-h2">Known limits</h3>
                  <ul style={{ color: "var(--fg-dim)", lineHeight: 1.75, paddingLeft: 18 }}>
                    {limits.map((l, i) => <li key={i}>{l}</li>)}
                  </ul>
                </div>
              </div>
            </div>
          </div>
        </section>
        <Footer />
      </div>
    </>
  );
}

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(<Docs />);
