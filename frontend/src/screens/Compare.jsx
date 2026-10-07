import React, { useEffect, useState } from "react";
import { ScenarioBars, StackedBreakdown } from "../components/charts.jsx";
import { Card, Issues } from "../components/ui.jsx";
import { api } from "../lib/api.js";
import { catColor, useChartTheme } from "../lib/colors.js";
import { CATEGORY_LABELS, fmtValue, num } from "../lib/format.js";

const DEFAULT = ["sample-sol-only", "sample-confidence-cascade", "sample-outcome-aware-router"];
const BREAKDOWN_KEYS = ["lightweight_model", "larger_model", "human_review", "tool_api", "evaluation", "other_variable", "infrastructure"];

export default function Compare({ scenarios, onClone }) {
  const t = useChartTheme();
  const [ids, setIds] = useState(() => DEFAULT.filter((d) => scenarios.some((s) => s.id === d)));
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!ids.length) { setData(null); return; }
    api.compare(ids).then((d) => { setData(d); setError(""); }).catch((e) => setError(e.message));
  }, [ids, scenarios]);

  const toggle = (id) => setIds((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]));
  const makeBaseline = (id) => setIds((cur) => [id, ...cur.filter((x) => x !== id)]);
  const cur = data?.currency || "USD";
  const bars = (key) => (data?.charts || []).map((c) => ({ name: c.name, value: Number(c[key]) }));
  const stacked = (data?.charts || []).map((c) => {
    const b = c.breakdown_monthly;
    return {
      name: c.name,
      ...Object.fromEntries(BREAKDOWN_KEYS.filter((k) => k !== "infrastructure").map((k) => [k, Number(b[k])])),
      infrastructure: Number(b.fixed_infrastructure) + Number(b.fixed_observability) + Number(b.fixed_other_fixed),
    };
  });

  return (
    <>
      <Card title="Compare architectures" subtitle="Pick scenarios; the first is the baseline for deltas. Clone a scenario to change its architecture.">
        <div className="row" style={{ gap: 6 }}>
          {scenarios.map((s) => (
            <span key={s.id} className="row" style={{ gap: 2 }}>
              <button className={`btn small ${ids.includes(s.id) ? "primary" : ""}`} onClick={() => toggle(s.id)}>
                {ids.indexOf(s.id) === 0 ? "★ " : ""}{s.name}
              </button>
            </span>
          ))}
        </div>
        {ids.length > 1 && (
          <div className="row small muted" style={{ marginTop: 8 }}>
            Baseline:
            <select className="btn small" value={ids[0]} onChange={(e) => makeBaseline(e.target.value)}>
              {ids.map((id) => <option key={id} value={id}>{scenarios.find((s) => s.id === id)?.name}</option>)}
            </select>
            <span className="spacer" />
            {ids.map((id) => <button key={id} className="btn small ghost" onClick={() => onClone(id)}>Clone “{scenarios.find((s) => s.id === id)?.name}”</button>)}
          </div>
        )}
        {error && <div className="issue error"><span className="tag">Error</span><span>{error}</span></div>}
      </Card>
      {data && (
        <>
          {data.scenarios.filter((s) => !s.ok).map((s) => (
            <Card key={s.id} title={`${s.name} has validation errors`}><Issues issues={s.issues} filter={(i) => i.severity === "error"} /></Card>
          ))}
          <Card title="Side by side" subtitle={`Deltas vs. ${data.baseline}. Green = better, red = worse.`}>
            <div style={{ overflowX: "auto" }}>
              <table className="data">
                <thead><tr><th>Metric</th>{data.scenarios.map((s, i) => <th key={s.id} className="n">{i === 0 ? "★ " : ""}{s.name}{s.is_sample ? " (sample)" : ""}</th>)}</tr></thead>
                <tbody>
                  {data.rows.map((row) => (
                    <tr key={row.key}>
                      <td>{row.label}</td>
                      {row.cells.map((c, i) => (
                        <td key={i} className="n">
                          {c.error ? <span className="worse">error</span> : c.unbounded ? <span className="unb">Unbounded</span>
                            : c.value == null ? <span className="muted">Not measured</span> : fmtValue(c.value, row.kind, cur)}
                          {i > 0 && c.delta_pct != null && Math.abs(Number(c.delta_pct)) >= 0.05 && (
                            <div className={`small ${c.better ? "better" : "worse"}`}>{Number(c.delta_pct) > 0 ? "+" : ""}{num(c.delta_pct, 1)}%</div>
                          )}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <div className="grid two" style={{ marginTop: 12 }}>
            <Card title="Model cost per 1,000 decisions"><ScenarioBars data={bars("model_cost_per_1000")} cur={cur} kind="unit_money" /></Card>
            <Card title="Expected cost per task (fully loaded)"><ScenarioBars data={bars("expected_cost_per_task")} cur={cur} kind="unit_money" /></Card>
            <Card title="Expected accuracy"><ScenarioBars data={bars("accuracy_pct")} cur={cur} kind="pct" /></Card>
            <Card title="Maximum bounded cost per task"
              subtitle={data.charts.some((c) => c.max_unbounded) ? "Unbounded scenarios are omitted — they have no maximum" : ""}>
              <ScenarioBars data={data.charts.filter((c) => !c.max_unbounded).map((c) => ({ name: c.name, value: Number(c.max_cost_per_task) }))} cur={cur} kind="unit_money" />
            </Card>
          </div>
          <Card title="Monthly cost by category">
            <StackedBreakdown data={stacked} keys={BREAKDOWN_KEYS} cur={cur} labels={CATEGORY_LABELS} colorFor={(k) => catColor(t, k)} />
            <div className="legend">{BREAKDOWN_KEYS.map((k) => <span key={k}><span className="swatch" style={{ background: catColor(t, k) }} />{CATEGORY_LABELS[k]}</span>)}</div>
          </Card>
        </>
      )}
    </>
  );
}
