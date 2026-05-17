function Nav({ active }) {
  const items = [
    { href: "/#commands", label: "CLI" },
    { href: "/#walkthrough", label: "Walkthrough" },
    { href: "/#install", label: "Install" },
    { href: "/#api", label: "VideoDB map" },
    { href: "/docs", label: "Docs" },
  ];

  const [open, setOpen] = React.useState(false);

  return (
    <>
      <nav className="nav">
        <div className="nav-inner">
          <a className="nav-brand" href="/">
            <img src="/static/logo.png" alt="trace" className="nav-logo" />
          </a>
          <div className="nav-links">
            {items.map((it) => (
              <a
                key={it.href}
                href={it.href}
                className={active === it.label ? "on" : ""}
              >
                {it.label}
              </a>
            ))}
            <a className="persist" href="https://github.com" target="_blank" rel="noreferrer">GitHub ↗</a>
          </div>
          <span className="nav-rev">v0.1 · videodb hackathon</span>
          <button
            className="nav-hamburger"
            aria-label="Toggle menu"
            aria-expanded={open}
            onClick={() => setOpen(!open)}
          >
            {open ? "✕" : "☰"}
          </button>
        </div>
        <div className={"nav-drawer" + (open ? " open" : "")} role="menu">
          {items.map((it) => (
            <a
              key={it.href}
              href={it.href}
              className={active === it.label ? "on" : ""}
              onClick={() => setOpen(false)}
            >
              {it.label}
            </a>
          ))}
          <a href="https://github.com" target="_blank" rel="noreferrer" onClick={() => setOpen(false)}>
            GitHub ↗
          </a>
        </div>
      </nav>
    </>
  );
}
window.Nav = Nav;
