function Nav({ active }) {
  const items = [
    { href: "/#commands", label: "CLI" },
    { href: "/#examples", label: "Examples" },
    { href: "/#walkthrough", label: "Walkthrough" },
    { href: "/#install", label: "Install" },
    { href: "/docs", label: "Docs" },
  ];
  return (
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
          <a className="persist" href="https://github.com/crypticsaiyan/trace" target="_blank" rel="noreferrer">GitHub ↗</a>
        </div>
        <span className="nav-rev">v0.1 · videodb hackathon</span>
      </div>
    </nav>
  );
}
window.Nav = Nav;
