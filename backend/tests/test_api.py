"""API, persistence, import adapters and report generation."""
import json
import os

import pytest
from fastapi.testclient import TestClient

os.environ["OES_DB_PATH"] = ":memory:"

from app.api.main import app, store  # noqa: E402

client = TestClient(app)

DECISIONS_CSV = """decision_id,route_id,correct,latency_ms,human_reviewed,larger_model_called,outcome_changed,fraud_auto_approved,segment,model_cost
1,deterministic,1,4,0,0,0,0,low,0
2,jev,1,190,0,0,0,0,low,0.00004
3,jev,1,210,1,0,0,0,high,0.00004
4,jev-sol,0,2600,1,1,1,0,high,0.0024
5,jev-sol,1,2400,0,1,0,0,high,0.0024
"""


@pytest.fixture(autouse=True)
def fresh_samples():
    store.seed_samples(force=True)


def test_list_includes_samples_and_template_validates():
    ids = {s["id"] for s in client.get("/api/scenarios").json()}
    assert {"sample-sol-only", "sample-confidence-cascade", "sample-outcome-aware-router"} <= ids
    tpl = client.get("/api/scenarios/template").json()
    assert tpl["routes"] == [] and tpl["models"] == [] and tpl["features"]["infra_costs"] is True
    r = client.post("/api/calculate", json=tpl).json()
    assert r["ok"] is False and r["issues"][0]["code"] == "no_routes"


def test_money_is_serialised_as_exact_strings():
    r = client.get("/api/scenarios/sample-outcome-aware-router/results").json()
    v = r["summary"]["monthly_cost"]["rounded"]
    assert isinstance(v, str) and len(v.split(".")[1]) == 2


def test_create_update_clone_delete_roundtrip():
    tpl = client.get("/api/scenarios/template").json()
    tpl["name"] = "Mine"
    created = client.post("/api/scenarios", json=tpl).json()
    sid = created["id"]
    created["workload"]["tasks_per_day"] = "5000"
    assert client.put(f"/api/scenarios/{sid}", json=created).json()["workload"]["tasks_per_day"] == "5000"
    clone = client.post(f"/api/scenarios/{sid}/clone", json={"name": "Mine v2"}).json()
    assert clone["id"] != sid and clone["name"] == "Mine v2"
    assert client.delete(f"/api/scenarios/{sid}").status_code == 200
    assert client.get(f"/api/scenarios/{sid}").status_code == 404


def test_put_cannot_overwrite_frozen_benchmark():
    sc = client.get("/api/scenarios/sample-sol-only").json()
    sc["benchmark"]["metrics"]["model_cost_per_1000_decisions"]["value"] = "0.01"
    sc["models"][1]["input_price_per_m"] = "5"
    saved = client.put("/api/scenarios/sample-sol-only", json=sc).json()
    assert saved["benchmark"]["metrics"]["model_cost_per_1000_decisions"]["value"] == "2.11"
    assert saved["models"][1]["input_price_per_m"] == "5"


def test_invalid_scenario_returns_issues_not_crash():
    sc = client.get("/api/scenarios/sample-sol-only").json()
    sc["routes"][0]["share_pct"] = "50"
    r = client.post("/api/calculate", json=sc).json()
    assert r["ok"] is False and r["issues"][0]["code"] == "route_share_total"


def test_compare_endpoint():
    r = client.post("/api/compare", json={"ids": ["sample-sol-only", "sample-outcome-aware-router"]}).json()
    assert r["baseline"] == "Sol-only" and len(r["rows"][0]["cells"]) == 2


def test_import_decision_csv_attaches_benchmark_and_optionally_updates_inputs():
    clone = client.post("/api/scenarios/sample-outcome-aware-router/clone").json()
    sid = clone["id"]
    # benchmark only
    r = client.post(f"/api/scenarios/{sid}/import", files={"file": ("run.csv", DECISIONS_CSV, "text/csv")},
                    data={"apply_to_inputs": "false"}).json()
    bm = r["scenario"]["benchmark"]
    assert bm["decisions"] == 5 and float(bm["metrics"]["accuracy_pct"]["value"]) == 80
    assert r["scenario"]["routes"][1]["share_pct"] == clone["routes"][1]["share_pct"]
    # apply measured values to inputs
    r = client.post(f"/api/scenarios/{sid}/import", files={"file": ("run.csv", DECISIONS_CSV, "text/csv")},
                    data={"apply_to_inputs": "true"}).json()
    routes = {x["id"]: x for x in r["scenario"]["routes"]}
    assert float(routes["jev"]["share_pct"]) == 40 and routes["jev"]["evidence"]["share_pct"] == "measured"
    assert float(routes["jev-sol"]["larger_changed_outcome_pct"]) == 50
    assert float(routes["jev"]["human_review_pct"]) == 50
    res = client.get(f"/api/scenarios/{sid}/results").json()
    assert res["ok"]
    assert {s["name"] for s in res["benchmark"]["segments"]} == {"low", "high"}


def test_import_rejects_unknown_routes_when_applying():
    bad = DECISIONS_CSV.replace("jev-sol", "mystery")
    r = client.post("/api/scenarios/sample-outcome-aware-router/import",
                    files={"file": ("run.csv", bad, "text/csv")}, data={"apply_to_inputs": "true"})
    assert r.status_code == 422 and "mystery" in r.json()["detail"]


def test_import_metrics_csv_and_benchmark_json_preview():
    csv_text = ("metric,value,unit,evidence,note\nbenchmark_name,My run,,,\ndecisions,1000,,,\n"
                "model_cost_per_1000_decisions,0.42,USD,measured,\naccuracy_pct,97.5,%,measured,\n")
    p = client.post("/api/import/preview", files={"file": ("m.csv", csv_text, "text/csv")}).json()
    assert p["kind"] == "metrics_csv" and p["benchmark"]["name"] == "My run" and p["benchmark"]["decisions"] == 1000
    js = {"schema_version": "1.0", "benchmark": {"name": "J", "decisions": 600,
                                                 "metrics": {"accuracy_pct": 98.8, "p50_latency_ms": {"value": 209}}},
          "routes": [{"id": "jev", "accuracy_pct": 99, "safety": {"fraud_auto_approval_pct": 0}}]}
    p = client.post("/api/import/preview", files={"file": ("b.json", json.dumps(js), "application/json")}).json()
    assert p["kind"] == "benchmark_json" and p["route_updates"]["jev"]["safety.fraud_auto_approval_pct"] == "0"


def test_bad_import_gives_clear_error():
    r = client.post("/api/import/preview", files={"file": ("x.csv", "a,b\n1,2\n", "text/csv")})
    assert r.status_code == 422 and "Unrecognised CSV" in r.json()["detail"]


def test_scenario_export_and_reimport():
    exported = client.get("/api/scenarios/sample-outcome-aware-router/export.json")
    assert "attachment" in exported.headers["content-disposition"]
    r = client.post("/api/import/scenario", files={"file": ("s.json", exported.text, "application/json")})
    assert r.status_code == 201 and r.json()["is_sample"] is False
    assert r.json()["benchmark"]["name"].startswith("Outcome-aware router")


def test_results_csv_and_report():
    csv_resp = client.get("/api/scenarios/sample-outcome-aware-router/results.csv")
    lines = csv_resp.text.splitlines()
    assert lines[0].startswith("scenario,section,metric") and any("benchmark.measured" in x for x in lines)
    html = client.get("/api/scenarios/sample-agentic-illustration/report").text
    assert "Unbounded" in html and "Could the additional model call change the governed outcome?" in html
    assert "Sample data" in client.get("/api/scenarios/sample-sol-only/report").text
