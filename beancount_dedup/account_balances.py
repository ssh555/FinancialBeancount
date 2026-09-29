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
    source: str | None = None
    balance_kind: str = "cash"
    statement_balance: Decimal | None = None
    pending_adjustment: Decimal = Decimal("0")

    def to_dict(self) -> dict[str, str]:
        result = {
            "name": self.name,
            "balance": str(self.balance),
            "as_of": self.as_of,
            "balance_kind": self.balance_kind,
        }
        if self.source is not None:
            result["source"] = self.source
        if self.statement_balance is not None:
            result["statement_balance"] = str(self.statement_balance)
            result["pending_adjustment"] = str(self.pending_adjustment)
            result["estimated"] = str(self.pending_adjustment != 0).lower()
        return result


class AccountBalanceService:
    """Report statement-backed balances without treating cumulative cash flow as wealth."""

    def __init__(self, store: LedgerStore):
        self.store = store

    def summarize(self) -> dict[str, Any]:
        cash_accounts = self._latest_bank_cash()
        internal_products = self._internal_products()
        snapshot_accounts = self._snapshot_accounts()
        cash_total = sum((item.balance for item in cash_accounts), Decimal("0"))
        product_total = sum((item.balance for item in internal_products), Decimal("0"))
        snapshot_total = sum(
            (item.balance for item in snapshot_accounts if item.balance_kind != "credit_limit"),
            Decimal("0"),
        )
        dates = [
            item.as_of
            for item in (*cash_accounts, *internal_products, *snapshot_accounts)
            if item.as_of
        ]
        return {
            "known_balance": str(cash_total + product_total + snapshot_total),
            "cash_total": str(cash_total),
            "internal_product_total": str(product_total),
            "snapshot_total": str(snapshot_total),
            "as_of": max(dates) if dates else None,
            "cash_accounts": [item.to_dict() for item in cash_accounts],
            "internal_products": [item.to_dict() for item in internal_products],
            "snapshot_accounts": [item.to_dict() for item in snapshot_accounts],
            "scope_note": "银行余额以最新流水余额为锚点，并叠加其后微信、支付宝中明确绑定该卡的待银行入账交易；另汇总可识别的银行内部产品及经用户核验的支付账户余额快照。不含没有银行流水余额锚点的账户或余额未知的外部基金平台。",
        }

    def _snapshot_accounts(self) -> tuple[BalanceItem, ...]:
        return tuple(
            BalanceItem(
                snapshot.source_account,
                snapshot.balance,
                snapshot.as_of.isoformat(),
                snapshot.source,
                snapshot.balance_kind,
            )
            for snapshot in self.store.list_latest_account_balance_snapshots()
        )

    def _latest_bank_cash(self) -> tuple[BalanceItem, ...]:
        rows = self.store.connection.execute(
            """
            WITH ranked AS (
                SELECT source_account, booking_date, transaction_time, balance,
                       bank_card_suffix,
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
            SELECT source_account, booking_date, transaction_time, balance, bank_card_suffix
            FROM ranked WHERE position = 1 ORDER BY source_account
            """
        ).fetchall()
        result = []
        for row in rows:
            statement_balance = Decimal(row["balance"])
            suffix = row["bank_card_suffix"]
            adjustment = Decimal("0")
            as_of = row["booking_date"]
            pending = self.store.connection.execute(
                """
                    SELECT amount, booking_date
                    FROM raw_transactions
                    WHERE source IN ('wechat', 'alipay')
                      AND (
                            (? != '' AND bank_card_suffix = ?)
                            OR payment_method LIKE '%' || ? || '%'
                      )
                      AND booking_date > ?
                      AND amount != '0'
                    ORDER BY booking_date, COALESCE(transaction_time, ''), raw_id
                """,
                (suffix or "", suffix or "", row["source_account"], row["booking_date"]),
            ).fetchall()
            adjustment = sum((Decimal(item["amount"]) for item in pending), Decimal("0"))
            if pending:
                as_of = max(item["booking_date"] for item in pending)
            result.append(
                BalanceItem(
                    row["source_account"],
                    statement_balance + adjustment,
                    as_of,
                    statement_balance=statement_balance,
                    pending_adjustment=adjustment,
                )
            )
        return tuple(result)

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
