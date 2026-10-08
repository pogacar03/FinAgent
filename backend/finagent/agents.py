"""Native LangGraph research with independent, evidence-only persona contexts.

Checkpoint envelopes contain typed JSON data and controlled audit metadata only.
No raw prompts, credentials, provider error bodies, or persona messages are saved.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import random
import time
import weakref
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, TypedDict

import httpx
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from . import quant
from .contracts import (Assumption, Mode, Persona, PersonaReport, PITStatus,
                        ResearchInput, ResearchMode, ResearchResult, stable_hash)


class ResearchValidationError(ValueError):
    code = 'VALIDATION_FAILED'


class ResearchUnavailable(RuntimeError):
    code = 'UNAVAILABLE'
    unavailable = True


class TransientToolError(RuntimeError):
    code = 'TRANSIENT_PROVIDER_ERROR'


class LLMBudget:
    """One worker event loop's shared HTTP concurrency and start-rate gate."""
    def __init__(self, concurrency: int, min_interval: float):
        self.limits = (concurrency, min_interval)
        self.semaphore = asyncio.Semaphore(concurrency)
        self.start_lock = asyncio.Lock()
        self.last_start: float | None = None

    async def request(self, operation: Callable[[], Awaitable[Any]], context: PrivateContext) -> Any:
        loop = asyncio.get_running_loop()
        queued_at = loop.time()
        async with self.semaphore:
            async with self.start_lock:
                if self.last_start is not None:
                    delay = self.limits[1] - (loop.time() - self.last_start)
                    if delay > 0:
                        await asyncio.sleep(delay)
                self.last_start = loop.time()
                context.audit.append({'phase': 'Tool Execution', 'status': 'LLM_BUDGET_ADMITTED',
                                      'concurrency_limit': self.limits[0],
                                      'min_interval_seconds': self.limits[1],
                                      'budget_wait_ms': round((self.last_start - queued_at) * 1000)})
            # No suspension between releasing the rate lock and entering HTTP post.
            return await operation()


_LLM_BUDGETS: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def llm_budget() -> LLMBudget:
    """Validate limits and reuse a single budget across all stock/persona graphs."""
    try:
        concurrency = int(os.getenv('LLM_CONCURRENCY', '3'))
        interval = float(os.getenv('LLM_MIN_INTERVAL_SECONDS', '0.2'))
        if concurrency <= 0 or not math.isfinite(interval) or interval < 0:
            raise ValueError('invalid limits')
    except (ValueError, OverflowError):
        raise ResearchValidationError('INVALID_LLM_LIMITS') from None
    loop = asyncio.get_running_loop()
    # Semaphores may retain their bound loop; drop closed-loop budgets explicitly.
    for old_loop in list(_LLM_BUDGETS):
        if old_loop.is_closed():
            del _LLM_BUDGETS[old_loop]
    budget = _LLM_BUDGETS.get(loop)
    if budget is None:
        budget = LLMBudget(concurrency, interval)
        _LLM_BUDGETS[loop] = budget
    elif budget.limits != (concurrency, interval):
        raise ResearchValidationError('LLM_LIMITS_CHANGED_IN_ACTIVE_LOOP')
    return budget


@dataclass
class PrivateContext:
    """One invocation's private budget/history; never shared with another role."""
    persona: Persona
    messages: list[dict[str, str]] = field(default_factory=list)
    tool_calls: int = 0
    max_calls: int = 3
    audit: list[dict[str, Any]] = field(default_factory=list)


class GraphState(TypedDict, total=False):
    input: dict[str, Any]
    report_value: dict[str, Any]
    report_growth: dict[str, Any]
    report_conservative: dict[str, Any]
    audit_value: list[dict[str, Any]]
    audit_growth: list[dict[str, Any]]
    audit_conservative: list[dict[str, Any]]
    audit_validation: list[dict[str, Any]]
    review_needed: bool
    review_rounds: int
    result: dict[str, Any]


_KEYS = {Persona.VALUE: 'value', Persona.GROWTH: 'growth', Persona.CONSERVATIVE: 'conservative'}
Generator = Callable[[ResearchInput, Persona, PrivateContext, dict[str, Any] | None, bool], Awaitable[PersonaReport]]


