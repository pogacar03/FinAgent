from __future__ import annotations

from datetime import date, datetime, timezone
import json

import pytest

from finagent.contracts import (
    BacktestStatus,
    BenchmarkList,
    FrozenSignal,
    Mode,
    PITStatus,
    RankedPick,
    stable_hash,
)
from finagent.backtest import run_backtest
from finagent.data import (
    ProviderUnavailable,
    fetch_sec_original_filings,
    load_benchmark_csv,
    parse_sec_original_filings,
    provider_for,
    validate_benchmark_list,
)


def test_demo_research_input_is_synthetic_and_respects_decision_cutoff():
    cutoff = datetime(2025, 12, 31, 21, 0, tzinfo=timezone.utc)

    value = provider_for(Mode.DEMO).research_input("NVDA", cutoff)

    assert value.mode == Mode.DEMO
    assert value.evidence.pit_status == PITStatus.UNVERIFIED
    assert "SYNTHETIC" in value.financials.source
    assert value.financials.source_uri.startswith("synthetic://")
    assert len(value.market) >= 60
    assert all(bar.mode == Mode.DEMO for bar in value.market)
    assert all(bar.pit_status == PITStatus.UNVERIFIED for bar in value.market)
    assert all(bar.available_at <= cutoff for bar in value.market)
    assert all(bar.session <= cutoff.date() for bar in value.market)
    assert all(item.available_at <= cutoff for item in value.evidence.items)
    assert all(item.pit_status == PITStatus.UNVERIFIED for item in value.evidence.items)


def test_demo_universe_is_diverse_and_future_benchmark_bars_are_available():
    provider = provider_for(Mode.DEMO)
    cutoff = datetime(2025, 6, 30, 23, 59, tzinfo=timezone.utc)

    universe = provider.universe("2025-H2", cutoff)
    future_bars = provider.bars("SPY", date(2025, 7, 1), date(2026, 1, 31))

    assert len(universe.members) >= 16
    assert {"NVDA", "SPY"} <= {member.ticker for member in universe.members}
    assert len({member.sector for member in universe.members}) >= 8
    assert universe.mode == Mode.DEMO
    assert universe.pit_status == PITStatus.UNVERIFIED
    assert "SYNTHETIC" in universe.source
    assert universe.source_uri.startswith("synthetic://")
    assert future_bars
    assert min(bar.session for bar in future_bars) >= date(2025, 7, 1)
    assert max(bar.session for bar in future_bars) <= date(2026, 1, 31)
    assert all(bar.mode == Mode.DEMO and bar.pit_status == PITStatus.UNVERIFIED for bar in future_bars)
    assert provider.actions_complete("SPY", date(2025, 7, 1), date(2026, 1, 31))
    assert all(action.source_uri.startswith("synthetic://") for action in provider.actions("SPY", date(2025, 7, 1), date(2026, 1, 31)))


def test_real_mode_requires_an_explicit_bundle_and_never_falls_back(monkeypatch, tmp_path):
    monkeypatch.delenv("REAL_DATA_PATH", raising=False)

    with pytest.raises(ProviderUnavailable, match="REAL_DATA_PATH") as error:
        provider_for(Mode.REAL)

    assert error.value.code == "UNAVAILABLE"
    monkeypatch.setenv("REAL_DATA_PATH", str(tmp_path / "missing.json"))
    with pytest.raises(ProviderUnavailable, match="does not exist"):
        provider_for(Mode.REAL)


def test_benchmark_import_rejects_non_seeking_alpha_source():
    value = {
        "period": "2025-H2",
        "tickers": [f"TICK{i}" for i in range(10)],
        "published_at": "2025-07-01T12:00:00+00:00",
        "source_uri": "https://example.com/claimed-sa-list",
        "content_hash": "ignored-until-canonicalized",
        "verification_status": "PIT_VERIFIED",
        "mode": "REAL",
        "verification_note": "Imported user list",
    }

    with pytest.raises(ValueError, match="Seeking Alpha"):
        validate_benchmark_list(value)


def _seal(record):
    record["content_hash"] = stable_hash(record)
    return record


