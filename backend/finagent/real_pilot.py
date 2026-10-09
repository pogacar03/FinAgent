"""Read-only single-NVDA evidence pilot; never creates a ten-stock signal.

Current retrospective market feeds lack original availability proof. The strict
chain therefore fails closed; a separately labelled diagnostic may reuse the
existing share/cash arithmetic without claiming PIT validation or strategy alpha.
"""
from __future__ import annotations

import hashlib
import json
import re
import platform
import os
import subprocess
from datetime import date, datetime, time, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from .backtest import _holding, _open, _six_months
from .contracts import Assumption, FinancialSnapshot, MarketBar, Mode, PITStatus, stable_hash
from .quant import target_from_assumptions

RELEASE_URL = 'https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-fourth-quarter-and-fiscal-2025'
NASDAQ_PRICES_URL = 'https://api.nasdaq.com/api/quote/NVDA/historical?assetclass=stocks&fromdate=2025-02-28&todate=2025-09-05&limit=9999'
NASDAQ_ACTIONS_URL = 'https://api.nasdaq.com/api/quote/NVDA/dividends?assetclass=stocks'
ISSUER_PRICE_URL = 'https://investor.nvidia.com/stock-info/historical-price-lookup/default.aspx'
YAHOO_URL = 'https://query1.finance.yahoo.com/v8/finance/chart/NVDA?period1=1740700800&period2=1757116800&interval=1d&events=div%2Csplits'
DECISION_AT = datetime(2025, 2, 28, 23, 59, 59, tzinfo=ZoneInfo('America/New_York'))
UTC = timezone.utc
SOURCE_SPECS = {
    'issuer_release': (RELEASE_URL, 'PRIMARY_ISSUER'),
    'nasdaq_prices': (NASDAQ_PRICES_URL, 'PRIMARY_EXCHANGE'),
    'nasdaq_dividends': (NASDAQ_ACTIONS_URL, 'PRIMARY_EXCHANGE'),
    'issuer_prices': (ISSUER_PRICE_URL, 'PRIMARY_ISSUER_HTML_BOOTSTRAP'),
    'secondary_yahoo_prices': (YAHOO_URL, 'SECONDARY_MARKET_FEED'),
}


class PilotUnavailable(ValueError):
    """Terminal evidence gaps are explicit, not repaired with invented data."""


