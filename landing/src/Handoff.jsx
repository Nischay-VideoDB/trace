function shellQuote(value) {
  const clean = String(value || "").trim() || "/absolute/path/to/repository";
  return `'${clean.replaceAll("'", `'"'"'`)}'`;
}

function Handoff() {
  const [platform, setPlatform] = React.useState(/Win/.test(navigator.platform) ? "windows" : "macos");
  const [projectPath, setProjectPath] = React.useState("/absolute/path/to/repository");
  const [microphone, setMicrophone] = React.useState(true);
  const [live, setLive] = React.useState(true);
  const [state, setState] = React.useState("idle");
  const [plan, setPlan] = React.useState(null);
  const [error, setError] = React.useState("");

  async function create(event) {
    event.preventDefault();
    setState("loading");
    setError("");
    setPlan(null);
    try {
      const response = await fetch("/api/handoffs", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "idempotency-key": `trace-web-${crypto.randomUUID()}`,
        },
        body: JSON.stringify({ platform, microphone, live }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || "The handoff could not be created.");
      setPlan(body);
      setState("ready");
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "The handoff could not be created.");
      setState("error");
    }
  }

  const startCommand = plan
    ? `uv run trace start --project ${shellQuote(projectPath)}${plan.options.live ? " --live" : ""}${plan.options.microphone ? "" : " --no-mic"}`
    : "";
  const doctorCommand = `uv run trace doctor --project ${shellQuote(projectPath)}`;
  const cliCommand = plan ? plan.cliCommand.replace("/absolute/path/to/repository", shellQuote(projectPath)) : "";

  return (
    <section className="section handoff" id="handoff">
      <div className="wrap">
        <div className="section-head">
          <div>
            <span className="section-tag">Live desktop workflow</span>
            <h2 className="section-title">Prepare the run here.<br />Capture it locally.</h2>
          </div>
          <p className="section-sub">
            This control creates a signed, expiring setup handoff. It never requests an API key and the browser never captures your screen, microphone, repository, or local files.
          </p>
        </div>

        <div className="handoff-grid">
          <form className="handoff-form card card-bracket" onSubmit={create}>
            <label>
              <span>Desktop runtime</span>
              <select value={platform} onChange={(event) => setPlatform(event.target.value)}>
                <option value="macos">macOS · VideoDB Capture SDK</option>
                <option value="windows">Windows · VideoDB Capture SDK</option>
              </select>
            </label>
            <label>
              <span>Local repository path</span>
              <input value={projectPath} onChange={(event) => setProjectPath(event.target.value)} autoComplete="off" spellCheck="false" />
              <small>This value stays in your browser and is never sent to Trace.</small>
            </label>
            <label className="handoff-check"><input type="checkbox" checked={live} onChange={(event) => setLive(event.target.checked)} /><span>Use live VideoDB capture/indexing</span></label>
            <label className="handoff-check"><input type="checkbox" checked={microphone} onChange={(event) => setMicrophone(event.target.checked)} /><span>Request microphone consent at start</span></label>
            <button className="btn primary" disabled={state === "loading"}>{state === "loading" ? "Creating…" : "Create signed handoff →"}</button>
            {error && <p className="handoff-error" role="alert">{error}</p>}
          </form>

          <div className="handoff-result card" aria-live="polite">
            {!plan && <div className="handoff-empty"><span>01</span><p>Choose the desktop options. Trace will return a verifiable local run plan—not a simulated browser recording.</p></div>}
            {plan && (
              <div>
                <div className="handoff-result-head"><span className="chip acc">Signed · 24 hours</span><code>{plan.id}</code></div>
                <p className="handoff-boundary">{plan.boundary}</p>
                <ol className="handoff-steps">
                  <li><span>Install</span><code>{plan.commands.install}</code></li>
                  <li><span>Verify</span><code>{doctorCommand}</code></li>
                  <li><span>Start native capture</span><code>{startCommand}</code></li>
                </ol>
                <details><summary>Open this handoff from the CLI</summary><code className="handoff-cli">{cliCommand}</code></details>
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

window.Handoff = Handoff;
