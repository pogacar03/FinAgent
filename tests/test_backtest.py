"""SYNTHETIC frozen execution fixtures, independent from any LLM/provider API."""
from datetime import date, datetime, timedelta, timezone
import pytest
from finagent.contracts import *
from finagent.backtest import run_backtest, aggregate_backtests

UTC=timezone.utc
DECISION=datetime(2025,7,1,12,tzinfo=UTC)
ASOF=datetime(2026,2,1,tzinfo=UTC)

def signal(frozen=DECISION):
    picks=tuple(RankedPick(rank=i+1,ticker=f'S{i}',sector=f'Sector{i%3}',weight=.1,score=1,
        target_12m=120,entry_price=96,snapshot_id=f'S{i}',snapshot_hash=f'h{i}',rationale='SYNTHETIC') for i in range(10))
    return FrozenSignal(signal_id='sig',run_id='run',period='2025-H2',decision_at=DECISION,frozen_at=frozen,
        mode=Mode.DEMO,pit_status=PITStatus.UNVERIFIED,picks=picks,config_hash='cfg')

def bar(ticker,session,price=100):
    at=datetime.combine(session,datetime.min.time(),UTC)+timedelta(hours=21)
    return MarketBar(ticker=ticker,session=session,as_of=at,available_at=at,source='SYNTHETIC',
        source_uri='synthetic://fixture',content_hash=f'{ticker}-{session}-{price}',mode=Mode.DEMO,
        pit_status=PITStatus.UNVERIFIED,open=price,high=price+10,low=price-10,close=price)

def action(ticker,session,kind,value):
    return CorporateAction(ticker=ticker,session=session,kind=kind,value=value,source='SYNTHETIC',
        source_uri='synthetic://fixture',available_at=datetime(2025,6,1,tzinfo=UTC))

class Provider:
    def __init__(self):
        self.sessions=(date(2025,7,1),date(2025,7,2),date(2025,7,3),date(2025,10,1),date(2026,1,2),date(2026,1,5))
        self.data={t:tuple(bar(t,d,100 if d.year==2025 else 110) for d in self.sessions)
                   for t in [*(f'S{i}' for i in range(10)),*(f'A{i}' for i in range(10)),'SPY']}
        self.events={}
        self.complete=True
    def bars(self,ticker,start,end):
        return tuple(b for b in self.data.get(ticker,()) if start<=b.session<=end)
    def actions(self,ticker,start,end):
        return tuple(a for a in self.events.get(ticker,()) if start<=a.session<=end)
    def actions_complete(self,ticker,start,end):
        return self.complete

def benchmark(published=datetime(2025,7,1,12,tzinfo=UTC),status=PITStatus.VERIFIED):
    return BenchmarkList(period='2025-H2',tickers=tuple(f'A{i}' for i in range(10)),published_at=published,
        source_uri='https://example.com/SYNTHETIC',content_hash='sa',verification_status=status,
        mode=Mode.DEMO,verification_note='SYNTHETIC fixture, not actual Seeking Alpha list')

def run(provider=None,**kw):
    return run_backtest(signal(),provider or Provider(),backtest_id='bt',as_of=ASOF,**kw)

def test_primary_same_common_open_and_calendar_months():
    result=run(benchmark=benchmark())
    assert result.status==BacktestStatus.COMPLETED
    assert result.entry_session==date(2025,7,1)
    assert result.exit_session==date(2026,1,2)
    assert result.finagent.total_return==pytest.approx(.1)
    assert result.seeking_alpha.total_return==pytest.approx(.1)
    assert result.excess_vs_sa_pp==pytest.approx(0)
    assert {(p.entry_session,p.exit_session) for p in (result.finagent,result.spy,result.seeking_alpha)}=={(date(2025,7,1),date(2026,1,2))}

