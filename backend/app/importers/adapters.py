"""Benchmark import adapters.

Three input shapes are supported (see docs/import-schema.md):

1. **Benchmark JSON** - summary metrics, optional segments, optional measured
   route and model statistics.
2. **Metrics CSV** - one row per metric: ``metric,value,unit,evidence,note``
   plus optional metadata rows (``benchmark_name``, ``source``, ``run_date``,
   ``decisions``).
3. **Decision-level CSV** - one row per evaluated decision (``route_id`` and
   ``correct`` required). Aggregated into measured route shares, accuracy,
   latency, review rates, changed-outcome rates, safety rates and a benchmark.

Every import produces an immutable ``MeasuredBenchmark``. Measured route/model
statistics are returned separately and are only written into scenario inputs
when the caller asks (``apply_to_inputs``); they are labelled ``measured``.
"""
from __future__ import annotations

import csv
import io
import json
import math
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from app.domain.models import Evidence, MeasuredBenchmark, MeasuredValue, Scenario, Segment

SCHEMA_VERSION = "1.0"
ROUTE_FIELDS = {"share_pct", "accuracy_pct", "p50_latency_ms", "p95_latency_ms", "human_review_pct",
                "larger_changed_outcome_pct"}
SAFETY_FIELDS = {"fraud_auto_approval_pct", "critical_false_approval_pct", "incorrect_auto_rejection_pct",
                 "unnecessary_review_pct", "policy_override_pct"}
MODEL_FIELDS = {"avg_input_tokens", "avg_output_tokens", "avg_reasoning_tokens", "retry_rate_pct",
                "cached_input_share_pct", "p50_latency_ms", "p95_latency_ms", "avg_calls_per_task"}
TRUE = {"1", "true", "yes", "y", "t"}


class ImportError_(ValueError):
    pass


@dataclass
class ImportResult:
    benchmark: MeasuredBenchmark
    route_updates: dict[str, dict] = field(default_factory=dict)   # route id -> {field: value}
    model_updates: dict[str, dict] = field(default_factory=dict)   # model id -> {field: value}
    warnings: list[str] = field(default_factory=list)
    kind: str = ""

    def summary(self) -> dict:
        return {"kind": self.kind, "benchmark": self.benchmark.model_dump(mode="json"),
                "route_updates": {k: {f: str(v) for f, v in d.items()} for k, d in self.route_updates.items()},
                "model_updates": {k: {f: str(v) for f, v in d.items()} for k, d in self.model_updates.items()},
                "warnings": self.warnings}


def _dec(v, where: str) -> Decimal | None:
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return None
    try:
        return Decimal(str(v).strip())
    except (InvalidOperation, ValueError):
        raise ImportError_(f"{where}: '{v}' is not a number")


# ------------------------------------------------------------------ JSON
def parse_benchmark_json(text: str) -> ImportResult:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ImportError_(f"Invalid JSON: {e}")
    if "benchmark" not in data:
        raise ImportError_("Benchmark JSON must contain a 'benchmark' object (see docs/import-schema.md).")
    b = data["benchmark"]
    if not b.get("name"):
        raise ImportError_("benchmark.name is required.")
    metrics = {}
    for key, v in (b.get("metrics") or {}).items():
        if isinstance(v, dict):
            metrics[key] = MeasuredValue(value=_dec(v.get("value"), f"metric {key}"), unit=v.get("unit", ""),
                                         evidence=Evidence(v.get("evidence", "measured")), note=v.get("note", ""))
        else:
            metrics[key] = MeasuredValue(value=_dec(v, f"metric {key}"))
    segments = [Segment(name=s["name"], decisions=s.get("decisions"),
                        accuracy_pct=_dec(s.get("accuracy_pct"), f"segment {s.get('name')}"))
                for s in b.get("segments") or []]
    bm = MeasuredBenchmark(name=b["name"], source=b.get("source", ""), run_date=b.get("run_date", ""),
                           is_sample=bool(b.get("is_sample", False)), decisions=b.get("decisions"),
                           metrics=metrics, segments=segments)
    res = ImportResult(benchmark=bm, kind="benchmark_json")
    if data.get("schema_version") not in (None, SCHEMA_VERSION):
        res.warnings.append(f"schema_version {data.get('schema_version')} differs from {SCHEMA_VERSION}")
    for r in data.get("routes") or []:
        if "id" not in r:
            raise ImportError_("Each route entry needs an 'id' matching a scenario route.")
        upd = {k: _dec(r[k], f"route {r['id']}.{k}") for k in ROUTE_FIELDS if r.get(k) is not None}
        for k, v in (r.get("safety") or {}).items():
            if k in SAFETY_FIELDS and v is not None:
                upd[f"safety.{k}"] = _dec(v, f"route {r['id']}.safety.{k}")
        res.route_updates[r["id"]] = upd
    for m in data.get("models") or []:
        if "id" not in m:
            raise ImportError_("Each model entry needs an 'id' matching a scenario model.")
        res.model_updates[m["id"]] = {k: _dec(m[k], f"model {m['id']}.{k}") for k in MODEL_FIELDS
                                      if m.get(k) is not None}
    return res


