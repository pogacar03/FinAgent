"""Deterministic PIT screening, guarded valuation, and immutable exact-ten signals.

All equations here are original narrow implementations; no framework source is
vendored. Versioned policy and assumption units are documented in QUANT_POLICY.
"""
from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from datetime import datetime, timedelta

from .contracts import (
    Assumption, FactorScore, FrozenSignal, MethodValuation, Mode, Persona,
    PersonaReport, PITStatus, RankedPick, ResearchInput, ResearchResult,
    ScreenedCandidate, ValuationResult, stable_hash,
)

FACTOR_VERSION = 'five-factor-rank-v1'
FACTOR_WEIGHTS = {'Value': .30, 'Growth': .25, 'Profitability': .20,
                  'Momentum': .15, 'EPS revisions': .10}
PERSONA_WEIGHTS = {Persona.VALUE: .5, Persona.GROWTH: .3, Persona.CONSERVATIVE: .2}


def _input_reasons(inp: ResearchInput) -> tuple[str, ...]:
    reasons: list[str] = []
    records = (*inp.market, inp.financials)
    if not inp.market:
        return ('MISSING_MARKET',)
    if any(r.available_at > inp.decision_at or r.as_of > inp.decision_at for r in records):
        reasons.append('FUTURE_DATA')
    if inp.evidence.decision_at != inp.decision_at or any(
        e.available_at > inp.decision_at for e in inp.evidence.items
    ):
        reasons.append('FUTURE_EVIDENCE')
    if any(r.currency != 'USD' or r.corporate_action_basis != 'RAW_WITH_ACTIONS' for r in records):
        reasons.append('INCOMPARABLE_CURRENCY_OR_BASIS')
    if inp.decision_at - inp.financials.available_at > timedelta(days=180):
        reasons.append('STALE_FINANCIALS')
    if (inp.decision_at.date() - inp.financials.period_end).days > 550:
        reasons.append('STALE_FINANCIAL_PERIOD')
    if inp.decision_at - max(r.as_of for r in inp.market) > timedelta(days=10):
        reasons.append('STALE_MARKET')
    if inp.mode == Mode.REAL and (
        inp.evidence.pit_status != PITStatus.VERIFIED
        or any(r.pit_status != PITStatus.VERIFIED for r in records)
        or any(e.pit_status != PITStatus.VERIFIED for e in inp.evidence.items)
    ):
        reasons.append('PIT_UNVERIFIED')
    return tuple(reasons)


def _raw_factors(inp: ResearchInput) -> tuple[FactorScore, ...]:
    market = sorted(inp.market, key=lambda b: (b.as_of, b.session))
    fin = inp.financials
    eps = fin.earnings_per_share
    momentum = None
    if (market[-1].session - market[0].session).days >= 90:
        momentum = market[-1].close / market[0].close - 1
    values = {'Value': eps / market[-1].close if eps is not None and eps > 0 else None,
              'Growth': fin.revenue_growth, 'Profitability': fin.profit_margin,
              'Momentum': momentum, 'EPS revisions': fin.eps_revision}
    reasons = {'Value': 'MISSING_OR_NONPOSITIVE_EPS', 'Growth': 'MISSING_REVENUE_GROWTH',
               'Profitability': 'MISSING_PROFIT_MARGIN', 'Momentum': 'MISSING_90_DAY_PRICE_HISTORY',
               'EPS revisions': 'MISSING_PIT_EPS_REVISION'}
    return tuple(FactorScore(name=name, value=value,
                            missing_reason=reasons[name] if value is None else None)
                 for name, value in values.items())


