# Backend independent review — 2026-10-08

Requested assignment: gpt-6.1-sol / High. Runtime billing/model metadata is not independently exposed; this records the requested assignment only.

## Verdicts

**SPEC COMPLIANCE: changes required.** The offline research/replay core is implemented, but seven concrete integrity/workflow defects prevent accepting the current backend as satisfying binding V2. No P0 identified. The first six affect primary REAL provenance, immutable execution, or SA comparison; the seventh affects the optional secondary limit-entry experiment.

**CODE QUALITY: changes required.** The native graph, frozen typed contracts, deterministic arithmetic and fenced SQL writes are sound foundations. Defects sit at subsystem boundaries: imported status is discarded, environment/config is not frozen, and dedupe conflates distinct evaluations. Passing existing tests do not cover these counterexamples. Root has acknowledged and is routing fixes; this report records the reviewed baseline, not success of changes made after review.

Scope: AGENTS.md, binding V2, frozen architecture/plan, architect/data/agent/quant reports, root's 4,723-line backend diff package, and current backend source (including newer worker retry/audit changes). Frontend excluded from this first review. No code, dependencies, commits, or subagents changed. Only this report is reviewer-owned.

## Actionable findings

### 1. P1 — Supported SA API cannot import verified data

Location: `backend/finagent/api.py:107-116`, `backend/finagent/data.py:validate_benchmark_list`.

The authenticated route accepts only BenchmarkList, then calls the helper without its separate verification_evidence parameter. That helper deliberately downgrades all such imports. Even a list already verified by the official helper becomes PIT_UNVERIFIED. The single immutable `sa:period` slot then prevents attaching a different verified/revised list later. Neither a persistence CLI nor an API attestation path is present. This is an implementation gap in a required ingestion workflow, not simply absence of user SA data.

Actual offline reproduction: construct the list with `validate_benchmark_list(..., verification_evidence={verified_by, verified_at, evidence_uri, notes})`, POST with configured Bearer token. Output: `SA_VERIFIED_IMPORT 200 {'status': 'IMPORTED', 'verification_status': 'PIT_UNVERIFIED'}`; GET status `UNVERIFIED`.

Fix: expose a typed authenticated import envelope with separate attestation and immutable revisions; pin the selected revision in backtests. Preserve unverified imports without claiming proof from a URL/token alone.

### 2. P1 — Default backtests are permanently reused across evaluation/benchmark changes

Location: `backend/finagent/api.py:29-38,82-88`, `backend/finagent/worker.py:198-203`.

The fingerprint includes `as_of: null`, while the worker resolves null to wall clock later. A pending evaluation becomes a COMPLETED database job and identical submissions forever reuse it. Fingerprint also omits selected SA artifact/provider revision, so supplying benchmark data cannot refresh a prior missing-SA result. Worker reads the benchmark at execution rather than freezing it with the request.

Actual offline reproduction with a seeded frozen signal and worker clock patched to 2025-12-01, then 2026-02-01: `DEFAULT_ASOF_FIRST PENDING`; second identical POST: `DEFAULT_ASOF_SECOND True COMPLETED PENDING` (same id, no reevaluation).

Fix: resolve evaluation timestamp and freeze benchmark revision into durable submission context before hashing. Keep explicit repeat requests idempotent for that concrete evaluation; allow a new current evaluation to be distinct.

### 3. P1 — Execution model/version/provider context is not durably pinned

Location: `backend/finagent/api.py:29-37`, `backend/finagent/worker.py:100-102,167`, `backend/finagent/agents.py:real_generator,checkpoint_identity`.

The API reads versions/model only while computing an implicit fingerprint and persists only RunRequest fields. Explicit keys omit those values entirely and conflict-check only request fields. Worker later uses its current provider path and model/base URL environment. Checkpoint identity's ResearchInput retains the default model version; it does not hash actual environment-selected model/base URL. API/worker configuration mismatch or a restart can therefore execute a different model/provider configuration under the same submitted identity or reuse old checkpoints.

