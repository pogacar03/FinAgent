"""Cancel actual research after one persisted ticker; restart using native checkpoints."""
import asyncio
from fastapi.testclient import TestClient
from finagent.api import create_app
from finagent.worker import Worker
from finagent.storage import Store
from finagent import agents
import pytest


@pytest.mark.asyncio
async def test_partial_batch_interruption_resumes_only_unfinished_tickers(tmp_path, monkeypatch):
    store = Store(f'sqlite:///{tmp_path}/app.db')
    with TestClient(create_app(store)) as client:
        run_id = client.post('/api/runs',json={'period':'2025-H2','mode':'DEMO'}).json()['run_id']
    original = agents.research_stock
    completed_first = asyncio.Event()
    first_ticker = []
    blocker = asyncio.Event()
    async def interrupted(input_, *args, **kwargs):
        if not first_ticker:
            first_ticker.append(input_.ticker)
            return await original(input_, *args, **kwargs)
        await blocker.wait()
        return await original(input_, *args, **kwargs)
    monkeypatch.setattr(agents, 'research_stock', interrupted)
    worker = Worker(store, checkpoint_url=str(tmp_path/'checkpoints.db'), lease_seconds=.3)
    task = asyncio.create_task(worker.run_once())
    for _ in range(300):
        if first_ticker and store.research(run_id,first_ticker[0]):
            break
        await asyncio.sleep(.01)
    else:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        pytest.fail('first real graph research was not persisted')
    retained = store.research(run_id,first_ticker[0])
    task.cancel()
    await asyncio.gather(task,return_exceptions=True)
    assert store.get(run_id)['status'] == 'RUNNING'
    await asyncio.sleep(.4)
    calls = []
    async def resumed(input_, *args, **kwargs):
        calls.append(input_.ticker)
        return await original(input_, *args, **kwargs)
    monkeypatch.setattr(agents,'research_stock',resumed)
    new_store = Store(store.url)
    restarted = Worker(new_store,checkpoint_url=str(tmp_path/'checkpoints.db'))
    assert await restarted.run_once()
    assert new_store.get(run_id)['status'] == 'COMPLETED'
    assert first_ticker[0] not in calls
    assert new_store.research(run_id,first_ticker[0]) == retained
    assert len(new_store.get(run_id)['result']['picks']) == 10


@pytest.mark.asyncio
async def test_unverified_real_universe_cannot_generate_verified_signal(tmp_path,monkeypatch):
    from finagent import data
    from finagent.contracts import Mode,PITStatus
    demo=data.DemoDataProvider()
    class BadUniverse:
        def universe(self,period,cutoff):
            return demo.universe(period,cutoff).model_copy(update={'mode':Mode.REAL,'pit_status':PITStatus.UNVERIFIED})
        def research_input(self,*args):
            pytest.fail('unverified universe should be rejected before researching stocks')
    monkeypatch.setattr(data,'provider_for',lambda mode:BadUniverse())
    store=Store(f'sqlite:///{tmp_path}/app.db')
    with TestClient(create_app(store)) as client:
        run_id=client.post('/api/runs',json={'period':'2025-H2','mode':'REAL'}).json()['run_id']
    await Worker(store,checkpoint_url=str(tmp_path/'checkpoints.db')).run_once()
    assert store.get(run_id)['status']=='FAILED'
    assert store.get(run_id)['result'] is None
    assert store.research(run_id)==[]


@pytest.mark.asyncio
async def test_changed_model_after_submission_cannot_execute_different_strategy(tmp_path,monkeypatch):
    monkeypatch.setenv('LLM_MODEL','model-a')
    store=Store(f'sqlite:///{tmp_path}/app.db')
    with TestClient(create_app(store)) as client:
        run_id=client.post('/api/runs',json={'mode':'REAL'}).json()['run_id']
    monkeypatch.setenv('LLM_MODEL','model-b')
    await Worker(store,checkpoint_url=str(tmp_path/'checkpoints.db')).run_once()
    assert store.get(run_id)['status']=='FAILED'
    assert store.get(run_id)['error']=='EXECUTION_CONFIGURATION_CHANGED'
    assert store.research(run_id)==[]
