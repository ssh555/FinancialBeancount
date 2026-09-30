"""Tests for reusable interval and row-level ledger reconciliation."""

from datetime import date
from decimal import Decimal

from beancount_dedup.interval_reconciliation import IntervalReconciliationService
from beancount_dedup.ledger_models import CanonicalTransaction, RawTransaction
from beancount_dedup.ledger_store import LedgerStore
from beancount_dedup.models import Platform, TransactionType


def _raw(amount: str, balance: str, identity: str) -> RawTransaction:
    return RawTransaction(
        source=Platform.BANK,
        source_account="测试银行",
        booking_date=date(2026, 1, int(identity)),
        amount=amount,
        balance=balance,
        direction="income" if not amount.startswith("-") else "expense",
        transaction_id=identity,
        original_row={"identity": identity},
    )


def test_interval_reconciliation_finds_first_balance_break(tmp_path):
    with LedgerStore(tmp_path / "ledger.sqlite3") as store:
        for row in (_raw("100", "100", "1"), _raw("-20", "81", "2")):
            stored = store.add_raw(row).raw_transaction
            canonical = CanonicalTransaction(
                transaction_time=None,
                booking_date=stored.booking_date,
                amount=stored.amount,
                direction=stored.direction,
                merchant="测试",
                tx_type=(TransactionType.INCOME if stored.amount >= 0 else TransactionType.EXPENSE),
            )
            canonical.add_source(
                stored,
                confidence="1",
                reasons=("test",),
                matcher_version="test",
            )
            store.add_canonical(canonical)

        report = IntervalReconciliationService(store).summarize()

    assert report["source_break_count"] == 1
    assert report["canonical_missing_count"] == 0
    assert report["accounts"][0]["first_failure"]["source_difference"] == "1"


def test_interval_reconciliation_finds_unlinked_anchor_row(tmp_path):
    with LedgerStore(tmp_path / "ledger.sqlite3") as store:
        store.add_raw(_raw("100", "100", "1"))

        report = IntervalReconciliationService(store).summarize()

    assert report["source_break_count"] == 0
    assert report["canonical_missing_count"] == 1
    assert report["accounts"][0]["first_failure"]["status"] == "canonical_missing"


def test_wallet_reconciliation_splits_mixed_alipay_payment(tmp_path):
    with LedgerStore(tmp_path / "ledger.sqlite3") as store:
        store.add_raw(
            RawTransaction(
                source=Platform.ALIPAY,
                source_account="支付宝",
                booking_date=date(2023, 9, 2),
                amount="-6.15",
                direction="expense",
                merchant="地铁",
                description="支付",
                payment_method="招商银行储蓄卡(5066)&账户余额",
                status="交易成功",
                transaction_id="ali",
                original_row={},
            )
        )
        store.add_raw(
            RawTransaction(
                source=Platform.BANK,
                source_account="招商银行",
                booking_date=date(2023, 9, 4),
                amount="-3.00",
                direction="expense",
                merchant="支付宝",
                description="快捷支付",
                payment_method="招商银行",
                balance="100",
                transaction_id="bank",
                original_row={},
            )
        )
        store.record_account_balance_snapshot(
            "alipay",
            "支付宝余额",
            Decimal("-3.15"),
            date(2023, 9, 4),
            created_by="test",
        )

        wallet = IntervalReconciliationService(store).summarize()["wallet_accounts"][1]

    assert wallet["projected_balance"] == "-3.15"
    assert wallet["difference"] == "0.00"
    assert wallet["intervals"][0]["reason"] == "mixed_funding_split"
    assert wallet["intervals"][0]["evidence"]["balance_anchor"] == "100"
    assert wallet["intervals"][0]["evidence"]["match_phase"] == "fuzzy_split_fallback"


