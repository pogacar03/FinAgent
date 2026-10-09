# Phase 2 independent critical review

2026-10-09. Requested configuration: `gpt-6.1-sol`, High. This report does not
claim separate routing to Fast or independently verified provider routing.
Ownership was read-only for implementation, scripts, tests and other reports;
the reviewer wrote only this report and created no commit.

Read `AGENTS.md`, binding V2, the frozen architecture, phase 2 reports and actual
pilot, observability, worker, storage, agent, benchmark and Compose smoke code.
Applied verification-before-completion: conclusions below use executed checks,
not another agent's completion claim.

## Defects found and independently verified after owner fixes

1. **P1 — replay could skip final financial/PIT result checks.** On a temporary
   copy of the actual `024842191325Z` execution record, deleting
   `observed_financial_facts` and replacing valuation with target `9999` and
   backtest return `42` originally returned replay `PASSED`. Changing the
   top-level status to `PASSED`, financial snapshot revenue to `1`, or financial
   PIT status also passed. The original owner replaced optional-field-driven
   checks with source-byte-driven recomputation and domain field comparison.
   Independently reran the same four corruptions against actual record
   `artifacts/real-pilot/20261009T025017981795Z/execution.json`: all rejected with
   `REPLAY_DOMAIN_FIELD_MISMATCH` for the appropriate field. The unchanged
   actual record replayed `PASSED` with zero network calls; its financial
   evidence remains partial research evidence and accepted valuation/total
   return remain `UNAVAILABLE`.
2. **P2 — malformed HTTP 200 source responses aborted evidence reporting.**
   Actual healthy issuer-release bytes plus mocked `b'[]'` responses for the
   market endpoints originally raised `AttributeError` and wrote no execution
   record. The owner added explicit response shape checks. Independently reran
   that same input: overall `PARTIAL`, price/actions/diagnostic `UNAVAILABLE`,
   one execution record saved, and its offline replay passed. No invented data
   filled the gaps.

Both defects were sent to the original data owner and resolved there. No
unresolved concrete blocker was found in this review's inspected scope.
The final acquired record `20261009T025343313311Z/execution.json` was also
independently replayed: `PASSED`, zero network calls, chain `PARTIAL`, accepted
valuation and six-month total return `UNAVAILABLE` with null numeric outputs.

## Executed validation

- Existing pre-phase-2 test files: **113 passed in 6.08s**, exit 0. Original
  tests were not edited. The earlier 98-test delivery is historical; subsequent
  existing CI guard tests explain the current baseline of 113.
- Phase-focused pilot/observability/trace/recovery/benchmark suite after fixes:
  **39 passed in 2.66s**, exit 0.
- Full offline suite: **149 passed in 7.31s**, exit 0.
- Latest agent/observability/trace suite after the final HTTP scope change:
  **29 passed in 1.85s**, exit 0.
- Latest HTTP scope was also checked directly after the root's final agent
  integration. An offline mocked HTTP call sleeping 3 ms produced one actual
  SDK Tool Calling span lasting 3.513 ms; the sensitive fixture key and raw
  prompt were absent. Boolean and negative provider token values were excluded;
  the valid fixture total of 45 was retained. Forced SDK initialization failure
  preserved exactly one HTTP call and the valid typed report. These are mocks,
  with **zero live LLM calls**.
- A separate offline mocked 503-to-200 retry ran two HTTP attempts and recorded
  two measured request latencies, 2.339 and 2.497 ms, without exporting the
  sensitive fixture key. These values establish instrumentation behavior,
  not real provider latency.

## Inspected execution artifacts and limits

`artifacts/traces/phase2-e2e.jsonl` passed the actual CI `trace_evidence` function
for research run `d6bc85be-e14f-46d3-ac5e-a31ae9abaa33`: trace
`6089cc0da86f41ebd80b16d554edc35f`, 105 correlated spans, all five stages, and
null DEMO LLM metrics. The separate backtest job has four spans and is not
evidence of a five-stage research trace; the guard evaluates the research run.
SDK tests exercised local write failure and actual unreachable localhost OTLP
transport without interrupting business execution. Langfuse ingestion/UI and
real LLM token, cost and latency remain **UNVERIFIED**.

Independently inspected the preliminary benchmark `phase2_demo_benchmark_20261009T024924Z.json` and final benchmark `phase2_demo_benchmark_20261009T025600Z.json`:
18 observations, zero failures, one common snapshot digest, null LLM metrics;
each of six recovery observations retained one ticker and redid nine with
integrity recorded true. It uses actual local API/Worker/native SQLite state,
with identical requests and tracing configuration. It measures DEMO throughput,
completed-job HTTP idempotency and interruption recovery. It establishes no
investment outperformance or real LLM speedup. The final artifact is `PASSED`
with 18 records and zero failures; every recorded backend/script source hash
was compared with the current file bytes and matched. Its six recovery trials
again retain one ticker and redo nine; snapshot digests match and all LLM
metrics remain null.

This reviewer ran no Docker stack, live Langfuse ingestion, SEC archive request,
or live LLM request, and does not count local fixtures as proof of those paths.