def _write_real_bundle(tmp_path, *, verified=True, coverage=True, coverage_end="2025-12-31"):
    universe = {
        "period": "2025-H2",
        "as_of": "2025-06-30T20:00:00+00:00",
        "available_at": "2025-06-30T23:59:00+00:00",
        "members": [
            {"ticker": "NVDA", "sector": "Information Technology"},
            {"ticker": "SPY", "sector": "ETF Benchmark"},
        ],
        "source": "Example Data Vendor",
        "source_uri": "https://data.example.test/universe/2025-H2",
        "mode": "REAL",
        "pit_status": "PIT_VERIFIED",
        "survivorship_warning": None,
    }
    _seal(universe)
    bars = [
        _seal(
            {
                "ticker": "NVDA",
                "as_of": f"{session}T20:00:00+00:00",
                "available_at": f"{session}T23:59:00+00:00",
                "source": "Example Data Vendor",
                "source_uri": f"https://data.example.test/bars/NVDA/{session}",
                "corporate_action_basis": "RAW_WITH_ACTIONS",
                "pit_status": "PIT_VERIFIED",
                "mode": "REAL",
                "currency": "USD",
                "session": session,
                "open": 100.0,
                "high": 103.0,
                "low": 99.0,
                "close": close,
                "volume": 1_000_000,
            }
        )
        for session, close in (("2025-12-30", 102.0), ("2025-12-31", 103.0))
    ]
    financial = _seal(
        {
            "ticker": "NVDA",
            "as_of": "2025-09-30T00:00:00+00:00",
            "available_at": "2025-11-14T23:59:00+00:00",
            "source": "Example Data Vendor",
            "source_uri": "https://data.example.test/financials/NVDA/2025-Q3",
            "corporate_action_basis": "RAW_WITH_ACTIONS",
            "pit_status": "PIT_VERIFIED",
            "mode": "REAL",
            "currency": "USD",
            "period_end": "2025-09-30",
            "revenue": 100_000_000_000.0,
            "revenue_growth": 0.15,
            "earnings_per_share": 4.2,
            "free_cash_flow": 20_000_000_000.0,
            "shares_outstanding": 2_400_000_000.0,
            "profit_margin": 0.24,
            "eps_revision": 0.03,
            "debt_to_equity": 0.4,
        }
    )
    actions = [
        {
            "record": {
                "ticker": "NVDA",
                "session": "2025-12-15",
                "kind": "DIVIDEND",
                "value": 0.01,
                "source": "Example Data Vendor",
                "source_uri": "https://data.example.test/actions/NVDA/2025-12-15",
                "available_at": "2025-12-15T23:59:00+00:00",
                "currency": "USD",
            },
            "mode": "REAL",
            "pit_status": "PIT_VERIFIED",
        }
    ]
    _seal(actions[0])
    coverage_rows = []
    if coverage:
        coverage_rows = [
            _seal(
                {
                    "ticker": "NVDA",
                    "start": "2025-01-01",
                    "end": coverage_end,
                    "complete": True,
                    "available_at": "2026-01-01T00:00:00+00:00",
                    "source_uri": "https://data.example.test/actions/NVDA/coverage/2025",
                    "currency": "USD",
                    "mode": "REAL",
                    "pit_status": "PIT_VERIFIED",
                }
            )
        ]
    bundle = {
        "schema_version": 1,
        "mode": "REAL",
        "verification": (
            {
                "status": "PIT_VERIFIED",
                "verified_by": "test reviewer",
                "verified_at": "2026-01-02T12:00:00+00:00",
                "evidence_uri": "file:///tmp/evidence/verification-note.txt",
                "notes": "User supplied source timestamp and archive review.",
            }
            if verified
            else None
        ),
        "universes": [universe],
        "market_bars": bars,
        "financials": [financial],
        "actions": actions,
        "action_coverage": coverage_rows,
    }
    bundle["bundle_hash"] = stable_hash(bundle)
    path = tmp_path / "real-bundle.json"
    path.write_text(json.dumps(bundle), encoding="utf-8")
    return path


def _reseal_bundle(path, update):
    raw = json.loads(path.read_text(encoding="utf-8"))
    update(raw)
    for action in raw["actions"]:
        action.pop("content_hash", None)
        action["content_hash"] = stable_hash(action)
    raw.pop("bundle_hash", None)
    raw["bundle_hash"] = stable_hash(raw)
    path.write_text(json.dumps(raw), encoding="utf-8")


def test_real_bundle_hash_and_attestation_gate_verified_pit_data(monkeypatch, tmp_path):
    path = _write_real_bundle(tmp_path, verified=True)
    monkeypatch.setenv("REAL_DATA_PATH", str(path))
    provider = provider_for(Mode.REAL)
    cutoff = datetime(2025, 12, 31, 12, 0, tzinfo=timezone.utc)

    result = provider.research_input("NVDA", cutoff)

    assert result.mode == Mode.REAL
    assert result.financials.pit_status == PITStatus.VERIFIED
    assert result.evidence.pit_status == PITStatus.VERIFIED
    assert result.market[-1].session == date(2025, 12, 30)
    assert all(bar.available_at <= cutoff for bar in result.market)
    assert all(item.available_at <= cutoff for item in result.evidence.items)
    assert provider.actions_complete("NVDA", date(2025, 1, 1), date(2025, 12, 31))
    assert not provider.actions_complete("NVDA", date(2025, 1, 1), date(2026, 1, 1))
    assert provider.actions("NVDA", date(2025, 12, 1), date(2025, 12, 31))


