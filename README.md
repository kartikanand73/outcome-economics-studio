# Outcome Economics Studio

> **Token price tells you what one model call costs. Outcome Economics Studio tells you what one
> correct business outcome costs, what it could cost in the worst permitted case, and which
> architectural changes reduce that cost safely.**

A local architecture-and-economics modelling tool for AI workflows. It prices a complete
decision trajectory — deterministic rules, a lightweight model, a larger model, tools,
human review, evaluation and allocated infrastructure — and asks the question that matters:

**Could the additional model call change the governed outcome?**

Guiding principle: *do not spend more intelligence than the decision requires.*


## Watch the demo

▶️ **Outcome Economics Studio: What Does a Correct, Governed AI Outcome Actually Cost?**

https://youtu.be/aiIg5N0LboU

Outcome Economics Studio goes beyond token-price calculations. It models the complete cost of producing a correct, governed business outcome across deterministic rules, decision models, larger language models, tools, retries, bounded execution, human review, infrastructure and evaluation.

The demo walks through a bank-withdrawal scenario and shows how architecture choices affect expected cost, bounded maximum cost, accuracy, latency and operational risk.

### What the studio helps answer

- Which route should handle each type of work?
- When does a larger model call provide enough decision value?
- What does human review add to the operating cost?
- Is the maximum cost actually bounded?
- What is the cost per correct governed outcome?
- Which numbers are measured, assumed or derived?

Read the complete article:

https://medium.com/@kartikanand_11915/agentic-finops-part-5-of-5-i-built-outcome-economics-studio-because-model-cost-is-not-outcome-92151182e1b1
---

## Quick start

### Option A — Docker (recommended)

```bash
docker compose up --build
# open http://localhost:8000
```

Scenarios persist in the `studio-data` volume.

### Option B — Python only (no Node needed)

The zip includes a pre-built UI in `frontend/dist`, which the backend serves directly.

```bash
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
uvicorn app.api.main:app --port 8000
# open http://localhost:8000
```

### Option C — local Python + Node (to edit the UI)

Requirements: Python 3.11+, Node 18+.

```bash
# 1. Backend
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest -q                                             # 73 tests
uvicorn app.api.main:app --reload --reload-dir app --port 8000   # watch only app/, never .venv

# 2. Frontend (second terminal)
cd frontend
npm install
npm run dev                                           # http://localhost:5173 (proxies /api to :8000)
```

To serve the UI from FastAPI instead of the Vite dev server, run `npm run build` in `frontend/`;
the backend then serves `frontend/dist` at http://localhost:8000.

Saved scenarios live in `backend/data/scenarios.db` (override with `OES_DB_PATH`). The sample
scenarios are seeded on first start; **Restore samples** in the sidebar resets them.

---

## What it does

**Three modes**

| Mode | Purpose |
|---|---|
| **Estimate** | Enter assumptions across five screens: Workload → Decision routes → Models → Context & bounds → Human, tool & infra. Results recalculate live as you type. |
| **Measure** | Import benchmark results (JSON, metrics CSV, or decision-level CSV). The benchmark is frozen; the projection is recalculated beside it. |
| **Compare** | Put scenarios side by side with deltas against a baseline. Clone a scenario to change its architecture. |

**Model catalog.** A shared, editable list of models and their prices per 1M tokens (input, cached input, output,
reasoning). It ships with published list prices from OpenAI, Anthropic, Google, xAI, Mistral and DeepSeek, each with a
source link and an as-of date (seeded from `backend/app/pricing/seed_catalog.json`), plus your own Jev entry.

- Pick any catalog model for any stage in **Decision routes**, or add it on the **Models** screen. Its price is copied into
  the scenario, with usage and limits defaulted by tier, so saved scenarios stay reproducible.
- Edit a price (for a contract or discount price) or add a new model in **Model catalog**. Old prices are kept in that
  model's history, and **Restore** puts a shipped model back to its published price.
- When the catalog changes, each scenario's Models screen says *Catalog price differs* and offers a one-click update.
- Catalog prices are labelled *Provider-reported*; models you add can be *Measured* (from bills) or *User assumption*.
- List prices change often. Check the as-of date and the source link before using a number in a decision.

