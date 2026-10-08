"""Synthetic, offline policy invariants (never historical stock facts)."""
from datetime import date, datetime, timedelta, timezone
import pytest
from finagent.contracts import *
from finagent.quant import freeze_signal, screen_candidates, valuate, target_from_assumptions

NOW = datetime(2025, 7, 1, 12, tzinfo=timezone.utc)

def research(ticker='NVDA', sector='Technology', *, eps=10, pit=PITStatus.VERIFIED, mode=Mode.DEMO):
    items = tuple(EvidenceItem(evidence_id=f'{ticker}-{field}', field=field, value=value,
        source_uri='synthetic://fixture', available_at=NOW-timedelta(days=1), content_hash=field,
        pit_status=pit) for field,value in [('earnings_per_share',eps),('revenue_growth',.2),('profit_margin',.3),('eps_revision',.1)])
    evidence = EvidenceSnapshot(snapshot_id=ticker, ticker=ticker, decision_at=NOW, mode=mode,
        items=items, content_hash=ticker, pit_status=pit)
    source=dict(ticker=ticker, source='SYNTHETIC', source_uri='synthetic://fixture',content_hash=ticker,
        pit_status=pit,mode=mode)
    market=tuple(MarketBar(**source,as_of=NOW-timedelta(days=d),available_at=NOW-timedelta(days=d),
        session=(NOW-timedelta(days=d)).date(),open=p,high=p,low=p,close=p) for d,p in [(120,80),(1,100)])
    financials=FinancialSnapshot(**source,as_of=NOW-timedelta(days=30),available_at=NOW-timedelta(days=20),
        period_end=date(2025,3,31),earnings_per_share=eps,revenue_growth=.2,profit_margin=.3,eps_revision=.1)
    return ResearchInput(ticker=ticker,sector=sector,decision_at=NOW,mode=mode,market=market,financials=financials,evidence=evidence)

def report(inp, persona=Persona.VALUE, target=190):
    ref=(f'{inp.ticker}-earnings_per_share',)
    return PersonaReport(persona=persona,ticker=inp.ticker,snapshot_id=inp.evidence.snapshot_id,
        assumptions=(Assumption(name='forward_eps',value=10,unit='USD/share',rationale='SYNTHETIC',evidence_ids=ref),
            Assumption(name='forward_pe',value=target/10,unit='multiple',rationale='SYNTHETIC',evidence_ids=ref)),
        evidence_ids=ref,target_price_candidate=target,rationale='SYNTHETIC',model_version='test-v1',prompt_version='test-v1')

def result(inp, score=1):
    val=valuate(inp,())
    return ResearchResult(ticker=inp.ticker,sector=inp.sector,mode=inp.mode,snapshot=inp.evidence,reports=(),
        valuation=val,score=score,research_mode=ResearchMode.QUANT_ONLY)

def freeze(results, **kw):
    return freeze_signal(results,run_id='run',period='2025-H2',decision_at=NOW,frozen_at=NOW,
        mode=Mode.DEMO,config_hash='cfg',**kw)

def test_synthetic_nvda_fixed_weights_and_margin():
    inp=research()
    reports=tuple(report(inp,p,v) for p,v in [(Persona.VALUE,190),(Persona.GROWTH,240),(Persona.CONSERVATIVE,160)])
    val=valuate(inp,reports)
    assert val.target_12m == pytest.approx(199)
    assert val.entry_price == pytest.approx(159.2)
    assert val.assumptions_version == 'blend-50-30-20-v1'
    assert all(m.evidence_ids for m in val.methods)

def test_target_is_recomputed_and_invalid_link_abstains():
    inp=research()
    bad=report(inp).model_copy(update={'target_price_candidate':999})
    assert valuate(inp,(bad,)).target_12m is None
    bad=report(inp).model_copy(update={'assumptions':(Assumption(name='forward_eps',value=10,unit='USD/share',rationale='ungrounded'),)})
    assert valuate(inp,(bad,)).target_12m is None

def test_single_quant_and_multi_are_distinct_and_negative_eps_guarded():
    inp=research()
    single=valuate(inp,(report(inp),))
    quant=valuate(inp,())
    assert single.assumptions_version == 'single-persona-v1'
    assert quant.assumptions_version == 'quant-pe-v1'
    assert quant.target_12m is not None
    assert valuate(inp,(report(inp),report(inp,Persona.GROWTH,240))).target_12m is None
    assert valuate(research(eps=-2),()).target_12m is None

