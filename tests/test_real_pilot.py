"""Offline synthetic parser fixtures; no fixture claims to be a market record."""
from datetime import date, datetime, timezone

import pytest

from finagent.real_pilot import (
    PilotUnavailable, conservative_available_bound, parse_fy25_release,
    parse_nasdaq_dividends, parse_yahoo_chart, pit_gate, build_policy_assumptions,
)
from finagent.quant import target_from_assumptions

FIXTURE = '''<div class="article-date">February 26, 2025</div>
<p>fiscal year ended January 26, 2025.</p><p>Fiscal 2025 Summary</p>
<table><tr><td>GAAP ($ in millions, except earnings per share)</td></tr>
<tr><td></td><td>FY25</td><td>FY24</td><td>Y/Y</td></tr>
<tr><td>Revenue</td><td>$100</td><td>$50</td><td>Up 100%</td></tr>
<tr><td>Net income</td><td>$20</td><td>$10</td><td>Up 100%</td></tr>
<tr><td>Diluted earnings per share*</td><td>$2.50</td><td>$1.25</td></tr></table>
<table><tr><td>Non-GAAP</td></tr><tr><td>FY25</td><td>FY24</td></tr>
<tr><td>Revenue</td><td>$999</td></tr></table>'''


def test_release_parses_actual_gaap_cells_and_unit_scaling():
    facts = parse_fy25_release(FIXTURE)
    assert facts['revenue'] == 100_000_000
    assert facts['earnings_per_share'] == 2.5
    assert facts['revenue_growth'] == 1
    assert facts['profit_margin'] == .2
    assert facts['publication_precision'] == 'DATE_ONLY'


def test_release_missing_period_or_eps_is_unavailable():
    for mutated in (FIXTURE.replace('January 26, 2025', ''),
                    FIXTURE.replace('Diluted earnings per share*', 'forecast EPS')):
        with pytest.raises(PilotUnavailable):
            parse_fy25_release(mutated)


def test_release_wrong_year_not_patched_from_memory():
    with pytest.raises(PilotUnavailable):
        parse_fy25_release(FIXTURE.replace('FY25', 'FY26'))


def test_date_only_upper_bound_not_fabricated_release_time():
    assert conservative_available_bound(date(2025, 2, 26)) == datetime(2025, 2, 27, 8, tzinfo=timezone.utc)


def test_policy_is_assumption_and_reuses_quant_arithmetic():
    assumptions = build_policy_assumptions(parse_fy25_release(FIXTURE), 'source-sha')
    assert all(a.kind == 'ASSUMPTION' for a in assumptions)
    assert target_from_assumptions(assumptions) == 65
    assert 'not analyst consensus' in assumptions[1].rationale


def test_pit_gate_never_upgrades_fetched_today_prices_or_incomplete_actions():
    out = pit_gate(datetime(2025, 3, 1, tzinfo=timezone.utc),
                   conservative_available_bound(date(2025, 2, 26)),
                   price_pit_verified=False, actions_complete=False)
    assert out['status'] == 'UNAVAILABLE'
    assert out['reasons'] == ['HISTORICAL_PRICE_PIT_UNVERIFIED', 'CORPORATE_ACTION_COVERAGE_UNVERIFIED']


def test_future_release_excluded_even_with_verified_other_inputs():
    out = pit_gate(datetime(2025, 2, 26, tzinfo=timezone.utc),
                   conservative_available_bound(date(2025, 2, 26)),
                   price_pit_verified=True, actions_complete=True)
    assert out['reasons'] == ['FINANCIAL_RELEASE_UNAVAILABLE_AT_DECISION']


def test_yahoo_parser_rejects_wrong_symbol_and_preserves_raw_open():
    blob = {'chart': {'error': None, 'result': [{'meta': {'symbol': 'NVDA', 'currency': 'USD'},
      'timestamp': [1741012200], 'indicators': {'quote': [{'open': [100.125], 'high': [102],
        'low': [99], 'close': [101], 'volume': [123]}], 'adjclose': [{'adjclose': [1]}]},
      'events': {'dividends': {'x': {'date': 1741786200, 'amount': .01}}}}]}}
    parsed = parse_yahoo_chart(blob)
    assert parsed['bars'][0]['open'] == 100.125
    assert 'adjclose' not in parsed['bars'][0]
    assert parsed['pit_status'] == 'PIT_UNVERIFIED'
    blob['chart']['result'][0]['meta']['symbol'] = 'SPY'
    with pytest.raises(PilotUnavailable):
        parse_yahoo_chart(blob)


def test_yahoo_missing_ohlc_is_unavailable_not_forward_filled():
    blob = {'chart': {'result': [{'meta': {'symbol': 'NVDA', 'currency': 'USD'},
         'timestamp': [1741012200], 'indicators': {'quote': [{'open': [None]}]}}]}}
    with pytest.raises(PilotUnavailable):
        parse_yahoo_chart(blob)


def test_dividends_use_ex_date_not_payment_and_do_not_claim_completeness():
    blob = {'data': {'dividends': {'rows': [{'exOrEffDate': '03/12/2025', 'type': 'Cash',
      'amount': '$0.01', 'declarationDate': '02/26/2025', 'paymentDate': '04/02/2025',
      'recordDate': '03/12/2025', 'currency': 'USD'}]}}}
    parsed = parse_nasdaq_dividends(blob)
    assert parsed['events'][0]['session'] == '2025-03-12'
    assert parsed['coverage_verified'] is False


