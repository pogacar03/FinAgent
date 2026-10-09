"""Offline real LangGraph invariants; all financial fixtures are SYNTHETIC."""
import asyncio
import json

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import ValidationError

from finagent import agents
from finagent.contracts import Mode, Persona, PITStatus, ResearchMode, ResearchResult
from test_quant import research


def run(awaitable):
    return asyncio.run(awaitable)


def test_actual_graph_structure_and_parallel_private_contexts():
    async def scenario():
        contexts, snapshots, started = [], [], set()
        all_started = asyncio.Event()
        async def generator(inp, role, context, review, combined):
            contexts.append(context)
            snapshots.append(inp.evidence)
            assert context.messages == [] and context.tool_calls == 0
            context.messages.append({'role': 'assistant', 'content': role.value})
            started.add(role)
            if len(started) == 3:
                all_started.set()
            await asyncio.wait_for(all_started.wait(), timeout=1)
            assert context.messages[0]['content'] == role.value
            with pytest.raises(ValidationError):
                inp.evidence.items[0].value = 999
            return await agents.demo_generator(inp, role, context, review, combined)
        graph = agents.build_research_graph(ResearchMode.MULTI_PERSONA, generator=generator)
        assert {'value_persona', 'growth_persona', 'conservative_persona', 'manager', 'valuation'} <= set(graph.get_graph().nodes)
        state = await graph.ainvoke({'input': research().model_dump(mode='json')})
        result = ResearchResult.model_validate(state['result'])
        assert len(result.reports) == 3
        assert len({id(c.messages) for c in contexts}) == 3
        assert len({s.content_hash for s in snapshots}) == 1
        assert result.valuation.target_12m == pytest.approx(199)
        assert result.valuation.entry_price == pytest.approx(159.2)
        assert result.versions.model == 'deterministic-demo-v1'
        assert all('SYNTHETIC' in r.risk_flags for r in result.reports)
        assert 'messages' not in json.dumps(state)
    run(scenario())


def test_ablations_have_zero_one_or_three_roles_and_distinct_prices():
    async def scenario():
        outputs = [await agents.research_stock(research(), mode) for mode in ResearchMode]
        assert [len(r.reports) for r in outputs] == [0, 1, 3, 3]
        assert len({r.valuation.target_12m for r in outputs[:3]}) == 3
        assert outputs[1].reports[0].rationale.endswith('combining value, growth and conservative skills.')
        assert [r.review_rounds for r in outputs] == [0, 0, 0, 1]
        assert all('UNRESOLVED_DISAGREEMENT' in r.risk_flags for r in outputs[-1].reports)
    run(scenario())


def test_debate_exactly_one_parallel_review_and_no_raw_peer_history():
    async def scenario():
        calls = []
        async def generator(inp, role, context, review, combined):
            calls.append((role, review, id(context)))
            assert not context.messages
            if review:
                assert set(review) == {'forecasts'}
                assert all('messages' not in p for p in review['forecasts'])
            return await agents.demo_generator(inp, role, context, review, combined)
        graph = agents.build_research_graph(ResearchMode.MULTI_PERSONA_DEBATE, generator=generator)
        state = await graph.ainvoke({'input': research().model_dump(mode='json')})
        assert len(calls) == 6 and sum(r is not None for _, r, _ in calls) == 3
        assert state['review_rounds'] == 1
        # Equal forecasts do not unnecessarily review.
        async def agreement(inp, role, context, review, combined):
            report = await agents.demo_generator(inp, role, context, review, True)
            return report
        graph = agents.build_research_graph(ResearchMode.MULTI_PERSONA_DEBATE, generator=agreement)
        state = await graph.ainvoke({'input': research().model_dump(mode='json')})
        assert state['review_rounds'] == 0
    run(scenario())


def test_native_sqlite_interruption_restart_and_cached_result(tmp_path):
    async def scenario():
        inp = research()
        identity = agents.checkpoint_identity(inp, ResearchMode.MULTI_PERSONA, 'run-A')
        config = {'configurable': {'thread_id': identity}}
        path = str(tmp_path / 'native.db')
        async with AsyncSqliteSaver.from_conn_string(path) as saver:
            graph = agents.build_research_graph(ResearchMode.MULTI_PERSONA, checkpointer=saver,
                                                 interrupt_before=['manager'])
            await graph.ainvoke({'input': inp.model_dump(mode='json')}, config)
            saved = await graph.aget_state(config)
            assert saved.next == ('manager',)
            assert 'report_value' in saved.values and 'result' not in saved.values
        # Reopen actual native database, not an in-memory checkpoint emulation.
        async with AsyncSqliteSaver.from_conn_string(path) as saver:
            result = await agents.research_stock(inp, ResearchMode.MULTI_PERSONA,
                                                 checkpointer=saver, thread_id='run-A')
            assert result.valuation.target_12m == pytest.approx(199)
            assert await agents.research_stock(inp, ResearchMode.MULTI_PERSONA,
                checkpointer=saver, thread_id='run-A') == result
            changed = agents.checkpoint_identity(inp, ResearchMode.MULTI_PERSONA, 'run-B')
            assert changed != identity
            assert agents.checkpoint_identity(inp, ResearchMode.QUANT_ONLY, 'run-A') != identity
    run(scenario())


