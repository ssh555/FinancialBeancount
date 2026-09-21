"""Tests for the auditable raw-to-canonical ledger model."""

from datetime import date, datetime
from decimal import Decimal

import pytest
from beancount_dedup.ledger_models import (
    CanonicalTransaction,
    RawTransaction,
    ReviewStatus,
)
from beancount_dedup.models import Platform, TransactionType


def make_raw(source: Platform, transaction_id: str) -> RawTransaction:
    return RawTransaction(
        source=source,
        source_account="account-token",
        transaction_time=datetime(2026, 3, 1, 11, 31, 44),
        booking_date=date(2026, 3, 1),
        amount=Decimal("-57.96"),
        direction="expense",
        merchant="高德打车" if source == Platform.ALIPAY else "高德信息技术有限公司",
        payment_method="工商银行储蓄卡(4000)" if source == Platform.ALIPAY else "快捷支付",
        bank_card_suffix="4000",
        transaction_id=transaction_id,
        source_file_hash="fixture-file-hash",
        raw_row_number=8,
        original_row={"amount": "57.96", "redacted": True},
    )


def make_canonical() -> CanonicalTransaction:
    return CanonicalTransaction(
        transaction_time=datetime(2026, 3, 1, 11, 31, 44),
        booking_date=date(2026, 3, 1),
        amount=Decimal("-57.96"),
        direction="expense",
        merchant="高德打车",
        normalized_merchant="高德",
        category="交通出行",
        payment_channel="支付宝",
        funding_account="工商银行储蓄卡(4000)",
        tx_type=TransactionType.EXPENSE,
        review_status=ReviewStatus.AUTO_CONFIRMED,
    )


def test_two_raw_observations_are_one_display_transaction():
    canonical = make_canonical()
    alipay = make_raw(Platform.ALIPAY, "alipay-order-redacted")
    bank = make_raw(Platform.BANK, "bank-reference-redacted")

    canonical.add_source(
        alipay,
        confidence="1.0",
        reasons=["transaction_id_exact"],
        matcher_version="test-v1",
    )
    canonical.add_source(
        bank,
        confidence="0.99",
        reasons=["amount_exact", "datetime_exact", "bank_suffix_exact"],
        matcher_version="test-v1",
    )

    assert canonical.source_count == 2
    assert len(canonical.to_dict()["sources"]) == 2
    assert canonical.to_dict()["amount"] == "-57.96"


def test_reimported_raw_observation_cannot_be_linked_twice():
    canonical = make_canonical()
    first_import = make_raw(Platform.ALIPAY, "same-order")
    second_import = make_raw(Platform.ALIPAY, "same-order")
    canonical.add_source(
        first_import,
        confidence="1",
        reasons=["transaction_id_exact"],
        matcher_version="test-v1",
    )

    with pytest.raises(ValueError, match="already linked"):
        canonical.add_source(
            second_import,
            confidence="1",
            reasons=["transaction_id_exact"],
            matcher_version="test-v1",
        )


def test_platform_transaction_id_remains_stable_when_optional_merchant_id_changes():
    first = make_raw(Platform.ALIPAY, "stable-platform-order")
    with_merchant_id = RawTransaction(
        **{**first.__dict__, "merchant_order_id": "optional-merchant-order"}
    )

    assert first.deduplication_key == with_merchant_id.deduplication_key


def test_overlapping_bank_exports_have_same_observation_key():
    common = {
        "source": Platform.BANK,
        "source_account": "cmb-account",
        "booking_date": date(2026, 3, 1),
        "amount": "-20.00",
        "direction": "expense",
        "balance": "980.00",
        "merchant": "测试商户",
        "description": "快捷支付",
        "payment_method": "招商银行",
        "original_row": {"same": "transaction"},
    }
    partial_export = RawTransaction(
        **common,
        source_file_hash="jan-sep-hash",
        raw_row_number=123,
    )
    annual_export = RawTransaction(
        **common,
        source_file_hash="jan-dec-hash",
        raw_row_number=456,
    )

    assert partial_export.deduplication_key == annual_export.deduplication_key


def test_separate_bank_transactions_with_different_balances_remain_distinct():
    common = {
        "source": Platform.BANK,
        "source_account": "cmb-account",
        "booking_date": date(2026, 3, 1),
        "amount": "-20.00",
        "direction": "expense",
        "merchant": "测试商户",
        "description": "快捷支付",
        "payment_method": "招商银行",
        "source_file_hash": "annual-hash",
        "original_row": {},
    }
    first = RawTransaction(**common, balance="980.00", raw_row_number=10)
    second = RawTransaction(**common, balance="960.00", raw_row_number=11)

    assert first.deduplication_key != second.deduplication_key


def test_source_can_be_detached_after_incorrect_match():
    canonical = make_canonical()
    raw = make_raw(Platform.BANK, "bank-reference")
    canonical.add_source(
        raw,
        confidence="0.7",
        reasons=["manual_candidate"],
        matcher_version="test-v1",
    )

    detached = canonical.remove_source(raw.raw_id)

    assert detached is raw
    assert canonical.source_count == 0


def test_raw_record_is_immutable():
    raw = make_raw(Platform.ALIPAY, "immutable-order")

    with pytest.raises((AttributeError, TypeError)):
        raw.amount = Decimal("-1")


def test_only_four_digit_card_suffix_is_accepted():
    with pytest.raises(ValueError, match="four digits"):
        RawTransaction(
            source=Platform.BANK,
            source_account="account-token",
            amount="-1",
            direction="expense",
            bank_card_suffix="123456",
            original_row={},
        )


def test_confidence_must_be_between_zero_and_one():
    canonical = make_canonical()

    with pytest.raises(ValueError, match="between 0 and 1"):
        canonical.add_source(
            make_raw(Platform.BANK, "bad-confidence"),
            confidence="1.01",
            reasons=["invalid"],
            matcher_version="test-v1",
        )
