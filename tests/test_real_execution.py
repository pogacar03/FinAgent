"""REAL plumbing exercised with invented, explicitly test-only attested records."""
import json
from datetime import date, datetime, timezone
import pytest
from fastapi.testclient import TestClient
from finagent.api import create_app
from finagent.contracts import stable_hash
from finagent.data import DemoDataProvider
from finagent.storage import Store
from finagent.worker import Worker


def seal(record):
    record.pop('content_hash', None)
    record['content_hash'] = stable_hash(record)
    return record


def real_record(model):
    value = model.model_dump(mode='json')
    value.update(mode='REAL', pit_status='PIT_VERIFIED', source='INVENTED TEST FIXTURE',
                 source_uri='https://fixture.example.test/' + str(value.get('ticker', 'universe')))
    return seal(value)


def write_bundle(path, bundle):
    bundle.pop('bundle_hash', None)
    bundle['bundle_hash'] = stable_hash(bundle)
    path.write_text(json.dumps(bundle))


@pytest.mark.asyncio
async def test_future_execution_data_can_mature_frozen_signal_but_history_cannot_change(tmp_path, monkeypatch):
    demo = DemoDataProvider()
    cutoff = datetime(2025, 6, 30, 23, 59, 59, tzinfo=timezone.utc)
    universe = demo.universe('2025-H2', cutoff)
    inputs = [demo.research_input(m.ticker, cutoff) for m in universe.members]
    bundle = {'schema_version': 1, 'mode': 'REAL', 'verification': {
        'status': 'PIT_VERIFIED', 'verified_by': 'offline test fixture',
        'verified_at': '2026-02-01T00:00:00+00:00', 'evidence_uri': 'https://fixture.example.test/attestation',
        'notes': 'Invented fixtures for integration tests; no actual market performance.'},
        'universes': [real_record(universe)],
        'market_bars': [real_record(b) for i in inputs for b in i.market],
        'financials': [real_record(i.financials) for i in inputs], 'actions': [],
        'action_coverage': [seal({'ticker': m.ticker, 'start': '2025-01-01', 'end': '2026-01-31',
            'complete': True, 'available_at': '2026-02-01T00:00:00+00:00',
            'source_uri': 'https://fixture.example.test/coverage', 'currency': 'USD',
            'mode': 'REAL', 'pit_status': 'PIT_VERIFIED'}) for m in universe.members]}
    path = tmp_path/'bundle.json'
    write_bundle(path, bundle)
    monkeypatch.setenv('REAL_DATA_PATH', str(path))
    store = Store(f'sqlite:///{tmp_path}/app.db')
    worker = Worker(store, checkpoint_url=str(tmp_path/'checkpoints.db'))
    with TestClient(create_app(store)) as client:
        run_id = client.post('/api/runs', json={'period': '2025-H2', 'mode': 'REAL',
            'research_mode': 'quant_only'}).json()['run_id']
        await worker.run_once()
        run = store.get(run_id)
        assert run['status'] == 'COMPLETED', run
        original_signal = run['result']['signal']
        bundle['market_bars'].extend(real_record(b) for m in universe.members
            for b in demo.bars(m.ticker, date(2025,7,1), date(2026,1,31)))
        write_bundle(path, bundle)
        bt_id = client.post('/api/backtests', json={'run_id': run_id, 'as_of': '2026-02-01T00:00:00Z'}).json()['backtest_id']
        await worker.run_once()
        evaluated = store.get(bt_id)
        assert evaluated['status'] == 'COMPLETED', evaluated
        assert evaluated['result']['status'] == 'COMPLETED', evaluated
        assert store.get(run_id)['result']['signal'] == original_signal
        assert evaluated['payload']['execution_context']['provider_bundle_hash'] != run['payload']['execution_context']['provider_bundle_hash']
        picked = original_signal['picks'][0]['ticker']
        old = next(f for f in bundle['financials'] if f['ticker'] == picked)
        old['earnings_per_share'] += 1
        seal(old)
        write_bundle(path, bundle)
        bad_id = client.post('/api/backtests', json={'run_id': run_id, 'as_of': '2026-02-02T00:00:00Z'}).json()['backtest_id']
        await worker.run_once()
        assert store.get(bad_id)['error'] == 'FROZEN_RESEARCH_INPUT_CHANGED'
        assert store.get(bad_id)['result'] is None
