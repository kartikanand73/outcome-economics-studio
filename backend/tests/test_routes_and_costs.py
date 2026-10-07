"""Route-weighted, human-review, overlapping-review and fixed-cost calculations."""
from decimal import Decimal as D

from app.domain.models import OperatingCosts, Workload
from app.engine.aggregate import calculate
from app.engine.routes import expected_route
from tests.conftest import make_scenario, route

LIGHT_CALL = D("0.0014")   # 1000 x $1/M + 100 x $4/M
BIG_CALL = D("0.014")      # 1000 x $10/M + 100 x $40/M


def test_route_cost_sums_all_stages(two_route_scenario):
    sc = two_route_scenario
    assert expected_route(sc, sc.routes[0]).total == LIGHT_CALL
    assert expected_route(sc, sc.routes[1]).total == LIGHT_CALL + BIG_CALL


def test_expected_task_cost_is_share_weighted(two_route_scenario):
    r = calculate(two_route_scenario)
    assert r["ok"]
    expected = D("0.6") * LIGHT_CALL + D("0.4") * (LIGHT_CALL + BIG_CALL)
    assert r["summary"]["variable_cost_per_task"]["value"] == expected
    assert r["breakdown_per_task"]["larger_model"]["value"] == D("0.4") * BIG_CALL
    assert r["breakdown_per_task"]["lightweight_model"]["value"] == LIGHT_CALL


def test_exclusive_route_shares_must_total_100():
    sc = make_scenario([route("a", 60, ["light"]), route("b", 30, ["big"])])
    r = calculate(sc)
    assert not r["ok"]
    assert any(i["code"] == "route_share_total" for i in r["issues"])


def test_human_review_cost_formula():
    # 3 minutes / 60 x $60/h x reviewed tasks; 10% of the route reviewed
    sc = make_scenario([route("a", 100, [], deterministic_rule=True, human_review_pct=D(10))])
    e = expected_route(sc, sc.routes[0])
    assert e.categories["human_review"] == D("3") / 60 * 60 * D("0.10")  # $0.30 per task
    r = calculate(sc)
    assert r["summary"]["human_reviews_monthly"]["value"] == D("3000")  # 30,000 tasks x 10%


def test_conditional_review_does_not_change_route_share():
    sc = make_scenario([
        route("det", 8, [], deterministic_rule=True, human_review_pct=D(0)),
        route("jev", 69, ["light"], human_review_pct=D(10)),
        route("cascade", 23, ["light", "big"], human_review_pct=D(20)),
    ])
    r = calculate(sc)
    assert r["ok"], r["issues"]
    reviews = D("0.69") * D("0.10") + D("0.23") * D("0.20")
    assert r["summary"]["human_review_share_pct"]["value"] == reviews * 100
    assert r["breakdown_per_task"]["human_review"]["value"] == reviews * 3


def test_overlapping_direct_human_and_model_then_review_paths():
    sc = make_scenario([
        route("model-review", 50, ["big"], human_review_mandatory=True),
        route("direct", 30, [], direct_human=True),
        route("auto", 20, ["light"], human_review_pct=D(25)),
    ])
    r = calculate(sc)
    assert r["ok"]
    # shares total 100 even though 85% of tasks are reviewed
    share_reviewed = D("0.5") + D("0.3") + D("0.2") * D("0.25")
    assert r["summary"]["human_review_share_pct"]["value"] == share_reviewed * 100
    # model spend before a mandatory review is flagged as unable to change the outcome
    dv = r["decision_value"]
    assert dv["mandatory_review_model_tasks_monthly"]["value"] == D("0.5") * 30000
    assert dv["routes"]["model-review"]["answer"] == "no"


def test_fixed_cost_allocation_is_labelled_and_correct():
    costs = OperatingCosts(fixed_infra_monthly=D(200), observability_monthly=D(50), other_fixed_monthly=D(50))
    sc = make_scenario([route("a", 100, ["light"])], costs=costs)
    r = calculate(sc)
    s = r["summary"]
    assert s["allocated_fixed_per_task"]["value"] == D(300) / D(30000)
    assert "allocation" in s["allocated_fixed_per_task"]["note"].lower()
    assert s["expected_cost_per_task"]["value"] == LIGHT_CALL + D("0.01")
    assert s["daily_cost"]["value"] == LIGHT_CALL * 1000
    assert s["monthly_cost"]["value"] == LIGHT_CALL * 1000 * 30 + 300


def test_annual_cost_without_and_with_growth():
    sc = make_scenario([route("a", 100, ["light"])])
    r = calculate(sc)
    assert r["summary"]["annual_cost"]["value"] == r["summary"]["monthly_cost"]["value"] * 12
    grown = make_scenario([route("a", 100, ["light"])],
                          workload=Workload(tasks_per_day=D(1000), operating_days_per_month=D(30),
                                            annual_growth_pct=D(20)))
    g = calculate(grown)
    sched = g["charts"]["growth_schedule"]
    assert g["summary"]["annual_cost"]["value"] > r["summary"]["annual_cost"]["value"]
    # month 13 would be exactly +20%; month 12 is (1.2)^(11/12)
    assert abs(sched[11]["tasks"] / sched[0]["tasks"] - D("1.2") ** (D(11) / D(12))) < D("1e-20")


def test_cost_per_correct_governed_task():
    sc = make_scenario([route("a", 50, ["light"], accuracy_pct=D(100)), route("b", 50, ["big"], accuracy_pct=D(90))])
    r = calculate(sc)
    s = r["summary"]
    assert s["expected_accuracy_pct"]["value"] == D(95)
    assert s["cost_per_correct_task"]["value"] == s["monthly_cost"]["value"] / (D(30000) * D("0.95"))