Actual reproduction: set LLM_MODEL=model-a and POST REAL with explicit key; set model-b and repeat: `MODEL_CONFIG_KEY_REUSE 202 True`. Stored payload fields were only `decision_at,max_candidates,max_per_sector,mode,period,research_mode,safety_margin`.

Fix: persist exact nonsecret execution context (versions, model, base URL identity, provider/bundle identity), include it in key conflict checking and checkpoint identity, and reject incompatible worker context. Never persist keys.

### 4. P1 — Recovery can calculate from a changed bundle while retaining old input artifacts

Location: `backend/finagent/worker.py:102-119,125-135`, `backend/finagent/storage.py:_insert_once`.

Every retry recreates the provider and refetches universe/inputs. Insert-once artifact writes silently ignore an existing key even when payload differs, but calculations use newly fetched values. Completed research is reused solely by run+ticker; fresh cross-sectional scores can also be applied to old results. A source file revised between attempts can mix snapshots and make persisted input disagree with research evidence.

Actual offline reproduction: persist run input A for AAPL, then run a provider with doubled EPS and a newly computed content hash. Job completes. Output: `RESUME_SOURCE_DRIFT JOB COMPLETED stored_vs_research_match False`; stored evidence hash `63f182127c62d150620eec0367badfd5775364a394d16588263f43f903fd8e34`, research hash `2dbd93cb278ec776c94bf7ea87ef0b02c58862d2b1132ae551b672b5e6957552`.

Fix: reload frozen universe/inputs for recovery, preserve one run-level dataset identity and cross-sectional screen basis, and reject conflicting insert-once content rather than silently allowing provenance divergence.

### 5. P1 — Unverified REAL universe can produce a PIT_VERIFIED signal

Location: `backend/finagent/worker.py:105-119,169-174`.

Worker checks universe availability but ignores its mode/PIT status. Screening/freezing checks stock snapshots only. A bundle with an individually unverified dated universe and verified stock records produces a verified primary signal without even requiring a survivorship warning. V2/AGENTS exclude unverified historical records from validated comparisons; membership is part of those inputs.

Actual offline targeted adapter reproduction (explicit synthetic test data converted to exercise contract statuses, no real-world facts claimed): `UNVERIFIED_UNIVERSE PIT_UNVERIFIED JOB COMPLETED SIGNAL PIT_VERIFIED`.

Fix: enforce REAL universe verification/mode/period/chronology at intake and bind its identity to immutable execution provenance; surface unavailable/unverified membership honestly.

### 6. P1 — REAL corporate-action PIT status is discarded

Location: `backend/finagent/data.py:542-553,actions,actions_complete`; `backend/finagent/backtest.py:_actions`.

Importer validates the action envelope enum but discards status and envelope hash when producing CorporateAction. A bundle-level attestation plus verified coverage can therefore admit a PIT_UNVERIFIED dividend/split. Backtest has no remaining field to detect it and can include its cash/share adjustment in a verified REAL result. Coverage proves completeness, not authenticity of every event. The envelope hash also does not enter replay provenance.

Actual reproduction: take test REAL bundle, change action envelope to PIT_UNVERIFIED, reseal action and bundle hashes. Output: `UNVERIFIED_ACTION_ACCEPTED 1 True False` (one action returned, coverage complete, returned action has no PIT field).

Fix: preserve per-event verification/hash in provider state, and reject/invalidate requested REAL action intervals containing unverified events. Do not silently drop such events as if no action occurred. Check coverage availability against evaluation where supported; the current coverage interface has no as_of parameter.

### 7. P1 — Pending limit price is not adjusted for splits

Location: `backend/finagent/backtest.py:80-91`.

Future RAW bars are compared to the unchanged pre-split frozen threshold. If an unfilled stock undergoes a 2:1 split, raw price100→50 incorrectly triggers original limit96; its comparable limit should become48. Reverse splits can incorrectly prevent fills. Existing share-action accounting after actual fill does not repair pending-order units.

