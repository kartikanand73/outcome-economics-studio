"""Apply the scenario's building blocks before calculating.

An unticked block is switched off for the calculation only; its values stay in the scenario so ticking it again
restores them. Scenarios without ``features`` (older files) are calculated exactly as configured.
"""
from __future__ import annotations

from decimal import Decimal

from app.domain.models import BoundsMode, BudgetPolicy, Scenario

ZERO = Decimal(0)


def effective(sc: Scenario) -> Scenario:
    f = sc.features
    if f is None:
        return sc
    sc = sc.model_copy(deep=True)
    if not f.advanced_limits:
        for m in sc.models:
            m.bounds_mode = BoundsMode.DEFAULT
    if not f.budget:
        sc.budget = BudgetPolicy()
    if not f.infra_costs:
        c = sc.costs
        c.fixed_infra_monthly = c.observability_monthly = c.other_fixed_monthly = ZERO
        c.eval_sampling_pct = c.other_variable_per_task = ZERO
    if not f.human_review:
        for r in sc.routes:
            r.human_review_pct = ZERO
            r.human_review_mandatory = False
    if not f.tools:
        for r in sc.routes:
            r.rule_tool_calls = ZERO
            r.max_rule_tool_calls = None
            for s in r.stages:
                s.tools_exposed = False
                s.avg_tool_calls = ZERO
    if not f.advanced_limits:
        for r in sc.routes:
            for s in r.stages:
                s.subagents_enabled = False
    return sc
