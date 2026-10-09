# Actual parallel execution ledger

Started 2026-10-08 (Asia/Shanghai). Primary workspace: finagent_codex_starter.

User explicitly authorizes autonomous design, model selection, parallel implementation and integration; max three concurrent child agents. No deployments, live orders, or messages to outside parties.

## Rulings
- CODEX_PARALLEL_START.md was absent in the supplied package and a Desktop search. Generate a clearly labelled replacement from the user's explicit rules plus binding V2 architecture. Cost if wrong: an unseen original might impose additional constraints; the report preserves this limitation.
- Supplied directory had no Git repository. Initialize a local feature branch in this directory, preserving input docs. Cost if wrong: project location may need moving later.
- Use installed Python 3.11, native PostgreSQL production + SQLite development/testing; no Docker/PostgreSQL executable initially detected. Deployment execution must remain unverified unless actually run.

## Dispatches
| Agent | Actual requested model | Effort | Task | Status |
|---|---|---|---|---|
| architect | gpt-6.1-sol | high | Frozen contracts, architecture, ownership, acceptance | Completed |
| data_engineer | gpt-6-luna | max | DEMO/REAL sealed providers, PIT/action validation, SA imports; action follow-up | Completed |
| quant_engineer | gpt-6.1-sol | high | Factors, valuations, exact ten, corporate-action backtests; split-wait fix | Completed |
| agent_engineer | gpt-6.1-sol | medium | Native isolated graph, persistent checkpoints, shared HTTP budget | Completed |
| frontend_engineer | gpt-6-luna | max | Chinese UI, actual API integration, dependency repair, pinned benchmark source | Completed |
| backend_reviewer | gpt-6.1-sol | high | Independent baseline and final source review, reproduced bugs and scoped retests | Completed: documented MVP PASS |

## File ownership
- architect: contracts.py, backend package init, frozen architecture/plan, generated parallel start, test_contracts.py, own report.
- root: dependencies/bootstrap, database/storage, API, worker integration, E2E/recovery tests, deployment, final docs/ledger.
- data_engineer: data.py, test_data.py, provider docs, own report.
- agent_engineer: agents.py, test_agents.py, own report.
- quant_engineer: quant.py, backtest.py, corresponding tests, own report.
- frontend_engineer: frontend/, own report.

No shared file may be modified by two agents concurrently. Agents do not commit; root integrates and commits after review and verification.

## Verification evidence
- Root storage RED: `pytest tests/test_storage.py -q`: missing module (before implementation).
- Root storage GREEN: same command: **3 passed**. Covers dedupe, immutable completed research, expired lease reclaim after restart, old worker fencing, permanent vs retry errors.
- Dependencies installed in Python 3.11 venv; exact resolved versions saved in `requirements.lock`.

## Wave 1 dispatched
- architect finished: actual source/contracts checked; **14 contract tests passed**, independently rerun by root with storage (**18 combined passed** after storage fencing expansion).
- data_engineer dispatched using `gpt-6-luna`, effort `max`; no separate Fast/service tier switch is exposed by spawn tool. Owns data.py/tests/provider docs.
- quant_engineer dispatched using `gpt-6.1-sol`, effort `high`; owns deterministic quant/backtest and tests.
- agent_engineer dispatched after architect completed using `gpt-6.1-sol`, effort `medium`; owns real LangGraph orchestration/tests.
- Root added HTTP API + standalone worker integration against frozen interfaces; integration tests not yet passable until dependencies finish.
- Root expanded fencing to per-ticker/snapshot/signal writes: RED **1 failed, 3 passed** (missing lease parameter), GREEN **18 passed** (contract + storage). Old lease can no longer insert research or artifacts.
- Installing local PostgreSQL 16 via Homebrew to test production dialect/native checkpoints. No system service was started; intended server is isolated test-only port/data directory.