**Screens follow your decision routes.** Models are chosen on Decision routes. The Models and Context & bounds
screens then show only the models those routes use; models used only in 0%-share routes are shown with a note. Human
review and tool cost inputs appear only when a route needs them. A route with no model has $0 LLM cost.

**Default vs custom bounds.** Each model added from the catalog starts in *default bounds*: its worst case is its own
token cost (average tokens per call x average calls including expected retries, priced without cache credit). Switch a
model to *custom limits* to model retries, retrieval, conversation history or agent loops; only then can a missing
limit make the workflow Unbounded. The Jev benchmark samples use custom limits.

**Results dashboard.**

- *Headline cards:* expected and maximum bounded cost per task, cost per correct governed task, and daily, monthly and annual cost.
- *Tokens and calls:* expected and maximum tokens, larger-model calls made and avoided, and human reviews.
- *Latency, accuracy and safety:* median and P95 latency, accuracy against target, and safety failures.
- *Cost breakdown:* by category, by route, expected versus bounded maximum, model versus human cost, and monthly cost by volume.
- *Other panels:* decision value, accuracy and safety, routes with stage-by-stage bounds, budget enforcement, measured versus projected, and warnings.

**Exports:** scenario JSON, results CSV, printable HTML report (print to PDF from the browser).

---

## Modelling rules

These are the decisions that make the numbers trustworthy. All are covered by tests.

### Routes are exclusive; human review is conditional
Every task follows exactly one route and route shares **must total 100%**. Human review is a
*conditional rate inside each route* (e.g. 0% of deterministic approvals, 10% of Jev-only,
20% of Jev→Sol) and is never added to the route total. A direct-human route is one of the
exclusive routes; a "review mandatory" route reviews 100% of its tasks.

### Costs
| Quantity | Formula |
|---|---|
| Model-call cost | input + output + reasoning − cached-input discount (reasoning billed at the output price unless overridden; only when separately metered) |
| Route cost | Σ stage model cost × expected attempts + tool calls + human review + evaluation + other variable |
| Human review | minutes ÷ 60 × hourly cost × reviewed tasks |
| Expected task cost | Σ route share × route cost (+ allocated fixed cost, labelled *allocation*) |
| Daily / monthly | expected variable cost × tasks/day; × operating days + fixed monthly |
| Annual | 12-month schedule with monthly-compounded growth |
| Cost per correct governed task | monthly operating cost ÷ (monthly tasks × share-weighted route accuracy) |

All money is `Decimal`. Rounding happens only at display time (ROUND_HALF_UP to the currency's
minor unit for totals; 6 decimals for sub-cent unit costs).

### Bounded maximum is computed stage by stage
For each reachable route (share > 0) and each stage:

* max input context = system + max user input + history + retrieval + tool schemas + few-shot
* max tokens / call = max input context + max output + max reasoning
* max attempts = max model calls (or agent-iteration cap) × (1 + max retries)
* stage max = attempts × max call cost (no cache credit) + max tool calls × tool cost + sub-agent fan-out

The route maximum sums its stages plus worst-case review, evaluation and other variable costs.
The task maximum is the worst reachable route. **If any reachable dimension is unbounded, the
maximum is reported as "Unbounded" with the reasons — never as a number.**

### Missing limits only matter when the feature is reachable
A missing sub-agent limit is irrelevant when sub-agents are disabled; a missing tool-call limit is
irrelevant when the stage exposes no tools; a missing retry limit matters only when retries are
enabled; a missing reasoning limit matters only for models that meter reasoning separately.
Routes with 0% share never raise warnings.

### Budgets are not automatically a maximum
The calculated maximum, configured budget, enforcement behaviour and single-call overshoot are
shown separately.

| Enforcement | Effect on the maximum |
|---|---|
| none / warn | none — monitoring only |
| degrade | none — not fail-closed; a soft bound is shown for information |
| reject + post-call check | automated spend ≤ budget + one worst-case call |
| reject + pre-call check | **hard bound**: automated spend ≤ budget — only if a single call's worst case is itself bounded |

