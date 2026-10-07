"""Engine vs. three scenarios worked out by hand. The working is in docs/validation.md.

Values here are typed from the hand calculation, not copied from engine output.
"""
from decimal import Decimal as D

import pytest

from app.domain.models import (BudgetPolicy, CallLimits, CheckTiming, ContextBounds, Enforcement, ModelConfig,
                               OperatingCosts, Route, Scenario, Stage, Tier, Workload)
from app.engine.aggregate import calculate
from app.engine.compare import compare


def v(res, *path):
    node = res
    for p in path:
        node = node[p]
    return node["value"] if isinstance(node, dict) and "value" in node else node


# ------------------------------------------------------------------ scenario A
def scenario_a() -> Scenario:
    L = ModelConfig(id="L", name="L", tier=Tier.LIGHTWEIGHT, input_price_per_m=D(1), output_price_per_m=D(4),
                    avg_input_tokens=D(1000), avg_output_tokens=D(100), avg_calls_per_task=D(1),
                    p50_latency_ms=D(200), p95_latency_ms=D(200),
                    context=ContextBounds(system_prompt_tokens=D(500), avg_user_input_tokens=D(500),
                                          max_user_input_tokens=D(500), max_output_tokens=D(200)),
                    limits=CallLimits(max_model_calls=1))
    return Scenario(
        name="A", workload=Workload(tasks_per_day=D(1000), operating_days_per_month=D(30)),
        models=[L],
        costs=OperatingCosts(tool_cost_per_call=D("0.001"), review_minutes_avg=D(3), review_minutes_max=D(10),
                             reviewer_hourly_cost=D(60), eval_sampling_pct=D(10), eval_cost_per_sample=D("0.05"),
                             fixed_infra_monthly=D(300)),
        routes=[Route(id="R1", name="R1", share_pct=D(20), deterministic_rule=True, rule_tool_calls=D(1),
                      rule_latency_ms=D(5), accuracy_pct=D(100)),
                Route(id="R2", name="R2", share_pct=D(80), rule_tool_calls=D(1), stages=[Stage(model_id="L")],
                      human_review_pct=D(10), accuracy_pct=D(95))])


def test_scenario_a_expected_and_totals():
    r = calculate(scenario_a())
    assert r["ok"], r["issues"]
    assert v(r, "summary", "variable_cost_per_task") == D("0.24712")
    assert v(r, "summary", "allocated_fixed_per_task") == D("0.01")
    assert v(r, "summary", "expected_cost_per_task") == D("0.25712")
    assert v(r, "summary", "daily_cost") == D("247.12")
    assert v(r, "summary", "monthly_cost") == D("7713.60")
    assert v(r, "summary", "annual_cost") == D("92563.20")
    assert v(r, "summary", "expected_accuracy_pct") == D(96)
    assert v(r, "summary", "correct_outcomes_monthly") == D(28800)
    assert v(r, "summary", "cost_per_correct_task") == D("7713.6") / D(28800)
    assert str(r["summary"]["cost_per_correct_task"]["rounded"]) == "0.267833"
    assert v(r, "summary", "human_reviews_monthly") == D(2400)
    assert r["projection"]["model_cost_per_1000"] == D("1.12")
    assert v(r, "summary", "expected_tokens_per_task") == D(880)


def test_scenario_a_category_breakdown():
    b = calculate(scenario_a())["breakdown_per_task"]
    assert v(b, "lightweight_model") == D("0.00112")
    assert v(b, "larger_model") == 0
    assert v(b, "tool_api") == D("0.001")
    assert v(b, "human_review") == D("0.24")
    assert v(b, "evaluation") == D("0.005")
    assert v(b, "infrastructure") == D("0.01")


def test_scenario_a_maximum_and_latency():
    r = calculate(scenario_a())
    assert v(r, "summary", "calculated_max_variable_per_task") == D("10.0528")
    assert v(r, "summary", "max_cost_per_task") == D("10.0628")
    assert v(r, "summary", "max_tokens_per_task") == D(1200)
    assert r["summary"]["worst_route"] == "R2"
    assert abs(v(r, "summary", "p50_latency_ms") - 200) < 0.01
    assert abs(v(r, "summary", "p95_latency_ms") - 200) < 0.01


# ------------------------------------------------------------------ scenario B
def model_g() -> ModelConfig:
    return ModelConfig(id="G", name="G", tier=Tier.LARGER, input_price_per_m=D(5), output_price_per_m=D(20),
                       cached_input_price_per_m=D("0.5"), cached_input_share_pct=D(50),
                       separately_metered_reasoning=True, avg_input_tokens=D(2000), avg_output_tokens=D(100),
                       avg_reasoning_tokens=D(200), avg_calls_per_task=D(1),
                       context=ContextBounds(system_prompt_tokens=D(1000), avg_user_input_tokens=D(1000),
                                             max_user_input_tokens=D(1000), max_output_tokens=D(200),
                                             max_reasoning_tokens=D(500)),
                       limits=CallLimits(max_model_calls=1))


