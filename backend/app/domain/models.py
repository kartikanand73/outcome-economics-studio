"""Domain schema for Outcome Economics Studio.

Design rules
------------
* All money and token quantities are ``Decimal``. Floats never enter the
  calculation engine for monetary values.
* ``None`` in a limit field means **not configured**. Whether a missing limit
  makes the workflow unbounded depends on whether that feature is reachable
  (see ``app.validation.bounds``).
* Every input model carries an ``evidence`` map (field name -> label). Fields
  that are not listed default to ``assumption`` - the tool never presents an
  unlabelled input as measured.
* Route ``share_pct`` values are *exclusive* and must total 100 %. Human
  review is a *conditional* rate applied inside each route and is never added
  to the route total.
"""
from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class Evidence(str, Enum):
    ASSUMPTION = "assumption"
    MEASURED = "measured"
    PROVIDER = "provider_reported"
    DERIVED = "derived"


class Tier(str, Enum):
    LIGHTWEIGHT = "lightweight"
    LARGER = "larger"


class Enforcement(str, Enum):
    NONE = "none"
    WARN = "warn"
    DEGRADE = "degrade"
    REJECT = "reject"


class BoundsMode(str, Enum):
    DEFAULT = "default"  # worst case = this model's average token usage, priced without cache credit
    CUSTOM = "custom"    # worst case from the configured context and call limits


class CheckTiming(str, Enum):
    PRE_CALL = "pre_call"    # blocks the next call if its worst case would exceed the remaining budget
    POST_CALL = "post_call"  # checks spend only after each call completes


D0 = Decimal("0")


class Labeled(BaseModel):
    """Base for input sections: carries per-field evidence labels."""

    model_config = ConfigDict(extra="ignore", validate_assignment=True)

    evidence: dict[str, Evidence] = Field(default_factory=dict)

    def ev(self, field: str) -> Evidence:
        return self.evidence.get(field, Evidence.ASSUMPTION)


# ---------------------------------------------------------------- workload
class Workload(Labeled):
    tasks_per_day: Decimal = Decimal("1000")
    operating_days_per_month: Decimal = Decimal("30")
    annual_growth_pct: Decimal = D0
    peak_tasks_per_minute: Optional[Decimal] = None
    target_accuracy_pct: Decimal = Decimal("98")
    max_latency_ms: Optional[Decimal] = Decimal("2000")
    currency: str = "USD"


# ---------------------------------------------------------------- models
class ContextBounds(Labeled):
    """Per-model context composition. Max values drive the bounded maximum."""

    system_prompt_tokens: Decimal = D0
    avg_user_input_tokens: Decimal = D0
    max_user_input_tokens: Optional[Decimal] = None  # falls back to average (flagged)
    history_enabled: bool = False
    max_history_tokens: Optional[Decimal] = None
    retrieval_enabled: bool = False
    max_retrieved_tokens: Optional[Decimal] = None
    tool_schema_tokens: Decimal = D0
    tool_schema_count: int = 0
    few_shot_tokens: Decimal = D0
    max_output_tokens: Optional[Decimal] = None
    max_reasoning_tokens: Optional[Decimal] = None


class CallLimits(Labeled):
    agent_loop_enabled: bool = False
    max_agent_iterations: Optional[int] = None
    max_model_calls: Optional[int] = None  # per task, for this model's stage
    max_retries: Optional[int] = None      # per call


