"""Offline vertical slice: actual graph, persisted jobs, frozen backtest."""
from fastapi.testclient import TestClient
import pytest
from finagent.api import create_app
from finagent.worker import Worker
from finagent.storage import Store


@pytest.mark.asyncio
async def test_run_freeze_backtest_and_honest_real_failure(tmp_path, monkeypatch):
    monkeypatch.delenv('REAL_DATA_PATH', raising=False)
    url = f'sqlite:///{tmp_path}/app.db'
    store = Store(url)
    app = create_app(store)
    worker = Worker(store, checkpoint_url=str(tmp_path / 'checkpoints.db'))
    with TestClient(app) as client:
        response = client.post('/api/runs', json={'period': '2025-H2', 'mode': 'DEMO'})
        assert response.status_code == 202
        run_id = response.json()['run_id']
        assert client.post('/api/runs', json={'period': '2025-H2', 'mode': 'DEMO'}).json()['run_id'] == run_id
        await worker.run_once()
        run = client.get(f'/api/runs/{run_id}').json()
        assert run['status'] == 'COMPLETED', run
        picks = client.get(f'/api/runs/{run_id}/picks').json()
        assert len(picks['picks']) == 10
        assert len({p['ticker'] for p in picks['picks']}) == 10
        research = client.get(f"/api/stocks/{picks['picks'][0]['ticker']}/research", params={'run_id': run_id}).json()
        assert len(research['reports']) == 3
        assert 'SYNTHETIC' in str(research)
        bt = client.post('/api/backtests', json={'run_id': run_id})
        assert bt.status_code == 202, bt.text
        bt_id = bt.json()['backtest_id']
        await worker.run_once()
        result = client.get(f'/api/backtests/{bt_id}').json()
        assert result['status'] == 'COMPLETED', result
        assert result['result']['seeking_alpha_status'] == 'UNAVAILABLE'
        assert result['result']['seeking_alpha'] is None
        assert result['result']['finagent'] is not None
        assert result['result']['spy'] is not None
        real = client.post('/api/runs', json={'period': '2025-H2', 'mode': 'REAL'})
        await worker.run_once()
        real_run = client.get('/api/runs/' + real.json()['run_id']).json()
        assert real_run['status'] == 'FAILED'
        assert 'UNAVAILABLE' in real_run['error']
        assert client.get('/api/runs/nonexistent').status_code == 404
        assert client.post('/api/runs', json={'period': 'wrong'}).status_code == 422
        assert client.get('/api/runs').json()['runs']
        events = client.get(f'/api/runs/{run_id}/audit').json()['events']
        assert {'Plan', 'Tools', 'State', 'Evidence', 'Output'} <= {e['phase'] for e in events}
        assert any(e['metadata'].get('checkpoint_id') for e in events)


def test_import_is_disabled_without_token(tmp_path, monkeypatch):
    monkeypatch.delenv('BENCHMARK_IMPORT_TOKEN', raising=False)
    with TestClient(create_app(Store(f'sqlite:///{tmp_path}/app.db'))) as client:
        assert client.post('/api/benchmarks/sa', json={}).status_code in (403, 503)
