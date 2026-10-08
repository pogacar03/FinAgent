# Data providers and imports

FinAgent has two explicit data modes. `DEMO` is deterministic fixture data for offline execution. `REAL` reads a local, timestamped JSON bundle selected by `REAL_DATA_PATH`. A missing or invalid REAL bundle raises `ProviderUnavailable` with code `UNAVAILABLE`; it never switches to DEMO.

```python
from datetime import datetime, timezone
from finagent.contracts import Mode
from finagent.data import provider_for

provider = provider_for(Mode.DEMO)
research = provider.research_input(
    "NVDA", datetime(2025, 12, 31, 21, tzinfo=timezone.utc)
)
```

## DEMO data

The fixed illustrative universe has 21 tickers across multiple sectors and includes `NVDA` and `SPY`. Its bars use a deterministic Monday-to-Friday synthetic calendar; weekdays do not imply an actual exchange session, and the calendar has no US market holiday or trading-status claim. Prices, volumes, financial fields, and dividends are invented. Every provider record uses a `SYNTHETIC` source, a `synthetic://` URI, `Mode.DEMO`, and `PIT_UNVERIFIED`. Evidence snapshots carry the same status and a warning that the values are not historical investment evidence. Financial-field evidence IDs refer to each populated field; those are observations in the fixture, while future forecast assumptions belong in report assumptions.

`research_input(ticker, decision_at)` returns at least 60 weekday bars when history exists and filters every market, financial, and evidence record to `available_at <= decision_at`; it also excludes sessions after the decision date. `bars(ticker, start, end)` can return later fixture dates for the July 2025–January 2026 maturity window. `actions_complete` is true for DEMO because the fixture generator owns the complete synthetic action series for any requested dates. These outputs are for demonstration and offline tests only.

## REAL bundle

Set `REAL_DATA_PATH=/absolute/path/to/real_bundle.json`. The provider loads and validates the file once, hashes it, and keeps its parsed records in memory. It does not update the file or fetch replacement values. Preserve the file and its source artifacts after import so the hash and the evidence remain reproducible.

The top-level object has this shape:

```json
{
  "schema_version": 1,
  "mode": "REAL",
  "verification": null,
  "universes": [],
  "market_bars": [],
  "financials": [],
  "actions": [],
  "action_coverage": [],
  "bundle_hash": "lowercase SHA-256"
}
```

`stable_hash` is the lowercase SHA-256 of `json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False).encode("utf-8")`. `bundle_hash` is `stable_hash` of the full object with `bundle_hash` omitted. Each universe, market bar, and financial snapshot has its contract fields, including explicit `mode: REAL`, `currency: USD`, `pit_status`, timezone-aware `as_of` and `available_at`, source, source URI, and `content_hash`. Its `content_hash` is `stable_hash` of that row with `content_hash` omitted. The loader checks both hash levels, the contract ticker and timestamps, the mode, and the currency. Bundle values are not trusted as PIT verified merely because a row says `PIT_VERIFIED`.

To retain `PIT_VERIFIED`, include a user-supplied verification attestation:

```json
{
  "status": "PIT_VERIFIED",
  "verified_by": "reviewer or organization",
  "verified_at": "2026-10-08T09:00:00+00:00",
  "evidence_uri": "file:///path/to/archived-source-review.pdf",
  "notes": "Describe how original publication and availability times were checked."
}
```

The loader checks that those fields are present and timestamped; it does not independently inspect or certify the referenced artifact. Without this user-supplied evidence, every imported universe, bar, and financial snapshot is downgraded to `PIT_UNVERIFIED`, even if the row requested `PIT_VERIFIED`. A verified attestation does not upgrade individual rows that are themselves unverified. No current SEC Company Facts values are treated as historical point-in-time evidence.

`actions` entries wrap the `CorporateAction` contract because that contract has no mode or PIT fields:

