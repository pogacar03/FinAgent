"""Reject incomplete worker trace evidence; fixtures are not live service proof."""
import json
import pytest
from scripts.ci.compose_smoke import trace_evidence


def trace_rows():
    attrs = dict(batch_id='run-1', run_id='run-1', ticker='NVDA',
                 snapshot_id='snapshot-1', checkpoint_id='checkpoint-1')
    return [dict(name=stage, trace_id='a'*32, attributes=attrs,
                 llm_metrics=dict(total_tokens=None, llm_latency_ms=None))
            for stage in ('Task Planning', 'Tool Calling', 'State Management',
                          'Evidence Verification', 'Result Expression')]


def test_reject_incomplete_or_split_trace():
    rows = trace_rows()
    with pytest.raises(RuntimeError, match='five-stage'):
        trace_evidence('\n'.join(map(json.dumps, rows[:-1])), 'run-1')
    rows[-1]['trace_id'] = 'b'*32
    with pytest.raises(RuntimeError, match='five-stage'):
        trace_evidence('\n'.join(map(json.dumps, rows)), 'run-1')


def test_reject_false_demo_metrics_and_missing_correlation():
    rows = trace_rows()
    assert trace_evidence('\n'.join(map(json.dumps, rows)), 'run-1')['status'] == 'PASSED'
    rows[0]['llm_metrics']['total_tokens'] = 0
    with pytest.raises(RuntimeError, match='invents'):
        trace_evidence('\n'.join(map(json.dumps, rows)), 'run-1')
    rows = trace_rows()
    for row in rows:
        row['attributes'] = {'run_id': 'run-1'}
    with pytest.raises(RuntimeError, match='correlation'):
        trace_evidence('\n'.join(map(json.dumps, rows)), 'run-1')
