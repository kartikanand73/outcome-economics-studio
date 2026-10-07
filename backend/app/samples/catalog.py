"""Sample scenarios.

The three Jev benchmark scenarios are reference data only: their measured
benchmark results are frozen in ``benchmark`` and the scenario inputs are
editable assumptions that produce a *projection*. Users should replace both.
"""
from __future__ import annotations

from decimal import Decimal

from app.domain.models import (BudgetPolicy, CallLimits, CheckTiming, ContextBounds, DecisionInputs, Enforcement,
                               Features,
                               Evidence, MeasuredBenchmark, MeasuredValue, ModelConfig, OperatingCosts, Route,
                               Safety, Scenario, Stage, Tier, Workload)
from app.pricing.catalog import sample_models

M = Evidence.MEASURED
A = Evidence.ASSUMPTION
D = Decimal

BENCH_SOURCE = "Jev benchmark - 600 test decisions (SAMPLE DATA: replace with your own benchmark)"
SAMPLE_NOTE = ("Sample benchmark data for demonstration. Measured values come from the Jev reference benchmark; "
               "prices, token counts, review rates and costs are illustrative assumptions. Replace them with your own.")


def _jev_models() -> list[ModelConfig]:
    return [m for m in sample_models() if m.id in ("jev-1-13", "gpt-6-sol")]


def _workload() -> Workload:
    return Workload(tasks_per_day=D(1000), operating_days_per_month=D(30), annual_growth_pct=D(0),
                    peak_tasks_per_minute=D(5), target_accuracy_pct=D(98), max_latency_ms=D(2000), currency="USD")


def _costs() -> OperatingCosts:
    return OperatingCosts(review_minutes_avg=D(3), review_minutes_max=D(10), reviewer_hourly_cost=D(60),
                          tool_cost_per_call=D("0.0002"), fixed_infra_monthly=D(120), observability_monthly=D(40),
                          eval_sampling_pct=D(2), eval_cost_per_sample=D("0.02"))


def _policy_route(accuracy: Decimal, acc_ev: Evidence, fraud=None) -> Route:
    return Route(id="deterministic", name="Deterministic outcome - no model", share_pct=D(8),
                 description="Policy rules decide cases where no model output could change the governed outcome.",
                 deterministic_rule=True, rule_tool_calls=D(1), expected_outcome="Approve / decline by policy",
                 accuracy_pct=accuracy, human_review_pct=D(0),
                 safety=Safety(fraud_auto_approval_pct=fraud, evidence={"fraud_auto_approval_pct": M}),
                 evidence={"share_pct": M, "accuracy_pct": acc_ev})


def _review(pct_: str = "5") -> Decimal:
    return D(pct_)


def sol_only() -> Scenario:
    acc = D("99.2")
    return Scenario(
        features=Features(rules=True, larger=True, larger_model_id="gpt-6-sol", human_review=True, tools=True, advanced_limits=True, completed=True),
        id="sample-sol-only", name="Sol-only", business_process="Bank withdrawal decision",
        description="GPT-6 Sol handles every model-eligible decision.", is_sample=True, sample_note=SAMPLE_NOTE,
        workload=_workload(), models=_jev_models(), costs=_costs(),
        routes=[
            _policy_route(acc, A),
            Route(id="sol", name="Sol decides", share_pct=D(92), rule_tool_calls=D(1),
                  stages=[Stage(model_id="gpt-6-sol")], human_review_pct=_review(),
                  expected_outcome="Approve / decline / refer", accuracy_pct=acc,
                  evidence={"share_pct": M, "accuracy_pct": A}),
        ],
        benchmark=MeasuredBenchmark(
            name="Sol-only (Jev benchmark)", source=BENCH_SOURCE, is_sample=True, decisions=600,
            metrics={
                "model_cost_per_1000_decisions": MeasuredValue(value=D("2.11"), unit="USD"),
                "accuracy_pct": MeasuredValue(value=D("99.2"), unit="%"),
                "p50_latency_ms": MeasuredValue(value=D(2448), unit="ms"),
                "larger_model_calls": MeasuredValue(value=D(552), unit="calls",
                                                    note="Sol-eligible baseline: 600 decisions - 48 policy-decided"),
            }),
    )