```json
{
  "record": {
    "ticker": "NVDA",
    "session": "2025-12-15",
    "kind": "DIVIDEND",
    "value": 0.01,
    "source": "provider name",
    "source_uri": "https://provider.example/action-record",
    "available_at": "2025-12-15T23:00:00+00:00",
    "currency": "USD"
  },
  "mode": "REAL",
  "pit_status": "PIT_VERIFIED",
  "content_hash": "stable_hash of this envelope without content_hash"
}
```

Every action also needs a corresponding coverage declaration if the provider can certify a complete action history. Coverage rows contain `ticker`, inclusive `start` and `end` dates, boolean `complete`, timezone-aware `available_at`, `source_uri`, `currency: USD`, `mode: REAL`, and `pit_status`, plus `content_hash` computed over the row without that field. The action envelope's own `pit_status` is retained by the provider; an unverified event makes its requested interval incomplete even when the coverage row is verified. `actions(ticker, start, end)` raises `ProviderUnavailable` if the interval contains an unverified event, so a caller cannot silently use it in a validated return. `actions_complete(ticker, start, end)` returns true only when complete, verified coverage spans the whole requested interval and every event in it is verified; missing, unverified, or gapped coverage returns false. Verified complete coverage with no action events is valid. Unknown coverage is never interpreted as “no actions.”

## Seeking Alpha benchmark imports

Start from [`data/benchmarks/sa_import_template.csv`](../data/benchmarks/sa_import_template.csv). Supply ten rows, one canonical uppercase ticker per row, and repeat the same `period`, timezone-aware `published_at`, original article `source_uri`, and `verification_note` on every row. The source URL must be HTTPS on `seekingalpha.com` or a subdomain. `load_benchmark_csv(path)` and `load_benchmark_json(path)` return a canonical `BenchmarkList`; `validate_benchmark_list(value)` applies the same checks to an object. Imports are hashed and default to `PIT_UNVERIFIED`, even when an input object claims `PIT_VERIFIED`.

Verification requires separate, explicit user evidence passed to the helper as `verification_evidence={"verified_by": ..., "verified_at": ..., "evidence_uri": ..., "notes": ...}`. A source URL alone never marks a benchmark verified. The helper records the supplied reviewer, time, evidence URI, and note in `verification_note`; it checks the structure but does not authenticate the reviewer or inspect the artifact. The API accepts either a plain BenchmarkList (unverified by default), or an envelope `{"list": {...}, "verification_evidence": {...}}` with this explicit attestation. Malformed evidence returns HTTP 422. Benchmark revisions are append-only; each backtest binds the revision selected at submission, and the current registry is displayed separately.

The CSV importer requires exactly these columns and exactly ten non-empty ticker rows:

```text
period,published_at,source_uri,ticker,verification_note
```

## SEC original filing metadata helper

`fetch_sec_original_filings(cik)` reads the SEC Submissions API and requires an identifying `SEC_USER_AGENT` environment variable (or an explicit `user_agent`) containing a contact email. It throttles this process to at most nine requests per second. The returned `SECOriginalFiling` retains the accession number, filing date, original filing-document URL, and the SEC `acceptanceDateTime` when that field includes a timezone. When no exact acceptance timestamp is present, `accepted_at` is `None`; a filing date is not invented into a precise timestamp. This helper supplies filing metadata only and does not fetch present-day company-facts values for historical research.

See the [SEC EDGAR API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces), [Accessing EDGAR Data](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data), and [SEC Developer Resources](https://www.sec.gov/about/developer-resources) for endpoint, user-agent, and fair-access guidance. SEC guidance currently sets a 10 requests/second ceiling per user; this helper uses a lower process-local rate.

## Execution dataset revisions

A backtest captures its own bundle byte hash at submission and rejects changes before worker execution. Later versions may append observations available after the frozen decision cutoff. The worker compares the original universe and each selected stock's decision-time ResearchInput against saved immutable artifacts, excluding only runtime version metadata; any historical amendment is rejected as FROZEN_RESEARCH_INPUT_CHANGED. Backtesting never reruns the LLM or changes frozen picks. Preserve both research and execution bundles and original source artifacts for replay.
