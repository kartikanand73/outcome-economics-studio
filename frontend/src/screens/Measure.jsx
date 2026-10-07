import React, { useState } from "react";
import { Card, EvidenceBadge, Toggle } from "../components/ui.jsx";
import { api } from "../lib/api.js";
import { num } from "../lib/format.js";

export default function Measure({ scenarios, currentId, onImported, toast }) {
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState("");
  const [target, setTarget] = useState(currentId || "");
  const [apply, setApply] = useState(false);
  const [busy, setBusy] = useState(false);

  const choose = async (f) => {
    setFile(f); setPreview(null); setError("");
    if (!f) return;
    try { setPreview(await api.preview(f)); } catch (e) { setError(e.message); }
  };
  const doImport = async () => {
    setBusy(true); setError("");
    try {
      const r = await api.importInto(target, file, apply);
      toast(`Imported "${r.import.benchmark.name}"${apply ? " and applied measured values to inputs" : ""}.`);
      onImported(r.scenario, r.notes);
    } catch (e) { setError(e.message); }
    setBusy(false);
  };
  const bm = preview?.benchmark;
  return (
    <>
      <Card title="Measure: import benchmark results"
        subtitle="Import measured results as JSON or CSV. The benchmark is stored frozen alongside the scenario and compared with the scenario's projection.">
        <div className="dropzone">
          <input type="file" accept=".json,.csv" onChange={(e) => choose(e.target.files?.[0] || null)} />
          <p className="small muted" style={{ marginBottom: 0 }}>
            Benchmark JSON · metrics CSV (<code>metric,value,unit,evidence,note</code>) · decision-level CSV
            (<code>route_id,correct,latency_ms,human_reviewed,larger_model_called,outcome_changed,…</code>).
            Examples are in <code>samples/</code>; the schema is documented in <code>docs/import-schema.md</code>.
          </p>
        </div>
        {error && <div className="issue error" style={{ marginTop: 10 }}><span className="tag">Import error</span><span>{error}</span></div>}
      </Card>
      {bm && (
        <Card title={`Preview: ${bm.name}`} subtitle={`${preview.kind.replace("_", " ")} · ${bm.decisions ? `${bm.decisions} decisions` : "decision count not given"}${bm.source ? ` · ${bm.source}` : ""}`}>
          <table className="data">
            <thead><tr><th>Metric</th><th className="n">Value</th><th>Unit</th><th>Evidence</th></tr></thead>
            <tbody>
              {Object.entries(bm.metrics).map(([k, m]) => (
                <tr key={k}><td>{k}</td><td className="n">{num(m.value, 4)}</td><td>{m.unit}</td><td><EvidenceBadge value={m.evidence} /></td></tr>
              ))}
            </tbody>
          </table>
          {Object.keys(preview.route_updates).length > 0 && (
            <>
              <div className="section-title">Measured route statistics</div>
              <table className="data">
                <thead><tr><th>Route id</th><th>Measured values</th></tr></thead>
                <tbody>{Object.entries(preview.route_updates).map(([rid, u]) => (
                  <tr key={rid}><td>{rid}</td><td className="small">{Object.entries(u).map(([k, v]) => `${k} = ${num(v, 4)}`).join(" · ")}</td></tr>
                ))}</tbody>
              </table>
            </>
          )}
          {bm.segments?.length > 0 && <p className="small">Segments: {bm.segments.map((s) => `${s.name} (${num(s.accuracy_pct)}%)`).join(" · ")}</p>}
          {preview.warnings.map((w, i) => <div key={i} className="issue warning"><span className="tag">Note</span><span>{w}</span></div>)}
          <div className="row" style={{ marginTop: 12, gap: 14 }}>
            <label className="field" style={{ minWidth: 260 }}>
              <span className="field-label"><span>Attach to scenario</span></span>
              <select value={target} onChange={(e) => setTarget(e.target.value)}>
                <option value="">Choose…</option>
                {scenarios.map((s) => <option key={s.id} value={s.id}>{s.name}{s.is_sample ? " (sample)" : ""}</option>)}
              </select>
            </label>
            <Toggle label="Also write measured route/model values into the scenario inputs (labelled Measured)"
              value={apply} onChange={setApply} />
            <button className="btn primary" disabled={!target || busy} onClick={doImport}>{busy ? "Importing…" : "Import"}</button>
          </div>
          <p className="small muted" style={{ marginBottom: 0 }}>
            The measured benchmark replaces any previous benchmark on that scenario and is never rewritten by later edits.
            Route ids in the file must match the scenario's route ids when applying values to inputs.
          </p>
        </Card>
      )}
    </>
  );
}