def confidence_cascade() -> Scenario:
    acc = D("98.0")
    return Scenario(
        features=Features(rules=True, lightweight=True, lightweight_model_id="jev-1-13", larger=True, larger_model_id="gpt-6-sol", human_review=True, tools=True, advanced_limits=True, budget=True, completed=True),
        id="sample-confidence-cascade", name="Confidence cascade", business_process="Bank withdrawal decision",
        description="Jev handles confident cases; GPT-6 Sol handles uncertain cases.", is_sample=True,
        sample_note=SAMPLE_NOTE, workload=_workload(), models=_jev_models(), costs=_costs(),
        budget=BudgetPolicy(max_monetary_budget_per_task=D("0.01"), enforcement=Enforcement.WARN),
        routes=[
            _policy_route(acc, A),
            Route(id="jev", name="Jev only (confident)", share_pct=D("62.6"), rule_tool_calls=D(1),
                  stages=[Stage(model_id="jev-1-13")], human_review_pct=_review(),
                  expected_outcome="Approve / decline", accuracy_pct=acc,
                  evidence={"share_pct": A, "accuracy_pct": A}),
            Route(id="jev-sol", name="Jev -> Sol (uncertain)", share_pct=D("29.4"), rule_tool_calls=D(1),
                  stages=[Stage(model_id="jev-1-13"), Stage(model_id="gpt-6-sol")], human_review_pct=_review(),
                  expected_outcome="Approve / decline / refer", accuracy_pct=acc,
                  evidence={"share_pct": A, "accuracy_pct": A}),
        ],
        benchmark=MeasuredBenchmark(
            name="Confidence cascade (Jev benchmark)", source=BENCH_SOURCE, is_sample=True, decisions=600,
            metrics={
                "model_cost_per_1000_decisions": MeasuredValue(value=D("0.71"), unit="USD"),
                "accuracy_pct": MeasuredValue(value=D("98.0"), unit="%"),
                "p50_latency_ms": MeasuredValue(value=D(221), unit="ms"),
            }),
    )


def outcome_aware_router() -> Scenario:
    acc = D("98.8")
    zero_fraud = D(0)
    return Scenario(
        features=Features(rules=True, lightweight=True, lightweight_model_id="jev-1-13", larger=True, larger_model_id="gpt-6-sol", human_review=True, tools=True, advanced_limits=True, budget=True, completed=True),
        id="sample-outcome-aware-router", name="Outcome-aware router", business_process="Bank withdrawal decision",
        description=("Deterministic policy eliminates calls that cannot matter; Jev scores the remaining eligible "
                     "cases; GPT-6 Sol is invoked only when a second opinion can change the governed outcome."),
        is_sample=True, sample_note=SAMPLE_NOTE, workload=_workload(), models=_jev_models(), costs=_costs(),
        budget=BudgetPolicy(max_monetary_budget_per_task=D("0.01"), enforcement=Enforcement.REJECT,
                            check_timing=CheckTiming.PRE_CALL),
        routes=[
            _policy_route(acc, A, fraud=zero_fraud),
            Route(id="jev", name="Jev only", share_pct=D("69.1667"), rule_tool_calls=D(1),
                  stages=[Stage(model_id="jev-1-13")], human_review_pct=_review(),
                  expected_outcome="Approve / decline", accuracy_pct=acc,
                  safety=Safety(fraud_auto_approval_pct=zero_fraud, evidence={"fraud_auto_approval_pct": M}),
                  evidence={"share_pct": M, "accuracy_pct": A}),
            Route(id="jev-sol", name="Jev -> Sol (outcome can change)", share_pct=D("22.8333"), rule_tool_calls=D(1),
                  stages=[Stage(model_id="jev-1-13"), Stage(model_id="gpt-6-sol")], human_review_pct=_review(),
                  expected_outcome="Approve / decline / refer", accuracy_pct=acc,
                  safety=Safety(fraud_auto_approval_pct=zero_fraud, evidence={"fraud_auto_approval_pct": M}),
                  evidence={"share_pct": M, "accuracy_pct": A}),
        ],
        benchmark=MeasuredBenchmark(
            name="Outcome-aware router (Jev benchmark)", source=BENCH_SOURCE, is_sample=True, decisions=600,
            metrics={
                "model_cost_per_1000_decisions": MeasuredValue(value=D("0.56"), unit="USD"),
                "accuracy_pct": MeasuredValue(value=D("98.8"), unit="%"),
                "p50_latency_ms": MeasuredValue(value=D(209), unit="ms"),
                "larger_model_calls": MeasuredValue(value=D(137), unit="calls"),
                "larger_model_calls_avoided": MeasuredValue(value=D(415), unit="calls",
                                                            note="vs. Sol-eligible baseline of 552"),
                "larger_model_token_reduction_pct": MeasuredValue(value=D(75), unit="%", note="vs. Sol-only"),
                "model_cost_reduction_pct": MeasuredValue(value=D(73), unit="%", note="vs. Sol-only"),
                "fraud_auto_approved": MeasuredValue(value=D(0), unit="cases"),
            }),
    )


