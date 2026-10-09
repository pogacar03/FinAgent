"""Frozen-signal replay with explicit calendar, share/cash, and coverage rules.

This module never imports agent orchestration or asks a model to recall prices.
The provider's SPY session panel is the session calendar; missing held-stock data
on those sessions fails validation rather than selecting a later favorable open.
"""
from __future__ import annotations

import calendar
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from .contracts import (
    BacktestResult, BacktestStatus, BenchmarkList, CorporateAction, FrozenSignal,
    HoldingReturn, MarketBar, Mode, PITStatus, PortfolioReturn, stable_hash,
)
if TYPE_CHECKING:
    from .data import DataProvider

NY = ZoneInfo('America/New_York')


class _InvalidData(ValueError):
    pass


def _open(session: date) -> datetime:
    return datetime.combine(session, time(9, 30), NY)


def _six_months(session: date) -> date:
    month_index = session.year * 12 + session.month - 1 + 6
    year, month0 = divmod(month_index, 12)
    month = month0 + 1
    return date(year, month, min(session.day, calendar.monthrange(year, month)[1]))


def _panel(ticker: str, bars: Sequence[MarketBar], signal: FrozenSignal,
           as_of: datetime) -> dict[date, MarketBar]:
    panel: dict[date, MarketBar] = {}
    for bar in bars:
        if bar.ticker != ticker or bar.mode != signal.mode:
            raise _InvalidData(f'BAR_TICKER_OR_MODE_MISMATCH:{ticker}')
        if bar.session in panel:
            raise _InvalidData(f'DUPLICATE_SESSION:{ticker}:{bar.session}')
        if bar.currency != 'USD' or bar.corporate_action_basis != 'RAW_WITH_ACTIONS':
            raise _InvalidData(f'BAR_CURRENCY_OR_BASIS:{ticker}')
        if bar.available_at > as_of or bar.as_of > as_of:
            raise _InvalidData(f'UNAVAILABLE_BAR_AT_EVALUATION:{ticker}:{bar.session}')
        if signal.mode == Mode.REAL and bar.pit_status != PITStatus.VERIFIED:
            raise _InvalidData(f'PIT_UNVERIFIED_BAR:{ticker}')
        panel[bar.session] = bar
    return panel


def _actions(ticker: str, events: Sequence[CorporateAction], *, start: date, end: date,
             as_of: datetime, sessions: set[date]) -> tuple[CorporateAction, ...]:
    seen = set()
    for event in events:
        if event.ticker != ticker or event.currency != 'USD' or event.available_at > as_of:
            raise _InvalidData(f'INVALID_ACTION:{ticker}')
        if not start <= event.session <= end or event.session not in sessions:
            raise _InvalidData(f'ACTION_OUTSIDE_VALID_SESSIONS:{ticker}:{event.session}')
        key = (event.session, event.kind)
        # Same-day action aggregation is the provider's job. Duplicate records
        # must never silently double a dividend or share adjustment.
        if key in seen:
            raise _InvalidData(f'DUPLICATE_ACTION:{ticker}:{event.session}:{event.kind}')
        seen.add(key)
    return tuple(sorted(events, key=lambda a: (a.session, 0 if a.kind == 'SPLIT' else 1)))


def _holding(ticker: str, weight: float, panel: dict[date, MarketBar],
             events: Sequence[CorporateAction], *, entry: date, exit: date,
             cost: float, slip: float, limit: float | None = None,
             limit_basis_at: datetime | None = None) -> HoldingReturn:
    fill_session = entry
    raw_entry = panel[entry].open
    if limit is not None:
        # The frozen limit is denominated in decision-time raw shares. Splits
        # after that instant change the pending order's per-share threshold,
        # including splits effective before common entry or on the fill day.
        splits = [event for event in events if event.kind == 'SPLIT'
                  and (limit_basis_at is None or _open(event.session) > limit_basis_at)]
        fill = None
        for session, bar in sorted(panel.items()):
            if not entry <= session < exit:
                continue
            split_factor = 1.0
            for event in splits:
                if event.session <= session:
                    split_factor *= event.value
            adjusted_limit = limit / split_factor
            if bar.low <= adjusted_limit:
                fill = bar
                limit = adjusted_limit
                break
        if fill is None:
            return HoldingReturn(ticker=ticker, weight=weight, filled=False,
                                 entry_price=panel[entry].open, exit_price=panel[exit].open, total_return=0)
        fill_session = fill.session
        raw_entry = min(fill.open, limit)
    execution_entry = raw_entry * (1 + slip)
    if limit is not None:
        execution_entry = min(execution_entry, limit)
    capital = execution_entry * (1 + cost)
    shares = 1.0
    dividend_cash = 0.0
    for action in events:
        # Ex-date entitlement belongs to holdings from the prior session.
        # Entry ex-date is excluded; exit-open ex-date is included.
        if not fill_session < action.session <= exit:
            continue
        if action.kind == 'SPLIT':
            shares *= action.value
        else:
            dividend_cash += shares * action.value
    raw_exit = panel[exit].open
    proceeds = shares * raw_exit * (1 - slip) * (1 - cost) + dividend_cash
    return HoldingReturn(ticker=ticker, weight=weight, entry_price=raw_entry, exit_price=raw_exit,
                         dividends=dividend_cash, split_factor=shares,
                         total_return=proceeds / capital - 1)