def test_real_bundle_without_user_evidence_is_unverified_and_unknown_actions_are_incomplete(monkeypatch, tmp_path):
    path = _write_real_bundle(tmp_path, verified=False, coverage=False)
    monkeypatch.setenv("REAL_DATA_PATH", str(path))
    provider = provider_for(Mode.REAL)

    result = provider.research_input("NVDA", datetime(2025, 12, 31, 12, 0, tzinfo=timezone.utc))

    assert result.financials.pit_status == PITStatus.UNVERIFIED
    assert result.evidence.pit_status == PITStatus.UNVERIFIED
    assert any("no complete user-supplied verification evidence" in warning for warning in result.evidence.warnings)
    assert not provider.actions_complete("NVDA", date(2025, 1, 1), date(2025, 12, 31))
    with pytest.raises(ProviderUnavailable, match="PIT_UNVERIFIED"):
        provider.actions("NVDA", date(2025, 1, 1), date(2025, 12, 31))


def test_verified_coverage_with_unverified_action_is_incomplete_and_unavailable(monkeypatch, tmp_path):
    path = _write_real_bundle(tmp_path, verified=True, coverage=True)
    _reseal_bundle(path, lambda raw: raw["actions"][0].update(pit_status="PIT_UNVERIFIED"))
    monkeypatch.setenv("REAL_DATA_PATH", str(path))
    provider = provider_for(Mode.REAL)

    assert not provider.actions_complete("NVDA", date(2025, 1, 1), date(2025, 12, 31))
    with pytest.raises(ProviderUnavailable, match="PIT_UNVERIFIED"):
        provider.actions("NVDA", date(2025, 1, 1), date(2025, 12, 31))


def test_verified_empty_action_coverage_allows_interval_with_no_events(monkeypatch, tmp_path):
    path = _write_real_bundle(tmp_path, verified=True, coverage=True)
    _reseal_bundle(path, lambda raw: raw.update(actions=[]))
    monkeypatch.setenv("REAL_DATA_PATH", str(path))
    provider = provider_for(Mode.REAL)

    assert provider.actions_complete("NVDA", date(2025, 1, 1), date(2025, 12, 31))
    assert provider.actions("NVDA", date(2025, 1, 1), date(2025, 12, 31)) == ()


def test_unverified_action_prevents_a_completed_real_comparison(monkeypatch, tmp_path):
    path = _write_real_bundle(tmp_path, verified=True, coverage=True, coverage_end="2026-01-02")
    _reseal_bundle(path, lambda raw: raw["actions"][0].update(pit_status="PIT_UNVERIFIED"))
    monkeypatch.setenv("REAL_DATA_PATH", str(path))
    imported = provider_for(Mode.REAL)
    demo = provider_for(Mode.DEMO)

    class ReplayProvider:
        def bars(self, ticker, start, end):
            result = []
            for item in demo.bars(ticker, start, end):
                raw = item.model_dump(mode="python")
                raw.update(
                    source="TEST_FIXTURE_FOR_REAL_ACTION_GUARD",
                    source_uri=f"https://fixture.invalid/{ticker}/{item.session}",
                    mode=Mode.REAL,
                    pit_status=PITStatus.VERIFIED,
                )
                raw["content_hash"] = stable_hash({key: value for key, value in raw.items() if key != "content_hash"})
                from finagent.contracts import MarketBar

                result.append(MarketBar.model_validate(raw))
            return tuple(result)

        def actions(self, ticker, start, end):
            return imported.actions(ticker, start, end)

        def actions_complete(self, ticker, start, end):
            return imported.actions_complete(ticker, start, end) if ticker == "NVDA" else True

    decision_at = datetime(2025, 6, 30, 23, 59, tzinfo=timezone.utc)
    picks = tuple(
        RankedPick(
            rank=index + 1,
            ticker=ticker,
            sector="Technology",
            weight=0.1,
            score=1.0,
            target_12m=120,
            entry_price=96,
            snapshot_id=f"snapshot-{ticker}",
            snapshot_hash=f"hash-{ticker}",
            rationale="test fixture",
        )
        for index, ticker in enumerate(("NVDA", *(f"S{i}" for i in range(9))))
    )
    signal = FrozenSignal(
        signal_id="real-fixture-signal",
        run_id="real-fixture-run",
        period="2025-H2",
        decision_at=decision_at,
        frozen_at=decision_at,
        mode=Mode.REAL,
        pit_status=PITStatus.VERIFIED,
        picks=picks,
        config_hash="fixture-config",
    )
    benchmark = BenchmarkList(
        period="2025-H2",
        tickers=tuple(f"A{i}" for i in range(10)),
        published_at=decision_at,
        source_uri="https://seekingalpha.com/article/test-fixture",
        content_hash="test-benchmark-hash",
        verification_status=PITStatus.VERIFIED,
        mode=Mode.REAL,
        verification_note="Test fixture only",
    )

    result = run_backtest(
        signal,
        ReplayProvider(),
        backtest_id="real-fixture-backtest",
        as_of=datetime(2026, 2, 2, 22, 0, tzinfo=timezone.utc),
        benchmark=benchmark,
    )

    assert not imported.actions_complete("NVDA", date(2025, 7, 1), date(2026, 1, 2))
    assert result.status == BacktestStatus.VALIDATION_FAILED
    assert result.reason == "MISSING_ACTION_COVERAGE:NVDA"
    assert result.finagent is None and result.spy is None and result.seeking_alpha is None
    assert result.excess_vs_sa_pp is None and result.excess_vs_spy_pp is None