# ------------------------------------------------------------------ CSV
def parse_csv(text: str, name: str = "Imported benchmark") -> ImportResult:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    cols = {c.strip().lower() for c in (reader.fieldnames or [])}
    rows = [{(k or "").strip().lower(): (v or "").strip() for k, v in r.items()} for r in reader]
    if {"metric", "value"} <= cols:
        return _parse_metrics_csv(rows, name)
    if {"route_id", "correct"} <= cols:
        return _parse_decisions_csv(rows, name)
    raise ImportError_("Unrecognised CSV. Use a metrics CSV (columns: metric,value[,unit,evidence,note]) or a "
                       "decision-level CSV (columns: route_id,correct[,...]). See docs/import-schema.md.")


def _parse_metrics_csv(rows: list[dict], name: str) -> ImportResult:
    meta = {"benchmark_name": name, "source": "", "run_date": "", "decisions": None}
    metrics = {}
    for i, r in enumerate(rows, start=2):
        key = r["metric"]
        if not key:
            continue
        if key in meta:
            meta[key] = r["value"]
            continue
        metrics[key] = MeasuredValue(value=_dec(r["value"], f"row {i} ({key})"), unit=r.get("unit", ""),
                                     evidence=Evidence(r.get("evidence") or "measured"), note=r.get("note", ""))
    decisions = int(meta["decisions"]) if meta["decisions"] else None
    bm = MeasuredBenchmark(name=meta["benchmark_name"], source=meta["source"], run_date=meta["run_date"],
                           decisions=decisions, metrics=metrics)
    return ImportResult(benchmark=bm, kind="metrics_csv")