class ModelConfig(Labeled):
    id: str
    provider: str = ""
    name: str
    tier: Tier = Tier.LIGHTWEIGHT
    # pricing (per million tokens)
    input_price_per_m: Decimal = D0
    output_price_per_m: Decimal = D0
    cached_input_price_per_m: Optional[Decimal] = None
    reasoning_price_per_m: Optional[Decimal] = None  # None -> output price
    separately_metered_reasoning: bool = False
    # expected usage per call
    avg_input_tokens: Decimal = D0
    avg_output_tokens: Decimal = D0
    avg_reasoning_tokens: Decimal = D0
    cached_input_share_pct: Decimal = D0  # % of input tokens billed at cached price
    avg_calls_per_task: Decimal = Decimal("1")
    retry_rate_pct: Decimal = D0  # expected retries per call, as %
    retries_enabled: bool = False
    # latency
    p50_latency_ms: Decimal = D0
    p95_latency_ms: Decimal = D0
    # bounds
    bounds_mode: BoundsMode = BoundsMode.CUSTOM
    context: ContextBounds = Field(default_factory=ContextBounds)
    limits: CallLimits = Field(default_factory=CallLimits)
    # link to the shared model catalog (prices are copied, not referenced, so saved scenarios stay reproducible)
    catalog_id: Optional[str] = None
    catalog_as_of: Optional[str] = None

    @property
    def effective_reasoning_price(self) -> Decimal:
        return self.reasoning_price_per_m if self.reasoning_price_per_m is not None else self.output_price_per_m

    @property
    def effective_cached_price(self) -> Decimal:
        return self.cached_input_price_per_m if self.cached_input_price_per_m is not None else self.input_price_per_m


# ---------------------------------------------------------------- shared model catalog
class PriceChange(BaseModel):
    changed_at: str
    as_of: Optional[str] = None
    input_price_per_m: Decimal
    output_price_per_m: Decimal
    cached_input_price_per_m: Optional[Decimal] = None
    reasoning_price_per_m: Optional[Decimal] = None
    note: str = ""


class CatalogModel(BaseModel):
    """One entry in the shared, editable model price catalog (not part of any scenario)."""

    model_config = ConfigDict(extra="ignore")

    id: str = ""
    provider: str
    name: str
    tier: Tier = Tier.LIGHTWEIGHT
    input_price_per_m: Decimal
    output_price_per_m: Decimal
    cached_input_price_per_m: Optional[Decimal] = None
    reasoning_price_per_m: Optional[Decimal] = None
    separately_metered_reasoning: bool = False
    context_window: Optional[int] = None
    source_url: str = ""
    as_of: str = ""
    evidence: Evidence = Evidence.PROVIDER
    notes: str = ""
    is_seed: bool = False        # shipped with the app (published price); False = added by you
    edited: bool = False         # a seed entry whose prices you changed
    updated_at: str = ""
    history: list[PriceChange] = Field(default_factory=list)

    def price_tuple(self):
        return (self.input_price_per_m, self.output_price_per_m, self.cached_input_price_per_m,
                self.reasoning_price_per_m)


# ---------------------------------------------------------------- routes
class Stage(Labeled):
    """One model step inside a route. Bounds come from the referenced model."""

    model_id: str
    avg_calls_override: Optional[Decimal] = None
    tools_exposed: bool = False
    avg_tool_calls: Decimal = D0
    max_tool_calls: Optional[int] = None
    subagents_enabled: bool = False
    avg_subagents: Decimal = D0
    max_subagents: Optional[int] = None
    subagent_model_id: Optional[str] = None  # None -> same model as the stage


class Safety(Labeled):
    """Route-level safety rates (% of tasks on the route). None = not measured."""

    fraud_auto_approval_pct: Optional[Decimal] = None
    critical_false_approval_pct: Optional[Decimal] = None
    incorrect_auto_rejection_pct: Optional[Decimal] = None
    unnecessary_review_pct: Optional[Decimal] = None  # % of *reviewed* tasks that did not need review
    policy_override_pct: Optional[Decimal] = None     # % of *reviewed* tasks where the reviewer overrode the automated outcome


