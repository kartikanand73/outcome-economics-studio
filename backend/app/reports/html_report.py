"""Printable HTML summary report (Jinja2). Opens in any browser; print to PDF from there."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from jinja2 import Environment, select_autoescape

from app.domain.models import Scenario

SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "INR": "₹", "JPY": "¥"}
EVIDENCE_LABEL = {"assumption": "User assumption", "measured": "Measured", "provider_reported": "Provider-reported",
                  "derived": "Derived"}
CATEGORY_LABEL = {"lightweight_model": "Lightweight-model", "larger_model": "Larger-model",
                  "tool_api": "Tool / API", "human_review": "Human review", "evaluation": "Evaluation / governance",
                  "other_variable": "Other variable", "infrastructure": "Infrastructure (allocated)"}


def fmt(m, currency="USD"):
    if m is None:
        return "—"
    if isinstance(m, dict):
        if m.get("unbounded"):
            return "Unbounded"
        kind, v = m.get("kind"), m.get("rounded")
    else:
        kind, v = "number", m
    if v is None:
        return "Not measured"
    v = Decimal(str(v))
    sym = SYMBOLS.get(currency, currency + " ")
    if kind == "money":
        return f"{sym}{v:,.2f}" if currency not in ("JPY",) else f"{sym}{v:,.0f}"
    if kind == "unit_money":
        return f"{sym}{v:,.6f}" if abs(v) < 1 else f"{sym}{v:,.4f}"
    if kind == "pct":
        return f"{v:,.2f}%"
    if kind in ("tokens", "count_int"):
        return f"{v:,.0f}"
    if kind == "ms":
        return f"{v:,.0f} ms"
    return f"{v:,.2f}"


TEMPLATE = """<!doctype html><html><head><meta charset="utf-8"><title>{{ sc.name }} — Outcome Economics Studio</title>
<style>
 body{font:13px/1.45 -apple-system,Segoe UI,Roboto,sans-serif;color:#1c2330;max-width:960px;margin:24px auto;padding:0 16px}
 h1{font-size:22px;margin:0 0 2px} h2{font-size:15px;margin:22px 0 8px;border-bottom:1px solid #d9dee7;padding-bottom:4px}
 .muted{color:#5b6576} .grid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}
 .card{border:1px solid #d9dee7;border-radius:6px;padding:8px 10px} .card b{display:block;font-size:16px;margin-top:2px}
 table{border-collapse:collapse;width:100%} td,th{border-bottom:1px solid #e6e9ef;padding:4px 6px;text-align:left;vertical-align:top}
 th{font-weight:600;background:#f5f7fa} td.n{text-align:right;font-variant-numeric:tabular-nums}
 .ev{font-size:10px;padding:1px 5px;border-radius:8px;border:1px solid #c8cfda;white-space:nowrap}
 .ev-assumption{background:#fff7e6;border-color:#f0c36d} .ev-measured{background:#e7f6ec;border-color:#7cc49a}
 .ev-derived{background:#eef2f8} .ev-provider_reported{background:#e8f0fd;border-color:#86a8e7}
 .warn{background:#fff7e6;border-left:3px solid #e0a106;padding:6px 10px;margin:4px 0}
 .err{background:#fdecec;border-left:3px solid #c62828;padding:6px 10px;margin:4px 0}
 .info{background:#eef2f8;border-left:3px solid #6b7a90;padding:6px 10px;margin:4px 0}
 .q{font-size:15px;font-weight:600;background:#eef2f8;padding:10px;border-radius:6px}
 .banner{background:#fff7e6;border:1px solid #f0c36d;padding:8px 10px;border-radius:6px;margin:10px 0}
 @media print{body{margin:0} .noprint{display:none}}
</style></head><body>
<div class="noprint" style="text-align:right"><button onclick="window.print()">Print / save as PDF</button></div>
<h1>{{ sc.name }}</h1>
<div class="muted">{{ sc.business_process }}{% if sc.description %} — {{ sc.description }}{% endif %}</div>
<div class="muted">Generated {{ now }} · Currency {{ cur }} · Outcome Economics Studio</div>
{% if sc.is_sample or (sc.benchmark and sc.benchmark.is_sample) %}<div class="banner"><b>Sample data.</b> {{ sc.sample_note or "Contains sample benchmark data." }}</div>{% endif %}
{% set b = r.evidence_basis %}
<p class="muted">Key-input evidence: {% for k,v in b.counts.items() if v %}{{ ev_label[k] }} {{ v }}{% if not loop.last %} · {% endif %}{% endfor %}
{% if b.mainly_assumptions %} — <b>estimate based mainly on assumptions</b>{% endif %}</p>

<h2>Headline</h2>
<div class="grid">
{% for key,label in cards %}{% set m = r.summary[key] %}<div class="card"><span class="muted">{{ label }}</span><b>{{ fmt(m, cur) }}</b><span class="ev ev-{{ m.evidence }}">{{ ev_label[m.evidence] }}</span></div>{% endfor %}
</div>
{% if r.summary.max_cost_per_task.unbounded %}<div class="err"><b>No maximum cost:</b> {{ r.summary.max_cost_per_task.reasons | join("; ") }}</div>{% endif %}

<h2>Cost breakdown per task</h2>
<table><tr><th>Category</th><th class="n">Per task</th><th class="n">Monthly</th></tr>
{% for k,m in r.breakdown_per_task.items() %}<tr><td>{{ cat_label.get(k,k) }}</td><td class="n">{{ fmt(m, cur) }}</td>
<td class="n">{% if k == "infrastructure" %}{{ fmt(fixed_total, cur) }}{% else %}{{ fmt(r.breakdown_monthly[k], cur) }}{% endif %}</td></tr>{% endfor %}
</table>
<p class="muted">Infrastructure is an allocation of monthly fixed cost across monthly volume, not a directly measured per-task charge.</p>

<h2>Routes (exclusive; shares total 100%)</h2>
<table><tr><th>Route</th><th class="n">Share</th><th class="n">Review (conditional)</th><th class="n">Expected cost</th><th class="n">Max (calculated)</th><th class="n">Accuracy</th><th>Can the larger model change the outcome?</th></tr>
{% for rt in r.routes %}<tr><td>{{ rt.name }}</td><td class="n">{{ "%.2f"|format(rt.share_pct|float) }}%</td><td class="n">{{ "%.1f"|format(rt.review_pct|float) }}%</td>
<td class="n">{{ fmt(rt.expected_cost, cur) }}</td><td class="n">{{ fmt(rt.max.calculated, cur) if rt.max else "unreachable" }}</td>
<td class="n">{{ fmt(rt.accuracy_pct, cur) }} <span class="ev ev-{{ rt.accuracy_pct.evidence }}">{{ ev_label[rt.accuracy_pct.evidence] }}</span></td>
<td>{% set q = r.decision_value.routes[rt.id] %}{% if q.applies %}<b>{{ q.answer|upper }}</b> — {{ q.detail }}{% else %}<span class="muted">n/a</span>{% endif %}</td></tr>{% endfor %}
</table>

<h2>Bounded maximum and budget</h2>
{% set bc = r.budget.cost %}
<table>
<tr><td>Calculated maximum trajectory cost (variable)</td><td class="n">{{ fmt(bc.calculated_max, cur) }}</td></tr>
<tr><td>Configured per-task budget</td><td class="n">{{ fmt(bc.configured, cur) if bc.configured is not none else "—" }}</td></tr>
<tr><td>Enforcement / check timing</td><td class="n">{{ bc.enforcement }} / {{ bc.check_timing }}</td></tr>
<tr><td>Possible single-call overshoot</td><td class="n">{{ fmt(bc.single_call_overshoot, cur) }}</td></tr>
<tr><td>Effective maximum (variable)</td><td class="n">{{ fmt(bc.effective_max, cur) }}</td></tr>
</table><p class="muted">{{ bc.explanation }}</p>

<h2>Decision value</h2>
<div class="q">{{ r.decision_value.question }}</div>
{% set dv = r.decision_value %}
<table>
<tr><td>Larger-model escalation rate</td><td class="n">{{ fmt(dv.larger_escalation_rate_pct, cur) }}</td></tr>
<tr><td>Larger-model calls that changed the outcome</td><td class="n">{{ fmt(dv.changed_outcome_pct, cur) }}</td></tr>
<tr><td>Cost per changed decision</td><td class="n">{{ fmt(dv.cost_per_changed_decision, cur) }}</td></tr>
<tr><td>Tokens on unchanged decisions / month</td><td class="n">{{ fmt(dv.tokens_on_unchanged_monthly, cur) }}</td></tr>
<tr><td>Avoidable model spend / month</td><td class="n">{{ fmt(dv.avoidable_model_spend_monthly, cur) }}</td></tr>
<tr><td>Tasks sent to a model although review was mandatory / month</td><td class="n">{{ fmt(dv.mandatory_review_model_tasks_monthly, cur) }}</td></tr>
<tr><td>Human reviews prevented / month</td><td class="n">{{ fmt(dv.human_reviews_prevented_monthly, cur) }}{% if dv.human_reviews_prevented_monthly.value is not none %} ({{ "safely" if dv.human_reviews_prevented_safe else "safety not established" }}){% endif %}</td></tr>
</table>

<h2>Accuracy and safety</h2>
<table><tr><th>Measure</th><th class="n">Rate</th><th class="n">Per month</th><th>Status</th></tr>
<tr><td>Overall accuracy</td><td class="n">{{ fmt(r.summary.expected_accuracy_pct, cur) }}</td><td class="n">{{ fmt(r.summary.correct_outcomes_monthly, cur) }} correct</td><td></td></tr>
{% for k,label in safety_rows %}{% set s = dv.safety[k] %}<tr><td>{{ label }}</td><td class="n">{{ fmt(s.rate_pct, cur) }}</td><td class="n">{{ fmt(s.monthly, cur) if s.monthly else "—" }}</td>
<td>{{ s.status.replace("_"," ") }}{% if s.missing_routes %} (missing: {{ s.missing_routes|join(", ") }}){% endif %}</td></tr>{% endfor %}
</table>

{% if r.benchmark %}<h2>Measured benchmark vs. current projection</h2>
<p class="muted">{{ r.benchmark.name }} — {{ r.benchmark.source }}{% if r.benchmark.decisions %} · {{ r.benchmark.decisions }} decisions{% endif %}</p>
<table><tr><th>Metric</th><th class="n">Measured</th><th class="n">Projected</th><th class="n">Difference</th></tr>
{% for row in r.benchmark.rows %}<tr><td>{{ row.label }}</td><td class="n">{{ num(row.measured.value) }} <span class="ev ev-{{ row.measured.evidence }}">{{ ev_label[row.measured.evidence] }}</span></td>
<td class="n">{{ num(row.projected.value) }}{% if row.projected.evidence %} <span class="ev ev-derived">Derived</span>{% endif %}</td>
<td class="n">{% if row.difference_pct is not none %}{{ "%+.1f"|format(row.difference_pct|float) }}%{% else %}—{% endif %}</td></tr>{% endfor %}
</table>{% if r.benchmark.segments %}<p><b>Segments:</b> {% for s in r.benchmark.segments %}{{ s.name }} {{ num(s.accuracy_pct) }}%{% if not loop.last %} · {% endif %}{% endfor %}</p>{% endif %}{% endif %}

<h2>Warnings</h2>
{% for i in r.issues %}<div class="{{ 'err' if i.severity=='error' else 'warn' if i.severity=='warning' else 'info' }}">{{ i.message }}</div>{% else %}<p class="muted">None.</p>{% endfor %}

<p class="muted" style="margin-top:24px">Token price tells you what one model call costs. Outcome Economics Studio tells you what one correct business outcome costs, what it could cost in the worst permitted case, and which architectural changes reduce that cost safely.</p>
</body></html>"""

CARDS = [("expected_cost_per_task", "Expected cost / task"), ("max_cost_per_task", "Maximum bounded cost / task"),
         ("cost_per_correct_task", "Cost / correct governed task"), ("monthly_cost", "Monthly cost"),
         ("daily_cost", "Daily cost (variable)"), ("annual_cost", "Annual cost"),
         ("expected_accuracy_pct", "Expected accuracy"), ("p50_latency_ms", "Median latency"),
         ("expected_tokens_per_task", "Expected tokens / task"), ("max_tokens_per_task", "Max tokens / task"),
         ("larger_calls_monthly", "Larger-model calls / month"), ("human_reviews_monthly", "Human reviews / month")]
SAFETY_ROWS = [("fraud_auto_approved", "Fraud auto-approved"), ("critical_false_approvals", "Critical false approvals"),
               ("incorrect_auto_rejections", "Incorrect automatic rejections"),
               ("unnecessary_human_reviews", "Unnecessary human reviews"),
               ("policy_override_rate", "Policy override rate (of reviews)")]

_env = Environment(autoescape=select_autoescape(default=True))
_tmpl = _env.from_string(TEMPLATE)


def _num(v):
    if v is None:
        return "—"
    d = Decimal(str(v))
    return f"{d:,.2f}" if d != d.to_integral_value() else f"{d:,.0f}"


def render_report(sc: Scenario, results: dict) -> str:
    fixed = sum((results["breakdown_monthly"][k]["value"] for k in results["breakdown_monthly"]
                 if k.startswith("fixed_")), Decimal(0))
    return _tmpl.render(sc=sc, r=results, cur=results["currency"], fmt=fmt, num=_num, cards=CARDS,
                        ev_label=EVIDENCE_LABEL, cat_label=CATEGORY_LABEL, safety_rows=SAFETY_ROWS,
                        fixed_total={"kind": "money", "rounded": fixed, "unbounded": False},
                        now=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
