"""Write a reusable row and balance-anchor reconciliation report for a ledger."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from beancount_dedup.interval_reconciliation import IntervalReconciliationService
from beancount_dedup.ledger_store import LedgerStore


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with LedgerStore(args.database.resolve()) as store:
        report = IntervalReconciliationService(store).summarize()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    print(
        json.dumps(
            {
                key: value
                for key, value in report.items()
                if key not in {"accounts", "wallet_accounts"}
            },
            indent=2,
        )
    )
    return 0 if not any(
        report[key]
        for key in (
            "source_break_count",
            "canonical_missing_count",
            "canonical_amount_mismatch_count",
            "wallet_difference_count",
        )
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
