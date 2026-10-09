# Agent engineer execution report

Owned files: `backend/finagent/agents.py`, `tests/test_agents.py`,
`docs/AGENT_RUNTIME.md`, and this report. No dependencies installed, no commits,
and no changes to other owners' files.

Implemented native asynchronous LangGraph fan-out/fan-in with isolated persona
contexts, typed immutable snapshots, manager validation, separate 0/1/3 role
ablations, and conditional one-round disagreement review. Python quant engine
recomputes every candidate from cited assumptions. DEMO is explicitly SYNTHETIC,
model deterministic-demo-v1; NVDA illustrative target199/entry159.2 verified.
REAL requires verified evidence, optional structured OpenAI-compatible model
configuration, anonymous prompt identifiers, and no synthetic fallback.

Native saver identity includes run/ticker/snapshot/graph plus exact input/mode/
safety margin. Tests verified checkpoint interruption, close/reopen recovery,
completed-result reuse, and native pending writes retaining successful persona
branches across a failed branch. Retry budgets, transient versus permanent
failures, timeouts, evidence validation and usage metadata were exercised.

Actual verification:

- `.venv/bin/python -m py_compile backend/finagent/agents.py`: exit 0.
- `.venv/bin/python -m pytest tests/test_agents.py tests/test_quant.py -q`:
  **18 passed in 0.57s**, exit 0 (9 agent tests + 9 quant tests).

No live model requests or native PostgreSQL saver tests were run. SQLite native
saver was exercised against actual temporary database files. The worker needs
to replace local single-input screen scores with shortlist cross-sectional
scores before ranking; root was informed. Audit metadata remains graph channels
and is not added to the frozen public ResearchResult schema. Persistent external
trace publication is owned by the worker/integration layer.

## Provider budget follow-up

Added a per-worker event-loop shared LLM HTTP budget, independent of stock and
persona private contexts. Exact knobs: `LLM_CONCURRENCY` (default 3, positive
integer) and `LLM_MIN_INTERVAL_SECONDS` (default 0.2, finite nonnegative).
Every actual HTTP attempt, including retry attempts, passes the shared semaphore
and monotonic request-start gate. Audit records limits/wait latency only;
credentials and prompts remain excluded. Invalid configuration and active-loop
limit changes are rejected. Each worker process has its own allocation.

RED: `.venv/bin/python -m pytest tests/test_agents.py -k
'shared_live_llm_budget or rejects_invalid_configuration' -q` failed 8 cases
before implementation: the timed transport exposed uncapped concurrency and
configuration validation was absent. GREEN: the same command passed 8 cases
(0.36s). The main test runs three concurrent REAL stock graphs (nine personas),
observes actual HTTP overlap/start times, injects a 503, and verifies all ten
HTTP attempts—including the retry—obey concurrency 2 and 0.01-second pacing.
It observes high-water exactly 2 and minimum start spacing >=0.009 seconds.
A further test rejects attempts to bypass limits by changing active-loop config.

Final fresh verification: `.venv/bin/python -m pytest tests/test_agents.py
 tests/test_quant.py -q` => **29 passed in 0.83s**, exit 0 (18 agent cases,
11 quant cases; quant owner added cases during integration).
`.venv/bin/python -m py_compile backend/finagent/agents.py` => exit 0.
No live HTTP requests or PostgreSQL saver checks were performed.