async def bounded_tool(context: PrivateContext, operation: Callable[[], Awaitable[Any]],
                       *, timeout: float = 20, attempts: int = 3) -> Any:
    """Retry only explicit transient/timeouts; cap total calls per context at three."""
    started = time.monotonic()
    for attempt in range(min(max(attempts, 1), 3)):
        if context.tool_calls >= context.max_calls:
            raise ResearchUnavailable('PERSONA_TOOL_BUDGET_EXHAUSTED')
        context.tool_calls += 1
        try:
            result = await asyncio.wait_for(operation(), timeout=timeout)
            context.audit.append({'phase': 'Tool Execution', 'attempt': attempt + 1,
                                  'status': 'OK', 'latency_ms': round((time.monotonic()-started)*1000)})
            return result
        except (TransientToolError, asyncio.TimeoutError) as exc:
            context.audit.append({'phase': 'Tool Execution', 'attempt': attempt + 1,
                                  'status': 'TRANSIENT', 'error_code': type(exc).__name__})
            if attempt + 1 >= min(max(attempts, 1), 3):
                raise TransientToolError('PERSONA_TRANSIENT_RETRIES_EXHAUSTED') from None
            await asyncio.sleep(min(.05 * 2**attempt + random.uniform(0, .01), .25))
        except (ValueError, ResearchUnavailable):
            context.audit.append({'phase': 'Evidence Verification', 'attempt': attempt + 1,
                                  'status': 'TERMINAL_VALIDATION'})
            raise
    raise TransientToolError('PERSONA_TRANSIENT_RETRIES_EXHAUSTED')


def _validate_input(inp: ResearchInput) -> None:
    records = (*inp.market, inp.financials)
    if any(r.currency != 'USD' or r.corporate_action_basis != 'RAW_WITH_ACTIONS' for r in records):
        raise ResearchValidationError('INCOMPARABLE_CURRENCY_OR_BASIS')
    if any(r.as_of > inp.decision_at or r.available_at > inp.decision_at for r in records):
        raise ResearchValidationError('FUTURE_DATA')
    if inp.mode == Mode.REAL and (inp.evidence.pit_status != PITStatus.VERIFIED or
            any(r.pit_status != PITStatus.VERIFIED for r in records) or
            any(e.pit_status != PITStatus.VERIFIED for e in inp.evidence.items)):
        raise ResearchValidationError('REAL_REQUIRES_PIT_VERIFIED')


def validate_report(inp: ResearchInput, report: PersonaReport) -> PersonaReport:
    """Validate all citations and recompute targets, ignoring model arithmetic."""
    if (report.ticker != inp.ticker or report.snapshot_id != inp.evidence.snapshot_id or
        report.currency != 'USD' or report.corporate_action_basis != 'RAW_WITH_ACTIONS'):
        raise ResearchValidationError('PERSONA_SNAPSHOT_OR_BASIS_MISMATCH')
    evidence = {e.evidence_id: e for e in inp.evidence.items}
    if not set(report.evidence_ids) <= evidence.keys() or any(
            evidence[eid].kind != 'FACT' for eid in report.evidence_ids if eid in evidence):
        raise ResearchValidationError('UNKNOWN_EVIDENCE_REFERENCE')
    for assumption in report.assumptions:
        if not assumption.evidence_ids or any(eid not in evidence or evidence[eid].kind != 'FACT'
                                              for eid in assumption.evidence_ids):
            raise ResearchValidationError('ASSUMPTION_REQUIRES_FACT_CITATION')
    if report.abstain_reason:
        return report
    try:
        target = quant.target_from_assumptions(report.assumptions)
    except ValueError:
        raise ResearchValidationError('INVALID_FORECAST_ASSUMPTIONS') from None
    return report.model_copy(update={'target_price_candidate': target})


def _abstention(inp: ResearchInput, persona: Persona, reason: str, model: str) -> PersonaReport:
    return PersonaReport(persona=persona, ticker=inp.ticker, snapshot_id=inp.evidence.snapshot_id,
                         abstain_reason=reason, rationale=reason, risk_flags=(reason,),
                         model_version=model, prompt_version=inp.versions.prompt)