def run_backtest(signal: FrozenSignal, provider: DataProvider, *, backtest_id: str,
                 as_of: datetime, benchmark: BenchmarkList | None = None,
                 transaction_cost_bps: float = 0, slippage_bps: float = 0,
                 policy: str = 'PRIMARY') -> BacktestResult:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError('as_of requires timezone')
    if policy not in ('PRIMARY', 'LIMIT_ENTRY'):
        raise ValueError('unknown backtest policy')
    if not 0 <= transaction_cost_bps <= 1000 or not 0 <= slippage_bps <= 1000:
        raise ValueError('cost and slippage must be in [0,1000] bps')
    warnings = ['RAW_WITH_ACTIONS; dividends kept as cash; no reinvestment.',
                'SPY provider sessions anchor the calendar; provider coverage must be complete.']
    if signal.mode == Mode.DEMO:
        warnings.append('SYNTHETIC_DEMO: simulated results are not validated historical performance.')
    if policy == 'LIMIT_ENTRY':
        warnings.append('SECONDARY_LIMIT_ENTRY: nonfills remain zero-interest cash; do not mix with PRIMARY selection results.')
    sa_status = 'UNAVAILABLE'
    verified_sa = None
    if benchmark is None:
        warnings.append('SEEKING_ALPHA_UNAVAILABLE: no original verified list supplied.')
    elif benchmark.verification_status != PITStatus.VERIFIED:
        sa_status = 'UNVERIFIED'
        warnings.append('SEEKING_ALPHA_UNVERIFIED: excluded from all comparisons and timing.')
    elif benchmark.period != signal.period or benchmark.mode != signal.mode:
        sa_status = 'UNVERIFIED'
        warnings.append('SEEKING_ALPHA_PERIOD_OR_MODE_MISMATCH: excluded from comparison.')
    else:
        verified_sa = benchmark
        sa_status = 'AVAILABLE'
    common = dict(backtest_id=backtest_id, signal_id=signal.signal_id, period=signal.period,
                  mode=signal.mode, policy=policy, seeking_alpha_status=sa_status,
                  transaction_cost_bps=transaction_cost_bps, slippage_bps=slippage_bps)
    def fail(status: BacktestStatus, reason: str, entry=None, exit=None) -> BacktestResult:
        return BacktestResult(**common, status=status, reason=reason, warnings=tuple(warnings),
                              entry_session=entry, exit_session=exit)
    cutoff = max(signal.decision_at, signal.frozen_at,
                 verified_sa.published_at if verified_sa else signal.frozen_at)
    if as_of <= cutoff:
        return fail(BacktestStatus.PENDING, 'NO_ELIGIBLE_OPEN_AFTER_FREEZE_OR_PUBLICATION')
    start = (signal.decision_at if policy == 'LIMIT_ENTRY' else cutoff).astimezone(NY).date()
    end = as_of.astimezone(NY).date()
    tickers = set(p.ticker for p in signal.picks) | {'SPY'}
    if verified_sa:
        tickers.update(verified_sa.tickers)
    try:
        spy_records = tuple(provider.bars('SPY', start, end))
        # Choose the interval using the calendar rows, then validate only its
        # data. A partial current-day bar years after exit is irrelevant to the
        # already matured experiment and must not invalidate it.
        session_dates = {b.session for b in spy_records if _open(b.session) <= as_of}
        entry_options = sorted(s for s in session_dates if _open(s) > cutoff)
        if not entry_options:
            return fail(BacktestStatus.PENDING if (as_of - cutoff) < timedelta(days=7)
                        else BacktestStatus.VALIDATION_FAILED, 'MISSING_ELIGIBLE_SPY_ENTRY_SESSION')
        entry = entry_options[0]
        maturity = _six_months(entry)
        if as_of < _open(maturity):
            return fail(BacktestStatus.PENDING, 'SIX_CALENDAR_MONTH_WINDOW_NOT_MATURE', entry)
        exit_options = sorted(s for s in session_dates if s >= maturity and _open(s) <= as_of)
        if not exit_options:
            return fail(BacktestStatus.PENDING if (as_of.date() - maturity).days <= 7
                        else BacktestStatus.VALIDATION_FAILED, 'MISSING_SPY_EXIT_SESSION', entry)
        exit = exit_options[0]
        needed_sessions = {s for s in session_dates if entry <= s <= exit}
        spy_panel = _panel('SPY', tuple(b for b in spy_records if entry <= b.session <= exit), signal, as_of)
        panels: dict[str, dict[date, MarketBar]] = {}
        action_panels: dict[str, tuple[CorporateAction, ...]] = {}
        for ticker in sorted(tickers):
            records = (spy_panel[s] for s in sorted(needed_sessions)) if ticker == 'SPY' else provider.bars(ticker, entry, exit)
            panel = _panel(ticker, tuple(records), signal, as_of)
            missing = needed_sessions - set(panel)
            if missing:
                raise _InvalidData(f'MISSING_REQUIRED_SESSION:{ticker}:{min(missing)}')
            # Extra rows on non-SPY sessions cannot alter the investment calendar.
            panels[ticker] = {s: panel[s] for s in needed_sessions}
            # Waiting orders require verified split coverage starting at the
            # frozen price basis, even if late SA publication delays entry.
            action_start = start if policy == 'LIMIT_ENTRY' and ticker in {p.ticker for p in signal.picks} else entry
            action_sessions = {s for s in session_dates if action_start <= s <= exit}
            if not provider.actions_complete(ticker, action_start, exit):
                raise _InvalidData(f'MISSING_ACTION_COVERAGE:{ticker}')
            action_panels[ticker] = _actions(ticker, provider.actions(ticker, action_start, exit),
                                             start=action_start, end=exit, as_of=as_of, sessions=action_sessions)
        cost, slip = transaction_cost_bps / 10_000, slippage_bps / 10_000
        def portfolio(name: str, members: Sequence[str], limits: dict[str, float] | None = None) -> PortfolioReturn:
            holdings = tuple(_holding(t, 1 / len(members), panels[t], action_panels[t],
                                      entry=entry, exit=exit, cost=cost, slip=slip,
                                      limit=limits.get(t) if limits else None,
                                      limit_basis_at=signal.decision_at if limits else None) for t in members)
            return PortfolioReturn(name=name, total_return=sum(h.total_return * h.weight for h in holdings),
                                   holdings=holdings, entry_session=entry, exit_session=exit)
        members = tuple(p.ticker for p in signal.picks)
        limits = {p.ticker: p.entry_price for p in signal.picks} if policy == 'LIMIT_ENTRY' else None
        finagent = portfolio('FinAgent', members, limits)
        if limits:
            primary = portfolio('FinAgent PRIMARY counterfactual', members)
            warnings.append('LIMIT_ENTRY_OPPORTUNITY_COST_VS_PRIMARY_PP='
                            f'{(primary.total_return - finagent.total_return) * 100:.6f}; '
                            'positive means waiting lost return relative to the same frozen picks.')
        spy = portfolio('SPY', ('SPY',))
        sa = portfolio('Seeking Alpha', verified_sa.tickers) if verified_sa else None
        snapshot_hash = stable_hash({'signal': signal, 'benchmark': verified_sa,
                                     'panels': {t: tuple(panels[t][s] for s in sorted(panels[t])) for t in sorted(panels)},
                                     'actions': action_panels, 'entry': entry, 'exit': exit,
                                     'cost_bps': transaction_cost_bps, 'slippage_bps': slippage_bps, 'policy': policy})
        return BacktestResult(**common, status=BacktestStatus.COMPLETED, entry_session=entry, exit_session=exit,
                              finagent=finagent, spy=spy, seeking_alpha=sa,
                              excess_vs_spy_pp=(finagent.total_return - spy.total_return) * 100,
                              excess_vs_sa_pp=(finagent.total_return - sa.total_return) * 100 if sa else None,
                              warnings=tuple(warnings), snapshot_hash=snapshot_hash,
                              cash_weight=sum(h.weight for h in finagent.holdings if not h.filled))
    except _InvalidData as exc:
        return fail(BacktestStatus.VALIDATION_FAILED, str(exc))
    except Exception as exc:
        # Do not expose provider exception strings, which may contain request URLs/keys.
        status = BacktestStatus.UNAVAILABLE if type(exc).__name__ == 'ProviderUnavailable' else BacktestStatus.VALIDATION_FAILED
        return fail(status, f'PROVIDER_ERROR:{type(exc).__name__}')


