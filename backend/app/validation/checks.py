"""Scenario validation: structural errors, dependency-aware unbounded-risk
warnings and data-quality warnings.

A missing limit only produces a warning when the feature it limits is enabled
or reachable (route share > 0 and the stage/model actually uses it).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal

from app.domain.models import Evidence, Scenario
from app.engine import tokens as tk
from app.engine.money import HUNDRED

TOOL_SCHEMA_COUNT_LIMIT = 10
TOOL_SCHEMA_SHARE_LIMIT = Decimal("0.30")
ASSUMPTION_SHARE_LIMIT = Decimal("0.5")


@dataclass
class Issue:
    severity: str  # error | warning | info
    code: str
    message: str
    route: str | None = None
    model: str | None = None

    def dict(self):
        return asdict(self)


def validate_structure(sc: Scenario) -> list[Issue]:
    out: list[Issue] = []
    ids = {m.id for m in sc.models}
    total = sum((r.share_pct for r in sc.routes), Decimal(0))
    if not sc.routes:
        out.append(Issue("error", "no_routes", "Define at least one decision route."))
    elif total != HUNDRED:
        out.append(Issue("error", "route_share_total",
                         f"Exclusive route shares must total 100% (currently {total.normalize():f}%). "
                         "Conditional human-review rates are set inside each route and are not part of this total."))
    for r in sc.routes:
        if r.share_pct < 0 or r.share_pct > HUNDRED:
            out.append(Issue("error", "route_share_range", f"{r.name}: share must be between 0 and 100%.", r.id))
        if not (0 <= r.accuracy_pct <= 100):
            out.append(Issue("error", "accuracy_range", f"{r.name}: accuracy must be between 0 and 100%.", r.id))
        if not (0 <= r.human_review_pct <= 100):
            out.append(Issue("error", "review_range", f"{r.name}: human-review rate must be between 0 and 100%.", r.id))
        if r.direct_human and r.stages:
            out.append(Issue("warning", "direct_human_with_models",
                             f"{r.name}: marked direct-human but also has model stages; model spend here cannot "
                             "change the outcome because a human decides.", r.id))
        for s in r.stages:
            if s.model_id not in ids:
                out.append(Issue("error", "unknown_model", f"{r.name}: stage references unknown model '{s.model_id}'.", r.id))
            if s.subagents_enabled and s.subagent_model_id and s.subagent_model_id not in ids:
                out.append(Issue("error", "unknown_model",
                                 f"{r.name}: sub-agent references unknown model '{s.subagent_model_id}'.", r.id))
    if sc.workload.tasks_per_day <= 0 or sc.workload.operating_days_per_month <= 0:
        out.append(Issue("error", "volume", "Tasks per day and operating days per month must be greater than zero."))
    return out


def validate_bounds(sc: Scenario) -> list[Issue]:
    """Dependency-aware unbounded-risk detection over reachable stages only."""
    out: list[Issue] = []
    seen: set[tuple[str, str]] = set()
    ids = {m.id for m in sc.models}

    def add(code: str, severity: str, msg: str, model_id: str, route_id: str | None = None):
        if (code, model_id) in seen:
            return
        seen.add((code, model_id))
        out.append(Issue(severity, code, msg, route_id, model_id))

    for r in sc.routes:
        if r.share_pct <= 0:
            continue  # unreachable route: its missing limits cannot be exercised
        for s in r.stages:
            if s.model_id not in ids:
                continue
            models = [sc.model_by_id(s.model_id)]
            if s.subagents_enabled and s.subagent_model_id in ids:
                models.append(sc.model_by_id(s.subagent_model_id))
            for m in models:
                if tk.uses_default_bounds(m):
                    add("default_bounds", "info",
                        f"{m.name}: uses default bounds - its worst case is its average token cost. "
                        "Set custom limits in Context & bounds to model retries, retrieval or agent loops.",
                        m.id, r.id)
                    continue
                c, lim = m.context, m.limits
                if lim.agent_loop_enabled and lim.max_agent_iterations is None:
                    if lim.max_model_calls is None:
                        add("iterations_unbounded", "warning",
                            f"{m.name}: agent loop is enabled with no iteration limit and no model-call limit - "
                            "agent iterations and model calls are unbounded.", m.id, r.id)
                    else:
                        add("iterations_capped_by_calls", "info",
                            f"{m.name}: agent iterations have no explicit limit; they are capped only by max model "
                            f"calls ({lim.max_model_calls}).", m.id, r.id)
                if c.retrieval_enabled and c.max_retrieved_tokens is None:
                    add("retrieval_unbounded", "warning",
                        f"{m.name}: retrieval is enabled with no maximum retrieved-document tokens.", m.id, r.id)
                if c.history_enabled and c.max_history_tokens is None:
                    add("history_unbounded", "warning",
                        f"{m.name}: conversation history is enabled with no maximum history tokens.", m.id, r.id)
                if tk.retries_reachable(m) and lim.max_retries is None:
                    add("retries_unbounded", "warning",
                        f"{m.name}: retries are enabled with no maximum retry count.", m.id, r.id)
                if c.max_output_tokens is None:
                    add("output_unbounded", "warning", f"{m.name}: maximum output tokens not set.", m.id, r.id)
                if m.separately_metered_reasoning and c.max_reasoning_tokens is None:
                    add("reasoning_unbounded", "warning",
                        f"{m.name}: reasoning tokens are separately metered but have no maximum.", m.id, r.id)
                if not m.separately_metered_reasoning and m.avg_reasoning_tokens > 0:
                    add("reasoning_not_metered", "info",
                        f"{m.name}: average reasoning tokens entered but reasoning is not separately metered; "
                        "they are not costed separately (assumed included in output).", m.id, r.id)
                if c.max_user_input_tokens is None and c.avg_user_input_tokens > 0:
                    add("user_input_max_missing", "info",
                        f"{m.name}: maximum user input not set; the bounded maximum uses the average.", m.id, r.id)
                ctx = tk.max_input_context(m)
                if c.tool_schema_count > TOOL_SCHEMA_COUNT_LIMIT or (
                        ctx.bounded and ctx.value > 0 and c.tool_schema_tokens / ctx.value > TOOL_SCHEMA_SHARE_LIMIT):
                    add("tool_schema_bloat", "warning",
                        f"{m.name}: {c.tool_schema_count} tool schemas ({c.tool_schema_tokens:f} tokens) are sent on "
                        "every call. Consider sending only the tools this step can use.", m.id, r.id)
            if s.tools_exposed and s.max_tool_calls is None:
                add("tool_calls_unbounded", "warning",
                    f"{r.name} / {sc.model_by_id(s.model_id).name}: tools are exposed with no tool-call limit.",
                    s.model_id + ":tools:" + r.id, r.id)
            if not s.tools_exposed and sc.model_by_id(s.model_id).context.tool_schema_count > 0:
                add("schemas_without_tools", "info",
                    f"{r.name} / {sc.model_by_id(s.model_id).name}: tool schemas are sent but no tools are exposed "
                    "on this step - those tokens buy nothing.", s.model_id + ":schemas:" + r.id, r.id)
            if s.subagents_enabled and s.max_subagents is None:
                add("subagents_unbounded", "warning",
                    f"{r.name} / {sc.model_by_id(s.model_id).name}: sub-agents are enabled with no fan-out limit.",
                    s.model_id + ":sub:" + r.id, r.id)
    return out


def _key_evidence(sc: Scenario) -> list[tuple[Evidence, str]]:
    """Evidence labels of the inputs that drive the headline numbers, with a readable name for each."""
    items: list[tuple[Evidence, str]] = []
    used = {s.model_id for r in sc.routes if r.share_pct > 0 for s in r.stages}
    names = {"input_price_per_m": "input price", "output_price_per_m": "output price",
             "avg_input_tokens": "input tokens", "avg_output_tokens": "output tokens"}
    for m in sc.models:
        if m.id in used:
            items += [(m.ev(f), f"{m.name}: {label}") for f, label in names.items()]
    for r in sc.routes:
        if r.share_pct > 0:
            items += [(r.ev("share_pct"), f"{r.name}: traffic share"), (r.ev("accuracy_pct"), f"{r.name}: accuracy")]
            if r.human_review_pct > 0 or r.direct_human or r.human_review_mandatory:
                items.append((r.ev("human_review_pct"), f"{r.name}: review rate"))
    if any((r.human_review_pct > 0 or r.direct_human or r.human_review_mandatory) and r.share_pct > 0 for r in sc.routes):
        items += [(sc.costs.ev("review_minutes_avg"), "Review time"), (sc.costs.ev("reviewer_hourly_cost"), "Reviewer hourly cost")]
    return items


def evidence_basis(sc: Scenario) -> dict:
    items = _key_evidence(sc)
    counts = {e.value: 0 for e in Evidence}
    for e, _ in items:
        counts[e.value] += 1
    n = len(items) or 1
    share = Decimal(counts[Evidence.ASSUMPTION.value]) / Decimal(n)
    return {"counts": counts, "total": len(items), "assumption_share": share,
            "mainly_assumptions": share > ASSUMPTION_SHARE_LIMIT,
            "assumed_inputs": [name for e, name in items if e == Evidence.ASSUMPTION]}


def validate_quality(sc: Scenario) -> list[Issue]:
    out: list[Issue] = []
    used = {s.model_id for r in sc.routes if r.share_pct > 0 for s in r.stages}
    for m in sc.models:
        if m.id not in used:
            continue
        if m.input_price_per_m == 0 and m.output_price_per_m == 0:
            out.append(Issue("warning", "missing_price", f"{m.name}: input and output prices are zero.", model=m.id))
        if m.avg_input_tokens == 0 and m.avg_output_tokens == 0:
            out.append(Issue("warning", "missing_tokens", f"{m.name}: average token usage is zero.", model=m.id))
    reviewed = any((r.human_review_pct > 0 or r.direct_human or r.human_review_mandatory) and r.share_pct > 0
                   for r in sc.routes)
    if reviewed and sc.costs.reviewer_hourly_cost == 0:
        out.append(Issue("warning", "missing_reviewer_cost", "Tasks are reviewed but reviewer hourly cost is zero."))
    basis = evidence_basis(sc)
    if basis["mainly_assumptions"]:
        pct_ = (basis["assumption_share"] * 100).quantize(Decimal(1))
        out.append(Issue("warning", "mainly_assumptions",
                         f"{pct_}% of the key inputs are user assumptions. Treat results as an estimate, "
                         "not a measurement; import benchmark data to replace assumptions."))
    if any(r.share_pct > 0 and r.stages and r.human_review_mandatory for r in sc.routes):
        out.append(Issue("info", "model_before_mandatory_review",
                         "Some tasks are sent to a model even though human review is mandatory on that route; "
                         "the model call cannot change the governed outcome there."))
    b = sc.budget
    if b.max_monetary_budget_per_task is not None and b.enforcement.value in ("none", "warn"):
        out.append(Issue("info", "budget_not_enforced",
                         "A monetary budget is configured but not enforced fail-closed; it does not bound cost."))
    return out


def validate(sc: Scenario) -> list[Issue]:
    structural = validate_structure(sc)
    if any(i.code == "unknown_model" for i in structural):
        return structural
    return structural + validate_bounds(sc) + validate_quality(sc)
