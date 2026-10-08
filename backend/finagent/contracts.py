"""Frozen public contracts. All synthetic values must carry Mode.DEMO.

Use model_dump(mode="json") for persistence/API boundaries and model_validate
on read. Financial calculations live in quant/backtest, never in this module.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Ticker = Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9.\-]{0,14}$")]
Period = Annotated[str, Field(pattern=r"^20\d{2}-H[12]$")]
Positive = Annotated[float, Field(gt=0, allow_inf_nan=False)]
NonNegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class Mode(str, Enum):
    DEMO = "DEMO"
    REAL = "REAL"


class PITStatus(str, Enum):
    VERIFIED = "PIT_VERIFIED"
    UNVERIFIED = "PIT_UNVERIFIED"
    MISSING = "MISSING"


class ResearchMode(str, Enum):
    QUANT_ONLY = "quant_only"
    SINGLE_AGENT = "single_agent_skills"
    MULTI_PERSONA = "multi_persona"
    MULTI_PERSONA_DEBATE = "multi_persona_debate"


class Persona(str, Enum):
    VALUE = "Value"
    GROWTH = "Growth"
    CONSERVATIVE = "Conservative"


class RunStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    INSUFFICIENT = "INSUFFICIENT_ELIGIBLE_STOCKS"
    UNAVAILABLE = "UNAVAILABLE"
    FAILED = "FAILED"


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    RETRY = "RETRY"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class BacktestStatus(str, Enum):
    COMPLETED = "COMPLETED"
    PENDING = "PENDING"
    UNAVAILABLE = "UNAVAILABLE"
    VALIDATION_FAILED = "VALIDATION_FAILED"


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)

    @field_validator("*", mode="after")
    @classmethod
    def reject_naive_datetimes(cls, value: Any) -> Any:
        if isinstance(value, datetime) and (
            value.tzinfo is None or value.utcoffset() is None
        ):
            raise ValueError("timestamp must include a UTC offset")
        return value


class VersionBundle(FrozenModel):
    strategy: str = "semiannual-v1"
    graph: str = "personas-v1"
    prompt: str = "evidence-only-v1"
    model: str = "deterministic-demo-v1"
    assumptions: str = "valuation-v1"


class SourceRecord(FrozenModel):
    ticker: Ticker
    as_of: datetime
    available_at: datetime
    source: str = Field(min_length=1)
    source_uri: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)
    corporate_action_basis: str = "RAW_WITH_ACTIONS"
    pit_status: PITStatus
    mode: Mode
    currency: str = "USD"

    @model_validator(mode="after")
    def chronology(self) -> SourceRecord:
        if self.available_at < self.as_of:
            raise ValueError("available_at cannot precede observation as_of")
        return self


class MarketBar(SourceRecord):
    session: date
    open: Positive
    high: Positive
    low: Positive
    close: Positive
    volume: NonNegative = 0

    @model_validator(mode="after")
    def valid_ohlc(self) -> MarketBar:
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("OHLC range is inconsistent")
        if self.low > self.high:
            raise ValueError("low exceeds high")
        return self


class CorporateAction(FrozenModel):
    ticker: Ticker
    session: date
    kind: Literal["SPLIT", "DIVIDEND"]
    value: Positive
    source: str
    source_uri: str
    available_at: datetime
    currency: str = "USD"


class FinancialSnapshot(SourceRecord):
    period_end: date
    revenue: NonNegative | None = None
    revenue_growth: float | None = Field(default=None, allow_inf_nan=False)
    earnings_per_share: float | None = Field(default=None, allow_inf_nan=False)
    free_cash_flow: float | None = Field(default=None, allow_inf_nan=False)
    shares_outstanding: Positive | None = None
    profit_margin: float | None = Field(default=None, allow_inf_nan=False)
    eps_revision: float | None = Field(default=None, allow_inf_nan=False)
    debt_to_equity: NonNegative | None = None


class EvidenceItem(FrozenModel):
    evidence_id: str
    field: str
    value: str | float
    source_uri: str
    available_at: datetime
    content_hash: str
    pit_status: PITStatus
    kind: Literal["FACT", "ASSUMPTION"] = "FACT"


class EvidenceSnapshot(FrozenModel):
    snapshot_id: str
    ticker: Ticker
    decision_at: datetime
    mode: Mode
    items: tuple[EvidenceItem, ...]
    content_hash: str
    pit_status: PITStatus
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def admissible(self) -> EvidenceSnapshot:
        ids = [item.evidence_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate evidence id")
        if any(item.available_at > self.decision_at for item in self.items):
            raise ValueError("evidence was unavailable at decision_at")
        if self.pit_status == PITStatus.VERIFIED and any(
            item.pit_status != PITStatus.VERIFIED for item in self.items
        ):
            raise ValueError("verified snapshot contains unverified evidence")
        return self


class UniverseMember(FrozenModel):
    ticker: Ticker
    sector: str


class UniverseSnapshot(FrozenModel):
    period: Period
    as_of: datetime
    available_at: datetime
    members: tuple[UniverseMember, ...]
    source: str
    source_uri: str
    content_hash: str
    mode: Mode
    pit_status: PITStatus
    survivorship_warning: str | None = None

    @model_validator(mode="after")
    def distinct_tickers(self) -> UniverseSnapshot:
        tickers = [member.ticker for member in self.members]
        if len(tickers) != len(set(tickers)):
            raise ValueError("duplicate universe ticker")
        return self


class ResearchInput(FrozenModel):
    ticker: Ticker
    sector: str
    decision_at: datetime
    mode: Mode
    market: tuple[MarketBar, ...]
    financials: FinancialSnapshot
    evidence: EvidenceSnapshot
    versions: VersionBundle = Field(default_factory=VersionBundle)

    @model_validator(mode="after")
    def admissible(self) -> ResearchInput:
        records = (*self.market, self.financials)
        if not self.market:
            raise ValueError("research requires market observations")
        if any(record.ticker != self.ticker or record.mode != self.mode for record in records):
            raise ValueError("research input ticker/mode mismatch")
        if any(record.available_at > self.decision_at for record in records):
            raise ValueError("future observation in research input")
        if self.evidence.ticker != self.ticker or self.evidence.mode != self.mode:
            raise ValueError("evidence ticker/mode mismatch")
        if self.evidence.decision_at != self.decision_at:
            raise ValueError("evidence decision cutoff mismatch")
        return self


class Assumption(FrozenModel):
    name: str
    value: float = Field(allow_inf_nan=False)
    unit: str
    rationale: str
    evidence_ids: tuple[str, ...] = ()
    kind: Literal["ASSUMPTION"] = "ASSUMPTION"


class PersonaReport(FrozenModel):
    persona: Persona
    ticker: Ticker
    snapshot_id: str
    horizon_months: Literal[12] = 12
    currency: str = "USD"
    corporate_action_basis: str = "RAW_WITH_ACTIONS"
    assumptions: tuple[Assumption, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    risk_flags: tuple[str, ...] = ()
    target_price_candidate: Positive | None = None
    abstain_reason: str | None = None
    rationale: str
    model_version: str
    prompt_version: str

    @model_validator(mode="after")
    def forecast_or_abstention(self) -> PersonaReport:
        if self.target_price_candidate is None and not self.abstain_reason:
            raise ValueError("persona requires a grounded target or abstain_reason")
        if self.target_price_candidate is not None and self.abstain_reason:
            raise ValueError("abstaining persona cannot supply target")
        return self


class MethodValuation(FrozenModel):
    method: str
    value: Positive
    assumptions: tuple[Assumption, ...] = ()
    evidence_ids: tuple[str, ...] = ()


class ValuationResult(FrozenModel):
    ticker: Ticker
    snapshot_id: str
    mode: Mode
    pit_status: PITStatus
    currency: str = "USD"
    corporate_action_basis: str = "RAW_WITH_ACTIONS"
    horizon_months: Literal[12] = 12
    fair_value: Positive | None = None
    target_12m: Positive | None = None
    entry_price: Positive | None = None
    safety_margin: float = Field(default=0.2, ge=0, lt=1)
    methods: tuple[MethodValuation, ...] = ()
    explanations: tuple[str, ...] = ()
    abstain_reason: str | None = None
    assumptions_version: str = "valuation-v1"

    @model_validator(mode="after")
    def valuation_consistency(self) -> ValuationResult:
        if self.target_12m is None:
            if not self.abstain_reason or self.entry_price is not None:
                raise ValueError("missing target requires abstention and no entry price")
        else:
            if self.abstain_reason or self.entry_price is None:
                raise ValueError("valued target requires entry price and no abstention")
            expected = self.target_12m * (1 - self.safety_margin)
            if not math.isclose(self.entry_price, expected, abs_tol=0.011):
                raise ValueError("entry price does not match target and safety margin")
        return self


class FactorScore(FrozenModel):
    name: str
    value: float | None = Field(default=None, allow_inf_nan=False)
    missing_reason: str | None = None


class ScreenedCandidate(FrozenModel):
    ticker: Ticker
    sector: str
    score: float = Field(allow_inf_nan=False)
    factors: tuple[FactorScore, ...] = ()
    warnings: tuple[str, ...] = ()


class ResearchResult(FrozenModel):
    ticker: Ticker
    sector: str
    mode: Mode
    snapshot: EvidenceSnapshot
    reports: tuple[PersonaReport, ...]
    valuation: ValuationResult
    score: float = Field(allow_inf_nan=False)
    factors: tuple[FactorScore, ...] = ()
    eligible: bool = True
    exclusion_reasons: tuple[str, ...] = ()
    research_mode: ResearchMode = ResearchMode.MULTI_PERSONA
    review_rounds: int = Field(default=0, ge=0, le=1)
    versions: VersionBundle = Field(default_factory=VersionBundle)

    @model_validator(mode="after")
    def linked_evidence(self) -> ResearchResult:
        ids = {item.evidence_id for item in self.snapshot.items}
        personas = [report.persona for report in self.reports]
        if len(personas) != len(set(personas)):
            raise ValueError("duplicate persona report")
        if self.snapshot.ticker != self.ticker or self.snapshot.mode != self.mode:
            raise ValueError("result snapshot mismatch")
        if self.valuation.ticker != self.ticker or self.valuation.snapshot_id != self.snapshot.snapshot_id:
            raise ValueError("valuation snapshot mismatch")
        for report in self.reports:
            if report.ticker != self.ticker or report.snapshot_id != self.snapshot.snapshot_id:
                raise ValueError("persona snapshot mismatch")
            if not set(report.evidence_ids) <= ids:
                raise ValueError("persona refers to nonexistent evidence")
        if self.eligible and self.valuation.target_12m is None:
            raise ValueError("abstained valuation cannot be eligible")
        return self


class RankedPick(FrozenModel):
    rank: int = Field(ge=1, le=10)
    ticker: Ticker
    sector: str
    weight: float = Field(gt=0, le=1)
    score: float = Field(allow_inf_nan=False)
    target_12m: Positive
    entry_price: Positive
    snapshot_id: str
    snapshot_hash: str
    rationale: str


class FrozenSignal(FrozenModel):
    signal_id: str
    run_id: str
    period: Period
    decision_at: datetime
    frozen_at: datetime
    mode: Mode
    pit_status: PITStatus
    picks: tuple[RankedPick, ...]
    versions: VersionBundle = Field(default_factory=VersionBundle)
    config_hash: str
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def exact_top_ten(self) -> FrozenSignal:
        if len(self.picks) != 10:
            raise ValueError("frozen signal requires exactly ten; surface shortfall separately")
        if len({pick.ticker for pick in self.picks}) != 10:
            raise ValueError("duplicate frozen ticker")
        if sorted(pick.rank for pick in self.picks) != list(range(1, 11)):
            raise ValueError("ranks must be 1 through 10")
        if any(not math.isclose(pick.weight, 0.1, abs_tol=1e-9) for pick in self.picks):
            raise ValueError("primary signal must be equal weighted")
        if self.frozen_at < self.decision_at:
            raise ValueError("freeze precedes decision")
        if self.mode == Mode.REAL and self.pit_status != PITStatus.VERIFIED:
            raise ValueError("real frozen signals require verified PIT evidence")
        return self


class BenchmarkList(FrozenModel):
    period: Period
    tickers: tuple[Ticker, ...]
    published_at: datetime
    source_uri: str = Field(min_length=1)
    content_hash: str
    verification_status: PITStatus
    mode: Mode = Mode.REAL
    verification_note: str

    @model_validator(mode="after")
    def ten_unique(self) -> BenchmarkList:
        if len(self.tickers) != 10 or len(set(self.tickers)) != 10:
            raise ValueError("benchmark requires exactly ten distinct canonical tickers")
        if not self.source_uri.startswith(("https://", "http://")):
            raise ValueError("benchmark original source must be an HTTP(S) URL")
        return self


class RunRequest(FrozenModel):
    period: Period = "2025-H2"
    mode: Mode = Mode.DEMO
    research_mode: ResearchMode = ResearchMode.MULTI_PERSONA
    decision_at: datetime | None = None
    safety_margin: float = Field(default=0.2, ge=0, lt=1)
    max_candidates: int = Field(default=30, ge=10, le=30)
    max_per_sector: int = Field(default=4, ge=1, le=10)
    idempotency_key: str | None = Field(default=None, max_length=128)


class BacktestRequest(FrozenModel):
    run_id: str
    as_of: datetime | None = None
    transaction_cost_bps: float = Field(default=0, ge=0, le=1000)
    slippage_bps: float = Field(default=0, ge=0, le=1000)
    policy: Literal["PRIMARY", "LIMIT_ENTRY"] = "PRIMARY"
    idempotency_key: str | None = Field(default=None, max_length=128)


class HoldingReturn(FrozenModel):
    ticker: Ticker
    entry_price: Positive
    exit_price: Positive
    dividends: NonNegative = 0
    split_factor: Positive = 1
    total_return: float = Field(allow_inf_nan=False)
    weight: float = Field(gt=0, le=1)
    filled: bool = True


class PortfolioReturn(FrozenModel):
    name: str
    total_return: float = Field(allow_inf_nan=False)
    holdings: tuple[HoldingReturn, ...]
    entry_session: date
    exit_session: date
    corporate_action_basis: str = "RAW_WITH_ACTIONS"


class BacktestResult(FrozenModel):
    backtest_id: str
    signal_id: str
    period: Period
    mode: Mode
    status: BacktestStatus
    policy: Literal["PRIMARY", "LIMIT_ENTRY"] = "PRIMARY"
    entry_session: date | None = None
    exit_session: date | None = None
    finagent: PortfolioReturn | None = None
    spy: PortfolioReturn | None = None
    seeking_alpha: PortfolioReturn | None = None
    seeking_alpha_status: Literal["AVAILABLE", "UNAVAILABLE", "UNVERIFIED"] = "UNAVAILABLE"
    excess_vs_spy_pp: float | None = Field(default=None, allow_inf_nan=False)
    excess_vs_sa_pp: float | None = Field(default=None, allow_inf_nan=False)
    warnings: tuple[str, ...] = ()
    reason: str | None = None
    transaction_cost_bps: float = 0
    slippage_bps: float = 0
    cash_weight: float = Field(default=0, ge=0, le=1)
    snapshot_hash: str | None = None

    @model_validator(mode="after")
    def fair_comparison(self) -> BacktestResult:
        portfolios = [p for p in (self.finagent, self.spy, self.seeking_alpha) if p is not None]
        if self.status == BacktestStatus.COMPLETED:
            if self.finagent is None or self.spy is None:
                raise ValueError("completed backtest requires FinAgent and SPY")
            if self.entry_session is None or self.exit_session is None:
                raise ValueError("completed backtest requires actual common sessions")
        elif portfolios or self.excess_vs_sa_pp is not None or self.excess_vs_spy_pp is not None:
            raise ValueError("unavailable/pending backtest cannot contain realized results")
        for portfolio in portfolios:
            if (portfolio.entry_session, portfolio.exit_session) != (self.entry_session, self.exit_session):
                raise ValueError("benchmark intervals differ")
        if self.seeking_alpha is None and self.excess_vs_sa_pp is not None:
            raise ValueError("cannot invent missing Seeking Alpha comparison")
        if self.seeking_alpha is not None and self.seeking_alpha_status != "AVAILABLE":
            raise ValueError("Seeking Alpha result requires AVAILABLE verification")
        return self


def stable_hash(value: Any) -> str:
    """Deterministic digest for configuration, evidence, and dedupe identities."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False)
    return hashlib.sha256(payload.encode()).hexdigest()
