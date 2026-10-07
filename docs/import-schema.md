# Import schema (v1.0)

Outcome Economics Studio imports measured results in three shapes. Every import
produces an **immutable measured benchmark** that is stored alongside a scenario
and shown next to the scenario's **projection**. The projection recalculates from
the scenario's editable inputs; the benchmark never changes.

Optionally (the *"Also write measured values into the scenario inputs"* switch, or
`apply_to_inputs=true` on the API), measured route and model statistics are written
into the scenario's inputs and labelled **Measured**.

Examples live in [`samples/`](../samples).

---

## 1. Benchmark JSON

```json
{
  "schema_version": "1.0",
  "benchmark": {
    "name": "Outcome-aware router - replay run",       // required
    "source": "Your evaluation harness",
    "run_date": "2026-09-01",
    "decisions": 600,                                   // enables per-1,000 normalisation of counts
    "is_sample": false,
    "metrics": {
      "model_cost_per_1000_decisions": {"value": 0.56, "unit": "USD", "evidence": "measured", "note": ""},
      "accuracy_pct": 98.8,                             // shorthand: a bare number = measured value
      "p50_latency_ms": 209
    },
    "segments": [
      {"name": "High-value withdrawals", "decisions": 120, "accuracy_pct": 97.5}
    ]
  },
  "routes": [                                           // optional; ids must match scenario route ids
    {"id": "jev-sol", "share_pct": 22.8333, "accuracy_pct": 97.4, "larger_changed_outcome_pct": 31,
     "p50_latency_ms": 2600, "p95_latency_ms": 5100, "human_review_pct": 5,
     "safety": {"fraud_auto_approval_pct": 0, "critical_false_approval_pct": 0}}
  ],
  "models": [                                           // optional; ids must match scenario model ids
    {"id": "gpt-6-sol", "avg_input_tokens": 1080, "avg_output_tokens": 46, "avg_reasoning_tokens": 64,
     "retry_rate_pct": 1, "cached_input_share_pct": 0, "p50_latency_ms": 2500, "p95_latency_ms": 5200}
  ]
}
```

`evidence` may be `measured` (default), `provider_reported`, `assumption` or `derived`.

### Recognised metric keys

Any key is accepted and displayed. These keys are also compared with the projection:

| Key | Meaning | Normalised per 1,000 decisions |
|---|---|---|
| `model_cost_per_1000_decisions` | Model spend per 1,000 decisions | – |
| `accuracy_pct` | Overall accuracy | – |
| `p50_latency_ms`, `p95_latency_ms` | Automated decision latency | – |
| `larger_model_calls` | Count of larger-model calls in the run | yes (needs `decisions`) |
| `larger_model_calls_avoided` | Count avoided vs. one call per model-eligible decision | yes |
| `human_reviews` | Count of reviews | yes |
| `fraud_auto_approved` | Count of fraud cases auto-approved | yes |
| `critical_false_approvals` | Count of critical false approvals | yes |
| `larger_model_token_reduction_pct`, `model_cost_reduction_pct` | Relative to a baseline architecture | shown only; project them with **Compare** |

Route fields: `share_pct`, `accuracy_pct`, `p50_latency_ms`, `p95_latency_ms`,
`human_review_pct`, `larger_changed_outcome_pct`, and `safety.{fraud_auto_approval_pct,
critical_false_approval_pct, incorrect_auto_rejection_pct, unnecessary_review_pct,
policy_override_pct}`.

Model fields: `avg_input_tokens`, `avg_output_tokens`, `avg_reasoning_tokens`,
`retry_rate_pct`, `cached_input_share_pct`, `avg_calls_per_task`, `p50_latency_ms`,
`p95_latency_ms`.

---

## 2. Metrics CSV

One row per metric, plus optional metadata rows.

```csv
metric,value,unit,evidence,note
benchmark_name,Confidence cascade replay,,,
source,Your evaluation harness,,,
decisions,600,,,
model_cost_per_1000_decisions,0.71,USD,measured,
accuracy_pct,98.0,%,measured,
p50_latency_ms,221,ms,measured,
```

Required columns: `metric`, `value`. Metadata rows: `benchmark_name`, `source`,
`run_date`, `decisions`.

---

## 3. Decision-level CSV

One row per evaluated decision. This is the richest import: the studio aggregates
it into measured route shares, route accuracy, latency quantiles, review rates,
changed-outcome rates, safety rates, segment accuracy and a benchmark.

| Column | Required | Type | Aggregated into |
|---|---|---|---|
| `route_id` | yes | text (must match a scenario route id to apply) | route share = count / total |
| `correct` | yes | 0/1 | route and overall accuracy |
| `latency_ms` | | number | route and overall P50/P95 |
| `human_reviewed` | | 0/1 | route review rate; `human_reviews` count |
| `larger_model_called` | | 0/1 | `larger_model_calls` count |
| `outcome_changed` | | 0/1 (with `larger_model_called`) | route `larger_changed_outcome_pct` among escalated rows |
| `fraud_auto_approved` | | 0/1 | route safety rate; count |
| `critical_false_approval` | | 0/1 | route safety rate; count |
| `incorrect_auto_rejection` | | 0/1 | route safety rate |
| `segment` | | text | segment-level accuracy |
| `model_cost` | | number | `model_cost_per_1000_decisions` |

Booleans accept `1/0`, `true/false`, `yes/no`. Route shares are computed to four
decimals and the rounding remainder goes to the largest route so shares total
exactly 100%. When applying to inputs, scenario routes absent from the file are
set to 0% (no measured traffic reached them) and a note is shown.

---

## Scenario JSON (export / import)

**Export scenario JSON** writes the complete scenario (inputs, evidence labels and
any frozen benchmark). **Import scenario** accepts that file and creates a new,
editable scenario. The document is the `Scenario` model in
`backend/app/domain/models.py`; money and token values are decimal strings.

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/import/preview` (multipart `file`) | Parse without saving |
| POST | `/api/scenarios/{id}/import` (multipart `file`, `apply_to_inputs`) | Attach benchmark; optionally apply measured values |
| POST | `/api/import/scenario` (multipart `file`) | Create a scenario from an export |
