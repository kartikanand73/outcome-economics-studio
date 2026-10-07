"""Decision-value metrics: does an additional model call change the governed outcome?

These metrics separate spend that can change a decision from spend that only
adds tokens, latency and cost.
"""
from __future__ import annotations

from decimal import Decimal

from app.domain.models import Route, Scenario, Tier
from app.engine.money import HUNDRED, ZERO, pct, safe_div
from app.engine.routes import RouteExpected, effective_review_pct, is_model_eligible


def _has_larger(sc: Scenario, r: Route) -> bool:
    for s in r.stages:
        if sc.model_by_id(s.model_id).tier == Tier.LARGER:
            return True
        if s.subagents_enabled and s.subagent_model_id and sc.model_by_id(s.subagent_model_id).tier == Tier.LARGER:
            return True
    return False


def _pct_text(v: Decimal) -> str:
    q = v.quantize(Decimal("0.01"))
    return format(q, "f").rstrip("0").rstrip(".") if "." in format(q, "f") else format(q, "f")


def change_question(sc: Scenario, r: Route) -> dict:
    """Answer 'Could the additional model call change the governed outcome?' for one route."""
    if not _has_larger(sc, r):
        return {"applies": False, "answer": "n/a", "detail": "No larger-model call on this route."}
    if r.direct_human:
        return {"applies": True, "answer": "no", "detail": "A human decides on this route; the model call cannot "
                                                          "change the governed outcome."}
    if r.human_review_mandatory:
        return {"applies": True, "answer": "no", "detail": "Human review is mandatory regardless of the model "
                                                          "output; the call cannot change the governed outcome."}
    if r.larger_changed_outcome_pct is None:
        return {"applies": True, "answer": "unknown", "detail": "Not measured. Record how often the larger model "
                                                               "changes the outcome to judge its value."}
    if r.larger_changed_outcome_pct == 0:
        return {"applies": True, "answer": "no", "detail": "0% of larger-model calls changed the outcome."}
    return {"applies": True, "answer": "yes",
            "detail": f"{_pct_text(r.larger_changed_outcome_pct)}% of larger-model calls changed the outcome.",
            "evidence": r.ev("larger_changed_outcome_pct").value}


def _safety_rate(sc: Scenario, weights: dict[str, Decimal], field: str, reviewed_basis: bool = False) -> dict:
    """Share-weighted safety rate. Unknown (None) is never treated as zero."""
    total = known_w = ZERO
    missing: list[str] = []
    evidences: set[str] = set()
    denom = ZERO
    for r in sc.routes:
        w = weights[r.id]
        if w <= 0:
            continue
        basis = w * pct(effective_review_pct(r)) if reviewed_basis else w
        if basis == 0:
            continue
        v = getattr(r.safety, field)
        denom += basis
        if v is None:
            missing.append(r.name)
            continue
        known_w += basis
        total += basis * pct(v)
        evidences.add(r.safety.ev(field).value)
    if denom == 0:
        return {"per_task": ZERO if not reviewed_basis else None, "status": "not_applicable", "missing_routes": [],
                "evidence": []}
    if known_w == 0:
        return {"per_task": None, "status": "not_measured", "missing_routes": missing, "evidence": []}
    return {"per_task": total if not reviewed_basis else total / denom,
            "status": "partial" if missing else "complete", "missing_routes": missing, "evidence": sorted(evidences)}


