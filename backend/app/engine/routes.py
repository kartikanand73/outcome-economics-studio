"""Route-level calculations: expected cost and the reachable bounded maximum.

A route is one exclusive path a task can take. Its cost is the sum of every
model stage, tool call, human review, evaluation sample and other variable
cost incurred on that path. Human review is a *conditional* rate inside the
route - it never changes the route's share of traffic.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal

from app.domain.models import ModelConfig, Route, Scenario, Stage, Tier
from app.engine import tokens as tk
from app.engine.bound import Bound, bsum
from app.engine.money import HUNDRED, ZERO, pct

CATEGORIES = ("lightweight_model", "larger_model", "tool_api", "human_review", "evaluation", "other_variable")


def effective_review_pct(route: Route) -> Decimal:
    """Direct-human routes and mandatory-review routes review 100 % of their tasks."""
    if route.direct_human or route.human_review_mandatory:
        return HUNDRED
    return route.human_review_pct


def is_model_eligible(route: Route) -> bool:
    if route.model_eligible is not None:
        return route.model_eligible
    if route.direct_human:
        return False
    return bool(route.stages) or not route.deterministic_rule


def stage_avg_calls(stage: Stage, m: ModelConfig) -> Decimal:
    return stage.avg_calls_override if stage.avg_calls_override is not None else m.avg_calls_per_task


def _cat(tier: Tier) -> str:
    return "larger_model" if tier == Tier.LARGER else "lightweight_model"


# ------------------------------------------------------------------ expected
@dataclass
class StageExpected:
    model_id: str
    model_name: str
    tier: Tier
    calls: Decimal            # expected billable attempts incl. retries
    tokens: Decimal
    model_cost: Decimal
    tool_calls: Decimal
    tool_cost: Decimal
    subagent_calls: Decimal
    subagent_tokens: Decimal
    subagent_cost: Decimal
    subagent_tier: Tier | None


@dataclass
class RouteExpected:
    route_id: str
    categories: dict[str, Decimal]
    stages: list[StageExpected]
    review_pct: Decimal
    reviews: Decimal           # expected human reviews per task on this route
    tokens: Decimal
    model_calls: Decimal
    larger_calls: Decimal
    larger_tokens: Decimal
    larger_cost: Decimal
    tool_calls: Decimal

    @property
    def total(self) -> Decimal:
        return sum(self.categories.values(), ZERO)

    @property
    def model_cost(self) -> Decimal:
        return self.categories["lightweight_model"] + self.categories["larger_model"]


def expected_stage(sc: Scenario, stage: Stage) -> StageExpected:
    m = sc.model_by_id(stage.model_id)
    calls = stage_avg_calls(stage, m) * tk.expected_attempt_multiplier(m)
    tool_cost = stage.avg_tool_calls * sc.costs.tool_cost_per_call
    sub_calls = sub_tokens = sub_cost = ZERO
    sub_tier = None
    if stage.subagents_enabled and stage.avg_subagents > 0:
        sm = sc.model_by_id(stage.subagent_model_id) if stage.subagent_model_id else m
        per_sub_calls = sm.avg_calls_per_task * tk.expected_attempt_multiplier(sm)
        sub_calls = stage.avg_subagents * per_sub_calls
        sub_tokens = sub_calls * tk.expected_tokens_per_call(sm)
        sub_cost = sub_calls * tk.expected_call_cost(sm).total
        sub_tier = sm.tier
    return StageExpected(
        model_id=m.id, model_name=m.name, tier=m.tier, calls=calls,
        tokens=calls * tk.expected_tokens_per_call(m),
        model_cost=calls * tk.expected_call_cost(m).total,
        tool_calls=stage.avg_tool_calls, tool_cost=tool_cost,
        subagent_calls=sub_calls, subagent_tokens=sub_tokens, subagent_cost=sub_cost, subagent_tier=sub_tier,
    )


def expected_route(sc: Scenario, route: Route) -> RouteExpected:
    c = sc.costs
    cats = {k: ZERO for k in CATEGORIES}
    stages = [expected_stage(sc, s) for s in route.stages]
    tokens = model_calls = larger_calls = larger_tokens = larger_cost = ZERO
    tool_calls = route.rule_tool_calls
    cats["tool_api"] += route.rule_tool_calls * c.tool_cost_per_call
    for s in stages:
        cats[_cat(s.tier)] += s.model_cost
        cats["tool_api"] += s.tool_cost
        tool_calls += s.tool_calls
        tokens += s.tokens
        model_calls += s.calls
        if s.tier == Tier.LARGER:
            larger_calls += s.calls
            larger_tokens += s.tokens
            larger_cost += s.model_cost
        if s.subagent_tier is not None:
            cats[_cat(s.subagent_tier)] += s.subagent_cost
            tokens += s.subagent_tokens
            model_calls += s.subagent_calls
            if s.subagent_tier == Tier.LARGER:
                larger_calls += s.subagent_calls
                larger_tokens += s.subagent_tokens
                larger_cost += s.subagent_cost
    review_pct = effective_review_pct(route)
    reviews = pct(review_pct)
    minutes = route.review_minutes_override if route.review_minutes_override is not None else c.review_minutes_avg
    # Human-review cost = minutes / 60 x hourly cost x reviewed tasks
    cats["human_review"] = minutes / Decimal(60) * c.reviewer_hourly_cost * reviews
    cats["evaluation"] = pct(c.eval_sampling_pct) * c.eval_cost_per_sample
    cats["other_variable"] = c.other_variable_per_task
    return RouteExpected(route.id, cats, stages, review_pct, reviews, tokens, model_calls,
                         larger_calls, larger_tokens, larger_cost, tool_calls)


# ------------------------------------------------------------------ maximum
@dataclass
class StageMax:
    model_id: str
    model_name: str
    tier: Tier
    max_input_context: Bound
    max_tokens_per_call: Bound
    max_call_cost: Bound
    max_attempts: Bound
    max_tokens: Bound        # attempts x tokens per call (+ sub-agents)
    model_cost: Bound        # attempts x cost per call
    tool_cost: Bound
    subagent_cost: Bound
    subagent_tokens: Bound
    notes: list[str] = field(default_factory=list)

    @property
    def automated_cost(self) -> Bound:
        return self.model_cost + self.tool_cost + self.subagent_cost


@dataclass
class RouteMax:
    route_id: str
    stages: list[StageMax]
    rule_tool_cost: Bound
    automated_cost: Bound     # models + tools + sub-agents: what a per-task budget can stop
    non_automated_cost: Bound  # human review + evaluation + other variable
    tokens: Bound
    largest_single_call_cost: Bound
    largest_single_call_tokens: Bound
    notes: list[str]

    @property
    def total(self) -> Bound:
        return self.automated_cost + self.non_automated_cost


def max_stage(sc: Scenario, stage: Stage) -> StageMax:
    m = sc.model_by_id(stage.model_id)
    attempts, notes = tk.max_attempts(m, stage_avg_calls(stage, m))
    per_call_tokens = tk.max_tokens_per_call(m)
    per_call_cost = tk.max_call_cost(m)
    tool_cost = Bound.of(0)
    if stage.tools_exposed:
        tool_calls = (Bound.of(stage.max_tool_calls) if stage.max_tool_calls is not None
                      else Bound.unbounded(f"{m.name} stage: tools are exposed with no tool-call limit"))
        tool_cost = tool_calls * Bound.of(sc.costs.tool_cost_per_call)
    sub_cost = sub_tokens = Bound.of(0)
    if stage.subagents_enabled:
        sm = sc.model_by_id(stage.subagent_model_id) if stage.subagent_model_id else m
        n = (Bound.of(stage.max_subagents) if stage.max_subagents is not None
             else Bound.unbounded(f"{m.name} stage: sub-agents are enabled with no fan-out limit"))
        sub_attempts, sub_notes = tk.max_attempts(sm, sm.avg_calls_per_task)
        notes += [f"sub-agent: {x}" for x in sub_notes]
        sub_cost = n * sub_attempts * tk.max_call_cost(sm)
        sub_tokens = n * sub_attempts * tk.max_tokens_per_call(sm)
    return StageMax(
        model_id=m.id, model_name=m.name, tier=m.tier,
        max_input_context=tk.max_input_context(m), max_tokens_per_call=per_call_tokens,
        max_call_cost=per_call_cost, max_attempts=attempts,
        max_tokens=attempts * per_call_tokens + sub_tokens,
        model_cost=attempts * per_call_cost, tool_cost=tool_cost,
        subagent_cost=sub_cost, subagent_tokens=sub_tokens, notes=notes,
    )


def max_route(sc: Scenario, route: Route) -> RouteMax:
    """Sum of every reachable stage's worst case, computed stage by stage."""
    c = sc.costs
    notes: list[str] = []
    stages = [max_stage(sc, s) for s in route.stages]
    for s in stages:
        notes += s.notes
    # Rule-level tool calls are made by deterministic code, so they are structurally fixed.
    if route.rule_tool_calls > 0:
        if route.max_rule_tool_calls is not None:
            n_rule = Decimal(route.max_rule_tool_calls)
        else:
            n_rule = Decimal(math.ceil(route.rule_tool_calls))
            notes.append(f"{route.name}: rule tool-call maximum not set; assumed {n_rule} (ceiling of average)")
        rule_tool_cost = Bound.of(n_rule * c.tool_cost_per_call)
    else:
        rule_tool_cost = Bound.of(0)
    automated = rule_tool_cost + bsum(s.automated_cost for s in stages)
    non_auto = Bound.of(0)
    if effective_review_pct(route) > 0:
        if route.review_minutes_override is not None:
            minutes = route.review_minutes_override
        elif c.review_minutes_max is not None:
            minutes = c.review_minutes_max
        else:
            minutes = c.review_minutes_avg
            notes.append(f"{route.name}: maximum review time not set; worst case uses the average review time")
        non_auto = non_auto + Bound.of(minutes / Decimal(60) * c.reviewer_hourly_cost)
    if c.eval_sampling_pct > 0:
        non_auto = non_auto + Bound.of(c.eval_cost_per_sample)
    non_auto = non_auto + Bound.of(c.other_variable_per_task)
    tokens = bsum(s.max_tokens for s in stages)
    largest_cost = Bound.of(0)
    largest_tokens = Bound.of(0)
    for st_cfg, s in zip(route.stages, stages):
        largest_cost = largest_cost.max(s.max_call_cost)
        largest_tokens = largest_tokens.max(s.max_tokens_per_call)
        if st_cfg.subagents_enabled:
            sm = sc.model_by_id(st_cfg.subagent_model_id) if st_cfg.subagent_model_id else sc.model_by_id(st_cfg.model_id)
            largest_cost = largest_cost.max(tk.max_call_cost(sm))
            largest_tokens = largest_tokens.max(tk.max_tokens_per_call(sm))
    return RouteMax(route.id, stages, rule_tool_cost, automated, non_auto, tokens,
                    largest_cost, largest_tokens, notes)
