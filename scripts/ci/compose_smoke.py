"""Validate the actual Compose stack from its Linux host; standard library only.

No subprocess starts a local substitute API/worker. All application work must
be done by the Docker services. Failure propagates to the shell/Actions job.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.error import URLError
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[2]


def compose(*args: str) -> str:
    result = subprocess.run(['docker', 'compose', '-f', str(ROOT/'compose.yaml'), *args],
                            check=True, capture_output=True, text=True, timeout=60)
    return result.stdout


def request(base: str, path: str, body: dict | None = None):
    req = Request(base.rstrip('/') + path, data=json.dumps(body).encode() if body is not None else None,
                  headers={'Content-Type': 'application/json'})
    with urlopen(req, timeout=10) as response:
        raw = response.read().decode()
        return json.loads(raw) if 'application/json' in response.headers.get('Content-Type', '') else raw


def wait_job(fetch, timeout: float = 90, interval: float = .25) -> dict:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = fetch()
        except (URLError, TimeoutError, OSError) as exc:
            last = type(exc).__name__
        else:
            status = last.get('status')
            if status == 'COMPLETED':
                return last
            if status not in ('QUEUED', 'RUNNING'):
                raise RuntimeError(f'Worker job terminal status: {status}; code={last.get("error")}')
        time.sleep(interval)
    raise TimeoutError(f'Worker job did not complete within {timeout}s; last={last}')


def check_worker_state(raw: str) -> None:
    try:
        parsed = json.loads(raw)
        rows = parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    if len(rows) != 1 or rows[0].get('Service') != 'worker' or rows[0].get('State') != 'running':
        raise RuntimeError('Compose worker is missing or not running')


def database_evidence(run_id: str, bt_id: str) -> dict:
    # Server IDs enter SQL only after strict UUID parsing; no arbitrary input SQL.
    run_id, bt_id = str(UUID(run_id)), str(UUID(bt_id))
    sql = f"""SELECT json_build_object(
        'run_status', (SELECT status FROM research_jobs WHERE id = '{run_id}'),
        'backtest_status', (SELECT status FROM research_jobs WHERE id = '{bt_id}'),
        'research_reports', (SELECT count(*) FROM agent_reports WHERE run_id = '{run_id}'),
        'universe_artifacts', (SELECT count(*) FROM immutable_artifacts WHERE id = '{run_id}:universe'),
        'checkpoint_threads', (SELECT count(DISTINCT thread_id) FROM checkpoints WHERE thread_id LIKE '{run_id}:%'),
        'audit_events', (SELECT count(*) FROM audit_events WHERE run_id = '{run_id}'))"""
    value = json.loads(compose('exec', '-T', 'postgres', 'psql', '-U', 'finagent', '-d', 'finagent',
                              '-v', 'ON_ERROR_STOP=1', '-At', '-c', sql))
    if not (value['run_status'] == value['backtest_status'] == 'COMPLETED'
            and value['research_reports'] >= 10 and value['universe_artifacts'] == 1
            and value['checkpoint_threads'] >= 10 and value['audit_events'] > 0):
        raise RuntimeError(f'PostgreSQL durable evidence incomplete: {value}')
    return value


def run_checks(api: str, frontend: str) -> dict:
    health = request(api, '/api/health')
    if health.get('status') != 'ok' or health.get('database') != 'postgresql':
        raise RuntimeError('Compose API must use the real PostgreSQL service')
    if request(frontend, '/api/health') != health or 'FinAgent' not in request(frontend, '/'):
        raise RuntimeError('Built nginx frontend or its API proxy is not healthy')
    check_worker_state(compose('ps', '--all', '--format', 'json', 'worker'))
    # Queue with worker down, then prove it advances only after this container starts.
    compose('stop', '--timeout', '10', 'worker')
    submitted = request(api, '/api/runs', {'period': '2025-H2', 'mode': 'DEMO',
        'research_mode': 'multi_persona', 'idempotency_key': 'ci-' + str(uuid4())})
    run_id = submitted['run_id']
    if request(api, '/api/runs/' + run_id)['status'] != 'QUEUED':
        raise RuntimeError('Job was not durably queued while worker stopped')
    compose('start', 'worker')
    run = wait_job(lambda: request(api, '/api/runs/' + run_id))
    picks = request(api, '/api/runs/' + run_id + '/picks')
    if picks['mode'] != 'DEMO' or len(picks['picks']) != 10 or len({p['ticker'] for p in picks['picks']}) != 10:
        raise RuntimeError('Synthetic research must freeze exactly ten unique picks')
    detail = request(api, '/api/stocks/' + picks['picks'][0]['ticker'] + '/research?run_id=' + run_id)
    if len(detail['reports']) != 3 or 'SYNTHETIC' not in json.dumps(detail):
        raise RuntimeError('Actual isolated graph reports or synthetic provenance missing')
    events = request(api, '/api/runs/' + run_id + '/audit')['events']
    if not ({'Plan', 'Tools', 'State', 'Evidence', 'Output'} <= {e['phase'] for e in events}
            and any(e['metadata'].get('checkpoint_id') for e in events)):
        raise RuntimeError('Native graph checkpoint/audit evidence missing')
    # Keep the original frozen signal, but execute backtest with a restarted worker.
    compose('stop', '--timeout', '10', 'worker')
    bt_id = request(api, '/api/backtests', {'run_id': run_id, 'as_of': '2026-02-01T00:00:00Z'})['backtest_id']
    if request(api, '/api/backtests/' + bt_id)['status'] != 'QUEUED':
        raise RuntimeError('Backtest was not durably queued during worker restart')
    compose('start', 'worker')
    bt = wait_job(lambda: request(api, '/api/backtests/' + bt_id))['result']
    if (bt['status'] != 'COMPLETED' or bt['mode'] != 'DEMO' or bt['seeking_alpha'] is not None
            or bt['seeking_alpha_status'] != 'UNAVAILABLE' or not bt['finagent'] or not bt['spy']):
        raise RuntimeError('Synthetic matured backtest or honest missing-SA handling failed')
    for field in ('entry_session', 'exit_session'):
        if bt['finagent'][field] != bt['spy'][field]:
            raise RuntimeError('Portfolio execution windows differ')
    if request(api, '/api/runs/' + run_id)['result']['signal'] != run['result']['signal']:
        raise RuntimeError('Frozen signal changed across worker restart')
    db = database_evidence(run_id, bt_id)
    check_worker_state(compose('ps', '--all', '--format', 'json', 'worker'))
    return {'status': 'CHECKS_PASSED', 'label': 'DEMO / SYNTHETIC', 'commit': os.getenv('GITHUB_SHA'),
            'github_run_id': os.getenv('GITHUB_RUN_ID'), 'run_id': run_id, 'backtest_id': bt_id,
            'database': 'postgresql', 'durable_evidence': db, 'picks': 10, 'personas': 3,
            'worker_restart': True, 'frontend_proxy': True, 'seeking_alpha_status': 'UNAVAILABLE',
            'entry_session': bt['entry_session'], 'exit_session': bt['exit_session']}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--api-url', default='http://127.0.0.1:8000')
    parser.add_argument('--frontend-url', default='http://127.0.0.1:5173')
    parser.add_argument('--report', type=Path, default=ROOT/'artifacts/docker-ci/integration.json')
    args = parser.parse_args()
    result = run_checks(args.api_url, args.frontend_url)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
