# Newly generated parallel implementation handoff

This file was newly generated on 2026-10-08 from the user's autonomous execution
rules, AGENTS.md and binding V2. It is **not** the original supplied parallel
start document: that document was absent after root searched project and Desktop.

Read `AGENTS.md`, `docs/IMPLEMENTATION_DECISIONS_V2.md`,
`docs/ARCHITECTURE_FROZEN.md` and actual `backend/finagent/contracts.py` before
implementation. Preserve autonomous execution without routine approval pauses.

| Owner | Exclusive files | Must not edit |
|---|---|---|
| architect | contracts.py, __init__.py, tests/test_contracts.py, ARCHITECTURE_FROZEN.md, IMPLEMENTATION_PLAN.md, this file, docs/agent_reports/architect.md | all other implementation files |
| root | project configuration, storage.py, worker.py, api.py, config.py, CLI/migrations, shared fixtures/integration tests, README/STATUS and final integration | other owners' files while their work is active |
| data_engineer | backend/finagent/data.py, tests/test_data.py, own report | contracts, shared fixtures/configuration |
| quant_engineer | backend/finagent/quant.py, backend/finagent/backtest.py, tests/test_quant.py, tests/test_backtest.py, own report | data.py, agents.py, contracts |
| agent_engineer | backend/finagent/agents.py, tests/test_agents.py, own report | quant.py, data.py, contracts |
| frontend_engineer | frontend/, own report | backend and root project configuration |

Schema or interface defect: message root/architect with a concrete blocker;
do not mutate shared code independently. Dependencies are installed by root
only, preventing concurrent virtualenv mutations. Do not commit. Use Python
3.11 and `.venv` with `PYTHONPATH=backend` for pytest. Every report names files,
actual commands/results, model information and remaining issues honestly.

Dependency waves:

1. Architect freezes executable schemas and callable interfaces. Root independently
   creates scaffolding and storage lease/recovery tests.
2. Data and quant implement against frozen contracts. Graph owns only its module;
   it can mock the valuation dependency in tests until quant is available.
   Frontend implements against the frozen API routes/envelopes provided by root.
3. Root integrates bounded worker orchestration, checkpoints and HTTP; each owner
   runs its own offline tests and reports command output.
4. Root runs combined pytest, frontend build/typecheck, local HTTP+UI synthetic
   vertical slice and restart/recovery. Any integration fix returns to the
   original file owner while that owner remains active.

Acceptance: submit run → DB claim → native LangGraph → persisted ticker research
→ immutable ten-pick signal → deterministic six-month DEMO result → rendered
Chinese UI. REAL lacks a verified bundle: return UNAVAILABLE. Missing SA list:
display UNAVAILABLE with no invented list/returns. Shortfall: explicit status,
never padding. All claims of passed tests must include real observed output.
