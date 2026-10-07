"""Per-task budget enforcement.

A configured budget is *not* automatically a maximum. It only bounds cost when
the workflow enforces it fail-closed:

* ``reject`` + ``pre_call`` - the next call is refused if its worst case would
  exceed the remaining budget. This is a hard bound only if the worst case of a
  single call is itself bounded (otherwise the pre-check cannot be computed).
* ``reject`` + ``post_call`` - spend is checked after each call, so the task can
  overshoot by up to one worst-case call. Effective bound = budget + overshoot.
* ``degrade`` - execution continues on a fallback path; it is not fail-closed and
  never replaces the calculated maximum. A soft bound is reported for information.
* ``warn`` / ``none`` - monitoring only, never a bound.

Budgets constrain automated spend (models, tools, sub-agents). Human review,
evaluation and other variable costs still apply after a rejection and are added
on top.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.domain.models import BudgetPolicy, CheckTiming, Enforcement
from app.engine.bound import Bound


@dataclass
class BudgetOutcome:
    configured_budget: Decimal | None
    enforcement: Enforcement
    check_timing: CheckTiming
    single_call_overshoot: Bound      # 0 for a working pre-call check
    automated_cap: Bound              # cap applied to automated spend (unbounded = no cap)
    is_hard_bound: bool               # budget itself is a hard maximum
    soft_bound: Bound | None          # degrade-mode informational bound
    explanation: str


def evaluate_budget(budget: Decimal | None, policy: BudgetPolicy, largest_single_call: Bound,
                    unit: str = "cost") -> BudgetOutcome:
    enf, timing = policy.enforcement, policy.check_timing
    none_cap = Bound.unbounded("no enforced budget")
    if budget is None:
        return BudgetOutcome(None, enf, timing, Bound.of(0), none_cap, False, None,
                             f"No per-task {unit} budget configured.")
    b = Bound.of(budget)
    if enf in (Enforcement.NONE, Enforcement.WARN):
        return BudgetOutcome(budget, enf, timing, largest_single_call, none_cap, False, None,
                             f"Budget is {'monitored (warn)' if enf == Enforcement.WARN else 'not enforced'}; "
                             f"it is not an execution bound. The calculated maximum applies.")
    overshoot = Bound.of(0) if timing == CheckTiming.PRE_CALL else largest_single_call
    if timing == CheckTiming.PRE_CALL and not largest_single_call.bounded:
        # A pre-call check needs the next call's worst case; without it the check cannot guarantee anything.
        overshoot = largest_single_call
    if enf == Enforcement.DEGRADE:
        fallback = Bound.of(policy.degrade_fallback_cost) if policy.degrade_fallback_cost is not None \
            else Bound.unbounded("degrade fallback cost not set")
        soft = b + overshoot + fallback if unit == "cost" else b + overshoot
        return BudgetOutcome(budget, enf, timing, overshoot, none_cap, False, soft,
                             "Degrade mode continues on a fallback path; it is not fail-closed, so the "
                             "calculated maximum still applies. Soft bound shown for information.")
    # REJECT
    if not overshoot.bounded:
        return BudgetOutcome(budget, enf, timing, overshoot, none_cap, False, None,
                             "Reject is configured, but the worst case of a single call is unbounded, so the "
                             "check cannot stop the next call before it exceeds the budget. Not a hard bound.")
    if timing == CheckTiming.PRE_CALL:
        return BudgetOutcome(budget, enf, timing, overshoot, b, True, None,
                             "Fail-closed pre-call check: automated spend cannot exceed the budget.")
    return BudgetOutcome(budget, enf, timing, overshoot, b + overshoot, False, None,
                         "Post-call check: spend can overshoot the budget by up to one worst-case call. "
                         "Automated spend is bounded by budget + overshoot.")
