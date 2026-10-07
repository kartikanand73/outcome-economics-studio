import React from "react";
import { Card, NumField, makeBinder } from "../components/ui.jsx";
import { fmt } from "../lib/format.js";
import { routeNeeds } from "../lib/state.js";

function NotUsed({ title, children, onOpenRoutes }) {
  return (
    <Card title={title}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <span className="small muted">{children}</span>
        {onOpenRoutes && <button className="btn small" onClick={onOpenRoutes}>Open Decision routes</button>}
      </div>
    </Card>
  );
}

export default function Costs({ draft, update, results, onOpenRoutes }) {
  const needs = routeNeeds(draft);
  const b = makeBinder(draft, update);
  const cp = (k) => ["costs", k];
  const cur = draft.workload.currency;
  const s = results?.ok ? results.summary : null;
  return (
    <>
      {!needs.humanReview ? (
        <NotUsed title="Human review" onOpenRoutes={onOpenRoutes}>
          No route uses human review, so review cost is $0. To add it, set a review rate on a route, or mark a route as a direct human decision or as review mandatory.
        </NotUsed>
      ) : (
      <Card title="Human review" subtitle="Human-review cost = review minutes ÷ 60 × hourly cost × reviewed tasks. The share of tasks reviewed comes from each route's conditional rate.">
        <div className="fields">
          <NumField label="Average review time" unit="min" {...b(cp("review_minutes_avg"))} />
          <NumField label="Maximum review time" unit="min" optional unsetLabel="= average" {...b(cp("review_minutes_max"))}
            hint="Used for the worst-case bound" />
          <NumField label="Fully loaded reviewer cost" unit={`${cur}/h`} {...b(cp("reviewer_hourly_cost"))} />
          <div className="field">
            <span className="field-label"><span>Tasks requiring review (derived)</span></span>
            <div className="value" style={{ padding: "6px 0", fontWeight: 600 }}>
              {s ? `${fmt(s.human_review_share_pct)} · ${fmt(s.human_reviews_monthly)} / month` : "—"}
            </div>
          </div>
        </div>
      </Card>
      )}
      {!needs.tools ? (
        <NotUsed title="Tool / API calls" onOpenRoutes={onOpenRoutes}>
          No route makes tool or API calls, so tool cost is $0. Add rule API calls to a route, or expose tools on a model stage, to price them.
        </NotUsed>
      ) : (
        <Card title="Tool / API calls">
          <div className="fields">
            <NumField label="Tool / API cost per invocation" unit={cur} {...b(cp("tool_cost_per_call"))} />
            <div className="field">
              <span className="field-label"><span>Average tool calls per task (derived)</span></span>
              <div style={{ padding: "6px 0", fontWeight: 600 }}>{s ? fmt(s.tool_calls_per_task) : "—"}</div>
              <span className="hint">Set per route (rule calls) and per stage (tools exposed)</span>
            </div>
          </div>
        </Card>
      )}
      <Card title="Evaluation and other variable costs">
        <div className="fields">
          <NumField label="Evaluation sampling rate" unit="% of tasks" {...b(cp("eval_sampling_pct"))} />
          <NumField label="Evaluation cost per sampled task" unit={cur} {...b(cp("eval_cost_per_sample"))} />
          <NumField label="Other variable cost per task" unit={cur} {...b(cp("other_variable_per_task"))} />
        </div>
      </Card>
      <Card title="Monthly fixed costs" subtitle="Allocated across monthly volume and labelled as an allocation — not a directly measured per-task charge.">
        <div className="fields">
          <NumField label="Fixed infrastructure" unit={`${cur}/mo`} {...b(cp("fixed_infra_monthly"))} />
          <NumField label="Observability" unit={`${cur}/mo`} {...b(cp("observability_monthly"))} />
          <NumField label="Other fixed" unit={`${cur}/mo`} {...b(cp("other_fixed_monthly"))} />
          <div className="field">
            <span className="field-label"><span>Allocated per task</span></span>
            <div style={{ padding: "6px 0", fontWeight: 600 }}>{s ? fmt(s.allocated_fixed_per_task, cur) : "—"}</div>
            <span className="hint">Allocation, not a measured charge</span>
          </div>
        </div>
      </Card>
    </>
  );
}