Actual test fixture: pre-split lows99; post-split lows49; original limit96; economic price remains above threshold throughout. Output: `filled=True, entry_price=50.0, exit_price=50.0, split_factor=1.0`. Expected: nonfill/cash. This is in the secondary experiment, not a primary open-to-open accounting failure.

Fix: carry split-adjusted pending limit in session order; on fill day use post-split units, then process only entitlement events belonging to the held position. Add forward/reverse split and same-session tests.

### 8. P2 — Compose ignores documented REAL_DATA_PATH configuration

Location: `compose.yaml:environment REAL_DATA_PATH`, `.env.example`, README real-mode enablement.

Compose hardcodes `/data/real`, overriding any REAL_DATA_PATH supplied through `.env`; the documentation tells users to select their JSON bundle path. Mounted `./data:/data` is suitable, but a normal `data/real_bundle.json` plus an environment setting cannot enable REAL as documented. No container startup was claimed or performed by this reviewer.

Fix: expose a container-relative configurable bundle path with an example aligned to the mounted data directory. Distinguish host and container paths.

## Verification evidence and limits

Reviewer executed two independent `PYTHONPATH=backend .venv/bin/python - <<'PY' ... PY` offline reproduction programs from the project directory, using TemporaryDirectory, actual Store/FastAPI TestClient/Worker, official fixture builders loaded via runpy, and targeted provider/clock mocks. Exit0; outputs quoted above. No live keys, LLM/provider calls, market facts or test-success claims fabricated. Scripts ran in 0.5s and 1.7s respectively. They verify the counterexamples; they do not certify owner fixes.

Existing evidence was read, not unnecessarily rerun: data report64 passed; later quant report full suite70 passed in2.83s and scoped28 passed. Parent reported actual HTTP E2E, partial cancellation/reopen, native SQLite close/reopen roles, and isolated PostgreSQL16 native saver + separate API/worker restart + eight concurrent SKIP LOCKED claims + stale-owner fence PASS. Those are parent/owner-reported checks, not independently executed reviewer tests. Root's current transient exception mapping and five-phase checkpoint audit extraction are newer than diff snapshot and are present in the inspected worker; do not report them as missing.

## Implemented foundations and surfaced limitations

Actual LangGraph fan-out/fan-in and private ephemeral histories exist. REAL HTTP adapter accepts structured JSON assumptions and Python recomputes arithmetic; no synthetic fallback in REAL. Fixed0/1/3 paths, 50/30/20 blending and exact-ten sector selection use actual preserved cross-sectional factor scores. Primary replay handles NY opening time/DST, freeze/publication cutoff, six calendar months, common sessions, cash dividends, split-before-dividend denomination, costs and immature/missing results. Token metadata/audit privacy and lease fencing are implemented; there is no brokerage execution.

These are accurately documented limitations rather than newly established bugs: no user REAL provider bundle/original SA history supplied; external live LLM not exercised; no independent exchange calendar (SPY provider rows assumed complete); momentum explicitly raw proxy and split-distorted; dividend payment-date financing absent; daily-low limit fills approximate liquidity; drawdown explicitly period-end only; observed windows cannot prove five-year completeness; historical LLM contamination remains possible. Langfuse/Redis are optional. Fair_value may remain absent when only a12-month forecast is defensible. Provider rate/concurrency observability could be strengthened, but no specific advertised provider-budget breach was reproduced in this review.

Latest owner update after reproductions: root reports fixes1–5 implemented with7 scoped API/recovery tests passed (verified import envelope and append-only revisions; resolved/pinned backtest context; persisted execution context and drift409; saved snapshot reuse; REAL universe guard). Quant reports split-limit fix with3 RED regressions then21 backtest tests GREEN. Reviewer has not yet inspected/reproduced those fixes; the findings above describe the reviewed baseline and require scoped re-review, not an assertion that all remain broken. Finding6 remains assigned for original data-owner repair;8 remains a deployment follow-up. Frontend/final full-app acceptance is a separate subsequent gate.
