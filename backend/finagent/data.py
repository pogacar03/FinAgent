"""Deterministic demo data and explicitly imported point-in-time bundles.

DEMO records are invented fixtures. REAL mode reads one immutable, hash-checked
JSON bundle and never falls back to DEMO data.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import threading
import time as time_module
from typing import Any, Mapping, Protocol, Sequence
from urllib.parse import quote, urlparse

import httpx
from .contracts import (
    BenchmarkList,
    CorporateAction,
    EvidenceItem,
    EvidenceSnapshot,
    FinancialSnapshot,
    MarketBar,
    Mode,
    PITStatus,
    ResearchInput,
    SourceRecord,
    UniverseMember,
    UniverseSnapshot,
    stable_hash,
)

UTC = timezone.utc
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9.\-]{0,14}$")
_FINANCIAL_FIELDS = (
    "revenue",
    "revenue_growth",
    "earnings_per_share",
    "free_cash_flow",
    "shares_outstanding",
    "profit_margin",
    "eps_revision",
    "debt_to_equity",
)


class ProviderUnavailable(RuntimeError, ValueError):
    """A provider cannot supply admissible records for the requested input."""

    code = "UNAVAILABLE"


class DataProvider(Protocol):
    def universe(self, period: str, decision_at: datetime) -> UniverseSnapshot: ...

    def research_input(self, ticker: str, decision_at: datetime) -> ResearchInput: ...

    def bars(self, ticker: str, start: date, end: date) -> tuple[MarketBar, ...]: ...

    def actions(self, ticker: str, start: date, end: date) -> tuple[CorporateAction, ...]: ...

    def actions_complete(self, ticker: str, start: date, end: date) -> bool: ...


@dataclass(frozen=True)
class SECOriginalFiling:
    cik: str
    accession_number: str
    form: str
    filing_date: date
    accepted_at: datetime | None
    source_uri: str


@dataclass(frozen=True)
class _ActionCoverage:
    ticker: str
    start: date
    end: date
    complete: bool
    available_at: datetime
    source_uri: str
    pit_status: PITStatus


@dataclass(frozen=True)
class _ActionRecord:
    action: CorporateAction
    pit_status: PITStatus
    content_hash: str


def _require_aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must include a UTC offset")
    return value.astimezone(UTC)


def _validate_ticker(ticker: str) -> str:
    if not isinstance(ticker, str) or not _TICKER_PATTERN.fullmatch(ticker):
        raise ValueError(f"invalid canonical ticker: {ticker!r}")
    return ticker


def _seed(value: str) -> int:
    return int.from_bytes(hashlib.sha256(value.encode("utf-8")).digest()[:8], "big")


def _weekday_dates(start: date, end: date) -> tuple[date, ...]:
    if start > end:
        raise ValueError("start must be on or before end")
    days = (start + timedelta(days=i) for i in range((end - start).days + 1))
    return tuple(day for day in days if day.weekday() < 5)


def _record_hash(value: Mapping[str, Any], field: str = "content_hash") -> bool:
    supplied = value.get(field)
    if not isinstance(supplied, str) or not _SHA256.fullmatch(supplied):
        return False
    return supplied == stable_hash({key: item for key, item in value.items() if key != field})


def _evidence_for_financials(
    financials: FinancialSnapshot,
) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    for field in ("period_end", *_FINANCIAL_FIELDS):
        value = getattr(financials, field)
        if value is None:
            continue
        if isinstance(value, date):
            value = value.isoformat()
        items.append(
            EvidenceItem(
                evidence_id=f"financial:{financials.ticker}:{financials.period_end.isoformat()}:{field}",
                field=field,
                value=value,
                source_uri=financials.source_uri,
                available_at=financials.available_at,
                content_hash=financials.content_hash,
                pit_status=financials.pit_status,
                # A synthetic fixture observation is still a FACT inside the
                # input record; mode, PIT status, URI, and warnings carry the
                # distinction from verified real-world evidence.
                kind="FACT",
            )
        )
    return items


def _make_evidence(
    ticker: str,
    decision_at: datetime,
    mode: Mode,
    financials: FinancialSnapshot,
    market: Sequence[MarketBar],
    *,
    warnings: Sequence[str] = (),
) -> EvidenceSnapshot:
    items = _evidence_for_financials(financials)
    last_bar = market[-1]
    items.append(
        EvidenceItem(
            evidence_id=f"market:{ticker}:{last_bar.session.isoformat()}:close",
            field="market_close",
            value=last_bar.close,
            source_uri=last_bar.source_uri,
            available_at=last_bar.available_at,
            content_hash=last_bar.content_hash,
            pit_status=last_bar.pit_status,
            kind="FACT",
        )
    )
    if ticker == "SPY":
        items.append(
            EvidenceItem(
                evidence_id=f"instrument:{ticker}:type",
                field="instrument_type",
                value="ETF benchmark; issuer financial metrics are not applicable",
                source_uri=financials.source_uri,
                available_at=financials.available_at,
                content_hash=financials.content_hash,
                pit_status=financials.pit_status,
                kind="FACT",
            )
        )
    warnings_tuple = tuple(warnings)
    status = (
        PITStatus.VERIFIED
        if items and all(item.pit_status == PITStatus.VERIFIED for item in items)
        else PITStatus.UNVERIFIED
    )
    digest = stable_hash(
        {
            "ticker": ticker,
            "decision_at": decision_at,
            "mode": mode,
            "items": items,
            "warnings": warnings_tuple,
        }
    )
    return EvidenceSnapshot(
        snapshot_id=f"evidence:{ticker}:{digest[:16]}",
        ticker=ticker,
        decision_at=decision_at,
        mode=mode,
        items=tuple(items),
        content_hash=digest,
        pit_status=status,
        warnings=warnings_tuple,
    )


class DemoDataProvider:
    """Stable invented weekday data, explicitly labeled SYNTHETIC."""

    _universe: tuple[tuple[str, str], ...] = (
        ("AAPL", "Information Technology"),
        ("MSFT", "Information Technology"),
        ("NVDA", "Information Technology"),
        ("AVGO", "Information Technology"),
        ("AMZN", "Consumer Discretionary"),
        ("TSLA", "Consumer Discretionary"),
        ("COST", "Consumer Staples"),
        ("WMT", "Consumer Staples"),
        ("GOOGL", "Communication Services"),
        ("META", "Communication Services"),
        ("JPM", "Financials"),
        ("BRK.B", "Financials"),
        ("UNH", "Health Care"),
        ("LLY", "Health Care"),
        ("XOM", "Energy"),
        ("CAT", "Industrials"),
        ("NEE", "Utilities"),
        ("PLD", "Real Estate"),
        ("TSM", "Information Technology"),
        ("BABA", "Consumer Discretionary"),
        ("SPY", "ETF Benchmark"),
    )

    def universe(self, period: str, decision_at: datetime) -> UniverseSnapshot:
        cutoff = _require_aware(decision_at, "decision_at")
        if not re.fullmatch(r"20\d{2}-H[12]", period):
            raise ValueError("period must use YYYY-H1 or YYYY-H2")
        members = tuple(UniverseMember(ticker=ticker, sector=sector) for ticker, sector in self._universe)
        source_uri = f"synthetic://universe/{period}"
        payload = {
            "period": period,
            "as_of": cutoff.isoformat(),
            "available_at": cutoff.isoformat(),
            "members": [member.model_dump(mode="json") for member in members],
            "source": "SYNTHETIC_DEMO_UNIVERSE",
            "source_uri": source_uri,
            "mode": Mode.DEMO.value,
            "pit_status": PITStatus.UNVERIFIED.value,
            "survivorship_warning": "Synthetic fixed universe; no historical membership or delisting claim.",
        }
        return UniverseSnapshot(
            period=period,
            as_of=cutoff,
            available_at=cutoff,
            members=members,
            source="SYNTHETIC_DEMO_UNIVERSE",
            source_uri=source_uri,
            content_hash=stable_hash(payload),
            mode=Mode.DEMO,
            pit_status=PITStatus.UNVERIFIED,
            survivorship_warning="Synthetic fixed universe; no historical membership or delisting claim.",
        )

    def _bar(self, ticker: str, session: date) -> MarketBar:
        seed = _seed(ticker)
        index = (session - date(2015, 1, 1)).days
        base = 18.0 + seed % 480
        phase = (seed % 1000) / 1000.0 * math.tau
        trend = 0.00008 + ((seed >> 9) % 45) / 100000.0
        close = base * (
            1.0
            + trend * index
            + 0.035 * math.sin(index / 18.0 + phase)
            + 0.012 * math.cos(index / 5.5 + phase / 2)
        )
        close = max(1.0, close)
        open_price = close * (1.0 + 0.006 * math.sin(index * 0.71 + phase))
        spread = 0.004 + 0.006 * abs(math.sin(index / 3.7 + phase))
        high = max(open_price, close) * (1.0 + spread)
        low = min(open_price, close) * (1.0 - spread)
        session_close = datetime.combine(session, time(20, 0), UTC)
        available_at = datetime.combine(session, time(23, 59), UTC)
        record = {
            "ticker": ticker,
            "as_of": session_close.isoformat(),
            "available_at": available_at.isoformat(),
            "source": "SYNTHETIC_DEMO_WEEKDAY_CALENDAR",
            "source_uri": f"synthetic://market/{ticker}/{session.isoformat()}",
            "corporate_action_basis": "RAW_WITH_ACTIONS",
            "pit_status": PITStatus.UNVERIFIED.value,
            "mode": Mode.DEMO.value,
            "currency": "USD",
            "session": session.isoformat(),
            "open": round(open_price, 4),
            "high": round(high, 4),
            "low": round(low, 4),
            "close": round(close, 4),
            "volume": float(1_000_000 + seed % 25_000_000),
        }
        record["content_hash"] = stable_hash(record)
        return MarketBar.model_validate(record)

    def bars(self, ticker: str, start: date, end: date) -> tuple[MarketBar, ...]:
        _validate_ticker(ticker)
        return tuple(self._bar(ticker, session) for session in _weekday_dates(start, end))

    def _financials(self, ticker: str, decision_at: datetime) -> FinancialSnapshot:
        seed = _seed("financial:" + ticker)
        eligible_periods: list[tuple[date, datetime]] = []
        for year in (decision_at.year - 1, decision_at.year):
            for month, last_day in ((3, 31), (6, 30), (9, 30), (12, 31)):
                period_end = date(year, month, last_day)
                available_at = datetime.combine(period_end + timedelta(days=45), time(23, 59), UTC)
                if period_end <= decision_at.date() and available_at <= decision_at:
                    eligible_periods.append((period_end, available_at))
        if not eligible_periods:
            # Very early synthetic cutoffs still receive a dated illustrative snapshot.
            period_end = decision_at.date() - timedelta(days=120)
            available_at = datetime.combine(period_end + timedelta(days=45), time(23, 59), UTC)
        else:
            period_end, available_at = max(eligible_periods, key=lambda item: item[0])
        if ticker == "SPY":
            fields: dict[str, float | None] = {name: None for name in _FINANCIAL_FIELDS}
        else:
            revenue = float((1 + seed % 250) * 1_000_000_000)
            margin = 0.04 + ((seed >> 5) % 27) / 100.0
            fields = {
                "revenue": revenue,
                "revenue_growth": (((seed >> 12) % 51) - 8) / 100.0,
                "earnings_per_share": 1.0 + ((seed >> 19) % 300) / 10.0,
                "free_cash_flow": revenue * margin,
                "shares_outstanding": max(100_000_000.0, revenue / (10.0 + ((seed >> 23) % 40))),
                "profit_margin": 0.03 + ((seed >> 28) % 38) / 100.0,
                "eps_revision": (((seed >> 36) % 41) - 20) / 100.0,
                "debt_to_equity": ((seed >> 43) % 250) / 100.0,
            }
        source_uri = f"synthetic://financials/{ticker}/{period_end.isoformat()}"
        record: dict[str, Any] = {
            "ticker": ticker,
            "as_of": datetime.combine(period_end, time.min, UTC).isoformat(),
            "available_at": available_at.isoformat(),
            "source": "SYNTHETIC_DEMO_ASSUMPTIONS",
            "source_uri": source_uri,
            "corporate_action_basis": "RAW_WITH_ACTIONS",
            "pit_status": PITStatus.UNVERIFIED.value,
            "mode": Mode.DEMO.value,
            "currency": "USD",
            "period_end": period_end.isoformat(),
            **fields,
        }
        record["content_hash"] = stable_hash(record)
        return FinancialSnapshot.model_validate(record)

    def research_input(self, ticker: str, decision_at: datetime) -> ResearchInput:
        _validate_ticker(ticker)
        cutoff = _require_aware(decision_at, "decision_at")
        financials = self._financials(ticker, cutoff)
        history_start = cutoff.date() - timedelta(days=400)
        visible_market = tuple(
            bar
            for bar in self.bars(ticker, history_start, cutoff.date())
            if bar.session <= cutoff.date() and bar.available_at <= cutoff
        )
        if not visible_market:
            raise ProviderUnavailable(f"no synthetic market history is available for {ticker} at decision_at")
        evidence = _make_evidence(
            ticker,
            cutoff,
            Mode.DEMO,
            financials,
            visible_market,
            warnings=(
                "SYNTHETIC fixture values and synthetic weekday calendar; not historical market evidence.",
                "PIT_UNVERIFIED: illustrative values are not verified investment claims.",
            ),
        )
        return ResearchInput(
            ticker=ticker,
            sector=self._sector(ticker),
            decision_at=cutoff,
            mode=Mode.DEMO,
            market=visible_market,
            financials=financials,
            evidence=evidence,
        )

    def _sector(self, ticker: str) -> str:
        return dict(self._universe).get(ticker, "Other")

    def actions(self, ticker: str, start: date, end: date) -> tuple[CorporateAction, ...]:
        _validate_ticker(ticker)
        sessions = _weekday_dates(start, end)
        result: list[CorporateAction] = []
        if not sessions:
            return ()
        seed = _seed("actions:" + ticker)
        for year in range(start.year, end.year + 1):
            for month in (3, 6, 9, 12):
                candidate = date(year, month, 15)
                if start <= candidate <= end and candidate.weekday() < 5:
                    available_at = datetime.combine(candidate, time(23, 59), UTC)
                    result.append(
                        CorporateAction(
                            ticker=ticker,
                            session=candidate,
                            kind="DIVIDEND",
                            value=round(0.12 + (seed % 125) / 100.0, 4),
                            source="SYNTHETIC_DEMO_ACTIONS",
                            source_uri=f"synthetic://actions/{ticker}/{candidate.isoformat()}/dividend",
                            available_at=available_at,
                            currency="USD",
                        )
                    )
        return tuple(sorted(result, key=lambda item: (item.session, item.kind)))

    def actions_complete(self, ticker: str, start: date, end: date) -> bool:
        _validate_ticker(ticker)
        if start > end:
            raise ValueError("start must be on or before end")
        return True


class RealBundleProvider:
    """Read-only REAL provider backed by a canonical hash-checked JSON file."""

    def __init__(self, path: Path):
        self.path = path
        self.bundle_hash = ""
        self.verification_warning: str | None = None
        self._verified_evidence = False
        self._universes: list[UniverseSnapshot] = []
        self._bars: list[MarketBar] = []
        self._financials: list[FinancialSnapshot] = []
        self._actions: list[_ActionRecord] = []
        self._coverage: list[_ActionCoverage] = []
        self._load()

    def _load_json(self) -> dict[str, Any]:
        def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"duplicate JSON key {key!r}")
                result[key] = value
            return result

        try:
            value = json.loads(self.path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            raise ValueError(f"cannot read REAL_DATA_PATH JSON bundle: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError("REAL_DATA_PATH bundle must be a JSON object")
        return value

    def _load(self) -> None:
        bundle = self._load_json()
        supplied_bundle_hash = bundle.get("bundle_hash")
        hash_payload = {key: value for key, value in bundle.items() if key != "bundle_hash"}
        if not isinstance(supplied_bundle_hash, str) or not _SHA256.fullmatch(supplied_bundle_hash):
            raise ValueError("bundle_hash must be a lowercase SHA-256 digest")
        if stable_hash(hash_payload) != supplied_bundle_hash:
            raise ValueError("bundle_hash does not match canonical bundle contents")
        self.bundle_hash = supplied_bundle_hash
        if bundle.get("schema_version") != 1:
            raise ValueError("schema_version must be 1")
        if bundle.get("mode") != Mode.REAL.value:
            raise ValueError("bundle mode must be REAL")
        self._verified_evidence = self._has_verification_evidence(bundle.get("verification"))
        if not self._verified_evidence:
            self.verification_warning = (
                "Imported bundle has no complete user-supplied verification evidence; records are PIT_UNVERIFIED."
            )

        arrays = ("universes", "market_bars", "financials", "actions", "action_coverage")
        for name in arrays:
            if not isinstance(bundle.get(name), list):
                raise ValueError(f"{name} must be a JSON array")
        self._universes = [self._parse_universe(raw) for raw in bundle["universes"]]
        self._bars = [self._parse_source_record(raw, MarketBar) for raw in bundle["market_bars"]]
        self._financials = [self._parse_source_record(raw, FinancialSnapshot) for raw in bundle["financials"]]
        self._actions = [self._parse_action_envelope(raw) for raw in bundle["actions"]]
        self._coverage = [self._parse_coverage_envelope(raw) for raw in bundle["action_coverage"]]
        self._ensure_unique_records()

    def _has_verification_evidence(self, raw: Any) -> bool:
        if raw is None:
            return False
        if not isinstance(raw, dict):
            raise ValueError("verification must be an object when supplied")
        if raw.get("status") != PITStatus.VERIFIED.value:
            return False
        required = ("verified_by", "verified_at", "evidence_uri", "notes")
        if any(not isinstance(raw.get(field), str) or not raw[field].strip() for field in required):
            raise ValueError("verified bundle evidence requires verified_by, verified_at, evidence_uri, and notes")
        _require_aware(datetime.fromisoformat(raw["verified_at"].replace("Z", "+00:00")), "verification.verified_at")
        parsed = urlparse(raw["evidence_uri"])
        if not parsed.scheme:
            raise ValueError("verification.evidence_uri must be a URL or URI")
        return True

    def _effective_status(self, status: Any) -> PITStatus:
        pit = PITStatus(status)
        if not self._verified_evidence:
            return PITStatus.UNVERIFIED
        return pit

    def _parse_universe(self, raw: Any) -> UniverseSnapshot:
        if not isinstance(raw, dict):
            raise ValueError("each universe must be an object")
        if raw.get("mode") != Mode.REAL.value:
            raise ValueError("universe mode must be REAL")
        if not _record_hash(raw):
            raise ValueError("universe content_hash mismatch")
        if not isinstance(raw.get("members"), list):
            raise ValueError("universe members must be an array")
        value = dict(raw)
        value["pit_status"] = self._effective_status(value.get("pit_status"))
        return UniverseSnapshot.model_validate(value)

    def _parse_source_record(self, raw: Any, model: type[SourceRecord]) -> Any:
        if not isinstance(raw, dict):
            raise ValueError("data records must be objects")
        if raw.get("mode") != Mode.REAL.value:
            raise ValueError("data record mode must be REAL")
        if raw.get("currency") != "USD":
            raise ValueError("REAL bundle records must declare currency USD")
        if not _record_hash(raw):
            raise ValueError("data record content_hash mismatch")
        if model is MarketBar and raw.get("session") != str(raw.get("session")):
            raise ValueError("market bar session must be an ISO date")
        value = dict(raw)
        value["pit_status"] = self._effective_status(value.get("pit_status"))
        return model.model_validate(value)

    def _parse_action_envelope(self, raw: Any) -> _ActionRecord:
        if not isinstance(raw, dict) or not isinstance(raw.get("record"), dict):
            raise ValueError("each action must use {record, mode, pit_status, content_hash}")
        if raw.get("mode") != Mode.REAL.value:
            raise ValueError("corporate action mode must be REAL")
        if not _record_hash(raw):
            raise ValueError("corporate action envelope content_hash mismatch")
        record = raw["record"]
        if record.get("currency") != "USD":
            raise ValueError("corporate actions must declare currency USD")
        status = self._effective_status(raw.get("pit_status"))
        return _ActionRecord(
            action=CorporateAction.model_validate(record),
            pit_status=status,
            content_hash=raw["content_hash"],
        )

    def _parse_coverage_envelope(self, raw: Any) -> _ActionCoverage:
        if not isinstance(raw, dict):
            raise ValueError("action coverage entries must be objects")
        if raw.get("mode") != Mode.REAL.value:
            raise ValueError("action coverage mode must be REAL")
        if raw.get("currency") != "USD":
            raise ValueError("action coverage must declare currency USD")
        if not _record_hash(raw):
            raise ValueError("action coverage content_hash mismatch")
        ticker = _validate_ticker(raw.get("ticker"))
        start = date.fromisoformat(raw["start"])
        end = date.fromisoformat(raw["end"])
        if start > end:
            raise ValueError("action coverage start must be on or before end")
        available_at = _require_aware(datetime.fromisoformat(raw["available_at"].replace("Z", "+00:00")), "available_at")
        if not isinstance(raw.get("complete"), bool):
            raise ValueError("action coverage complete must be boolean")
        if not isinstance(raw.get("source_uri"), str) or not raw["source_uri"].strip():
            raise ValueError("action coverage source_uri is required")
        return _ActionCoverage(
            ticker=ticker,
            start=start,
            end=end,
            complete=raw["complete"],
            available_at=available_at,
            source_uri=raw["source_uri"],
            pit_status=self._effective_status(raw.get("pit_status")),
        )

    def _ensure_unique_records(self) -> None:
        bar_keys = [(bar.ticker, bar.session) for bar in self._bars]
        if len(bar_keys) != len(set(bar_keys)):
            raise ValueError("duplicate ticker/session market bar")
        financial_keys = [(item.ticker, item.period_end, item.available_at) for item in self._financials]
        if len(financial_keys) != len(set(financial_keys)):
            raise ValueError("duplicate ticker/period/availability financial snapshot")
        universe_keys = [(item.period, item.available_at) for item in self._universes]
        if len(universe_keys) != len(set(universe_keys)):
            raise ValueError("duplicate period/availability universe snapshot")

    def universe(self, period: str, decision_at: datetime) -> UniverseSnapshot:
        cutoff = _require_aware(decision_at, "decision_at")
        options = [
            item
            for item in self._universes
            if item.period == period and item.as_of <= cutoff and item.available_at <= cutoff
        ]
        if not options:
            raise ProviderUnavailable(f"REAL bundle has no PIT-admissible universe for {period}; import it in REAL_DATA_PATH")
        return max(options, key=lambda item: (item.available_at, item.as_of))

    def research_input(self, ticker: str, decision_at: datetime) -> ResearchInput:
        _validate_ticker(ticker)
        cutoff = _require_aware(decision_at, "decision_at")
        market = tuple(
            sorted(
                (
                    item
                    for item in self._bars
                    if item.ticker == ticker and item.session <= cutoff.date() and item.available_at <= cutoff
                ),
                key=lambda item: item.session,
            )
        )
        financial_options = [
            item
            for item in self._financials
            if item.ticker == ticker and item.period_end <= cutoff.date() and item.available_at <= cutoff
        ]
        if not market:
            raise ProviderUnavailable(f"REAL bundle has no market bars for {ticker} available by {cutoff.isoformat()}")
        if not financial_options:
            raise ProviderUnavailable(f"REAL bundle has no financial snapshot for {ticker} available by {cutoff.isoformat()}")
        financials = max(financial_options, key=lambda item: (item.available_at, item.period_end))
        warnings = (self.verification_warning,) if self.verification_warning else ()
        evidence = _make_evidence(ticker, cutoff, Mode.REAL, financials, market, warnings=warnings)
        return ResearchInput(
            ticker=ticker,
            sector=self._sector(ticker, cutoff),
            decision_at=cutoff,
            mode=Mode.REAL,
            market=market,
            financials=financials,
            evidence=evidence,
        )

    def _sector(self, ticker: str, decision_at: datetime) -> str:
        try:
            universe = self.universe_for_ticker(ticker, decision_at)
        except ProviderUnavailable:
            return "Unknown"
        return universe

    def universe_for_ticker(self, ticker: str, decision_at: datetime) -> str:
        eligible = [
            item
            for item in self._universes
            if item.as_of <= decision_at and item.available_at <= decision_at
        ]
        for snapshot in sorted(eligible, key=lambda item: item.available_at, reverse=True):
            match = next((member for member in snapshot.members if member.ticker == ticker), None)
            if match:
                return match.sector
        raise ProviderUnavailable(f"REAL bundle has no sector for {ticker}")

    def bars(self, ticker: str, start: date, end: date) -> tuple[MarketBar, ...]:
        _validate_ticker(ticker)
        if start > end:
            raise ValueError("start must be on or before end")
        return tuple(sorted((item for item in self._bars if item.ticker == ticker and start <= item.session <= end), key=lambda item: item.session))

    def actions(self, ticker: str, start: date, end: date) -> tuple[CorporateAction, ...]:
        _validate_ticker(ticker)
        if start > end:
            raise ValueError("start must be on or before end")
        records = [
            record
            for record in self._actions
            if record.action.ticker == ticker and start <= record.action.session <= end
        ]
        if any(record.pit_status != PITStatus.VERIFIED for record in records):
            raise ProviderUnavailable(
                f"REAL action interval contains PIT_UNVERIFIED events for {ticker}; refusing validated return calculation"
            )
        return tuple(sorted((record.action for record in records), key=lambda item: item.session))

    def actions_complete(self, ticker: str, start: date, end: date) -> bool:
        _validate_ticker(ticker)
        if start > end:
            raise ValueError("start must be on or before end")
        if any(
            record.action.ticker == ticker
            and start <= record.action.session <= end
            and record.pit_status != PITStatus.VERIFIED
            for record in self._actions
        ):
            return False
        coverage = sorted(
            (
                item
                for item in self._coverage
                if item.ticker == ticker and item.complete and item.pit_status == PITStatus.VERIFIED
            ),
            key=lambda item: (item.start, item.end),
        )
        covered_through: date | None = None
        for item in coverage:
            if item.end < start or item.start > end:
                continue
            if covered_through is None:
                if item.start > start:
                    return False
                covered_through = item.end
            elif item.start <= covered_through + timedelta(days=1):
                covered_through = max(covered_through, item.end)
            elif item.start > covered_through + timedelta(days=1):
                return False
            if covered_through >= end:
                return True
        return False


def provider_for(mode: Mode | str) -> DataProvider:
    try:
        normalized = Mode(mode)
    except ValueError as exc:
        raise ValueError(f"unsupported data mode: {mode!r}") from exc
    if normalized == Mode.DEMO:
        return DemoDataProvider()
    bundle_path = os.environ.get("REAL_DATA_PATH")
    if not bundle_path:
        raise ProviderUnavailable("REAL mode needs REAL_DATA_PATH pointing to a verified local JSON bundle")
    path = Path(bundle_path).expanduser()
    if not path.is_file():
        raise ProviderUnavailable(f"REAL_DATA_PATH does not exist or is not a file: {path}")
    try:
        return RealBundleProvider(path)
    except (OSError, TypeError, ValueError, KeyError) as exc:
        raise ProviderUnavailable(f"invalid REAL_DATA_PATH bundle: {exc}") from exc


def _canonical_benchmark_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    published_at = value.get("published_at")
    if isinstance(published_at, str):
        published_at = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    if isinstance(published_at, datetime):
        published_at = _require_aware(published_at, "published_at").isoformat()
    status = value.get("verification_status", PITStatus.UNVERIFIED)
    mode = value.get("mode", Mode.REAL)
    fields = {
        "period": value.get("period"),
        "tickers": list(value.get("tickers", ())),
        "published_at": published_at,
        "source_uri": value.get("source_uri"),
        "verification_status": status.value if isinstance(status, PITStatus) else str(status),
        "mode": mode.value if isinstance(mode, Mode) else str(mode),
        "verification_note": value.get("verification_note"),
    }
    return fields


def _verification_text(value: Mapping[str, Any]) -> str:
    required = ("verified_by", "verified_at", "evidence_uri", "notes")
    if any(not isinstance(value.get(field), str) or not value[field].strip() for field in required):
        raise ValueError("verified benchmark evidence requires verified_by, verified_at, evidence_uri, and notes")
    verified_at = datetime.fromisoformat(value["verified_at"].replace("Z", "+00:00"))
    _require_aware(verified_at, "verification_evidence.verified_at")
    if not urlparse(value["evidence_uri"]).scheme:
        raise ValueError("verification_evidence.evidence_uri must be a URL or URI")
    return (
        f"{value['notes'].strip()} (user-supplied evidence: {value['evidence_uri']}; "
        f"verified by {value['verified_by'].strip()} at {verified_at.isoformat()})"
    )


def validate_benchmark_list(
    value: BenchmarkList | Mapping[str, Any],
    *,
    verification_evidence: Mapping[str, Any] | None = None,
) -> BenchmarkList:
    """Validate an imported SA Top 10; default imported lists to PIT_UNVERIFIED."""
    raw = value.model_dump(mode="python") if isinstance(value, BenchmarkList) else dict(value)
    raw = dict(raw)
    source_uri = raw.get("source_uri")
    parsed = urlparse(source_uri if isinstance(source_uri, str) else "")
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (hostname == "seekingalpha.com" or hostname.endswith(".seekingalpha.com")):
        raise ValueError("benchmark original source URL must use the Seeking Alpha domain")
    if Mode(raw.get("mode", Mode.REAL)) != Mode.REAL:
        raise ValueError("Seeking Alpha benchmark mode must be REAL")
    if not isinstance(raw.get("verification_note"), str) or not raw["verification_note"].strip():
        raise ValueError("benchmark verification_note is required")
    tickers = raw.get("tickers")
    if not isinstance(tickers, (list, tuple)):
        raise ValueError("benchmark tickers must be an array")
    normalized = []
    for ticker in tickers:
        if not isinstance(ticker, str) or ticker != ticker.strip().upper():
            raise ValueError("benchmark tickers must be canonical uppercase symbols")
        normalized.append(_validate_ticker(ticker))
    if len(normalized) != 10 or len(set(normalized)) != 10:
        raise ValueError("benchmark requires exactly ten distinct canonical tickers")
    raw["tickers"] = tuple(normalized)
    raw["mode"] = Mode.REAL
    if verification_evidence is None:
        raw["verification_status"] = PITStatus.UNVERIFIED
    else:
        raw["verification_status"] = PITStatus.VERIFIED
        raw["verification_note"] = _verification_text(verification_evidence)
    raw["content_hash"] = stable_hash(_canonical_benchmark_payload(raw))
    return BenchmarkList.model_validate(raw)


def load_benchmark_csv(
    path: str | Path,
    *,
    verification_evidence: Mapping[str, Any] | None = None,
) -> BenchmarkList:
    """Load ten ticker rows sharing one period, URL, publication time, and note."""
    try:
        with Path(path).open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            required = {"period", "published_at", "source_uri", "ticker", "verification_note"}
            if reader.fieldnames is None or not required <= set(reader.fieldnames):
                raise ValueError(f"benchmark CSV requires columns: {', '.join(sorted(required))}")
            rows = [row for row in reader if any((value or "").strip() for value in row.values())]
    except OSError as exc:
        raise ValueError(f"cannot read benchmark CSV: {exc}") from exc
    if len(rows) != 10:
        raise ValueError("benchmark CSV must contain exactly ten non-empty ticker rows")
    metadata_fields = ("period", "published_at", "source_uri", "verification_note")
    first = rows[0]
    for row in rows:
        if any((row.get(field) or "").strip() != (first.get(field) or "").strip() for field in metadata_fields):
            raise ValueError("benchmark CSV metadata must match across all ten ticker rows")
    raw = {
        **{field: (first.get(field) or "").strip() for field in metadata_fields},
        "tickers": [(row.get("ticker") or "").strip() for row in rows],
        "mode": Mode.REAL,
        "verification_status": PITStatus.UNVERIFIED,
    }
    return validate_benchmark_list(raw, verification_evidence=verification_evidence)


def load_benchmark_json(
    path: str | Path,
    *,
    verification_evidence: Mapping[str, Any] | None = None,
) -> BenchmarkList:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"cannot read benchmark JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("benchmark JSON must be an object")
    return validate_benchmark_list(raw, verification_evidence=verification_evidence)


_sec_lock = threading.Lock()
_sec_last_request = 0.0


def _wait_for_sec_rate_limit() -> None:
    """Process-local throttle at 9 requests/second, under SEC's 10 RPS ceiling."""
    global _sec_last_request
    with _sec_lock:
        now = time_module.monotonic()
        delay = 1.0 / 9.0 - (now - _sec_last_request)
        if delay > 0:
            time_module.sleep(delay)
        _sec_last_request = time_module.monotonic()


