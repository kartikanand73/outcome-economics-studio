import React from "react";
import ModelPicker from "../components/ModelPicker.jsx";
import { Card, Issues, NumField, SelectField, TextField, Toggle, makeBinder } from "../components/ui.jsx";
import { useChartTheme } from "../lib/colors.js";
import { num } from "../lib/format.js";
import { uid } from "../lib/state.js";

function newRoute(models) {
  return {
    id: uid("route"), name: "New route", share_pct: 0, description: "", deterministic_rule: false,
    rule_latency_ms: 5, rule_tool_calls: 0, max_rule_tool_calls: null, stages: models.length ? [{ model_id: models[0].id }] : [],
    direct_human: false, human_review_pct: 0, human_review_mandatory: false, review_minutes_override: null,
    expected_outcome: "", accuracy_pct: 98, p50_latency_ms: null, p95_latency_ms: null, model_eligible: null,
    larger_changed_outcome_pct: null, safety: {}, evidence: {},
  };
}

function RouteFlow({ route, models }) {
  const byId = Object.fromEntries(models.map((m) => [m.id, m]));
  const parts = [];
  if (route.deterministic_rule) parts.push(<span key="rule" className="chip">Deterministic rule</span>);
  route.stages.forEach((s, i) => {
    const m = byId[s.model_id];
    parts.push(<span key={`s${i}`} className={`chip ${m?.tier === "larger" ? "larger" : ""}`}>{m?.name ?? s.model_id}</span>);
  });
  if (route.direct_human) parts.push(<span key="h" className="chip human">Human decides</span>);
  else if (route.human_review_mandatory) parts.push(<span key="h" className="chip human">Human review (mandatory, 100%)</span>);
  else if (Number(route.human_review_pct) > 0) parts.push(<span key="h" className="chip human">Human review ({num(route.human_review_pct)}% of this route)</span>);
  return <div className="flow">{parts.reduce((acc, p, i) => (i ? [...acc, <span key={`a${i}`}>→</span>, p] : [p]), [])}</div>;
}

function Stage({ stage, idx, path, models, update, remove }) {
  const b = makeBinder({ s: stage }, (p, v) => update([...path, ...p.slice(1)], v));
  return (
    <div className="stage">
      <div className="stage-head">
        <b>Stage {idx + 1}</b>
        <div style={{ flex: 1 }} />
        <button className="btn small ghost danger" onClick={remove}>Remove stage</button>
      </div>
      <div className="fields">
        <ModelPicker label="Model (scenario or catalog)" value={stage.model_id} models={models} update={update}
          onPick={(id) => update([...path, "model_id"], id)} />
        <NumField label="Avg calls (override)" optional unsetLabel="Model default" noEvidence {...b(["s", "avg_calls_override"])} />
      </div>
      <div className="row" style={{ marginTop: 8, gap: 16 }}>
        <Toggle label="Tools exposed to this stage" value={stage.tools_exposed} onChange={(v) => update([...path, "tools_exposed"], v)} />
        <Toggle label="Sub-agents enabled" value={stage.subagents_enabled} onChange={(v) => update([...path, "subagents_enabled"], v)} />
      </div>
      {(stage.tools_exposed || stage.subagents_enabled) && (
        <div className="fields" style={{ marginTop: 8 }}>
          {stage.tools_exposed && <>
            <NumField label="Avg tool calls" noEvidence {...b(["s", "avg_tool_calls"])} />
            <NumField label="Max tool calls" optional integer noEvidence {...b(["s", "max_tool_calls"])} unsetLabel="Unbounded" />
          </>}
          {stage.subagents_enabled && <>
            <NumField label="Avg sub-agents" noEvidence {...b(["s", "avg_subagents"])} />
            <NumField label="Max sub-agents" optional integer noEvidence {...b(["s", "max_subagents"])} unsetLabel="Unbounded" />
            <ModelPicker label="Sub-agent model" allowSame value={stage.subagent_model_id} models={models} update={update}
              onPick={(id) => update([...path, "subagent_model_id"], id)} />
          </>}
        </div>
      )}
    </div>
  );
}

