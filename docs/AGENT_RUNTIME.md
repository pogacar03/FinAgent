# Native research runtime

`backend/finagent/agents.py` implements an asynchronous native LangGraph
`StateGraph`. It uses the frozen `research_stock` interface. The worker supplies
an opened native `AsyncSqliteSaver` (offline development) or
`AsyncPostgresSaver` (deployment), and a run identifier as `thread_id`.

The graph validates its immutable snapshot before three persona nodes execute
in the same fan-out superstep. Each persona constructs its own frozen
`ResearchInput` view and ephemeral `PrivateContext`: messages, tool budget and
controlled audit events. Each writes a distinct report/audit channel. The
manager receives only typed report data, validates every evidence reference,
and never merges raw messages. The same currency (`USD`), corporate-action
basis (`RAW_WITH_ACTIONS`) and 12-month horizon are enforced.

| Mode | Persona calls | Valuation |
|---|---:|---|
| `quant_only` | 0 | Explicit versioned quant P/E policy baseline |
| `single_agent_skills` | 1 | One persona combines value/growth/conservative skills |
| `multi_persona` | 3 parallel | Fixed 50/30/20 Value/Growth/Conservative blend |
| `multi_persona_debate` | 3, optionally 3 parallel review calls | Same blend, at most one review |

The review threshold defaults to `(max target / min target) - 1 > .25`.
A review passes anonymous typed assumptions/evidence summaries, never private
messages. There is no loop back to the manager. Remaining disagreement receives
`UNRESOLVED_DISAGREEMENT` risk flags. This flag does not claim consensus; the
published target remains a declared fixed policy blend. Missing/invalid
forecasts abstain and cannot become eligible stocks.

## DEMO and REAL

DEMO uses a deterministic assumption generator, model
`deterministic-demo-v1`; it performs no LLM call. Reports contain `SYNTHETIC`
flags and describe all forecast parameters as assumptions. Synthetic fixture
observations are FACT evidence *within the fixture*, not authenticated market
facts. `PIT_UNVERIFIED` is permitted only for DEMO. Positive evidence EPS and
bounded source revenue growth ground forward EPS; role-specific P/E multiples
are declared subjective assumptions. The NVDA illustration uses explicitly
synthetic multiples to yield 190/240/160, target 199 and entry 159.20. It is not a
real historical forecast. Other tickers use declared multiples 20/26/16;
single skills uses 21 and the quant baseline follows quant's separate policy.

REAL requires verified evidence and source records. Configure `LLM_API_KEY`,
`LLM_MODEL`, and optionally `LLM_BASE_URL` (default OpenAI-compatible `/v1`
endpoint). The adapter uses `/chat/completions` JSON response mode. It sends an
anonymous `instrument_1`, anonymous evidence IDs, numeric evidence, requested
skills, and optional typed review assumptions. It excludes tickers, dates,
source URIs, raw filings, credentials and unrelated history from prompts.
Evidence aliases are mapped back locally. An arbitrary model's historical
knowledge cannot be proven absent; retrospective results still need the
product's historical-contamination warning.

Only returned assumptions are accepted. Every numeric assumption must cite
known FACT evidence. Python `quant.target_from_assumptions` computes the target;
the model is never trusted to calculate it. `forward_eps` is USD/share and
`forward_pe` is a multiple. Missing model configuration returns explicit
`UNAVAILABLE_LLM_CONFIGURATION` abstention; no synthetic forecast substitutes
for a REAL model. Invalid structured responses are terminal validation errors.

## Recovery and observability

Checkpoint identity includes supplied run/thread identity, ticker, snapshot ID,
graph version and a hash of the entire input, ablation and safety margin.
Checkpoint state consists of typed JSON envelopes and controlled audit events;
raw ephemeral messages are not checkpointed. An existing unfinished checkpoint
resumes with `ainvoke(None, config)`. Completed checkpoints return the validated
saved result. Native pending writes preserve successful parallel branches when
another branch fails. See [LangGraph persistence documentation](https://docs.langchain.com/oss/python/langgraph/persistence).

Actual REAL HTTP attempts also share one `LLMBudget` per worker event loop,
across all stock graphs and personas. `LLM_CONCURRENCY` defaults to 3 and must
be a positive integer; `LLM_MIN_INTERVAL_SECONDS` defaults to 0.2 and must be
finite and nonnegative. A semaphore bounds in-flight HTTP calls and a monotonic
start gate spaces request starts, including each retry. The budget is not a
persona context and contains no messages, evidence or credentials. Changing
limits within an active loop is rejected to prevent independent budgets from
bypassing the cap; restart the worker to apply configuration. Limits are per
worker process, so multiple worker processes multiply the provider allocation.
Controlled audit events record limits and budget wait milliseconds only.

Each persona's tool budget allows at most three calls per generation/review
phase. Timeouts, HTTP 429/5xx and network failures retry at most three times with
capped jitter/backoff; malformed data and permanent HTTP errors never retry.
Exceptions expose controlled codes: `ResearchValidationError` has
`VALIDATION_FAILED`, `ResearchUnavailable` has `UNAVAILABLE`, and
`TransientToolError` has `TRANSIENT_PROVIDER_ERROR`. Audit channels retain phase,
status, attempt, latency and provider-supplied integer token usage; they omit
response bodies and credentials. They are available from graph state to the
worker's persistence/observability layer, not added to the frozen public
`ResearchResult` schema.

The graph's single-stock factor score is only a local eligibility score. The
worker must replace it with the shortlist's cross-sectional deterministic
screen score/factors before ranking stocks; otherwise all complete observations
have identical percentile scores.

## Verification

Offline tests use synthetic fixtures and mocked model transport. They exercise
actual parallel fan-out (all roles must start before any can finish), immutable
views and isolated histories, 0/1/3 ablations, bounded review, FACT-reference
validation, Python target recomputation, transient versus permanent handling,
anonymous REAL prompts and token metadata, native SQLite close/reopen,
and shared HTTP concurrency/start pacing across three concurrent stocks' nine
personas plus a transient retry. That test observes actual overlap and request
start timestamps inside the mocked async HTTP transport, rather than asserting
only the number of mock calls. Invalid limits and active-loop reconfiguration
are also rejected.
A branch-failure test verifies successful roles execute once while only the
failed role executes again after reopening the checkpoint database.

Run `.venv/bin/python -m pytest tests/test_agents.py tests/test_quant.py -q`.
Production PostgreSQL saver and live model/provider access need configured
services/credentials and are not claimed verified by these offline tests.
