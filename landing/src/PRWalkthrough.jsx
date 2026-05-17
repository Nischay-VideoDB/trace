var PR_CLIPS = [
  {
    t: 0, d: 12, label: "Setup", file: "auth.py",
    cap: "We start by reading the failing test — the JWT expiry check is off by one.",
    code: [
      ["41", ["def ", { kw: "verify" }, "(token: str):"]],
      ["42", ["    payload = decode(token, KEY)"]],
      ["43", ["    exp = payload[", { str: "\"exp\"" }, "]"]],
      ["44", ["    ", { kw: "if" }, " exp < now():"]],
      ["45", ["        raise Expired()"]],
      ["46", ["    return payload"]],
    ],
    diff: [
      { k: "hunk", v: "@@ auth.py:42-48 @@" },
      { k: "ctx", v: "  def verify(token: str):" },
      { k: "rem", v: "-     if exp < now():" },
      { k: "add", v: "+     if exp <= now() - LEEWAY:" },
      { k: "ctx", v: "          raise Expired" },
    ],
  },
  {
    t: 12, d: 18, label: "Stuck", file: "jwt.py",
    cap: "I get stuck on PyJWT's leeway semantics — docs and source disagree on the sign.",
    code: [
      ["01", [{ kw: "import" }, " jwt"]],
      ["02", [{ kw: "from" }, " jwt ", { kw: "import" }, " InvalidTokenError"]],
      ["03", [""]],
      ["04", ["# ?? leeway sign — docs say add, src subtracts"]],
      ["05", ["jwt.decode(token, key, ", { acc: "leeway=30" }, ")"]],
    ],
    diff: [
      { k: "hunk", v: "@@ jwt.py:1-8 @@" },
      { k: "rem", v: "- import jwt" },
      { k: "add", v: "+ from authlib.jose import jwt" },
      { k: "ctx", v: "  # authlib gives us claim validators" },
    ],
  },
  {
    t: 30, d: 14, label: "Research", file: "rfc 7519",
    cap: "Reading RFC 7519 directly — exp is seconds-from-epoch, leeway flips inside the comparator.",
    code: [
      ["§4.1.4", ["The \"exp\" (expiration time) claim identifies"]],
      ["      ", ["the expiration time on or after which the JWT"]],
      ["      ", ["MUST NOT be accepted for processing."]],
      ["      ", [""]],
      ["      ", [{ acc: "Implementers MAY provide for some small leeway" }]],
      ["      ", [{ acc: "to account for clock skew (usually no more than" }]],
      ["      ", [{ acc: "a few minutes)." }]],
    ],
    diff: [
      { k: "hunk", v: "(research moment, no diff)" },
      { k: "ctx", v: "rfc 7519 §4.1.4 — leeway is reviewer-defined" },
    ],
  },
  {
    t: 44, d: 16, label: "Progress", file: "auth.py",
    cap: "Locked in: <= with a 30s leeway, matches the rfc and our prior behavior.",
    code: [
      ["41", ["LEEWAY = ", { kw: "timedelta" }, "(seconds=30)"]],
      ["42", [""]],
      ["43", [{ kw: "def" }, " verify(token: str):"]],
      ["44", ["    payload = jwt.decode(token, KEY)"]],
      ["45", ["    exp = payload[", { str: "\"exp\"" }, "]"]],
      ["46", ["    ", { kw: "if" }, " exp ", { acc: "<=" }, " now() - LEEWAY:"]],
      ["47", ["        raise Expired()"]],
    ],
    diff: [
      { k: "hunk", v: "@@ auth.py:42-50 @@" },
      { k: "add", v: "+     LEEWAY = timedelta(seconds=30)" },
      { k: "ctx", v: "      if exp <= now() - LEEWAY:" },
      { k: "ctx", v: "          raise Expired" },
    ],
  },
  {
    t: 60, d: 16, label: "Speech", file: "tests/test_auth.py",
    cap: "Added a regression test for the boundary — was the original bug.",
    code: [
      ["12", [{ kw: "def" }, " test_exp_at_boundary_with_leeway():"]],
      ["13", ["    token = make({", { str: "\"exp\"" }, ": now() - 5})"]],
      ["14", ["    ", { kw: "assert" }, " verify(token) ", { kw: "is None" }]],
      ["15", [""]],
      ["16", [{ kw: "def" }, " test_exp_past_leeway_window():"]],
      ["17", ["    token = make({", { str: "\"exp\"" }, ": now() - 60})"]],
      ["18", ["    ", { kw: "with" }, " raises(Expired):"]],
      ["19", ["        verify(token)"]],
    ],
    diff: [
      { k: "hunk", v: "@@ tests/test_auth.py +1,12 @@" },
      { k: "add", v: "+ def test_exp_at_boundary_with_leeway():" },
      { k: "add", v: "+     token = make({'exp': now() - 5})" },
      { k: "add", v: "+     assert verify(token) is None" },
    ],
  },
  {
    t: 76, d: 14, label: "Progress", file: "README.md",
    cap: "Documented the leeway choice so future readers don't ask again.",
    code: [
      ["88", ["### token expiry"]],
      ["89", [""]],
      ["90", ["verify() accepts a 30s leeway window to"]],
      ["91", ["account for clock skew between issuer and"]],
      ["92", ["verifier. Tokens within the window pass;"]],
      ["93", ["beyond it, Expired is raised."]],
      ["94", [""]],
      ["95", ["See rfc 7519 §4.1.4 for the spec basis."]],
    ],
    diff: [
      { k: "hunk", v: "@@ README.md +88,3 @@" },
      { k: "add", v: "+ ### token expiry" },
      { k: "add", v: "+ verify() accepts a 30s leeway window" },
    ],
  },
];

