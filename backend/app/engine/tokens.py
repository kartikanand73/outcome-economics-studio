"""Per-call token and cost calculations for a single model."""
from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal

from app.domain.models import BoundsMode, ModelConfig
from app.engine.bound import Bound
from app.engine.money import MILLION, ZERO, pct


# ------------------------------------------------------------------ expected
@dataclass(frozen=True)
class CallCost:
    input_cost: Decimal          # all input tokens at the full input price
    cached_discount: Decimal     # (input price - cached price) x cached tokens
    output_cost: Decimal
    reasoning_cost: Decimal

    @property
    def total(self) -> Decimal:
        return self.input_cost - self.cached_discount + self.output_cost + self.reasoning_cost


def reasoning_tokens_billed(m: ModelConfig) -> Decimal:
    """Reasoning tokens are only costed separately when the model meters them separately."""
    return m.avg_reasoning_tokens if m.separately_metered_reasoning else ZERO


def expected_call_cost(m: ModelConfig) -> CallCost:
    """Model-call cost = input + output + reasoning - applicable cached-input discount."""
    cached_tokens = m.avg_input_tokens * pct(m.cached_input_share_pct)
    return CallCost(
        input_cost=m.avg_input_tokens * m.input_price_per_m / MILLION,
        cached_discount=cached_tokens * (m.input_price_per_m - m.effective_cached_price) / MILLION,
        output_cost=m.avg_output_tokens * m.output_price_per_m / MILLION,
        reasoning_cost=reasoning_tokens_billed(m) * m.effective_reasoning_price / MILLION,
    )


def expected_tokens_per_call(m: ModelConfig) -> Decimal:
    return m.avg_input_tokens + m.avg_output_tokens + reasoning_tokens_billed(m)


def retries_reachable(m: ModelConfig) -> bool:
    return m.retries_enabled or m.retry_rate_pct > 0


def expected_attempt_multiplier(m: ModelConfig) -> Decimal:
    """Each logical call costs (1 + expected retries) attempts."""
    return Decimal(1) + (pct(m.retry_rate_pct) if retries_reachable(m) else ZERO)


# ------------------------------------------------------------------ maximum
def uses_default_bounds(m: ModelConfig) -> bool:
    return m.bounds_mode == BoundsMode.DEFAULT


def max_input_context(m: ModelConfig) -> Bound:
    """System prompt + user input + history + retrieval + tool schemas + examples."""
    if uses_default_bounds(m):
        return Bound.of(m.avg_input_tokens)
    c = m.context
    user = c.max_user_input_tokens if c.max_user_input_tokens is not None else c.avg_user_input_tokens
    total = Bound.of(c.system_prompt_tokens + user + c.tool_schema_tokens + c.few_shot_tokens)
    if c.history_enabled:
        total = total + (Bound.of(c.max_history_tokens) if c.max_history_tokens is not None
                         else Bound.unbounded(f"{m.name}: conversation history is enabled with no maximum"))
    if c.retrieval_enabled:
        total = total + (Bound.of(c.max_retrieved_tokens) if c.max_retrieved_tokens is not None
                         else Bound.unbounded(f"{m.name}: retrieved context is enabled with no maximum"))
    return total


def max_output(m: ModelConfig) -> Bound:
    if uses_default_bounds(m):
        return Bound.of(m.avg_output_tokens)
    c = m.context
    return (Bound.of(c.max_output_tokens) if c.max_output_tokens is not None
            else Bound.unbounded(f"{m.name}: maximum output tokens not set"))


def max_reasoning(m: ModelConfig) -> Bound:
    if not m.separately_metered_reasoning:
        return Bound.of(0)
    if uses_default_bounds(m):
        return Bound.of(m.avg_reasoning_tokens)
    c = m.context
    return (Bound.of(c.max_reasoning_tokens) if c.max_reasoning_tokens is not None
            else Bound.unbounded(f"{m.name}: maximum reasoning tokens not set (reasoning is separately metered)"))


def max_tokens_per_call(m: ModelConfig) -> Bound:
    """Maximum input context + maximum output + maximum reasoning tokens."""
    return max_input_context(m) + max_output(m) + max_reasoning(m)


def max_call_cost(m: ModelConfig) -> Bound:
    """Worst-case cost of one attempt. Assumes no cache hits (the cache is not a bound)."""
    inp = max_input_context(m) * Bound.of(m.input_price_per_m / MILLION)
    out = max_output(m) * Bound.of(m.output_price_per_m / MILLION)
    rsn = max_reasoning(m) * Bound.of(m.effective_reasoning_price / MILLION)
    return inp + out + rsn


def max_logical_calls(m: ModelConfig, avg_calls: Decimal) -> tuple[Bound, list[str]]:
    """Maximum logical calls of this model in one stage (before retries).

    Returns the bound and informational notes (not warnings).
    """
    lim = m.limits
    notes: list[str] = []
    if lim.max_model_calls is not None:
        if lim.agent_loop_enabled and lim.max_agent_iterations is None:
            notes.append(f"{m.name}: agent iterations have no explicit limit; calls are capped by max model calls")
        calls = Bound.of(lim.max_model_calls)
        if lim.agent_loop_enabled and lim.max_agent_iterations is not None:
            calls = calls.min(Bound.of(lim.max_agent_iterations))
        return calls, notes
    if lim.agent_loop_enabled:
        if lim.max_agent_iterations is not None:
            notes.append(f"{m.name}: max model calls derived from agent-iteration limit (1 call per iteration)")
            return Bound.of(lim.max_agent_iterations), notes
        return Bound.unbounded(f"{m.name}: agent loop enabled with no iteration or model-call limit"), notes
    fixed = Decimal(math.ceil(avg_calls)) if avg_calls > 0 else ZERO
    notes.append(f"{m.name}: no model-call limit set; non-agentic stage assumed to make at most "
                 f"{fixed} call(s) (ceiling of average)")
    return Bound.of(fixed), notes


def max_attempts(m: ModelConfig, avg_calls: Decimal) -> tuple[Bound, list[str]]:
    """Maximum billable attempts = logical calls x (1 + max retries)."""
    if uses_default_bounds(m):
        return (Bound.of(avg_calls * expected_attempt_multiplier(m)),
                [f"{m.name}: default bounds - worst case is its average token usage per task "
                 f"({avg_calls:f} call(s) incl. expected retries), priced without cache credit"])
    calls, notes = max_logical_calls(m, avg_calls)
    if not retries_reachable(m):
        return calls, notes
    if m.limits.max_retries is None:
        return calls * Bound.unbounded(f"{m.name}: retries are enabled with no maximum"), notes
    return calls * Bound.of(1 + m.limits.max_retries), notes