def test_currency_basis_unknown_assumption_and_future_evidence_are_rejected():
    inp=research()
    for change in ({'currency':'EUR'},{'corporate_action_basis':'ADJUSTED'},{'snapshot_id':'wrong'}):
        assert valuate(inp,(report(inp).model_copy(update=change),)).target_12m is None
    with pytest.raises(ValueError):
        target_from_assumptions((Assumption(name='forward_eps',value=-1,unit='USD/share',rationale='test'),
            Assumption(name='forward_pe',value=20,unit='multiple',rationale='test')))

def test_dcf_equation_guards_terminal_growth():
    assumptions=tuple(Assumption(name=n,value=v,unit=u,rationale='test') for n,v,u in [
        ('fcf_per_share',5,'USD/share'),('fcf_growth',.05,'ratio'),('discount_rate',.1,'ratio'),('terminal_growth',.02,'ratio')])
    expected=sum(5*1.05**year/1.1**year for year in range(1,6))+5*1.05**5*1.02/(.1-.02)/1.1**5
    assert target_from_assumptions(assumptions)==pytest.approx(expected)
    with pytest.raises(ValueError):
        target_from_assumptions((*assumptions[:-1],assumptions[-1].model_copy(update={'value':.1})))

def test_screen_deterministic_missing_and_limit30():
    inputs=[research(f'S{i}',f'Sector{i%4}') for i in range(35)]
    a=screen_candidates(inputs,limit=100)
    b=screen_candidates(list(reversed(inputs)),limit=100)
    assert a==b and len(a)==30
    assert {f.name for f in a[0].factors}=={'Value','Growth','Profitability','Momentum','EPS revisions'}
    missing=research().model_copy(update={'financials':research().financials.model_copy(update={'eps_revision':None})})
    score=screen_candidates((missing,))[0]
    assert next(f for f in score.factors if f.name=='EPS revisions').missing_reason
    with pytest.raises(ValueError):
        screen_candidates((research(),research()))

def test_stale_and_unverified_real_excluded_demo_warns():
    inp=research()
    stale=inp.model_copy(update={'financials':inp.financials.model_copy(update={'available_at':NOW-timedelta(days=190)})})
    assert screen_candidates((stale,))==()
    assert valuate(stale,()).target_12m is None
    assert screen_candidates((research(mode=Mode.REAL,pit=PITStatus.UNVERIFIED),))==()
    demo=research(pit=PITStatus.UNVERIFIED)
    assert screen_candidates((demo,))[0].warnings
    assert valuate(demo,()).target_12m is not None

def test_exact10_diversification_and_shortfall_no_padding():
    results=[result(research(f'S{i}',f'Sector{i%3}'),20-i) for i in range(12)]
    signal=freeze(results)
    assert len(signal.picks)==10 and all(p.weight==.1 for p in signal.picks)
    assert freeze(results[:9]) is None
    assert freeze([result(research(f'S{i}'),i) for i in range(12)]) is None
    with pytest.raises(ValueError):
        freeze([*results,results[0]])
    assert signal.signal_id==freeze(list(reversed(results))).signal_id

def test_freeze_rejects_post_decision_snapshot_and_mixed_modes():
    results=[result(research(f'S{i}',f'Sector{i%3}')) for i in range(10)]
    results[0]=results[0].model_copy(update={'snapshot':results[0].snapshot.model_copy(update={'decision_at':NOW+timedelta(days=1)})})
    assert freeze(results) is None

def test_quant_growth_needs_ledger_fact_or_declared_zero_growth_fallback():
    inp=research()
    evidence=inp.evidence.model_copy(update={'items':tuple(e for e in inp.evidence.items if e.field!='revenue_growth')})
    value=valuate(inp.model_copy(update={'evidence':evidence}),())
    assert value.target_12m==pytest.approx(200)
    assert any('ZERO_GROWTH' in explanation for explanation in value.explanations)


def test_spy_etf_operating_metrics_are_not_stock_candidates():
    inp=research('SPY','ETF Benchmark')
    inp=inp.model_copy(update={'financials':inp.financials.model_copy(update={'earnings_per_share':None,
        'revenue_growth':None,'profit_margin':None,'eps_revision':None})})
    assert screen_candidates((inp,))==()