def scenario_b() -> Scenario:
    L = ModelConfig(id="L", name="L", tier=Tier.LIGHTWEIGHT, input_price_per_m=D("0.5"), output_price_per_m=D(2),
                    avg_input_tokens=D(800), avg_output_tokens=D(50), avg_calls_per_task=D(1),
                    retries_enabled=True, retry_rate_pct=D(5),
                    context=ContextBounds(system_prompt_tokens=D(300), avg_user_input_tokens=D(500),
                                          max_user_input_tokens=D(500), max_output_tokens=D(100)),
                    limits=CallLimits(max_model_calls=1, max_retries=1))
    return Scenario(
        name="B", workload=Workload(tasks_per_day=D(2000), operating_days_per_month=D(20)),
        models=[L, model_g()],
        costs=OperatingCosts(review_minutes_avg=D(4), reviewer_hourly_cost=D(45)),
        budget=BudgetPolicy(max_monetary_budget_per_task=D("0.01"), enforcement=Enforcement.REJECT,
                            check_timing=CheckTiming.PRE_CALL),
        routes=[Route(id="R1", name="R1", share_pct=D(70), stages=[Stage(model_id="L")], accuracy_pct=D(96)),
                Route(id="R2", name="R2", share_pct=D(30), stages=[Stage(model_id="L"), Stage(model_id="G")],
                      human_review_pct=D(20), accuracy_pct=D(99), larger_changed_outcome_pct=D(40))])


def test_scenario_b_expected_and_totals():
    r = calculate(scenario_b())
    assert r["ok"], r["issues"]
    assert v(r, "summary", "expected_cost_per_task") == D("0.183975")
    assert v(r, "summary", "daily_cost") == D("367.95")
    assert v(r, "summary", "monthly_cost") == D("7359.00")
    assert v(r, "summary", "annual_cost") == D("88308.00")
    assert v(r, "summary", "expected_accuracy_pct") == D("96.9")
    assert v(r, "summary", "correct_outcomes_monthly") == D(38760)
    assert v(r, "summary", "cost_per_correct_task") == D(7359) / D(38760)
    assert v(r, "summary", "human_reviews_monthly") == D(2400)
    assert v(r, "summary", "larger_calls_monthly") == D(12000)
    assert r["projection"]["model_cost_per_1000"] == D("3.975")


def test_scenario_b_decision_value():
    dv = calculate(scenario_b())["decision_value"]
    assert v(dv, "larger_escalation_rate_pct") == D(30)
    assert v(dv, "larger_cost_per_task") == D("0.00345")
    assert v(dv, "cost_per_changed_decision") == D("0.02875")
    assert v(dv, "avoidable_model_spend_monthly") == D("82.8")
    assert v(dv, "tokens_on_unchanged_monthly") == D(16560000)
    assert v(dv, "larger_calls_avoided_per_task") * 40000 == D(28000)


def test_scenario_b_maximum_and_budget():
    r = calculate(scenario_b())
    b = r["budget"]["cost"]
    assert v(b, "calculated_max") == D("3.0252")
    assert b["is_hard_bound"] is True
    assert v(b, "single_call_overshoot") == 0
    assert v(b, "effective_max") == D("3.01")
    assert v(r, "summary", "max_tokens_per_task") == D(4500)
    stages = r["routes"][1]["max"]["stages"]
    assert v(stages[0], "max_attempts") == 2 and v(stages[0], "model_cost") == D("0.0012")
    assert v(stages[1], "max_call_cost") == D("0.024") and v(stages[1], "max_tokens_per_call") == D(2700)


# ------------------------------------------------------------------ scenario C and Compare
def scenario_c() -> Scenario:
    return Scenario(
        name="C", workload=Workload(tasks_per_day=D(2000), operating_days_per_month=D(20)),
        models=[model_g()], costs=OperatingCosts(review_minutes_avg=D(4), reviewer_hourly_cost=D(45)),
        routes=[Route(id="R", name="R", share_pct=D(100), stages=[Stage(model_id="G")], human_review_pct=D(20),
                      accuracy_pct=D(99))])


def test_scenario_c_totals():
    r = calculate(scenario_c())
    assert v(r, "summary", "expected_cost_per_task") == D("0.6115")
    assert v(r, "summary", "monthly_cost") == D("24460.00")
    assert v(r, "summary", "correct_outcomes_monthly") == D(39600)
    assert v(r, "summary", "human_reviews_monthly") == D(8000)
    assert v(r, "summary", "larger_calls_monthly") == D(40000)


def test_compare_headline_c_baseline_vs_b():
    h = compare([scenario_c(), scenario_b()])["vs_baseline"][1]
    assert h["monthly_savings"] == D("17101.00")
    assert h["accuracy_difference_pts"] == D("-2.1")
    assert h["human_reviews_avoided_monthly"] == D(5600)
    assert h["larger_calls_avoided_monthly"] == D(28000)
    assert h["correct_outcomes_difference_monthly"] == D(-840)
    assert h["verdict"] == "saves_per_correct_given_up"
    assert h["cost_per_additional_correct"] == D(17101) / D(840)


def test_compare_headline_b_baseline_vs_c():
    h = compare([scenario_b(), scenario_c()])["vs_baseline"][1]
    assert h["verdict"] == "costs_per_additional_correct"
    assert h["cost_per_additional_correct"] == D(17101) / D(840)
    assert h["monthly_savings"] == D("-17101.00")


@pytest.mark.parametrize("acc_b,cost_b,verdict", [(D(100), D("0.0001"), "dominates"), (D(90), D(1), "dominated")])
def test_compare_dominance_verdicts(acc_b, cost_b, verdict):
    base = scenario_c()
    alt = scenario_c()
    alt.routes[0].accuracy_pct = acc_b
    alt.costs.other_variable_per_task = cost_b if verdict == "dominated" else D(0)
    if verdict == "dominates":
        alt.routes[0].human_review_pct = D(0)
    assert compare([base, alt])["vs_baseline"][1]["verdict"] == verdict
