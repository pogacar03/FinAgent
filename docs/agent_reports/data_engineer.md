# Data engineer report

**Model:** `gpt-6-luna/max` (Luna Max fast setting; the tool exposed no separate Fast flag).

Implemented the synchronous data-provider contract for deterministic DEMO and local REAL bundles. DEMO includes a 21-ticker diversified universe with NVDA and SPY, synthetic weekday OHLCV history and future maturity bars, synthetic financial snapshots with field evidence IDs, and complete synthetic action coverage. Every DEMO record is `Mode.DEMO`, `PIT_UNVERIFIED`, and labeled with `SYNTHETIC` provenance and a `synthetic://` URI. REAL mode requires `REAL_DATA_PATH`, verifies bundle and record hashes, explicit mode/ticker/currency/timestamp fields, and user-supplied PIT attestation; absent attestation downgrades imported records to `PIT_UNVERIFIED`. Unknown or unverified REAL corporate-action coverage returns false.

Seeking Alpha CSV/JSON helpers enforce a Seeking Alpha HTTPS source URL, ten distinct uppercase tickers, an offset-bearing publication time, a verification note, and stable content hashes. Imports remain unverified unless a separate user verification attestation is supplied. The SEC helper fetches original filing metadata with a required identifying `SEC_USER_AGENT`, a process-local nine-request-per-second throttle, and the actual acceptance timestamp when SEC supplies a timezone-aware value; it does not turn filing dates into precise times or use current Company Facts as historical input.

Reviewer finding 6 is fixed: REAL action envelopes retain their effective PIT status and content hash internally. Missing bundle verification evidence downgrades action events. An unverified event inside a requested interval makes `actions_complete` false, and `actions` raises `ProviderUnavailable`; verified complete coverage with no action events remains valid. A regression test drives a REAL backtest and confirms it returns validation failure without FinAgent, SPY, Seeking Alpha, or excess-return results for an interval containing an unverified event.

Files changed:

- `backend/finagent/data.py`
- `tests/test_data.py`
- `docs/PROVIDERS.md`
- `data/benchmarks/sa_import_template.csv`
- `docs/agent_reports/data_engineer.md`

Verification performed with the required project interpreter:

- Before the provider implementation: `.venv/bin/python -m pytest tests/test_data.py -q` — collection failed as expected with `ModuleNotFoundError: No module named 'finagent.data'`.
- Finding 6 RED: `.venv/bin/python -m pytest tests/test_data.py -q` — `2 failed, 10 passed`; the failures reproduced unverified action use with absent attestation and with verified coverage.
- Finding 6 GREEN: `.venv/bin/python -m pytest tests/test_data.py -q` — `13 passed in 0.12s`.
- Full repository suite after the fix: `.venv/bin/python -m pytest -q` — `86 passed in 2.91s`.
- Syntax check: `.venv/bin/python -m py_compile backend/finagent/data.py` — passed.

The DEMO action stream contains synthetic dividends and no split events, so its RAW bars remain internally consistent. The REAL bundle supports split records with explicit action coverage. The SEC throttle is process-local; coordinating one SEC request budget across multiple independent worker processes is outside this helper's scope. No live SEC or market request was made; all tests remain offline.
