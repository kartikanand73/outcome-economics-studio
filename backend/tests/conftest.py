from decimal import Decimal as D

import pytest

from app.domain.models import (CallLimits, ContextBounds, ModelConfig, OperatingCosts, Route, Scenario, Stage,
                               Tier, Workload)


def make_model(id="m", tier=Tier.LIGHTWEIGHT, **kw) -> ModelConfig:
    base = dict(
        id=id, name=id.upper(), tier=tier,
        input_price_per_m=D("1"), output_price_per_m=D("4"),
        avg_input_tokens=D("1000"), avg_output_tokens=D("100"),
        p50_latency_ms=D("100"), p95_latency_ms=D("200"),
        context=ContextBounds(system_prompt_tokens=D("500"), avg_user_input_tokens=D("500"),
                              max_user_input_tokens=D("500"), max_output_tokens=D("200")),
        limits=CallLimits(max_model_calls=1),
    )
    base.update(kw)
    return ModelConfig(**base)


def make_scenario(routes, models=None, **kw) -> Scenario:
    return Scenario(
        name=kw.pop("name", "test"),
        workload=kw.pop("workload", Workload(tasks_per_day=D(1000), operating_days_per_month=D(30))),
        models=models if models is not None else [make_model("light"), make_model("big", Tier.LARGER,
                                                                                    input_price_per_m=D("10"),
                                                                                    output_price_per_m=D("40"))],
        routes=routes,
        costs=kw.pop("costs", OperatingCosts(review_minutes_avg=D(3), reviewer_hourly_cost=D(60))),
        **kw,
    )


def route(id, share, stages=(), **kw) -> Route:
    return Route(id=id, name=id, share_pct=D(share), stages=[Stage(model_id=s) if isinstance(s, str) else s
                                                             for s in stages], **kw)


@pytest.fixture
def two_route_scenario():
    return make_scenario([route("light", 60, ["light"]), route("cascade", 40, ["light", "big"])])