## Interface dependency scan
| Producer / consumer | Shared interface | Finding |
|---|---|---|
| architect / all | frozen Pydantic envelopes | Consistent; schema edits require root coordination |
| data / root, quant | sync provider + actions_complete | Explicit complete-actions helper added and relayed |
| quant / agents | valuate + forward_eps/forward_pe assumptions | Numeric values computed in Python; DEMO unverified chronology allowed only with synthetic labels |
| agents / root | async research_stock + supplied native saver | Worker uses AsyncSqliteSaver or AsyncPostgresSaver, bounded concurrency |
| root / frontend | HTTP routes and typed reports/backtest JSON | Frontend implemented against actual API source |
| quant selection / root | None means shortfall | Explicit INSUFFICIENT_ELIGIBLE_STOCKS, no padded picks |

## Integration evidence (first complete backend pass)
- Full offline suite: `.venv/bin/python -m pytest -q` => **52 passed in 0.98s** (owners still extending tests).
- Actual HTTP E2E: `.venv/bin/python scripts/e2e_demo.py` => exit 0; separate API/worker, ten picks, three actual graph reports, worker shutdown/restart, deterministic synthetic backtest, absent SA => UNAVAILABLE/null. Saved artifact `artifacts/e2e_report.json`; first run id `3c41c872-e928-49ef-a87c-449e2b9e5f92`.
- Worker failure injection: `pytest tests/test_worker_recovery.py -q` => **1 passed in 1.37s**. Interrupt real graph after first ticker persisted, leave lease, reopen Store after expiry, reuse first result, execute only unfinished tickers, freeze exactly ten.
- Ruling: DEMO historical observations are FACT records *inside an invented dataset*, with Mode.DEMO/PIT_UNVERIFIED/SYNTHETIC provenance. Forecasts are separate Assumption objects. Cost if wrong: UI must keep synthetic labels prominent so fixture facts cannot be mistaken for market facts.
- Root cancels all sibling ticker tasks when a batch task fails/cancels, before closing native saver/transitioning lease state.

## Wave 2, fixes and final verification

Frontend was dispatched only after a backend slot freed; no more than three child agents were active. Architect froze contracts before coding roles. Root alone owns API/storage/worker integration. Owners performed targeted fixes in their own files; read-only reviewer modified only reports. Models shown above are actual spawn-request parameters, not independently verified billing/runtime identities; no separate Fast flag exists in the tool.

Baseline reviewer found seven P1 issues and one P2. Root fixed verified-SA attestation/revisions, default evaluation snapshots, immutable execution context, saved-input resume, REAL universe PIT and Compose path configuration. Original data owner fixed action verification; original quant owner fixed split-adjusted pending limits. Final reviewer independently reproduced three additional P1 issues and three P2 issues. Root repaired default explicit-key retry, evolving execution dataset validation, first-boot schema locking and malformed import envelopes; frontend owner repaired displayed source provenance; root corrected provider docs.

- Default explicit-key and malformed-attestation regressions: **2 failed, 2 passed RED**, then **6 API tests passed GREEN** with contract suite.
- REAL execution integration uses invented test-only sealed records: future observations first caused FAILED (RED); after repair, REAL quant-only signal matures without redoing research, and amended original EPS is rejected (GREEN).
- PostgreSQL first-boot regression: eight simultaneous Store constructors produced actual pg_type unique violation (RED). Same-connection transaction advisory lock: **8 constructors PASS** (GREEN). Reviewer independently repeated **8 OK**.
- Agent HTTP budget owner timed test: nine stock/persona calls initially exceeded cap; shared budget observed cap2 and spaced starts including a503retry (GREEN).
- Latest root `.venv/bin/python -m pytest -q`: **98 passed in 4.95s**, exit0.
- Latest `npm ci`, `npm run check:provenance`, `npm run build`, `npm audit`: all exit0; TypeScript+Vite8.3.4 build; **0 vulnerabilities**.
- Latest `scripts/e2e_demo.py`: SQLite actual HTTP submission / separate worker / native graph / ten picks / three reports / worker shutdown-restart / frozen deterministic backtest / SA unavailable, exit0. Run c0c74fac-af67-4215-a621-42cbe6c65751.
- Latest `scripts/postgres_smoke.py`: eight fresh concurrent constructors, native PostgreSQL graph saver, HTTP/worker restart E2E, eight unique claims among12workers, stale research-write rejection: PASS/exit0. Run f5654ecb-f75f-415a-8a81-27b46d927aa5. Cluster stopped in finally; no system service started.
- Native browser performed actual DEMO submission,10picks,NVDA3reports199/159.20,backtest; narrow520 and wide1280 views inspected. Final Vite/API/worker restarted from current source; reload recovered run and backtest and showed pinned-source unavailable message. Screenshot artifacts/finagent-final.jpg.

