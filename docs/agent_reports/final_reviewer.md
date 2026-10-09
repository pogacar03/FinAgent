# Final full-app review — 2026-10-08

Requested assignment: gpt-6.1-sol / High. Routing/billing metadata is not independently exposed. Review was read-only except this report; no code, dependency, commit or subagent changes. Original `backend_reviewer.md` preserved.

## Verdicts

**SPEC COMPLIANCE: PASS for the documented MVP, with environment/data prerequisites surfaced.** All eight baseline findings and six follow-on findings are addressed. No remaining reproduced P0/P1/P2 reviewer defect. This does not certify Docker startup, live provider/model access, historical SA coverage or five-year investment performance.

**CODE QUALITY: PASS for this research prototype.** Native LangGraph/private contexts, typed immutable boundaries, deterministic arithmetic/ranking, fenced leases, frozen execution provenance, recovery and real frontend/API state are implemented. Targeted counterexamples passed after repair. No claim of production hardening or complete external-data verification.

Read AGENTS/binding V2, frozen architecture/plan, owner reports, backend/full-app diff packages, and authoritative current backend/frontend source. Final diff package contained8,286 lines when initially opened; reviewed fixes added afterward were inspected in current files.

## Baseline findings

| Finding | Final disposition | Verification |
|---|---|---|
|1. Verified SA ingestion unavailable | **ADDRESSED** | Separate authenticated attestation envelope; immutable revision registry; verified import/revision regression passed. |
|2. Backtest evaluation/benchmark stale reuse | **ADDRESSED** | Resolved timestamp and selected benchmark frozen into submission identity; changed evaluation/revision test passed. |
|3. Model/provider/version context mutable | **ADDRESSED** | Durable nonsecret execution_context; model/endpoint/version/bundle identity; worker drift rejection; explicit changed-model conflict tests passed. |
|4. Recovery/artifact divergence | **ADDRESSED** | Reload frozen universe/ResearchInput; reject unequal insert-once artifacts; regression passed; recovery source inspected. |
|5. Unverified REAL universe admitted | **ADDRESSED** | Mode/period/observation/availability/PIT guards; rejection regression passed. |
|6. Corporate-action PIT discarded | **ADDRESSED** | Internal immutable action status/hash retained; unverified event makes coverage incomplete and action access unavailable; real-return rejection tests passed. |
|7. Pending limit ignores splits | **ADDRESSED** | Cumulative decision-basis split adjustment, including fill-day, reverse and pre-common-entry events; scoped tests passed. |
|8. Compose REAL path ignored | **ADDRESSED** | Configurable REAL_DATA_PATH_CONTAINER with `/data/real/bundle.json` default; host/container paths documented. Docker runtime remains untested. |

Shared LLM HTTP semaphore/start-rate gate now covers all stock/persona calls and retries; timed transport regression passed. Invalid and active-loop changed budgets are rejected. Limits are persisted in execution context.

Frontend advisories addressed by exact Vite8.3.4/plugin-react6.1.2 pins and Node22 build stage. Owner reports fresh audit0 vulnerabilities and TypeScript/Vite buildPASS after final source-provenance changes. Reviewer inspected manifests/source/report; did not unnecessarily rerun stable audit/build.

## Follow-on findings — all closed

