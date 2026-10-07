"""Token-cost calculations."""
from decimal import Decimal as D

from app.domain.models import ContextBounds
from app.engine import tokens as tk
from tests.conftest import make_model


def test_model_call_cost_components_and_cached_discount():
    m = make_model(input_price_per_m=D("2"), output_price_per_m=D("8"), cached_input_price_per_m=D("0.5"),
                   cached_input_share_pct=D("50"), separately_metered_reasoning=True,
                   avg_input_tokens=D(1000), avg_output_tokens=D(500), avg_reasoning_tokens=D(200))
    c = tk.expected_call_cost(m)
    assert c.input_cost == D("0.002")
    assert c.output_cost == D("0.004")
    assert c.reasoning_cost == D("0.0016")          # reasoning defaults to the output price
    assert c.cached_discount == D("0.00075")        # 500 cached tokens x (2 - 0.5) / 1M
    assert c.total == D("0.00685")


def test_reasoning_price_override():
    m = make_model(output_price_per_m=D("8"), reasoning_price_per_m=D("2"), separately_metered_reasoning=True,
                   avg_input_tokens=D(0), avg_output_tokens=D(0), avg_reasoning_tokens=D(1_000_000))
    assert tk.expected_call_cost(m).total == D("2")


def test_reasoning_not_costed_when_not_separately_metered():
    m = make_model(separately_metered_reasoning=False, avg_reasoning_tokens=D(5000))
    assert tk.expected_call_cost(m).reasoning_cost == 0
    assert tk.expected_tokens_per_call(m) == D(1100)


def test_retry_multiplier_only_when_retries_reachable():
    assert tk.expected_attempt_multiplier(make_model(retry_rate_pct=D(0))) == 1
    assert tk.expected_attempt_multiplier(make_model(retry_rate_pct=D(5))) == D("1.05")


def test_max_context_and_tokens_per_call():
    m = make_model(separately_metered_reasoning=True, context=ContextBounds(
        system_prompt_tokens=D(400), avg_user_input_tokens=D(200), max_user_input_tokens=D(300),
        history_enabled=True, max_history_tokens=D(1000), retrieval_enabled=True, max_retrieved_tokens=D(2000),
        tool_schema_tokens=D(500), few_shot_tokens=D(600), max_output_tokens=D(256), max_reasoning_tokens=D(1024)))
    # system + max user + history + retrieval + tool schemas + examples
    assert tk.max_input_context(m).value == D(400 + 300 + 1000 + 2000 + 500 + 600)
    assert tk.max_tokens_per_call(m).value == D(4800 + 256 + 1024)


def test_max_call_cost_assumes_no_cache_hits():
    m = make_model(input_price_per_m=D("1"), output_price_per_m=D("4"), cached_input_price_per_m=D("0.1"),
                   cached_input_share_pct=D("90"))
    # max input 1000 (500 system + 500 user) at full price, 200 output
    assert tk.max_call_cost(m).value == D("0.001") + D("0.0008")


def test_unbounded_output_is_reported_with_reason():
    m = make_model(context=ContextBounds(system_prompt_tokens=D(100), max_output_tokens=None))
    b = tk.max_tokens_per_call(m)
    assert not b.bounded
    assert any("output" in r for r in b.reasons)


def test_disabled_features_do_not_make_context_unbounded():
    m = make_model(context=ContextBounds(system_prompt_tokens=D(100), max_output_tokens=D(10),
                                         history_enabled=False, retrieval_enabled=False,
                                         max_history_tokens=None, max_retrieved_tokens=None))
    assert tk.max_tokens_per_call(m).bounded