def parse_sec_original_filings(cik: str, payload: Mapping[str, Any], *, limit: int = 100) -> tuple[SECOriginalFiling, ...]:
    """Parse original EDGAR filing metadata; never reads current companyfacts as PIT history."""
    if not re.fullmatch(r"\d{1,10}", cik):
        raise ValueError("CIK must contain one to ten digits")
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be from 1 through 1000")
    recent = payload.get("filings", {}).get("recent", {}) if isinstance(payload.get("filings"), Mapping) else {}
    if not isinstance(recent, Mapping):
        raise ValueError("SEC submissions payload is missing filings.recent")
    columns = ("accessionNumber", "form", "filingDate", "primaryDocument")
    if any(not isinstance(recent.get(name), list) for name in columns):
        raise ValueError("SEC submissions recent section is missing required filing columns")
    count = min(limit, *(len(recent[name]) for name in columns))
    accepted_column = recent.get("acceptanceDateTime", [])
    results: list[SECOriginalFiling] = []
    normalized_cik = cik.zfill(10)
    archive_cik = str(int(cik))
    for index in range(count):
        accession = str(recent["accessionNumber"][index])
        form = str(recent["form"][index])
        filing_date = date.fromisoformat(str(recent["filingDate"][index]))
        document = str(recent["primaryDocument"][index])
        if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession) or not document:
            continue
        accepted_at: datetime | None = None
        if index < len(accepted_column) and isinstance(accepted_column[index], str):
            stamp = accepted_column[index]
            try:
                accepted_at = _require_aware(datetime.fromisoformat(stamp.replace("Z", "+00:00")), "acceptanceDateTime")
            except ValueError:
                accepted_at = None
        source_uri = (
            f"https://www.sec.gov/Archives/edgar/data/{archive_cik}/"
            f"{accession.replace('-', '')}/{quote(document, safe='') }"
        )
        results.append(
            SECOriginalFiling(
                cik=normalized_cik,
                accession_number=accession,
                form=form,
                filing_date=filing_date,
                accepted_at=accepted_at,
                source_uri=source_uri,
            )
        )
    return tuple(results)


