"""Tests for auditable canonical refund relationships."""

from datetime import date, datetime

import pytest
from beancount_dedup.ledger_models import CanonicalTransaction
from beancount_dedup.ledger_store import LedgerStore
from beancount_dedup.models import TransactionType
from beancount_dedup.refund_relationships import RefundRelationshipService


@pytest.fixture
def store(tmp_path):
    with LedgerStore(tmp_path / "ledger.sqlite3") as ledger_store:
        yield ledger_store


def transaction(day: int, amount: str, merchant: str, *, status: str = ""):
    return CanonicalTransaction(
        transaction_time=datetime(2026, 3, day, 12, 0),
        booking_date=date(2026, 3, day),
        amount=amount,
        direction="income" if not amount.startswith("-") else "expense",
        merchant=merchant,
        status=status,
        tx_type=TransactionType.INCOME if not amount.startswith("-") else TransactionType.EXPENSE,
    )


def test_full_refund_candidate_requires_refund_marker_and_merchant_match(store):
    original = transaction(1, "-100", "星巴克咖啡")
    refund = transaction(5, "100", "星巴克退款", status="退款成功")
    unrelated_income = transaction(5, "100", "工资", status="入账")
    for item in (original, refund, unrelated_income):
        store.add_canonical(item)

    candidates = RefundRelationshipService(store).generate_candidates()

    assert len(candidates) == 1
    assert candidates[0].refund_canonical_id == refund.canonical_id
    assert candidates[0].original_canonical_id == original.canonical_id
    assert candidates[0].amount == 100
    assert "amount_full" in candidates[0].evidence


def test_same_amount_multiple_originals_is_ambiguous(store):
    for item in (
        transaction(1, "-100", "星巴克"),
        transaction(2, "-100", "星巴克咖啡"),
        transaction(5, "100", "星巴克退款", status="退款成功"),
    ):
        store.add_canonical(item)

    candidates = RefundRelationshipService(store).generate_candidates()

    assert len(candidates) == 2
    assert all(item.is_ambiguous for item in candidates)

    service = RefundRelationshipService(store)
    service.confirm(candidates[0].relationship_id, "local-user")
    assert service.get_candidate(candidates[1].relationship_id).status == "superseded"
    assert service.list_events(candidates[1].relationship_id)[0].action == "superseded"


def test_multiple_partial_refunds_can_link_to_one_original(store):
    original = transaction(1, "-100", "测试商户")
    first_refund = transaction(5, "30", "测试商户退款", status="退款成功")
    second_refund = transaction(6, "40", "测试商户退款", status="退款成功")
    for item in (original, first_refund, second_refund):
        store.add_canonical(item)
    service = RefundRelationshipService(store)
    candidates = service.generate_candidates()

    first = next(
        item for item in candidates if item.refund_canonical_id == first_refund.canonical_id
    )
    second = next(
        item for item in candidates if item.refund_canonical_id == second_refund.canonical_id
    )
    service.confirm(first.relationship_id, "local-user")
    service.confirm(second.relationship_id, "local-user")

    assert service._get(first.relationship_id).status == "confirmed"
    assert service._get(second.relationship_id).status == "confirmed"
    assert store.get_canonical(first_refund.canonical_id).tx_type == TransactionType.REFUND
    assert store.get_canonical(second_refund.canonical_id).tx_type == TransactionType.REFUND


def test_confirmed_refunds_cannot_exceed_original_amount(store):
    original = transaction(1, "-100", "测试商户")
    first_refund = transaction(5, "70", "测试商户退款", status="退款成功")
    second_refund = transaction(6, "70", "测试商户退款", status="退款成功")
    for item in (original, first_refund, second_refund):
        store.add_canonical(item)
    service = RefundRelationshipService(store)
    candidates = service.generate_candidates()
    first = next(
        item for item in candidates if item.refund_canonical_id == first_refund.canonical_id
    )
    second = next(
        item for item in candidates if item.refund_canonical_id == second_refund.canonical_id
    )
    service.confirm(first.relationship_id, "local-user")

    with pytest.raises(ValueError, match="exceed"):
        service.confirm(second.relationship_id, "local-user")

    assert service._get(second.relationship_id).status == "pending"


def test_reject_preserves_transactions_and_writes_audit_event(store):
    original = transaction(1, "-50", "测试商户")
    refund = transaction(5, "50", "测试商户退款", status="退款成功")
    store.add_canonical(original)
    store.add_canonical(refund)
    service = RefundRelationshipService(store)
    candidate = service.generate_candidates()[0]

    event = service.reject(candidate.relationship_id, "local-user")

    assert event.action == "rejected"
    assert service._get(candidate.relationship_id).status == "rejected"
    assert service.list_events(candidate.relationship_id) == [event]
    assert store.get_canonical(original.canonical_id) is not None
    assert store.get_canonical(refund.canonical_id) is not None
