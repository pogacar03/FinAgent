from datetime import datetime, timedelta, timezone
import pytest
from finagent.storage import Store, LeaseLost


def test_deduplication_and_completed_research_are_immutable(tmp_path):
    store = Store(f'sqlite:///{tmp_path}/app.db')
    first = store.submit('RUN', {'period': '2025-H2'}, 'same')
    assert store.submit('RUN', {'period': '2025-H2'}, 'same') == first
    store.save_research(first, 'NVDA', {'target': 199})
    store.save_research(first, 'NVDA', {'target': 240})
    assert store.research(first, 'NVDA') == {'target': 199}
    assert store.get(first)['status'] == 'QUEUED'


def test_crash_expiry_reclaim_fences_old_worker(tmp_path):
    url = f'sqlite:///{tmp_path}/app.db'
    store = Store(url)
    run = store.submit('RUN', {}, 'resume')
    now = datetime(2025, 7, 1, tzinfo=timezone.utc)
    first = store.claim('worker1', 1, now)
    assert first['id'] == run
    assert store.claim('worker2', 1, now) is None
    store.save_research(run, 'NVDA', {'completed': True})
    restarted = Store(url)
    second = restarted.claim('worker2', 10, now + timedelta(seconds=2))
    assert second['id'] == run and second['attempts'] == 2
    with pytest.raises(LeaseLost):
        store.finish(first, {'bad': True}, now=now+timedelta(seconds=3))
    restarted.finish(second, {'picks': ['NVDA']}, now=now+timedelta(seconds=3))
    assert store.get(run)['status'] == 'COMPLETED'
    assert store.research(run, 'NVDA') == {'completed': True}
    assert store.claim('worker3', 10, now+timedelta(seconds=4)) is None


def test_retry_and_permanent_errors(tmp_path):
    store = Store(f'sqlite:///{tmp_path}/app.db')
    run = store.submit('RUN', {}, 'retry')
    lease = store.claim('worker', 20)
    store.fail(lease, 'TRANSIENT_PROVIDER', retry=True, delay=0)
    assert store.get(run)['status'] == 'QUEUED'
    lease = store.claim('worker', 20)
    store.fail(lease, 'PIT_UNVERIFIED', retry=False)
    assert store.get(run)['status'] == 'FAILED'
    assert store.get(run)['error'] == 'PIT_UNVERIFIED'


def test_lost_lease_cannot_insert_ticker_or_signal(tmp_path):
    store = Store(f'sqlite:///{tmp_path}/app.db')
    run = store.submit('RUN', {}, 'fence-writes')
    past = datetime.now(timezone.utc) - timedelta(seconds=2)
    old = store.claim('dead', 1, past)
    new = store.claim('alive', 60)
    with pytest.raises(LeaseLost):
        store.save_research(run, 'NVDA', {'stale': True}, lease=old)
    with pytest.raises(LeaseLost):
        store.put_artifact('signal', 'SIGNAL', {'stale': True}, lease=old)
    store.save_research(run, 'NVDA', {'stale': False}, lease=new)
    assert store.research(run, 'NVDA')['stale'] is False


def test_parallel_claimers_do_not_claim_same_job(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    url = f'sqlite:///{tmp_path}/app.db'
    store = Store(url)
    ids = {store.submit('RUN', {'n': n}, f'job{n}') for n in range(6)}
    stores = [Store(url) for _ in range(12)]
    with ThreadPoolExecutor(max_workers=12) as pool:
        claims = list(pool.map(lambda pair: pair[1].claim(f'w{pair[0]}', 60), enumerate(stores)))
    claimed = [c['id'] for c in claims if c]
    assert len(claimed) == len(set(claimed))
    # CAS losers may return no job; remaining queued jobs can be claimed later.
    while (next_job := store.claim('remaining', 60)):
        claimed.append(next_job['id'])
    assert set(claimed) == ids


def test_conflicting_artifact_payload_cannot_diverge_from_frozen_source(tmp_path):
    store=Store(f'sqlite:///{tmp_path}/app.db')
    store.put_artifact('snapshot','INPUT',{'hash':'first'})
    store.put_artifact('snapshot','INPUT',{'hash':'first'})
    with pytest.raises(ValueError,match='IMMUTABLE_ARTIFACT_CONFLICT'):
        store.put_artifact('snapshot','INPUT',{'hash':'different'})
    assert store.artifact('snapshot')=={'hash':'first'}
