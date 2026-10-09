# Phase 2 benchmark implementation report

## Result

**PASSED:** the local deterministic DEMO benchmark completed 18 observations
(three repetitions for each of two worker strategies across cold start,
completed-job idempotency replay, and worker recovery), with zero failures.
The output records input and snapshot hashes, run IDs, checkpoint IDs, timings,
recovery counts, model/strategy versions, and execution environment.

**PASSED:** `tests/test_benchmark_runner.py` reports 5 passed. It verifies
strategy input/model hash equality, rejection of mismatched input/model
observations, and JSON/CSV persistence of observations and failures. The actual
benchmark command also completed successfully:

```text
.venv/bin/python scripts/benchmark_e2e.py
status=PASSED observations=18 failures=0
```

## Measured baseline

| Scenario | Serial median (min–max), ms | Bounded 3 median (min–max), ms |
| --- | ---: | ---: |
| Cold start, API submission through completed worker | 454.578 (445.565–455.660) | 445.676 (436.452–451.574) |
| Completed-job idempotency replay API request | 1.304 (1.153–1.327) | 1.205 (1.200–1.296) |
| Interrupt, expire lease, restart and complete | 896.735 (878.377–906.660) | 893.976 (850.306–916.918) |

The recovery restart portion medians were 382.104 ms serial and 382.958 ms
bounded-3; lease-wait medians were 309.175 ms and 314.597 ms. Each of the six
recovery trials retained one completed ticker and redid nine. It verified the
same ten final results, two worker attempts, and no repeat of the retained
ticker. The measured differences are small and should be treated as descriptive
DEMO observations, not a reliable speedup claim.

## Scope and evidence

* All trials used the exact request hash
  `d08097b75bac6c5a4e4dde81a65cf78fd08a54dbf96d6ba55ae2009c522dc828`, semantic
  input hash `37e599e162730510852053b448d8b525f807b57e627ee11fb40e57621af08cca`,
  `multi_persona`, and `deterministic-demo-v1`.
* The source-snapshot digest matched in every scenario:
  `bb768b0f125e8c0abd537bf67abaaa2ba1f2ecbb3a4eb3d005406c800f940841`.
* Completed-job replay uses the API's existing idempotency behavior and verifies
  that the replay returns the same `COMPLETED` run ID. It is not a claim about
  provider, report, or checkpoint cache reuse.
* Recovery uses a real FastAPI submission, `Worker`, SQLite store, and native
  SQLite checkpoint. It cancels after one ticker result is saved, lets the
  fenced lease expire, then opens a new store and worker on the same files.
* Environment: CPython 3.11.14, macOS 15.3.2 arm64, SQLite 3.53.0, FastAPI
  0.142.4, Pydantic 2.13.5, SQLAlchemy 2.1.4, LangGraph 1.2.14, and
  langgraph-checkpoint-sqlite 3.1.1. OpenTelemetry API, SDK and OTLP HTTP
  exporter were 1.45.1. Local JSONL traces were enabled; Langfuse remote export
  was disabled and credentials were absent. Captured repository revision was
  `1bcedb6fc8374a09748d26fbb10b6e4ff5537c21`; the worktree was dirty during the
  run, so the recorded measurements correspond to local source state. This
  run includes the HTTP SDK scope and token logging guard. Metadata includes
  SHA-256 for each `.py`/`.sh` file under `backend/` and `scripts/` (19 files),
  combined source-tree SHA-256
  `06d440f14ccb5f51d5e882fa509df6ca117fabc624f408dbd8af8326ab2b9b79`, and
  environment fingerprint
  `9dad12d5d3eac466b456981e16478a9b0cc77695968fae67e4ed7a25fbeb33db`.
  Post-run verification confirmed the captured source hashes and environment
  fingerprint match the current source and runtime.
* **UNVERIFIED:** actual LLM latency and token consumption. The run was offline
  DEMO with no LLM calls; both metrics are null. No real market data or
  investment returns are measured.
* Docker/PostgreSQL validation is outside this benchmark subtask and is not
  claimed here.

## Files and Git

Implementation: `scripts/benchmark_e2e.py`; tests:
`tests/test_benchmark_runner.py`; run procedure and measured summary:
`docs/BENCHMARK.md`. Raw artifacts:

* Final integrated baseline:
  `docs/benchmark_results/phase2_demo_benchmark_20261009T025600Z.json`
  and `docs/benchmark_results/phase2_demo_benchmark_20261009T025600Z.csv`.
* Prior runs retained separately:
  `docs/benchmark_results/phase2_demo_benchmark_20261009T024550Z.json`
  and `.csv`, and
  `docs/benchmark_results/phase2_demo_benchmark_20261009T024924Z.json` and
  `.csv`.

No commit was created. Other files were already modified by concurrent phase
work; this agent changed only the benchmark-owned files listed above.
