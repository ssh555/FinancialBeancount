"""Tests for conservative cross-platform candidate generation."""

from datetime import date, datetime
from decimal import Decimal

import pytest
from beancount_dedup.canonical_matcher import ConservativeMatcher
from beancount_dedup.ledger_models import CanonicalTransaction, RawTransaction
from beancount_dedup.ledger_store import LedgerStore
from beancount_dedup.models import Platform


@pytest.fixture
def store(tmp_path):
    with LedgerStore(tmp_path / "ledger.sqlite3") as ledger_store:
        yield ledger_store


def raw(
    source: Platform,
    identity: str,
    *,
    when: datetime | None,
    merchant: str,
    payment_method: str,
    suffix: str | None,
    amount: str = "-57.96",
) -> RawTransaction:
    return RawTransaction(
        source=source,
        source_account=f"account-{identity}",
        transaction_time=when,
        booking_date=when.date() if when else date(2026, 3, 1),
        amount=amount,
        direction="expense",
        merchant=merchant,
        counterparty=merchant,
        payment_method=payment_method,
        bank_card_suffix=suffix,
        transaction_id=identity,
        original_row={"redacted": True},
    )


def add(store, *transactions):
    return [store.add_raw(transaction).raw_transaction for transaction in transactions]


def test_exact_time_suffix_and_merchant_create_high_confidence_candidate(store):
    payment, bank = add(
        store,
        raw(
            Platform.ALIPAY,
            "payment",
            when=datetime(2026, 3, 1, 11, 31, 44),
            merchant="高德打车",
            payment_method="工商银行储蓄卡(4000)",
            suffix="4000",
        ),
        raw(
            Platform.BANK,
            "bank",
            when=datetime(2026, 3, 1, 11, 31, 44),
            merchant="高德信息技术有限公司",
            payment_method="工商银行 快捷支付",
            suffix="4000",
        ),
    )

    candidates = ConservativeMatcher(store).generate_candidates()

    assert len(candidates) == 1
    assert candidates[0].payment_raw_id == payment.raw_id
    assert candidates[0].bank_raw_id == bank.raw_id
    assert candidates[0].confidence == pytest.approx(Decimal("0.99"))
    assert candidates[0].is_ambiguous is False


def test_amount_and_date_without_independent_evidence_create_no_candidate(store):
    add(
        store,
        raw(
            Platform.ALIPAY,
            "payment",
            when=datetime(2026, 3, 1, 10, 0),
            merchant="甲商户",
            payment_method="余额",
            suffix=None,
        ),
        raw(
            Platform.BANK,
            "bank",
            when=None,
            merchant="完全不同名称",
            payment_method="未知银行",
            suffix=None,
        ),
    )

    assert ConservativeMatcher(store).generate_candidates() == []


def test_same_amount_multiple_bank_records_are_marked_ambiguous(store):
    add(
        store,
        raw(
            Platform.WECHAT,
            "payment",
            when=datetime(2026, 3, 1, 9, 0),
            merchant="高德打车",
            payment_method="招商银行储蓄卡(5066)",
            suffix="5066",
        ),
        raw(
            Platform.BANK,
            "bank-one",
            when=None,
            merchant="高德信息技术有限公司",
            payment_method="招商银行",
            suffix="5066",
        ),
        raw(
            Platform.BANK,
            "bank-two",
            when=None,
            merchant="高德信息技术有限公司",
            payment_method="招商银行",
            suffix="5066",
        ),
    )

    candidates = ConservativeMatcher(store).generate_candidates()

    assert len(candidates) == 2
    assert all(candidate.is_ambiguous for candidate in candidates)
    assert all(candidate.status == "pending" for candidate in candidates)


def test_lower_scoring_competing_candidate_is_still_ambiguous(store):
    add(
        store,
        raw(
            Platform.WECHAT,
            "payment",
            when=datetime(2026, 3, 1, 9, 0),
            merchant="高德打车",
            payment_method="招商银行储蓄卡(5066)",
            suffix="5066",
        ),
        raw(
            Platform.BANK,
            "strong-bank",
            when=datetime(2026, 3, 1, 9, 0),
            merchant="高德信息技术有限公司",
            payment_method="招商银行",
            suffix="5066",
        ),
        raw(
            Platform.BANK,
            "weaker-bank",
            when=None,
            merchant="高德信息技术有限公司",
            payment_method="未知银行",
            suffix=None,
        ),
    )

    candidates = ConservativeMatcher(store).generate_candidates()

    assert len(candidates) == 2
    assert candidates[0].confidence != candidates[1].confidence
    assert all(candidate.is_ambiguous for candidate in candidates)


def test_persisted_candidates_can_be_loaded_for_review(store):
    add(
        store,
        raw(
            Platform.ALIPAY,
            "payment",
            when=datetime(2026, 3, 1, 11, 31, 44),
            merchant="高德打车",
            payment_method="工商银行储蓄卡(4000)",
            suffix="4000",
        ),
        raw(
            Platform.BANK,
            "bank",
            when=datetime(2026, 3, 1, 11, 31, 44),
            merchant="高德信息技术有限公司",
            payment_method="工商银行",
            suffix="4000",
        ),
    )
    matcher = ConservativeMatcher(store)
    generated = matcher.generate_candidates()

    loaded = matcher.list_candidates()

    assert loaded == generated


def test_same_platform_records_are_never_cross_platform_candidates(store):
    add(
        store,
        raw(
            Platform.ALIPAY,
            "one",
            when=datetime(2026, 3, 1, 9, 0),
            merchant="高德打车",
            payment_method="工商银行储蓄卡(4000)",
            suffix="4000",
        ),
        raw(
            Platform.ALIPAY,
            "two",
            when=datetime(2026, 3, 1, 9, 0),
            merchant="高德打车",
            payment_method="工商银行储蓄卡(4000)",
            suffix="4000",
        ),
    )

    assert ConservativeMatcher(store).generate_candidates() == []


def test_already_linked_raw_is_excluded_from_candidate_generation(store):
    payment, bank = add(
        store,
        raw(
            Platform.ALIPAY,
            "payment",
            when=datetime(2026, 3, 1, 11, 31, 44),
            merchant="高德打车",
            payment_method="工商银行储蓄卡(4000)",
            suffix="4000",
        ),
        raw(
            Platform.BANK,
            "bank",
            when=datetime(2026, 3, 1, 11, 31, 44),
            merchant="高德信息技术有限公司",
            payment_method="工商银行",
            suffix="4000",
        ),
    )
    canonical = CanonicalTransaction(
        transaction_time=payment.transaction_time,
        booking_date=date(2026, 3, 1),
        amount="-57.96",
        direction="expense",
        merchant="高德打车",
    )
    canonical.add_source(
        payment,
        confidence="1",
        reasons=["manual_confirmed"],
        matcher_version="test-v1",
    )
    store.add_canonical(canonical)

    assert bank.raw_id
    assert ConservativeMatcher(store).generate_candidates() == []
