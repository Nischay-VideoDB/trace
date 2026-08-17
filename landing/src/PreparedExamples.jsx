const PREPARED_FALLBACKS = [
  { id: "feature", kind: "Feature", title: "Narrated PR walkthrough" },
  { id: "bug", kind: "Bug fix", title: "Failure-to-fix replay" },
  { id: "refactor", kind: "Refactor", title: "Review-boundary refactor" },
];

function preparedTime(seconds) {
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.floor(seconds % 60);
  return `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
}

function validatePreparedExamples(payload) {
  if (!payload || payload.version !== 1 || !Array.isArray(payload.examples) || payload.examples.length !== 3) {
    throw new Error("Prepared example manifest is unavailable.");
  }

  const kinds = new Set(payload.examples.map((example) => example.kind));
  if (!kinds.has("Feature") || !kinds.has("Bug fix") || !kinds.has("Refactor")) {
    throw new Error("Prepared example manifest is incomplete.");
  }

  return payload.examples;
}

function PreparedExamples() {
  const [examples, setExamples] = React.useState([]);
  const [activeId, setActiveId] = React.useState("");
  const [activeChapter, setActiveChapter] = React.useState(0);
  const [status, setStatus] = React.useState("loading");
  const [playbackError, setPlaybackError] = React.useState("");
  const videoRef = React.useRef(null);
  const hlsRef = React.useRef(null);

  React.useEffect(() => {
    let mounted = true;

    fetch("/static/prepared-examples.v1.json")
      .then((response) => {
        if (!response.ok) throw new Error("Prepared examples could not be loaded.");
        return response.json();
      })
      .then((payload) => {
        const nextExamples = validatePreparedExamples(payload);
        if (!mounted) return;
        setExamples(nextExamples);
        setActiveId(nextExamples[0].id);
        setStatus("ready");
      })
      .catch(() => {
        if (!mounted) return;
        setExamples(PREPARED_FALLBACKS);
        setActiveId(PREPARED_FALLBACKS[0].id);
        setStatus("error");
      });

    return () => { mounted = false; };
  }, []);

  const activeExample = examples.find((example) => example.id === activeId) || examples[0];

  React.useEffect(() => {
    setPlaybackError("");
    const video = videoRef.current;
    const media = activeExample && activeExample.media;

    if (!video || status !== "ready" || !media || media.status !== "available") return undefined;

    if (hlsRef.current) {
      hlsRef.current.destroy();
      hlsRef.current = null;
    }
    video.removeAttribute("src");

    if (window.Hls && window.Hls.isSupported()) {
      const hls = new window.Hls();
      hlsRef.current = hls;
      hls.loadSource(media.src);
      hls.attachMedia(video);
      hls.on(window.Hls.Events.ERROR, (_event, data) => {
        if (data && data.fatal) setPlaybackError("The embedded player could not load this public output.");
      });
    } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
      video.src = media.src;
      video.load();
    } else {
      setPlaybackError("This browser cannot play the public HLS output inline.");
    }

    return () => {
      if (hlsRef.current) {
        hlsRef.current.destroy();
        hlsRef.current = null;
      }
    };
  }, [activeId, status]);

  function selectExample(id) {
    setActiveId(id);
    setActiveChapter(0);
    setPlaybackError("");
  }

  function selectChapter(index) {
    setActiveChapter(index);
    const chapter = activeExample.chapters[index];
    if (videoRef.current && chapter) {
      videoRef.current.currentTime = chapter.start;
      videoRef.current.pause();
    }
  }

  return (
    <section className="section prepared-examples" id="examples">
      <div className="wrap">
        <div className="section-head">
          <div>
            <span className="section-tag">Pre-run examples</span>
            <h2 className="section-title">Review the evidence<br />before you run.</h2>
          </div>
          <p className="section-sub">
            Three prepared, safe-to-share walkthroughs. Public outputs retain their source links; the refactor is clearly synthetic and intentionally clip-free.
          </p>
        </div>

        {status === "loading" && <p className="prepared-status" role="status">Loading prepared examples…</p>}
        {status === "error" && (
          <div className="prepared-status prepared-status-error" role="status">
            <strong>The prepared-example manifest is unavailable.</strong> You can still start the live workflow locally.
            <a className="lnk" href="#install">View local setup</a>
          </div>
        )}

        <div className="prepared-picker" aria-label="Prepared Trace examples">
          {examples.map((example) => (
            <button
              key={example.id}
              type="button"
              className={`prepared-picker-button${activeExample && example.id === activeExample.id ? " is-active" : ""}`}
              aria-pressed={Boolean(activeExample && example.id === activeExample.id)}
              onClick={() => selectExample(example.id)}
            >
              <span className="prepared-kind">{example.kind}</span>
              <span className="prepared-picker-title">{example.title}</span>
              {example.media && example.media.status === "available" && <span className="prepared-availability">playable output</span>}
              {example.media && example.media.status === "unavailable" && <span className="prepared-availability">interactive evidence</span>}
            </button>
          ))}
        </div>

        {activeExample && status === "ready" && (
          <article className="prepared-detail card card-bracket" id="prepared-example-detail" aria-live="polite">
            <div className="prepared-detail-head">
              <div>
                <div className="prepared-detail-meta">
                  <span className="chip acc">{activeExample.kind}</span>
                  <span>{activeExample.pullRequest.label}</span>
                  <span>{activeExample.pullRequest.state}</span>
                  <span>{activeExample.pullRequest.scope}</span>
                </div>
                <h3 className="prepared-detail-title">{activeExample.title}</h3>
                <p>{activeExample.summary}</p>
              </div>
              <a className="lnk prepared-source" href={activeExample.source.url} target={activeExample.source.url === "#examples" ? undefined : "_blank"} rel={activeExample.source.url === "#examples" ? undefined : "noreferrer"}>
                {activeExample.source.label} ↗
              </a>
            </div>

            <div className="prepared-main">
              <div className="prepared-media-column">
                {activeExample.media.status === "available" ? (
                  <div className="prepared-video-shell">
                    <video ref={videoRef} controls preload="metadata" aria-label={activeExample.media.label}>
                      Your browser does not support the prepared walkthrough video.
                    </video>
                    <div className="prepared-media-note">
                      <span>{activeExample.media.duration} public output</span>
                      <a className="lnk" href={activeExample.media.src} target="_blank" rel="noreferrer">Open original stream ↗</a>
                    </div>
                    <p className="prepared-rights-note">{activeExample.media.rights_note}</p>
                    {playbackError && <p className="prepared-playback-error" role="alert">{playbackError} Use “Open original stream” above.</p>}
                  </div>
                ) : (
                  <div className="prepared-no-media" role="status">
                    <span className="prepared-no-media-kicker">Clip intentionally unavailable</span>
                    <p>{activeExample.media.message}</p>
                    <a className="btn" href="#install">Run the live workflow locally →</a>
                  </div>
                )}

                <div className="prepared-evidence">
                  <span className="prepared-panel-label">{activeExample.evidence.label}</span>
                  <p>{activeExample.evidence.text}</p>
                  <span className="prepared-citation">Source: {activeExample.evidence.citation}</span>
                </div>
                <div className="prepared-evidence">
                  <span className="prepared-panel-label">Transcript / evidence</span>
                  <p>{activeExample.transcript.text}</p>
                  <span className="prepared-citation">{activeExample.transcript.label} · Source: {activeExample.transcript.citation}</span>
                </div>
              </div>

              <div className="prepared-evidence-column">
                <div className="prepared-panel">
                  <div className="prepared-panel-label">Timeline and chapters</div>
                  <div className="prepared-chapters">
                    {activeExample.chapters.map((chapter, index) => (
                      <button
                        type="button"
                        key={`${chapter.start}-${chapter.label}`}
                        className={`prepared-chapter${index === activeChapter ? " is-active" : ""}`}
                        onClick={() => selectChapter(index)}
                      >
                        <span className="prepared-chapter-time">{preparedTime(chapter.start)} - {preparedTime(chapter.end)}</span>
                        <span>{chapter.label}</span>
                      </button>
                    ))}
                  </div>
                  <p className="prepared-chapter-evidence">{activeExample.chapters[activeChapter].evidence}</p>
                </div>

                <div className="prepared-panel">
                  <div className="prepared-panel-label">Contribution map</div>
                  <div className="prepared-contribution-bar" role="img" aria-label={activeExample.contribution.map((item) => `${item.label} ${item.value}%`).join(", ")}>
                    {activeExample.contribution.map((item) => (
                      <span key={item.label} className={item.className} style={{ width: `${item.value}%` }} />
                    ))}
                  </div>
                  <div className="prepared-contribution-legend">
                    {activeExample.contribution.map((item) => <span key={item.label}>{item.label} {item.value}%</span>)}
                  </div>
                  <p>{activeExample.contributionNote}</p>
                </div>

                <div className="prepared-panel">
                  <div className="prepared-panel-label">Review Q&amp;A</div>
                  <p className="prepared-question">{activeExample.qa.question}</p>
                  <p>{activeExample.qa.answer}</p>
                  <span className="prepared-citation">Source: {activeExample.qa.citation}</span>
                </div>
              </div>
            </div>

            <div className="prepared-files">
              <span className="prepared-panel-label">Context</span>
              <div>
                {activeExample.files.map((file) => <code key={file}>{file}</code>)}
              </div>
              <p>{activeExample.source.note}</p>
            </div>
          </article>
        )}
      </div>
    </section>
  );
}

window.PreparedExamples = PreparedExamples;
