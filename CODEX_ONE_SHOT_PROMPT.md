# One-shot Codex Task — Build FinAgent end to end

You are the principal engineer and autonomous coding agent for the **FinAgent** repository. **Execute implementation now**. Do not stop after writing a plan, suggesting an architecture, or generating stubs. Inspect the current repo, make changes, install dependencies where possible, run and fix tests, launch the end-to-end demo, and give a concise truthful completion report. Do not ask questions unless external authorization/credentials are absolutely necessary; otherwise use documented functional fallbacks and continue. Work within this repository. Do not make unrelated destructive changes.

## Read these first, in this order
1. `AGENTS.md`
2. `docs/IMPLEMENTATION_DECISIONS_V2.md` — latest, overrides conflicting V1 details
3. `docs/REUSE_MAP.md`
4. Relevant sections of `docs/FinAgent_设计文档_V1_参考.md` (read selectively, not all at once)

## Business scenario: implement this example all the way through
An analyst starts a **2025-H2 US stock Top 10** research run. The system loads a dated US stock universe and historically admissible information, screens candidates down to up to 30, researches each with **Value, Growth, Conservative** personas running independently in a LangGraph graph, validates evidence, computes an explainable 12-month target price and safety-margin entry price, ranks and freezes exactly 10 stocks when at least 10 eligible stocks exist, and shows a web report. A separate backtest uses matching historical sessions, buys those picks equally at the first executable open, marks value six calendar months later, and compares total returns to SPY and, **only when verifiable original lists exist**, Seeking Alpha's matching Top 10. Show who won and by how many percentage points; never invent unavailable competitor lists or performance. Example NVDA scenario assumptions Value $190, Growth $240, Conservative $160, weights .5/.3/.2 => target $199, 20% safety margin => entry $159.20 are SYNTHETIC illustration/test fixtures only, not real equity facts.

## Hard implementation decisions
- Python 3.11+, FastAPI, Pydantic, LangGraph, PostgreSQL, React/Vite (or existing front end if repo already has one), pytest, Docker Compose; Langfuse optional; Redis optional only as a cache. No Kafka/Celery/RabbitMQ, no code execution sandbox, no live brokerage, no auto-order execution.
- One `asyncio` worker **separate from HTTP process**, plus DB persisted jobs, dedupe/task fingerprint, bounded concurrency, job claim leases/timeout recovery, idempotent result commits. Avoid FastAPI `BackgroundTasks` for durable jobs. Native LangGraph checkpoint mechanism for subgraph state, with graph version in thread identity.
- Plan + Tools + State + Evidence + Output are the five observable phases. Link traces by batch/run/ticker/checkpoint IDs and record spans, retries, token counts and validation status where available.
- No hardcoded fake provider data masquerading as production. Implement a complete **offline synthetic DEMO mode** with highly visible label. Real mode must use actual sources and reject unprovable historical PIT data. Degrade explicitly on lack of data/keys rather than silently mixing in fake values.
- Avoid unnecessary duplication: consult supplied REUSE_MAP for reference. Reuse official library APIs and small original adapters. Record source links/license/versions if adapting third-party code.
- The main half-year Top 10 fair comparison is separate from optional entry-price timing experiment. The latter must account for non-fills and cash drag.