def test_mixed_payment_does_not_reuse_bank_row_linked_to_other_wallet_raw(tmp_path):
    with LedgerStore(tmp_path / "ledger.sqlite3") as store:
        mixed = store.add_raw(
            RawTransaction(
                source=Platform.ALIPAY,
                source_account="支付宝",
                booking_date=date(2023, 9, 2),
                amount="-6.15",
                direction="expense",
                merchant="地铁",
                payment_method="招商银行储蓄卡(5066)&账户余额",
                status="交易成功",
                transaction_id="mixed",
                original_row={},
            )
        ).raw_transaction
        other = store.add_raw(
            RawTransaction(
                source=Platform.ALIPAY,
                source_account="支付宝",
                booking_date=date(2023, 9, 4),
                amount="-3.00",
                direction="expense",
                merchant="另一笔交易",
                payment_method="招商银行储蓄卡(5066)",
                status="交易成功",
                transaction_id="other",
                original_row={},
            )
        ).raw_transaction
        bank = store.add_raw(
            RawTransaction(
                source=Platform.BANK,
                source_account="招商银行",
                booking_date=date(2023, 9, 4),
                amount="-3.00",
                direction="expense",
                merchant="支付宝",
                payment_method="招商银行",
                balance="100",
                transaction_id="bank",
                original_row={},
            )
        ).raw_transaction
        canonical = CanonicalTransaction(
            transaction_time=None,
            booking_date=date(2023, 9, 4),
            amount=Decimal("-3.00"),
            direction="expense",
            merchant="另一笔交易",
            tx_type=TransactionType.EXPENSE,
        )
        canonical.add_source(other, confidence="1", reasons=("test",), matcher_version="test")
        canonical.add_source(bank, confidence="1", reasons=("test",), matcher_version="test")
        store.add_canonical(canonical)
        store.record_account_balance_snapshot(
            "alipay", "支付宝余额", Decimal("-6.15"), date(2023, 9, 4), created_by="test"
        )

        wallet = IntervalReconciliationService(store).summarize()["wallet_accounts"][1]

    assert mixed.raw_id == wallet["intervals"][0]["raw_id"]
    assert wallet["intervals"][0]["reason"] == "mixed_funding_unresolved"
    assert wallet["intervals"][0]["evidence"] == {"warning": "bank_part_not_found"}


def test_aggregate_fallback_reports_unique_exact_sum_without_confirming(tmp_path):
    with LedgerStore(tmp_path / "ledger.sqlite3") as store:
        raws = [
            RawTransaction(
                source=Platform.ALIPAY,
                source_account="支付宝",
                booking_date=date(2026, 1, 2),
                amount=amount,
                direction="expense",
                merchant=merchant,
                payment_method="招商银行储蓄卡(5066)",
                transaction_id=identity,
                original_row={},
            )
            for amount, merchant, identity in (
                ("-10", "商户甲", "a"),
                ("-20", "商户乙", "b"),
            )
        ]
        raws.append(
            RawTransaction(
                source=Platform.BANK,
                source_account="招商银行",
                booking_date=date(2026, 1, 2),
                amount="-30",
                direction="expense",
                merchant="支付宝",
                payment_method="招商银行",
                balance="70",
                transaction_id="bank",
                original_row={},
            )
        )
        for raw in raws:
            stored = store.add_raw(raw).raw_transaction
            canonical = CanonicalTransaction(
                transaction_time=None,
                booking_date=stored.booking_date,
                amount=stored.amount,
                direction=stored.direction,
                merchant=stored.merchant,
                tx_type=TransactionType.EXPENSE,
            )
            canonical.add_source(stored, confidence="1", reasons=("test",), matcher_version="test")
            store.add_canonical(canonical)

        candidates = IntervalReconciliationService(store).summarize()["aggregate_match_candidates"]

    assert len(candidates) == 1
    assert candidates[0]["bank_amount"] == "-30"
    assert candidates[0]["is_unique"] is True
    assert candidates[0]["requires_review"] is True
    assert {item["amount"] for item in candidates[0]["solutions"][0]} == {"-10", "-20"}


def test_fast_reconciliation_can_skip_expensive_match_diagnostics(tmp_path):
    with LedgerStore(tmp_path / "ledger.sqlite3") as store:
        store.add_raw(_raw("100", "100", "1"))

        report = IntervalReconciliationService(store).summarize(include_match_candidates=False)

    assert report["aggregate_match_candidates"] == []
