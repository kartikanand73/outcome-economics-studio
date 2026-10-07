"""Decision value, safety, measured-vs-projected, comparison and currency rounding."""
from decimal import Decimal as D

import pytest

from app.domain.models import Safety
from app.engine.aggregate import calculate
from app.engine.compare import compare
from app.engine.money import round_money, round_unit
from app.samples.catalog import confidence_cascade, outcome_aware_router, sol_only
from tests.conftest import make_scenario, route

BIG_CALL = D("0.014")


# ---------------------------------------------------------------- decision value
def test_changed_outcome_and_avoidable_spend():
    sc = make_scenario([
        route("det", 20, [], deterministic_rule=True),
        route("light", 50, ["light"]),
        route("cascade", 30, ["light", "big"], larger_changed_outcome_pct=D(25)),
    ])
    dv = calculate(sc)["decision_value"]
    assert dv["larger_escalation_rate_pct"]["value"] == D(30)
    assert dv["changed_outcome_pct"]["value"] == D(25)
    changed_per_task = D("0.3") * D("0.25")
    assert dv["cost_per_changed_decision"]["value"] == D("0.3") * BIG_CALL / changed_per_task
    assert dv["avoidable_model_spend_monthly"]["value"] == D("0.3") * BIG_CALL * D("0.75") * 30000
    # baseline = one larger call per model-eligible task (80%); actual 30%
    assert dv["larger_calls_avoided_per_task"]["value"] == D("0.5")


def test_unknown_changed_outcome_is_not_zero():
    sc = make_scenario([route("cascade", 100, ["light", "big"])])
    dv = calculate(sc)["decision_value"]
    assert dv["changed_outcome_pct"]["value"] is None
    assert dv["avoidable_model_spend_monthly"]["value"] is None
    assert dv["routes"]["cascade"]["answer"] == "unknown"


# ---------------------------------------------------------------- safety
def test_overall_accuracy_does_not_hide_fraud():
    sc = make_scenario([
        route("a", 99, ["light"], accuracy_pct=D("99.9"), safety=Safety(fraud_auto_approval_pct=D(0))),
        route("b", 1, ["light"], accuracy_pct=D(90), safety=Safety(fraud_auto_approval_pct=D(5))),
    ])
    r = calculate(sc)
    assert r["summary"]["expected_accuracy_pct"]["value"] > D(99)
    fraud = r["decision_value"]["safety"]["fraud_auto_approved"]
    assert fraud["status"] == "complete"
    assert fraud["monthly"]["value"] == D("0.01") * D("0.05") * 30000
    assert r["summary"]["safety_failures_monthly"]["value"] > 0


def test_unmeasured_safety_is_never_reported_as_zero():
    sc = make_scenario([route("a", 50, ["light"], safety=Safety(fraud_auto_approval_pct=D(0))),
                        route("b", 50, ["light"])])
    fraud = calculate(sc)["decision_value"]["safety"]["fraud_auto_approved"]
    assert fraud["status"] == "partial"
    assert fraud["missing_routes"] == ["b"]
    none = calculate(make_scenario([route("a", 100, ["light"])]))
    assert none["decision_value"]["safety"]["fraud_auto_approved"]["status"] == "not_measured"
    assert none["summary"]["safety_failures_monthly"]["value"] is None


# ---------------------------------------------------------------- measured vs projected
def test_price_change_recalculates_projection_but_not_benchmark():
    sc = outcome_aware_router()
    before = calculate(sc)["benchmark"]
    measured_before = {r["key"]: r["measured"]["value"] for r in before["rows"]}
    sol = sc.model_by_id("gpt-6-sol")
    sol.input_price_per_m = sol.input_price_per_m * 2
    after = calculate(sc)["benchmark"]
    measured_after = {r["key"]: r["measured"]["value"] for r in after["rows"]}
    assert measured_before == measured_after
    row_b = next(r for r in before["rows"] if r["key"] == "model_cost_per_1000_decisions")
    row_a = next(r for r in after["rows"] if r["key"] == "model_cost_per_1000_decisions")
    assert row_a["projected"]["value"] > row_b["projected"]["value"]
    assert row_a["measured"]["value"] == D("0.56")
    assert row_a["measured"]["evidence"] == "measured" and row_a["projected"]["evidence"] == "derived"
    assert row_a["difference"] == row_a["projected"]["value"] - D("0.56")