def agentic_illustration() -> Scenario:
    """Shows unbounded-risk detection, direct human review and mandatory review after a model call."""
    models = [m for m in sample_models() if m.id in ("generic-light", "generic-frontier")]
    frontier = models[1].model_copy(deep=True)
    frontier.id = "generic-frontier-agent"
    frontier.name = "Generic frontier agent"
    frontier.limits = CallLimits(agent_loop_enabled=True, max_model_calls=None, max_retries=None)
    frontier.context = frontier.context.model_copy(update={"max_retrieved_tokens": None})
    models.append(frontier)
    return Scenario(
        features=Features(rules=True, lightweight=True, lightweight_model_id="generic-light", larger=True, larger_model_id="generic-frontier-agent", human_review=True, tools=True, advanced_limits=True, budget=True, completed=True),
        id="sample-agentic-illustration", name="Illustrative: agentic exception handling",
        business_process="Payment exception handling",
        description="Illustrative assumptions only - demonstrates unbounded-risk warnings and budget enforcement.",
        is_sample=True, sample_note="Illustrative assumptions only. Not benchmark data.",
        workload=Workload(tasks_per_day=D(500), operating_days_per_month=D(22), annual_growth_pct=D(20),
                          peak_tasks_per_minute=D(3), target_accuracy_pct=D(97), max_latency_ms=D(10000)),
        models=models,
        costs=OperatingCosts(review_minutes_avg=D(6), review_minutes_max=D(20), reviewer_hourly_cost=D(55),
                             tool_cost_per_call=D("0.001"), fixed_infra_monthly=D(400), observability_monthly=D(150),
                             eval_sampling_pct=D(5), eval_cost_per_sample=D("0.05")),
        budget=BudgetPolicy(max_monetary_budget_per_task=D("0.25"), enforcement=Enforcement.REJECT,
                            check_timing=CheckTiming.POST_CALL),
        decision=DecisionInputs(baseline_review_pct=D(40)),
        routes=[
            Route(id="rule", name="Deterministic outcome - no model", share_pct=D(10), deterministic_rule=True,
                  rule_tool_calls=D(1), accuracy_pct=D("99.5"), expected_outcome="Auto-resolve by policy"),
            Route(id="light", name="Lightweight model only", share_pct=D(50), stages=[Stage(model_id="generic-light")],
                  human_review_pct=D(5), accuracy_pct=D(96), expected_outcome="Resolve",
                  safety=Safety(critical_false_approval_pct=D("0.2"), incorrect_auto_rejection_pct=D("0.5"))),
            Route(id="light-agent", name="Lightweight -> frontier agent", share_pct=D(20),
                  stages=[Stage(model_id="generic-light"),
                          Stage(model_id="generic-frontier-agent", tools_exposed=True, avg_tool_calls=D(3),
                                max_tool_calls=None, subagents_enabled=False)],
                  human_review_pct=D(15), accuracy_pct=D(97), larger_changed_outcome_pct=D(30),
                  expected_outcome="Resolve / refer",
                  safety=Safety(critical_false_approval_pct=D("0.1"), incorrect_auto_rejection_pct=D("0.3"))),
            Route(id="human", name="Direct human review", share_pct=D(10), direct_human=True, accuracy_pct=D(99),
                  expected_outcome="Human decision"),
            Route(id="frontier-human", name="Frontier model -> mandatory human review", share_pct=D(10),
                  stages=[Stage(model_id="generic-frontier")], human_review_mandatory=True, accuracy_pct=D(99),
                  expected_outcome="Human decision with model summary"),
        ],
    )


def new_scenario_template() -> Scenario:
    """A blank scenario for the wizard: no routes or models yet; step 1 builds them."""
    return Scenario(name="New scenario", business_process="", models=[], routes=[],
                    costs=OperatingCosts(tool_cost_per_call=D("0.0002")), features=Features())


def all_samples() -> list[Scenario]:
    return [sol_only(), confidence_cascade(), outcome_aware_router(), agentic_illustration()]
