# FinAgent Coding Rules (Codex)

## Mission
Deliver a real, runnable, testable research prototype for semiannual US equity Top-10 selection, with auditable research, forecast/entry prices, frozen-signal backtests, and transparent comparison to Seeking Alpha Top 10 and SPY. User is the product owner; you are the implementation agent.

## Decision hierarchy
1. `docs/IMPLEMENTATION_DECISIONS_V2.md` (latest, binding)
2. This `AGENTS.md`
3. `docs/FinAgent_设计文档_V1_参考.md` (background; obsolete choices overridden)
4. Existing repository code and conventions
5. Public documentation at pinned/current versions

## Non-negotiables
- DO the implementation, not just a plan or scaffolding. Continue through integration, tests, debugging, and a final execution report.
- Do not fabricate prices, financials, Seeking Alpha pick lists, data provenance, backtest results, benchmark outperformance, or test success. Clearly label all examples/fixtures as DEMO/SYNTHETIC.
- Historical `as_of` data must enforce publication/availability timestamps (`available_at <= decision_at`). If proof is missing, label `PIT_UNVERIFIED`, exclude from validated historical comparisons, and give a reason.
- Every result must link to a source snapshot and immutable strategy/model/prompt version. Run deterministic calculations in Python, not in free-form LLM text.
- No actual brokerage connection, automatic orders, financial advice claims, sandbox execution, Kafka, RabbitMQ, Celery, Elasticsearch, Doris, or Kubernetes in the MVP.
- No queue: run a separate async job-runner process with PostgreSQL persistent leases and deduplication; use bounded `asyncio` concurrency and LangGraph checkpoints.
- Secrets from `.env`/environment only. Never commit keys or send them to logs/LLM prompts. Public APIs must honor rate limits, terms, user agent requirements.
- Use LangGraph for actual graph orchestration, not sequential fake agent calls. Three personas have separate contexts; shared evidence is read-only. Fan-out/fan-in + optional bounded disagreement review.
- Tests must run offline, without live market keys or LLM APIs; live mode can require user-supplied keys.
- Prefer official library APIs, reuse tested open-source code only after dependency/license review. Do not copy entire third-party repositories.
- English internal identifiers; Chinese UI/docs acceptable. Typed Python, Pydantic contracts, pytest, explicit errors, idempotency.
- Keep outputs compact and actionable; in final response report actual commands/tests, changes, what worked, what is blocked, and why.

## Functional priorities
P0: runnable app, data contracts, historical visibility validation, quant screen, three-context agent research, valuation/entry price, Top-10 rank, batch idempotency, replayable signals, six-month SPY backtest, correct missing-SA behavior, Web UI, tests.
P1: conditional debate, distinct single/multi/quant ablation, Langfuse tracing, optional Redis caching, conditional-entry backtest, performance benchmark.
P2: beyond-MVP extras. Never sacrifice P0 for P2.

## Completion means
- `docker compose up --build` launches documented services; demo path functions without API keys.
- A documented end-to-end demo from job submission to Top-10 + report + synthetic labeled backtest works.
- Honest real-data mode is supported when providers are configured; if external feeds/SA data unavailable, UI reports `UNAVAILABLE` instead of substituting fake results.
- Each test suite invoked; any failures reported, fixed where feasible. Include a tested shutdown/restart + resume path.
