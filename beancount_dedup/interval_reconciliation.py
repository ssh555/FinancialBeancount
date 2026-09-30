"""Interval and row-level reconciliation between source balances and canonical ledger."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from itertools import combinations
from typing import Any

from .ledger_store import LedgerStore


class IntervalReconciliationService:
    """Locate the first point where imported or canonical data diverges from an anchor."""

    def __init__(self, store: LedgerStore):
        self.store = store

    def summarize(self, *, include_match_candidates: bool = True) -> dict[str, Any]:
        rows = self.store.connection.execute(
            """
            SELECT raw.raw_id, raw.source, raw.source_account, raw.booking_date,
                   raw.transaction_time, raw.amount, raw.balance, raw.description,
                   raw.source_file, raw.raw_row_number, links.canonical_id,
                   canonical.amount AS canonical_amount,
                   canonical.tx_type, canonical.review_status
            FROM raw_transactions AS raw
            LEFT JOIN source_record_links AS links ON links.raw_id = raw.raw_id
            LEFT JOIN canonical_transactions AS canonical
              ON canonical.canonical_id = links.canonical_id
            WHERE raw.balance IS NOT NULL AND TRIM(raw.balance) != ''
            ORDER BY raw.source, raw.source_account, raw.booking_date,
                     CASE WHEN raw.transaction_time IS NULL THEN 1 ELSE 0 END,
                     raw.transaction_time, raw.raw_row_number, raw.raw_id
            """
        ).fetchall()
        grouped: dict[tuple[str, str], list[Any]] = defaultdict(list)
        for row in rows:
            grouped[(row["source"], row["source_account"])].append(row)

        accounts = []
        for (source, account_name), account_rows in grouped.items():
            intervals = []
            previous = None
            first_failure = None
            for row in account_rows:
                actual = Decimal(row["balance"])
                amount = Decimal(row["amount"])
                source_difference = Decimal("0")
                if previous is not None:
                    source_difference = actual - (Decimal(previous["balance"]) + amount)
                canonical_difference = (
                    None
                    if row["canonical_id"] is None
                    else Decimal(row["canonical_amount"]) - amount
                )
                status = "ok"
                reasons = []
                if source_difference:
                    status = "source_balance_break"
                    reasons.append("source_balance_break")
                if row["canonical_id"] is None:
                    status = "canonical_missing"
                    reasons.append("canonical_missing")
                elif canonical_difference:
                    status = "canonical_amount_mismatch"
                    reasons.append("canonical_amount_mismatch")
                item = {
                    "raw_id": row["raw_id"],
                    "booking_date": row["booking_date"],
                    "transaction_time": row["transaction_time"],
                    "amount": str(amount),
                    "previous_balance": previous["balance"] if previous is not None else None,
                    "actual_balance": str(actual),
                    "source_difference": str(source_difference),
                    "canonical_id": row["canonical_id"],
                    "canonical_amount": row["canonical_amount"],
                    "canonical_difference": (
                        str(canonical_difference) if canonical_difference is not None else None
                    ),
                    "tx_type": row["tx_type"],
                    "review_status": row["review_status"],
                    "description": row["description"],
                    "status": status,
                    "reasons": reasons,
                    "source_file": row["source_file"],
                    "raw_row_number": row["raw_row_number"],
                }
                intervals.append(item)
                if first_failure is None and status != "ok":
                    first_failure = item
                previous = row
            accounts.append(
                {
                    "source": source,
                    "source_account": account_name,
                    "row_count": len(intervals),
                    "opening_balance": intervals[0]["actual_balance"],
                    "opening_before_first": str(
                        Decimal(intervals[0]["actual_balance"]) - Decimal(intervals[0]["amount"])
                    ),
                    "closing_balance": intervals[-1]["actual_balance"],
                    "source_break_count": sum(
                        "source_balance_break" in item["reasons"] for item in intervals
                    ),
                    "canonical_missing_count": sum(
                        item["canonical_id"] is None for item in intervals
                    ),
                    "canonical_amount_mismatch_count": sum(
                        "canonical_amount_mismatch" in item["reasons"] for item in intervals
                    ),
                    "first_failure": first_failure,
                    "intervals": intervals,
                }
            )
        wallet_accounts = self._summarize_wallet_accounts()
        asset_closure = self._summarize_asset_closure(accounts, wallet_accounts)
        aggregate_candidates = (
            self._summarize_aggregate_candidates() if include_match_candidates else []
        )
        return {
            "account_count": len(accounts),
            "source_break_count": sum(item["source_break_count"] for item in accounts),
            "canonical_missing_count": sum(item["canonical_missing_count"] for item in accounts),
            "canonical_amount_mismatch_count": sum(
                item["canonical_amount_mismatch_count"] for item in accounts
            ),
            "accounts": accounts,
            "wallet_accounts": wallet_accounts,
            "wallet_difference_count": sum(
                Decimal(item["difference"]) != 0 for item in wallet_accounts
            ),
            "asset_closure": asset_closure,
            "aggregate_match_candidates": aggregate_candidates,
        }

    def _summarize_aggregate_candidates(self) -> list[dict[str, Any]]:
        """Find auditable N-wallet-to-one-bank fallback candidates.

        Exact one-to-one matching is intentionally performed elsewhere first.
        This diagnostic only considers still-separate, single-source canonical
        entries on the same booking date.  It never mutates or confirms them.
        A candidate is marked unique only when exactly one 2-3 row combination
        reaches the bank amount; confirmation still requires statement review.
        """

        rows = self.store.connection.execute(
            """
            WITH source_counts AS (
                SELECT canonical_id, COUNT(*) AS source_count
                FROM source_record_links GROUP BY canonical_id
            )
            SELECT raw.raw_id, raw.source, raw.source_account, raw.booking_date,
                   raw.amount, raw.direction, raw.merchant, raw.description,
                   raw.payment_method, raw.bank_card_suffix, raw.balance,
                   links.canonical_id
            FROM raw_transactions AS raw
            JOIN source_record_links AS links ON links.raw_id = raw.raw_id
            JOIN source_counts AS counts ON counts.canonical_id = links.canonical_id
            WHERE counts.source_count = 1
              AND raw.source IN ('bank', 'wechat', 'alipay')
            ORDER BY raw.booking_date, raw.raw_id
            """
        ).fetchall()
        banks = [row for row in rows if row["source"] == "bank" and row["balance"] is not None]
        wallets = [row for row in rows if row["source"] in {"wechat", "alipay"}]
        result = []
        for bank in banks:
            bank_amount = Decimal(bank["amount"])
            eligible = [
                row
                for row in wallets
                if row["booking_date"] == bank["booking_date"]
                and Decimal(row["amount"]) * bank_amount > 0
                and self._wallet_funding_account(row) == bank["source_account"]
            ]
            solutions = []
            for size in (2, 3):
                for group in combinations(eligible, size):
                    if sum((Decimal(row["amount"]) for row in group), Decimal("0")) == bank_amount:
                        solutions.append(group)
            if not solutions:
                continue
            result.append(
                {
                    "bank_raw_id": bank["raw_id"],
                    "bank_canonical_id": bank["canonical_id"],
                    "booking_date": bank["booking_date"],
                    "source_account": bank["source_account"],
                    "bank_amount": str(bank_amount),
                    "balance_anchor": bank["balance"],
                    "solution_count": len(solutions),
                    "is_unique": len(solutions) == 1,
                    "solutions": [
                        [
                            {
                                "raw_id": row["raw_id"],
                                "canonical_id": row["canonical_id"],
                                "source": row["source"],
                                "amount": row["amount"],
                                "merchant": row["merchant"],
                                "description": row["description"],
                            }
                            for row in group
                        ]
                        for group in solutions
                    ],
                    "match_phase": "aggregate_fuzzy_fallback",
                    "requires_review": True,
                }
            )
        return result

    @staticmethod
    def _wallet_funding_account(row: Any) -> str | None:
        value = " ".join((row["payment_method"] or "", row["description"] or "")).lower()
        aliases = {
            "招商银行": ("招商银行", "招商", "5066", "cmb"),
            "工商银行": ("工商银行", "工行", "4000", "icbc"),
            "重庆农村商业银行": (
                "重庆农村商业银行",
                "重庆农商行",
                "农村商业银行",
                "农商行",
                "6235",
                "cqrcb",
            ),
        }
        return next(
            (
                account
                for account, names in aliases.items()
                if any(name.lower() in value for name in names)
            ),
            None,
        )

    def _summarize_asset_closure(
        self, accounts: list[dict[str, Any]], wallet_accounts: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Reconcile closing assets without confusing transfers with income."""
        bank_closing = sum((Decimal(item["closing_balance"]) for item in accounts), Decimal("0"))
        wallet_closing = sum(
            (Decimal(item["projected_balance"]) for item in wallet_accounts), Decimal("0")
        )
        product_rows = self.store.connection.execute(
            """
            SELECT source_account, balance, as_of
            FROM account_balance_snapshots
            WHERE source = 'bank'
            ORDER BY source_account, as_of DESC, created_at DESC
            """
        ).fetchall()
        latest_products: dict[str, Any] = {}
        for row in product_rows:
            latest_products.setdefault(row["source_account"], row)
        product_total = sum(
            (Decimal(row["balance"]) for row in latest_products.values()), Decimal("0")
        )
        pending = Decimal("0")
        for account in accounts:
            latest_date = account["intervals"][-1]["booking_date"]
            rows = self.store.connection.execute(
                """
                SELECT DISTINCT canonical.canonical_id, canonical.amount
                FROM canonical_transactions AS canonical
                JOIN source_record_links AS links
                  ON links.canonical_id = canonical.canonical_id
                JOIN raw_transactions AS raw ON raw.raw_id = links.raw_id
                WHERE canonical.booking_date > ?
                  AND canonical.funding_account LIKE '%' || ? || '%'
                  AND raw.source IN ('wechat', 'alipay')
                  AND NOT EXISTS (
                      SELECT 1 FROM source_record_links AS bank_links
                      JOIN raw_transactions AS bank_raw ON bank_raw.raw_id = bank_links.raw_id
                      WHERE bank_links.canonical_id = canonical.canonical_id
                        AND bank_raw.source = 'bank'
                  )
                """,
                (latest_date, account["source_account"]),
            ).fetchall()
            pending += sum((Decimal(row["amount"]) for row in rows), Decimal("0"))
        computed = bank_closing + wallet_closing + product_total + pending
        known = (
            bank_closing
            + product_total
            + pending
            + sum(
                (
                    Decimal(item["actual_balance"])
                    for item in wallet_accounts
                    if item["actual_balance"] is not None
                ),
                Decimal("0"),
            )
        )
        return {
            "bank_statement_closing": str(bank_closing),
            "wallet_projected_closing": str(wallet_closing),
            "internal_product_snapshots": str(product_total),
            "post_statement_pending": str(pending),
            "computed_total_assets": str(computed),
            "known_total_assets": str(known),
            "difference": str(known - computed),
            "internal_products": [
                {
                    "source_account": name,
                    "balance": row["balance"],
                    "as_of": row["as_of"],
                }
                for name, row in latest_products.items()
            ],
        }

    def _summarize_wallet_accounts(self) -> list[dict[str, Any]]:
        """Project wallet balances and compare them with verified snapshots."""
        result = []
        for source, snapshot_account in (
            ("wechat", "微信零钱"),
            ("alipay", "支付宝余额"),
        ):
            rows = self.store.connection.execute(
                """
                SELECT raw_id, booking_date, transaction_time, amount, direction,
                       merchant, description, payment_method, status
                FROM raw_transactions WHERE source = ?
                ORDER BY booking_date, transaction_time, raw_row_number, raw_id
                """,
                (source,),
            ).fetchall()
            projected = Decimal("0")
            intervals = []
            for row in rows:
                effect, reason, evidence = self._wallet_effect(source, row)
                if effect is None:
                    continue
                projected += effect
                intervals.append(
                    {
                        "raw_id": row["raw_id"],
                        "booking_date": row["booking_date"],
                        "transaction_time": row["transaction_time"],
                        "source_amount": row["amount"],
                        "wallet_effect": str(effect),
                        "projected_balance": str(projected),
                        "reason": reason,
                        "evidence": evidence,
                        "merchant": row["merchant"],
                        "description": row["description"],
                        "payment_method": row["payment_method"],
                    }
                )
            snapshot = self.store.connection.execute(
                """
                SELECT balance, as_of FROM account_balance_snapshots
                WHERE source = ? AND source_account = ?
                ORDER BY as_of DESC, created_at DESC LIMIT 1
                """,
                (source, snapshot_account),
            ).fetchone()
            actual = Decimal(snapshot["balance"]) if snapshot else None
            difference = actual - projected if actual is not None else Decimal("0")
            result.append(
                {
                    "source": source,
                    "source_account": snapshot_account,
                    "projected_balance": str(projected),
                    "actual_balance": str(actual) if actual is not None else None,
                    "difference": str(difference),
                    "as_of": snapshot["as_of"] if snapshot else None,
                    "row_count": len(intervals),
                    "first_divergence_note": (
                        "需要更早的阶段余额锚点才能定位首个偏差" if difference else None
                    ),
                    "intervals": intervals,
                }
            )
        return result

    def _wallet_effect(  # noqa: PLR0911
        self, source: str, row: Any
    ) -> tuple[Decimal | None, str, dict[str, Any]]:
        amount = Decimal(row["amount"])
        method = row["payment_method"] or ""
        text = " ".join((row["merchant"] or "", row["description"] or "", row["status"] or ""))
        if source == "wechat":
            if "充值完成" in text:
                return abs(amount), "wallet_recharge", {}
            if "提现已到账" in text:
                return -abs(amount), "wallet_withdrawal", {}
            if "零钱" in method:
                return amount, "wallet_funded", {}
            if row["direction"] == "income" and method in {"", "/"}:
                return amount, "wallet_income", {}
            return None, "not_wallet_funded", {}

        if row["status"] == "交易关闭":
            return None, "closed", {}
        if row["direction"] == "income" and not method:
            return amount, "wallet_income", {}
        if "余额" not in method:
            return None, "not_wallet_funded", {}
        if "银行" not in method and "卡(" not in method:
            if row["direction"] == "neutral" and "提现" in text:
                return -abs(amount), "wallet_withdrawal", {}
            return amount, "wallet_funded", {}

        bank_part = self._mixed_alipay_bank_part(row)
        if bank_part is None:
            return amount, "mixed_funding_unresolved", {"warning": "bank_part_not_found"}
        wallet_part = max(abs(amount) - Decimal(bank_part["amount"]), Decimal("0"))
        effect = -wallet_part if amount < 0 else wallet_part
        return effect, "mixed_funding_split", bank_part

    def _mixed_alipay_bank_part(self, row: Any) -> dict[str, Any] | None:
        """Resolve the bank-funded part of a mixed Alipay payment conservatively.

        This is deliberately a fallback after ordinary full-amount matching.
        A bank row is usable only when it carries a running-balance anchor, is
        not already linked to another wallet observation, and is the unique
        best candidate.  Returning ``None`` is safer than silently consuming a
        bank debit twice.
        """
        suffixes = {
            "5066": "招商银行",
            "4000": "工商银行",
            "6235": "重庆农村商业银行",
        }
        account = next(
            (name for suffix, name in suffixes.items() if suffix in row["payment_method"]),
            None,
        )
        if account is None:
            return None
        day = date.fromisoformat(row["booking_date"])
        candidates = self.store.connection.execute(
            """
            SELECT bank.raw_id, bank.booking_date, bank.amount, bank.merchant,
                   bank.balance
            FROM raw_transactions AS bank
            WHERE bank.source = 'bank'
              AND bank.source_account = ?
              AND CAST(bank.amount AS REAL) < 0
              AND bank.balance IS NOT NULL
              AND TRIM(bank.balance) != ''
              AND NOT EXISTS (
                  SELECT 1
                  FROM source_record_links AS bank_link
                  JOIN source_record_links AS other_link
                    ON other_link.canonical_id = bank_link.canonical_id
                   AND other_link.raw_id != bank_link.raw_id
                  JOIN raw_transactions AS other_raw
                    ON other_raw.raw_id = other_link.raw_id
                  WHERE bank_link.raw_id = bank.raw_id
                    AND other_raw.source IN ('wechat', 'alipay')
              )
            """,
            (account,),
        ).fetchall()
        viable = []
        for candidate in candidates:
            distance = abs((date.fromisoformat(candidate["booking_date"]) - day).days)
            bank_amount = abs(Decimal(candidate["amount"]))
            if distance > 3 or bank_amount > abs(Decimal(row["amount"])):
                continue
            exact = candidate["merchant"] == row["merchant"]
            generic = "支付宝" in (candidate["merchant"] or "")
            if exact or generic:
                viable.append((not exact, distance, -bank_amount, candidate))
        if not viable:
            return None
        viable.sort(key=lambda item: item[:3])
        best_rank = viable[0][:3]
        best = [item for item in viable if item[:3] == best_rank]
        if len(best) != 1:
            return None
        _, distance, _, chosen = best[0]
        return {
            "raw_id": chosen["raw_id"],
            "booking_date": chosen["booking_date"],
            "amount": str(abs(Decimal(chosen["amount"]))),
            "day_distance": distance,
            "balance_anchor": chosen["balance"],
            "match_phase": "fuzzy_split_fallback",
        }