function renderCodeLine(parts) {
  return parts.map(function (p, i) {
    if (typeof p === "string") return p;
    if (p.kw) return React.createElement("span", { key: i, className: "kw" }, p.kw);
    if (p.str) return React.createElement("span", { key: i, className: "str" }, p.str);
    if (p.acc) return React.createElement("span", { key: i, className: "acc" }, p.acc);
    return null;
  });
}

var PR_QA = [
  { q: "why authlib instead of pyjwt?", a: "PyJWT's leeway parameter applied to the wrong side of the comparator — see clip ", clip: "[18:11-18:44]", a2: ". authlib's validators are explicit about the sign." },
  { q: "is 30s leeway safe?", a: "Yes — matches our prior implementation and rfc 7519 §4.1.4 (clip ", clip: "[26:07-26:52]", a2: "). Tests cover the boundary." },
];

var PR_DESC_BLOCKS = [
  { h: "## What", body: "Fix off-by-one in JWT expiry check. Switch from PyJWT to authlib for clearer leeway semantics. Add boundary regression test." },
  { h: "## Why", body: "The original 'if exp < now()' rejected tokens exactly at their stated expiry, breaking refresh flows that hit the boundary. PyJWT's leeway flag couldn't be applied in the needed direction." },
  { h: "## Struggles", body: "~6 min stuck on PyJWT leeway sign. Resolved by reading rfc 7519 §4.1.4 directly." },
  { h: "## Follow-ups", body: "• Audit other expiry checks for the same pattern\n• Centralize token validation" },
];

function findCurrentClip(clips, t) {
  var cur = clips[0];
  for (var i = 0; i < clips.length; i++) {
    if (clips[i].t <= t) cur = clips[i];
  }
  return cur;
}

function fmtTime(s) {
  var m = Math.floor(s / 60);
  var ss = Math.floor(s % 60);
  return (m < 10 ? "0" + m : "" + m) + ":" + (ss < 10 ? "0" + ss : "" + ss);
}