def decision_value(sc: Scenario, weights: dict[str, Decimal], exp: dict[str, RouteExpected],
                   monthly_tasks: Decimal) -> dict:
    larger_calls = larger_cost = larger_tokens = escalation = eligible = ZERO
    changed = unchanged_tokens = unchanged_spend = ZERO
    changed_known = True
    mandatory_share = mandatory_spend = ZERO
    model_free = ZERO
    for r in sc.routes:
        w = weights[r.id]
        if w <= 0:
            continue
        e = exp[r.id]
        if is_model_eligible(r):
            eligible += w
        if not r.stages and not r.direct_human:
            model_free += w
        if r.stages and (r.human_review_mandatory or r.direct_human):
            mandatory_share += w
            mandatory_spend += w * e.model_cost
        if e.larger_calls > 0:
            escalation += w
            larger_calls += w * e.larger_calls
            larger_cost += w * e.larger_cost
            larger_tokens += w * e.larger_tokens
            if r.human_review_mandatory or r.direct_human:
                rate = ZERO  # cannot change the governed outcome
            elif r.larger_changed_outcome_pct is None:
                changed_known = False
                continue
            else:
                rate = pct(r.larger_changed_outcome_pct)
            changed += w * rate
            unchanged_tokens += w * e.larger_tokens * (1 - rate)
            if not (r.human_review_mandatory or r.direct_human):
                unchanged_spend += w * e.larger_cost * (1 - rate)
    baseline_larger = eligible  # one larger-model call per model-eligible task
    avoided = max(baseline_larger - larger_calls, ZERO)
    actual_review = sum((weights[r.id] * pct(effective_review_pct(r)) for r in sc.routes), ZERO)
    prevented = None
    if sc.decision.baseline_review_pct is not None:
        prevented = max(pct(sc.decision.baseline_review_pct) - actual_review, ZERO)

    fraud = _safety_rate(sc, weights, "fraud_auto_approval_pct")
    critical = _safety_rate(sc, weights, "critical_false_approval_pct")
    wrong_reject = _safety_rate(sc, weights, "incorrect_auto_rejection_pct")
    unnecessary = _safety_rate(sc, weights, "unnecessary_review_pct", reviewed_basis=True)
    override = _safety_rate(sc, weights, "policy_override_pct", reviewed_basis=True)
    unsafe_known = any(x["per_task"] not in (None, ZERO) for x in (fraud, critical))
    safety_measured = fraud["status"] == "complete" and critical["status"] == "complete"

    def monthly(v):
        return None if v is None else v * monthly_tasks

    return {
        "question": "Could the additional model call change the governed outcome?",
        "larger_escalation_rate": escalation,
        "larger_calls_per_task": larger_calls,
        "larger_cost_per_task": larger_cost,
        "larger_tokens_per_task": larger_tokens,
        "larger_eligible_baseline_per_task": baseline_larger,
        "larger_calls_avoided_per_task": avoided,
        "model_free_share": model_free,
        "changed_outcome_share_of_larger": (safe_div(changed, escalation) if changed_known else None),
        "changed_decisions_per_task": changed if changed_known else None,
        "cost_per_changed_decision": (safe_div(larger_cost, changed) if changed_known else None),
        "tokens_on_unchanged_decisions_per_task": unchanged_tokens if changed_known else None,
        "avoidable_model_spend_per_task": (unchanged_spend + mandatory_spend) if changed_known else None,
        "avoidable_spend_complete": changed_known,
        "mandatory_review_model_share": mandatory_share,
        "mandatory_review_model_spend_per_task": mandatory_spend,
        "human_review_share": actual_review,
        "human_reviews_prevented_per_task": prevented,
        "human_reviews_prevented_safe": (prevented is not None and safety_measured and not unsafe_known),
        "safety": {
            "fraud_auto_approved": {**fraud, "monthly": monthly(fraud["per_task"])},
            "critical_false_approvals": {**critical, "monthly": monthly(critical["per_task"])},
            "incorrect_auto_rejections": {**wrong_reject, "monthly": monthly(wrong_reject["per_task"])},
            "unnecessary_human_reviews": {**unnecessary,
                                          "monthly": None if unnecessary["per_task"] is None
                                          else unnecessary["per_task"] * actual_review * monthly_tasks},
            "policy_override_rate": override,
        },
        "routes": {r.id: change_question(sc, r) for r in sc.routes},
    }
