import React, { useState } from "react";
import { HBars, VolumeLine } from "../components/charts.jsx";
import { Card, EvidenceBadge, Issues, Stat } from "../components/ui.jsx";
import { catColor, useChartTheme } from "../lib/colors.js";
import { CATEGORY_LABELS, EVIDENCE, fmt, fmtValue, num } from "../lib/format.js";

const SAFETY_ROWS = [
  ["fraud_auto_approved", "Fraud auto-approved"],
  ["critical_false_approvals", "Critical false approvals"],
  ["incorrect_auto_rejections", "Incorrect automatic rejections"],
  ["unnecessary_human_reviews", "Unnecessary human reviews"],
  ["policy_override_rate", "Policy override rate (of reviews)"],
];

function EvidenceBasis({ basis }) {
  const parts = Object.entries(basis.counts).filter(([, v]) => v > 0);
  return (
    <div className="row small muted" style={{ marginBottom: 12 }}>
      <span>Key inputs:</span>
      {parts.map(([k, v]) => <span key={k}><EvidenceBadge value={k} /> {v}</span>)}
      {basis.mainly_assumptions && <b style={{ color: "var(--warn)" }}>Estimate based mainly on assumptions</b>}
    </div>
  );
}

function Question({ results, draft }) {
  const dv = results.decision_value;
  const applies = draft.routes.filter((r) => dv.routes[r.id]?.applies);
  return (
    <div className="question">
      <div className="q">{dv.question}</div>
      {applies.length ? (
        <div className="answers">
          {applies.map((r) => {
            const a = dv.routes[r.id];
            return (
              <div key={r.id} className={`answer ${a.answer}`}>
                <b>{a.answer === "yes" ? "Yes" : a.answer === "no" ? "No" : "Unknown"}</b>
                <span className="muted">{r.name}:</span> {a.detail}
              </div>
            );
          })}
        </div>
      ) : <div className="small muted" style={{ marginTop: 6 }}>No route calls a larger model.</div>}
    </div>
  );
}

