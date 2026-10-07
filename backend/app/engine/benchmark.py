"""Measured benchmark vs. modelled projection.

The imported benchmark is frozen. The projection is recalculated from the
scenario's editable inputs. Both are shown side by side with the difference,
and each side keeps its own evidence label.
"""
from __future__ import annotations

from decimal import Decimal

from app.domain.models import MeasuredBenchmark
from app.engine.money import safe_div

THOUSAND = Decimal(1000)

# key -> (label, unit, normalize counts per 1,000 decisions?, projection key)
METRICS: dict[str, tuple[str, str, bool, str | None]] = {
    "model_cost_per_1000_decisions": ("Model cost per 1,000 decisions", "currency", False, "model_cost_per_1000"),
    "accuracy_pct": ("Accuracy", "%", False, "accuracy_pct"),
    "p50_latency_ms": ("Median latency", "ms", False, "p50_latency_ms"),
    "p95_latency_ms": ("P95 latency", "ms", False, "p95_latency_ms"),
    "larger_model_calls": ("Larger-model calls per 1,000 decisions", "calls", True, "larger_calls_per_1000"),
    "larger_model_calls_avoided": ("Larger-model calls avoided per 1,000 decisions", "calls", True,
                                   "larger_avoided_per_1000"),
    "human_reviews": ("Human reviews per 1,000 decisions", "reviews", True, "human_reviews_per_1000"),
    "fraud_auto_approved": ("Fraud auto-approved per 1,000 decisions", "cases", True, "fraud_per_1000"),
    "critical_false_approvals": ("Critical false approvals per 1,000 decisions", "cases", True, "critical_per_1000"),
    "larger_model_token_reduction_pct": ("Larger-model token reduction vs. baseline", "%", False, None),
    "model_cost_reduction_pct": ("Model cost reduction vs. baseline", "%", False, None),
}


def compare_benchmark(bm: MeasuredBenchmark, projected: dict[str, Decimal | None]) -> dict:
    rows = []
    for key, mv in bm.metrics.items():
        label, unit, per_1000, pkey = METRICS.get(key, (key, mv.unit, False, None))
        measured = mv.value
        measured_norm = measured
        if per_1000 and measured is not None:
            measured_norm = safe_div(measured * THOUSAND, Decimal(bm.decisions)) if bm.decisions else None
        proj = projected.get(pkey) if pkey else None
        diff = diff_pct = None
        if measured_norm is not None and proj is not None:
            diff = proj - measured_norm
            diff_pct = safe_div(diff * 100, measured_norm) if measured_norm != 0 else None
        rows.append({
            "key": key, "label": label, "unit": unit,
            "measured": {"raw": measured, "value": measured_norm, "evidence": mv.evidence.value,
                         "source": bm.source, "note": mv.note},
            "projected": {"value": proj, "evidence": "derived" if proj is not None else None,
                          "note": "" if pkey else "Relative to a baseline architecture - compare scenarios to project."},
            "difference": diff, "difference_pct": diff_pct,
        })
    segments = [{"name": s.name, "decisions": s.decisions, "accuracy_pct": s.accuracy_pct,
                 "evidence": s.evidence.value} for s in bm.segments]
    return {"name": bm.name, "source": bm.source, "run_date": bm.run_date, "is_sample": bm.is_sample,
            "decisions": bm.decisions, "rows": rows, "segments": segments}
