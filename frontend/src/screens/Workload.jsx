import React from "react";
import { Card, NumField, SelectField, TextField, makeBinder } from "../components/ui.jsx";

const CURRENCIES = ["USD", "EUR", "GBP", "INR", "CAD", "AUD", "JPY"].map((c) => ({ value: c, label: c }));

export default function Workload({ draft, update }) {
  const b = makeBinder(draft, update);
  return (
    <>
      <Card title="Scenario" subtitle="What workflow is being modeled">
        <div className="fields wide">
          <TextField label="Scenario name" value={draft.name} onChange={(v) => update(["name"], v)} />
          <TextField label="Business process" value={draft.business_process} placeholder="e.g. Bank withdrawal decision"
            onChange={(v) => update(["business_process"], v)} />
        </div>
        <div style={{ marginTop: 10 }}>
          <TextField label="Description" multiline value={draft.description} onChange={(v) => update(["description"], v)} />
        </div>
      </Card>
      <Card title="Workload" subtitle="Volume, targets and currency. Values default to User assumption — click a label to change its evidence.">
        <div className="fields">
          <NumField label="Tasks per day" unit="tasks" {...b(["workload", "tasks_per_day"])} />
          <NumField label="Operating days per month" unit="days" {...b(["workload", "operating_days_per_month"])} />
          <NumField label="Annual growth" unit="%" {...b(["workload", "annual_growth_pct"])}
            hint="Compounded monthly in the annual projection" />
          <NumField label="Peak tasks per minute" unit="/min" optional {...b(["workload", "peak_tasks_per_minute"])} />
          <NumField label="Target accuracy" unit="%" {...b(["workload", "target_accuracy_pct"])} />
          <NumField label="Maximum acceptable latency" unit="ms" optional {...b(["workload", "max_latency_ms"])} />
          <SelectField label="Currency" value={draft.workload.currency} options={CURRENCIES}
            onChange={(v) => update(["workload", "currency"], v)} />
          <NumField label="Human review rate today (without this design)" unit="% of tasks" optional unsetLabel="Not set"
            {...b(["decision", "baseline_review_pct"])} hint="Used to count human reviews prevented" />
        </div>
      </Card>
    </>
  );
}
