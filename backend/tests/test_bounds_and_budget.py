"""Expected vs maximum cost, per-stage bounds, unbounded-risk detection and budgets."""
from decimal import Decimal as D

from app.domain.models import (BudgetPolicy, CallLimits, CheckTiming, ContextBounds, Enforcement, OperatingCosts,
                               Stage, Tier)
from app.engine.aggregate import calculate
from app.validation.checks import validate
from tests.conftest import make_model, make_scenario, route

LIGHT_MAX_CALL = D("0.001") + D("0.0008")   # 1000 input x $1/M + 200 output x $4/M
BIG_MAX_CALL = D("0.01") + D("0.008")       # same tokens at $10/$40


def codes(sc):
    return {i.code for i in validate(sc)}


# ---------------------------------------------------------------- expected vs max
def test_max_is_at_least_expected(two_route_scenario):
    r = calculate(two_route_scenario)
    s = r["summary"]
    assert s["max_cost_per_task"]["value"] >= s["expected_cost_per_task"]["value"]


def test_cascade_max_sums_each_stage_separately():
    light = make_model("light", limits=CallLimits(max_model_calls=2, max_retries=1), retries_enabled=True)
    big = make_model("big", Tier.LARGER, input_price_per_m=D("10"), output_price_per_m=D("40"),
                     limits=CallLimits(max_model_calls=1))
    sc = make_scenario([route("cascade", 100, ["light", "big"])], models=[light, big])
    r = calculate(sc)
    # light: 2 calls x (1 + 1 retry) = 4 attempts; big: 1 attempt
    stages = r["routes"][0]["max"]["stages"]
    assert stages[0]["max_attempts"]["value"] == 4
    assert stages[1]["max_attempts"]["value"] == 1
    assert r["summary"]["calculated_max_variable_per_task"]["value"] == 4 * LIGHT_MAX_CALL + BIG_MAX_CALL
    # tokens: 4 x 1200 + 1 x 1200 (not a single global limit x global calls)
    assert r["summary"]["max_tokens_per_task"]["value"] == 5 * 1200


def test_task_max_is_worst_reachable_route_and_includes_review():
    costs = OperatingCosts(review_minutes_avg=D(3), review_minutes_max=D(10), reviewer_hourly_cost=D(60))
    sc = make_scenario([route("auto", 90, ["light"]), route("review", 10, ["light"], human_review_pct=D(50))],
                       costs=costs)
    r = calculate(sc)
    assert r["summary"]["calculated_max_variable_per_task"]["value"] == LIGHT_MAX_CALL + D(10)  # 10 min at $60/h
    assert r["summary"]["worst_route"] == "review"


def test_tools_and_subagents_add_to_stage_max():
    costs = OperatingCosts(tool_cost_per_call=D("0.01"))
    stage = Stage(model_id="light", tools_exposed=True, max_tool_calls=3, subagents_enabled=True, max_subagents=2,
                  subagent_model_id="big")
    sc = make_scenario([route("a", 100, [stage])], costs=costs)
    r = calculate(sc)
    assert r["summary"]["calculated_max_variable_per_task"]["value"] == \
        LIGHT_MAX_CALL + 3 * D("0.01") + 2 * BIG_MAX_CALL


# ---------------------------------------------------------------- unbounded detection
def test_unbounded_workflow_has_no_maximum():
    m = make_model("light", context=ContextBounds(system_prompt_tokens=D(100), max_output_tokens=None))
    sc = make_scenario([route("a", 100, ["light"])], models=[m])
    r = calculate(sc)
    mx = r["summary"]["max_cost_per_task"]
    assert mx["unbounded"] is True
    assert mx["value"] is None and mx["rounded"] is None
    assert mx["reasons"]
    assert "output_unbounded" in codes(sc)


def test_each_enabled_feature_without_limit_warns():
    m = make_model("big", Tier.LARGER, separately_metered_reasoning=True, retries_enabled=True,
                   context=ContextBounds(system_prompt_tokens=D(100), history_enabled=True, retrieval_enabled=True,
                                         max_output_tokens=D(100), tool_schema_count=15, tool_schema_tokens=D(3000)),
                   limits=CallLimits(agent_loop_enabled=True))
    stage = Stage(model_id="big", tools_exposed=True, subagents_enabled=True)
    sc = make_scenario([route("a", 100, [stage])], models=[m])
    assert {"iterations_unbounded", "history_unbounded", "retrieval_unbounded", "retries_unbounded",
            "reasoning_unbounded", "tool_calls_unbounded", "subagents_unbounded", "tool_schema_bloat"} <= codes(sc)
    assert calculate(sc)["summary"]["max_cost_per_task"]["unbounded"]


def test_missing_limits_ignored_when_feature_disabled():
    """Dependency-aware: a missing limit only matters when the feature is reachable."""
    m = make_model("light", separately_metered_reasoning=False, retries_enabled=False, retry_rate_pct=D(0),
                   context=ContextBounds(system_prompt_tokens=D(100), max_output_tokens=D(50),
                                         history_enabled=False, retrieval_enabled=False,
                                         max_reasoning_tokens=None, max_history_tokens=None,
                                         max_retrieved_tokens=None),
                   limits=CallLimits(agent_loop_enabled=False, max_model_calls=None, max_retries=None))
    stage = Stage(model_id="light", tools_exposed=False, max_tool_calls=None, subagents_enabled=False,
                  max_subagents=None)
    sc = make_scenario([route("a", 100, [stage])], models=[m])
    found = codes(sc)
    for code in ("iterations_unbounded", "history_unbounded", "retrieval_unbounded", "retries_unbounded",
                 "reasoning_unbounded", "tool_calls_unbounded", "subagents_unbounded"):
        assert code not in found
    assert not calculate(sc)["summary"]["max_cost_per_task"]["unbounded"]


