import type { BacktestJob, BenchmarkList } from './api';

export type BacktestBenchmarkSource =
  | { kind: 'pinned'; benchmark: BenchmarkList }
  | { kind: 'not_bound' }
  | { kind: 'unknown_legacy' };

export function resolveBacktestBenchmark(job: BacktestJob): BacktestBenchmarkSource {
  const payload = job.payload;
  if (!payload || !Object.prototype.hasOwnProperty.call(payload, 'benchmark')) {
    return { kind: 'unknown_legacy' };
  }
  const benchmark = payload.benchmark;
  if (benchmark === undefined) return { kind: 'unknown_legacy' };
  if (benchmark === null) return { kind: 'not_bound' };
  return { kind: 'pinned', benchmark };
}
