"""Standalone bounded asyncio job runner, fenced database leases and checkpoints."""
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
import os
import random
import signal as signal_module
from uuid import uuid4
from .contracts import (RunRequest, BacktestRequest, ResearchResult, FrozenSignal,
                        BenchmarkList, Mode, PITStatus, UniverseSnapshot, ResearchInput, VersionBundle, stable_hash)
from .storage import Store, LeaseLost, utcnow
from .config import execution_context


def decision_time(period: str) -> datetime:
    year = int(period[:4])
    start = datetime(year, 1 if period.endswith('H1') else 7, 1, tzinfo=timezone.utc)
    return start - timedelta(seconds=1)


@asynccontextmanager
async def checkpoint_saver(url: str):
    if url.startswith(('postgresql://', 'postgres://')):
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        async with AsyncPostgresSaver.from_conn_string(url) as saver:
            await saver.setup()
            yield saver
    else:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        async with AsyncSqliteSaver.from_conn_string(url.removeprefix('sqlite:///')) as saver:
            await saver.setup()
            yield saver


class Worker:
    def __init__(self, store: Store, checkpoint_url: str | None = None, concurrency: int | None = None,
                 lease_seconds: float | None = None):
        self.store = store
        self.checkpoint_url = checkpoint_url or os.environ.get('CHECKPOINT_URL', './checkpoints.db')
        self.concurrency = max(1, concurrency or int(os.environ.get('WORKER_CONCURRENCY', '3')))
        self.lease_seconds = lease_seconds or float(os.environ.get('WORKER_LEASE_SECONDS', '60'))
        self.owner = 'worker:' + str(uuid4())
        self.stop = asyncio.Event()

    async def _heartbeat(self, lease: dict):
        while True:
            await asyncio.sleep(max(.1, self.lease_seconds / 3))
            if not self.store.heartbeat(lease, self.lease_seconds):
                raise LeaseLost(lease['id'])

    async def run_once(self) -> bool:
        lease = self.store.claim(self.owner, self.lease_seconds)
        if lease is None:
            return False
        self.store.event(lease['id'], 'State', {'status': 'CLAIMED', 'attempts': lease['attempts'], 'job_id': lease['id']})
        pulse = asyncio.create_task(self._heartbeat(lease))
        work = asyncio.create_task(self._execute(lease))
        try:
            finished, _ = await asyncio.wait({pulse, work}, return_when=asyncio.FIRST_COMPLETED)
            if pulse in finished:
                pulse.result()
                raise LeaseLost(lease['id'])
            await work
        except LeaseLost:
            work.cancel()
            await asyncio.gather(work, return_exceptions=True)
        except asyncio.CancelledError:
            work.cancel()
            await asyncio.gather(work, return_exceptions=True)
            # A killed/interrupted process leaves a persistent lease, reclaimed on expiry.
            raise
        except Exception as exc:
            from .data import ProviderUnavailable
            transient = isinstance(exc, (TimeoutError, ConnectionError)) or getattr(exc, 'transient', False) or getattr(exc, 'code', None) == 'TRANSIENT_PROVIDER_ERROR'
            # Never persist raw provider exception text that may embed a token or URL.
            code = 'UNAVAILABLE' if isinstance(exc, ProviderUnavailable) or getattr(exc, 'code', None) == 'UNAVAILABLE' else ('TRANSIENT_PROVIDER' if transient else 'VALIDATION_FAILED')
            if isinstance(exc, ValueError) and str(exc) in {'EXECUTION_CONFIGURATION_CHANGED', 'FROZEN_RESEARCH_INPUT_CHANGED', 'IMMUTABLE_ARTIFACT_CONFLICT'}:
                code = str(exc)  # Fixed application codes only; no provider exception body.
            try:
                self.store.fail(lease, code, retry=transient and lease['attempts'] < 3,
                                delay=min(30, 2**lease['attempts']) + random.random())
                self.store.event(lease['id'], 'State', {'error_code': code, 'exception_type': type(exc).__name__, 'attempts': lease['attempts']})
            except LeaseLost:
                pass
        finally:
            pulse.cancel()
            await asyncio.gather(pulse, return_exceptions=True)
        return True

    async def _execute(self, lease: dict):
        if lease['kind'] == 'RUN':
            await self._research(lease)
        elif lease['kind'] == 'BACKTEST':
            await self._backtest(lease)
        else:
            raise ValueError('unknown job kind')

    async def _research(self, lease: dict):
        from .data import provider_for
        from .quant import screen_candidates, freeze_signal
        from .agents import research_stock, checkpoint_identity
        request = RunRequest.model_validate({k:v for k,v in lease['payload'].items() if k != 'execution_context'})
        context = lease['payload'].get('execution_context')
        if context and context != execution_context(request.mode, request.research_mode):
            raise ValueError('EXECUTION_CONFIGURATION_CHANGED')
        cutoff = request.decision_at or decision_time(request.period)
        provider = provider_for(request.mode)
        run_id = lease['id']
        self.store.event(run_id, 'Plan', {'period': request.period, 'mode': request.mode.value, 'research_mode': request.research_mode.value})
        saved_universe = self.store.artifact(run_id + ':universe')
        universe = UniverseSnapshot.model_validate(saved_universe) if saved_universe else await asyncio.to_thread(provider.universe, request.period, cutoff)
        if universe.available_at > cutoff or universe.as_of > cutoff or universe.period != request.period or universe.mode != request.mode or (request.mode == Mode.REAL and universe.pit_status != PITStatus.VERIFIED):
            raise ValueError('future universe')
        self.store.put_artifact(run_id + ':universe', 'UNIVERSE', universe.model_dump(mode='json'), lease=lease)
        self.store.event(run_id, 'Tools', {'universe_hash': universe.content_hash, 'count': len(universe.members)})
        inputs = []
        exclusions = []
        for member in universe.members:
            try:
                saved_input = self.store.artifact(run_id + ':input:' + member.ticker)
                value = ResearchInput.model_validate(saved_input) if saved_input else await asyncio.to_thread(provider.research_input, member.ticker, cutoff)
                if value.mode != request.mode or value.ticker != member.ticker or value.decision_at != cutoff:
                    raise ValueError('IMMUTABLE_INPUT_CONFIGURATION_MISMATCH')
                if context:
                    value = value.model_copy(update={'versions': value.versions.model_copy(update={'model': context['model']})})
                inputs.append(value)
                self.store.put_artifact(run_id + ':input:' + member.ticker, 'SNAPSHOT', value.model_dump(mode='json'), lease=lease)
            except ValueError as exc:
                exclusions.append({'ticker': member.ticker, 'reason': 'DATA_VALIDATION_FAILED'})
        candidates = screen_candidates(inputs, request.max_candidates)
        candidate_tickers = {c.ticker for c in candidates}
        exclusions.extend({'ticker': i.ticker, 'reason': 'QUANT_SCREEN_INELIGIBLE_OR_OUTSIDE_SHORTLIST'}
                          for i in inputs if i.ticker not in candidate_tickers)
        indexed = {i.ticker: i for i in inputs}
        sem = asyncio.Semaphore(self.concurrency)
        async with checkpoint_saver(self.checkpoint_url) as saver:
            async def one(candidate):
                async with sem:
                    saved = self.store.research(run_id, candidate.ticker)
                    if saved:
                        return ResearchResult.model_validate(saved)
                    input_ = indexed[candidate.ticker]
                    thread_id = ':'.join((run_id, candidate.ticker, input_.evidence.content_hash,
                                         input_.versions.graph, request.research_mode.value))
                    result = await research_stock(input_, request.research_mode, checkpointer=saver,
                                                  thread_id=thread_id, safety_margin=request.safety_margin)
                    # Screen score and factor policy are the frozen input to portfolio ranking.
                    result = ResearchResult.model_validate({**result.model_dump(mode='json'),
                        'score': candidate.score, 'factors': [f.model_dump(mode='json') for f in candidate.factors]})
                    if not self.store.heartbeat(lease, self.lease_seconds):
                        raise LeaseLost(run_id)
                    self.store.save_research(run_id, candidate.ticker, result.model_dump(mode='json'), lease=lease)
                    identity = checkpoint_identity(input_, request.research_mode, thread_id, request.safety_margin)
                    checkpoint = await saver.aget_tuple({'configurable': {'thread_id': identity}})
                    if checkpoint:
                        values = checkpoint.checkpoint.get('channel_values', {})
                        phase_map = {'Planning': 'Plan', 'Tool Execution': 'Tools', 'State Management': 'State',
                                     'Evidence Verification': 'Evidence', 'Result Synthesis': 'Output'}
                        allowed = {'phase', 'status', 'attempt', 'latency_ms', 'error_code', 'prompt_tokens',
                                   'completion_tokens', 'total_tokens', 'persona_count', 'snapshot_hash'}
                        for channel in ('audit_validation', 'audit_value', 'audit_growth', 'audit_conservative'):
                            for span in values.get(channel, []):
                                safe = {k: v for k, v in span.items() if k in allowed}
                                safe.update(ticker=candidate.ticker, checkpoint_id=checkpoint.checkpoint['id'],
                                            thread_id=identity, channel=channel)
                                self.store.event(run_id, phase_map.get(span.get('phase'), 'State'), safe)
                    self.store.event(run_id, 'Evidence', {'ticker': candidate.ticker, 'snapshot_id': input_.evidence.snapshot_id,
                        'snapshot_hash': input_.evidence.content_hash, 'eligible': result.eligible,
                        'graph_version': result.versions.graph, 'model_version': result.versions.model,
                        'prompt_version': result.versions.prompt, 'review_rounds': result.review_rounds})
                    return result
            tasks = [asyncio.create_task(one(c)) for c in candidates]
            try:
                results = await asyncio.gather(*tasks)
            except BaseException:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                raise
        exclusions.extend({'ticker': r.ticker, 'reason': ','.join(r.exclusion_reasons)}
                          for r in results if not r.eligible)
        self.store.progress(lease, 90)
        config_hash = stable_hash(lease['payload'])
        # Historical DEMO replays the modeled release; real execution audit time is stored separately.
        frozen = freeze_signal(results, run_id=run_id, period=request.period, decision_at=cutoff,
                               frozen_at=cutoff, mode=request.mode, config_hash=config_hash,
                               max_per_sector=request.max_per_sector)
        warnings = list(universe.survivorship_warning and [universe.survivorship_warning] or [])
        if cutoff < utcnow():
            warnings.append('Retrospective research: modeled release chronology; actual job/audit creation is wall-clock. Historical LLM knowledge contamination remains possible.')
        if request.mode == Mode.DEMO:
            warnings += ['DEMO / SYNTHETIC: all prices, financials and return paths are invented fixtures.',
                         'Synthetic session calendar; not validated historical investment performance.']
        if frozen:
            self.store.put_artifact(frozen.signal_id, 'FROZEN_SIGNAL', frozen.model_dump(mode='json'), lease=lease)
            payload = {'signal': frozen.model_dump(mode='json'), 'picks': [p.model_dump(mode='json') for p in frozen.picks],
                       'warnings': warnings + list(frozen.warnings), 'exclusions': exclusions}
            self.store.finish(lease, payload)
        else:
            status = 'UNAVAILABLE' if results and not any(r.eligible for r in results) and any('UNAVAILABLE' in reason for r in results for reason in r.exclusion_reasons) else 'INSUFFICIENT_ELIGIBLE_STOCKS'
            self.store.finish(lease, {'signal': None, 'picks': [], 'warnings': warnings,
                'exclusions': exclusions, 'reason': status, 'eligible_count': sum(r.eligible for r in results)},
                status=status)
        self.store.event(run_id, 'Output', {'frozen': frozen is not None, 'picks': len(frozen.picks) if frozen else 0})

    async def _backtest(self, lease: dict):
        from .data import provider_for
        from .backtest import run_backtest
        request = BacktestRequest.model_validate({k:v for k,v in lease['payload'].items() if k not in ('execution_context','benchmark','submitted_request')})
        run = self.store.get(request.run_id)
        if not run or not run['result'] or not run['result'].get('signal'):
            raise ValueError('missing frozen signal')
        frozen = FrozenSignal.model_validate(run['result']['signal'])
        context = lease['payload'].get('execution_context')
        if context and context != execution_context(frozen.mode):
            raise ValueError('EXECUTION_CONFIGURATION_CHANGED')
        provider = provider_for(frozen.mode)
        if frozen.mode == Mode.REAL:
            # Execution data may append post-cutoff observations; decision inputs
            # and universe remain byte-for-byte frozen apart from runtime versions.
            current_universe = await asyncio.to_thread(provider.universe, frozen.period, frozen.decision_at)
            if current_universe.model_dump(mode='json') != self.store.artifact(request.run_id + ':universe'):
                raise ValueError('FROZEN_RESEARCH_INPUT_CHANGED')
            for pick in frozen.picks:
                saved = self.store.artifact(request.run_id + ':input:' + pick.ticker)
                current = await asyncio.to_thread(provider.research_input, pick.ticker, frozen.decision_at)
                saved_input = ResearchInput.model_validate(saved) if saved else None
                if not saved_input or current.model_dump(mode='json', exclude={'versions'}) != saved_input.model_dump(mode='json', exclude={'versions'}):
                    raise ValueError('FROZEN_RESEARCH_INPUT_CHANGED')
        raw_benchmark = lease['payload'].get('benchmark')
        benchmark = BenchmarkList.model_validate(raw_benchmark) if raw_benchmark else None
        result = await asyncio.to_thread(run_backtest, frozen, provider, backtest_id=lease['id'],
            as_of=request.as_of or utcnow(), benchmark=benchmark,
            transaction_cost_bps=request.transaction_cost_bps, slippage_bps=request.slippage_bps, policy=request.policy)
        self.store.finish(lease, result.model_dump(mode='json'))
        self.store.event(lease['id'], 'Output', {'signal_id': frozen.signal_id, 'backtest_status': result.status.value,
                                              'sa_status': result.seeking_alpha_status})

    async def run(self):
        while not self.stop.is_set():
            worked = await self.run_once()
            if not worked:
                try:
                    await asyncio.wait_for(self.stop.wait(), timeout=.5)
                except TimeoutError:
                    pass


async def main():
    store = Store(os.environ.get('DATABASE_URL', 'sqlite:///./finagent.db'))
    worker = Worker(store)
    loop = asyncio.get_running_loop()
    for signum in (signal_module.SIGINT, signal_module.SIGTERM):
        loop.add_signal_handler(signum, worker.stop.set)
    await worker.run()


if __name__ == '__main__':
    asyncio.run(main())