def test_real_bundle_detects_tampering_even_when_file_is_present(monkeypatch, tmp_path):
    path = _write_real_bundle(tmp_path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["market_bars"][0]["close"] = 999.0
    path.write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setenv("REAL_DATA_PATH", str(path))

    with pytest.raises(ProviderUnavailable, match="bundle_hash"):
        provider_for(Mode.REAL)


def test_benchmark_import_defaults_to_unverified_and_needs_explicit_evidence_for_verified():
    value = {
        "period": "2025-H2",
        "tickers": ["AAPL", "MSFT", "NVDA", "AVGO", "AMZN", "META", "JPM", "LLY", "XOM", "CAT"],
        "published_at": "2025-07-01T12:00:00+00:00",
        "source_uri": "https://seekingalpha.com/article/original-top-ten-list",
        "content_hash": "not-trusted",
        "verification_status": "PIT_VERIFIED",
        "mode": "REAL",
        "verification_note": "Original list imported from the source article.",
    }

    imported = validate_benchmark_list(value)
    verified = validate_benchmark_list(
        value,
        verification_evidence={
            "verified_by": "researcher",
            "verified_at": "2026-01-02T12:00:00+00:00",
            "evidence_uri": "file:///tmp/evidence/sa-capture.pdf",
            "notes": "Compared original publication time and all ten symbols to saved capture.",
        },
    )

    assert imported.verification_status == PITStatus.UNVERIFIED
    assert len(imported.content_hash) == 64
    assert verified.verification_status == PITStatus.VERIFIED
    assert verified.content_hash != imported.content_hash


def test_benchmark_csv_loader_reads_exactly_ten_shared_metadata_rows(tmp_path):
    path = tmp_path / "sa.csv"
    tickers = ["AAPL", "MSFT", "NVDA", "AVGO", "AMZN", "META", "JPM", "LLY", "XOM", "CAT"]
    lines = ["period,published_at,source_uri,ticker,verification_note"]
    lines += [
        f"2025-H2,2025-07-01T12:00:00+00:00,https://seekingalpha.com/article/original-top-ten-list,{ticker},Source imported; manually verify original publication"
        for ticker in tickers
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = load_benchmark_csv(path)

    assert result.tickers == tuple(tickers)
    assert result.verification_status == PITStatus.UNVERIFIED


def test_sec_adapter_preserves_original_acceptance_timestamp_and_requires_contact_user_agent(monkeypatch):
    payload = {
        "filings": {
            "recent": {
                "accessionNumber": ["0000320193-25-000123"],
                "form": ["10-Q"],
                "filingDate": ["2025-10-31"],
                "primaryDocument": ["aapl-20250927.htm"],
                "acceptanceDateTime": ["2025-10-31T20:15:00Z"],
            }
        }
    }
    filing = parse_sec_original_filings("320193", payload)[0]
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)

    with pytest.raises(ProviderUnavailable, match="SEC_USER_AGENT"):
        fetch_sec_original_filings("320193")

    assert filing.accepted_at == datetime(2025, 10, 31, 20, 15, tzinfo=timezone.utc)
    assert filing.source_uri.endswith("/000032019325000123/aapl-20250927.htm")
