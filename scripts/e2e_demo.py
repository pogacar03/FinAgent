"""Offline HTTP E2E with separately launched API and worker; no API keys."""
from __future__ import annotations
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import sys
import httpx

ROOT = Path(__file__).resolve().parents[1]


def wait_until(fetch, predicate, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = fetch()
            if predicate(value):
                return value
        except (httpx.HTTPError, ValueError):
            pass
        time.sleep(.2)
    raise RuntimeError('E2E timeout')


def main():
    with tempfile.TemporaryDirectory(prefix='finagent-e2e-') as tmp:
        env = dict(os.environ, PYTHONPATH=str(ROOT / 'backend'),
                   DATABASE_URL=os.environ.get('E2E_DATABASE_URL', 'sqlite:///' + tmp + '/app.db'),
                   CHECKPOINT_URL=os.environ.get('E2E_CHECKPOINT_URL', tmp + '/checkpoints.db'))
        env.pop('LLM_API_KEY', None)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        logs = open(Path(tmp) / 'services.log', 'w+')
        processes = []
        report = {}
        try:
            processes.append(subprocess.Popen([sys.executable, '-m', 'uvicorn', 'finagent.api:app', '--host', '127.0.0.1', '--port', str(port)], cwd=ROOT, env=env, stdout=logs, stderr=logs))
            client = httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=10)
            wait_until(lambda: client.get('/api/health').json(), lambda r: r.get('status') == 'ok')
            response = client.post('/api/runs', json={'period': '2025-H2', 'mode': 'DEMO'})
            response.raise_for_status()
            run_id = response.json()['run_id']
            # Submit while worker is down, then start: HTTP is independent of execution.
            assert client.get('/api/runs/' + run_id).json()['status'] == 'QUEUED'
            worker_cmd = [sys.executable, '-m', 'finagent.worker']
            worker = subprocess.Popen(worker_cmd, cwd=ROOT, env=env, stdout=logs, stderr=logs)
            processes.append(worker)
            run = wait_until(lambda: client.get('/api/runs/' + run_id).json(), lambda r: r['status'] in ('COMPLETED','FAILED','INSUFFICIENT_ELIGIBLE_STOCKS'))
            assert run['status'] == 'COMPLETED', run
            picks = client.get('/api/runs/' + run_id + '/picks').json()
            assert len(picks['picks']) == 10 and picks['mode'] == 'DEMO'
            detail = client.get('/api/stocks/' + picks['picks'][0]['ticker'] + '/research', params={'run_id': run_id}).json()
            assert len(detail['reports']) == 3
            assert 'SYNTHETIC' in str(detail)
            # Graceful shutdown/restart before backtest proves persisted signals survive.
            worker.terminate()
            worker.wait(timeout=10)
            bt_id = client.post('/api/backtests', json={'run_id': run_id}).json()['backtest_id']
            assert client.get('/api/backtests/' + bt_id).json()['status'] == 'QUEUED'
            processes.append(subprocess.Popen(worker_cmd, cwd=ROOT, env=env, stdout=logs, stderr=logs))
            bt = wait_until(lambda: client.get('/api/backtests/' + bt_id).json(), lambda r: r['status'] in ('COMPLETED','FAILED'))
            assert bt['status'] == 'COMPLETED', bt
            result = bt['result']
            assert result['status'] == 'COMPLETED', result
            assert result['seeking_alpha'] is None and result['seeking_alpha_status'] == 'UNAVAILABLE'
            assert result['finagent']['entry_session'] == result['spy']['entry_session']
            assert result['finagent']['exit_session'] == result['spy']['exit_session']
            events = client.get('/api/runs/' + run_id + '/audit').json()['events']
            assert {'Plan','Tools','State','Evidence','Output'} <= {e['phase'] for e in events}
            report = {'label': 'DEMO / SYNTHETIC', 'run_id': run_id, 'picks': len(picks['picks']),
                      'research_reports': len(detail['reports']), 'api_worker_separate': True,
                      'worker_shutdown_restart': True, 'database': env['DATABASE_URL'].split(':')[0], 'backtest': result, 'audit_events': len(events)}
            print(json.dumps(report, ensure_ascii=False, indent=2))
            destination = ROOT / 'artifacts' / 'e2e_report.json'
            destination.parent.mkdir(exist_ok=True)
            destination.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        except Exception:
            logs.flush()
            logs.seek(0)
            print(logs.read()[-12000:], file=sys.stderr)
            raise
        finally:
            for proc in reversed(processes):
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
            logs.close()


if __name__ == '__main__':
    main()
