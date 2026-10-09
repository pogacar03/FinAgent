"""Durable app state; PostgreSQL production, SQLite development only.

Every lease commit is fenced by a random token and expiry. Completed results
and ticker research are insert-once; HTTP processes never execute research.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from typing import Any
import json
from sqlalchemy import (create_engine, MetaData, Table, Column, String, Integer,
                        Float, Text, select, update, insert, and_, or_, delete, text)
from sqlalchemy.exc import IntegrityError


class LeaseLost(RuntimeError):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def encoded(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


metadata = MetaData()
jobs = Table('research_jobs', metadata,
    Column('id', String, primary_key=True), Column('kind', String, nullable=False),
    Column('fingerprint', String, unique=True, nullable=False), Column('payload', Text, nullable=False),
    Column('status', String, nullable=False), Column('attempts', Integer, nullable=False, default=0),
    Column('created_at', Float, nullable=False), Column('updated_at', Float, nullable=False),
    Column('lease_until', Float), Column('lease_token', String), Column('owner', String),
    Column('retry_at', Float, nullable=False, default=0), Column('result', Text),
    Column('error', Text), Column('progress', Integer, nullable=False, default=0))
research = Table('agent_reports', metadata, Column('run_id', String, primary_key=True),
    Column('ticker', String, primary_key=True), Column('result', Text, nullable=False))
artifacts = Table('immutable_artifacts', metadata, Column('id', String, primary_key=True),
    Column('kind', String, nullable=False), Column('payload', Text, nullable=False))
audit = Table('audit_events', metadata, Column('id', String, primary_key=True),
    Column('run_id', String, nullable=False), Column('phase', String, nullable=False),
    Column('timestamp', Float, nullable=False), Column('metadata', Text, nullable=False))
benchmarks = Table('benchmark_revisions', metadata, Column('id', String, primary_key=True),
    Column('period', String, nullable=False), Column('payload', Text, nullable=False),
    Column('created_at', Float, nullable=False))
versions = Table('schema_versions', metadata, Column('version', Integer, primary_key=True))


class Store:
    def __init__(self, url: str):
        self.url = url
        self.engine = create_engine(url, pool_pre_ping=True,
            connect_args={'check_same_thread': False, 'timeout': 30} if url.startswith('sqlite') else {})
        with self.engine.begin() as connection:
            if self.engine.dialect.name == 'postgresql':
                connection.execute(text('SELECT pg_advisory_xact_lock(6134757681)'))
            elif self.engine.dialect.name == 'sqlite':
                connection.exec_driver_sql('BEGIN IMMEDIATE')
            metadata.create_all(connection)
        self._insert_once(versions, {'version': 1}, versions.c.version == 1)

    def _insert_once(self, table: Table, values: dict, key: Any, lease: dict | None = None, strict_payload: bool = False) -> None:
        try:
            with self.engine.begin() as c:
                if lease is not None:
                    # UPDATE locks the lease row until the result insert commits.
                    fenced = c.execute(update(jobs).where(self._fence(lease, utcnow().timestamp())).values(updated_at=utcnow().timestamp()))
                    if fenced.rowcount != 1:
                        raise LeaseLost(lease['id'])
                c.execute(insert(table).values(**values))
        except IntegrityError:
            with self.engine.connect() as c:
                existing = c.execute(select(table).where(key)).mappings().first()
                if existing is None:
                    raise
                if strict_payload and existing['payload'] != values['payload']:
                    raise ValueError('IMMUTABLE_ARTIFACT_CONFLICT') from None

    def submit(self, kind: str, payload: dict, fingerprint: str) -> str:
        item_id = str(uuid4())
        now = utcnow().timestamp()
        self._insert_once(jobs, dict(id=item_id, kind=kind, fingerprint=fingerprint,
            payload=encoded(payload), status='QUEUED', attempts=0, created_at=now,
            updated_at=now, retry_at=0, progress=0), jobs.c.fingerprint == fingerprint)
        with self.engine.connect() as c:
            return c.execute(select(jobs.c.id).where(jobs.c.fingerprint == fingerprint)).scalar_one()

    def get(self, item_id: str) -> dict | None:
        with self.engine.connect() as c:
            row = c.execute(select(jobs).where(jobs.c.id == item_id)).mappings().first()
        if row is None:
            return None
        out = dict(row)
        for key in ('payload', 'result'):
            out[key] = json.loads(out[key]) if out[key] else None
        # Lease tokens are internal, never exposed through an API.
        return out

    def by_fingerprint(self, fingerprint: str) -> dict | None:
        with self.engine.connect() as c:
            item_id = c.execute(select(jobs.c.id).where(jobs.c.fingerprint == fingerprint)).scalar_one_or_none()
        return self.get(item_id) if item_id else None

    def list_runs(self, limit: int = 30) -> list[dict]:
        with self.engine.connect() as c:
            ids = c.execute(select(jobs.c.id).where(jobs.c.kind == 'RUN').order_by(jobs.c.created_at.desc()).limit(limit)).scalars().all()
        return [self.get(i) for i in ids]

    def claim(self, owner: str, lease_seconds: float = 60, now: datetime | None = None) -> dict | None:
        stamp = (now or utcnow()).timestamp()
        eligible = or_(and_(jobs.c.status == 'QUEUED', jobs.c.retry_at <= stamp),
                       and_(jobs.c.status == 'RUNNING', jobs.c.lease_until <= stamp))
        # SKIP LOCKED for Postgres; CAS remains necessary for SQLite contenders.
        with self.engine.begin() as c:
            query = select(jobs).where(eligible).order_by(jobs.c.created_at).limit(1)
            if self.engine.dialect.name == 'postgresql':
                query = query.with_for_update(skip_locked=True)
            row = c.execute(query).mappings().first()
            if row is None:
                return None
            token = str(uuid4())
            changed = c.execute(update(jobs).where(jobs.c.id == row['id'], eligible)
                .values(status='RUNNING', owner=owner, lease_token=token, lease_until=stamp+lease_seconds,
                        attempts=jobs.c.attempts+1, updated_at=stamp, error=None))
            if changed.rowcount != 1:
                return None
        result = self.get(row['id'])
        return result

    @staticmethod
    def _fence(lease: dict, stamp: float):
        return and_(jobs.c.id == lease['id'], jobs.c.status == 'RUNNING',
                    jobs.c.lease_token == lease['lease_token'], jobs.c.lease_until > stamp)

    def heartbeat(self, lease: dict, lease_seconds: float = 60) -> bool:
        stamp = utcnow().timestamp()
        with self.engine.begin() as c:
            row = c.execute(update(jobs).where(self._fence(lease, stamp)).values(lease_until=stamp+lease_seconds, updated_at=stamp))
            return row.rowcount == 1

    def finish(self, lease: dict, result: dict, status: str = 'COMPLETED', now: datetime | None = None) -> None:
        stamp = (now or utcnow()).timestamp()
        with self.engine.begin() as c:
            row = c.execute(update(jobs).where(self._fence(lease, stamp)).values(status=status,
                result=encoded(result), progress=100, updated_at=stamp, lease_token=None, lease_until=None))
            if row.rowcount != 1:
                raise LeaseLost(lease['id'])

    def fail(self, lease: dict, error: str, retry: bool = False, delay: float = 1) -> None:
        stamp = utcnow().timestamp()
        with self.engine.begin() as c:
            row = c.execute(update(jobs).where(self._fence(lease, stamp)).values(
                status='QUEUED' if retry else 'FAILED', error=error, updated_at=stamp,
                retry_at=stamp+delay, lease_token=None, lease_until=None))
            if row.rowcount != 1:
                raise LeaseLost(lease['id'])

    def progress(self, lease: dict, percent: int) -> None:
        stamp = utcnow().timestamp()
        with self.engine.begin() as c:
            row = c.execute(update(jobs).where(self._fence(lease, stamp)).values(progress=percent, updated_at=stamp))
            if row.rowcount != 1:
                raise LeaseLost(lease['id'])

    def save_research(self, run_id: str, ticker: str, result: dict, lease: dict | None = None) -> None:
        self._insert_once(research, {'run_id': run_id, 'ticker': ticker, 'result': encoded(result)},
                          and_(research.c.run_id == run_id, research.c.ticker == ticker), lease=lease)

    def research(self, run_id: str, ticker: str | None = None) -> dict | list[dict] | None:
        with self.engine.connect() as c:
            query = select(research).where(research.c.run_id == run_id)
            if ticker:
                query = query.where(research.c.ticker == ticker)
            rows = c.execute(query.order_by(research.c.ticker)).mappings().all()
        if ticker:
            return json.loads(rows[0]['result']) if rows else None
        return [json.loads(row['result']) for row in rows]

    def put_artifact(self, item_id: str, kind: str, payload: dict, lease: dict | None = None) -> None:
        self._insert_once(artifacts, {'id': item_id, 'kind': kind, 'payload': encoded(payload)}, artifacts.c.id == item_id, lease=lease, strict_payload=True)

    def artifact(self, item_id: str) -> dict | None:
        with self.engine.connect() as c:
            value = c.execute(select(artifacts.c.payload).where(artifacts.c.id == item_id)).scalar_one_or_none()
        return json.loads(value) if value else None

    def save_benchmark(self, payload: dict) -> None:
        key = payload['period'] + ':' + payload['content_hash']
        self._insert_once(benchmarks, {'id': key, 'period': payload['period'], 'payload': encoded(payload),
                                    'created_at': utcnow().timestamp()}, benchmarks.c.id == key)

    def benchmark_revisions(self, period: str) -> list[dict]:
        with self.engine.connect() as c:
            rows = c.execute(select(benchmarks.c.payload).where(benchmarks.c.period == period)
                             .order_by(benchmarks.c.created_at.desc())).scalars().all()
        return [json.loads(r) for r in rows]

    def benchmark(self, period: str) -> dict | None:
        revisions = self.benchmark_revisions(period)
        return next((r for r in revisions if r['verification_status'] == 'PIT_VERIFIED'),
                    revisions[0] if revisions else None)

    def event(self, run_id: str, phase: str, details: dict) -> None:
        # Only controlled metadata, never environment, credentials or raw prompts.
        with self.engine.begin() as c:
            c.execute(insert(audit).values(id=str(uuid4()), run_id=run_id, phase=phase,
                                         timestamp=utcnow().timestamp(), metadata=encoded(details)))

    def events(self, run_id: str) -> list[dict]:
        with self.engine.connect() as c:
            rows = c.execute(select(audit).where(audit.c.run_id == run_id).order_by(audit.c.timestamp)).mappings().all()
        return [dict(id=r['id'], phase=r['phase'], timestamp=r['timestamp'], metadata=json.loads(r['metadata'])) for r in rows]
