"""HTTP submission/reporting only; durable worker is a separate process."""
from __future__ import annotations
import os
import secrets
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from .contracts import RunRequest, BacktestRequest, BenchmarkList, VersionBundle, stable_hash
from .storage import Store, utcnow
from .config import execution_context


def public_job(row: dict) -> dict:
    return {k: v for k, v in row.items() if k not in ('lease_token', 'owner', 'lease_until', 'fingerprint')}


def create_app(store: Store | None = None) -> FastAPI:
    db = store or Store(os.environ.get('DATABASE_URL', 'sqlite:///./finagent.db'))
    app = FastAPI(title='FinAgent', version='0.1.0', description='可审计研究原型；DEMO 数据全部 SYNTHETIC')
    app.state.store = db
    app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:5173', 'http://127.0.0.1:5173'],
                       allow_methods=['GET', 'POST'], allow_headers=['Content-Type', 'Authorization'])

    def lookup(item_id: str, kind: str | None = None) -> dict:
        row = db.get(item_id)
        if row is None or (kind and row['kind'] != kind):
            raise HTTPException(404, 'NOT_FOUND')
        return row

    def submit(kind: str, payload, idempotency_key: str | None, extra: dict | None = None):
        values = payload.model_dump(mode='json', exclude={'idempotency_key'})
        values.update(extra or {})
        versions = VersionBundle().model_dump(mode='json')
        model = os.environ.get('LLM_MODEL') if values.get('mode') == 'REAL' else 'deterministic-demo-v1'
        fingerprint = stable_hash({'kind': kind, 'key': idempotency_key}) if idempotency_key else stable_hash({'kind': kind, 'config': values, 'versions': versions, 'model': model})
        item_id = db.submit(kind, values, fingerprint)
        row = lookup(item_id)
        if row['payload'] != values and not (kind == 'BACKTEST' and idempotency_key and
                row['payload'].get('submitted_request') == values.get('submitted_request')):
            raise HTTPException(409, 'IDEMPOTENCY_KEY_CONFIG_CONFLICT')
        return item_id, row

    @app.get('/api/health')
    def health():
        # Exercise database, not only process liveness.
        db.list_runs(1)
        return {'status': 'ok', 'version': '0.1.0', 'database': db.engine.dialect.name,
                'demo_label': 'DEMO / SYNTHETIC', 'worker': 'separate-process'}

    @app.post('/api/runs', status_code=202)
    def new_run(payload: RunRequest):
        run_id, row = submit('RUN', payload, payload.idempotency_key,
                             {'execution_context': execution_context(payload.mode, payload.research_mode)})
        return {'run_id': run_id, 'status': row['status'], 'mode': payload.mode}

    @app.get('/api/runs')
    def list_runs():
        return {'runs': [dict(public_job(r), run_id=r['id']) for r in db.list_runs()]}

    @app.get('/api/runs/{run_id}')
    def run(run_id: str):
        return dict(public_job(lookup(run_id, 'RUN')), run_id=run_id)

    @app.get('/api/runs/{run_id}/picks')
    def picks(run_id: str):
        row = lookup(run_id, 'RUN')
        result = row['result'] or {}
        return {'run_id': run_id, 'status': row['status'], 'mode': row['payload']['mode'],
                'label': 'DEMO / SYNTHETIC' if row['payload']['mode'] == 'DEMO' else 'REAL',
                'picks': result.get('picks', []), 'signal': result.get('signal'),
                'warnings': result.get('warnings', []), 'exclusions': result.get('exclusions', [])}

    @app.get('/api/runs/{run_id}/audit')
    def events(run_id: str):
        lookup(run_id, 'RUN')
        return {'events': db.events(run_id)}

    @app.get('/api/stocks/{ticker}/research')
    def research(ticker: str, run_id: str):
        lookup(run_id, 'RUN')
        result = db.research(run_id, ticker.upper())
        if result is None:
            raise HTTPException(404, 'RESEARCH_NOT_AVAILABLE')
        return result

    @app.post('/api/backtests', status_code=202)
    def new_backtest(payload: BacktestRequest):
        original = payload.model_dump(mode='json', exclude={'idempotency_key'})
        if payload.idempotency_key:
            previous = db.by_fingerprint(stable_hash({'kind': 'BACKTEST', 'key': payload.idempotency_key}))
            if previous:
                if previous['payload'].get('submitted_request') != original:
                    raise HTTPException(409, 'IDEMPOTENCY_KEY_CONFIG_CONFLICT')
                return {'backtest_id': previous['id'], 'status': previous['status']}
        row = lookup(payload.run_id, 'RUN')
        if row['status'] != 'COMPLETED' or not (row['result'] or {}).get('signal'):
            raise HTTPException(409, 'FROZEN_SIGNAL_REQUIRED')
        resolved = payload.model_copy(update={'as_of': payload.as_of or utcnow()})
        period = row['payload'].get('period') or row['result']['signal'].get('period')
        mode = row['payload'].get('mode', 'DEMO')
        bt_id, row = submit('BACKTEST', resolved, payload.idempotency_key,
                           {'benchmark': db.benchmark(period) if period else None,
                            'execution_context': execution_context(mode),
                            **({'submitted_request': original} if payload.idempotency_key else {})})
        return {'backtest_id': bt_id, 'status': row['status']}

    @app.get('/api/backtests/{backtest_id}')
    def backtest(backtest_id: str):
        return dict(public_job(lookup(backtest_id, 'BACKTEST')), backtest_id=backtest_id)

    @app.get('/api/benchmarks/sa/{period}')
    def benchmark(period: str):
        value = db.benchmark(period)
        return {'status': 'AVAILABLE' if value and value['verification_status'] == 'PIT_VERIFIED' else ('UNVERIFIED' if value else 'UNAVAILABLE'), 'list': value}

    @app.post('/api/benchmarks/sa')
    async def import_sa(request: Request, authorization: str | None = Header(default=None)):
        token = os.environ.get('BENCHMARK_IMPORT_TOKEN')
        if not token:
            raise HTTPException(503, 'IMPORT_DISABLED_SET_BENCHMARK_IMPORT_TOKEN')
        if not authorization or not secrets.compare_digest(authorization, 'Bearer ' + token):
            raise HTTPException(403, 'IMPORT_FORBIDDEN')
        from .data import validate_benchmark_list
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError('object required')
            verification = body.get('verification_evidence') if 'list' in body else None
            if verification is not None and not isinstance(verification, dict):
                raise ValueError('verification_evidence must be an object')
            data = BenchmarkList.model_validate(body['list'] if 'list' in body else body)
            data = validate_benchmark_list(data, verification_evidence=verification)
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, 'INVALID_BENCHMARK_LIST') from exc
        db.save_benchmark(data.model_dump(mode='json'))
        return {'status': 'IMPORTED', 'verification_status': data.verification_status}

    return app


app = create_app()