def test_benchmark_is_immutable():
    sc = sol_only()
    with pytest.raises(Exception):
        sc.benchmark.decisions = 1


def test_count_metrics_normalised_per_1000_decisions():
    rows = {r["key"]: r for r in calculate(outcome_aware_router())["benchmark"]["rows"]}
    assert rows["larger_model_calls"]["measured"]["raw"] == D(137)
    assert rows["larger_model_calls"]["measured"]["value"] == D(137) * 1000 / 600


@pytest.mark.parametrize("factory,measured", [(sol_only, "2.11"), (confidence_cascade, "0.71"),
                                              (outcome_aware_router, "0.56")])
def test_sample_projections_stay_close_to_measured(factory, measured):
    row = next(r for r in calculate(factory())["benchmark"]["rows"] if r["key"] == "model_cost_per_1000_decisions")
    assert abs(row["difference_pct"]) < 5, "sample assumptions drifted far from the reference benchmark"


# ---------------------------------------------------------------- comparison
def test_scenario_comparison_deltas_against_baseline():
    res = compare([sol_only(), confidence_cascade(), outcome_aware_router()])
    row = next(r for r in res["rows"] if r["key"] == "model_cost_per_1000")
    base, cascade, router = row["cells"]
    assert base["delta"] == 0
    assert cascade["value"] < base["value"] and router["value"] < cascade["value"]
    assert router["better"] is True
    reduction = -router["delta_pct"]
    assert D(70) < reduction < D(76)  # benchmark reports ~73% lower model cost
    tokens = next(r for r in res["rows"] if r["key"] == "larger_tokens_per_task")["cells"][2]
    assert D(-78) < tokens["delta_pct"] < D(-72)  # benchmark reports ~75% fewer Sol tokens


def test_clone_then_modify_changes_only_the_clone():
    a = outcome_aware_router()
    b = a.model_copy(deep=True)
    b.name = "Router without Sol"
    b.routes[1].share_pct += b.routes[2].share_pct
    b.routes[2].share_pct = D(0)
    res = compare([a, b])
    row = next(r for r in res["rows"] if r["key"] == "larger_calls_monthly")
    assert row["cells"][1]["value"] == 0 and row["cells"][0]["value"] > 0
    assert a.routes[2].share_pct != 0


# ---------------------------------------------------------------- currency rounding
def test_money_rounding_is_half_up_to_minor_units():
    assert round_money(D("0.345"), "USD") == D("0.35")   # banker's rounding would give 0.34
    assert round_money(D("1234.5"), "JPY") == D("1235")
    assert round_money(D("1.2345"), "KWD") == D("1.235")
    assert round_unit(D("0.0000125")) == D("0.000013")


def test_no_intermediate_rounding_in_aggregates():
    # $0.0000005 per task would round to $0.000001 per task; 1,000,000 tasks must give exactly $0.50
    from app.domain.models import OperatingCosts, Workload
    sc = make_scenario([route("a", 100, [], deterministic_rule=True)],
                       costs=OperatingCosts(other_variable_per_task=D("0.0000005")),
                       workload=Workload(tasks_per_day=D(1_000_000), operating_days_per_month=D(1)))
    s = calculate(sc)["summary"]
    assert s["daily_cost"]["value"] == D("0.5")
    assert s["daily_cost"]["rounded"] == D("0.50")


def test_float_inputs_convert_exactly():
    from app.domain.models import OperatingCosts
    c = OperatingCosts(tool_cost_per_call=0.1)
    assert c.tool_cost_per_call == D("0.1")