class _Tables(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self.table: list[list[str]] | None = None
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == 'table':
            self.table = []
        elif tag == 'tr' and self.table is not None:
            self.row = []
        elif tag in ('td', 'th') and self.row is not None:
            self.cell = []

    def handle_data(self, data: str) -> None:
        self.text.append(data)
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ('td', 'th') and self.cell is not None:
            if self.row is not None:
                self.row.append(' '.join(''.join(self.cell).split()))
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            if self.table is not None:
                self.table.append(self.row)
            self.row = None
        elif tag == 'table' and self.table is not None:
            self.tables.append(self.table)
            self.table = None


def conservative_available_bound(published: date) -> datetime:
    """Next midnight in issuer-local Pacific time: upper bound, NOT exact time."""
    return datetime.combine(published + timedelta(days=1), time(), ZoneInfo('America/Los_Angeles')).astimezone(UTC)


def parse_fy25_release(html: str) -> dict[str, Any]:
    parser = _Tables()
    parser.feed(html)
    plain = ' '.join(' '.join(parser.text).split())
    publication = re.search(r'<div[^>]+class=[\"\']article-date[\"\'][^>]*>\s*February 26, 2025\s*</div>', html)
    if publication is None or 'January 26, 2025' not in plain:
        raise PilotUnavailable('RELEASE_PUBLICATION_OR_FINANCIAL_PERIOD_MISSING')
    candidates = [t for t in parser.tables if t and t[0] and t[0][0].startswith('GAAP')
                  and any('FY25' in row and 'FY24' in row for row in t)]
    if len(candidates) != 1:
        raise PilotUnavailable('UNIQUE_FY25_GAAP_SUMMARY_MISSING')
    rows = {row[0].rstrip('*'): row[1:] for row in candidates[0] if len(row) > 1}
    def number(label: str, index: int = 0) -> float:
        try:
            cell = rows[label][index]
            if not re.fullmatch(r'\$?[\d,]+(?:\.\d+)?', cell):
                raise ValueError()
            return float(cell.replace('$', '').replace(',', ''))
        except (KeyError, ValueError, IndexError):
            raise PilotUnavailable(f'GAAP_CELL_MISSING_OR_INVALID:{label}:{index}') from None
    revenue = number('Revenue') * 1_000_000
    prior_revenue = number('Revenue', 1) * 1_000_000
    net_income = number('Net income') * 1_000_000
    if prior_revenue <= 0 or revenue <= 0:
        raise PilotUnavailable('INVALID_REVENUE')
    return {'period_end': '2025-01-26', 'publication_date': '2025-02-26',
            'publication_precision': 'DATE_ONLY',
            'availability_upper_bound': conservative_available_bound(date(2025, 2, 26)).isoformat(),
            'availability_policy': 'DATE_BOUND_NEXT_PACIFIC_MIDNIGHT_NOT_EXACT_RELEASE_TIMESTAMP',
            'revenue': revenue, 'prior_revenue': prior_revenue, 'net_income': net_income,
            'earnings_per_share': number('Diluted earnings per share'),
            'eps_basis': 'GAAP_DILUTED_USD_PER_POST_2024_SPLIT_SHARE',
            'revenue_growth': revenue / prior_revenue - 1, 'profit_margin': net_income / revenue,
            'provenance_status': 'ISSUER_DATED_RELEASE_CONSERVATIVE_BOUND',
            'analyst_consensus': None, 'historical_consensus_status': 'UNAVAILABLE'}


def build_policy_assumptions(facts: dict[str, Any], source_hash: str) -> tuple[Assumption, ...]:
    growth = max(-.2, min(.3, float(facts['revenue_growth'])))
    return (Assumption(name='forward_eps', value=float(facts['earnings_per_share']) * (1 + growth),
                       unit='USD/share', evidence_ids=(source_hash,),
                       rationale='quant-pe-v1 policy extrapolation: GAAP EPS times bounded reported revenue growth; no consensus'),
            Assumption(name='forward_pe', value=20, unit='multiple', evidence_ids=(source_hash,),
                       rationale='quant-pe-v1 fixed policy multiple; not analyst consensus'))


def pit_gate(decision_at: datetime, financial_available_bound: datetime, *,
             price_pit_verified: bool, actions_complete: bool) -> dict[str, Any]:
    reasons: list[str] = []
    if financial_available_bound > decision_at:
        reasons.append('FINANCIAL_RELEASE_UNAVAILABLE_AT_DECISION')
    if not price_pit_verified:
        reasons.append('HISTORICAL_PRICE_PIT_UNVERIFIED')
    if not actions_complete:
        reasons.append('CORPORATE_ACTION_COVERAGE_UNVERIFIED')
    return {'status': 'UNAVAILABLE' if reasons else 'PASSED', 'reasons': reasons,
            'price_pit_status': 'PIT_VERIFIED' if price_pit_verified else 'PIT_UNVERIFIED',
            'actions_complete': actions_complete}


def parse_yahoo_chart(blob: dict[str, Any]) -> dict[str, Any]:
    try:
        result = blob['chart']['result'][0]
        if result['meta']['symbol'] != 'NVDA' or result['meta']['currency'] != 'USD':
            raise PilotUnavailable('PRICE_SYMBOL_OR_CURRENCY_MISMATCH')
        q = result['indicators']['quote'][0]
        bars = []
        for i, timestamp in enumerate(result['timestamp']):
            bar = {'session': datetime.fromtimestamp(timestamp, UTC).astimezone(ZoneInfo('America/New_York')).date().isoformat(),
                   'provider_bar_timestamp': datetime.fromtimestamp(timestamp, UTC).isoformat(),
                   **{key: q[key][i] for key in ('open', 'high', 'low', 'close', 'volume')}}
            if any(bar[key] is None for key in ('open', 'high', 'low', 'close', 'volume')):
                raise PilotUnavailable('MISSING_OHLCV_NO_FORWARD_FILL')
            bars.append(bar)
        if not bars or len({b['session'] for b in bars}) != len(bars):
            raise PilotUnavailable('EMPTY_OR_DUPLICATE_PRICE_SESSIONS')
        return {'bars': bars, 'events': result.get('events', {}), 'pit_status': 'PIT_UNVERIFIED',
                'price_basis': 'PROVIDER_QUOTE_OHLC_NOT_ADJCLOSE_RAW_BASIS_UNCERTIFIED',
                'availability_proof': None, 'origin': 'YAHOO_SECONDARY_NOT_EXCHANGE_ARCHIVE',
                'coverage_verified': False}
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        if isinstance(exc, PilotUnavailable):
            raise
        raise PilotUnavailable('PRICE_RESPONSE_MALFORMED') from None


def parse_nasdaq_dividends(blob: dict[str, Any]) -> dict[str, Any]:
    try:
        rows = blob['data']['dividends']['rows']
        events = []
        for row in rows:
            if row['type'] != 'Cash' or row.get('currency') != 'USD':
                raise PilotUnavailable('UNSUPPORTED_DIVIDEND_TYPE_OR_CURRENCY')
            session = datetime.strptime(row['exOrEffDate'], '%m/%d/%Y').date()
            if date(2025, 3, 3) <= session <= date(2025, 9, 3):
                events.append({'ticker': 'NVDA', 'session': session.isoformat(), 'kind': 'DIVIDEND',
                               'value': float(row['amount'].replace('$', '')),
                               'declaration_date': datetime.strptime(row['declarationDate'], '%m/%d/%Y').date().isoformat(),
                               'payment_date': datetime.strptime(row['paymentDate'], '%m/%d/%Y').date().isoformat()})
        return {'events': events, 'coverage_verified': False,
                'reason': 'DIVIDEND_ENDPOINT_DOES_NOT_ATTEST_SPLIT_AND_DIVIDEND_COMPLETENESS_OR_HISTORICAL_AVAILABILITY'}
    except (KeyError, TypeError, ValueError):
        raise PilotUnavailable('DIVIDEND_RESPONSE_MALFORMED') from None


def fetch_snapshot(url: str, directory: Path, label: str) -> tuple[dict[str, Any], bytes]:
    directory.mkdir(parents=True, exist_ok=True)
    fetched_at = datetime.now(UTC).isoformat()
    try:
        with httpx.Client(timeout=25, follow_redirects=True, headers={
            'User-Agent': 'FinAgent-Research-Pilot/1.0', 'Accept': 'application/json,text/html'}) as client:
            response = client.get(url)
        content = response.content
        digest = hashlib.sha256(content).hexdigest()
        path = directory / f'{label}-{digest}.raw'
        path.write_bytes(content)
        meta = {'source_url': url, 'resolved_url': str(response.url), 'fetched_at': fetched_at,
                'http_status': response.status_code, 'content_sha256': digest,
                'snapshot_id': f'{label}:{digest}', 'raw_file': str(path.resolve()),
                'content_type': response.headers.get('content-type'),
                'source_last_modified': response.headers.get('last-modified'),
                'status': 'FETCHED' if response.status_code == 200 else 'UNAVAILABLE'}
    except httpx.HTTPError as exc:
        content = b''
        meta = {'source_url': url, 'fetched_at': fetched_at, 'status': 'UNAVAILABLE',
                'error_code': type(exc).__name__, 'http_status': None, 'snapshot_id': None}
    return meta, content


def diagnostic_price_only(parsed: dict[str, Any], *, fetched_at: datetime,
                          source_hash: str) -> dict[str, Any]:
    """Existing accounting with NO actions: explicitly not investment total return."""
    panel: dict[date, MarketBar] = {}
    for row in parsed['bars']:
        session = date.fromisoformat(row['session'])
        # No fabricated historical availability timestamp. These records are
        # available only at this retrieval; strict historical inputs reject them.
        panel[session] = MarketBar(ticker='NVDA', session=session,
            as_of=datetime.combine(session, time(16), ZoneInfo('America/New_York')),
            available_at=fetched_at, source='Yahoo chart retrospective SECONDARY',
            source_uri=YAHOO_URL, content_hash=source_hash, pit_status=PITStatus.UNVERIFIED,
            mode=Mode.REAL, **{k: row[k] for k in ('open', 'high', 'low', 'close', 'volume')})
    entry_options = sorted(s for s in panel if _open(s) > DECISION_AT)
    if not entry_options:
        raise PilotUnavailable('NO_OBSERVED_ENTRY_SESSION')
    entry = entry_options[0]
    maturity = _six_months(entry)
    exit_options = sorted(s for s in panel if s >= maturity)
    if not exit_options:
        raise PilotUnavailable('NO_OBSERVED_EXIT_SESSION')
    exit_session = exit_options[0]
    result = _holding('NVDA', 1, panel, (), entry=entry, exit=exit_session, cost=0, slip=0)
    return {'status': 'UNVERIFIED', 'eligible_for_validated_comparison': False,
            'metric': 'PRICE_ONLY_CHANGE_EXCLUDES_DIVIDENDS_SPLIT_COVERAGE_UNCERTIFIED',
            'entry_session': str(entry), 'exit_session': str(exit_session),
            'entry_open': result.entry_price, 'exit_open': result.exit_price,
            'price_only_change': result.total_return,
            'calendar': 'OBSERVED_SECONDARY_BARS_NOT_VERIFIED_EXCHANGE_CALENDAR',
            'fees_bps': 0, 'slippage_bps': 0, 'assumption': 'NO_ACTIONS_DIAGNOSTIC_ONLY',
            'calculation': 'finagent.backtest._holding reused without changing production logic'}


def analyze_snapshot_data(sources: dict[str, Any], raw: dict[str, bytes],
                          execution_id: str) -> dict[str, Any]:
    """Pure source-driven calculation shared by acquisition and audited replay."""
    result: dict[str, Any] = {'execution_id': execution_id, 'mode': 'REAL', 'ticker': 'NVDA',
        'status': 'PARTIAL', 'decision_at': DECISION_AT.isoformat(), 'sources': sources,
        'strategy_signal': None, 'exact_ten_status': 'NOT_APPLICABLE_SINGLE_INSTRUMENT_PILOT',
        'llm_calls': 0, 'model_generated_conclusions': [], 'seeking_alpha': 'UNAVAILABLE',
        'limitations': ['Single-instrument evidence experiment; never substitutes for exact-ten production signals.',
                        'No trusted historical analyst consensus; analyst and DCF methods remain UNAVAILABLE.',
                        'SEC archive not fetched: no programmatic request or fabricated identity; this adapter uses issuer release.',
                        'Retrieved bytes prove this execution, not a contemporaneous 2025 captured archive.']}
    try:
        if sources['issuer_release']['status'] != 'FETCHED':
            raise PilotUnavailable('ISSUER_RELEASE_FETCH_UNAVAILABLE')
        facts = parse_fy25_release(raw['issuer_release'].decode('utf-8'))
        result['observed_financial_facts'] = facts
        bound = datetime.fromisoformat(facts['availability_upper_bound'])
        source_hash = sources['issuer_release']['content_sha256']
        financial = FinancialSnapshot(ticker='NVDA', as_of=datetime(2025, 1, 26, tzinfo=UTC),
            available_at=bound, period_end=date(2025, 1, 26), source='NVIDIA issuer FY25 GAAP release',
            source_uri=RELEASE_URL, content_hash=source_hash, pit_status=PITStatus.VERIFIED,
            mode=Mode.REAL, **{k: facts[k] for k in ('revenue', 'revenue_growth', 'earnings_per_share', 'profit_margin')})
        result['financial_snapshot'] = financial.model_dump(mode='json')
        result['financial_pit'] = {'status': 'PASSED' if bound <= DECISION_AT else 'UNAVAILABLE',
            'policy': facts['availability_policy'], 'precision': 'DATE_BOUND_NOT_EXACT_TIMESTAMP',
            'date_bound_is_before_decision': bound <= DECISION_AT}
        assumptions = build_policy_assumptions(facts, source_hash)
        target = target_from_assumptions(assumptions)
        result['unvalidated_policy_calculation'] = {'status': 'PARTIAL',
            'eligible_for_validated_comparison': False, 'policy': 'quant-pe-v1',
            'assumptions': [a.model_dump(mode='json') for a in assumptions], 'target_12m': target,
            'safety_margin': .2, 'entry_threshold': target * .8,
            'warning': 'Arithmetic from real reported facts plus subjective assumptions; not an accepted valuation without market PIT.'}
        gate = pit_gate(DECISION_AT, bound, price_pit_verified=False, actions_complete=False)
        result['pit_validation'] = gate
        result['valuation'] = {'status': 'UNAVAILABLE', 'target_12m': None, 'entry_price': None,
                               'reasons': gate['reasons']}
        result['six_month_total_return_backtest'] = {'status': 'UNAVAILABLE', 'total_return': None,
            'reasons': gate['reasons'], 'signal_id': None, 'strategy_alpha_claim': None}
    except (PilotUnavailable, ValueError) as exc:
        result['financial_pit'] = {'status': 'UNAVAILABLE', 'reason': str(exc)}
        result['valuation'] = {'status': 'UNAVAILABLE', 'target_12m': None, 'reason': str(exc)}
        result['six_month_total_return_backtest'] = {'status': 'UNAVAILABLE', 'total_return': None, 'reason': str(exc)}
    try:
        blob = json.loads(raw['nasdaq_prices'])
        if not isinstance(blob, dict):
            raise PilotUnavailable('PRIMARY_PRICE_RESPONSE_ROOT_MALFORMED')
        data = blob.get('data')
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise PilotUnavailable('PRIMARY_PRICE_RESPONSE_DATA_MALFORMED')
        table = data.get('tradesTable')
        if table is None:
            table = {}
        if not isinstance(table, dict):
            raise PilotUnavailable('PRIMARY_PRICE_RESPONSE_TABLE_MALFORMED')
        rows = table.get('rows')
        if rows is None:
            rows = []
        if not isinstance(rows, list):
            raise PilotUnavailable('PRIMARY_PRICE_RESPONSE_ROWS_MALFORMED')
        result['primary_price_availability'] = {'status': 'PARTIAL' if rows else 'UNAVAILABLE',
            'row_count': len(rows), 'provider_total_records': data.get('totalRecords'),
            'original_availability_proof': None}
    except (ValueError, TypeError):
        result['primary_price_availability'] = {'status': 'UNAVAILABLE', 'row_count': 0}
    try:
        result['observed_corporate_actions'] = parse_nasdaq_dividends(json.loads(raw['nasdaq_dividends']))
    except (ValueError, TypeError) as exc:
        result['observed_corporate_actions'] = {'status': 'UNAVAILABLE', 'coverage_verified': False, 'reason': str(exc)}
    try:
        if sources['secondary_yahoo_prices']['status'] != 'FETCHED':
            raise PilotUnavailable('SECONDARY_PRICE_FETCH_UNAVAILABLE')
        parsed = parse_yahoo_chart(json.loads(raw['secondary_yahoo_prices']))
        result['secondary_price_observations'] = parsed
        result['diagnostic_half_year_price_only'] = diagnostic_price_only(parsed,
            fetched_at=datetime.fromisoformat(sources['secondary_yahoo_prices']['fetched_at']),
            source_hash=sources['secondary_yahoo_prices']['content_sha256'])
    except (ValueError, TypeError) as exc:
        result['diagnostic_half_year_price_only'] = {'status': 'UNAVAILABLE', 'reason': str(exc)}
    if result.get('financial_pit', {}).get('status') != 'PASSED':
        result['status'] = 'BLOCKED'
    return result


def run_pilot(output_dir: Path) -> dict[str, Any]:
    execution_id = datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')
    directory = output_dir / execution_id
    directory.mkdir(parents=True, exist_ok=True)
    sources: dict[str, Any] = {}
    raw: dict[str, bytes] = {}
    for name, (url, source_class) in SOURCE_SPECS.items():
        sources[name], raw[name] = fetch_snapshot(url, directory, name)
        sources[name]['source_class'] = source_class
    result = analyze_snapshot_data(sources, raw, execution_id)
    result['original_sec_filing'] = {'status': 'BLOCKED',
        'contact_user_agent_configured': bool(os.environ.get('SEC_USER_AGENT')),
        'reason': 'SEC_ARCHIVE_NOT_FETCHED; issuer dated earnings release used, not SEC 10-K; no identity invented'}
    result['versions'] = {'adapter': 'real-pilot-v1', 'strategy': 'quant-pe-v1',
                          'accounting': 'frozen-share-cash-v1', 'model': 'NONE_NO_LLM',
                          'python': platform.python_version(), 'platform': platform.platform()}
    try:
        result['versions']['git_head'] = subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=Path(__file__).resolve().parents[2],
            stderr=subprocess.DEVNULL, text=True).strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        result['versions']['git_head'] = None
    result['versions']['source_code_sha256'] = {
        name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
        for name in ('real_pilot.py', 'quant.py', 'backtest.py', 'contracts.py')}
    result['snapshot_id'] = 'real-pilot:' + stable_hash({'decision': result['decision_at'], 'sources': sources})
    path = directory / 'execution.json'
    result['execution_record'] = str(path.resolve())
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / 'latest.json').write_text(json.dumps({'execution_record': str(path.resolve()),
        'snapshot_id': result['snapshot_id'], 'status': result['status']}, indent=2) + '\n')
    return result