def aggregate_backtests(results: Sequence[BacktestResult]) -> dict:
    """Period-end coverage/NAV only; no claim to intraperiod maximum drawdown.

    Mixed policies/modes and overlapping completed windows are rejected. Each
    period contributes at most one completed observation, avoiding sample inflation.
    """
    if len({(r.mode, r.policy) for r in results}) > 1:
        raise ValueError('aggregate requires one mode and one execution policy')
    valid = sorted((r for r in results if r.status == BacktestStatus.COMPLETED),
                   key=lambda r: (r.entry_session, r.period))
    if len({r.period for r in valid}) != len(valid):
        raise ValueError('duplicate completed period')
    if any(a.exit_session > b.entry_session for a, b in zip(valid, valid[1:])):
        raise ValueError('overlapping periods cannot form chained NAV')
    label = ('NO_RESULTS' if not results else
             'SYNTHETIC_DEMO' if results[0].mode == Mode.DEMO else 'REAL_VERIFIED_INPUTS')
    missing = sorted({r.period for r in results if r.status != BacktestStatus.COMPLETED})
    nav = peak = 1.0
    drawdown = 0.0
    history = [{'session': str(valid[0].entry_session), 'nav': 1.0}] if valid else []
    for result in valid:
        nav *= 1 + result.finagent.total_return
        peak = max(peak, nav)
        drawdown = min(drawdown, nav / peak - 1)
        history.append({'session': str(result.exit_session), 'period': result.period, 'nav': nav})
    sa_valid = [r for r in valid if r.seeking_alpha is not None]
    def benchmark_nav(attribute: str) -> list[dict] | None:
        if not valid or any(getattr(result, attribute) is None for result in valid):
            return None
        value = 1.0
        history = [{'session': str(valid[0].entry_session), 'nav': value}]
        for result in valid:
            value *= 1 + getattr(result, attribute).total_return
            history.append({'session': str(result.exit_session), 'period': result.period, 'nav': value})
        return history
    returns = [{'period': r.period, 'entry_session': str(r.entry_session), 'exit_session': str(r.exit_session),
                'finagent': r.finagent.total_return, 'spy': r.spy.total_return,
                'seeking_alpha': r.seeking_alpha.total_return if r.seeking_alpha else None,
                'excess_vs_spy_pp': r.excess_vs_spy_pp, 'excess_vs_sa_pp': r.excess_vs_sa_pp}
               for r in valid]
    return {'truth_label': label, 'policy': results[0].policy if results else 'PRIMARY',
            'total_periods': len(results), 'valid_periods': len(valid),
            'valid_sa_periods': len(sa_valid), 'missing_periods': missing,
            'coverage': len(valid) / len(results) if results else 0,
            'winning_periods_vs_spy': sum(r.excess_vs_spy_pp > 0 for r in valid),
            'winning_periods_vs_sa': sum(r.excess_vs_sa_pp > 0 for r in sa_valid),
            'chained_nav': history, 'max_drawdown': drawdown,
            'spy_chained_nav': benchmark_nav('spy'),
            'seeking_alpha_chained_nav': benchmark_nav('seeking_alpha'), 'returns': returns,
            'chained_nav_basis': 'OBSERVED_NONOVERLAPPING_WINDOWS_ONLY',
            'drawdown_basis': 'OBSERVED_PERIOD_ENDS_ONLY_NOT_DAILY',
            'warnings': ['Coverage is limited to provided verified windows; no five-year completeness claim.',
                         'Missing periods are not zero-return observations.']}