function RouteCard({ route, idx, draft, update, results }) {
  const path = ["routes", idx];
  const b = makeBinder(draft, update);
  const rp = (k) => [...path, k];
  const sp = (k) => [...path, "safety", k];
  const models = draft.models;
  const q = results?.ok ? results.decision_value.routes[route.id] : null;
  const remove = () => update(["routes"], draft.routes.filter((_, i) => i !== idx));
  return (
    <div className="route-card">
      <div className="route-head">
        <TextField label="Route name" value={route.name} onChange={(v) => update(rp("name"), v)} />
        <NumField label="Exclusive share" unit="% of tasks" {...b(rp("share_pct"))} />
        <NumField label="Conditional human review" unit="% of route"
          {...b(rp("human_review_pct"))}
          hint={route.direct_human || route.human_review_mandatory ? "Forced to 100% by route type" : "Not part of the 100% total"} />
        <button className="btn small ghost danger" onClick={remove} style={{ alignSelf: "center" }}>Remove</button>
      </div>
      <RouteFlow route={route} models={models} />
      <div className="row" style={{ gap: 16, margin: "4px 0 6px" }}>
        <Toggle label="Deterministic rule used" value={route.deterministic_rule} onChange={(v) => update(rp("deterministic_rule"), v)} />
        <Toggle label="Direct human decision" value={route.direct_human} onChange={(v) => update(rp("direct_human"), v)} />
        <Toggle label="Human review mandatory regardless of model output" value={route.human_review_mandatory}
          onChange={(v) => update(rp("human_review_mandatory"), v)} />
      </div>
      {route.stages.map((s, i) => (
        <Stage key={i} stage={s} idx={i} path={[...path, "stages", i]} models={models} update={update}
          remove={() => update(rp("stages"), route.stages.filter((_, j) => j !== i))} />
      ))}
      <div className="row" style={{ marginTop: 8 }}>
        <button className="btn small" disabled={!models.length}
          onClick={() => update(rp("stages"), [...route.stages, { model_id: models[models.length - 1].id }])}>+ Add model stage</button>
        {q?.applies && (
          <span className={`answer ${q.answer}`} style={{ marginLeft: "auto" }}>
            <b>{q.answer === "yes" ? "Can change outcome" : q.answer === "no" ? "Cannot change outcome" : "Unknown"}</b>{q.detail}
          </span>
        )}
      </div>
      <div className="fields" style={{ marginTop: 10 }}>
        <NumField label="Accuracy / acceptance" unit="%" {...b(rp("accuracy_pct"))} />
        <NumField label="Larger-model calls that changed outcome" unit="%" optional unsetLabel="Not measured"
          {...b(rp("larger_changed_outcome_pct"))} />
        <NumField label="Median latency (override)" unit="ms" optional unsetLabel="Derived from stages" {...b(rp("p50_latency_ms"))} />
        <NumField label="P95 latency (override)" unit="ms" optional unsetLabel="Derived from stages" {...b(rp("p95_latency_ms"))} />
      </div>
      <details className="more">
        <summary>Tool calls, review time, outcome and safety rates</summary>
        <div className="fields" style={{ marginTop: 8 }}>
          <TextField label="Expected outcome" value={route.expected_outcome} onChange={(v) => update(rp("expected_outcome"), v)} />
          <NumField label="Rule/API tool calls (outside models)" {...b(rp("rule_tool_calls"))} />
          <NumField label="Max rule tool calls" optional integer noEvidence {...b(rp("max_rule_tool_calls"))} unsetLabel="Ceiling of average" />
          <NumField label="Rule latency" unit="ms" noEvidence {...b(rp("rule_latency_ms"))} />
          <NumField label="Review minutes (override)" unit="min" optional unsetLabel="Global default" {...b(rp("review_minutes_override"))} />
          <SelectField label="Model-eligible (for avoided-call baseline)" value={route.model_eligible === null ? "" : String(route.model_eligible)}
            options={[{ value: "", label: "Derived" }, { value: "true", label: "Yes" }, { value: "false", label: "No" }]}
            onChange={(v) => update(rp("model_eligible"), v === "" ? null : v === "true")} />
        </div>
        <div className="section-title">Safety rates (leave blank when not measured — blank is never treated as zero)</div>
        <div className="fields">
          <NumField label="Fraud auto-approved" unit="% of route" optional unsetLabel="Not measured" {...b(sp("fraud_auto_approval_pct"))} />
          <NumField label="Critical false approvals" unit="% of route" optional unsetLabel="Not measured" {...b(sp("critical_false_approval_pct"))} />
          <NumField label="Incorrect automatic rejections" unit="% of route" optional unsetLabel="Not measured" {...b(sp("incorrect_auto_rejection_pct"))} />
          <NumField label="Unnecessary reviews" unit="% of reviews" optional unsetLabel="Not measured" {...b(sp("unnecessary_review_pct"))} />
          <NumField label="Policy overrides" unit="% of reviews" optional unsetLabel="Not measured" {...b(sp("policy_override_pct"))} />
        </div>
      </details>
    </div>
  );
}

export default function Routes({ draft, update, results }) {
  const theme = useChartTheme();
  const total = draft.routes.reduce((s, r) => s + Number(r.share_pct || 0), 0);
  const ok = Math.abs(total - 100) < 1e-9;
  return (
    <>
      <Card title="Decision routes"
        subtitle="Each task follows exactly one route. Exclusive shares must total 100%. Human review is a conditional rate inside each route and is not added to the total."
        actions={<button className="btn" onClick={() => update(["routes"], [...draft.routes, newRoute(draft.models)])}>+ Add route</button>}>
        <div className="share-meter">
          <div className="bar">
            {draft.routes.map((r, i) => Number(r.share_pct) > 0 && (
              <div key={r.id} className="seg" title={`${r.name}: ${num(r.share_pct)}%`}
                style={{ width: `${Math.min(Number(r.share_pct), 100)}%`, background: theme.series[i % 8] }} />
            ))}
          </div>
          <b className={ok ? "better" : "worse"}>{num(total, 4)}%</b>
          <span className="muted small">{ok ? "Routes total 100%" : "Must total exactly 100%"}</span>
        </div>
        <div className="legend">
          {draft.routes.map((r, i) => <span key={r.id}><span className="swatch" style={{ background: theme.series[i % 8] }} />{r.name}</span>)}
        </div>
        <div style={{ marginTop: 8 }}>
          <Issues issues={results?.issues} filter={(i) => ["route_share_total", "route_share_range", "review_range", "accuracy_range", "unknown_model", "direct_human_with_models"].includes(i.code)} />
        </div>
      </Card>
      <div style={{ marginTop: 12 }}>
        {draft.routes.map((r, i) => <RouteCard key={r.id} route={r} idx={i} draft={draft} update={update} results={results} />)}
      </div>
    </>
  );
}