## Final rulings and boundaries

- Explicit keyed backtest retries reuse FIRST resolved evaluation, benchmark and dataset; same request/different current registry is still the same evaluation. Different logical request returns409. Unkeyed default evaluation is newly timestamped.
- REAL research and execution bundles have independent immutable byte identities. Append-only post-cutoff observations are allowed after verifying original universe and selected decision inputs; historical amendments are rejected. Cost if wrong: stricter record equality may reject legitimate vendor restatements; such corrections require a new research run.
- PostgreSQL schema v1 startup holds a transaction advisory lock on the DDL connection; SQLite uses BEGIN IMMEDIATE. Future migrations require explicit versioned changes.
- Docker is unavailable in this host, so Compose files are delivered and statically checked, not container-runtime verified. Local equivalent PostgreSQL/native checkpoint paths were executed.
- No live paid provider/model access or original SA lists were supplied. REAL fixtures test the adapter plumbing only. No fabricated investment advantage, missing-list substitution, or five-year claim.
- Git author identity is not configured. Preserve all work in the feature-branch working tree; do not fabricate an author or claim a commit.

Final reviewer verdict: SPEC and QUALITY **PASS for documented MVP**; independently verified18scopedtests,8freshPGconstructors and frontendprovenance; no outstanding reproduced defects. Docker/live prerequisites remain explicitly unverified. Final handoff references STATUS.md, latest local services and screenshots.

## CI-only follow-up

User: keep Mac local workflow; no Docker Desktop installation or development blocking; add GitHub Linux CI without changing core business logic.

Root added workflow, real-container smoke script, strict shell lifecycle/logging, and CI guard tests. RED12failed before files existed; GREEN15guards (including actual verdict-step failure/skip cases). Fullsuite113passed6.38s; npmci/provenance/buildexit0; SQLite HTTP+worker E2Eexit0, run df418756-5074-4d6c-ac1a-ce7d01597d15. No container execution counted. Bash syntax/Python compile/YAML gates/actionlint1.7.12 passed; official release checksum verified. AllfourofficialActions resolved to tag SHAs and pinned. Hash manifest confirmed21core/frontend/Docker/Compose/Makefilefiles unchanged. Independent reused backend_reviewer requested same gpt-6.1-sol/high:12guards independently passed plus bash/YAML, no blocker; reportci_reviewer.md. Later added3actualworkflowverdict cases and rootran15guards/full113.

User supplied https://github.com/pogacar03/FinAgent. Actual GitHub connector repo metadata:public,main,write/admin permission; initialHEAD96c0b6d1326a7565bbbd0b899069c03b4d90eb08, onlyLICENSE. Configureorigin, preservemain/license; upload tested project baseline unchanged and newCI into a separatebranch. GitHub API authenticatedcommit avoids fabricated local author. Linux container status remainsUNVERIFIED until actualjob success. No Docker installed onMac.

