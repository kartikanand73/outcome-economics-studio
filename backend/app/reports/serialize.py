"""Serialisation helpers: Decimal-safe JSON and results CSV."""
from __future__ import annotations

import csv
import io
import json
from decimal import Decimal

MAX_PLACES = Decimal("1e-10")


def dec_str(d: Decimal) -> str:
    """Exact-enough string: integers stay integers, long repeating decimals are cut at 10 places."""
    if d == d.to_integral_value():
        return format(d.quantize(Decimal(1)), "f")
    if d.as_tuple().exponent < -10:
        d = d.quantize(MAX_PLACES)
    return format(d.normalize(), "f")


def _default(o):
    if isinstance(o, Decimal):
        return dec_str(o)
    if hasattr(o, "model_dump"):
        return o.model_dump(mode="json")
    raise TypeError(f"Not serialisable: {type(o)}")


def dumps(obj) -> str:
    return json.dumps(obj, default=_default)


def jsonable(obj):
    return json.loads(dumps(obj))


def _flatten_metrics(prefix: str, d: dict, rows: list):
    for k, v in d.items():
        if isinstance(v, dict) and "kind" in v and "evidence" in v:
            rows.append([prefix, k, v["value"], v["rounded"], v["kind"], v["evidence"],
                         "unbounded" if v["unbounded"] else "", "; ".join(v.get("reasons") or []) or v["note"]])
        elif isinstance(v, dict):
            _flatten_metrics(f"{prefix}.{k}", v, rows)


def results_csv(name: str, results: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["scenario", "section", "metric", "value", "rounded", "kind", "evidence", "bound", "note"])
    rows: list = []
    for section in ("summary", "breakdown_per_task", "breakdown_monthly", "decision_value"):
        _flatten_metrics(section, results.get(section, {}), rows)
    for r in results.get("routes", []):
        _flatten_metrics(f"route:{r['name']}", {k: r[k] for k in ("expected_cost", "contribution", "tokens",
                                                                   "accuracy_pct")}, rows)
        if "max" in r:
            _flatten_metrics(f"route:{r['name']}.max", {k: r["max"][k] for k in ("calculated", "effective",
                                                                                  "tokens")}, rows)
    for bm in (results.get("benchmark") or {}).get("rows", []):
        rows.append(["benchmark.measured", bm["key"], bm["measured"]["value"], "", bm["unit"],
                     bm["measured"]["evidence"], "", bm["measured"]["source"]])
        rows.append(["benchmark.projected", bm["key"], bm["projected"]["value"], "", bm["unit"],
                     bm["projected"]["evidence"] or "", "", bm["projected"]["note"]])
    for row in rows:
        w.writerow([name] + [dec_str(x) if isinstance(x, Decimal) else ("" if x is None else x) for x in row])
    return buf.getvalue()