def screen_candidates(inputs: Sequence[ResearchInput], limit: int = 30) -> tuple[ScreenedCandidate, ...]:
    """Percentile rank five factors; missing factors get zero without reweighting."""
    if len({i.ticker for i in inputs}) != len(inputs):
        raise ValueError('duplicate research ticker')
    if limit < 0:
        raise ValueError('limit must be nonnegative')
    if len({(i.mode, i.decision_at) for i in inputs}) > 1:
        raise ValueError('screen requires the same mode and decision cutoff')
    eligible: list[tuple[ResearchInput, tuple[FactorScore, ...]]] = []
    for inp in inputs:
        if _input_reasons(inp):
            continue
        factors = _raw_factors(inp)
        if sum(f.value is not None for f in factors) >= 3:
            eligible.append((inp, factors))
    distributions = {name: sorted(f.value for _, factors in eligible for f in factors
                                 if f.name == name and f.value is not None)
                     for name in FACTOR_WEIGHTS}
    candidates: list[ScreenedCandidate] = []
    for inp, factors in eligible:
        score = 0.0
        for factor in factors:
            if factor.value is None:
                continue
            values = distributions[factor.name]
            # Midrank percentile avoids ticker/input ordering affecting tied factors.
            below = sum(v < factor.value for v in values)
            equal = sum(v == factor.value for v in values)
            percentile = (below + (equal - 1) / 2) / (len(values) - 1) if len(values) > 1 else .5
            score += FACTOR_WEIGHTS[factor.name] * percentile
        warnings = [FACTOR_VERSION]
        if next(f for f in factors if f.name == 'Momentum').value is not None:
            warnings.append('MOMENTUM_RAW_PRICE_PROXY_NOT_ACTION_ADJUSTED_TOTAL_RETURN')
        if inp.mode == Mode.DEMO:
            warnings.append('SYNTHETIC_DEMO_NOT_HISTORICAL_EVIDENCE')
        warnings.extend(f.missing_reason for f in factors if f.missing_reason)
        candidates.append(ScreenedCandidate(ticker=inp.ticker, sector=inp.sector, score=score,
                                            factors=factors, warnings=tuple(warnings)))
    return tuple(sorted(candidates, key=lambda c: (-c.score, c.ticker))[:min(30, limit)])


def target_from_assumptions(assumptions: Sequence[Assumption]) -> float:
    """Compute a narrow P/E or five-year DCF forecast; validate names and units.

    Citation validation requires a ResearchInput and is done by `valuate`.
    This arithmetic helper intentionally does not claim forecasts are facts.
    """
    values = {a.name: a for a in assumptions}
    if len(values) != len(assumptions):
        raise ValueError('duplicate assumption name')
    pe_names = {'forward_eps', 'forward_pe'}
    dcf_names = {'fcf_per_share', 'fcf_growth', 'discount_rate', 'terminal_growth'}
    if set(values) == pe_names:
        eps, pe = values['forward_eps'], values['forward_pe']
        if eps.unit != 'USD/share' or pe.unit != 'multiple':
            raise ValueError('P/E assumption units must be USD/share and multiple')
        if eps.value <= 0 or not 0 < pe.value <= 100:
            raise ValueError('positive EPS and P/E in (0,100] required')
        target = eps.value * pe.value
    elif set(values) == dcf_names:
        fcf = values['fcf_per_share']
        growth, discount, terminal = (values[n] for n in ('fcf_growth', 'discount_rate', 'terminal_growth'))
        if fcf.unit != 'USD/share' or any(a.unit != 'ratio' for a in (growth, discount, terminal)):
            raise ValueError('DCF assumption units must be USD/share and ratio')
        if fcf.value <= 0 or not -.5 <= growth.value <= .5:
            raise ValueError('positive FCF and growth in [-.5,.5] required')
        if not 0 < discount.value <= .5 or not -.1 <= terminal.value < discount.value:
            raise ValueError('DCF requires discount > terminal growth')
        target = sum(fcf.value * (1 + growth.value) ** y / (1 + discount.value) ** y for y in range(1, 6))
        target += (fcf.value * (1 + growth.value) ** 5 * (1 + terminal.value)
                   / (discount.value - terminal.value) / (1 + discount.value) ** 5)
    else:
        raise ValueError('use exactly forward_eps/forward_pe or the four DCF assumptions')
    if not math.isfinite(target) or target <= 0:
        raise ValueError('valuation must be finite and positive')
    return target