| ID / initial priority | Reproduced failure | Final fix and evidence |
|---|---|---|
|R1 P1 | Same default-as_of explicit-key POST202→409. | Original logical request is stored; retries reuse first pinned evaluation; conflicting costs still409. Regression **PASS**. |
|R2 P1 | Appending only future REAL bars caused FROZEN_PROVIDER_VERSION_CHANGED/FAILED. | Evaluation pins its own execution dataset; original cutoff universe/selected inputs must still match saved artifacts. Full REAL fixture appends future bars, matures successfully without changing signal, then rejects overwritten historical EPS. Regression **PASS**. |
|R3 P1 | Eight fresh PostgreSQL Store constructors:1OK/7UniqueViolation (`pg_type_typname_nsp_index`). | Same-connection transaction advisory lock serializes bootstrap; SQLite uses BEGIN IMMEDIATE. Reviewer reran actual fresh PostgreSQL16 cluster: **8/8OK**. |
|R4 P2 | Authenticated string/list/int attestations each500. | Non-object evidence rejected422; regression **PASS**. |
|R5 P2 | UI source came from latest registry rather than pinned backtest input. | Uses BacktestJob.payload.benchmark, labels latest registry separately, distinguishes null/legacy source. Source inspected; focused provenance script **PASS**. |
|R6 P2 | PROVIDERS said API attestation unsupported. | Current provider paragraph accurately documents envelope,422, immutable revisions and pinned inputs. **Inspected**. |

## Actual reviewer verification

From `/Users/yu/Desktop/FinAgent/finagent_codex_starter`, with PYTHONPATH=backend:

- Scoped waiting/pending-limit pytest selection: **5 passed**,37 deselected in0.30s (last -k governed whole collection).
- Data/API/recovery selection for action status, attestation, model conflicts/drift and universe gate: **6 passed**,12 deselected in0.37s.
- Explicit benchmark-revision/evaluation, immutable-artifact and shared-LLM-budget nodes: **4 passed** in0.57s.
- Follow-on explicit-key retry, malformed attestation and REAL future-data/history-preservation nodes: **3 passed** in1.76s.
- `npm run check:provenance` from frontend: **PASS** for pinned, null and legacy cases.
- Isolated fresh PostgreSQL16 bootstrap reproduction: baseline1success/7errors; after fix **8success/0errors**,1.3s. Temporary cluster stopped/removed in finally. One recheck setup attempt failed at pg_ctl startup before Store code; retry with a shorter temporary directory succeeded.

**18 scoped pytest cases passed across these reviewer invocations.** Offline reproduction programs also observed the quoted pre-fix failures. No live keys, market/model calls or fabricated data-success claims. The REAL integration fixture is explicitly invented test data exercising REAL plumbing, not actual financial history.

Broader evidence is attributed, not claimed independently executed: owner full86 backend tests at data checkpoint; root native PostgreSQL saver+HTTP restart+SKIP LOCKED/fence smokePASS before the last follow-on fixes; owner final frontend audit0/buildPASS (17 modules, JS178.21kB/CSS29.52kB); root browser submission→Top10→NVDA3roles199/159.20→synthetic/missing-SA backtest with520/1280 views. Root's comprehensive post-fix PostgreSQL run was in progress at reviewer completion; fresh-bootstrap correction was independently verified here. Stable full backend suite/browser/Compose tests were not unnecessarily rerun by reviewer.

## Full-app integrity and explicit limits

Frontend uses actual API state, nested result status, percentages versus percentage-point excess, synthetic badges, safe HTTP(S) links, missing/unverified SA, persona assumptions, snapshots and durable audit metadata. Local Vite/Compose Nginx API routing is wired. Fixed0/1/3 modes, deterministic50/30/20 valuation, exact-ten/equal weights/sector constraints and genuine cross-sectional factor scores are present. Primary replay handles NY opening/DST, frozen/publication cutoff, six calendar months, common sessions, splits/dividends/costs and pending/missing windows. No fabricated REAL prices/SA results or assumed outperformance found.

Surface accurately at delivery: Docker unavailable (no full container launch claim); live REAL feeds/model configuration and original historical SA lists not supplied; no verified five-year coverage. Provider SPY calendar completeness is assumed and documented; momentum is a raw split-sensitive proxy; dividend payment dates and order-book fills are not modeled; drawdown is explicitly observed period-end; historical LLM contamination remains possible. Cross-period aggregation exists in Python while UI focuses on individual runs. Langfuse/Redis are optional. These limitations do not represent remaining reproduced code defects or justify claims of proven alpha.
