# FinAgent V2 — Binding Implementation Decisions
Updated 2026-10-08. This document overrides conflicts in the V1 background design.

## Product boundary
- US-listed stocks/ADRs, semiannual (H1/H2) Top 10 stock ideas; shortlist about 30 candidates after cheap, deterministic factor pre-screen. User enters a period and can inspect picks, role-specific views, target price, entry threshold, rationale, citations, and backtest comparisons.
- Primary research goal: 6-month **equal-weight** Top-10 return against original Seeking Alpha Top-10 list for the same verified period and against SPY. Not a claim of consistent outperformance.
- Secondary experiment: waiting for a 12-month valuation-derived entry price. Do not mix entry-timing results into the primary Top-10 selection comparison.
- No sell-price predictions or live trading. A fixed 6-month mark-to-market / liquidation in simulation is evaluation accounting only.
- One-week MVP: high-quality demonstrable core first. Five-year comparison is desired only for periods with verifiable historical picks and usable PIT data. Insufficient historical data is a **valid surfaced limitation**, never an excuse to fabricate.

## Example to implement and document
"For 2025 H2, screen an eligible, dated ticker universe; analyze NVDA within candidate stocks (illustrative numbers ONLY): Value target 190, Growth 240, Conservative 160. Separate persona messages, shared read-only evidence, common 12-month horizon. Example fixed weights 50/30/20 yield target 199; 20% safety margin yields example entry 159.20. Ranking chooses 10; shared benchmark comparison buys at the same eligible opening session after both sides' timestamped picks are available and tracks six calendar months of total returns." Do not present these illustrative numbers as real historical stock facts.

## Architecture
`React/Vite UI -> FastAPI -> Postgres batch_runs + research_jobs -> standalone asyncio worker -> LangGraph per-ticker graph -> valuation engine -> immutable signals -> deterministic backtest -> report/dashboard.`
Use LangGraph native PostgreSQL checkpoint saver if compatible; otherwise documented SQLite dev-only saver with Postgres app state, not a custom reimplementation. Langfuse optional, gracefully off when credentials absent.
- No mandatory message queue. Use DB leases/atomic claim and periodic stale-job reconciliation in a separate worker process; no dependence on FastAPI BackgroundTasks or request lifetime.
- Limit concurrency globally per worker and provider with semaphores plus rate-limiting; retries only for transient errors, exponential backoff with jitter and caps. Terminal PIT/data errors never silently turn into neutral rankings.
- Persist exact configuration hashes and graph/model/prompt versions; a retry of the same request must reuse finished results. State checkpoint must support worker interruption and selective retry.

## Research graph
1. Fetch immutable historical/live snapshot and validate completeness/PIT status.
2. In parallel: `ValuePersona`, `GrowthPersona`, `ConservativePersona`, each with separate messages and constrained tools.
3. Each produces typed evidence references + forecast assumptions; numeric claims validated by tool code.
4. Compare forecasts on same currency, corporate-action basis, forecast horizon; if disagreement exceeds configurable ratio, run max ONE review round. If unresolvable, abstain/flag rather than hallucinate.
5. Deterministic valuation adapter (e.g. DCF / forward P/E when input evidence is sufficient), blend only comparable values; distinct `fair_value`, `target_12m`, `entry_price` and provenance. Clearly label unverified subjective assumptions.
6. Rank by reproducible factor policy and sector constraints, output exactly ten only if at least ten eligible; otherwise explicit insufficient-universe state.
7. Persist `signal`, input snapshot hash and model version, evidence ledger, trace/run IDs.

## Data and historical integrity
- Market OHLCV and corporate actions (splits/dividends); SEC EDGAR original filings with actual filing / availability date for fundamentals; adapters for other providers if configured. `yfinance.info` today must never be used as point-in-time historical consensus.
- Data layers must support `PIT_VERIFIED`, `PIT_UNVERIFIED`, `MISSING`; unverified records cannot contaminate claims labeled validated.
- Historical investable universe membership and delistings are hard: dated universe or explicit survivorship-bias warning. Prefer honest reduced coverage over wrong data.
- Seeking Alpha pick list ingest requires source URL, original publication time, canonical tickers, and verification status. CSV/JSON import with strict validation. Some lists may be paywalled; never scrape through access controls. Absent list -> no SA result.

## Backtest
- Primary: two independent Top-10 equal-weight buy-at-next-valid-open, hold 6 calendar months, same actual entry/exit sessions for FinAgent/Seeking Alpha/SPY, dividends/splits and assumed costs appropriately handled; represent incomplete windows as `PENDING`.
- Start session >= both SA publication timestamp and FinAgent decision freeze timestamp; signal generation cannot observe prices after decision time. If benchmark list published after our period's decision, explicitly choose a common eligible start and freeze only admissible evidence (do not retroactively trade).
- Return formula with consistent total-return treatment; include period absolute returns, excess percentage points vs SA and SPY, winning periods/valid periods, five-year chained NAV if possible, drawdown, sample sizes, missing periods.
- Secondary: limit entry <= rule, remaining cash and non-fills; don't judge only fills, quantify opportunity cost.
- Quant-only vs single-agent skills vs multi-persona (and optional debate) ablation must use same eligible snapshots, model/versions, samples and execution rules. Report risk of LLM historical knowledge contamination; no unsupported 'proved Alpha' claims.

## Observability
- Run-level and stock-level IDs, Planning/Tool Execution/State Management/Evidence Verification/Result Synthesis spans; token, costs if provider returns, latency, retries, cache, validation status, error code; storage in own DB for durable audit and Langfuse (optional).
- Privacy: redact keys, avoid logging arbitrary raw filings or full prompts containing sensitive data; retain hashes and local artifact pointers.

## UI and delivery
- UI pages: overview / latest Top 10 with status, stock detail with three personas and evidence/price breakdown, historical experiment dashboard with SA/SPY comparisons and missing-data badges, run progress and trace links; clear DEMO badge in synthetic mode.
- API: POST `/api/runs`, GET `/api/runs/{id}`, GET `/api/runs/{id}/picks`, GET `/api/stocks/{ticker}/research?run_id=`, POST `/api/backtests`, GET `/api/backtests/{id}`, GET `/api/health`, and ingestion endpoint/CLI for authenticated/locally supplied benchmark lists. Request validation and truthful errors mandatory.
- Docker Compose: api, worker, postgres, frontend. Redis optional only when its measured benefit justifies it. Seed non-sensitive explicitly synthetic data for offline demo/tests and document real mode enablement.
- Tests: unit (valuation, ranking, timestamps, duplicate tasks), integration (jobs/checkpoint), deterministic backtest invariants (no same-day look-ahead, same benchmark interval, missing SA, incomplete 6-month horizon), E2E smoke, crash/restart and recovery; timeouts and provider failure mocks.

## Reuse philosophy
- Use `docs/REUSE_MAP.md`. Prefer direct dependency over copying framework source. If FinRobot's valuation file imports too much of its internal stack, copy/port only the needed **verified core equations** with attribution and tests, or implement transparent narrow fallback; document decision.
- No multi-repo giant forks, no duplicate backtest engines. Review licensing before bundling source; vectorbt has Commons Clause license condition, confirm suitability.
