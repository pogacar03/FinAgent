from datetime import date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from finagent.contracts import (
    BacktestResult, BacktestStatus, BenchmarkList, EvidenceItem, EvidenceSnapshot,
    FrozenSignal, MarketBar, Mode, Persona, PersonaReport, PITStatus,
    PortfolioReturn, RankedPick, RunRequest, ValuationResult, stable_hash,
)

NOW = datetime(2025, 7, 1, 20, tzinfo=timezone.utc)


def evidence(**changes):
    return EvidenceItem(
        evidence_id="e1", field="eps", value=5.0, source_uri="synthetic://eps",
        available_at=changes.pop("available_at", NOW), content_hash="digest",
        pit_status=changes.pop("pit_status", PITStatus.VERIFIED), **changes,
    )


def snapshot(**changes):
    defaults = dict(snapshot_id="s1", ticker="NVDA", decision_at=NOW, mode=Mode.DEMO,
                    items=(evidence(),), content_hash="digest", pit_status=PITStatus.VERIFIED)
    return EvidenceSnapshot(**(defaults | changes))


def signal(**changes):
    picks = tuple(RankedPick(rank=i+1, ticker=f"S{i}", sector="Technology", weight=.1,
                            score=10-i, target_12m=199, entry_price=159.2,
                            snapshot_id=f"snap-{i}", snapshot_hash=f"hash-{i}",
                            rationale="SYNTHETIC test") for i in range(10))
    defaults = dict(signal_id="sig", run_id="run", period="2025-H2", decision_at=NOW,
                    frozen_at=NOW, mode=Mode.DEMO, pit_status=PITStatus.VERIFIED,
                    picks=picks, config_hash="hash")
    return FrozenSignal(**(defaults | changes))


def portfolio(name="FinAgent", **changes):
    defaults = dict(name=name, total_return=.1, holdings=(),
                    entry_session=date(2025, 7, 2), exit_session=date(2026, 1, 2))
    return PortfolioReturn(**(defaults | changes))


def test_snapshot_is_deeply_frozen_and_json_roundtrips():
    snap = snapshot()
    with pytest.raises(ValidationError):
        snap.ticker = "MSFT"
    with pytest.raises(ValidationError):
        snap.items[0].value = 100
    assert EvidenceSnapshot.model_validate_json(snap.model_dump_json()) == snap


def test_future_evidence_is_rejected():
    with pytest.raises(ValidationError, match="unavailable"):
        snapshot(items=(evidence(available_at=NOW + timedelta(seconds=1)),))


def test_verified_label_cannot_hide_unverified_evidence():
    with pytest.raises(ValidationError, match="unverified"):
        snapshot(items=(evidence(pit_status=PITStatus.UNVERIFIED),))


def test_duplicate_evidence_is_rejected():
    with pytest.raises(ValidationError, match="duplicate"):
        snapshot(items=(evidence(), evidence()))


def test_naive_decision_and_extra_request_fields_are_rejected():
    with pytest.raises(ValidationError, match="UTC offset"):
        RunRequest(decision_at=datetime(2025, 7, 1))
    with pytest.raises(ValidationError, match="Extra inputs"):
        RunRequest(brokerage_account="not supported")


def test_frozen_signal_has_ten_unique_equal_weighted_positions():
    frozen = signal()
    assert len(frozen.picks) == 10
    assert sum(p.weight for p in frozen.picks) == pytest.approx(1)
    for invalid in (
        {"picks": frozen.picks[:9]},
        {"picks": frozen.picks[:-1] + (frozen.picks[0],)},
        {"picks": (frozen.picks[0].model_copy(update={"weight": .2}),) + frozen.picks[1:]},
    ):
        with pytest.raises(ValidationError):
            signal(**invalid)


def test_real_signal_cannot_be_pit_unverified():
    with pytest.raises(ValidationError, match="verified PIT"):
        signal(mode=Mode.REAL, pit_status=PITStatus.UNVERIFIED)


def test_forecast_needs_explicit_abstention_or_grounded_target():
    params = dict(persona=Persona.VALUE, ticker="NVDA", snapshot_id="s1",
                  rationale="SYNTHETIC fixture", model_version="demo", prompt_version="v1")
    with pytest.raises(ValidationError, match="abstain_reason"):
        PersonaReport(**params)
    report = PersonaReport(**params, abstain_reason="missing EPS")
    assert report.target_price_candidate is None
    with pytest.raises(ValidationError, match="abstaining"):
        PersonaReport(**params, target_price_candidate=190, abstain_reason="missing EPS")


def test_illustrative_entry_price_guard():
    params = dict(ticker="NVDA", snapshot_id="s1", mode=Mode.DEMO,
                  pit_status=PITStatus.VERIFIED, fair_value=195, target_12m=199)
    assert ValuationResult(**params, entry_price=159.2).entry_price == 159.2
    with pytest.raises(ValidationError, match="safety margin"):
        ValuationResult(**params, entry_price=190)


def test_unverified_benchmark_never_becomes_verified_by_parsing():
    listing = BenchmarkList(period="2025-H2", tickers=tuple(f"S{i}" for i in range(10)),
                            published_at=NOW, source_uri="https://example.com/original",
                            content_hash="hash", verification_status=PITStatus.UNVERIFIED,
                            verification_note="local import; not verified")
    assert listing.verification_status == PITStatus.UNVERIFIED
    with pytest.raises(ValidationError, match="ten distinct"):
        BenchmarkList.model_validate(listing.model_dump() | {"tickers": ["NVDA"] * 10})


def test_completed_backtest_requires_common_actual_sessions():
    params = dict(backtest_id="bt", signal_id="sig", period="2025-H2", mode=Mode.DEMO,
                  status=BacktestStatus.COMPLETED, entry_session=date(2025, 7, 2),
                  exit_session=date(2026, 1, 2), finagent=portfolio(), spy=portfolio("SPY"))
    assert BacktestResult(**params).seeking_alpha is None
    with pytest.raises(ValidationError, match="intervals differ"):
        BacktestResult(**(params | {"spy": portfolio("SPY", entry_session=date(2025, 7, 3))}))
    with pytest.raises(ValidationError, match="missing Seeking Alpha"):
        BacktestResult(**params, excess_vs_sa_pp=12)


def test_pending_window_does_not_contain_realized_return():
    with pytest.raises(ValidationError, match="realized results"):
        BacktestResult(backtest_id="bt", signal_id="sig", period="2025-H2", mode=Mode.DEMO,
                       status=BacktestStatus.PENDING, finagent=portfolio())


def test_invalid_market_ohlc_and_infinite_values_are_rejected():
    params = dict(ticker="NVDA", as_of=NOW, available_at=NOW, source="SYNTHETIC",
                  source_uri="synthetic://NVDA", content_hash="hash", pit_status=PITStatus.VERIFIED,
                  mode=Mode.DEMO, session=date(2025, 7, 1), open=100, close=101, high=102, low=99)
    with pytest.raises(ValidationError, match="OHLC"):
        MarketBar(**(params | {"low": 103}))
    with pytest.raises(ValidationError):
        MarketBar(**(params | {"close": float("inf")}))


def test_hash_is_stable_across_dict_order_and_changes_with_contents():
    assert stable_hash({"a": 1, "b": 2}) == stable_hash({"b": 2, "a": 1})
    assert stable_hash({"a": 1}) != stable_hash({"a": 2})
    assert stable_hash(snapshot()) == stable_hash(snapshot().model_dump(mode="json"))
