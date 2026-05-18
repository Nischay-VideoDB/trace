function App() {
  return (
    <>
      <div className="grid-bg" />
      <div className="page">
        <Nav active="" />
        <Hero />
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