def test_assumption_unknown_or_nonfact_reference_is_terminal():
    async def scenario():
        inp = research()
        report = await agents.demo_generator(inp, Persona.VALUE, agents.PrivateContext(Persona.VALUE))
        unknown = report.assumptions[0].model_copy(update={'evidence_ids': ('unknown',)})
        with pytest.raises(agents.ResearchValidationError, match='FACT_CITATION'):
            agents.validate_report(inp, report.model_copy(update={'assumptions': (unknown, report.assumptions[1])}))
        bad_item = inp.evidence.items[0].model_copy(update={'kind': 'ASSUMPTION'})
        changed = inp.model_copy(update={'evidence': inp.evidence.model_copy(update={
            'items': (bad_item, *inp.evidence.items[1:])})})
        with pytest.raises(agents.ResearchValidationError):
            agents.validate_report(changed, report)
        fake_price = report.model_copy(update={'target_price_candidate': 99999})
        assert agents.validate_report(inp, fake_price).target_price_candidate == pytest.approx(190)
    run(scenario())


def test_transient_retry_timeout_and_permanent_no_retry():
    async def scenario():
        context = agents.PrivateContext(Persona.VALUE)
        async def flaky():
            if context.tool_calls < 3:
                raise agents.TransientToolError('temporary')
            return 7
        assert await agents.bounded_tool(context, flaky) == 7
        assert context.tool_calls == 3
        terminal = agents.PrivateContext(Persona.VALUE)
        async def invalid():
            raise agents.ResearchValidationError('invalid citation')
        with pytest.raises(agents.ResearchValidationError):
            await agents.bounded_tool(terminal, invalid)
        assert terminal.tool_calls == 1
        timeout = agents.PrivateContext(Persona.VALUE)
        async def slow():
            await asyncio.sleep(1)
        with pytest.raises(agents.TransientToolError):
            await agents.bounded_tool(timeout, slow, timeout=.001)
        assert timeout.tool_calls == 3
    run(scenario())


def test_real_unconfigured_abstains_and_unverified_rejected(monkeypatch):
    monkeypatch.delenv('LLM_API_KEY', raising=False)
    monkeypatch.delenv('LLM_MODEL', raising=False)
    async def scenario():
        inp = research(mode=Mode.REAL)
        result = await agents.research_stock(inp, ResearchMode.MULTI_PERSONA)
        assert not result.eligible and result.valuation.target_12m is None
        assert all(r.abstain_reason == 'UNAVAILABLE_LLM_CONFIGURATION' for r in result.reports)
        assert all(r.model_version == 'unavailable' for r in result.reports)
        with pytest.raises(agents.ResearchValidationError, match='PIT_VERIFIED'):
            await agents.research_stock(research(mode=Mode.REAL, pit=PITStatus.UNVERIFIED), ResearchMode.QUANT_ONLY)
    run(scenario())


def test_real_structured_model_anonymous_prompt_and_usage(monkeypatch):
    monkeypatch.setenv('LLM_API_KEY', 'secret-for-offline-test')
    monkeypatch.setenv('LLM_MODEL', 'offline-mocked-model')
    requests = []
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, *, headers, json):
            requests.append(json)
            payload = {'assumptions': [
                {'name':'forward_eps','value':12,'unit':'USD/share','rationale':'source EPS projection','evidence_ids':['evidence_1']},
                {'name':'forward_pe','value':20,'unit':'multiple','rationale':'subjective multiple','evidence_ids':['evidence_1']}],
                'evidence_ids':['evidence_1'],'rationale':'evidence only','risk_flags':['SUBJECTIVE'], 'abstain_reason':None}
            return httpx.Response(200, json={'choices':[{'message':{'content':__import__('json').dumps(payload)}}],
                                            'usage':{'prompt_tokens':15,'completion_tokens':30,'total_tokens':45}})
    import httpx
    monkeypatch.setattr(agents.httpx, 'AsyncClient', Client)
    async def scenario():
        inp = research(mode=Mode.REAL)
        context = agents.PrivateContext(Persona.VALUE)
        report = await agents.real_generator(inp, Persona.VALUE, context)
        assert report.target_price_candidate == 240
        assert report.evidence_ids == ('NVDA-earnings_per_share',)
        prompt = json.dumps(requests)
        assert 'NVDA' not in prompt and 'secret-for-offline-test' not in prompt
        assert 'source_uri' not in prompt and '2025' not in prompt
        assert any(a.get('total_tokens') == 45 for a in context.audit)
    run(scenario())


