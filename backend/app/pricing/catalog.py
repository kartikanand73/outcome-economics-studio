"""Model price sources.

The MVP ships a manual catalog. ``PriceProvider`` is the seam for future live
provider lookups: an implementation returns ``PriceQuote`` objects labelled
``provider_reported`` with a retrieval timestamp, and the UI can apply a quote
to a scenario's model without the engine knowing where the price came from.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal

from app.domain.models import (CallLimits, ContextBounds, Evidence, ModelConfig, Tier)


@dataclass(frozen=True)
class PriceQuote:
    provider: str
    model: str
    input_price_per_m: Decimal
    output_price_per_m: Decimal
    cached_input_price_per_m: Decimal | None
    reasoning_price_per_m: Decimal | None
    evidence: Evidence
    source: str
    retrieved_at: str | None = None


class PriceProvider(ABC):
    name: str

    @abstractmethod
    def list_models(self) -> list[ModelConfig]: ...

    @abstractmethod
    def quote(self, model_id: str) -> PriceQuote | None: ...


def sample_models() -> list[ModelConfig]:
    """Editable sample models. All prices and usage are illustrative user assumptions."""
    return [
        ModelConfig(
            id="jev-1-13", provider="Jev (sample)", name="Jev 1.13", tier=Tier.LIGHTWEIGHT,
            input_price_per_m=Decimal("0.05"), output_price_per_m=Decimal("0.20"),
            avg_input_tokens=Decimal("650"), avg_output_tokens=Decimal("35"),
            avg_calls_per_task=Decimal("1"), retry_rate_pct=Decimal("0.5"), retries_enabled=True,
            p50_latency_ms=Decimal("180"), p95_latency_ms=Decimal("420"),
            context=ContextBounds(system_prompt_tokens=Decimal("300"), avg_user_input_tokens=Decimal("350"),
                                  max_user_input_tokens=Decimal("500"), max_output_tokens=Decimal("64")),
            limits=CallLimits(max_model_calls=1, max_retries=1),
            catalog_id="custom-jev-1-13", catalog_as_of="2026-09-28",
        ),
        ModelConfig(
            id="gpt-6-sol", provider="OpenAI (sample pricing)", name="GPT-6 Sol", tier=Tier.LARGER,
            input_price_per_m=Decimal("1.25"), output_price_per_m=Decimal("10.00"),
            cached_input_price_per_m=Decimal("0.125"), separately_metered_reasoning=True,
            avg_input_tokens=Decimal("1000"), avg_output_tokens=Decimal("44"), avg_reasoning_tokens=Decimal("60"),
            avg_calls_per_task=Decimal("1"), retry_rate_pct=Decimal("1"), retries_enabled=True,
            p50_latency_ms=Decimal("2570"), p95_latency_ms=Decimal("5200"),
            context=ContextBounds(system_prompt_tokens=Decimal("450"), avg_user_input_tokens=Decimal("350"),
                                  max_user_input_tokens=Decimal("500"), retrieval_enabled=True,
                                  max_retrieved_tokens=Decimal("1200"), max_output_tokens=Decimal("256"),
                                  max_reasoning_tokens=Decimal("1024")),
            limits=CallLimits(max_model_calls=1, max_retries=2),
        ),
        ModelConfig(
            id="generic-light", provider="Generic", name="Generic lightweight model", tier=Tier.LIGHTWEIGHT,
            input_price_per_m=Decimal("0.15"), output_price_per_m=Decimal("0.60"),
            cached_input_price_per_m=Decimal("0.075"), cached_input_share_pct=Decimal("40"),
            avg_input_tokens=Decimal("900"), avg_output_tokens=Decimal("80"),
            avg_calls_per_task=Decimal("1"), retry_rate_pct=Decimal("1"), retries_enabled=True,
            p50_latency_ms=Decimal("350"), p95_latency_ms=Decimal("900"),
            context=ContextBounds(system_prompt_tokens=Decimal("500"), avg_user_input_tokens=Decimal("400"),
                                  max_user_input_tokens=Decimal("800"), max_output_tokens=Decimal("256")),
            limits=CallLimits(max_model_calls=1, max_retries=2),
        ),
        ModelConfig(
            id="generic-frontier", provider="Generic", name="Generic frontier model", tier=Tier.LARGER,
            input_price_per_m=Decimal("3.00"), output_price_per_m=Decimal("15.00"),
            cached_input_price_per_m=Decimal("0.30"), cached_input_share_pct=Decimal("30"),
            separately_metered_reasoning=True,
            avg_input_tokens=Decimal("2500"), avg_output_tokens=Decimal("200"), avg_reasoning_tokens=Decimal("400"),
            avg_calls_per_task=Decimal("1"), retry_rate_pct=Decimal("2"), retries_enabled=True,
            p50_latency_ms=Decimal("3500"), p95_latency_ms=Decimal("9000"),
            context=ContextBounds(system_prompt_tokens=Decimal("1200"), avg_user_input_tokens=Decimal("400"),
                                  max_user_input_tokens=Decimal("800"), retrieval_enabled=True,
                                  max_retrieved_tokens=Decimal("4000"), tool_schema_tokens=Decimal("900"),
                                  tool_schema_count=6, max_output_tokens=Decimal("1024"),
                                  max_reasoning_tokens=Decimal("4096")),
            limits=CallLimits(max_model_calls=2, max_retries=2),
        ),
    ]


class ManualPriceProvider(PriceProvider):
    """Prices entered by hand (the MVP default). Values are user assumptions."""

    name = "manual"

    def list_models(self) -> list[ModelConfig]:
        return sample_models()

    def quote(self, model_id: str) -> PriceQuote | None:
        for m in sample_models():
            if m.id == model_id:
                return PriceQuote(m.provider, m.name, m.input_price_per_m, m.output_price_per_m,
                                  m.cached_input_price_per_m, m.reasoning_price_per_m,
                                  Evidence.ASSUMPTION, "Manual sample catalog")
        return None


PROVIDERS: dict[str, PriceProvider] = {"manual": ManualPriceProvider()}
