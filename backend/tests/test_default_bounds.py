"""Default bounds: an unconfigured model's worst case is just its token cost; no LLM means $0 LLM cost."""
from decimal import Decimal as D

from app.domain.models import BoundsMode, CallLimits, ContextBounds, OperatingCosts
from app.engine.aggregate import calculate
from app.engine.routes import expected_route
from app.validation.checks import validate
from tests.conftest import make_model, make_scenario, route

LIGHT_CALL = D("0.0014")  # 1000 in x $1/M + 100 out x $4/M


def _default_model(**kw):
    # deliberately "dangerous" custom settings that default mode must ignore
    return make_model("light", bounds_mode=BoundsMode.DEFAULT, retries_enabled=True, retry_rate_pct=D(10),
                      context=ContextBounds(max_output_tokens=None, retrieval_enabled=True),
                      limits=CallLimits(agent_loop_enabled=True), **kw)


def test_default_bounds_max_is_the_models_token_cost():
    sc = make_scenario([route("a", 100, ["light"])], models=[_default_model()])
    r = calculate(sc)
    assert r["ok"]
    mx = r["summary"]["calculated_max_variable_per_task"]
    assert mx["unbounded"] is False
    # one call x (1 + 10% retries) at average tokens, no cache credit
    assert mx["value"] == LIGHT_CALL * D("1.1")
    assert r["summary"]["calculated_max_tokens_per_task"]["value"] == D(1100) * D("1.1")


def test_default_bounds_max_never_below_expected_even_with_cache():
    m = _default_model(cached_input_price_per_m=D("0.1"), cached_input_share_pct=D(80))
    sc = make_scenario([route("a", 100, ["light"])], models=[m])
    r = calculate(sc)
    assert r["summary"]["calculated_max_variable_per_task"]["value"] > r["summary"]["variable_cost_per_task"]["value"]


def test_default_bounds_raise_no_unbounded_warnings():
    sc = make_scenario([route("a", 100, ["light"])], models=[_default_model()])
    codes = {i.code for i in validate(sc)}
    assert "default_bounds" in codes
    assert not codes & {"output_unbounded", "retrieval_unbounded", "iterations_unbounded", "retries_unbounded"}


def test_custom_mode_still_detects_unbounded():
    m = _default_model()
    m.bounds_mode = BoundsMode.CUSTOM
    sc = make_scenario([route("a", 100, ["light"])], models=[m])
    assert calculate(sc)["summary"]["max_cost_per_task"]["unbounded"] is True


def test_no_llm_route_has_zero_llm_cost():
    costs = OperatingCosts(review_minutes_avg=D(3), reviewer_hourly_cost=D(60), tool_cost_per_call=D("0.001"))
    sc = make_scenario([route("rule", 70, [], deterministic_rule=True, rule_tool_calls=D(1)),
                        route("human", 30, [], direct_human=True)], costs=costs)
    r = calculate(sc)
    assert r["ok"]
    b = r["breakdown_per_task"]
    assert b["lightweight_model"]["value"] == 0 and b["larger_model"]["value"] == 0
    assert r["projection"]["model_cost_per_1000"] == 0
    assert r["summary"]["expected_tokens_per_task"]["value"] == 0
    assert r["summary"]["max_tokens_per_task"]["value"] == 0
    assert r["summary"]["max_cost_per_task"]["unbounded"] is False
    rule = expected_route(sc, sc.routes[0])
    assert rule.model_cost == 0 and rule.categories["tool_api"] == D("0.001")