def test_native_checkpoint_retains_successful_parallel_writes(tmp_path):
    async def scenario():
        calls = {r: 0 for r in Persona}
        fail = True
        async def generator(inp, role, context, review, combined):
            calls[role] += 1
            if role == Persona.GROWTH and fail:
                raise agents.TransientToolError('simulated process failure')
            return await agents.demo_generator(inp, role, context, review, combined)
        inp = research()
        config = {'configurable': {'thread_id': agents.checkpoint_identity(inp, ResearchMode.MULTI_PERSONA, 'crash-run')}}
        path = str(tmp_path / 'pending-writes.db')
        async with AsyncSqliteSaver.from_conn_string(path) as saver:
            graph = agents.build_research_graph(ResearchMode.MULTI_PERSONA, checkpointer=saver, generator=generator)
            with pytest.raises(agents.TransientToolError):
                await graph.ainvoke({'input': inp.model_dump(mode='json')}, config)
        fail = False
        async with AsyncSqliteSaver.from_conn_string(path) as saver:
            graph = agents.build_research_graph(ResearchMode.MULTI_PERSONA, checkpointer=saver, generator=generator)
            state = await graph.ainvoke(None, config)
            assert state['result']['valuation']['target_12m'] == pytest.approx(199)
        assert calls == {Persona.VALUE: 1, Persona.GROWTH: 2, Persona.CONSERVATIVE: 1}
    run(scenario())


def test_shared_live_llm_budget_across_stocks_and_retries(monkeypatch):
    """Observe real await overlap/start times in HTTP transport, across 3 stock graphs."""
    import httpx
    monkeypatch.setenv('LLM_API_KEY', 'offline-budget-key')
    monkeypatch.setenv('LLM_MODEL', 'offline-budget-model')
    monkeypatch.setenv('LLM_CONCURRENCY', '2')
    monkeypatch.setenv('LLM_MIN_INTERVAL_SECONDS', '0.01')
    starts, active, high_water = [], 0, 0
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, *, headers, json):
            nonlocal active, high_water
            starts.append(asyncio.get_running_loop().time())
            first_attempt = len(starts) == 1
            active += 1
            high_water = max(high_water, active)
            try:
                await asyncio.sleep(.03)
                if first_attempt:
                    return httpx.Response(503)
                payload = {'assumptions': [
                    {'name':'forward_eps','value':12,'unit':'USD/share','rationale':'projection','evidence_ids':['evidence_1']},
                    {'name':'forward_pe','value':20,'unit':'multiple','rationale':'policy','evidence_ids':['evidence_1']}],
                    'evidence_ids':['evidence_1'],'rationale':'offline mock','risk_flags':[], 'abstain_reason':None}
                return httpx.Response(200, json={'choices':[{'message':{'content':__import__('json').dumps(payload)}}]})
            finally:
                active -= 1
    monkeypatch.setattr(agents.httpx, 'AsyncClient', Client)
    async def scenario():
        results = await asyncio.gather(*(agents.research_stock(research(ticker=t, mode=Mode.REAL),
                    ResearchMode.MULTI_PERSONA) for t in ('NVDA', 'MSFT', 'AAPL')))
        assert all(r.eligible for r in results)
        assert len(starts) == 10  # Nine personas plus one actual transient retry.
        assert high_water == 2  # Bound holds while useful parallelism remains.
        assert min(b-a for a,b in zip(starts, starts[1:])) >= .009
    run(scenario())


@pytest.mark.parametrize('concurrency,interval', [('0','.01'), ('2.5','.01'), ('-1','.01'),
                                                   ('2','-0.1'), ('2','nan'), ('2','inf'), ('2','oops')])
def test_live_llm_budget_rejects_invalid_configuration(monkeypatch, concurrency, interval):
    monkeypatch.setenv('LLM_CONCURRENCY', concurrency)
    monkeypatch.setenv('LLM_MIN_INTERVAL_SECONDS', interval)
    async def scenario():
        with pytest.raises(agents.ResearchValidationError, match='INVALID_LLM_LIMITS'):
            agents.llm_budget()
    run(scenario())


def test_shared_budget_cannot_be_bypassed_by_reconfiguring_active_loop(monkeypatch):
    monkeypatch.setenv('LLM_CONCURRENCY', '2')
    monkeypatch.setenv('LLM_MIN_INTERVAL_SECONDS', '0.01')
    async def scenario():
        first = agents.llm_budget()
        assert agents.llm_budget() is first
        monkeypatch.setenv('LLM_CONCURRENCY', '3')
        with pytest.raises(agents.ResearchValidationError, match='CHANGED_IN_ACTIVE_LOOP'):
            agents.llm_budget()
    run(scenario())
