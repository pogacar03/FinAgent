import asyncio
import json

import pytest
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

from finagent.observability import (Observability, QuietOTLPExporter, STAGES,
                                    current_correlation, safe_attributes)


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_sdk_five_stages_real_ids_parent_and_metrics(tmp_path):
    path = tmp_path / 'trace.jsonl'
    obs = Observability(path)
    with obs.trace_scope('Plan', batch_id='b1', run_id='r1', mode='DEMO', llm_called=False) as root:
        for stage in STAGES:
            child = obs.record_event(stage, {'ticker': 'NVDA', 'snapshot_id': 's1',
                'checkpoint_id': 'c1', 'cache_hit': False, 'resumed': True,
                'recovery_result': 'RESUMED'})
            assert child['trace_id'] == root['trace_id']
            assert child['span_id'] != root['span_id']
    assert obs.flush()
    data = rows(path)
    assert set(row['name'] for row in data) == set(STAGES)
    assert len(root['trace_id']) == 32 and int(root['trace_id'], 16) > 0
    assert len(root['span_id']) == 16 and int(root['span_id'], 16) > 0
    for row in data[:-1]:
        assert row['parent_span_id'] == root['span_id']
        assert row['attributes']['langfuse.trace.metadata.run_id'] == 'r1'
        assert row['attributes']['langfuse.trace.metadata.snapshot_id'] == 's1'
        assert row['llm_metrics']['total_tokens'] is None
    assert current_correlation() == {}
    obs.shutdown()


def test_async_tasks_and_to_thread_correlation_isolated(tmp_path):
    obs = Observability(tmp_path / 'async.jsonl')

    async def one(ticker):
        with obs.trace_scope('Tool Calling', run_id='run-' + ticker, ticker=ticker):
            await asyncio.sleep(.001)
            state = await asyncio.to_thread(current_correlation)
            child = obs.record_event('Evidence', {'snapshot_id': 'snap-' + ticker})
            assert state['ticker'] == ticker
            assert child['ticker'] == ticker
            assert child['run_id'] == 'run-' + ticker
            return child['trace_id']

    async def run():
        return await asyncio.gather(one('NVDA'), one('SPY'))

    traces = asyncio.run(run())
    assert traces[0] != traces[1]
    assert current_correlation() == {}
    assert len(rows(tmp_path / 'async.jsonl')) == 4
    obs.shutdown()


def test_filter_unsafe_values_and_record_provider_metrics(tmp_path):
    assert safe_attributes({'prompt': 'sensitive', 'api_key': 'sk-secret',
        'status': 'Bearer-sk-secret', 'ticker': 'NVDA', 'latency_ms': float('nan'),
        'prompt_tokens': -1, 'completion_tokens': True, 'total_tokens': 1.5,
        'cache_hit': 'true', 'snapshot_id': {'raw': 'document'}}) == {'ticker': 'NVDA'}
    obs = Observability(tmp_path / 'safe.jsonl')
    obs.record_event('Output', {'prompt_tokens': 30, 'completion_tokens': 20,
        'total_tokens': 50, 'llm_latency_ms': 125, 'usage_source': 'PROVIDER',
        'prompt': 'secret raw prompt', 'document': 'secret financial document'})
    row = rows(tmp_path / 'safe.jsonl')[0]
    assert row['llm_metrics']['total_tokens'] == 50
    assert row['attributes']['gen_ai.usage.input_tokens'] == 30
    assert 'secret' not in (tmp_path / 'safe.jsonl').read_text()
    obs.shutdown()


def test_exception_does_not_export_message_or_stack(tmp_path):
    obs = Observability(tmp_path / 'error.jsonl')
    with pytest.raises(RuntimeError):
        with obs.trace_scope('Tools', run_id='safe-run'):
            raise RuntimeError('sk-secret raw sensitive prompt')
    row = rows(tmp_path / 'error.jsonl')[0]
    assert row['status'] == 'ERROR'
    assert 'secret' not in (tmp_path / 'error.jsonl').read_text()
    assert current_correlation() == {}
    obs.shutdown()


def test_local_write_failure_failopen(tmp_path):
    blocked = tmp_path / 'not-a-directory'
    blocked.write_text('block')
    obs = Observability(blocked / 'trace.jsonl')
    with obs.trace_scope('State', cache_hit=True):
        value = 42
    assert value == 42
    assert obs.local.failures == 1
    obs.shutdown()


def test_remote_unavailable_preserves_local_and_workflow(tmp_path):
    remote = QuietOTLPExporter('http://127.0.0.1:1/api/public/otel/v1/traces',
                              'TEST_PUBLIC', 'TEST_SECRET')
    obs = Observability(tmp_path / 'remote-fail.jsonl', remote_exporter=remote)
    with obs.trace_scope('State Management', resumed=True):
        answer = 42
    obs.flush()
    assert answer == 42
    assert remote.failures == 1
    assert len(rows(tmp_path / 'remote-fail.jsonl')) == 1
    obs.shutdown()


def test_no_keys_means_no_remote(monkeypatch, tmp_path):
    monkeypatch.setenv('FINAGENT_LANGFUSE_ENABLED', 'true')
    monkeypatch.delenv('LANGFUSE_PUBLIC_KEY', raising=False)
    monkeypatch.delenv('LANGFUSE_SECRET_KEY', raising=False)
    obs = Observability(tmp_path / 'missing.jsonl')
    assert obs.remote is None and obs.remote_status == 'UNAVAILABLE'
    obs.record_event('Output', {'llm_called': False})
    assert rows(tmp_path / 'missing.jsonl')[0]['llm_metrics']['total_tokens'] is None
    obs.shutdown()


def test_provider_initialization_failopen_and_business_error_preserved(monkeypatch):
    import finagent.observability as module

    def broken():
        raise RuntimeError('provider initialization failed')

    monkeypatch.setattr(module, 'get_observability', broken)
    calls = []
    with module.trace_scope('Plan') as ids:
        calls.append(1)
    assert calls == [1] and ids == {}
    assert module.record_event('State', {'status': 'OK'}) == {}
    assert module.flush() is False
    with pytest.raises(ValueError, match='business error'):
        with module.trace_scope('Plan'):
            raise ValueError('business error')


def test_span_start_failopen_and_business_error_preserved(tmp_path, monkeypatch):
    obs = Observability(tmp_path / 'broken.jsonl')

    def broken(*args, **kwargs):
        raise RuntimeError('SDK start failed')

    monkeypatch.setattr(obs.tracer, 'start_as_current_span', broken)
    calls = []
    with obs.trace_scope('Plan') as ids:
        calls.append(1)
    assert calls == [1] and ids == {}
    with pytest.raises(ValueError, match='business error'):
        with obs.trace_scope('Plan'):
            raise ValueError('business error')
    obs.shutdown()