function PRWalkthrough() {
  var clips = PR_CLIPS;
  var total = clips[clips.length - 1].t + clips[clips.length - 1].d;

  var stateT = React.useState(0);
  var t = stateT[0];
  var setT = stateT[1];
  var statePlay = React.useState(true);
  var playing = statePlay[0];
  var setPlaying = statePlay[1];
  var railRef = React.useRef(null);

  React.useEffect(function () {
    if (!playing) return undefined;
    var id = setInterval(function () {
      setT(function (p) {
        var n = p + 0.2;
        return n >= total ? 0 : n;
      });
    }, 200);
    return function () { clearInterval(id); };
  }, [playing, total]);

  var cur = findCurrentClip(clips, t);

  function onScrub(e) {
    if (!railRef.current) return;
    var r = railRef.current.getBoundingClientRect();
    var x = e.clientX - r.left;
    if (x < 0) x = 0;
    if (x > r.width) x = r.width;
    setT((x / r.width) * total);
  }

  return (
    <section id="walkthrough" className="section">
      <div className="wrap">
        <div className="section-head">
          <div>
            <span className="section-tag">Your code, narrated</span>
            <h2 className="section-title">Your PR, narrated.</h2>
          </div>
          <p className="section-sub">
            Scrub the timeline. Each segment is a moment the timeline builder tagged from the session. The narration, diff, and badges swap as the playhead moves.
          </p>
        </div>

        <div className="pr-stage">
          <div className="pr-video crosshair">
            <div className="pr-title">
              <span className="tag">feat(auth):</span>
              fix JWT expiry boundary, swap pyjwt → authlib
            </div>
            <div className="pr-meta">
              <span className="green">+ 47</span>{"  "}
              <span className="red">− 18</span>{"  "}·{"  "}5 files{"  "}·{"  "}session 7a2f-…{"  "}·{"  "}
              <span className="acc">posted by @trace</span>
            </div>

            <div className="pr-stage-screen">
              <div className="pr-stage-fake-code">
                {cur.code && cur.code.map(function (row, i) {
                  return (
                    <div key={i}>
                      <span className="ln">{row[0]}</span>{renderCodeLine(row[1])}
                    </div>
                  );
                })}
              </div>
              <div className="pr-stage-overlay">
                <div className="pr-badges">
                  <span className="pr-badge">{cur.label}</span>
                  <span className="pr-badge dim">{cur.file}</span>
                </div>
                <div className="pr-caption">
                  <div className="pr-caption-text">{cur.cap}</div>
                </div>
              </div>
            </div>

            <div className="pr-timeline" ref={railRef} onClick={onScrub}>
              {clips.map(function (c, i) {
                var active = cur === c;
                return React.createElement("div", {
                  key: i,
                  className: "pr-timeline-seg " + (active ? "active" : ""),
                  style: {
                    left: ((c.t / total) * 100) + "%",
                    width: ((c.d / total) * 100) + "%",
                    pointerEvents: "none",
                  },
                }, c.label);
              })}
              <div className="pr-playhead" style={{ left: ((t / total) * 100) + "%", pointerEvents: "none" }} />
            </div>

            <div className="pr-controls">
              <button className="pr-play" onClick={function () { setPlaying(!playing); }}>
                {playing ? "❚❚" : "▶"}
              </button>
              <span>{fmtTime(t)} / {fmtTime(total)}</span>
              <span className="mute">·</span>
              <span>{cur.label.toLowerCase()} · {cur.file}</span>
            </div>
          </div>

          <div className="pr-side">
            <div className="card pr-side-card">
              <div className="pr-side-h">▸ Diff at playhead</div>
              <pre className="pr-diff">
                {cur.diff.map(function (d, i) {
                  return <div key={i} className={d.k}>{d.v}</div>;
                })}
              </pre>
            </div>

            <div className="card pr-side-card">
              <div className="pr-side-h">▸ @trace Q&amp;A in comments</div>
              {PR_QA.map(function (row, i) {
                return (
                  <div key={i} className="pr-qa-row">
                    <div className="pr-qa-q">{row.q}</div>
                    <div className="pr-qa-a">
                      {row.a}<span className="clip">{row.clip}</span>{row.a2}
                    </div>
                  </div>
                );
              })}
            </div>

            <div className="card pr-side-card">
              <div className="pr-side-h">▸ Auto-appended PR description</div>
              <div className="pr-desc">
                {PR_DESC_BLOCKS.map(function (b, i) {
                  return (
                    <div key={i} style={{ marginBottom: 10 }}>
                      <span className="h">{b.h}</span>
                      {"\n"}{b.body}
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
window.PRWalkthrough = PRWalkthrough;