def valuate(input: ResearchInput, reports: Sequence[PersonaReport], safety_margin: float = .2) -> ValuationResult:
    if not 0 <= safety_margin < 1:
        raise ValueError('safety_margin must be in [0,1)')
    common = dict(ticker=input.ticker, snapshot_id=input.evidence.snapshot_id, mode=input.mode,
                  pit_status=input.evidence.pit_status, safety_margin=safety_margin)
    warnings = ['Forecast assumptions are subjective; evidence links establish inputs, not forecast truth.']
    if input.mode == Mode.DEMO:
        warnings.append('SYNTHETIC_DEMO: illustrative values are not historical stock facts.')
    def abstain(reason: str) -> ValuationResult:
        return ValuationResult(**common, abstain_reason=reason, explanations=tuple(warnings))
    reasons = _input_reasons(input)
    if reasons:
        return abstain(','.join(reasons))
    facts = {e.evidence_id: e for e in input.evidence.items if e.kind == 'FACT'}
    methods: list[MethodValuation] = []
    if not reports:
        eps = input.financials.earnings_per_share
        eps_facts = tuple(e.evidence_id for e in facts.values() if e.field == 'earnings_per_share'
                          and isinstance(e.value, (int, float)) and eps is not None
                          and math.isclose(float(e.value), eps, rel_tol=1e-8))
        if eps is None or eps <= 0 or not eps_facts:
            return abstain('QUANT_REQUIRES_GROUNDED_POSITIVE_EPS')
        growth = input.financials.revenue_growth
        growth_facts = tuple(e.evidence_id for e in facts.values() if e.field == 'revenue_growth'
                             and isinstance(e.value, (int, float)) and growth is not None
                             and math.isclose(float(e.value), growth, rel_tol=1e-8))
        if growth is None or not growth_facts:
            growth = 0
            warnings.append('QUANT_ZERO_GROWTH_POLICY_FALLBACK: no matching growth FACT in ledger.')
        else:
            growth = max(-.2, min(.3, growth))
        forward_refs = tuple(sorted(set(eps_facts + growth_facts)))
        # Explicit baseline assumptions, not a fabricated analyst consensus.
        assumptions = (Assumption(name='forward_eps', value=eps * (1 + growth), unit='USD/share',
                                  rationale='quant-pe-v1: EPS grown by bounded reported revenue growth',
                                  evidence_ids=forward_refs),
                       Assumption(name='forward_pe', value=20, unit='multiple',
                                  rationale='quant-pe-v1 fixed policy multiple; not market consensus', evidence_ids=eps_facts))
        target = target_from_assumptions(assumptions)
        methods.append(MethodValuation(method='QUANT_PE_POLICY', value=target,
                                       assumptions=assumptions, evidence_ids=forward_refs))
        version = 'quant-pe-v1'
    else:
        personas = [r.persona for r in reports]
        if len(set(personas)) != len(personas) or len(reports) not in (1, 3):
            return abstain('REQUIRES_ONE_PERSONA_OR_THREE_DISTINCT_PERSONAS')
        values: dict[Persona, float] = {}
        for report in reports:
            if (report.ticker != input.ticker or report.snapshot_id != input.evidence.snapshot_id
                or report.currency != 'USD' or report.corporate_action_basis != 'RAW_WITH_ACTIONS'
                or report.horizon_months != 12):
                return abstain('INCOMPARABLE_PERSONA_FORECAST')
            if report.abstain_reason:
                return abstain(f'{report.persona.value}_ABSTAINED:{report.abstain_reason}')
            if not report.evidence_ids or not set(report.evidence_ids) <= set(facts):
                return abstain('INVALID_FACT_EVIDENCE_LINK')
            if any(not a.evidence_ids or not set(a.evidence_ids) <= set(facts) for a in report.assumptions):
                return abstain('UNGROUNDED_ASSUMPTION')
            try:
                computed = target_from_assumptions(report.assumptions)
            except ValueError as exc:
                return abstain(f'INVALID_ASSUMPTIONS:{exc}')
            if report.target_price_candidate is None or not math.isclose(
                computed, report.target_price_candidate, abs_tol=.011, rel_tol=1e-8
            ):
                return abstain('PERSONA_TARGET_DOES_NOT_MATCH_ASSUMPTIONS')
            values[report.persona] = computed
            methods.append(MethodValuation(method=f'{report.persona.value}_' +
                                           ('FORWARD_PE' if any(a.name == 'forward_pe' for a in report.assumptions) else 'DCF'),
                                           value=computed, assumptions=report.assumptions,
                                           evidence_ids=tuple(sorted(set(report.evidence_ids) |
                                               {e for a in report.assumptions for e in a.evidence_ids}))))
        if len(reports) == 3:
            target = sum(values[persona] * weight for persona, weight in PERSONA_WEIGHTS.items())
            version = 'blend-50-30-20-v1'
        else:
            target = next(iter(values.values()))
            version = 'single-persona-v1'
    return ValuationResult(**common, target_12m=round(target, 6), entry_price=round(target * (1 - safety_margin), 6),
                           # Fair value is not silently equated to a 12-month forecast.
                           methods=tuple(sorted(methods, key=lambda m: m.method)), explanations=tuple(warnings),
                           assumptions_version=version)