Actual remote delivery: authenticated GitHub commit5aad5e0cbf2f587485214553a45f7d17238cc538 oncodex/ci-linux-compose, preserved main/LICENSE, draftPR#1 created+attached. Pushrun37791876438 andPRrun37791940279 bothsuccess. ActualLinuxpytest113passed9.40s; frontendTypeScript/Vite passed; Dockerapi/worker/frontend built; ComposePG/API healthy, workerstop/start,10picks3roles,20durablereports20checkpointthreads84audit, frozenbacktestsamewindows+SAunavailable, nginxproxy:PASS. CIverdictVERIFIED onlyafteractualsuccess. Downloadedlogs/evidence retained inartifacts; committedsummarydocs/CI_RESULT.json. Core21files hashesunchanged. Mac Docker remainsUNVERIFIED/NOT_RUN. Documentation-only follow-up must rerun CI for its new commit before latest-head success is claimed.


## Phase 2 actual execution — 2026-10-09

Root inspected AGENTS/one-shot/parallel/frozen V2 source/review/Git independently. Synced actual authenticated baseline1bcedb6; fresh113passed6.20s; original98+15CI guards unchanged. New branchcodex/phase2-validation. Ownership: real_data newpilot/script/test/report (inherited model); observability newSDKmodule/test/report (gpt-6.1-sol medium); benchmark newrunner/test/rawdocs/report (gpt-6-luna max). Max3children. Afterobservabilityfinished SolHighindependentreviewer (gpt-6.1-sol high) tookthirdslot. NoFastflag/externalroutingproof.

Root installedSDK/OTLPHTTP1.45.1, pinned9newtransitives, minimally integratedworkerjob/ticker scopes andStore auditcorrelations, actualHTTP SDKscope/latency andvalidproviderusage only. Originalbusinesscalculations/contracts/data/API/frontend intact. Added actual containertraceguard and2offlineguards; they cannotprovecontainersuntilCI runs. Obs9passed, data20passed plusoldquant/backtest55passed, benchmark5passed, rootfull149passed7.16s; reviewerfull149passed7.31s. Frontendprovenance/tsc/Viteexit0. RealisolatedPG bootstrap8 + workerHTTP/nativecheckpoint/restart + 12claims8unique + staleownerwrite rejection PASS; run d6bc85be-e14f-46d3-ac5e-a31ae9abaa33, actualtrace6089cc0da86f41ebd80b16d554edc35f105spans fivephases allDEMOLLMmetricsnull. SeparateSQLiteE2E alsoexit0. Bash syntax/compile/diffcheck pass.

Data actualnetworkfinal025343313311Z PARTIAL; rootindependentreplayPASSED0network/originalPARTIAL. FinancialGAAP fromissuerannouncementdatebound; Nasdaqprice0rows; issuerdynamicbootstrap; YahoodiagnosticUNVERIFIED; actioncompletefalse; stricttarget/entry/totalreturnnullUNAVAILABLE. No inventedSECidentity, nineadditionalstocks, contemporaneousarchive oranalystconsensus. Reviewerreproduced P1optionalfieldreplaybypass andP2malformedJSONaborts; originalowneraddedfailingregressions+pureunconditionalrecompute andshapechecks, reviewerindependentlyconfirmedallmutationsrejected andrecordpersisted.

Benchmark executedfinal18/0failures; everystrategy/scenario3trials sameinput/model/snapshot/environment, actualleaseinterruptionretains1ticker/redoes9. Rawallrunsretainedin docs/benchmark_results; finalmeasuredsourceperfilehashes independentlychecked. MetricsactualDEMO only, nullLLMmetrics; no unsupportedspeedup/token/Alpha claim. FinalLangfuseingestion/UI UNVERIFIEDwithoutcredentials; actualunreachableOTLPfallbacktested, modelHTTPtestsarefixtureszeroLiveLLM.

Newphase2CI must beverifiedagainstactualnewcommit; oldCIgreenrecordisnotnewsourceproof. AuthenticatedGitHubcommitanddraftPRretainmainandbaselinePR#1dependency; finalresultsappendedwhenactuallyavailable.
