from datetime import datetime, timezone
from fastapi.testclient import TestClient
from finagent.api import create_app
from finagent.storage import Store
from finagent.contracts import BenchmarkList, PITStatus, Mode


def imported_list():
    return BenchmarkList(period='2025-H2',tickers=('AAPL','MSFT','NVDA','AVGO','AMZN','GOOG','META','WMT','COST','JPM'),
        published_at=datetime(2025,7,1,tzinfo=timezone.utc),source_uri='https://seekingalpha.com/article/example',
        content_hash='user-supplied',verification_status=PITStatus.VERIFIED,mode=Mode.REAL,
        verification_note='User-attested original document')


def test_user_verification_can_be_added_as_immutable_revision(tmp_path, monkeypatch):
    monkeypatch.setenv('BENCHMARK_IMPORT_TOKEN','test-only-token')
    store=Store(f'sqlite:///{tmp_path}/app.db')
    headers={'Authorization':'Bearer test-only-token'}
    with TestClient(create_app(store)) as client:
        raw=imported_list().model_dump(mode='json')
        first=client.post('/api/benchmarks/sa',json=raw,headers=headers)
        assert first.status_code == 200
        assert first.json()['verification_status']=='PIT_UNVERIFIED'
        evidence={'verified_by':'offline-test-reviewer','verified_at':'2026-10-08T10:00:00Z',
                  'evidence_uri':'https://seekingalpha.com/article/example','notes':'original list and publication compared by reviewer'}
        second=client.post('/api/benchmarks/sa',json={'list':raw,'verification_evidence':evidence},headers=headers)
        assert second.status_code == 200,second.text
        assert second.json()['verification_status']=='PIT_VERIFIED'
        current=client.get('/api/benchmarks/sa/2025-H2').json()
        assert current['status']=='AVAILABLE'
        assert len(store.benchmark_revisions('2025-H2'))==2


def test_backtest_default_evaluation_and_benchmark_revision_affect_identity(tmp_path,monkeypatch):
    store=Store(f'sqlite:///{tmp_path}/app.db')
    run=store.submit('RUN',{'period':'2025-H2'},'frozen')
    lease=store.claim('seed',60)
    store.finish(lease,{'signal':{'signal_id':'frozen-one'}})
    import finagent.api as api
    with TestClient(create_app(store)) as client:
        monkeypatch.setattr(api,'utcnow',lambda:datetime(2025,7,1,tzinfo=timezone.utc))
        one=client.post('/api/backtests',json={'run_id':run}).json()['backtest_id']
        monkeypatch.setattr(api,'utcnow',lambda:datetime(2026,7,1,tzinfo=timezone.utc))
        two=client.post('/api/backtests',json={'run_id':run}).json()['backtest_id']
        assert one != two
        # Same explicit evaluation snapshot remains idempotent.
        request={'run_id':run,'as_of':'2026-07-01T00:00:00Z'}
        assert client.post('/api/backtests',json=request).json()['backtest_id']==two
        store.save_benchmark(imported_list().model_dump(mode='json'))
        three=client.post('/api/backtests',json=request).json()['backtest_id']
        assert three != two
        assert store.get(three)['payload']['benchmark']['verification_status']=='PIT_VERIFIED'


def test_explicit_key_default_evaluation_retries_reuse_first_snapshot(tmp_path,monkeypatch):
    store=Store(f'sqlite:///{tmp_path}/app.db')
    run=store.submit('RUN',{'period':'2025-H2'},'key-retry')
    store.finish(store.claim('seed'),{'signal':{'signal_id':'one'}})
    import finagent.api as api
    with TestClient(create_app(store)) as client:
        monkeypatch.setattr(api,'utcnow',lambda:datetime(2026,7,1,tzinfo=timezone.utc))
        request={'run_id':run,'idempotency_key':'stable-evaluation'}
        first=client.post('/api/backtests',json=request)
        monkeypatch.setattr(api,'utcnow',lambda:datetime(2026,7,2,tzinfo=timezone.utc))
        second=client.post('/api/backtests',json=request)
        assert second.status_code==202,second.text
        assert first.json()['backtest_id']==second.json()['backtest_id']
        assert client.post('/api/backtests',json={**request,'slippage_bps':10}).status_code==409


def test_malformed_verification_evidence_is_422_not_500(tmp_path,monkeypatch):
    monkeypatch.setenv('BENCHMARK_IMPORT_TOKEN','test-only-token')
    with TestClient(create_app(Store(f'sqlite:///{tmp_path}/app.db')),raise_server_exceptions=False) as client:
        for invalid in ('bad',[],3):
            response=client.post('/api/benchmarks/sa',json={'list':imported_list().model_dump(mode='json'),'verification_evidence':invalid},
                                 headers={'Authorization':'Bearer test-only-token'})
            assert response.status_code==422,response.text
