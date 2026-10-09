# Quantitative policy and frozen replay

All DEMO inputs and outputs are synthetic. Chronology verification inside a
synthetic fixture does not verify historical prices, financials, picks, or alpha.
The equations in `backend/finagent/quant.py` and `backtest.py` are original narrow
implementations; no FinRobot or vectorbt source is copied or vendored.

## Versioned screening

`five-factor-rank-v1` uses these fixed weights; every factor is ascending (larger
is preferred). Present values receive cross-sectional midrank percentiles, with
all equal observations scored 0.5. Ties in composite score break by canonical
ticker. The same set in a different input order therefore gives the same result.

| Factor | Raw input | Weight |
|---|---|---:|
| Value | positive reported EPS / latest admissible close | 0.30 |
| Growth | reported revenue growth | 0.25 |
| Profitability | reported profit margin | 0.20 |
| Momentum | earliest-to-latest raw close return, at least 90 calendar days | 0.15 |
| EPS revisions | supplied dated EPS revision | 0.10 |

Missing factors are recorded with a reason, receive zero contribution, and do
not cause remaining weights to be renormalized. Fewer than three observed
factors excludes an input. Thus SPY, with no issuer operating metrics, cannot
enter the stock shortlist. No negative earnings yield is treated as attractive
Value. The shortlist contains at most 30 names and rejects duplicate tickers or
mixed decisions/modes. Ranking occurs over the common eligible universe; the
worker preserves that screen score rather than reranking each singleton graph.

Momentum is explicitly a **raw price proxy**, not action-adjusted or total-return
momentum. ResearchInput has no corporate-action sequence. A split inside its
history can distort this factor; its output warning preserves that limitation.
Do not label this proxy a validated action-adjusted momentum signal. A future
version should expose admissible research actions and version any new adjustment.

All records must have USD and RAW_WITH_ACTIONS basis. Future observations or
publication times are excluded. Latest market observation must be no more than
10 calendar days old; latest financial availability no more than 180 days old;
its financial period end no more than 550 days old. REAL additionally requires
PIT_VERIFIED across market, financials, snapshot, and ledger. DEMO allows its
explicitly unverified invented observations with synthetic warnings. Current
`yfinance.info` or current consensus is not a historical input.

## Forecast adapter protocol

`target_from_assumptions(assumptions)` recomputes one of two transparent models:

1. Forward P/E: exactly `forward_eps` (USD/share), `forward_pe` (multiple).
   Target = forward EPS × forward P/E. EPS must be positive; P/E must be in
   (0,100]. Negative/zero EPS is unsupported by this narrow P/E equation.
2. Five-year DCF: exactly `fcf_per_share` (USD/share), `fcf_growth`, `discount_rate`,
   `terminal_growth` (all ratios). At the common 12-month forecast anchor, project
   the supplied forward FCF/share for years 1–5, discount each, and add terminal
   value `FCF5 × (1+terminal_growth)/(discount_rate-terminal_growth)` discounted
   from year 5. FCF must be positive, growth in [-0.5,0.5], discount in (0,0.5],
   terminal growth in [-0.1,discount). The discount spread must be positive.

Duplicate/unknown assumptions, wrong units, invalid ranges, nonfinite or
nonpositive results fail. The arithmetic helper alone does not verify sources;
`valuate` performs the evidence checks with the immutable input snapshot.
Every forecast assumption cites at least one known FACT ID; each report also
cites known FACT IDs. Report ticker, snapshot, currency, action basis, and
12-month horizon must match. A supplied numeric target that disagrees with its
computed assumptions causes abstention. Citing evidence grounds an input;
it does not establish that a subjective growth/multiple/discount forecast is true.

| Report set | Calculation | Valuation version |
|---|---|---|
| Three distinct personas | Value 0.50 + Growth 0.30 + Conservative 0.20 | blend-50-30-20-v1 |
| One persona | one recomputed forecast; no implicit blend | single-persona-v1 |
| No reports | positive EPS × (1+bounded reported growth) × policy P/E20 | quant-pe-v1 |
| Two reports or duplicate persona | explicit abstention | no partial reweighting |

Quant-only EPS must match a numeric `earnings_per_share` FACT in the ledger.
Reported growth must also match a `revenue_growth` FACT; otherwise a disclosed
zero-growth policy fallback applies. Valid growth is clipped to [-0.2,0.3].
P/E20 is explicitly a policy assumption rather than observed consensus.
The graph's research mode remains separate from the valuation version, so
single-agent skills, three personas, and bounded debate are distinct ablations.
Fair value remains unset when only a 12-month target is computed; no identical
price is silently assigned to two different valuation concepts.

Entry threshold = target × (1 − safety margin), margin in [0,1). The documented
**SYNTHETIC NVDA** illustration 190/240/160 yields target **199** and entry
**159.20** with margin 0.20. These are not real NVDA historical forecasts.

## Frozen selection

`freeze_signal` rejects duplicate results and mixed eligible research modes or
version bundles. It excludes ineligible/abstained results, wrong mode/cutoff,
future evidence, or unverified REAL records. It sorts by preserved factor score
then ticker, and greedily respects `max_per_sector` (default four). Exactly ten
unique eligible names are required, each weight 0.1. If the universe or sector
constraint yields fewer than ten, it returns None: no padding or partial signal.
Frozen IDs hash the actual selected snapshots, scores, prices, versions, config,
run, period, decision, and freeze. DEMO historical freeze is a modeled event;
actual job creation remains a separate current-time audit record.

