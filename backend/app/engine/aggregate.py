"""Scenario calculator: turns a Scenario into the full results payload."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from app.domain.models import Scenario
from app.engine import latency as lat
from app.engine.benchmark import compare_benchmark
from app.engine.bound import Bound
from app.engine.budget import evaluate_budget
from app.engine.decision_value import decision_value
from app.engine.features import effective
from app.engine.money import HUNDRED, ZERO, pct, round_money, round_unit, safe_div
from app.engine.routes import (CATEGORIES, RouteMax, effective_review_pct, expected_route, is_model_eligible,
                               max_route, stage_avg_calls)
from app.validation.checks import evidence_basis, validate

VOLUME_MULTIPLIERS = [Decimal(x) for x in ("0.25", "0.5", "1", "2", "4", "8")]


# ------------------------------------------------------------------ metric envelope
def metric(value, kind: str, currency: str = "USD", evidence: str = "derived", note: str = "",
           bound: Bound | None = None) -> dict:
    """Uniform envelope: exact value, display-rounded value, evidence label, unbounded flag."""
    reasons: list[str] = []
    unbounded = False
    if bound is not None:
        if bound.bounded:
            value = bound.value
        else:
            value, unbounded, reasons = None, True, list(bound.reasons)
    return {"value": value, "rounded": _round(value, kind, currency), "kind": kind, "evidence": evidence,
            "note": note, "unbounded": unbounded, "reasons": reasons}


def _round(v, kind, currency):
    if v is None:
        return None
    v = Decimal(v)
    if kind == "money":
        return round_money(v, currency)
    if kind == "unit_money":
        return round_unit(v)
    if kind in ("tokens", "ms", "count_int"):
        return v.quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ------------------------------------------------------------------ latency
def route_latency(sc: Scenario, r) -> tuple[float | None, float | None, str]:
    if r.direct_human:
        return None, None, "excluded"
    if r.p50_latency_ms is not None:
        p50 = float(r.p50_latency_ms)
        p95 = float(r.p95_latency_ms) if r.p95_latency_ms is not None else p50
        return p50, p95, r.ev("p50_latency_ms").value
    p50 = p95 = float(r.rule_latency_ms) if (r.deterministic_rule or not r.stages) else 0.0
    for s in r.stages:
        m = sc.model_by_id(s.model_id)
        calls = float(stage_avg_calls(s, m))
        p50 += float(m.p50_latency_ms) * calls
        p95 += float(m.p95_latency_ms) * max(calls, 1.0)
    return p50, p95, "derived"


# ------------------------------------------------------------------ main
def calculate(sc: Scenario) -> dict:
    sc = effective(sc)
    issues = [i.dict() for i in validate(sc)]
    if any(i["severity"] == "error" for i in issues):
        return {"ok": False, "issues": issues}

    wl, c = sc.workload, sc.costs
    cur = wl.currency
    weights = {r.id: pct(r.share_pct) for r in sc.routes}
    reachable = [r for r in sc.routes if r.share_pct > 0]
    exp = {r.id: expected_route(sc, r) for r in sc.routes}
    mx: dict[str, RouteMax] = {r.id: max_route(sc, r) for r in reachable}

    # ---- expected (share-weighted over exclusive routes)
    cats = {k: sum((weights[r.id] * exp[r.id].categories[k] for r in sc.routes), ZERO) for k in CATEGORIES}
    variable = sum(cats.values(), ZERO)
    monthly_tasks = wl.tasks_per_day * wl.operating_days_per_month
    fixed_parts = {"infrastructure": c.fixed_infra_monthly, "observability": c.observability_monthly,
                   "other_fixed": c.other_fixed_monthly}
    fixed_monthly = sum(fixed_parts.values(), ZERO)
    allocated = safe_div(fixed_monthly, monthly_tasks) or ZERO
    expected_task = variable + allocated
    daily = variable * wl.tasks_per_day
    monthly = daily * wl.operating_days_per_month + fixed_monthly
    growth = pct(wl.annual_growth_pct)
    monthly_factor = (Decimal(1) + growth) ** (Decimal(1) / Decimal(12)) if growth else Decimal(1)
    schedule = []
    for i in range(12):
        f = monthly_factor ** i
        schedule.append({"month": i + 1, "tasks": monthly_tasks * f,
                         "cost": daily * wl.operating_days_per_month * f + fixed_monthly})
    annual = sum((m["cost"] for m in schedule), ZERO)
    accuracy = sum((weights[r.id] * pct(r.accuracy_pct) for r in sc.routes), ZERO)
    correct_monthly = monthly_tasks * accuracy
    cost_per_correct = safe_div(monthly, correct_monthly)
    tokens_task = sum((weights[r.id] * exp[r.id].tokens for r in sc.routes), ZERO)
    calls_task = sum((weights[r.id] * exp[r.id].model_calls for r in sc.routes), ZERO)
    reviews_task = sum((weights[r.id] * exp[r.id].reviews for r in sc.routes), ZERO)
    tool_calls_task = sum((weights[r.id] * exp[r.id].tool_calls for r in sc.routes), ZERO)

    # ---- bounded maximum (reachable routes only, stage by stage)
    largest_cost = Bound.of(0)
    largest_tokens = Bound.of(0)
    for r in reachable:
        largest_cost = largest_cost.max(mx[r.id].largest_single_call_cost)
        largest_tokens = largest_tokens.max(mx[r.id].largest_single_call_tokens)
    b = sc.budget
    cost_budget = evaluate_budget(b.max_monetary_budget_per_task, b, largest_cost, "cost")
    token_budget = evaluate_budget(b.max_token_budget_per_task, b, largest_tokens, "token")
    calc_max = Bound.of(0)
    eff_max = Bound.of(0)
    calc_tokens = Bound.of(0)
    route_calc: list[tuple[str, Bound]] = []
    route_rows = []
    route_lat: list[lat.RouteLatency] = []
    for r in sc.routes:
        e = exp[r.id]
        m = mx.get(r.id)
        p50, p95, lat_ev = route_latency(sc, r)
        if r.share_pct > 0 and p50 is not None:
            route_lat.append(lat.RouteLatency(float(weights[r.id]), p50, p95))
        row = {
            "id": r.id, "name": r.name, "share_pct": r.share_pct, "share_evidence": r.ev("share_pct").value,
            "reachable": r.share_pct > 0, "model_eligible": is_model_eligible(r),
            "review_pct": effective_review_pct(r), "review_evidence": r.ev("human_review_pct").value,
            "human_review_mandatory": r.human_review_mandatory, "direct_human": r.direct_human,
            "expected_cost": metric(e.total, "unit_money", cur),
            "contribution": metric(weights[r.id] * e.total, "unit_money", cur),
            "categories": {k: metric(v, "unit_money", cur) for k, v in e.categories.items()},
            "tokens": metric(e.tokens, "tokens"), "model_calls": metric(e.model_calls, "count"),
            "accuracy_pct": metric(r.accuracy_pct, "pct", evidence=r.ev("accuracy_pct").value),
            "p50_latency_ms": metric(p50, "ms", evidence=lat_ev) if p50 is not None else None,
            "p95_latency_ms": metric(p95, "ms", evidence=lat_ev) if p95 is not None else None,
            "stages": [{"model": s.model_name, "tier": s.tier.value, "calls": metric(s.calls, "count"),
                        "cost": metric(s.model_cost + s.subagent_cost, "unit_money", cur)} for s in e.stages],
        }
        if m is not None:
            calc_total = m.total
            eff_total = m.automated_cost.min(cost_budget.automated_cap) + m.non_automated_cost
            calc_max = calc_max.max(calc_total)
            eff_max = eff_max.max(eff_total)
            calc_tokens = calc_tokens.max(m.tokens)
            route_calc.append((r.name, calc_total))
            row["max"] = {
                "calculated": metric(None, "unit_money", cur, bound=calc_total),
                "effective": metric(None, "unit_money", cur, bound=eff_total),
                "automated": metric(None, "unit_money", cur, bound=m.automated_cost),
                "non_automated": metric(None, "unit_money", cur, bound=m.non_automated_cost),
                "tokens": metric(None, "tokens", bound=m.tokens),
                "notes": m.notes,
                "stages": [{
                    "model": s.model_name, "tier": s.tier.value,
                    "max_input_context": metric(None, "tokens", bound=s.max_input_context),
                    "max_tokens_per_call": metric(None, "tokens", bound=s.max_tokens_per_call),
                    "max_attempts": metric(None, "count_int", bound=s.max_attempts),
                    "max_tokens": metric(None, "tokens", bound=s.max_tokens),
                    "max_call_cost": metric(None, "unit_money", cur, bound=s.max_call_cost),
                    "model_cost": metric(None, "unit_money", cur, bound=s.model_cost),
                    "tool_cost": metric(None, "unit_money", cur, bound=s.tool_cost),
                    "subagent_cost": metric(None, "unit_money", cur, bound=s.subagent_cost),
                } for s in m.stages],
            }
        route_rows.append(row)
    unbounded_routes = [n for n, bd in route_calc if not bd.bounded]
    if unbounded_routes:
        worst_route = ", ".join(unbounded_routes)
    else:
        worst_route = max(route_calc, key=lambda t: t[1].value)[0] if route_calc else None
    eff_tokens = calc_tokens.min(token_budget.automated_cap)
    fully_loaded_max = eff_max + Bound.of(allocated)
    p50_all = lat.mixture_quantile(route_lat, 0.5)
    p95_all = lat.mixture_quantile(route_lat, 0.95)

    dv = decision_value(sc, weights, exp, monthly_tasks)
    model_task = cats["lightweight_model"] + cats["larger_model"]
    basis = evidence_basis(sc)

    # ---- projection used for measured-vs-projected comparison
    def per_1000(v):
        return None if v is None else v * Decimal(1000)
    projected = {
        "model_cost_per_1000": model_task * 1000,
        "accuracy_pct": accuracy * HUNDRED,
        "p50_latency_ms": Decimal(str(round(p50_all, 1))) if p50_all is not None else None,
        "p95_latency_ms": Decimal(str(round(p95_all, 1))) if p95_all is not None else None,
        "larger_calls_per_1000": dv["larger_calls_per_task"] * 1000,
        "larger_avoided_per_1000": dv["larger_calls_avoided_per_task"] * 1000,
        "human_reviews_per_1000": reviews_task * 1000,
        "fraud_per_1000": per_1000(dv["safety"]["fraud_auto_approved"]["per_task"]),
        "critical_per_1000": per_1000(dv["safety"]["critical_false_approvals"]["per_task"]),
    }

    def m_(v, kind="unit_money", **kw):
        return metric(v, kind, cur, **kw)

    safety = dv["safety"]
    safety_monthly_known = [safety[k]["monthly"] for k in ("fraud_auto_approved", "critical_false_approvals")
                            if safety[k]["monthly"] is not None]
    results = {
        "ok": True,
        "currency": cur,
        "issues": issues,
        "evidence_basis": basis,
        "summary": {
            "expected_cost_per_task": m_(expected_task, note="Variable cost + allocated fixed cost"),
            "variable_cost_per_task": m_(variable),
            "allocated_fixed_per_task": m_(allocated, note="Allocation of monthly fixed cost across monthly volume "
                                                          "- not a directly measured per-task charge"),
            "max_cost_per_task": m_(None, bound=fully_loaded_max,
                                   note="Worst permitted case across reachable routes, incl. allocated fixed cost"),
            "calculated_max_variable_per_task": m_(None, bound=calc_max,
                                                   note="Calculated maximum trajectory cost (before budget)"),
            "effective_max_variable_per_task": m_(None, bound=eff_max,
                                                  note="After fail-closed budget enforcement, if any"),
            "worst_route": worst_route,
            "cost_per_correct_task": m_(cost_per_correct, note="Monthly operating cost / correct outcomes"),
            "daily_cost": m_(daily, "money", note="Variable cost only; fixed cost is added monthly"),
            "monthly_cost": m_(monthly, "money"),
            "annual_cost": m_(annual, "money", note="12-month projection with monthly compounded growth"
                              if growth else "Monthly cost x 12 (no growth configured)"),
            "monthly_tasks": m_(monthly_tasks, "count_int"),
            "expected_tokens_per_task": m_(tokens_task, "tokens"),
            "max_tokens_per_task": m_(None, "tokens", bound=eff_tokens),
            "calculated_max_tokens_per_task": m_(None, "tokens", bound=calc_tokens),
            "model_calls_per_task": m_(calls_task, "count"),
            "tool_calls_per_task": m_(tool_calls_task, "count"),
            "larger_calls_monthly": m_(dv["larger_calls_per_task"] * monthly_tasks, "count_int"),
            "larger_calls_avoided_monthly": m_(dv["larger_calls_avoided_per_task"] * monthly_tasks, "count_int",
                                               note="vs. one larger-model call per model-eligible task"),
            "model_free_decisions_monthly": m_(dv["model_free_share"] * monthly_tasks, "count_int"),
            "human_reviews_monthly": m_(reviews_task * monthly_tasks, "count_int"),
            "human_review_share_pct": m_(reviews_task * HUNDRED, "pct"),
            "p50_latency_ms": m_(p50_all, "ms", note="Automated decision latency (lognormal mixture of route "
                                                   "P50/P95); human-review turnaround excluded"),
            "p95_latency_ms": m_(p95_all, "ms"),
            "expected_accuracy_pct": m_(accuracy * HUNDRED, "pct"),
            "correct_outcomes_monthly": m_(correct_monthly, "count_int"),
            "safety_failures_monthly": m_(sum(safety_monthly_known, ZERO) if safety_monthly_known else None,
                                          "count", note="Fraud auto-approved + critical false approvals"
                                          + ("" if safety["fraud_auto_approved"]["status"] == "complete" and
                                             safety["critical_false_approvals"]["status"] == "complete"
                                             else " (incomplete: not measured on every route)")),
            "target_accuracy_pct": m_(wl.target_accuracy_pct, "pct", evidence=wl.ev("target_accuracy_pct").value),
            "meets_target_accuracy": accuracy * HUNDRED >= wl.target_accuracy_pct,
            "meets_latency": (None if wl.max_latency_ms is None or p50_all is None
                              else Decimal(str(p50_all)) <= wl.max_latency_ms),
            "peak_larger_calls_per_minute": m_(wl.peak_tasks_per_minute * dv["larger_calls_per_task"]
                                               if wl.peak_tasks_per_minute else None, "count"),
        },
        "breakdown_per_task": {**{k: m_(v) for k, v in cats.items()},
                               "infrastructure": m_(allocated, note="Allocated")},
        "breakdown_monthly": {**{k: m_(v * monthly_tasks, "money") for k, v in cats.items()},
                              **{f"fixed_{k}": m_(v, "money") for k, v in fixed_parts.items()}},
        "budget": {
            "cost": {"configured": b.max_monetary_budget_per_task, "enforcement": b.enforcement.value,
                     "check_timing": b.check_timing.value,
                     "calculated_max": m_(None, bound=calc_max),
                     "single_call_overshoot": m_(None, bound=cost_budget.single_call_overshoot),
                     "effective_max": m_(None, bound=eff_max),
                     "is_hard_bound": cost_budget.is_hard_bound,
                     "soft_bound": m_(None, bound=cost_budget.soft_bound) if cost_budget.soft_bound else None,
                     "explanation": cost_budget.explanation},
            "tokens": {"configured": b.max_token_budget_per_task,
                       "calculated_max": m_(None, "tokens", bound=calc_tokens),
                       "single_call_overshoot": m_(None, "tokens", bound=token_budget.single_call_overshoot),
                       "effective_max": m_(None, "tokens", bound=eff_tokens),
                       "is_hard_bound": token_budget.is_hard_bound, "explanation": token_budget.explanation},
            "max_execution_time_s": b.max_execution_time_s,
        },
        "routes": route_rows,
        "decision_value": {
            "question": dv["question"],
            "larger_escalation_rate_pct": m_(dv["larger_escalation_rate"] * HUNDRED, "pct"),
            "larger_calls_per_task": m_(dv["larger_calls_per_task"], "count"),
            "larger_cost_per_task": m_(dv["larger_cost_per_task"]),
            "larger_tokens_per_task": m_(dv["larger_tokens_per_task"], "tokens"),
            "changed_outcome_pct": m_(None if dv["changed_outcome_share_of_larger"] is None
                                      else dv["changed_outcome_share_of_larger"] * HUNDRED, "pct",
                                      note="" if dv["avoidable_spend_complete"] else
                                      "Not measured on every escalating route"),
            "cost_per_changed_decision": m_(dv["cost_per_changed_decision"]),
            "tokens_on_unchanged_monthly": m_(None if dv["tokens_on_unchanged_decisions_per_task"] is None else
                                              dv["tokens_on_unchanged_decisions_per_task"] * monthly_tasks, "tokens"),
            "avoidable_model_spend_monthly": m_(None if dv["avoidable_model_spend_per_task"] is None else
                                                dv["avoidable_model_spend_per_task"] * monthly_tasks, "money"),
            "mandatory_review_model_tasks_monthly": m_(dv["mandatory_review_model_share"] * monthly_tasks,
                                                       "count_int"),
            "mandatory_review_model_spend_monthly": m_(dv["mandatory_review_model_spend_per_task"] * monthly_tasks,
                                                       "money"),
            "human_reviews_prevented_monthly": m_(None if dv["human_reviews_prevented_per_task"] is None else
                                                  dv["human_reviews_prevented_per_task"] * monthly_tasks,
                                                  "count_int"),
            "human_reviews_prevented_safe": dv["human_reviews_prevented_safe"],
            "larger_calls_avoided_per_task": m_(dv["larger_calls_avoided_per_task"], "count"),
            "safety": {k: {"rate_pct": m_(None if v["per_task"] is None else v["per_task"] * HUNDRED, "pct",
                                          evidence=",".join(v["evidence"]) or "derived"),
                           "monthly": m_(v.get("monthly"), "count") if "monthly" in v else None,
                           "status": v["status"], "missing_routes": v["missing_routes"]}
                       for k, v in safety.items()},
            "routes": dv["routes"],
        },
        "charts": {
            "cost_by_category_monthly": [{"category": k, "value": v * monthly_tasks} for k, v in cats.items()]
                                        + [{"category": "infrastructure (fixed)", "value": fixed_monthly}],
            "cost_by_route": [{"route": r.name, "contribution": weights[r.id] * exp[r.id].total,
                               "unit_cost": exp[r.id].total} for r in sc.routes],
            "expected_vs_max": {"expected": expected_task,
                                "max": fully_loaded_max.value, "max_unbounded": not fully_loaded_max.bounded},
            "monthly_by_volume": [{"multiplier": mul, "tasks": monthly_tasks * mul,
                                   "monthly_cost": variable * monthly_tasks * mul + fixed_monthly,
                                   "cost_per_task": variable + fixed_monthly / (monthly_tasks * mul)}
                                  for mul in VOLUME_MULTIPLIERS],
            "model_vs_human_monthly": {"model": model_task * monthly_tasks,
                                       "human": cats["human_review"] * monthly_tasks},
            "growth_schedule": schedule,
        },
        "projection": projected,
        "benchmark": compare_benchmark(sc.benchmark, projected) if sc.benchmark else None,
    }
    return results
