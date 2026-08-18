function App() {
  return (
    <>
      <div className="grid-bg" />
      <div className="page">
        <Nav active="" />
        <Hero />
        <Handoff />
        <PreparedExamples />
        <Commands />
        <PRWalkthrough />
        <Features />
        <Install />
        <Footer />
      </div>
    </>
  );
}

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(<App />);
