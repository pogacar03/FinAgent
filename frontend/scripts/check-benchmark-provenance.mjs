import assert from 'node:assert/strict';
import { resolveBacktestBenchmark } from '../src/benchmarkProvenance.ts';

const source = {
  period: '2025-H2',
  tickers: Array.from({ length: 10 }, (_, index) => `T${index}`),
  source_uri: 'https://example.com/list',
  published_at: '2025-07-01T12:00:00Z',
  content_hash: 'a'.repeat(64),
  verification_status: 'PIT_VERIFIED',
  verification_note: 'Verified source fixture for this focused UI check.',
};
const job = { backtest_id: 'bt-1', status: 'COMPLETED' };

assert.deepEqual(resolveBacktestBenchmark({ ...job, payload: { run_id: 'run-1', benchmark: source } }), {
  kind: 'pinned',
  benchmark: source,
});
assert.deepEqual(resolveBacktestBenchmark({ ...job, payload: { run_id: 'run-1', benchmark: null } }), { kind: 'not_bound' });
assert.deepEqual(resolveBacktestBenchmark({ ...job, payload: { run_id: 'run-1' } }), { kind: 'unknown_legacy' });
assert.deepEqual(resolveBacktestBenchmark({ ...job, payload: { run_id: 'run-1', benchmark: undefined } }), { kind: 'unknown_legacy' });
assert.deepEqual(resolveBacktestBenchmark(job), { kind: 'unknown_legacy' });

console.log('Backtest benchmark provenance: pinned, absent, and legacy cases passed.');