async def demo_generator(inp: ResearchInput, persona: Persona, context: PrivateContext,
                         review: dict[str, Any] | None = None, combined_skills: bool = False) -> PersonaReport:
    """SYNTHETIC assumption generator; never represented as an LLM."""
    facts = {e.field: e for e in inp.evidence.items if e.kind == 'FACT'}
    eps_fact = facts.get('earnings_per_share')
    growth_fact = facts.get('revenue_growth')
    if eps_fact is None or not isinstance(eps_fact.value, (int, float)) or eps_fact.value <= 0:
        return _abstention(inp, persona, 'MISSING_POSITIVE_EPS_FACT', 'deterministic-demo-v1')
    growth = float(growth_fact.value) if growth_fact and isinstance(growth_fact.value, (int, float)) else 0
    growth = max(-.2, min(growth, .5))
    forward_eps = float(eps_fact.value) * (1 + growth)
    multiple = {Persona.VALUE: 20., Persona.GROWTH: 26., Persona.CONSERVATIVE: 16.}[persona]
    if inp.ticker == 'NVDA' and not combined_skills:
        # Declared illustration: multiple is an assumption, never a market fact.
        multiple = {Persona.VALUE: 190., Persona.GROWTH: 240., Persona.CONSERVATIVE: 160.}[persona] / forward_eps
    if combined_skills:
        multiple = 21.
    ids = (eps_fact.evidence_id,) + ((growth_fact.evidence_id,) if growth_fact else ())
    assumptions = (
        Assumption(name='forward_eps', value=forward_eps, unit='USD/share', evidence_ids=ids,
                   rationale='SYNTHETIC: positive source EPS times 1 + source growth clipped to [-20%, 50%].'),
        Assumption(name='forward_pe', value=multiple, unit='multiple', evidence_ids=(eps_fact.evidence_id,),
                   rationale='SYNTHETIC declared illustrative multiple; subjective, not observed market consensus.'),
    )
    context.messages.append({'role': 'assistant', 'content': 'SYNTHETIC assumption generation complete'})
    return PersonaReport(persona=persona, ticker=inp.ticker, snapshot_id=inp.evidence.snapshot_id,
                         assumptions=assumptions, evidence_ids=ids,
                         target_price_candidate=quant.target_from_assumptions(assumptions),
                         rationale='SYNTHETIC offline assumption generator' +
                                   (' combining value, growth and conservative skills.' if combined_skills else '.'),
                         risk_flags=('SYNTHETIC', 'SUBJECTIVE_MULTIPLE') +
                                    (('UNRESOLVED_DISAGREEMENT',) if review else ()),
                         model_version='deterministic-demo-v1', prompt_version=inp.versions.prompt)


async def real_generator(inp: ResearchInput, persona: Persona, context: PrivateContext,
                         review: dict[str, Any] | None = None, combined_skills: bool = False) -> PersonaReport:
    key, model = os.getenv('LLM_API_KEY'), os.getenv('LLM_MODEL')
    if not key or not model:
        return _abstention(inp, persona, 'UNAVAILABLE_LLM_CONFIGURATION', 'unavailable')
    # Anonymous instrument ID avoids ticker/history cues. Local provenance stays local.
    aliases = {e.evidence_id: f'evidence_{i}' for i, e in enumerate(inp.evidence.items, 1)}
    originals = {alias: eid for eid, alias in aliases.items()}
    ledger = [{'evidence_id': aliases[e.evidence_id], 'field': e.field, 'value': e.value, 'kind': e.kind}
              for e in inp.evidence.items if isinstance(e.value, (int, float))]
    if review:
        review = {'forecasts': [{'persona': r['persona'],
            'assumptions': [{**a, 'evidence_ids': [aliases[e] for e in a['evidence_ids']]}
                            for a in r['assumptions']],
            'evidence_ids': [aliases[e] for e in r['evidence_ids']]} for r in review['forecasts']]}
    prompt = {'instrument': 'instrument_1', 'persona': persona.value,
              'skills': ['value', 'growth', 'conservative'] if combined_skills else [persona.value],
              'evidence': ledger, 'review': review, 'horizon_months': 12,
              'instruction': 'Use only evidence. Return JSON assumptions [{name: forward_eps or forward_pe, '
                             'value: number, unit: USD/share or multiple, rationale: string, evidence_ids: [id]}], '
                             'evidence_ids, rationale, risk_flags, abstain_reason (null or string). '
                             'Do not return target prices. Cite FACT evidence for every numeric assumption.'}
    # This private ephemeral history is never in checkpoints/audits.
    context.messages.append({'role': 'user', 'content': json.dumps(prompt)})
    base = os.getenv('LLM_BASE_URL', 'https://api.openai.com/v1').rstrip('/')
    budget = llm_budget()

    async def operation() -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=18) as client:
                response = await budget.request(
                    lambda: client.post(base + '/chat/completions',
                        headers={'Authorization': 'Bearer ' + key},
                        json={'model': model, 'messages': context.messages,
                              'response_format': {'type': 'json_object'}, 'temperature': 0}),
                    context)
        except (httpx.TimeoutException, httpx.NetworkError):
            raise TransientToolError('LLM_TRANSPORT_TRANSIENT') from None
        if response.status_code == 429 or response.status_code >= 500:
            raise TransientToolError('LLM_HTTP_TRANSIENT')
        if response.status_code >= 400:
            raise ResearchUnavailable('LLM_HTTP_TERMINAL')
        try:
            envelope = response.json()
            payload = json.loads(envelope['choices'][0]['message']['content'])
            usage = envelope.get('usage', {})
            context.audit.append({'phase': 'Result Synthesis', 'status': 'MODEL_RETURNED',
                                  **{k: v for k, v in usage.items() if k in
                                     ('prompt_tokens', 'completion_tokens', 'total_tokens') and isinstance(v, int)}})
            allowed = {'assumptions', 'evidence_ids', 'rationale', 'risk_flags', 'abstain_reason'}
            if not isinstance(payload, dict) or set(payload) - allowed:
                raise ValueError('invalid schema')
            assumptions = tuple(Assumption.model_validate({**a,
                'evidence_ids': [originals[e] for e in a.get('evidence_ids', [])]})
                for a in payload.get('assumptions', []))
            abstain = payload.get('abstain_reason')
            report = PersonaReport(persona=persona, ticker=inp.ticker, snapshot_id=inp.evidence.snapshot_id,
                assumptions=assumptions, evidence_ids=tuple(originals[e] for e in payload.get('evidence_ids', [])),
                rationale=payload['rationale'], risk_flags=tuple(payload.get('risk_flags', [])),
                abstain_reason=abstain, target_price_candidate=None if abstain else quant.target_from_assumptions(assumptions),
                model_version=model, prompt_version=inp.versions.prompt)
            return validate_report(inp, report).model_dump(mode='json')
        except (KeyError, TypeError, ValueError, ValidationError):
            raise ResearchValidationError('INVALID_STRUCTURED_MODEL_OUTPUT') from None

    report = await bounded_tool(context, operation)
    return PersonaReport.model_validate(report)


