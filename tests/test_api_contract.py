from fastapi.testclient import TestClient
from finagent.api import create_app
from finagent.storage import Store


def test_api_only_persists_and_rejects_conflicting_idempotency(tmp_path):
    store = Store(f'sqlite:///{tmp_path}/db.sqlite')
    with TestClient(create_app(store)) as client:
        first = client.post('/api/runs', json={'period': '2025-H2','idempotency_key':'one'})
        assert first.status_code == 202
        run_id = first.json()['run_id']
        assert client.get('/api/runs/' + run_id).json()['status'] == 'QUEUED'
        assert store.research(run_id) == []
        second = client.post('/api/runs', json={'period':'2026-H1','idempotency_key':'one'})
        assert second.status_code == 409
        assert client.post('/api/backtests',json={'run_id':run_id}).status_code == 409
        public = client.get('/api/runs/' + run_id).json()
        assert not {'lease_token','lease_until','owner'} & public.keys()
        assert client.get('/api/health').json()['worker'] == 'separate-process'


def test_explicit_idempotency_cannot_reuse_changed_model(tmp_path,monkeypatch):
    store=Store(f'sqlite:///{tmp_path}/app.db')
    monkeypatch.setenv('LLM_MODEL','model-a')
    with TestClient(create_app(store)) as client:
        payload={'period':'2025-H2','mode':'REAL','idempotency_key':'fixed-model'}
        first=client.post('/api/runs',json=payload)
        assert first.status_code==202
        monkeypatch.setenv('LLM_MODEL','model-b')
        second=client.post('/api/runs',json=payload)
        assert second.status_code==409
        assert store.get(first.json()['run_id'])['payload']['execution_context']['model']=='model-a'