def test_replay_rejects_changed_raw_snapshot(tmp_path):
    import hashlib
    import json
    from finagent.real_pilot import replay_pilot
    raw = tmp_path / 'source.raw'
    raw.write_text('original')
    record = tmp_path / 'execution.json'
    record.write_text(json.dumps({'sources': {'issuer_release': {'raw_file': str(raw),
        'content_sha256': hashlib.sha256(b'original').hexdigest(),
        'source_url': 'https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-fourth-quarter-and-fiscal-2025',
        'source_class': 'PRIMARY_ISSUER', 'http_status': 200, 'status': 'FETCHED'}}, 'execution_id': 'fixture'}))
    raw.write_text('tampered')
    with pytest.raises(PilotUnavailable, match='SNAPSHOT_HASH_MISMATCH'):
        replay_pilot(record)


def test_run_network_failure_returns_unavailable_not_policy_price(tmp_path, monkeypatch):
    from finagent import real_pilot
    monkeypatch.setattr(real_pilot, 'fetch_snapshot', lambda url, directory, label:
        ({'source_url': url, 'status': 'UNAVAILABLE', 'http_status': 403,
          'snapshot_id': None}, b''))
    result = real_pilot.run_pilot(tmp_path)
    assert result['valuation']['target_12m'] is None
    assert result['six_month_total_return_backtest']['total_return'] is None
    assert 'unvalidated_policy_calculation' not in result
    assert result['status'] == 'BLOCKED'
    assert result['strategy_signal'] is None


def test_publication_date_is_article_field_not_unrelated_page_text():
    with pytest.raises(PilotUnavailable):
        parse_fy25_release(FIXTURE.replace('class="article-date"', 'class="unrelated"'))


def test_replay_rejects_changed_source_class_or_url(tmp_path):
    import json
    from finagent.real_pilot import replay_pilot
    record = tmp_path / 'execution.json'
    record.write_text(json.dumps({'sources': {'issuer_release': {
        'source_url': 'https://untrusted.example.invalid/nvda', 'source_class': 'PRIMARY_ISSUER',
        'status': 'UNAVAILABLE', 'http_status': 403}}, 'execution_id': 'fixture'}))
    with pytest.raises(PilotUnavailable, match='SOURCE_IDENTITY_MISMATCH'):
        replay_pilot(record)


def _synthetic_record(tmp_path, monkeypatch, malformed_other=False):
    import hashlib
    import json
    from finagent import real_pilot
    def fake_fetch(url, directory, label):
        content = FIXTURE.encode() if label == 'issuer_release' else (b'[]' if malformed_other else b'{}')
        digest = hashlib.sha256(content).hexdigest()
        raw = directory / (label + '.raw')
        raw.write_bytes(content)
        return ({'source_url': url, 'http_status': 200, 'status': 'FETCHED',
                 'fetched_at': '2026-10-09T00:00:00+00:00', 'content_sha256': digest,
                 'snapshot_id': label + ':' + digest, 'raw_file': str(raw)}, content)
    monkeypatch.setattr(real_pilot, 'fetch_snapshot', fake_fetch)
    result = real_pilot.run_pilot(tmp_path)
    return result, json


@pytest.mark.parametrize('mutation', ['missing_facts_and_forged_returns', 'financial_snapshot',
                                      'financial_pit', 'top_status', 'diagnostic_upgrade'])
def test_replay_recomputes_all_domain_fields_from_raw_not_optional_result_fields(tmp_path, monkeypatch, mutation):
    from finagent.real_pilot import replay_pilot
    from pathlib import Path
    result, json = _synthetic_record(tmp_path, monkeypatch)
    assert replay_pilot(Path(result['execution_record']))['status'] == 'PASSED'
    if mutation == 'missing_facts_and_forged_returns':
        result.pop('observed_financial_facts')
        result['valuation'] = {'status': 'PASSED', 'target_12m': 9999}
        result['six_month_total_return_backtest'] = {'status': 'PASSED', 'total_return': 42}
    elif mutation == 'financial_snapshot':
        result['financial_snapshot']['revenue'] = 1
    elif mutation == 'financial_pit':
        result['financial_pit']['status'] = 'PIT_UNVERIFIED'
    elif mutation == 'top_status':
        result['status'] = 'PASSED'
    else:
        result['diagnostic_half_year_price_only'] = {'status': 'PASSED', 'total_return': 42}
    record = Path(result['execution_record'])
    record.write_text(json.dumps(result))
    with pytest.raises(PilotUnavailable, match='REPLAY'):
        replay_pilot(record)


def test_malformed_provider_roots_do_not_abort_valid_other_evidence(tmp_path, monkeypatch):
    result, _ = _synthetic_record(tmp_path, monkeypatch, malformed_other=True)
    assert result['status'] == 'PARTIAL'
    assert result['financial_pit']['status'] == 'PASSED'
    assert result['primary_price_availability']['status'] == 'UNAVAILABLE'
    assert result['diagnostic_half_year_price_only']['status'] == 'UNAVAILABLE'