def test_intraday_freeze_does_not_retroactively_buy_today_open():
    sig=signal(datetime(2025,7,1,15,tzinfo=UTC)) # 11:00 New York; open is 13:30 UTC
    result=run_backtest(sig,Provider(),backtest_id='bt',as_of=ASOF)
    assert result.entry_session==date(2025,7,2)
    assert result.exit_session==date(2026,1,2)
    result=run(benchmark=benchmark(datetime(2025,7,2,14,tzinfo=UTC)))
    assert result.entry_session==date(2025,7,3)
    assert result.exit_session==date(2026,1,5)

def test_at_exact_open_still_next_session():
    result=run_backtest(signal(datetime(2025,7,1,13,30,tzinfo=UTC)),Provider(),backtest_id='bt',as_of=ASOF)
    assert result.entry_session==date(2025,7,2)

def test_absent_or_unverified_sa_is_explicit_never_synthesized():
    result=run()
    assert result.status==BacktestStatus.COMPLETED
    assert result.seeking_alpha_status=='UNAVAILABLE'
    assert result.seeking_alpha is None and result.excess_vs_sa_pp is None
    result=run(benchmark=benchmark(datetime(2025,8,1,tzinfo=UTC),PITStatus.UNVERIFIED))
    assert result.seeking_alpha_status=='UNVERIFIED'
    assert result.seeking_alpha is None and result.entry_session==date(2025,7,1)

def test_maturity_pending_has_no_realized_results():
    result=run_backtest(signal(),Provider(),backtest_id='bt',as_of=datetime(2025,12,31,tzinfo=UTC))
    assert result.status==BacktestStatus.PENDING
    assert result.finagent is None and result.excess_vs_spy_pp is None

def test_missing_entry_exit_or_intermediate_panel_fails_instead_of_shifting():
    for missing in (date(2025,7,1),date(2026,1,2),date(2025,10,1)):
        provider=Provider()
        provider.data['S0']=tuple(b for b in provider.data['S0'] if b.session!=missing)
        result=run(provider)
        assert result.status==BacktestStatus.VALIDATION_FAILED
        assert result.finagent is None

def test_missing_action_coverage_fails_even_if_no_actions_returned():
    provider=Provider(); provider.complete=False
    result=run(provider)
    assert result.status==BacktestStatus.VALIDATION_FAILED
    assert 'ACTION_COVERAGE' in result.reason

def test_split_then_dividend_entry_excluded_exit_included():
    provider=Provider()
    # Buy July 1 AFTER its ex-date action. Hold October and exit Jan 2.
    provider.events['S0']=(action('S0',date(2025,7,1),'DIVIDEND',100),
        action('S0',date(2025,10,1),'DIVIDEND',2),
        action('S0',date(2025,10,1),'SPLIT',2),
        action('S0',date(2026,1,2),'DIVIDEND',1),
        action('S0',date(2026,1,5),'DIVIDEND',999))
    provider.data['S0']=tuple(bar('S0',d,55 if d.year==2026 else 100) for d in provider.sessions)
    result=run(provider)
    holding=result.finagent.holdings[0]
    assert holding.split_factor==2
    assert holding.dividends==6 # two post-split shares × (2+1)
    assert holding.total_return==pytest.approx(.16)
    assert result.finagent.total_return==pytest.approx(.106)

def test_costs_apply_to_both_sides_and_dividends_are_cash_not_reinvested():
    result=run(transaction_cost_bps=10,slippage_bps=20)
    expected=110*.998*.999/(100*1.002*1.001)-1
    assert result.finagent.total_return==pytest.approx(expected)
    assert result.spy.total_return==pytest.approx(expected)

def test_adjusted_bars_wrong_mode_future_data_and_duplicate_actions_rejected():
    for change in ({'corporate_action_basis':'ADJUSTED'},{'mode':Mode.REAL},{'available_at':ASOF+timedelta(days=1)}):
        provider=Provider()
        provider.data['S0']=tuple(b.model_copy(update=change) for b in provider.data['S0'])
        assert run(provider).status==BacktestStatus.VALIDATION_FAILED
    provider=Provider(); event=action('S0',date(2025,10,1),'SPLIT',2)
    provider.events['S0']=(event,event)
    assert run(provider).status==BacktestStatus.VALIDATION_FAILED