def _quantile(values: list[float], q: float) -> float:
    s = sorted(values)
    if not s:
        return math.nan
    pos = (len(s) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def _flag(v: str) -> bool:
    return v.strip().lower() in TRUE


def _parse_decisions_csv(rows: list[dict], name: str) -> ImportResult:
    if not rows:
        raise ImportError_("Decision CSV has no rows.")
    n = len(rows)
    by_route: dict[str, list[dict]] = {}
    for r in rows:
        if not r["route_id"]:
            raise ImportError_("Every decision row needs a route_id.")
        by_route.setdefault(r["route_id"], []).append(r)
    has = lambda c: c in rows[0]  # noqa: E731
    warnings: list[str] = []
    route_updates: dict[str, dict] = {}
    counts = {rid: len(rs) for rid, rs in by_route.items()}
    # exact shares with 4 dp, remainder assigned to the largest route so the total is exactly 100
    shares = {rid: (Decimal(c) * 100 / Decimal(n)).quantize(Decimal("0.0001")) for rid, c in counts.items()}
    gap = Decimal(100) - sum(shares.values())
    if gap:
        largest = max(counts, key=counts.get)
        shares[largest] += gap

    def rate(rs, col):
        return Decimal(sum(1 for r in rs if _flag(r[col]))) * 100 / Decimal(len(rs))

    for rid, rs in by_route.items():
        upd: dict[str, Decimal] = {"share_pct": shares[rid], "accuracy_pct": rate(rs, "correct")}
        if has("latency_ms"):
            lats = [float(r["latency_ms"]) for r in rs if r["latency_ms"]]
            if lats:
                upd["p50_latency_ms"] = Decimal(str(round(_quantile(lats, 0.5), 1)))
                upd["p95_latency_ms"] = Decimal(str(round(_quantile(lats, 0.95), 1)))
        if has("human_reviewed"):
            upd["human_review_pct"] = rate(rs, "human_reviewed")
        if has("larger_model_called") and has("outcome_changed"):
            esc = [r for r in rs if _flag(r["larger_model_called"])]
            if esc:
                upd["larger_changed_outcome_pct"] = rate(esc, "outcome_changed")
        for col, fld in (("fraud_auto_approved", "fraud_auto_approval_pct"),
                         ("critical_false_approval", "critical_false_approval_pct"),
                         ("incorrect_auto_rejection", "incorrect_auto_rejection_pct")):
            if has(col):
                upd[f"safety.{fld}"] = rate(rs, col)
        route_updates[rid] = upd

    metrics: dict[str, MeasuredValue] = {
        "accuracy_pct": MeasuredValue(value=rate(rows, "correct"), unit="%")}
    if has("latency_ms"):
        lats = [float(r["latency_ms"]) for r in rows if r["latency_ms"]]
        if lats:
            metrics["p50_latency_ms"] = MeasuredValue(value=Decimal(str(round(_quantile(lats, 0.5), 1))), unit="ms")
            metrics["p95_latency_ms"] = MeasuredValue(value=Decimal(str(round(_quantile(lats, 0.95), 1))), unit="ms")
    if has("larger_model_called"):
        metrics["larger_model_calls"] = MeasuredValue(
            value=Decimal(sum(1 for r in rows if _flag(r["larger_model_called"]))), unit="calls")
    if has("human_reviewed"):
        metrics["human_reviews"] = MeasuredValue(
            value=Decimal(sum(1 for r in rows if _flag(r["human_reviewed"]))), unit="reviews")
    for col, key in (("fraud_auto_approved", "fraud_auto_approved"),
                     ("critical_false_approval", "critical_false_approvals")):
        if has(col):
            metrics[key] = MeasuredValue(value=Decimal(sum(1 for r in rows if _flag(r[col]))), unit="cases")
    if has("model_cost"):
        total = sum((_dec(r["model_cost"], "model_cost") or Decimal(0) for r in rows), Decimal(0))
        metrics["model_cost_per_1000_decisions"] = MeasuredValue(value=total * 1000 / Decimal(n), unit="currency")
    segments = []
    if has("segment"):
        seg: dict[str, list[dict]] = {}
        for r in rows:
            seg.setdefault(r["segment"] or "(none)", []).append(r)
        segments = [Segment(name=k, decisions=len(v), accuracy_pct=rate(v, "correct")) for k, v in seg.items()]
    bm = MeasuredBenchmark(name=name, source="Decision-level CSV import", decisions=n, metrics=metrics,
                           segments=segments)
    return ImportResult(benchmark=bm, route_updates=route_updates, warnings=warnings, kind="decisions_csv")


# ------------------------------------------------------------------ apply
def apply_import(sc: Scenario, res: ImportResult, apply_to_inputs: bool) -> tuple[Scenario, list[str]]:
    """Attach the frozen benchmark; optionally write measured stats into inputs (labelled measured)."""
    sc = sc.model_copy(deep=True)
    sc.benchmark = res.benchmark
    notes = list(res.warnings)
    if not apply_to_inputs:
        return sc, notes
    route_ids = {r.id for r in sc.routes}
    unknown = [rid for rid in res.route_updates if rid not in route_ids]
    if unknown:
        raise ImportError_(f"Imported route ids not found in scenario: {', '.join(unknown)}. "
                           f"Scenario routes: {', '.join(sorted(route_ids))}.")
    if res.kind == "decisions_csv":
        # traffic that did not appear in the measured sample went nowhere
        for r in sc.routes:
            if r.id not in res.route_updates:
                r.share_pct = Decimal(0)
                r.evidence = {**r.evidence, "share_pct": Evidence.MEASURED}
                notes.append(f"Route '{r.name}' had no decisions in the import; its share is set to 0%.")
    for r in sc.routes:
        upd = res.route_updates.get(r.id)
        if not upd:
            continue
        for k, v in upd.items():
            if k.startswith("safety."):
                f = k.split(".", 1)[1]
                setattr(r.safety, f, v)
                r.safety.evidence = {**r.safety.evidence, f: Evidence.MEASURED}
            else:
                setattr(r, k, v)
                r.evidence = {**r.evidence, k: Evidence.MEASURED}
    model_ids = {m.id for m in sc.models}
    for mid, upd in res.model_updates.items():
        if mid not in model_ids:
            notes.append(f"Model '{mid}' is not in the scenario; its measured values were skipped.")
            continue
        m = sc.model_by_id(mid)
        for k, v in upd.items():
            setattr(m, k, v)
            m.evidence = {**m.evidence, k: Evidence.MEASURED}
    return sc, notes
