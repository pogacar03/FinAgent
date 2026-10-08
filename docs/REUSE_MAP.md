# Reuse Map — targeted inspection only
Read only files needed for the current implementation; do not ingest full repositories into model context. Pin external commits / package versions in the final report. These are references, not proof of drop-in compatibility.

## TradingAgents (https://github.com/TauricResearch/TradingAgents)
- `tradingagents/graph/setup.py`: LangGraph subgraph Fan-out/Fan-in, private analyst contexts.
- `tradingagents/graph/conditional_logic.py`: bounded debates; do not duplicate irrelevant risk/trader graph.
- `tradingagents/graph/checkpointer.py`: reference for deterministic thread IDs and resume.
- `tradingagents/agents/state.py`: typed Agent state structure.
Choice: use official LangGraph APIs in new lightweight graph; do not fork trading system.

## AI Hedge Fund (https://github.com/virattt/ai-hedge-fund)
- `hedge_fund/signals/base.py`: standardized AlphaModel interface and abstention semantics.
- `hedge_fund/signals/llm_agent.py`: model call errors, caching, constrained input snapshot, persona base design.
- `hedge_fund/signals/buffett.py`, `graham.py`, `lynch.py`: public philosophy prompts, not actual investors' private strategies or endorsements.
- `hedge_fund/backtesting/engine.py`: reference separation of decision from execution; no direct drop-in for semiannual Top10.
Choice: implement small Agent Factory with prompts and typed responses; do not import whole hedge fund runtime.

## FinRobot V2 (https://github.com/AI4Finance-Foundation/FinRobot)
Files under `finrobot_desktop/finrobot/engine/compute/operators/`:
- `dcf.py`, `wacc.py`: DCF equations, inputs/guards.
- `multiples.py`: PE and peer multiple rules.
- `forward_estimates.py`: central handling of forward projections; do not use today's consensus in historical PIT.
- `valuation_synthesis.py`: deterministic multi-method aggregation.
Internal `finrobot.engine.models.financial` dependencies need validation before any extraction/copy. Prefer importable tested components if reasonable. Preserve licenses and attribution. Avoid installing unrelated older `finrobot` distribution expecting V2.

## Backtest / tracing libraries
- `vectorbt` (https://github.com/polakowo/vectorbt): direct library for performance/accounting if suitable; Apache 2.0 with Commons Clause; keep backtest interface library-agnostic.
- `langgraph-checkpoint-postgres`: official checkpoint implementation.
- `langfuse` v4 API: official tracing / callback, avoid obsolete v2 `trace()` interface.
- `pytest`, `httpx`, `pydantic`: direct libraries.

## Reuse acceptance
For each module: dependency install succeeds; a minimal import and unit test passes; license is documented; chosen version/commit is pinned; if adaptation costs > writing small tested integration layer, use integration layer instead. Do not copy source just to save model tokens.
