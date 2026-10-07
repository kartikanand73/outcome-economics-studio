import React from "react";
import { Card, Issues, NumField, SelectField, Toggle, makeBinder } from "../components/ui.jsx";
import { fmt } from "../lib/format.js";
import { modelUsage } from "../lib/state.js";

function computedFor(results, model) {
  if (!results?.ok) return null;
  for (const r of results.routes) {
    for (const s of r.max?.stages ?? []) if (s.model === model.name) return s;
  }
  return null;
}

function Computed({ label, metric, cur }) {
  return (
    <div className="stat" style={{ padding: "8px 10px" }}>
      <span className="label"><span>{label}</span></span>
      <span className={`value ${metric?.unbounded ? "unb" : ""}`} style={{ fontSize: 16 }}>{fmt(metric, cur)}</span>
      {metric?.unbounded && <span className="sub">{metric.reasons.join("; ")}</span>}
    </div>
  );
}

function ModelBounds({ m, idx, draft, update, results, usage }) {
  const b = makeBinder(draft, update);
  const cp = (k) => ["models", idx, "context", k];
  const lp = (k) => ["models", idx, "limits", k];
  const c = m.context, l = m.limits;
  const comp = computedFor(results, m);
  const cur = draft.workload.currency;
  const isDefault = m.bounds_mode === "default";
  const where = `Used in: ${usage.routes.join(", ")}${usage.reachable ? "" : " (only routes at 0% share, so not in the results yet)"}`;
  const computed = (
    <>
      <div className="section-title">Calculated bounds (derived)</div>
      {comp ? (
        <div className="stats">
          <Computed label="Max input context / call" metric={comp.max_input_context} />
          <Computed label="Max tokens / call" metric={comp.max_tokens_per_call} />
          <Computed label={isDefault ? "Calls per task (incl. expected retries)" : "Max attempts (calls × retries)"} metric={comp.max_attempts} />
          <Computed label="Max task-token exposure (this stage)" metric={comp.max_tokens} />
          <Computed label="Max cost / call (no cache)" metric={comp.max_call_cost} cur={cur} />
        </div>
      ) : <p className="muted small">Not used by a reachable route{results && !results.ok ? " (fix validation errors to see bounds)" : ""}.</p>}
    </>
  );
  const modeSwitch = (
    <div className="row" style={{ gap: 6 }}>
      <span className="small muted">Bounds:</span>
      <button className={`btn small ${isDefault ? "primary" : ""}`} onClick={() => update(["models", idx, "bounds_mode"], "default")}>Default</button>
      <button className={`btn small ${!isDefault ? "primary" : ""}`} onClick={() => update(["models", idx, "bounds_mode"], "custom")}>Custom limits</button>
    </div>
  );
  if (isDefault) {
    return (
      <Card title={m.name} subtitle={where} actions={modeSwitch}>
        <p className="small" style={{ margin: 0 }}>
          <b>Default bounds.</b> The worst case for this model is its token cost: average input ({fmt({ kind: "tokens", value: m.avg_input_tokens })}),
          output ({fmt({ kind: "tokens", value: m.avg_output_tokens })}){m.separately_metered_reasoning ? ` and reasoning (${fmt({ kind: "tokens", value: m.avg_reasoning_tokens })})` : ""} tokens
          per call, at its average calls per task including expected retries, priced without any cache discount.
          Change the averages on the Models screen. Choose <b>Custom limits</b> to model retries, retrieval, conversation history or agent loops.
        </p>
        {computed}
      </Card>
    );
  }
  return (
    <Card title={m.name} subtitle={`${where}. Custom limits: blank = not configured.`} actions={modeSwitch}>
      <div className="section-title" style={{ marginTop: 0 }}>Context components (tokens)</div>
      <div className="fields">
        <NumField label="System prompt" {...b(cp("system_prompt_tokens"))} />
        <NumField label="Avg user input" {...b(cp("avg_user_input_tokens"))} />
        <NumField label="Max user input" optional unsetLabel="= average" {...b(cp("max_user_input_tokens"))} />
        <NumField label="Tool schemas" {...b(cp("tool_schema_tokens"))} />
        <NumField label="Number of tool schemas" integer noEvidence {...b(cp("tool_schema_count"))} />
        <NumField label="Few-shot examples" {...b(cp("few_shot_tokens"))} />
        <NumField label="Max output" optional unsetLabel="Unbounded" {...b(cp("max_output_tokens"))} />
        <NumField label="Max reasoning" optional unsetLabel={m.separately_metered_reasoning ? "Unbounded" : "Not metered"}
          {...b(cp("max_reasoning_tokens"))} />
      </div>
      <div className="row" style={{ gap: 16, margin: "10px 0 4px" }}>
        <Toggle label="Conversation history sent" value={c.history_enabled} onChange={(v) => update(cp("history_enabled"), v)} />
        <Toggle label="Retrieved documents sent" value={c.retrieval_enabled} onChange={(v) => update(cp("retrieval_enabled"), v)} />
        <Toggle label="Agent loop enabled" value={l.agent_loop_enabled} onChange={(v) => update(lp("agent_loop_enabled"), v)} />
      </div>
      <div className="fields">
        {c.history_enabled && <NumField label="Max history" optional unsetLabel="Unbounded" {...b(cp("max_history_tokens"))} />}
        {c.retrieval_enabled && <NumField label="Max retrieved documents" optional unsetLabel="Unbounded" {...b(cp("max_retrieved_tokens"))} />}
        <NumField label="Max model calls per task" optional integer noEvidence
          unsetLabel={l.agent_loop_enabled ? "Unbounded" : "Ceiling of average"} {...b(lp("max_model_calls"))} />
        {l.agent_loop_enabled && <NumField label="Max agent iterations" optional integer noEvidence unsetLabel="Unbounded" {...b(lp("max_agent_iterations"))} />}
        <NumField label="Max retries per call" optional integer noEvidence
          unsetLabel={m.retries_enabled || Number(m.retry_rate_pct) > 0 ? "Unbounded" : "Retries disabled"} {...b(lp("max_retries"))} />
      </div>
      {computed}
      <div style={{ marginTop: 8 }}>
        <Issues issues={results?.issues} filter={(i) => i.model && (i.model === m.id || i.model.startsWith(`${m.id}:`))} />
      </div>
    </Card>
  );
}

