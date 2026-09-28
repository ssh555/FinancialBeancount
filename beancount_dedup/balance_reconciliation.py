"""Statement-balance reconciliation for accounts which expose per-row balances."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .ledger_store import LedgerStore


class BalanceReconciliationService:
    """Verify every consecutive statement balance without guessing missing anchors."""

    def __init__(self, store: LedgerStore):
        self.store = store

    def summarize(self) -> dict[str, Any]:
        rows = self.store.connection.execute(
            """
            SELECT raw_id, source, source_account, booking_date, transaction_time,
                   amount, balance, description, counterparty, source_file, raw_row_number
            FROM raw_transactions
            WHERE balance IS NOT NULL AND TRIM(balance) != ''
            ORDER BY source, source_account, booking_date,
                     CASE WHEN transaction_time IS NULL THEN 1 ELSE 0 END,
                     transaction_time, raw_row_number, raw_id
            """
        ).fetchall()
        accounts: list[dict[str, Any]] = []
        current_key: tuple[str, str] | None = None
        previous = None
        account: dict[str, Any] | None = None
        for row in rows:
            key = (row["source"], row["source_account"])
            if key != current_key:
                account = {
                    "source": key[0],
                    "source_account": key[1],
                    "anchored_rows": 0,
                    "verified_transitions": 0,
                    "breaks": [],
                }
                accounts.append(account)
                current_key = key
                previous = None
            assert account is not None
            account["anchored_rows"] += 1
            if previous is not None:
                expected = Decimal(previous["balance"]) + Decimal(row["amount"])
                actual = Decimal(row["balance"])
                if expected == actual:
                    account["verified_transitions"] += 1
                else:
                    account["breaks"].append(
                        {
                            "previous_raw_id": previous["raw_id"],
                            "raw_id": row["raw_id"],
                            "booking_date": row["booking_date"],
                            "amount": row["amount"],
                            "previous_balance": previous["balance"],
                            "expected_balance": str(expected),
                            "actual_balance": row["balance"],
                            "difference": str(actual - expected),
                            "description": row["description"],
                            "counterparty": row["counterparty"],
                            "source_file": row["source_file"],
                            "raw_row_number": row["raw_row_number"],
                        }
                    )
            previous = row
        return {
            "anchored_account_count": len(accounts),
            "anchored_row_count": sum(item["anchored_rows"] for item in accounts),
            "verified_transition_count": sum(item["verified_transitions"] for item in accounts),
            "break_count": sum(len(item["breaks"]) for item in accounts),
            "accounts": accounts,
        }