def checkpoint_identity(inp: ResearchInput, research_mode: ResearchMode, thread_id: str | None,
                        safety_margin: float = .2) -> str:
    return ':'.join((thread_id or 'standalone', inp.ticker, inp.evidence.snapshot_id,
                     inp.versions.graph, stable_hash({'input': inp, 'mode': research_mode.value,
                                                     'margin': safety_margin})[:20]))


def build_research_graph(research_mode: ResearchMode, *, checkpointer=None,
                         safety_margin: float = .2, generator: Generator | None = None,
                         disagreement_ratio: float = .25, interrupt_before: list[str] | None = None):
    """Compile a real fan-out/fan-in graph; injection is for offline tests."""
    research_mode = ResearchMode(research_mode)
    if not 0 <= safety_margin < 1 or not math.isfinite(disagreement_ratio) or disagreement_ratio < 0:
        raise ResearchValidationError('INVALID_GRAPH_CONFIGURATION')
    graph = StateGraph(GraphState)
    roles = (() if research_mode == ResearchMode.QUANT_ONLY else (Persona.VALUE,) if
             research_mode == ResearchMode.SINGLE_AGENT else tuple(Persona))

    async def validate(state: GraphState):
        inp = ResearchInput.model_validate(state['input'])
        _validate_input(inp)
        return {'review_rounds': 0, 'audit_validation': [
            {'phase': 'Planning', 'status': 'OK', 'persona_count': len(roles)},
            {'phase': 'State Management', 'status': 'IMMUTABLE_SNAPSHOT', 'snapshot_hash': inp.evidence.content_hash},
            {'phase': 'Evidence Verification', 'status': inp.evidence.pit_status.value}]}

    def node(role: Persona):
        async def run(state: GraphState):
            inp = ResearchInput.model_validate(state['input'])
            context = PrivateContext(role)
            selected = generator or (demo_generator if inp.mode == Mode.DEMO else real_generator)
            report = await selected(inp, role, context, None, research_mode == ResearchMode.SINGLE_AGENT)
            if report.persona != role:
                raise ResearchValidationError('PERSONA_IDENTITY_MISMATCH')
            report = validate_report(inp, report)
            key = _KEYS[role]
            return {'report_' + key: report.model_dump(mode='json'), 'audit_' + key: context.audit}
        return run

    def reports(state):
        return tuple(PersonaReport.model_validate(state['report_' + _KEYS[r]]) for r in roles)

    async def manager(state):
        inp = ResearchInput.model_validate(state['input'])
        validated = [validate_report(inp, report) for report in reports(state)]
        values = [r.target_price_candidate for r in validated if r.target_price_candidate is not None]
        disagreement = (max(values) / min(values) - 1) if len(values) > 1 else 0
        return {'review_needed': research_mode == ResearchMode.MULTI_PERSONA_DEBATE and
                disagreement > disagreement_ratio and not state.get('review_rounds', 0)}

    async def review(state):
        inp = ResearchInput.model_validate(state['input'])
        # Manager passes typed assumption summaries; never merges raw messages.
        summary = {'forecasts': [{'persona': r.persona.value,
                    'assumptions': [a.model_dump(mode='json') for a in r.assumptions],
                    'evidence_ids': list(r.evidence_ids)} for r in reports(state)]}
        async def one(role):
            context = PrivateContext(role)
            selected = generator or (demo_generator if inp.mode == Mode.DEMO else real_generator)
            report = validate_report(inp, await selected(inp, role, context, summary, False))
            if report.persona != role:
                raise ResearchValidationError('PERSONA_IDENTITY_MISMATCH')
            return role, report, context
        reviewed = await asyncio.gather(*(one(r) for r in roles))
        update: dict[str, Any] = {'review_rounds': 1, 'review_needed': False}
        values = [r.target_price_candidate for _, r, _ in reviewed if r.target_price_candidate is not None]
        unresolved = len(values) > 1 and max(values) / min(values) - 1 > disagreement_ratio
        for role, report, context in reviewed:
            if unresolved:
                report = report.model_copy(update={'risk_flags': tuple(sorted(set(report.risk_flags) |
                                                       {'UNRESOLVED_DISAGREEMENT'}))})
            key = _KEYS[role]
            update['report_' + key] = report.model_dump(mode='json')
            update['audit_' + key] = state.get('audit_' + key, []) + context.audit
        return update

    async def valuation(state):
        inp = ResearchInput.model_validate(state['input'])
        role_reports = reports(state)
        value = quant.valuate(inp, role_reports, safety_margin=safety_margin)
        candidates = quant.screen_candidates((inp,), limit=1)
        reasons = ((() if candidates else ('QUANT_SCREEN_INELIGIBLE',)) +
                   (() if value.target_12m is not None else (value.abstain_reason or 'UNAVAILABLE',)))
        versions = inp.versions.model_copy(update={'model': role_reports[0].model_version if role_reports else 'quant-only-v1'})
        result = ResearchResult(ticker=inp.ticker, sector=inp.sector, mode=inp.mode,
            snapshot=inp.evidence, reports=role_reports, valuation=value,
            score=candidates[0].score if candidates else 0, factors=candidates[0].factors if candidates else (),
            eligible=not reasons, exclusion_reasons=reasons, research_mode=research_mode,
            review_rounds=state.get('review_rounds', 0), versions=versions)
        return {'result': result.model_dump(mode='json')}

    graph.add_node('validate_snapshot', validate)
    graph.add_node('manager', manager)
    graph.add_node('review', review)
    graph.add_node('valuation', valuation)
    graph.add_edge(START, 'validate_snapshot')
    if roles:
        names = []
        for role in roles:
            name = 'single_skills' if research_mode == ResearchMode.SINGLE_AGENT else _KEYS[role] + '_persona'
            names.append(name)
            graph.add_node(name, node(role))
            graph.add_edge('validate_snapshot', name)
        graph.add_edge(names, 'manager')
    else:
        graph.add_edge('validate_snapshot', 'manager')
    graph.add_conditional_edges('manager', lambda state: 'review' if state['review_needed'] else 'valuation',
                                {'review': 'review', 'valuation': 'valuation'})
    graph.add_edge('review', 'valuation')
    graph.add_edge('valuation', END)
    return graph.compile(checkpointer=checkpointer, interrupt_before=interrupt_before)


async def research_stock(input: ResearchInput, research_mode: ResearchMode, *,
                         checkpointer=None, thread_id: str | None = None,
                         safety_margin: float = .2) -> ResearchResult:
    graph = build_research_graph(research_mode, checkpointer=checkpointer, safety_margin=safety_margin)
    config = {'configurable': {'thread_id': checkpoint_identity(input, ResearchMode(research_mode), thread_id,
                                                               safety_margin)}, 'recursion_limit': 12}
    invocation: Any = {'input': input.model_dump(mode='json')}
    if checkpointer is not None:
        saved = await graph.aget_state(config)
        if saved.values:
            if saved.values.get('result') and not saved.next:
                return ResearchResult.model_validate(saved.values['result'])
            invocation = None  # Native resume: retain completed parallel branch writes.
    state = await graph.ainvoke(invocation, config=config)
    return ResearchResult.model_validate(state['result'])
