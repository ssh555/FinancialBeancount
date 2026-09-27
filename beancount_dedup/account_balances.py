"""Latest known bank cash and conservatively identified internal-product balances."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from .ledger_store import LedgerStore


@dataclass(frozen=True)
class BalanceItem:
    name: str
    balance: Decimal
    as_of: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "balance": str(self.balance), "as_of": self.as_of}


class AccountBalanceService:
    """Report statement-backed balances without treating cumulative cash flow as wealth."""

    def __init__(self, store: LedgerStore):
        self.store = store

    def summarize(self) -> dict[str, Any]:
        cash_accounts = self._latest_bank_cash()
        internal_products = self._internal_products()
        cash_total = sum((item.balance for item in cash_accounts), Decimal("0"))
        product_total = sum((item.balance for item in internal_products), Decimal("0"))
        dates = [item.as_of for item in (*cash_accounts, *internal_products) if item.as_of]
        return {
            "known_balance": str(cash_total + product_total),
            "cash_total": str(cash_total),
            "internal_product_total": str(product_total),
            "as_of": max(dates) if dates else None,
            "cash_accounts": [item.to_dict() for item in cash_accounts],
            "internal_products": [item.to_dict() for item in internal_products],
            "scope_note": "仅汇总带余额的银行活期账户和可明确识别的银行内部产品，不含外部基金平台及无法获得余额的支付账户。",
        }

    def _latest_bank_cash(self) -> tuple[BalanceItem, ...]:
        rows = self.store.connection.execute(
            """
            WITH ranked AS (
                SELECT source_account, booking_date, balance,
                       ROW_NUMBER() OVER (
                           PARTITION BY source_account
                           ORDER BY booking_date DESC,
                                    COALESCE(transaction_time, '') DESC,
                                    COALESCE(raw_row_number, 0) DESC,
                                    raw_id DESC
                       ) AS position
                FROM raw_transactions
                WHERE source = 'bank' AND balance IS NOT NULL AND balance != ''
            )
            SELECT source_account, booking_date, balance
            FROM ranked WHERE position = 1 ORDER BY source_account
            """
        ).fetchall()
        return tuple(
            BalanceItem(row["source_account"], Decimal(row["balance"]), row["booking_date"])
            for row in rows
        )

    def _internal_products(self) -> tuple[BalanceItem, ...]:
        rows = self.store.connection.execute(
            """
            SELECT source_account, booking_date, amount, description, counterparty
            FROM raw_transactions
            WHERE source = 'bank'
              AND (
                    description IN ('朝朝宝转入', '朝朝宝转出')
                    OR (
                        source_account LIKE '%工商银行%'
                        AND description = '基金购买'
                        AND counterparty NOT LIKE '%基金销售%'
                    )
              )
            ORDER BY booking_date
            """
        ).fetchall()
        positions: dict[str, Decimal] = {}
        latest: dict[str, str] = {}
        for row in rows:
            if row["description"] in {"朝朝宝转入", "朝朝宝转出"}:
                name = f"{row['source_account']}朝朝宝"
                movement = -Decimal(row["amount"])
            else:
                name = f"{row['source_account']}天天盈"
                movement = abs(Decimal(row["amount"]))
            positions[name] = positions.get(name, Decimal("0")) + movement
            latest[name] = max(latest.get(name, ""), row["booking_date"])
        return tuple(
            BalanceItem(name, balance, latest[name])
            for name, balance in sorted(positions.items())
            if balance != 0
        )