def test_limit_nonfills_remain_cash_and_comparison_stays_separate():
    provider=Provider()
    provider.data['S0']=tuple(bar('S0',d,150) for d in provider.sessions)
    result=run(provider,policy='LIMIT_ENTRY')
    assert result.policy=='LIMIT_ENTRY' and result.cash_weight==pytest.approx(.1)
    assert result.finagent.holdings[0].filled is False
    assert result.finagent.holdings[0].total_return==0
    assert len(result.finagent.holdings)==10

def test_aggregation_truth_labels_coverage_and_nonoverlap_nav():
    complete=run()
    pending=complete.model_copy(update={'backtest_id':'pending','status':BacktestStatus.PENDING,
        'finagent':None,'spy':None,'seeking_alpha':None,'excess_vs_spy_pp':None})
    summary=aggregate_backtests((complete,pending))
    assert summary['valid_periods']==1 and summary['total_periods']==2
    assert summary['truth_label']=='SYNTHETIC_DEMO'
    assert summary['missing_periods']==['2025-H2']
    assert summary['chained_nav'][-1]['nav']==pytest.approx(1.1)
    assert summary['max_drawdown']==0

def test_unavailable_bar_after_exit_does_not_invalidate_mature_window():
    provider=Provider()
    provider.data['SPY']=(*provider.data['SPY'],bar('SPY',date(2026,1,30)))
    result=run_backtest(signal(),provider,backtest_id='bt',as_of=datetime(2026,1,30,15,tzinfo=UTC))
    assert result.status==BacktestStatus.COMPLETED
    assert result.exit_session==date(2026,1,2)

def test_winter_open_uses_new_york_dst_not_midnight_or_fixed_utc():
    provider=Provider()
    dates=(date(2025,11,3),date(2025,11,4),date(2026,5,4))
    provider.data={t:tuple(bar(t,d) for d in dates) for t in provider.data}
    result=run_backtest(signal(datetime(2025,11,3,14,tzinfo=UTC)),provider,backtest_id='bt',
        as_of=datetime(2026,6,1,tzinfo=UTC))
    assert result.entry_session==date(2025,11,3) # opens 14:30 UTC in November
    assert result.exit_session==date(2026,5,4)


def test_split_on_exit_open_and_dividend_apply_to_overnight_shares():
    provider=Provider()
    provider.events['S0']=(action('S0',date(2026,1,2),'DIVIDEND',1),action('S0',date(2026,1,2),'SPLIT',2))
    provider.data['S0']=tuple(bar('S0',d,55 if d.year==2026 else 100) for d in provider.sessions)
    holding=run(provider).finagent.holdings[0]
    assert holding.split_factor==2 and holding.dividends==2
    assert holding.total_return==pytest.approx(.12)

def test_limit_records_opportunity_cost_vs_same_picks_primary():
    result=run(policy='LIMIT_ENTRY')
    assert any('OPPORTUNITY_COST_VS_PRIMARY_PP=' in warning for warning in result.warnings)


def test_aggregation_empty_and_missing_sa_cannot_claim_truth_or_sa_nav():
    assert aggregate_backtests(())['truth_label']=='NO_RESULTS'
    summary=aggregate_backtests((run(),))
    assert summary['seeking_alpha_chained_nav'] is None
    assert summary['spy_chained_nav'][-1]['nav']==pytest.approx(1.1)
    assert summary['returns'][0]['finagent']==pytest.approx(.1)


def split_wait_provider(split_session=date(2025,10,1), *, fill_price=None):
    provider=Provider()
    provider.events['S0']=(action('S0',split_session,'SPLIT',2),)
    records=[]
    for session in provider.sessions:
        price=100 if session<split_session else 50
        if fill_price is not None and session==split_session:
            price=fill_price
        record=bar('S0',session,price)
        records.append(record.model_copy(update={'low':price*.99,'high':price*1.01}))
    provider.data['S0']=tuple(records)
    return provider


