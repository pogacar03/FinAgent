# Implementation plan and acceptance gates

This plan is active implementation guidance, not a delivery assertion. Root
maintains final implemented/incomplete status in STATUS.md. Architecture and
ownership are frozen in ARCHITECTURE_FROZEN.md and CODEX_PARALLEL_START.md.

1. Freeze typed immutable contracts; test timestamps, evidence integrity,
   exact-ten/equal-weight signals, abstention, valuation guards, fair intervals.
2. Root scaffolds Python/React/Compose and SQLAlchemy persistence. Verify job
   deduplication, owner/token fencing, expiry takeover, result idempotency.
3. Implement a dated synthetic universe, historical snapshots and future-only
   execution bars/actions. REAL requires verified provider configuration and
   raises explicit unavailability if absent. Test future-data rejection and
   zero silent substitutions.
4. Implement deterministic factor handling, valuation, sector-aware selection
   and backtest accounting. Missing EPS revisions remain missing with a stated
   policy. Verify synthetic 199/159.20 example, ten/shortfall, cash/cost/action
   accounting, missing SA, common sessions, calendar maturity and look-ahead.
5. Implement actual LangGraph fan-out/fan-in. Isolate each persona's context,
   validate references and common basis/horizon; at most one review. Distinct
   quant-only/single/multi/debate modes. Verify native checkpoint resume and
   deterministic offline execution without live LLM calls.
6. Root integrates worker leases, persisted progress/events and typed HTTP
   endpoints. Transient retry is bounded; PIT/data failures are terminal.
   Force interruption after partial work, restart worker and assert completed
   ticker results are reused and no duplicate signal is produced.
7. Frontend renders real API state in Chinese: mode badges, progress, Top10,
   evidence/persona/valuation detail and comparison/unavailability diagnostics.
   Build/typecheck and inspect UI through the running app.
8. Root runs final offline suite and actual HTTP E2E demo. Record exact test
   counts, build output, demo identifiers and limitations. Attempt Compose only
   if Docker is present; report unavailable prerequisites without claiming a
   container startup succeeded. Document clean local startup as tested fallback.

## Acceptance matrix

| Gate | Observable evidence | Owner |
|---|---|---|
| Frozen schemas | tests/test_contracts.py passes | architect |
| Historical admissibility | late financial/evidence rejection; source/mode consistency | data + architect |
| Provider honesty | REAL missing bundle UNAVAILABLE, DEMO conspicuous synthetic labels | data + root + UI |
| Graph isolation | real LangGraph nodes; private contexts; typed evidence references | agents |
| Arithmetic | weighted target/entry deterministic; invalid inputs abstain | quant |
| Selection | unique exact ten or explicit shortfall; deterministic tie policy | quant |
| Frozen replay | altering future bars changes backtest only; no LLM invoked | quant + root |
| Fair comparison | common sessions, split/dividend convention, verified SA only | quant |
| Immature period | PENDING with no realized return/excess | quant |
| Durability | stale lease denied; takeover; resume finished ticker outputs | root + agents |
| API | actual typed run/research/backtest data, semantic error codes | root |
| UI | live API pages, no assumed winner, missing-data badges | frontend + root |
| Reuse | official native APIs; locked versions/licenses; no giant copied repo | root |

Baseline measurements must be measured later: per-run wall time, completed
tickers/second, failed/retried jobs, checkpoint resume reuse, database claim
latency, tokens/cost only when returned by a provider, and coverage counts.
Do not invent performance improvement percentages or backtest alpha.
