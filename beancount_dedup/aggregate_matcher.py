"""Conservative many-wallet-rows to one bank-row matching."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from itertools import combinations

from .ledger_models import CanonicalTransaction, RawTransaction, ReviewStatus
from .ledger_store import LedgerStore
from .models import Platform, TransactionType, source_id_value


@dataclass(frozen=True)
class AggregateMatchCandidate:
    bank: RawTransaction
    payments: tuple[RawTransaction, ...]
    is_unique: bool


class AggregateMatcher:
    """Apply only after exact one-to-one matching has consumed its rows."""

    VERSION = "aggregate-balance-anchored-v1"

    def __init__(self, store: LedgerStore):
        self.store = store

    def generate_candidates(self) -> list[AggregateMatchCandidate]:
        raws = self.store.list_unlinked_raw()
        banks = [row for row in raws if row.source == Platform.BANK and row.balance is not None]
        payments = [row for row in raws if row.source in {Platform.ALIPAY, Platform.WECHAT}]
        candidates = []
        for bank in banks:
            eligible = [
                row
                for row in payments
                if row.booking_date == bank.booking_date
                and row.amount * bank.amount > 0
                and _funding_account(row) == bank.source_account
            ]
            solutions = [
                group
                for size in (2, 3)
                for group in combinations(eligible, size)
                if sum((row.amount for row in group), Decimal("0")) == bank.amount
            ]
            for group in solutions:
                candidates.append(
                    AggregateMatchCandidate(bank, tuple(group), len(solutions) == 1)
                )
        payment_usage: dict[str, int] = {}
        for candidate in candidates:
            if not candidate.is_unique:
                continue
            for payment in candidate.payments:
                payment_usage[payment.raw_id] = payment_usage.get(payment.raw_id, 0) + 1
        return [
            AggregateMatchCandidate(
                item.bank,
                item.payments,
                item.is_unique
                and all(payment_usage.get(row.raw_id) == 1 for row in item.payments),
            )
            for item in candidates
        ]

    def confirm_unique(self, actor: str) -> int:
        confirmed = 0
        for candidate in self.generate_candidates():
            if not candidate.is_unique:
                continue
            raws = (*candidate.payments, candidate.bank)
            if any(self.store.find_canonical_for_raw(row.raw_id) is not None for row in raws):
                continue
            direction = "expense" if candidate.bank.amount < 0 else "income"
            canonical = CanonicalTransaction(
                transaction_time=min(
                    (row.transaction_time for row in candidate.payments if row.transaction_time),
                    default=candidate.bank.transaction_time,
                ),
                booking_date=candidate.bank.booking_date,
                amount=candidate.bank.amount,
                direction=direction,
                merchant=" + ".join(
                    dict.fromkeys(
                        row.merchant or row.counterparty for row in candidate.payments
                    )
                ),
                payment_channel="+".join(
                    sorted({source_id_value(row.source) for row in candidate.payments})
                ),
                funding_account=candidate.bank.source_account,
                tx_type=(
                    TransactionType.EXPENSE
                    if candidate.bank.amount < 0
                    else TransactionType.INCOME
                ),
                review_status=ReviewStatus.AUTO_CONFIRMED,
                notes="同日平台明细合并为一笔银行流水；金额精确求和且余额链候选唯一",
            )
            reasons = (
                "match_phase_aggregate_fuzzy_fallback",
                "aggregate_amount_exact",
                "booking_date_exact",
                "bank_account_exact",
                "bank_balance_anchored",
                "aggregate_solution_unique",
            )
            for row in raws:
                canonical.add_source(
                    row,
                    confidence="0.95",
                    reasons=reasons,
                    matcher_version=self.VERSION,
                    linked_by=actor,
                )
            self.store.add_canonical(canonical)
            self.store.record_canonical_event(
                canonical.canonical_id,
                "aggregate_auto_confirmed",
                {"raw_ids": [row.raw_id for row in raws]},
                canonical.to_dict(),
                actor,
            )
            confirmed += 1
        return confirmed


def _funding_account(row: RawTransaction) -> str | None:
    value = f"{row.payment_method} {row.description}".lower()
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
