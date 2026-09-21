"""Canonical-only financial statistics with explicit refund treatment."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import date

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
    pending_review_excluded_count: int
    categories: tuple[CategoryStatistics, ...]

    @property
    def net_expense(self) -> Decimal:
        return self.gross_expense - self.refunds

    @property
    def net_cash_flow(self) -> Decimal:
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
            "expense_count": self.expense_count,
            "income_count": self.income_count,
            "refund_count": self.refund_count,
            "excluded_non_consumption_count": self.excluded_non_consumption_count,
            "pending_review_excluded_count": self.pending_review_excluded_count,
            "categories": [item.to_dict() for item in self.categories],
        }


class StatisticsService:
    """Calculate reports from unique economic transactions, never raw observations."""

    def __init__(self, store: LedgerStore):
        self.store = store

    def summarize(
        self, date_from: date | None = None, date_to: date | None = None
    ) -> StatisticsReport:
        if date_from and date_to and date_from > date_to:
            raise ValueError("date_from must not be after date_to")
        transactions = [
            item
            for item in self.store.list_canonical()
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

        refund_rows = self.store.connection.execute(
            """
            SELECT relationships.amount, original.category
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
            pending_review_excluded_count=len(pending),
            categories=categories,
        )


def _in_range(value: date, date_from: date | None, date_to: date | None) -> bool:
    return (date_from is None or value >= date_from) and (date_to is None or value <= date_to)