export default function Bounds({ draft, update, results }) {
  const b = makeBinder(draft, update);
  const bp = (k) => ["budget", k];
  const bc = results?.ok ? results.budget.cost : null;
  const cur = draft.workload.currency;
  const usage = modelUsage(draft);
  const used = draft.models.map((m, i) => [m, i]).filter(([m]) => usage[m.id]);
  if (used.length === 0) {
    return (
      <Card title="No LLM in any route">
        <p className="small" style={{ margin: 0 }}>
          Every route is a deterministic rule or a human decision, so LLM cost is <b>{fmt({ kind: "money", value: 0 }, cur)}</b> and
          there are no context or call limits to set. Add a model stage in Decision routes to model LLM cost.
        </p>
      </Card>
    );
  }
  return (
    <>
      <Card title="Per-task budget and enforcement"
        subtitle="A budget only bounds cost when enforced fail-closed before the next call. It is shown separately from the calculated maximum.">
        <div className="fields">
          <NumField label="Max monetary budget / task" unit={cur} optional unsetLabel="None" {...b(bp("max_monetary_budget_per_task"))} />
          <NumField label="Max token budget / task" unit="tokens" optional unsetLabel="None" {...b(bp("max_token_budget_per_task"))} />
          <SelectField label="Enforcement" value={draft.budget.enforcement} onChange={(v) => update(bp("enforcement"), v)}
            options={[{ value: "none", label: "None" }, { value: "warn", label: "Warn (monitor only)" },
              { value: "degrade", label: "Degrade to fallback path" }, { value: "reject", label: "Reject (fail-closed)" }]} />
          <SelectField label="Check timing" value={draft.budget.check_timing} onChange={(v) => update(bp("check_timing"), v)}
            options={[{ value: "pre_call", label: "Before each call (pre-call)" }, { value: "post_call", label: "After each call (post-call)" }]} />
          {draft.budget.enforcement === "degrade" &&
            <NumField label="Degrade fallback cost" unit={cur} optional {...b(bp("degrade_fallback_cost"))} />}
          <NumField label="Max execution time" unit="s" optional unsetLabel="None" {...b(bp("max_execution_time_s"))} />
        </div>
        {bc && (
          <>
            <div className="stats" style={{ marginTop: 12 }}>
              <Computed label="Calculated maximum trajectory cost" metric={bc.calculated_max} cur={cur} />
              <div className="stat" style={{ padding: "8px 10px" }}>
                <span className="label"><span>Configured budget · enforcement</span></span>
                <span className="value" style={{ fontSize: 16 }}>
                  {bc.configured != null ? fmt({ kind: "unit_money", value: bc.configured }, cur) : "None"} · {bc.enforcement}
                </span>
                <span className="sub">{bc.check_timing.replace("_", "-")} check</span>
              </div>
              <Computed label="Possible single-call overshoot" metric={bc.single_call_overshoot} cur={cur} />
              <Computed label="Effective maximum (variable)" metric={bc.effective_max} cur={cur} />
            </div>
            <p className="small" style={{ margin: "8px 0 0" }}>
              <b>{bc.is_hard_bound ? "Hard bound. " : "Not a hard bound. "}</b>{bc.explanation}
            </p>
          </>
        )}
      </Card>
      {used.map(([m, i]) => <ModelBounds key={m.id} m={m} idx={i} draft={draft} update={update} results={results} usage={usage[m.id]} />)}
    </>
  );
}
