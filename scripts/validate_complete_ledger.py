"""Validate complete-ledger integrity and user-visible statistics."""

from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from beancount_dedup.account_balances import AccountBalanceService
from beancount_dedup.ledger_store import LedgerStore
from beancount_dedup.statistics import StatisticsService


def validate_database(database: Path) -> dict[str, Any]:
    with LedgerStore(database) as store:
        transactions = store.list_canonical()
        if not transactions:
            raise ValueError("账本没有唯一交易")
        statistics = StatisticsService(store)
        summary = statistics.summarize()
        account_balance = AccountBalanceService(store).summarize()
        yearly = statistics.timeline("year")
        checks = {
            "gross_expense_matches_years": _sum(yearly, "gross_expense") == summary.gross_expense,
            "ordinary_income_matches_years": _sum(yearly, "ordinary_income")
            == summary.ordinary_income,
            "refunds_match_years": _sum(yearly, "refunds") == summary.refunds,
            "net_cash_flow_formula": summary.net_cash_flow
            == summary.ordinary_income + summary.refunds - summary.gross_expense,
            "account_balance_components": Decimal(account_balance["known_balance"])
            == Decimal(account_balance["cash_total"])
            + Decimal(account_balance["internal_product_total"])
            + Decimal(account_balance.get("snapshot_total", "0")),
        }
        report = {
            "success": all(checks.values()),
            "database": str(database.resolve()),
            "date_from": min(item.booking_date for item in transactions).isoformat(),
            "date_to": max(item.booking_date for item in transactions).isoformat(),
            "canonical_count": len(transactions),
            "raw_count": _count(store, "raw_transactions"),
            "zero_amount_count": sum(item.amount == 0 for item in transactions),
            "empty_merchant_count": sum(not item.merchant.strip() for item in transactions),
            "unclassified_excluded_count": summary.unclassified_excluded_count,
            "pending_review_excluded_count": summary.pending_review_excluded_count,
            "summary": summary.to_dict(),
            "account_balance": account_balance,
            "yearly": yearly,
            "checks": checks,
        }
    if not report["success"]:
        raise RuntimeError("完整账本统计校验失败")
    return report


def _sum(rows: list[dict[str, Any]], key: str) -> Decimal:
    return sum((Decimal(row[key]) for row in rows), Decimal("0"))


def _count(store: LedgerStore, table: str) -> int:
    return int(store.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = validate_database(args.database.resolve())
    except (OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    content = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(content, encoding="utf-8", newline="\n")
    print(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
