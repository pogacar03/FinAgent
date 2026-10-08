# Quant engineer execution report

Implementation completed inside the assigned scope: `backend/finagent/quant.py`,
`backend/finagent/backtest.py`, `tests/test_quant.py`, `tests/test_backtest.py`,
`docs/QUANT_POLICY.md`, and this report. No dependency installation, spawning,
commits, secrets, external prices, or copied third-party engine source.

## Delivered

- Versioned five-factor percentile screening with missing-factor reasons, fixed
  weights, stale/publication/currency/action-basis checks, deterministic ties,
  duplicate rejection, minimum evidence coverage, and at most 30 candidates.
- Original guarded P/E and five-year DCF equations; shared assumption protocol
  (`forward_eps` USD/share + `forward_pe` multiple), ledger FACT validation,
  recomputed target checking, explicit single/quant/three-persona version labels.
- Synthetic NVDA 190/240/160 illustration equals target 199, entry 159.20.
- Exact-ten equal-weight freeze with sector cap, immutable version/hash inputs,
  distinct experiment modes, and explicit shortfall rather than padding.
- Agent-independent raw-price replay at NY9:30 actual provider sessions after
  freeze/decision/verified SA publication, six calendar months, common intervals,
  PENDING maturity, full held-panel and action-coverage validation, truthful
  missing/unverified SA, and snapshot-hashed reproducibility.
- Share/cash accounting with splits before same-session dividends, entry ex-date
  exclusion, exit ex-date inclusion, no dividend reinvestment, symmetric assumed
  costs/slippage. Optional limit-entry preserves cash drag and discloses lost
  return vs the same picks' primary counterfactual.
- Aggregation with observed-period coverage, absolute/excess returns, win counts,
  nonoverlapping-window chained FinAgent/SPY NAV, conditional SA NAV, explicit
  synthetic/real/no-result labels, and period-end-only drawdown.

## Actual verification

All commands executed from `/Users/yu/Desktop/FinAgent/finagent_codex_starter`.

| Command/checkpoint | Observed result |
|---|---|
| `.venv/bin/python -m pytest tests/test_quant.py -q` against missing module | collection failed because quant module absent |
| Same command against minimal unimplemented quant skeleton | 9 failed, expected RED behavior |
| Same command after quant implementation | 9 passed |
| `.venv/bin/python -m pytest tests/test_backtest.py -q` against unimplemented skeleton | 12 failed, expected RED behavior |
| `.venv/bin/python -m pytest tests/test_quant.py tests/test_backtest.py -q` initial implementation | 21 passed |
| Unavailable after-exit SPY tail regression test before fix | 1 failed, expected RED |
| `.venv/bin/python -m pytest tests/test_backtest.py -q` after tail fix | 13 passed |
| Missing growth-ledger FACT regression before fallback | 1 failed, expected RED |
| Scoped suites after grounding/DST/exit-action tests | 26 passed |
| Opportunity-cost and empty-aggregate tests before implementation | 2 failed, expected RED (root also observed this active TDD checkpoint) |
| Scoped suites after implementation | **28 passed in 0.06s** |
| `.venv/bin/python -m pytest -q` latest full-suite checkpoint | **70 passed in 2.83s** |
| `.venv/bin/python -m compileall -q backend/finagent/quant.py backend/finagent/backtest.py` | exit 0, no diagnostics |

The tests run offline and use labeled invented typed fixtures. They exercise
stale/PIT validation, grounded arithmetic, mode separation, exact ten/shortfall/
duplicates, common interval, exact/intraday/winter opening timestamps, late SA
publication, missing panels/actions, pending maturity, split/dividend timing,
cost equations, nonfills, and truthful aggregate sample/NAV labels. No historical
outperformance has been tested or claimed.

## Coordination

Sent the assumption protocol to root and agent engineer before integration.
Agent results preserve the root worker's cross-sectional screen score. Data
engineer aligned synthetic observed ledger items to FACT semantics while keeping
DEMO/PIT_UNVERIFIED/SYNTHETIC labels, and keeps SPY issuer metrics missing.
Raised the DEMO raw-bar/split consistency issue to data engineer: synthetic split
shares require correspondingly divided subsequent raw prices (or no demo split);
the engine's own split tests provide consistent raw prices.

## Remaining limitations / issue list

1. No independent exchange-calendar dependency is in the frozen interface.
   Provider SPY sessions anchor the calendar; missing held-stock sessions fail,
   but a missing SPY calendar row cannot itself be independently proven. REAL
   adapter coverage is an input requirement. DEMO uses a labeled weekday calendar.
2. ResearchInput has no action sequence. Momentum is labeled a raw price proxy;
   splits can distort it. It is not claimed to be total-return momentum.
3. CorporateAction has one session and no payment date. Dividend receivables
   accrue at ex-date; payment-date financing and order-book liquidity are outside
   this prototype. All action coverage is an explicit provider attestation.
4. Limit-entry uses a daily-low fill approximation and keeps nonfills as
   zero-interest cash. It is separated from primary selection comparisons.
5. Chained NAV covers observed nonoverlapping windows only. Drawdown uses observed
   period ends, not daily equity. Missing windows and SA coverage are explicit.
6. REAL verified-input labels do not remove source/survivorship or retrospective
   LLM knowledge risks; no five-year history or proven alpha is fabricated.

No outstanding scoped failing tests at the latest verification checkpoint.

## Reviewer P1 follow-up: split-aware pending limit orders

The reviewer correctly identified that comparing later raw prices with an
unchanged decision-time threshold could create a false LIMIT_ENTRY fill after
an intervening split. Reproduced three failing regressions before changing code:
a 2:1 split during the wait, a split on first common entry, and a split before a
late-SA-delayed entry (`3 failed, 18 passed` in the backtest suite).

Pending order thresholds now divide by the cumulative split ratio effective
strictly after the decision-time raw share basis and at/before each possible
fill, including fill-day splits. Waiting-order coverage/actions extend back to
decision so delayed common entry cannot hide a prior split. Splits already
reflected by a decision after their effective open do not adjust the order twice.
Normal post-fill holdings accounting still excludes the fill day's actions,
preventing newly purchased post-split shares from doubling again. PRIMARY
accounting and all public signatures are unchanged.

Additional offline fixtures cover a genuine post-split fill with same-day
dividend exclusion, reverse splits, repeated cumulative splits, and already
observed pre-decision splits. Actual follow-up command results:

- `.venv/bin/python -m pytest tests/test_backtest.py -q` immediately after fix:
  **21 passed in 0.06s**.
- `.venv/bin/python -m pytest tests/test_quant.py tests/test_backtest.py -q` after
  all seven follow-up tests: **35 passed in 0.09s**.
- `.venv/bin/python -m pytest -q`: **80 passed in 2.77s**.

Updated QUANT_POLICY with pending-order share-basis and extended coverage rules.
No unresolved failure at this checkpoint; no dependencies or public contracts
changed.
