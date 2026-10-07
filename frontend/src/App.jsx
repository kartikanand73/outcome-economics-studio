import React, { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./lib/api.js";
import { setIn } from "./lib/state.js";
import Bounds from "./screens/Bounds.jsx";
import Catalog from "./screens/Catalog.jsx";
import Compare from "./screens/Compare.jsx";
import Costs from "./screens/Costs.jsx";
import Measure from "./screens/Measure.jsx";
import Models from "./screens/Models.jsx";
import Results from "./screens/Results.jsx";
import Routes from "./screens/Routes.jsx";
import Workload from "./screens/Workload.jsx";

const STEPS = [
  ["workload", "Workload"],
  ["routes", "Decision routes"],
  ["models", "Models"],
  ["bounds", "Context & bounds"],
  ["costs", "Human, tool & infra"],
  ["results", "Results"],
];
const STEP_CODES = {
  routes: ["route_share_total", "route_share_range", "review_range", "accuracy_range", "unknown_model"],
  workload: ["volume"],
};

export default function App() {
  const [list, setList] = useState([]);
  const [currentId, setCurrentId] = useState(null);
  const [draft, setDraft] = useState(null);
  const [savedSnap, setSavedSnap] = useState("");
  const [results, setResults] = useState(null);
  const [calcError, setCalcError] = useState("");
  const [mode, setMode] = useState("estimate");
  const [step, setStep] = useState("results");
  const [toastMsg, setToastMsg] = useState("");
  const importRef = useRef(null);

  const toast = useCallback((m) => { setToastMsg(m); setTimeout(() => setToastMsg(""), 4200); }, []);
  const refresh = useCallback(async () => { const l = await api.list(); setList(l); return l; }, []);

  const open = useCallback(async (id) => {
    const sc = await api.get(id);
    setCurrentId(id); setDraft(sc); setSavedSnap(JSON.stringify(sc)); setResults(null); setMode("estimate");
  }, []);

  useEffect(() => {
    refresh().then((l) => {
      const first = l.find((s) => s.id === "sample-outcome-aware-router") || l[0];
      if (first) open(first.id);
    }).catch((e) => setCalcError(`Cannot reach the API: ${e.message}`));
  }, []);

  // Live recalculation of the unsaved draft (debounced).
  useEffect(() => {
    if (!draft) return;
    const h = setTimeout(() => {
      api.calculate(draft).then((r) => { setResults(r); setCalcError(""); }).catch((e) => setCalcError(e.message));
    }, 250);
    return () => clearTimeout(h);
  }, [draft]);

  const update = useCallback((path, value) => setDraft((d) => setIn(d, path, value)), []);
  const dirty = draft && JSON.stringify(draft) !== savedSnap;

  const save = async () => {
    const sc = currentId ? await api.update(currentId, draft) : await api.create(draft);
    setCurrentId(sc.id); setDraft(sc); setSavedSnap(JSON.stringify(sc));
    await refresh(); toast("Scenario saved.");
  };
  const clone = async (id = currentId) => {
    const src = list.find((s) => s.id === id);
    const name = window.prompt("Name for the cloned scenario", `${src?.name ?? "Scenario"} (copy)`);
    if (name === null) return;
    const sc = await api.clone(id, name);
    await refresh(); await open(sc.id); setStep("routes");
    toast("Cloned. Change its architecture, then compare.");
  };
  const newScenario = async () => {
    const tpl = await api.template();
    const sc = await api.create(tpl);
    await refresh(); await open(sc.id); setStep("workload");
  };
  const remove = async () => {
    if (!window.confirm(`Delete "${draft.name}"? This cannot be undone.`)) return;
    await api.remove(currentId);
    const l = await refresh();
    if (l[0]) open(l[0].id); else { setDraft(null); setCurrentId(null); }
  };
  const importScenario = async (f) => {
    if (!f) return;
    try { const sc = await api.importScenario(f); await refresh(); await open(sc.id); toast("Scenario imported."); }
    catch (e) { toast(`Import failed: ${e.message}`); }
  };
  const resetSamples = async () => {
    if (!window.confirm("Restore the sample scenarios to their original values?")) return;
    await api.resetSamples(); await refresh(); if (currentId?.startsWith("sample-")) open(currentId);
    toast("Samples restored.");
  };

  const errCodes = new Set((results?.issues || []).filter((i) => i.severity === "error").map((i) => i.code));
  const exportActions = currentId && (
    <div className="row">
      {dirty && <span className="small muted">Save to export current edits</span>}
      <a className="btn small" href={`/api/scenarios/${currentId}/export.json`} aria-disabled={dirty}>Scenario JSON</a>
      <a className="btn small" href={`/api/scenarios/${currentId}/results.csv`}>Results CSV</a>
      <a className="btn small" href={`/api/scenarios/${currentId}/report`} target="_blank" rel="noreferrer">Printable report</a>
    </div>
  );
  const samples = list.filter((s) => s.is_sample);
  const mine = list.filter((s) => !s.is_sample);

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <h1>Outcome Economics Studio</h1>
          <p>Do not spend more intelligence than the decision requires.</p>
        </div>
        <div className="side-actions">
          <button className="btn small primary" onClick={newScenario}>+ New scenario</button>
          <button className="btn small" onClick={() => importRef.current?.click()}>Import scenario</button>
          <input ref={importRef} type="file" accept=".json" hidden onChange={(e) => { importScenario(e.target.files?.[0]); e.target.value = ""; }} />
        </div>
        <div className="side-group">
          <h4>My scenarios</h4>
          {mine.length === 0 && <p className="small muted" style={{ margin: "0 8px" }}>Clone a sample or create a new scenario.</p>}
          {mine.map((s) => (
            <button key={s.id} className={`side-item ${s.id === currentId && mode === "estimate" ? "active" : ""}`} onClick={() => open(s.id)}>
              {s.name}<small>{s.business_process || "—"}{s.has_benchmark ? " · benchmark" : ""}</small>
            </button>
          ))}
        </div>
        <div className="side-group">
          <h4>Sample data</h4>
          {samples.map((s) => (
            <button key={s.id} className={`side-item ${s.id === currentId && mode === "estimate" ? "active" : ""}`} onClick={() => open(s.id)}>
              {s.name}<small>{s.has_benchmark ? "Jev benchmark sample" : "Illustrative assumptions"}</small>
            </button>
          ))}
          <button className="btn small ghost" onClick={resetSamples}>Restore samples</button>
        </div>
      </aside>

      <main className="main">
        <div className="topbar">
          <div className="modes">
            {[["estimate", "Estimate"], ["measure", "Measure"], ["compare", "Compare"], ["catalog", "Model catalog"]].map(([k, l]) => (
              <button key={k} className={mode === k ? "active" : ""} onClick={() => setMode(k)}>{l}</button>
            ))}
          </div>
          {mode === "estimate" && draft && (
            <>
              <h2>{draft.name}</h2>
              {draft.is_sample && <span className="ev ev-assumption">Sample</span>}
              <div className="spacer" />
              {dirty && <span className="small muted">Unsaved changes · results update live</span>}
              <button className="btn primary" disabled={!dirty} onClick={save}>Save</button>
              <button className="btn" onClick={() => clone()}>Clone</button>
              {!draft.is_sample && <button className="btn ghost danger" onClick={remove}>Delete</button>}
            </>
          )}
        </div>
        {calcError && <div className="issue error"><span className="tag">Error</span><span>{calcError}</span></div>}

        {mode === "estimate" && draft && (
          <>
            <nav className="steps">
              {STEPS.map(([k, l], i) => (
                <button key={k} className={step === k ? "active" : ""} onClick={() => setStep(k)}>
                  <span className="num">{k === "results" ? "=" : i + 1}</span>{l}
                  {(STEP_CODES[k] || []).some((c) => errCodes.has(c)) && <span className="dot-err" title="Has errors" />}
                </button>
              ))}
            </nav>
            {step === "workload" && <Workload draft={draft} update={update} />}
            {step === "routes" && <Routes draft={draft} update={update} results={results} />}
            {step === "models" && <Models draft={draft} update={update} onOpenCatalog={() => setMode("catalog")} onOpenRoutes={() => setStep("routes")} />}
            {step === "bounds" && <Bounds draft={draft} update={update} results={results} />}
            {step === "costs" && <Costs draft={draft} update={update} results={results} onOpenRoutes={() => setStep("routes")} />}
            {step === "results" && <Results results={results} draft={draft} onExport={exportActions} />}
          </>
        )}
        {mode === "measure" && (
          <Measure scenarios={list} currentId={currentId} toast={toast}
            onImported={async (sc, notes) => {
              await refresh(); await open(sc.id); setStep("results");
              if (notes?.length) toast(notes.join(" "));
            }} />
        )}
        {mode === "compare" && list.length > 0 && <Compare scenarios={list} onClone={clone} />}
        {mode === "catalog" && <Catalog toast={toast} />}
      </main>
      {toastMsg && <div className="toast">{toastMsg}</div>}
    </div>
  );
}