class Route(Labeled):
    id: str
    name: str
    share_pct: Decimal  # exclusive; all routes must total 100
    description: str = ""
    deterministic_rule: bool = False
    rule_latency_ms: Decimal = Decimal("5")
    rule_tool_calls: Decimal = D0  # tool/API calls made outside model stages
    max_rule_tool_calls: Optional[int] = None
    stages: list[Stage] = Field(default_factory=list)
    direct_human: bool = False  # human decides; no automated decision
    human_review_pct: Decimal = D0  # conditional: % of this route's tasks reviewed
    human_review_mandatory: bool = False  # review happens regardless of model output
    review_minutes_override: Optional[Decimal] = None
    expected_outcome: str = ""
    accuracy_pct: Decimal = Decimal("100")
    p50_latency_ms: Optional[Decimal] = None  # None -> derived from stages
    p95_latency_ms: Optional[Decimal] = None
    model_eligible: Optional[bool] = None  # None -> derived (not deterministic-only, not direct human)
    larger_changed_outcome_pct: Optional[Decimal] = None  # % of larger-model calls that changed the governed outcome
    safety: Safety = Field(default_factory=Safety)


# ---------------------------------------------------------------- costs
class OperatingCosts(Labeled):
    review_minutes_avg: Decimal = Decimal("3")
    review_minutes_max: Optional[Decimal] = None
    reviewer_hourly_cost: Decimal = Decimal("60")
    tool_cost_per_call: Decimal = D0
    fixed_infra_monthly: Decimal = D0
    observability_monthly: Decimal = D0
    other_fixed_monthly: Decimal = D0
    eval_sampling_pct: Decimal = D0
    eval_cost_per_sample: Decimal = D0
    other_variable_per_task: Decimal = D0


class BudgetPolicy(Labeled):
    max_monetary_budget_per_task: Optional[Decimal] = None
    max_token_budget_per_task: Optional[Decimal] = None
    enforcement: Enforcement = Enforcement.NONE
    check_timing: CheckTiming = CheckTiming.POST_CALL
    degrade_fallback_cost: Optional[Decimal] = None
    max_execution_time_s: Optional[Decimal] = None


class DecisionInputs(Labeled):
    baseline_review_pct: Optional[Decimal] = None  # review rate the process would have without this architecture


# ---------------------------------------------------------------- measured benchmark
class MeasuredValue(BaseModel):
    value: Optional[Decimal] = None
    unit: str = ""
    evidence: Evidence = Evidence.MEASURED
    note: str = ""


class Segment(BaseModel):
    name: str
    decisions: Optional[int] = None
    accuracy_pct: Optional[Decimal] = None
    evidence: Evidence = Evidence.MEASURED


class MeasuredBenchmark(BaseModel):
    """Imported benchmark result. Immutable once imported - projections never write here."""

    model_config = ConfigDict(frozen=True)

    name: str
    source: str = ""
    run_date: str = ""
    is_sample: bool = False
    decisions: Optional[int] = None
    metrics: dict[str, MeasuredValue] = Field(default_factory=dict)
    segments: list[Segment] = Field(default_factory=list)


# ---------------------------------------------------------------- building blocks (wizard step 1)
class Features(BaseModel):
    """What the workflow uses. Unticked blocks are ignored by the engine without deleting their values."""

    model_config = ConfigDict(extra="ignore")

    rules: bool = False
    lightweight: bool = False
    lightweight_model_id: Optional[str] = None
    larger: bool = False
    larger_model_id: Optional[str] = None
    human_review: bool = False
    tools: bool = False
    advanced_limits: bool = False
    budget: bool = False
    infra_costs: bool = True
    completed: bool = False  # wizard walked through once: every step can be opened directly


# ---------------------------------------------------------------- scenario
class Scenario(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: Optional[str] = None
    name: str
    business_process: str = ""
    description: str = ""
    is_sample: bool = False
    sample_note: str = ""
    workload: Workload = Field(default_factory=Workload)
    models: list[ModelConfig] = Field(default_factory=list)
    routes: list[Route] = Field(default_factory=list)
    costs: OperatingCosts = Field(default_factory=OperatingCosts)
    budget: BudgetPolicy = Field(default_factory=BudgetPolicy)
    decision: DecisionInputs = Field(default_factory=DecisionInputs)
    benchmark: Optional[MeasuredBenchmark] = None
    features: Optional[Features] = None  # None = older scenario; everything it configures applies

    def model_by_id(self, model_id: str) -> ModelConfig:
        for m in self.models:
            if m.id == model_id:
                return m
        raise KeyError(f"Unknown model id '{model_id}'")