def test_unreachable_route_does_not_make_task_unbounded():
    bad = make_model("bad", context=ContextBounds(max_output_tokens=None))
    sc = make_scenario([route("ok", 100, ["light"]), route("never", 0, ["bad"])],
                       models=[make_model("light"), bad])
    assert "output_unbounded" not in codes(sc)
    assert not calculate(sc)["summary"]["max_cost_per_task"]["unbounded"]


def test_agent_loop_capped_by_iterations_is_bounded():
    m = make_model("light", limits=CallLimits(agent_loop_enabled=True, max_agent_iterations=5))
    sc = make_scenario([route("a", 100, ["light"])], models=[m])
    r = calculate(sc)
    assert r["summary"]["calculated_max_variable_per_task"]["value"] == 5 * LIGHT_MAX_CALL


# ---------------------------------------------------------------- budget enforcement
def _budget_scenario(policy, model=None):
    m = model or make_model("light", limits=CallLimits(max_model_calls=10))  # calc max = 10 x 0.0018 = 0.018
    return make_scenario([route("a", 100, ["light"])], models=[m], budget=policy)


def test_warn_budget_does_not_cap_maximum():
    r = calculate(_budget_scenario(BudgetPolicy(max_monetary_budget_per_task=D("0.005"),
                                                enforcement=Enforcement.WARN)))
    b = r["budget"]["cost"]
    assert b["calculated_max"]["value"] == 10 * LIGHT_MAX_CALL
    assert b["effective_max"]["value"] == 10 * LIGHT_MAX_CALL
    assert b["is_hard_bound"] is False


def test_reject_pre_call_is_hard_bound():
    r = calculate(_budget_scenario(BudgetPolicy(max_monetary_budget_per_task=D("0.005"),
                                                enforcement=Enforcement.REJECT, check_timing=CheckTiming.PRE_CALL)))
    b = r["budget"]["cost"]
    assert b["is_hard_bound"] is True
    assert b["single_call_overshoot"]["value"] == 0
    assert b["effective_max"]["value"] == D("0.005")
    assert b["calculated_max"]["value"] == 10 * LIGHT_MAX_CALL  # shown separately, not overwritten


def test_reject_post_call_allows_single_call_overshoot():
    r = calculate(_budget_scenario(BudgetPolicy(max_monetary_budget_per_task=D("0.005"),
                                                enforcement=Enforcement.REJECT, check_timing=CheckTiming.POST_CALL)))
    b = r["budget"]["cost"]
    assert b["is_hard_bound"] is False
    assert b["single_call_overshoot"]["value"] == LIGHT_MAX_CALL
    assert b["effective_max"]["value"] == D("0.005") + LIGHT_MAX_CALL


def test_degrade_is_not_fail_closed():
    r = calculate(_budget_scenario(BudgetPolicy(max_monetary_budget_per_task=D("0.005"),
                                                enforcement=Enforcement.DEGRADE, degrade_fallback_cost=D("0.5"))))
    b = r["budget"]["cost"]
    assert b["is_hard_bound"] is False
    assert b["effective_max"]["value"] == 10 * LIGHT_MAX_CALL
    assert b["soft_bound"]["value"] == D("0.005") + D("0.5") + LIGHT_MAX_CALL


def test_pre_call_budget_bounds_an_unbounded_loop_when_calls_are_bounded():
    m = make_model("light", limits=CallLimits(agent_loop_enabled=True))  # loop without limits
    r = calculate(_budget_scenario(BudgetPolicy(max_monetary_budget_per_task=D("0.05"),
                                                enforcement=Enforcement.REJECT, check_timing=CheckTiming.PRE_CALL),
                                   model=m))
    s = r["summary"]
    assert s["calculated_max_variable_per_task"]["unbounded"] is True
    assert s["effective_max_variable_per_task"]["value"] == D("0.05")
    assert s["max_cost_per_task"]["unbounded"] is False


def test_pre_call_check_cannot_bound_when_single_call_unbounded():
    m = make_model("light", context=ContextBounds(max_output_tokens=None))
    r = calculate(_budget_scenario(BudgetPolicy(max_monetary_budget_per_task=D("0.05"),
                                                enforcement=Enforcement.REJECT, check_timing=CheckTiming.PRE_CALL),
                                   model=m))
    assert r["budget"]["cost"]["is_hard_bound"] is False
    assert r["summary"]["max_cost_per_task"]["unbounded"] is True


def test_budget_does_not_cap_human_review():
    costs = OperatingCosts(review_minutes_avg=D(6), reviewer_hourly_cost=D(60))
    sc = make_scenario([route("a", 100, ["light"], human_review_pct=D(100))],
                       models=[make_model("light", limits=CallLimits(max_model_calls=10))], costs=costs,
                       budget=BudgetPolicy(max_monetary_budget_per_task=D("0.005"), enforcement=Enforcement.REJECT,
                                           check_timing=CheckTiming.PRE_CALL))
    r = calculate(sc)
    assert r["summary"]["effective_max_variable_per_task"]["value"] == D("0.005") + D(6)  # 6 min at $60/h
