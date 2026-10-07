"""Side-by-side scenario comparison with deltas against a baseline scenario."""
from __future__ import annotations

from decimal import Decimal

from app.domain.models import Scenario
from app.engine.aggregate import calculate
from app.engine.money import safe_div

# (key, label, (section, key), kind, lower_is_better)
ROWS = [
    ("expected_cost_per_task", "Expected cost per task", ("summary", "expected_cost_per_task"), "unit_money", True),
    ("max_cost_per_task", "Maximum bounded cost per task", ("summary", "max_cost_per_task"), "unit_money", True),
    ("cost_per_correct_task", "Cost per correct governed outcome", ("summary", "cost_per_correct_task"), "unit_money", True),
    ("model_cost_per_1000", "Model cost per 1,000 decisions", ("projection", "model_cost_per_1000"), "unit_money", True),
    ("monthly_cost", "Monthly cost", ("summary", "monthly_cost"), "money", True),
    ("annual_cost", "Annual cost", ("summary", "annual_cost"), "money", True),
    ("expected_accuracy_pct", "Expected accuracy", ("summary", "expected_accuracy_pct"), "pct", False),
    ("p50_latency_ms", "Median latency", ("summary", "p50_latency_ms"), "ms", True),
    ("p95_latency_ms", "P95 latency", ("summary", "p95_latency_ms"), "ms", True),
    ("larger_calls_monthly", "Larger-model calls / month", ("summary", "larger_calls_monthly"), "count_int", True),
    ("larger_tokens_per_task", "Larger-model tokens per task", ("decision_value", "larger_tokens_per_task"),
     "tokens", True),
    ("human_reviews_monthly", "Human reviews / month", ("summary", "human_reviews_monthly"), "count_int", True),
    ("safety_failures_monthly", "Safety failures / month", ("summary", "safety_failures_monthly"), "count", True),
    ("expected_tokens_per_task", "Expected tokens per task", ("summary", "expected_tokens_per_task"), "tokens", True),
]


def _value(res: dict, path: tuple[str, str]):
    section, key = path
    if section == "projection":
        return res["projection"].get(key), False
    m = res[section][key]
    return m["value"], m["unbounded"]


def _num(res: dict, key: str) -> Decimal | None:
    m = res["summary"][key]
    return None if m["value"] is None else Decimal(m["value"])


def headline(base: dict, alt: dict) -> dict:
    """What switching from the baseline to this scenario does, per month."""
    monthly_b, monthly_a = _num(base, "monthly_cost"), _num(alt, "monthly_cost")
    correct_b, correct_a = _num(base, "correct_outcomes_monthly"), _num(alt, "correct_outcomes_monthly")
    d_cost = monthly_a - monthly_b
    d_correct = correct_a - correct_b
    per_correct, verdict = None, "same_correct"
    if d_correct > 0:
        if d_cost > 0:
            per_correct, verdict = d_cost / d_correct, "costs_per_additional_correct"
        else:
            verdict = "dominates"  # cheaper (or equal) and more correct outcomes
    elif d_correct < 0:
        if d_cost < 0:
            per_correct, verdict = d_cost / d_correct, "saves_per_correct_given_up"
        else:
            verdict = "dominated"  # costs the same or more and fewer correct outcomes
    return {
        "monthly_savings": monthly_b - monthly_a,
        "accuracy_difference_pts": _num(alt, "expected_accuracy_pct") - _num(base, "expected_accuracy_pct"),
        "human_reviews_avoided_monthly": _num(base, "human_reviews_monthly") - _num(alt, "human_reviews_monthly"),
        "larger_calls_avoided_monthly": _num(base, "larger_calls_monthly") - _num(alt, "larger_calls_monthly"),
        "correct_outcomes_difference_monthly": d_correct,
        "monthly_cost_difference": d_cost,
        "cost_per_additional_correct": per_correct,
        "verdict": verdict,
    }


def compare(scenarios: list[Scenario]) -> dict:
    results = [calculate(sc) for sc in scenarios]
    base = results[0] if results and results[0].get("ok") else None
    rows = []
    for key, label, path, kind, lower_better in ROWS:
        base_v = _value(base, path)[0] if base else None
        cells = []
        for res in results:
            if not res.get("ok"):
                cells.append({"value": None, "unbounded": False, "error": True})
                continue
            v, unb = _value(res, path)
            delta = delta_pct = better = None
            if v is not None and base_v is not None:
                delta = Decimal(v) - Decimal(base_v)
                delta_pct = safe_div(delta * 100, Decimal(base_v)) if Decimal(base_v) != 0 else None
                if delta != 0:
                    better = (delta < 0) == lower_better
            cells.append({"value": v, "unbounded": unb, "delta": delta, "delta_pct": delta_pct, "better": better})
        rows.append({"key": key, "label": label, "kind": kind, "lower_is_better": lower_better, "cells": cells})
    return {
        "scenarios": [{"id": sc.id, "name": sc.name, "is_sample": sc.is_sample, "ok": res.get("ok", False),
                       "issues": res.get("issues", [])} for sc, res in zip(scenarios, results)],
        "baseline": scenarios[0].name if scenarios else None,
        "vs_baseline": [None if (i == 0 or not base or not res.get("ok")) else headline(base, res)
                        for i, res in enumerate(results)],
        "assumptions": [res.get("evidence_basis") if res.get("ok") else None for res in results],
        "rows": rows,
        "currency": scenarios[0].workload.currency if scenarios else "USD",
        "charts": [{"name": sc.name,
                    "expected_cost_per_task": res["summary"]["expected_cost_per_task"]["value"],
                    "max_cost_per_task": res["summary"]["max_cost_per_task"]["value"],
                    "max_unbounded": res["summary"]["max_cost_per_task"]["unbounded"],
                    "model_cost_per_1000": res["projection"]["model_cost_per_1000"],
                    "monthly_cost": res["summary"]["monthly_cost"]["value"],
                    "accuracy_pct": res["summary"]["expected_accuracy_pct"]["value"],
                    "breakdown_monthly": {k: v["value"] for k, v in res["breakdown_monthly"].items()}}
                   for sc, res in zip(scenarios, results) if res.get("ok")],
    }