def freeze_signal(results: Sequence[ResearchResult], *, run_id: str, period: str,
                  decision_at: datetime, frozen_at: datetime, mode: Mode,
                  config_hash: str, max_per_sector: int = 4) -> FrozenSignal | None:
    if len({r.ticker for r in results}) != len(results):
        raise ValueError('duplicate research result ticker')
    if not 1 <= max_per_sector <= 10:
        raise ValueError('max_per_sector must be in [1,10]')
    if frozen_at < decision_at:
        raise ValueError('freeze cannot precede decision')
    admissible = []
    for result in results:
        snapshot, valuation = result.snapshot, result.valuation
        if not result.eligible or result.exclusion_reasons or valuation.target_12m is None:
            continue
        if result.mode != mode or snapshot.decision_at != decision_at or valuation.mode != mode:
            continue
        if any(item.available_at > decision_at for item in snapshot.items):
            continue
        if mode == Mode.REAL and (snapshot.pit_status != PITStatus.VERIFIED
                                 or valuation.pit_status != PITStatus.VERIFIED
                                 or any(i.pit_status != PITStatus.VERIFIED for i in snapshot.items)):
            continue
        admissible.append(result)
    # A single frozen experiment cannot silently mix ablations or configurations.
    if len({(r.research_mode, stable_hash(r.versions)) for r in admissible}) > 1:
        raise ValueError('mixed research modes or model versions')
    counts: Counter[str] = Counter()
    chosen: list[ResearchResult] = []
    for result in sorted(admissible, key=lambda r: (-r.score, r.ticker)):
        if counts[result.sector] >= max_per_sector:
            continue
        chosen.append(result)
        counts[result.sector] += 1
        if len(chosen) == 10:
            break
    if len(chosen) != 10:
        return None
    picks = tuple(RankedPick(rank=rank, ticker=r.ticker, sector=r.sector, weight=.1, score=r.score,
                            target_12m=r.valuation.target_12m, entry_price=r.valuation.entry_price,
                            snapshot_id=r.snapshot.snapshot_id, snapshot_hash=r.snapshot.content_hash,
                            rationale='; '.join(report.rationale for report in r.reports) or 'quant-pe-v1 baseline')
                  for rank, r in enumerate(chosen, 1))
    pit = PITStatus.VERIFIED if all(r.snapshot.pit_status == PITStatus.VERIFIED for r in chosen) else PITStatus.UNVERIFIED
    payload = dict(run_id=run_id, period=period, decision_at=decision_at, frozen_at=frozen_at,
                   mode=mode, pit_status=pit, picks=picks, versions=chosen[0].versions, config_hash=config_hash)
    return FrozenSignal(signal_id='sig_' + stable_hash(payload)[:24], **payload,
                        warnings=('SYNTHETIC_DEMO_NOT_VALIDATED_HISTORY',) if mode == Mode.DEMO else ())
