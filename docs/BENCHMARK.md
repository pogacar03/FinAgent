# Local E2E benchmark

`scripts/benchmark_e2e.py` measures the existing offline DEMO run path with
`multi_persona` research. It compares `Worker(concurrency=1)` with bounded
`Worker(concurrency=3)` under the same submitted request, synthetic provider,
strategy/graph/prompt/model versions, Python process, and machine.

The default run executes three repetitions for each strategy in each scenario
(18 raw observations total):

1. **Cold start** creates a fresh SQLite application store and native SQLite
   LangGraph checkpoint, submits through the FastAPI endpoint, and executes the
   actual worker. Its wall time includes store/checkpoint creation, submission,
   worker execution, and completion verification.
2. **Completed-job idempotency reuse** first creates a real completed job, then
   times a second API submission using the same request and idempotency key. The
   timed section is only the replay request and completed-job lookup. This is
   explicitly the job idempotency path; it does not claim to measure report,
   provider, or checkpoint cache layers.
3. **Worker recovery** interrupts a live worker after one ticker's research has
   been persisted, waits for its lease to expire, opens a new store/worker on
   the same SQLite files, and completes the run. The record includes retained
   tickers, tickers redone after restart, lease waiting time, restart execution
   time, and full scenario wall time.

Run from the repository root with the project virtual environment:

```sh
.venv/bin/python scripts/benchmark_e2e.py
.venv/bin/python -m pytest -q tests/test_benchmark_runner.py
```

Use `--output-dir PATH` to choose where timestamped JSON and CSV files are
written. `--repeats N` accepts values of at least three. The runner writes its
files before executing and rewrites them after every observation, so interrupted
runs retain collected observations and failures. Exit status is nonzero when
any scenario fails or the required observations are incomplete.

Each JSON document records raw observations, failures, input and source-snapshot
hashes, model/strategy versions, Python/OS/dependency metadata, repository
revision/dirty state, SHA-256 for each Python/shell source file under `backend/`
and `scripts/` plus a combined source-tree hash, run and checkpoint identity,
and scenario timing. OpenTelemetry API, SDK, and OTLP exporter package versions,
plus local/remote tracing configuration state without credentials or raw
endpoints, are part of the dependency/environment fingerprint. CSV is a
row-per-observation export of those raw records. All API submissions share the
same fixed request and idempotency key; each observation is checked against the
same request and semantic input hashes and deterministic DEMO model version.

The provider is deterministic and synthetic. Its timings describe this local
DEMO implementation only. No LLM request occurs, so LLM latency and token usage
are `null`, and real LLM performance remains `UNVERIFIED`. No investment return
or performance claim is calculated by this benchmark. Three repetitions are a
small descriptive baseline, not a statistically powered performance study.

## Executed baseline

The recorded run on 2026-10-09 completed all 18 observations with no failures.
This is the final run after the HTTP SDK scope and token logging guard were
integrated. It used CPython 3.11.14 on macOS 15.3.2 / arm64 (8 reported CPUs), SQLite
3.53.0, LangGraph 1.2.14, OpenTelemetry SDK and OTLP HTTP exporter 1.45.1, and the request hash
`d08097b75bac6c5a4e4dde81a65cf78fd08a54dbf96d6ba55ae2009c522dc828`.
All runs used `multi_persona`, `deterministic-demo-v1`, and identical
source-snapshot hashes (`bb768b0f125e8c0abd537bf67abaaa2ba1f2ecbb3a4eb3d005406c800f940841`).
OpenTelemetry worker tracing and the local JSONL exporter were enabled; the
Langfuse remote exporter was disabled and no credentials were configured. The
`backend/` + `scripts/` source-tree SHA-256 was
`06d440f14ccb5f51d5e882fa509df6ca117fabc624f408dbd8af8326ab2b9b79` across 19
Python/shell source files. The full per-file hashes and environment fingerprint
`9dad12d5d3eac466b456981e16478a9b0cc77695968fae67e4ed7a25fbeb33db` are in the
JSON. Post-run verification confirmed all 19 captured source hashes and the
environment fingerprint match the current source and runtime.

| Scenario | Serial median (range), ms | Bounded 3 median (range), ms | Serial minus bounded median, ms |
| --- | ---: | ---: | ---: |
| Cold start through completion | 454.578 (445.565–455.660) | 445.676 (436.452–451.574) | 8.902 |
| Completed-job idempotency replay | 1.304 (1.153–1.327) | 1.205 (1.200–1.296) | 0.099 |
| Interrupt, lease expiry and recovery | 896.735 (878.377–906.660) | 893.976 (850.306–916.918) | 2.759 |

In recovery runs, the restart portion had a 382.104 ms serial median and a
382.958 ms bounded-3 median; lease waiting medians were 309.175 ms and
314.597 ms. All six runs retained one saved ticker and researched the other
nine after restart. These small observed differences do not establish a
reliable parallel speedup. Both recovery ranges include run-to-run variation,
which is why ranges are shown beside medians.

Raw observations and environment metadata are in
[`phase2_demo_benchmark_20261009T025600Z.json`](benchmark_results/phase2_demo_benchmark_20261009T025600Z.json)
and [`phase2_demo_benchmark_20261009T025600Z.csv`](benchmark_results/phase2_demo_benchmark_20261009T025600Z.csv).
The `024550Z` and `024924Z` files remain as historical preliminary runs; the
`025600Z` pair records the latest frozen source including the HTTP SDK scope and
token logging guard. The final JSON reports
`PASSED` for this DEMO run, `real_llm_benchmark: UNVERIFIED`, and null LLM
latency/token fields.