Budgets constrain automated spend (models, tools, sub-agents). Human review and evaluation still
apply after a rejection and are added on top.

### Measured vs projected
Imported benchmarks are frozen (immutable model, and the API refuses to overwrite them on save).
Changing a model price recalculates the projection only. Each sample shows the original measured
result, the current projection, the difference and the evidence source.

### Accuracy never hides safety
Fraud auto-approved, critical false approvals, incorrect automatic rejections, unnecessary reviews,
policy override rate and segment accuracy are shown separately. **A blank safety rate means
"not measured" and is never treated as zero**; partial coverage is flagged with the missing routes.

### Evidence labels
Every input carries a label: *User assumption* (default), *Measured*, *Provider-reported*. Every
output is *Derived*. Click a badge to relabel an input. When more than half of the key inputs are
assumptions, the results carry an "estimate based mainly on assumptions" warning.

---

## Sample data

| Scenario | What it shows |
|---|---|
| **Sol-only** | GPT-6 Sol on every model-eligible decision. Measured: ~$2.11 / 1,000 decisions, 99.2% accuracy, 2,448 ms median. |
| **Confidence cascade** | Jev on confident cases, Sol on uncertain. Measured: ~$0.71 / 1,000, 98.0%, 221 ms. |
| **Outcome-aware router** | Policy removes calls that cannot matter; Sol only when a second opinion can change the outcome. Measured: 137 Sol calls in 600 decisions, 415 avoided, ~75% fewer Sol tokens, ~73% lower model cost, ~$0.56 / 1,000, 98.8%, 209 ms, zero fraud auto-approved. |
| **Illustrative: agentic exception handling** | Assumptions only. Demonstrates unbounded-risk warnings, direct human review, a model call before mandatory review, and a post-call budget that cannot bound an unbounded single call. |

The three Jev scenarios are **sample benchmark data** and are labelled as such throughout.
Their measured values come from the reference benchmark; the model prices, token counts,
human-review rates (a uniform 5% of model decisions, for comparability) and infrastructure costs
are illustrative assumptions. Replace them with your own. With these assumptions the projections
land within about 1–3% of the measured figures, and Compare reproduces the ~73% model-cost and
~75% Sol-token reductions.

Example import files: `samples/example-benchmark.json`, `samples/example-metrics.csv`,
`samples/example-decisions.csv`. Schema: [`docs/import-schema.md`](docs/import-schema.md).

---

## Architecture

```
backend/app/
  domain/        Pydantic schema (Decimal fields, evidence labels, frozen MeasuredBenchmark)
  engine/        pure calculation — no I/O
    tokens.py      per-call cost, context and token bounds
    routes.py      route expected cost and stage-by-stage maximum
    budget.py      budget enforcement semantics
    decision_value.py  changed-outcome, avoidable spend, safety aggregation
    latency.py     lognormal mixture of route P50/P95
    benchmark.py   measured vs projected
    aggregate.py   scenario → results payload
    compare.py     side-by-side deltas
  validation/    structural errors, dependency-aware unbounded warnings, data quality
  pricing/       PriceProvider interface + ManualPriceProvider (sample catalog)
  importers/     JSON / metrics CSV / decision-level CSV adapters
  persistence/   SQLite scenario store
  reports/       Decimal-safe JSON, results CSV, printable HTML report
  api/           FastAPI routes; serves frontend/dist when built
  samples/       sample scenarios
frontend/src/    React + Vite + Recharts
```

**Extension points**

- *Live price lookup:* implement `PriceProvider` in `pricing/catalog.py` (return `PriceQuote`s labelled `provider_reported`) and register it in `PROVIDERS`.
- *Telemetry:* write an adapter that emits the decision-level CSV/JSON shape, or add a module to `importers/` that produces an `ImportResult`.

**API:** interactive docs at http://localhost:8000/docs.

---

## MVP boundaries

Not included by design: automatic policy changes, live production routing, provider billing
reconciliation, enterprise authentication, cloud deployment, self-modifying thresholds.