## Primary replay and accounting

Replay imports no agent code and invokes no LLM. It takes the immutable signal,
provider data, evaluation timestamp, optional independently imported SA list,
and explicit cost assumptions.

- A session opens at 09:30 **America/New_York**, with DST, rather than at the
  MarketBar observation timestamp or midnight. The first eligible SPY session
  open must be strictly later than decision, freeze, and verified SA publication.
  An intraday release cannot buy the already elapsed opening price. Equality at
  the opening instant advances to the next eligible session.
- Six months means calendar months with end-of-month clamping. Exit is the first
  SPY session at/after the six-month anniversary. All included portfolios use the
  same entry and exit. If not mature, PENDING has no realized portfolio/excess.
- SPY's supplied session panel anchors the provider calendar. The provider must
  supply a complete calendar: without an independent exchange calendar, a
  missing SPY calendar row cannot be independently detected by this interface.
  DEMO uses a labeled synthetic weekday calendar, not actual exchange holidays.
  Every held ticker must have every SPY session in the interval. Missing entry,
  exit, or intermediate rows causes VALIDATION_FAILED; the engine never moves
  to a later favorable open to hide a missing ticker. Missing action-coverage
  attestation also fails even when the actions tuple is empty.
- Required bars must be observable by evaluation, correct ticker/mode, USD,
  RAW_WITH_ACTIONS, and PIT_VERIFIED in REAL mode. Only the needed interval is
  validated: an unpublished current-day bar after a historical exit is irrelevant.
- A verified SA list must match signal period and mode. An absent list is
  UNAVAILABLE; an unverified/mismatched list has no SA portfolio, excess, or
  timing influence. No invented SA constituents are substituted.
- Start with one share and capital `raw_entry × (1+slippage) × (1+cost)` per
  holding, equivalent to normalized equal-weight allocations. At each action
  session, apply splits **before** per-share dividends. Dividend values are in
  that session's post-split share denomination. Splits multiply current shares;
  dividends add cash. Dividends remain cash, with no reinvestment.
- Entry ex-date actions are excluded because the position was not held over the
  preceding close. Exit ex-date actions are included because the position was
  held overnight before selling at the open. Dividend cash is accrued ex-date
  entitlement; payment-date financing is not modeled because the action schema
  supplies only one session. Actions after exit are excluded. Duplicate same-day
  same-kind actions fail; providers must consolidate them first.
- Proceeds = split-adjusted shares × raw exit × (1−slippage) × (1−cost)
  + accumulated dividends. Total return = proceeds / initial capital − 1.
  HoldingReturn prices are source raw prices; bps assumptions describe execution
  adjustments. `dividends` means cash per original purchased share, and
  `split_factor` means final shares per original share. Apply identical costs to
  FinAgent, SPY, and valid SA portfolios. Excess = return difference ×100,
  expressed as percentage points.

Corporate-action completeness is a provider attestation, not something absence
of action rows can prove. REAL import verification also does not remove possible
retrospective LLM knowledge contamination, survivorship bias, or source errors.

## Secondary limit-entry experiment and aggregation

LIMIT_ENTRY remains a separately labeled policy. The frozen threshold is in
decision-time raw share units. Before each candidate fill, divide it by the
cumulative split ratio effective after the decision and at/before that session,
including a split on the fill day. For example, a pending threshold of 96 becomes
48 after a 2:1 split; a raw price of 50 must not fill it merely because its
presplit economic price was 100. Reverse splits raise the pending per-share
threshold proportionally. Splits already effective by the decision are excluded
from this pending-order adjustment.

Action-coverage attestation and action retrieval for these pending FinAgent
orders begin at the decision date, covering splits before a delayed common entry
(for example due to late SA publication). Other primary portfolios still require
coverage from their common entry. The common interval and equal allocations do
not change. After a fill, normal share/cash accounting excludes fill-date actions:
shares bought after the split must not receive that split again.

For the same common evaluation window, each FinAgent allocation waits for the
first pre-exit bar with low at or below the split-adjusted threshold. If open is
below the threshold, use open; otherwise threshold. Adverse slippage is capped
at that adjusted limit (fees remain separate). This
is a simplified daily-bar fill model and does not estimate order-book liquidity.
Nonfills retain full zero-interest cash weight and zero return; comparisons use
all ten allocations. Each result discloses opportunity cost in percentage points
versus PRIMARY for the **same frozen picks**, including cash drag. SPY/SA remain
primary open-to-open benchmarks, preserving the interval comparison.

`aggregate_backtests` reports supplied/completed/valid-SA sample counts, coverage,
per-period absolute and excess returns, wins, and observed-window chained NAV.
Mixed modes/policies, duplicate completed periods, or overlapping completed
windows fail. Missing periods are disclosed and never treated as zero-return
observations. SA NAV is absent unless all valid windows have SA results. NAV
chains only the supplied nonoverlapping windows, so it is not evidence of complete
five-year performance. Drawdown uses observed **period ends only**, explicitly
not a daily or intraperiod maximum drawdown. Truth labels are SYNTHETIC_DEMO,
REAL_VERIFIED_INPUTS, or NO_RESULTS; none is a claim of proven alpha.