def test_waiting_limit_does_not_fill_only_because_two_for_one_split_halves_price():
    result=run(split_wait_provider(),policy='LIMIT_ENTRY')
    holding=result.finagent.holdings[0]
    assert result.status==BacktestStatus.COMPLETED
    assert not holding.filled and holding.total_return==0
    assert result.cash_weight==pytest.approx(.1)


def test_pending_limit_adjusts_fill_day_split_without_double_adjusting_bought_shares():
    provider=split_wait_provider(fill_price=46)
    provider.events['S0']=(*provider.events['S0'],action('S0',date(2025,10,1),'DIVIDEND',3),
        action('S0',date(2026,1,2),'DIVIDEND',1))
    holding=run(provider,policy='LIMIT_ENTRY').finagent.holdings[0]
    assert holding.filled and holding.entry_price==46
    assert holding.split_factor==1 and holding.dividends==1
    assert holding.total_return==pytest.approx(51/46-1)


def test_split_on_first_common_entry_day_adjusts_pending_limit_before_matching():
    holding=run(split_wait_provider(date(2025,7,1)),policy='LIMIT_ENTRY').finagent.holdings[0]
    assert not holding.filled


def test_split_between_decision_and_late_common_entry_adjusts_frozen_limit():
    provider=split_wait_provider(date(2025,7,2))
    dates=(*provider.sessions,date(2026,7,1))
    for ticker in provider.data:
        old={record.session:record for record in provider.data[ticker]}
        provider.data[ticker]=tuple(old.get(session) or bar(ticker,session,50 if ticker=='S0' else 110)
            for session in dates)
    result=run_backtest(signal(),provider,backtest_id='bt',as_of=datetime(2026,8,1,tzinfo=UTC),
        benchmark=benchmark(datetime(2025,7,3,14,tzinfo=UTC)),policy='LIMIT_ENTRY')
    assert result.status==BacktestStatus.COMPLETED and result.entry_session==date(2025,10,1)
    assert not result.finagent.holdings[0].filled


def test_waiting_limit_adjusts_reverse_split_and_keeps_post_fill_shares_one():
    provider=Provider()
    provider.events['S0']=(action('S0',date(2025,10,1),'SPLIT',.5),)
    provider.data['S0']=tuple(bar('S0',session,100 if session<date(2025,10,1) else
        180 if session==date(2025,10,1) else 200).model_copy(update={
            'low':99 if session<date(2025,10,1) else 178 if session==date(2025,10,1) else 198})
        for session in provider.sessions)
    holding=run(provider,policy='LIMIT_ENTRY').finagent.holdings[0]
    assert holding.filled and holding.entry_price==180 and holding.split_factor==1
    assert holding.total_return==pytest.approx(200/180-1)


def test_split_already_effective_before_decision_does_not_adjust_limit_twice():
    at=datetime(2025,7,1,14,tzinfo=UTC)
    sig=signal(at).model_copy(update={'decision_at':at})
    result=run_backtest(sig,split_wait_provider(date(2025,7,1)),backtest_id='bt',as_of=ASOF,policy='LIMIT_ENTRY')
    assert result.finagent.holdings[0].filled
    assert result.finagent.holdings[0].entry_price==50


def test_waiting_limit_uses_cumulative_split_product():
    provider=split_wait_provider(date(2025,7,2))
    provider.events['S0']=(*provider.events['S0'],action('S0',date(2025,10,1),'SPLIT',2))
    provider.data['S0']=tuple((record if record.session<date(2025,10,1) else
        bar('S0',record.session,25).model_copy(update={'low':24.75,'high':25.25}))
        for record in provider.data['S0'])
    assert not run(provider,policy='LIMIT_ENTRY').finagent.holdings[0].filled