function MaxDetail({ route, cur }) {
  const mx = route.max;
  if (!mx) return <span className="muted">Unreachable (0% share)</span>;
  return (
    <div>
      <table className="data">
        <thead><tr><th>Stage</th><th className="n">Max input ctx</th><th className="n">Max tokens/call</th>
          <th className="n">Max attempts</th><th className="n">Max tokens</th><th className="n">Model</th><th className="n">Tools</th><th className="n">Sub-agents</th></tr></thead>
        <tbody>
          {mx.stages.map((s, i) => (
            <tr key={i}>
              <td>{s.model}</td>
              {["max_input_context", "max_tokens_per_call", "max_attempts", "max_tokens"].map((k) => (
                <td key={k} className={`n ${s[k].unbounded ? "unb" : ""}`}>{fmt(s[k])}</td>
              ))}
              {["model_cost", "tool_cost", "subagent_cost"].map((k) => (
                <td key={k} className={`n ${s[k].unbounded ? "unb" : ""}`}>{fmt(s[k], cur)}</td>
              ))}
            </tr>
          ))}
          <tr className="total">
            <td colSpan={5}>Automated (budget-constrainable) · Non-automated (review, eval, other)</td>
            <td className="n" colSpan={3}>{fmt(mx.automated, cur)} · {fmt(mx.non_automated, cur)}</td>
          </tr>
        </tbody>
      </table>
      {mx.calculated.unbounded && <div className="issue error"><span className="tag">Unbounded</span><span>{mx.calculated.reasons.join("; ")}</span></div>}
      {mx.notes.length > 0 && <ul className="small muted" style={{ margin: "6px 0 0", paddingLeft: 18 }}>{mx.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
    </div>
  );
}

function RouteTable({ results, cur }) {
  const [open, setOpen] = useState(null);
  const t = useChartTheme();
  return (
    <table className="data">
      <thead>
        <tr><th>Route</th><th className="n">Share</th><th className="n">Review</th><th className="n">Expected cost</th>
          <th className="n">Contribution</th><th className="n">Max (calculated)</th><th className="n">Max (effective)</th>
          <th className="n">Accuracy</th><th className="n">P50 / P95</th><th /></tr>
      </thead>
      <tbody>
        {results.routes.map((r, i) => (
          <React.Fragment key={r.id}>
            <tr>
              <td><span className="swatch" style={{ background: t.series[i % 8] }} />{r.name}</td>
              <td className="n">{num(r.share_pct, 2)}%</td>
              <td className="n">{num(r.review_pct, 1)}%{r.direct_human ? " (human)" : r.human_review_mandatory ? " (mand.)" : ""}</td>
              <td className="n">{fmt(r.expected_cost, cur)}</td>
              <td className="n">{fmt(r.contribution, cur)}</td>
              <td className={`n ${r.max?.calculated.unbounded ? "unb" : ""}`}>{r.max ? fmt(r.max.calculated, cur) : "—"}</td>
              <td className={`n ${r.max?.effective.unbounded ? "unb" : ""}`}>{r.max ? fmt(r.max.effective, cur) : "—"}</td>
              <td className="n">{fmt(r.accuracy_pct)} <EvidenceBadge value={r.accuracy_pct.evidence} /></td>
              <td className="n">{r.p50_latency_ms ? `${fmt(r.p50_latency_ms)} / ${fmt(r.p95_latency_ms)}` : "human"}</td>
              <td><button className="btn small ghost" onClick={() => setOpen(open === r.id ? null : r.id)}>{open === r.id ? "Hide" : "Bounds"}</button></td>
            </tr>
            {open === r.id && <tr><td colSpan={10} style={{ background: "var(--surface)" }}><MaxDetail route={r} cur={cur} /></td></tr>}
          </React.Fragment>
        ))}
      </tbody>
    </table>
  );
}

function BenchmarkPanel({ bm, cur }) {
  const unitFmt = (v, unit) => {
    if (v == null) return "—";
    if (unit === "currency" || unit === "USD" || unit === cur) return fmtValue(v, "unit_money", cur);
    if (unit === "%") return fmtValue(v, "pct");
    if (unit === "ms") return fmtValue(v, "ms");
    return num(v, 2);
  };
  return (
    <Card title="Measured benchmark vs. current projection"
      subtitle={`${bm.name} — ${bm.source}${bm.decisions ? ` · ${bm.decisions.toLocaleString()} decisions` : ""}. The measured result is frozen; the projection recalculates from your editable inputs.`}>
      {bm.is_sample && <div className="banner">Sample benchmark data — replace with your own via Measure.</div>}
      <table className="data">
        <thead><tr><th>Metric</th><th className="n">Original measured</th><th className="n">Current projection</th><th className="n">Difference</th><th>Evidence source</th></tr></thead>
        <tbody>
          {bm.rows.map((r) => (
            <tr key={r.key}>
              <td>{r.label}</td>
              <td className="n">{unitFmt(r.measured.value, r.unit)} <EvidenceBadge value={r.measured.evidence} /></td>
              <td className="n">{r.projected.value != null ? <>{unitFmt(r.projected.value, r.unit)} <EvidenceBadge value="derived" /></> : <span className="muted small">{r.projected.note || "—"}</span>}</td>
              <td className={`n ${r.difference_pct != null && Math.abs(Number(r.difference_pct)) > 10 ? "worse" : ""}`}>
                {r.difference_pct != null ? (Math.abs(Number(r.difference_pct)) < 0.05 ? "0%" : `${Number(r.difference_pct) > 0 ? "+" : ""}${num(r.difference_pct, 1)}%`) : r.difference != null ? num(r.difference, 4) : "—"}
              </td>
              <td className="small muted">{r.measured.note || (r.measured.raw !== r.measured.value && r.measured.raw != null ? `raw ${num(r.measured.raw)} over ${bm.decisions}` : "Benchmark")}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {bm.segments?.length > 0 && (
        <>
          <div className="section-title">Segment-level accuracy</div>
          <table className="data"><thead><tr><th>Segment</th><th className="n">Decisions</th><th className="n">Accuracy</th></tr></thead>
            <tbody>{bm.segments.map((s) => <tr key={s.name}><td>{s.name}</td><td className="n">{num(s.decisions)}</td><td className="n">{s.accuracy_pct != null ? `${num(s.accuracy_pct)}%` : "—"} <EvidenceBadge value={s.evidence} /></td></tr>)}</tbody>
          </table>
        </>
      )}
    </Card>
  );
}

export default function Results({ results, draft, onExport }) {
  const t = useChartTheme();
  if (!results) return <div className="empty">Calculating…</div>;
  if (!results.ok) {
    return (
      <Card title="Fix these issues to see results">
        <Issues issues={results.issues} filter={(i) => i.severity === "error"} />
      </Card>
    );
  }
  const cur = results.currency;
  const s = results.summary;
  const dv = results.decision_value;
  const b = results.budget.cost;
  const catData = results.charts.cost_by_category_monthly.map((c) => {
    const key = c.category.startsWith("infrastructure") ? "infrastructure" : c.category;
    return { label: CATEGORY_LABELS[key] || c.category, value: Number(c.value), color: catColor(t, key), kind: "money" };
  }).filter((c) => c.value > 0).sort((a, b) => b.value - a.value);
  const routeData = results.charts.cost_by_route.map((r, i) => ({ label: r.route, value: Number(r.contribution), color: t.series[i % 8], kind: "unit_money" }));
  const ev = results.charts.expected_vs_max;
  const evData = [{ label: "Expected / task", value: Number(ev.expected), color: t.series[0], kind: "unit_money" }];
  if (!ev.max_unbounded) evData.push({ label: "Bounded maximum / task", value: Number(ev.max), color: t.series[6], kind: "unit_money" });
  const mvh = results.charts.model_vs_human_monthly;
  const mvhData = [
    { label: "Model spend", value: Number(mvh.model), color: t.series[0], kind: "money" },
    { label: "Human-review spend", value: Number(mvh.human), color: catColor(t, "human_review"), kind: "money" },
  ];
  const volData = results.charts.monthly_by_volume.map((v) => ({ label: `${Number(v.multiplier)}×`, monthly: Number(v.monthly_cost), tasks: Number(v.tasks) }));
  const safetyAlert = s.safety_failures_monthly.value != null && Number(s.safety_failures_monthly.value) > 0;
  const perTaskCats = Object.entries(results.breakdown_per_task);

  return (
    <>
      {(draft.is_sample || draft.benchmark?.is_sample) && <div className="banner"><b>Sample data.</b> {draft.sample_note || "This scenario uses sample benchmark data."}</div>}
      <div className="row no-print" style={{ marginBottom: 10 }}>
        <EvidenceBasis basis={results.evidence_basis} />
        <div className="spacer" />
        {onExport}
      </div>
      <Question results={results} draft={draft} />

      <div className="stats">
        <Stat hero label="Cost per correct governed task" metric={s.cost_per_correct_task} cur={cur}
          sub={`${fmt(s.correct_outcomes_monthly)} correct outcomes / month`} />
        <Stat label="Expected cost per task" metric={s.expected_cost_per_task} cur={cur}
          sub={`${fmt(s.variable_cost_per_task, cur)} variable + ${fmt(s.allocated_fixed_per_task, cur)} allocated`} />
        <Stat label="Maximum bounded cost per task" metric={s.max_cost_per_task} cur={cur} alert={s.max_cost_per_task.unbounded}
          sub={s.max_cost_per_task.unbounded ? s.max_cost_per_task.reasons[0] : `Worst route: ${s.worst_route}${b.is_hard_bound ? " · budget hard-bounded" : ""}`} />
        <Stat label="Daily cost (variable)" metric={s.daily_cost} cur={cur} />
        <Stat label="Monthly cost" metric={s.monthly_cost} cur={cur} sub={`${fmt(s.monthly_tasks)} tasks`} />
        <Stat label="Annual cost" metric={s.annual_cost} cur={cur} sub={s.annual_cost.note} />
        <Stat label="Expected tokens per task" metric={s.expected_tokens_per_task} />
        <Stat label="Maximum tokens per task" metric={s.max_tokens_per_task} alert={s.max_tokens_per_task.unbounded} />
        <Stat label="Larger-model calls / month" metric={s.larger_calls_monthly}
          sub={`${fmt(dv.larger_escalation_rate_pct)} of tasks escalate`} />
        <Stat label="Larger-model calls avoided / month" metric={s.larger_calls_avoided_monthly}
          sub={`${fmt(s.model_free_decisions_monthly)} decisions need no model`} />
        <Stat label="Human reviews / month" metric={s.human_reviews_monthly} sub={`${fmt(s.human_review_share_pct)} of tasks`} />
        <Stat label="Median / P95 latency" metric={s.p50_latency_ms}
          sub={s.meets_latency === false ? "Median exceeds the latency target" : "Automated decisions; review turnaround excluded"}>
          {fmt(s.p50_latency_ms)} / {fmt(s.p95_latency_ms)}
        </Stat>
        <Stat label="Expected accuracy" metric={s.expected_accuracy_pct} okFlag={s.meets_target_accuracy}
          sub={`${s.meets_target_accuracy ? "Meets" : "Below"} target ${fmt(s.target_accuracy_pct)}`} />
        <Stat label="Safety failures / month" metric={s.safety_failures_monthly} alert={safetyAlert} sub={s.safety_failures_monthly.note} />
      </div>

      <div className="grid two" style={{ marginTop: 12 }}>
        <Card title="Cost by category" subtitle="Monthly">
          <HBars data={catData} cur={cur} kind="money" valueName="Monthly" />
          <table className="data" style={{ marginTop: 8 }}>
            <thead><tr><th>Category</th><th className="n">Per task</th><th className="n">Monthly</th></tr></thead>
            <tbody>{perTaskCats.map(([k, m]) => (
              <tr key={k}><td><span className="swatch" style={{ background: catColor(t, k) }} />{CATEGORY_LABELS[k] || k}</td>
                <td className="n">{fmt(m, cur)}</td>
                <td className="n">{k === "infrastructure"
                  ? fmtValue(["fixed_infrastructure", "fixed_observability", "fixed_other_fixed"].reduce((a, x) => a + Number(results.breakdown_monthly[x].value), 0), "money", cur)
                  : fmt(results.breakdown_monthly[k], cur)}</td></tr>))}</tbody>
          </table>
        </Card>
        <Card title="Cost by route" subtitle="Contribution to expected cost per task (share × route cost)">
          <HBars data={routeData} cur={cur} kind="unit_money" valueName="Contribution" />
        </Card>
        <Card title="Expected vs. bounded maximum" subtitle="Per task, including allocated fixed cost">
          {ev.max_unbounded
            ? <><HBars data={evData} cur={cur} kind="unit_money" /><div className="issue error"><span className="tag">No maximum</span><span>The workflow is unbounded, so no maximum is shown: {s.max_cost_per_task.reasons.join("; ")}</span></div></>
            : <HBars data={evData} cur={cur} kind="unit_money" />}
        </Card>
        <Card title="Model cost vs. human cost" subtitle="Monthly">
          <HBars data={mvhData} cur={cur} kind="money" />
          <div className="chart-note">Human review costs {Number(mvh.model) > 0 ? `${num(Number(mvh.human) / Number(mvh.model), 0)}×` : "—"} the model spend.</div>
        </Card>
      </div>
      <Card title="Monthly cost by volume" subtitle="Variable cost scales with volume; fixed cost does not">
        <VolumeLine data={volData} cur={cur} />
      </Card>

      <div className="grid two" style={{ marginTop: 12 }}>
        <Card title="Decision value" subtitle="Separates spend that can change a decision from spend that only adds tokens, latency and cost">
          <table className="data"><tbody>
            <tr><td>Larger-model escalation rate</td><td className="n">{fmt(dv.larger_escalation_rate_pct)}</td></tr>
            <tr><td>Larger-model calls that changed the useful outcome</td><td className="n">{fmt(dv.changed_outcome_pct)}</td></tr>
            <tr><td>Cost per changed decision</td><td className="n">{fmt(dv.cost_per_changed_decision, cur)}</td></tr>
            <tr><td>Tokens spent on unchanged decisions / month</td><td className="n">{fmt(dv.tokens_on_unchanged_monthly)}</td></tr>
            <tr><td>Avoidable model spend / month</td><td className="n">{fmt(dv.avoidable_model_spend_monthly, cur)}</td></tr>
            <tr><td>Tasks sent to a model although review was mandatory / month</td><td className="n">{fmt(dv.mandatory_review_model_tasks_monthly)} ({fmt(dv.mandatory_review_model_spend_monthly, cur)})</td></tr>
            <tr><td>Larger-model calls avoided per task (vs. one per eligible task)</td><td className="n">{fmt(dv.larger_calls_avoided_per_task)}</td></tr>
            <tr><td>Human reviews prevented / month</td><td className="n">{fmt(dv.human_reviews_prevented_monthly, cur, { emptyLabel: "Set baseline" })}{dv.human_reviews_prevented_monthly.value != null && <span className="small muted"> · {dv.human_reviews_prevented_safe ? "safely" : "safety not established"}</span>}</td></tr>
          </tbody></table>
          {dv.changed_outcome_pct.value == null && <p className="small muted" style={{ marginBottom: 0 }}>Record how often the larger model changes the governed outcome on each escalating route to price its value.</p>}
        </Card>
        <Card title="Accuracy and safety" subtitle="Overall accuracy never hides critical failures; unmeasured is not zero">
          <table className="data">
            <thead><tr><th>Measure</th><th className="n">Rate</th><th className="n">Per month</th><th>Status</th></tr></thead>
            <tbody>
              <tr><td>Overall accuracy</td><td className="n">{fmt(s.expected_accuracy_pct)}</td><td className="n">{fmt(s.correct_outcomes_monthly)} correct</td><td /></tr>
              {SAFETY_ROWS.map(([k, label]) => {
                const x = dv.safety[k];
                const bad = x.monthly?.value != null && Number(x.monthly.value) > 0 && (k === "fraud_auto_approved" || k === "critical_false_approvals");
                return (
                  <tr key={k}>
                    <td>{label}</td>
                    <td className={`n ${bad ? "worse" : ""}`}>{fmt(x.rate_pct)}</td>
                    <td className={`n ${bad ? "worse" : ""}`}>{x.monthly ? fmt(x.monthly) : "—"}</td>
                    <td className="small muted">{x.status.replace("_", " ")}{x.missing_routes.length ? ` · missing: ${x.missing_routes.join(", ")}` : ""}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {results.benchmark?.segments?.length > 0 && <p className="small muted" style={{ marginBottom: 0 }}>Segment-level accuracy is shown in the benchmark panel below.</p>}
        </Card>
      </div>

      <Card title="Routes" subtitle="Exclusive shares; review rates are conditional. Open 'Bounds' for the stage-by-stage maximum.">
        <RouteTable results={results} cur={cur} />
      </Card>

      <Card title="Bounded maximum and budget" subtitle="The configured budget is reported separately from the calculated maximum">
        <div className="stats">
          <Stat label="Calculated maximum trajectory cost" metric={b.calculated_max} cur={cur} alert={b.calculated_max.unbounded} />
          <Stat label="Configured budget / task" cur={cur}>{b.configured != null ? fmtValue(b.configured, "unit_money", cur) : "None"}</Stat>
          <Stat label="Enforcement behavior" sub={`${b.check_timing.replace("_", "-")} check`}>{b.enforcement}</Stat>
          <Stat label="Possible single-call overshoot" metric={b.single_call_overshoot} cur={cur} />
          <Stat label="Effective maximum (variable)" metric={b.effective_max} cur={cur} alert={b.effective_max.unbounded} />
          {b.soft_bound && <Stat label="Degrade soft bound (informational)" metric={b.soft_bound} cur={cur} />}
        </div>
        <p className="small" style={{ marginBottom: 0 }}><b>{b.is_hard_bound ? "Hard bound." : "Not a hard bound."}</b> {b.explanation}</p>
      </Card>

      {results.benchmark && <BenchmarkPanel bm={results.benchmark} cur={cur} />}

      <Card title="Warnings and data quality">
        <Issues issues={results.issues} empty="No warnings." />
      </Card>
      <p className="message" style={{ marginTop: 18 }}>
        Token price tells you what one model call costs. Outcome Economics Studio tells you what one correct business outcome
        costs, what it could cost in the worst permitted case, and which architectural changes reduce that cost safely.
      </p>
      <p className="small muted">Evidence labels: {Object.values(EVIDENCE).join(" · ")}. Assumptions are never presented as measured results.</p>
    </>
  );
}
