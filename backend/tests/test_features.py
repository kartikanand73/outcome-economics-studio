"""Building blocks: unticked blocks are ignored by the engine but their values are kept."""
from decimal import Decimal as D

from app.domain.models import (BudgetPolicy, CheckTiming, ContextBounds, Enforcement, Features, OperatingCosts,
                               Stage)
from app.engine.aggregate import calculate
from app.engine.features import effective
from app.samples.catalog import all_samples, outcome_aware_router
from tests.conftest import make_model, make_scenario, route


def _sc(features):
    costs = OperatingCosts(review_minutes_avg=D(3), reviewer_hourly_cost=D(60), tool_cost_per_call=D("0.01"),
                           fixed_infra_monthly=D(300), eval_sampling_pct=D(10), eval_cost_per_sample=D("0.1"))
    m = make_model("light", context=ContextBounds(max_output_tokens=None))  # unbounded only in custom mode
    return make_scenario([route("a", 100, [Stage(model_id="light", tools_exposed=True, avg_tool_calls=D(2),
                                                 max_tool_calls=2)],
                                human_review_pct=D(50), rule_tool_calls=D(1))],
                         models=[m], costs=costs, features=features,
                         budget=BudgetPolicy(max_monetary_budget_per_task=D("0.0001"), enforcement=Enforcement.REJECT,
                                             check_timing=CheckTiming.PRE_CALL))


def test_no_features_means_everything_applies():
    r = calculate(_sc(None))
    assert r["summary"]["max_cost_per_task"]["unbounded"] is True  # custom mode, no max output
    assert r["breakdown_per_task"]["human_review"]["value"] > 0


def test_unticked_blocks_are_ignored():
    r = calculate(_sc(Features(lightweight=True, lightweight_model_id="light")))
    b = r["breakdown_per_task"]
    assert b["human_review"]["value"] == 0
    assert b["tool_api"]["value"] == 0
    assert b["evaluation"]["value"] > 0  # infrastructure & evaluation is ticked by default
    assert r["summary"]["max_cost_per_task"]["unbounded"] is False   # default bounds without advanced limits
    assert r["budget"]["cost"]["configured"] is None


def test_infra_unticked_removes_fixed_and_eval():
    r = calculate(_sc(Features(lightweight=True, human_review=True, tools=True, infra_costs=False)))
    assert r["summary"]["allocated_fixed_per_task"]["value"] == 0
    assert r["breakdown_per_task"]["evaluation"]["value"] == 0
    assert r["breakdown_per_task"]["human_review"]["value"] > 0 and r["breakdown_per_task"]["tool_api"]["value"] > 0


def test_ticked_blocks_apply_and_values_are_kept():
    sc = _sc(Features(lightweight=True, human_review=True, tools=True, advanced_limits=True, budget=True))
    r = calculate(sc)
    assert r["budget"]["cost"]["is_hard_bound"] is False  # single call unbounded in custom mode
    off = sc.model_copy(deep=True)
    off.features = Features(lightweight=True)
    effective(off)
    assert off.routes[0].human_review_pct == D(50) and off.budget.max_monetary_budget_per_task == D("0.0001")


def test_samples_unchanged_by_their_features():
    for sc in all_samples():
        with_f = calculate(sc)
        plain = sc.model_copy(deep=True)
        plain.features = None
        assert with_f["summary"]["expected_cost_per_task"]["value"] == calculate(plain)["summary"]["expected_cost_per_task"]["value"], sc.name
    assert outcome_aware_router().features.lightweight_model_id == "jev-1-13"
