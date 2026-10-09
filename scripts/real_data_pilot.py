#!/usr/bin/env python3
"""Run explicit read-only network evidence pilot; never included in offline tests."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from finagent.real_pilot import replay_pilot, run_pilot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('artifacts/real-pilot'))
    parser.add_argument('--replay', type=Path, help='Offline stored raw-response hash and arithmetic replay')
    args = parser.parse_args()
    if args.replay:
        print(json.dumps(replay_pilot(args.replay), indent=2))
        return 0
    result = run_pilot(args.output)
    print(json.dumps({key: result.get(key) for key in (
        'status', 'execution_record', 'snapshot_id', 'financial_pit', 'valuation',
        'six_month_total_return_backtest', 'diagnostic_half_year_price_only')}, indent=2))
    # Partial evidence is a valid reported outcome, never a green full-chain claim.
    return 0 if result.get('financial_pit', {}).get('status') == 'PASSED' else 2


if __name__ == '__main__':
    raise SystemExit(main())