def fetch_sec_original_filings(
    cik: str,
    *,
    user_agent: str | None = None,
    limit: int = 100,
    timeout: float = 10.0,
    client: httpx.Client | None = None,
) -> tuple[SECOriginalFiling, ...]:
    """Fetch SEC Submissions metadata using SEC_USER_AGENT and a bounded throttle."""
    agent = user_agent or os.environ.get("SEC_USER_AGENT")
    if not isinstance(agent, str) or len(agent.strip()) < 10 or "@" not in agent or "\n" in agent or "\r" in agent:
        raise ProviderUnavailable("set SEC_USER_AGENT to an identifying value with a contact email")
    if not re.fullmatch(r"\d{1,10}", cik):
        raise ValueError("CIK must contain one to ten digits")
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    url = f"https://data.sec.gov/submissions/CIK{cik.zfill(10)}.json"
    _wait_for_sec_rate_limit()
    owns_client = client is None
    request_client = client or httpx.Client(timeout=timeout, follow_redirects=True)
    try:
        response = request_client.get(
            url,
            headers={"User-Agent": agent.strip(), "Accept-Encoding": "gzip, deflate", "Host": "data.sec.gov"},
        )
        response.raise_for_status()
        payload = response.json()
    finally:
        if owns_client:
            request_client.close()
    if not isinstance(payload, Mapping):
        raise ValueError("SEC submissions response must be a JSON object")
    return parse_sec_original_filings(cik, payload, limit=limit)


__all__ = [
    "DataProvider",
    "DemoDataProvider",
    "ProviderUnavailable",
    "RealBundleProvider",
    "SECOriginalFiling",
    "fetch_sec_original_filings",
    "load_benchmark_csv",
    "load_benchmark_json",
    "parse_sec_original_filings",
    "provider_for",
    "validate_benchmark_list",
]
