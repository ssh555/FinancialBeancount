"""Canonical-only financial statistics with explicit refund treatment."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from .ledger_store import LedgerStore
from .models import TransactionType


@dataclass(frozen=True)
class CategoryStatistics:
    category: str
    gross_expense: Decimal
    refunds: Decimal

    @property
    def net_expense(self) -> Decimal:
        return self.gross_expense - self.refunds

    def to_dict(self) -> dict[str, str]:
        return {
            "category": self.category,
            "gross_expense": str(self.gross_expense),
            "refunds": str(self.refunds),
            "net_expense": str(self.net_expense),
        }


@dataclass(frozen=True)
class StatisticsReport:
    date_from: date | None
    date_to: date | None
    gross_expense: Decimal
    refunds: Decimal
    ordinary_income: Decimal
    expense_count: int
    income_count: int
    refund_count: int
    excluded_non_consumption_count: int
    unclassified_excluded_count: int
    pending_review_excluded_count: int
    categories: tuple[CategoryStatistics, ...]
    reconciled_asset_change: Decimal | None = None

    @property
    def net_expense(self) -> Decimal:
        return self.gross_expense - self.refunds

    @property
    def net_cash_flow(self) -> Decimal:
        if self.reconciled_asset_change is not None:
            return self.reconciled_asset_change
        return self.transaction_net_cash_flow

    @property
    def transaction_net_cash_flow(self) -> Decimal:
        return self.ordinary_income + self.refunds - self.gross_expense

    def to_dict(self) -> dict[str, Any]:
        return {
            "date_from": self.date_from.isoformat() if self.date_from else None,
            "date_to": self.date_to.isoformat() if self.date_to else None,
            "gross_expense": str(self.gross_expense),
            "refunds": str(self.refunds),
            "net_expense": str(self.net_expense),
            "ordinary_income": str(self.ordinary_income),
            "net_cash_flow": str(self.net_cash_flow),
            "transaction_net_cash_flow": str(self.transaction_net_cash_flow),
            "asset_reconciliation_adjustment": str(
                self.net_cash_flow - self.transaction_net_cash_flow
            ),
            "net_cash_flow_basis": (
                "verified_asset_chain"
                if self.reconciled_asset_change is not None
                else "classified_transactions"
            ),
            "expense_count": self.expense_count,
            "income_count": self.income_count,
            "refund_count": self.refund_count,
            "excluded_non_consumption_count": self.excluded_non_consumption_count,
            "unclassified_excluded_count": self.unclassified_excluded_count,
            "pending_review_excluded_count": self.pending_review_excluded_count,
            "categories": [item.to_dict() for item in self.categories],
        }


class StatisticsService:
    """Calculate reports from unique economic transactions, never raw observations."""

    def __init__(self, store: LedgerStore):
        self.store = store
        self._asset_change_cache: tuple[tuple[int, int], Decimal | None] | None = None

    def summarize(
        self,
        date_from: date | None = None,
        date_to: date | None = None,
        source_filters: list[tuple[str, str | None]] | None = None,
    ) -> StatisticsReport:
        if date_from and date_to and date_from > date_to:
            raise ValueError("date_from must not be after date_to")
        transactions = [
            item
            for item in self.store.list_canonical(source_filters)
            if _in_range(item.booking_date, date_from, date_to)
        ]
        pending_ids = {
            row["canonical_id"]
            for row in self.store.connection.execute(
                "SELECT canonical_id FROM classification_candidates WHERE status = 'pending'"
            ).fetchall()
        }
        pending_ids.update(
            row["from_canonical_id"]
            for row in self.store.connection.execute(
                """
                SELECT from_canonical_id FROM transaction_relationships
                WHERE relationship_type = 'refund' AND status = 'pending'
                """
            ).fetchall()
        )
        pending = [item for item in transactions if item.canonical_id in pending_ids]
        reportable = [item for item in transactions if item.canonical_id not in pending_ids]
        expenses = [item for item in reportable if item.tx_type == TransactionType.EXPENSE]
        incomes = [item for item in reportable if item.tx_type == TransactionType.INCOME]
        excluded_types = {
            TransactionType.TRANSFER,
            TransactionType.INVESTMENT,
            TransactionType.PREAUTHORIZATION,
        }
        excluded = [item for item in reportable if item.tx_type in excluded_types]
        unclassified = [item for item in reportable if item.tx_type == TransactionType.UNKNOWN]

        refund_rows = self.store.connection.execute(
            """
            SELECT relationships.amount, original.category, refund.canonical_id
            FROM transaction_relationships AS relationships
            JOIN canonical_transactions AS refund
              ON refund.canonical_id = relationships.from_canonical_id
            JOIN canonical_transactions AS original
              ON original.canonical_id = relationships.to_canonical_id
            WHERE relationships.relationship_type = 'refund'
              AND relationships.status = 'confirmed'
              AND (? IS NULL OR refund.booking_date >= ?)
              AND (? IS NULL OR refund.booking_date <= ?)
            """,
            (
                date_from.isoformat() if date_from else None,
                date_from.isoformat() if date_from else None,
                date_to.isoformat() if date_to else None,
                date_to.isoformat() if date_to else None,
            ),
        ).fetchall()

        selected_ids = {item.canonical_id for item in transactions}
        refund_rows = [row for row in refund_rows if row["canonical_id"] in selected_ids]
        confirmed_refund_ids = {row["canonical_id"] for row in refund_rows}
        refund_rows.extend(
            {
                "amount": str(abs(item.amount)),
                "category": item.category,
                "canonical_id": item.canonical_id,
            }
            for item in reportable
            if item.tx_type == TransactionType.REFUND
            and item.canonical_id not in confirmed_refund_ids
        )
        category_expenses: dict[str, Decimal] = {}
        for item in expenses:
            category = item.category or "未分类"
            category_expenses[category] = category_expenses.get(category, Decimal("0")) + abs(
                item.amount
            )
        category_refunds: dict[str, Decimal] = {}
        for row in refund_rows:
            category = row["category"] or "未分类"
            category_refunds[category] = category_refunds.get(category, Decimal("0")) + Decimal(
                row["amount"]
            )
        categories = tuple(
            CategoryStatistics(
                category=category,
                gross_expense=category_expenses.get(category, Decimal("0")),
                refunds=category_refunds.get(category, Decimal("0")),
            )
            for category in sorted(set(category_expenses) | set(category_refunds))
        )
        refund_total = sum((Decimal(row["amount"]) for row in refund_rows), Decimal("0"))
        reconciled_asset_change = None
        if date_from is None and date_to is None and not source_filters:
            reconciled_asset_change = self._verified_full_asset_change()
        return StatisticsReport(
            date_from=date_from,
            date_to=date_to,
            gross_expense=sum((abs(item.amount) for item in expenses), Decimal("0")),
            refunds=refund_total,
            ordinary_income=sum((item.amount for item in incomes), Decimal("0")),
            expense_count=len(expenses),
            income_count=len(incomes),
            refund_count=len(refund_rows),
            excluded_non_consumption_count=len(excluded),
            unclassified_excluded_count=len(unclassified),
            pending_review_excluded_count=len(pending),
            categories=categories,
            reconciled_asset_change=reconciled_asset_change,
        )

    def _verified_full_asset_change(self) -> Decimal | None:
        """Use independent balance chains only when the complete scope closes."""

        from .interval_reconciliation import IntervalReconciliationService

        signature = (
            self.store.connection.total_changes,
            int(self.store.connection.execute("PRAGMA data_version").fetchone()[0]),
        )
        if self._asset_change_cache and self._asset_change_cache[0] == signature:
            return self._asset_change_cache[1]
        report = IntervalReconciliationService(self.store).summarize(
            include_match_candidates=False
        )
        if any(
            report[key]
            for key in (
                "source_break_count",
                "canonical_missing_count",
                "canonical_amount_mismatch_count",
                "wallet_difference_count",
            )
        ):
            return self._cache_asset_change(signature, None)
        accounts = report["accounts"]
        wallets = report["wallet_accounts"]
        if not accounts and not any(item["actual_balance"] is not None for item in wallets):
            return self._cache_asset_change(signature, None)
        if any(Decimal(item["opening_before_first"]) != 0 for item in accounts):
            return self._cache_asset_change(signature, None)
        wallet_sources = {
            row["source"]
            for row in self.store.connection.execute(
                "SELECT DISTINCT source FROM raw_transactions "
                "WHERE source IN ('wechat', 'alipay')"
            ).fetchall()
        }
        if any(
            item["source"] in wallet_sources and item["actual_balance"] is None
            for item in wallets
        ):
            return self._cache_asset_change(signature, None)
        return self._cache_asset_change(
            signature, Decimal(report["asset_closure"]["known_total_assets"])
        )

    def _cache_asset_change(
        self, signature: tuple[int, int], value: Decimal | None
    ) -> Decimal | None:
        self._asset_change_cache = (signature, value)
        return value

    def timeline(
        self,
        period: str,
        date_from: date | None = None,
        date_to: date | None = None,
        source_filters: list[tuple[str, str | None]] | None = None,
    ) -> list[dict[str, Any]]:
        """Aggregate reportable canonical transactions into calendar periods."""
        if period not in {"day", "week", "month", "year"}:
            raise ValueError("period must be day, week, month, or year")
        if date_from and date_to and date_from > date_to:
            raise ValueError("date_from must not be after date_to")
        transactions = [
            item
            for item in self.store.list_canonical(source_filters)
            if _in_range(item.booking_date, date_from, date_to)
        ]
        pending_ids = {
            row["canonical_id"]
            for row in self.store.connection.execute(
                "SELECT canonical_id FROM classification_candidates WHERE status = 'pending'"
            ).fetchall()
        }
        pending_ids.update(
            row["from_canonical_id"]
            for row in self.store.connection.execute(
                "SELECT from_canonical_id FROM transaction_relationships "
                "WHERE relationship_type = 'refund' AND status = 'pending'"
            ).fetchall()
        )
        buckets: dict[date, dict[str, Any]] = {}
        for item in transactions:
            start = _period_start(item.booking_date, period)
            bucket = buckets.setdefault(start, _empty_period(start, period))
            if item.canonical_id in pending_ids:
                bucket["pending_review_excluded_count"] += 1
            elif item.tx_type == TransactionType.EXPENSE:
                bucket["gross_expense"] += abs(item.amount)
                bucket["expense_count"] += 1
            elif item.tx_type == TransactionType.INCOME:
                bucket["ordinary_income"] += item.amount
                bucket["income_count"] += 1
            elif item.tx_type == TransactionType.UNKNOWN:
                bucket["unclassified_excluded_count"] += 1

        refund_rows = self.store.connection.execute(
            """
            SELECT relationships.amount, refund.booking_date, refund.canonical_id
            FROM transaction_relationships AS relationships
            JOIN canonical_transactions AS refund
              ON refund.canonical_id = relationships.from_canonical_id
            WHERE relationships.relationship_type = 'refund'
              AND relationships.status = 'confirmed'
              AND (? IS NULL OR refund.booking_date >= ?)
              AND (? IS NULL OR refund.booking_date <= ?)
            """,
            (
                date_from.isoformat() if date_from else None,
                date_from.isoformat() if date_from else None,
                date_to.isoformat() if date_to else None,
                date_to.isoformat() if date_to else None,
            ),
        ).fetchall()
        selected_ids = {item.canonical_id for item in transactions}
        refund_rows = [row for row in refund_rows if row["canonical_id"] in selected_ids]
        confirmed_refund_ids = {row["canonical_id"] for row in refund_rows}
        refund_rows.extend(
            {
                "amount": str(abs(item.amount)),
                "booking_date": item.booking_date.isoformat(),
                "canonical_id": item.canonical_id,
            }
            for item in transactions
            if item.canonical_id not in pending_ids
            and item.tx_type == TransactionType.REFUND
            and item.canonical_id not in confirmed_refund_ids
        )
        for row in refund_rows:
            start = _period_start(date.fromisoformat(row["booking_date"]), period)
            bucket = buckets.setdefault(start, _empty_period(start, period))
            bucket["refunds"] += Decimal(row["amount"])
            bucket["refund_count"] += 1

        result = []
        for start in sorted(buckets, reverse=True):
            bucket = buckets[start]
            bucket["net_expense"] = bucket["gross_expense"] - bucket["refunds"]
            bucket["net_cash_flow"] = (
                bucket["ordinary_income"] + bucket["refunds"] - bucket["gross_expense"]
            )
            result.append(
                {
                    key: str(value) if isinstance(value, Decimal) else value
                    for key, value in bucket.items()
                }
            )
        return result


def _in_range(value: date, date_from: date | None, date_to: date | None) -> bool:
    return (date_from is None or value >= date_from) and (date_to is None or value <= date_to)


def _period_start(value: date, period: str) -> date:
    if period == "week":
        return value - timedelta(days=value.weekday())
    if period == "month":
        return value.replace(day=1)
    if period == "year":
        return value.replace(month=1, day=1)
    return value


def _empty_period(start: date, period: str) -> dict[str, Any]:
    if period == "week":
        end = start + timedelta(days=6)
    elif period == "month":
        next_start = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        end = next_start - timedelta(days=1)
    elif period == "year":
        end = start.replace(month=12, day=31)
    else:
        end = start
    return {
        "period": period,
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "gross_expense": Decimal("0"),
        "refunds": Decimal("0"),
        "net_expense": Decimal("0"),
        "ordinary_income": Decimal("0"),
        "net_cash_flow": Decimal("0"),
        "expense_count": 0,
        "income_count": 0,
        "refund_count": 0,
        "pending_review_excluded_count": 0,
        "unclassified_excluded_count": 0,
    }