## Deliver real project, not only designs
1. **Repo/bootstrap**: clear modular directory layout; dependency/env management, type hints, config and sample `.env.example` (no secrets), Docker Compose for postgres/api/worker/frontend, `.gitignore`, Makefile or `justfile`, README startup from clean clone. Health check and schema migrations.
2. **Data**: provider abstraction (`MarketDataProvider`, `FinancialsProvider`, `BenchmarkListProvider`); actual data integration where feasible, optional provider credentials with explicit setup. Typed, immutable market & financial snapshots with `ticker`, `as_of`, `available_at`, `source`, `source_uri`, `content_hash`, `corporate_action_basis`, `pit_status`. Enforce PIT cutoff and test it. Fetch corporate actions and dividend data or explicitly indicate unsupported periods. An original-filing SEC ingestion route may use EDGAR public endpoints subject to access rules. Historical fundamental/analyst estimate shortcuts using present-day data are forbidden.
3. **Universe/Quant screener**: dated universe interface, finite test universe, deterministic Value/Growth/Profitability/EPS Revisions/Momentum factors with clearly documented missing-factor behavior; filter eligibility and produce <=30 candidates; no invented historical index constituents. Provide an honest survivorship warning when current ticker list is used for historical research.
4. **Multi-Agent**: actual LangGraph state graph, private context per Persona, shared read-only snapshot, typed persona output (`assumptions`, `evidence_ids`, `risk_flags`, `target_price_candidate`, `abstain_reason`). Tool wrappers track input/output metadata and distinguish transient vs permanent failure; do not leak tool logs across personas. Independent views fan-in; optional ONE bounded disagreement debate based on predetermined threshold. Research Manager checks apples-to-apples horizon, units, split basis. Deterministic code computes final values, never LLM arithmetic alone. Support `quant_only`, `single_agent_skills`, `multi_persona`, optional `multi_persona_debate` modes.
5. **Valuation**: use existing proven forward P/E / DCF functions from reference only if their deps and licenses are manageable. No need to reproduce finance textbooks. Typed `ValuationResult` contains method results, assumption versions, target 12M, fair value, entry price, explanations and `PIT_VERIFIED/UNVERIFIED`; validity checks for negative earnings, missing FCF, divide-by-zero, stale data, currency mismatch. Distinguish fact vs assumption, and fail/abstain when ungrounded.
6. **Selection**: deterministic ranking with versioned weights, diversification constraints, duplicates banned, exact Top10 when eligible universe >=10, otherwise display `INSUFFICIENT_ELIGIBLE_STOCKS` without padding. Save immutable results and reasons for exclusions.
7. **Backtesting**: independent typed `FrozenSignal` and `BacktestResult`. Implement half-year release calendar, same trade start/end for FinAgent/SA/SPY, first tradable open after freeze, six calendar months, split/dividend-aware total returns or explicit validation-failure on missing actions; transaction costs/slippage configurable, time-window pending if not matured. FinAgent versus Seeking Alpha requires original source URL, original published_at, 10 valid tickers, verified list. Build CSV import template and validator. Never use Seeking Alpha's multi-year promotional aggregate as six-month performance. Aggregate wins/valid periods, excess percentage points, combined NAV and drawdown with coverage cautions. Keep secondary limit-entry policy and nonfill/cash drag as separate report. Backtest deterministic snapshots WITHOUT re-calling the LLM.
8. **API**: `POST /api/runs`, `GET /api/runs/{id}`, `GET /api/runs/{id}/picks`, `GET /api/stocks/{ticker}/research?run_id=...`, `POST /api/backtests`, `GET /api/backtests/{id}`, `GET /api/health`, and a secure/local import CLI or API for Seeking Alpha lists. Use sensible validation/error codes. Include OpenAPI examples.
9. **Frontend**: real functioning site in Chinese, with period/run selector, Top10 cards/table, research detail (three personas and evidence/target assumptions), status/progress, half-year comparison chart/table against SA/SPY, data coverage/PIT warnings, DEMO or REAL mode labeling and missing-list diagnostics. No hardcoded claim that FinAgent wins.
10. **Observability**: optional Langfuse v4 and OpenTelemetry-compatible spans for planning/tool/state/evidence/report. In all modes persist audit events with IDs and timestamps. Don't log secrets or massive raw filings.
11. **Tests**: use offline fixtures/mocks, add unit/integration/E2E smoke tests for graph context isolation; deterministic valuation; PIT rejection; no data fabrication; async retries & job resume; idempotency; exactly10/pool shortfall; same-period benchmark calculation; no same-day look-ahead; unverified Seeking Alpha list; incomplete half-year; split/dividend handling; no LLM required for frozen backtest; crash recovery. Tests should assert outputs, not merely API 200.
12. **Documentation**: `README.md` commands, architecture Mermaid diagram using NVDA illustration, table of reused code (license, version, link), test commands, performance baseline procedure, provider credentials required and currently missing, limitations/history-bias disclosures, `docs/STATUS.md` describing implemented vs incomplete features.

## Autonomous execution loop — follow without stopping between phases
Phase A: inspect project & versions, select simplest feasible dependencies; make a small actionable internal plan. Do NOT send user a plan-only answer.
Phase B: implement repository scaffolding, DB, offline demo data model and one deterministic vertical slice. Run tests.
Phase C: implement research graph and worker reliability. Run tests.
Phase D: implement score/valuation, backtest and benchmark adapters. Run tests.
Phase E: implement web frontend, API integration and documentation. Run Docker or local services, test via HTTP and real UI if tooling available.
Phase F: run `pytest`, front-end build/typecheck, API smoke and E2E run; repair failures; commit code only if repository allows, otherwise leave changes in working tree with a clear diff summary. Never claim success for skipped tests.
If live data provider access or external network is blocked, **do not stop the entire implementation**. Complete honest offline DEMO and implement real providers with explicit `UNAVAILABLE` status plus exact required configuration. Real five-year Seeking Alpha comparison should remain unavailable until lists and PIT data can be verified.

## Completion gates (do not call it done if they fail)
- A clean machine can start the app with documented commands, at least in DEMO mode.
- API and frontend work together, not static screenshots.
- Submit a run -> persist jobs -> execute real LangGraph nodes -> freeze signal -> see Top10 report -> run a deterministic half-year demo backtest -> see result in UI, with prominent SYNTHETIC label.
- All critical tests pass, including a restart/resume or failure-injection test; real-data missing prerequisites do not produce fictional performance.
- Backtest's comparison has same actual common start/end dates and corporate-action conventions.
- No user's API key or credentials in commits/logs.

## Final response to product owner — concise and factual
1. What really runs (DEMO and REAL separately) and how to launch it (exact commands).
2. Major files created/modified.
3. Tests/build/smoke outputs with pass/fail counts and any skipped cases.
4. Open-source reuse decisions and license caveats.
5. Data coverage/Seeking Alpha lists and PIT limitations, clearly marked; no invented performance.
6. Remaining blockers / missing API keys / optional enhancements.
7. A few honest resume-friendly engineering metrics to measure later; never make up XX% gains.

**Begin now. Do not ask for confirmation on routine design choices. Choose simple implementations consistent with these constraints and complete the vertical slice first, then the rest.**
