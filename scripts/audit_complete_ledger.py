"""Create a read-only data-quality audit for a complete ledger."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Any

from beancount_dedup.account_balances import AccountBalanceService
from beancount_dedup.ledger_store import LedgerStore


def audit_database(database: Path) -> dict[str, Any]:
    with LedgerStore(database) as store:
        connection = store.connection
        collisions = _bank_balance_collisions(store)
        candidate_rows = connection.execute(
            "SELECT confidence, is_ambiguous, status FROM match_candidates"
        ).fetchall()
        candidate_distribution = Counter(
            (row["status"], row["confidence"], bool(row["is_ambiguous"]))
            for row in candidate_rows
        )
        investment_rows = connection.execute(
            """
            SELECT source_account, description, counterparty, amount
            FROM raw_transactions
            WHERE source = 'bank' AND (
                description LIKE '%朝朝宝%' OR description LIKE '%天天盈%'
                OR description LIKE '%基金%' OR description LIKE '%理财%'
                OR counterparty LIKE '%基金销售%'
            )
            """
        ).fetchall()
        investment_groups: dict[tuple[str, str, str], dict[str, Any]] = {}
        for row in investment_rows:
            description = row["description"] or "未注明类型"
            counterparty = row["counterparty"] or ""
            scope = _investment_scope(description, counterparty)
            key = (row["source_account"], description, scope)
            group = investment_groups.setdefault(
                key,
                {
                    "source_account": key[0],
                    "description": key[1],
                    "scope": key[2],
                    "count": 0,
                    "net": Decimal("0"),
                },
            )
            group["count"] += 1
            group["net"] += Decimal(row["amount"])

        report = {
            "success": True,
            "database": str(database.resolve()),
            "read_only": True,
            "raw_count": _count(store, "raw_transactions"),
            "canonical_count": _count(store, "canonical_transactions"),
            "account_balance": AccountBalanceService(store).summarize(),
            "match_candidates": {
                "pending_count": sum(row["status"] == "pending" for row in candidate_rows),
                "high_confidence_unambiguous_count": sum(
                    row["status"] == "pending"
                    and not row["is_ambiguous"]
                    and Decimal(row["confidence"]) >= Decimal("0.80")
                    for row in candidate_rows
                ),
                "distribution": [
                    {
                        "status": status,
                        "confidence": confidence,
                        "ambiguous": ambiguous,
                        "count": count,
                    }
                    for (status, confidence, ambiguous), count in sorted(
                        candidate_distribution.items(),
                        key=lambda item: (item[0][0], -Decimal(item[0][1]), item[0][2]),
                    )
                ],
                "policy": "即使高置信度也只提高人工审核优先级，不自动归并。",
            },
            "bank_balance_collisions": {
                "group_count": len(collisions),
                "high_priority_count": sum(item["priority"] == "high" for item in collisions),
                "groups": collisions,
                "policy": "余额碰撞只是疑似重复；朝朝宝自动赎回等连续流水可能合法，不自动删除。",
            },
            "investment_and_internal_product_flows": [
                {**group, "net": str(group["net"])}
                for group in sorted(
                    investment_groups.values(),
                    key=lambda item: (item["source_account"], item["description"]),
                )
            ],
        }
    return report


def _bank_balance_collisions(store: LedgerStore) -> list[dict[str, Any]]:
    groups = store.connection.execute(
        """
        SELECT source_account, booking_date, amount, balance, COUNT(*) AS row_count
        FROM raw_transactions
        WHERE source = 'bank' AND balance IS NOT NULL AND balance != ''
        GROUP BY source_account, booking_date, amount, balance
        HAVING COUNT(*) > 1
        ORDER BY booking_date, source_account, CAST(amount AS REAL)
        """
    ).fetchall()
    result = []
    for group in groups:
        rows = store.connection.execute(
            """
            SELECT raw_id, description, counterparty, source_file, raw_row_number
            FROM raw_transactions
            WHERE source = 'bank' AND source_account = ? AND booking_date = ?
              AND amount = ? AND balance = ?
            ORDER BY source_file, raw_row_number, raw_id
            """,
            (group["source_account"], group["booking_date"], group["amount"], group["balance"]),
        ).fetchall()
        counterparties = {_normalized(row["counterparty"]) for row in rows if row["counterparty"]}
        descriptions = {_normalized(row["description"]) for row in rows if row["description"]}
        same_counterparty = len(counterparties) == 1 and len(counterparties) > 0
        same_description = len(descriptions) == 1 and len(descriptions) > 0
        interleaved_reversal = _has_interleaved_reversal(store, rows, Decimal(group["amount"]))
        priority = (
            "high"
            if not interleaved_reversal
            and (
                (same_counterparty and same_description)
                or (same_description and abs(Decimal(group["amount"])) >= Decimal("1000"))
            )
            else "review"
        )
        result.append(
            {
                "source_account": group["source_account"],
                "booking_date": group["booking_date"],
                "amount": group["amount"],
                "balance": group["balance"],
                "row_count": group["row_count"],
                "priority": priority,
                "same_description": same_description,
                "same_counterparty": same_counterparty,
                "interleaved_reversal": interleaved_reversal,
                "rows": [dict(row) for row in rows],
            }
        )
    return result


def _normalized(value: str) -> str:
    return "".join(value.lower().split())


def _has_interleaved_reversal(
    store: LedgerStore, rows: list[Any], amount: Decimal
) -> bool:
    for left, right in pairwise(rows):
        if left["source_file"] != right["source_file"]:
            continue
        between = store.connection.execute(
            """
            SELECT 1 FROM raw_transactions
            WHERE source_file = ? AND raw_row_number > ? AND raw_row_number < ?
              AND CAST(amount AS NUMERIC) = ?
            LIMIT 1
            """,
            (
                left["source_file"],
                left["raw_row_number"],
                right["raw_row_number"],
                str(-amount),
            ),
        ).fetchone()
        if between:
            return True
    return False


def _investment_scope(description: str, counterparty: str) -> str:
    if "朝朝宝" in description or "天天盈" in description:
        return "bank_internal"
    if description == "基金购买" and "基金销售" not in counterparty:
        return "bank_internal"
    return "external_or_review"


def _count(store: LedgerStore, table: str) -> int:
    return int(store.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit_database(args.database.resolve())
    content = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(content, encoding="utf-8", newline="\n")
    print(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