def replay_pilot(record_path: Path) -> dict[str, Any]:
    """Verify stored response bytes and recompute without making network calls."""
    record = json.loads(record_path.read_text())
    raw: dict[str, bytes] = {}
    for name, source in record['sources'].items():
        if name not in SOURCE_SPECS or (source.get('source_url'), source.get('source_class')) != SOURCE_SPECS[name]:
            raise PilotUnavailable(f'SOURCE_IDENTITY_MISMATCH:{name}')
        expected_status = 'FETCHED' if source.get('http_status') == 200 else 'UNAVAILABLE'
        if source.get('status') != expected_status:
            raise PilotUnavailable(f'SOURCE_STATUS_MISMATCH:{name}')
        if source['status'] == 'FETCHED' and not source.get('raw_file'):
            raise PilotUnavailable(f'SOURCE_RAW_SNAPSHOT_MISSING:{name}')
        if not source.get('raw_file'):
            raw[name] = b''
            continue
        content = Path(source['raw_file']).read_bytes()
        if hashlib.sha256(content).hexdigest() != source['content_sha256']:
            raise PilotUnavailable(f'SNAPSHOT_HASH_MISMATCH:{name}')
        raw[name] = content
    if set(record['sources']) != set(SOURCE_SPECS):
        raise PilotUnavailable('SOURCE_RECORD_SET_INCOMPLETE')
    expected = analyze_snapshot_data(record['sources'], raw, record['execution_id'])
    for key, value in expected.items():
        if key not in record or record[key] != value:
            raise PilotUnavailable(f'REPLAY_DOMAIN_FIELD_MISMATCH:{key}')
    domain_keys = set(expected)
    metadata_keys = {'original_sec_filing', 'versions', 'snapshot_id', 'execution_record'}
    if set(record) - domain_keys - metadata_keys:
        raise PilotUnavailable('REPLAY_UNEXPECTED_DOMAIN_FIELDS')
    expected_snapshot = 'real-pilot:' + stable_hash({'decision': expected['decision_at'], 'sources': record['sources']})
    if record.get('snapshot_id') != expected_snapshot:
        raise PilotUnavailable('REPLAY_SNAPSHOT_ID_MISMATCH')
    checks = ['SOURCE_IDENTITY_AND_HTTP_STATUS', 'STORED_RESPONSE_HASHES',
              'ALL_DOMAIN_FIELDS_RECOMPUTED_FROM_ORIGINAL_BYTES',
              'FINANCIAL_SCHEMA_AND_DATE_BOUND', 'POLICY_ARITHMETIC',
              'STRICT_UNAVAILABLE_PIT_GATE', 'UNVERIFIED_PRICE_ONLY_DIAGNOSTIC']
    return {'status': 'PASSED', 'original_chain_status': record['status'],
            'execution_id': record['execution_id'], 'record_path': str(record_path.resolve()),
            'checks': checks, 'network_calls': 0,
            'meaning': 'Reproduction PASSED does not upgrade original unavailable/unverified evidence.'}
