"""Run isolated PostgreSQL production E2E; never starts a system/login service."""
from __future__ import annotations
import getpass
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    configured = os.environ.get('PG_BIN', '/opt/homebrew/opt/postgresql@16/bin')
    pg_bin = Path(configured)
    if not (pg_bin / 'initdb').exists():
        found = shutil.which('initdb')
        if not found:
            raise RuntimeError('PostgreSQL binaries unavailable; set PG_BIN')
        pg_bin = Path(found).parent
    with tempfile.TemporaryDirectory(prefix='finagent-postgres-') as tmp:
        data_dir = str(Path(tmp) / 'data')
        subprocess.run([str(pg_bin/'initdb'), '-D', data_dir, '-A', 'trust', '--no-locale', '-E', 'UTF8'], check=True, capture_output=True)
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            port = s.getsockname()[1]
        ctl = str(pg_bin/'pg_ctl')
        subprocess.run([ctl, '-D', data_dir, '-l', str(Path(tmp)/'postgres.log'), '-o', f'-p {port} -h 127.0.0.1 -k {tmp}', '-w', 'start'], check=True, capture_output=True)
        try:
            subprocess.run([str(pg_bin/'createdb'), '-h', '127.0.0.1', '-p', str(port), 'finagent'], check=True, capture_output=True)
            user = getpass.getuser()
            url = f'postgresql://{user}@127.0.0.1:{port}/finagent'
            env = dict(os.environ, E2E_DATABASE_URL=url.replace('postgresql://', 'postgresql+psycopg://'), E2E_CHECKPOINT_URL=url)
            sys.path.insert(0,str(ROOT/'backend'))
            from finagent.storage import Store, LeaseLost
            from datetime import datetime, timedelta, timezone
            from concurrent.futures import ThreadPoolExecutor
            # Fresh database: API and workers must safely initialize together.
            import threading
            barrier = threading.Barrier(8)
            def boot(_):
                barrier.wait()
                return Store(env['E2E_DATABASE_URL'])
            with ThreadPoolExecutor(max_workers=8) as pool:
                bootstrap_stores = list(pool.map(boot, range(8)))
            assert len(bootstrap_stores) == 8
            for item in bootstrap_stores:
                item.engine.dispose()
            print('POSTGRES_FRESH_BOOTSTRAP: 8 concurrent constructors PASS', flush=True)
            subprocess.run([sys.executable, str(ROOT/'scripts/e2e_demo.py')], cwd=ROOT, env=env, check=True)
            store = Store(env['E2E_DATABASE_URL'])
            expected = {store.submit('RUN',{'n':n},'pg-concurrent-'+str(n)) for n in range(8)}
            stores = [Store(env['E2E_DATABASE_URL']) for _ in range(12)]
            with ThreadPoolExecutor(max_workers=12) as pool:
                claimed = list(pool.map(lambda pair: pair[1].claim('pg-worker-'+str(pair[0]),60),enumerate(stores)))
            ids = [r['id'] for r in claimed if r]
            assert len(ids) == 8 and len(set(ids)) == 8 and set(ids) == expected
            # Finish those jobs so next synthetic time claim only sees the recovery job.
            for lease in claimed:
                if lease:
                    store.finish(lease,{'test':True})
            item = store.submit('RUN',{},'pg-recovery')
            old = store.claim('pg-dead',1,datetime.now(timezone.utc)-timedelta(seconds=2))
            new = store.claim('pg-new',60)
            assert old['id'] == new['id'] == item
            try:
                store.save_research(item,'NVDA',{'stale':True},lease=old)
            except LeaseLost:
                pass
            else:
                raise AssertionError('Postgres stale write was accepted')
            store.finish(new,{'recovered':True})
            print('POSTGRES_CHECKS: native graph checkpoints + HTTP worker restart + SKIP LOCKED concurrent claims + stale-owner fencing PASS')
        finally:
            subprocess.run([ctl,'-D',data_dir,'-m','fast','-w','stop'],check=True,capture_output=True)


if __name__ == '__main__':
    main()
