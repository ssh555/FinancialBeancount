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


def test_unambiguous_full_refund_can_be_confirmed_in_batch(store):
    original = transaction(1, "-100", "星巴克咖啡")
    refund = transaction(5, "100", "星巴克退款", status="退款成功")
    store.add_canonical(original)
    store.add_canonical(refund)
    service = RefundRelationshipService(store)
    service.generate_candidates()

    assert service.confirm_preferred_refunds("acceptance") == {"confirmed": 1, "warnings": 0}
    assert store.get_canonical(refund.canonical_id).tx_type == TransactionType.REFUND


def test_multiple_equal_refunds_use_earliest_available_same_day_expense(store):
    first = transaction(1, "-50", "医院")
    first.transaction_time = datetime(2026, 3, 1, 9, 0)
    second = transaction(1, "-50", "医院")
    second.transaction_time = datetime(2026, 3, 1, 10, 0)
    first_refund = transaction(1, "50", "医院退款", status="退款成功")
    first_refund.transaction_time = datetime(2026, 3, 1, 11, 0)
    second_refund = transaction(1, "50", "医院退款", status="退款成功")
    second_refund.transaction_time = datetime(2026, 3, 1, 12, 0)
    for item in (first, second, first_refund, second_refund):
        store.add_canonical(item)
    service = RefundRelationshipService(store)
    service.generate_candidates()

    assert service.confirm_preferred_refunds("acceptance") == {"confirmed": 2, "warnings": 2}
    confirmed = store.connection.execute(
        """
        SELECT from_canonical_id, to_canonical_id FROM transaction_relationships
        WHERE status = 'confirmed' ORDER BY from_canonical_id
        """
    ).fetchall()
    assert {row["to_canonical_id"] for row in confirmed} == {
        first.canonical_id,
        second.canonical_id,
    }


def test_partial_refund_is_confirmed_as_warning(store):
    original = transaction(1, "-100", "高铁票")
    refund = transaction(5, "80", "高铁票退款", status="退款成功")
    store.add_canonical(original)
    store.add_canonical(refund)
    service = RefundRelationshipService(store)
    service.generate_candidates()

    assert service.confirm_preferred_refunds("acceptance") == {"confirmed": 1, "warnings": 1}
    selected = service.list_candidates("confirmed")[0]
    assert "amount_partial" in selected.evidence


def test_warning_can_be_acknowledged_or_escalated_for_required_review(store):
    original = transaction(1, "-100", "高铁票")
    refund = transaction(5, "80", "高铁票退款", status="退款成功")
    store.add_canonical(original)
    store.add_canonical(refund)
    service = RefundRelationshipService(store)
    service.generate_candidates()
    service.confirm_preferred_refunds("acceptance")
    selected = service.list_candidates("confirmed")[0]

    acknowledged = service.acknowledge_warning(selected.relationship_id, "local-user")
    assert acknowledged.action == "warning_acknowledged"
    assert "warning_acknowledged" in service.get_candidate(selected.relationship_id).evidence
    restored = service.restore_warning(selected.relationship_id, "local-user")
    assert restored.action == "warning_restored"
    assert "warning_acknowledged" not in service.get_candidate(selected.relationship_id).evidence

    other_original = transaction(10, "-50", "医院")
    other_refund = transaction(11, "40", "医院退款", status="退款成功")
    store.add_canonical(other_original)
    store.add_canonical(other_refund)
    service.generate_candidates()
    service.confirm_preferred_refunds("acceptance")
    warning = next(
        item
        for item in service.list_candidates("confirmed")
        if item.refund_canonical_id == other_refund.canonical_id
    )
    escalated = service.escalate_warning(warning.relationship_id, "local-user")

    assert escalated.action == "warning_escalated"
    assert service.get_candidate(warning.relationship_id).status == "pending"
    assert store.get_canonical(other_refund.canonical_id).review_status.value == "pending"


def test_excluding_refund_rejects_all_choices_and_keeps_source_record_recoverable(store):
    first = transaction(1, "-50", "医院")
    second = transaction(2, "-50", "医院")
    refund = transaction(3, "50", "医院退款", status="退款成功")
    for item in (first, second, refund):
        store.add_canonical(item)
    service = RefundRelationshipService(store)
    candidates = service.generate_candidates()

    events = service.exclude_refund(candidates[0].relationship_id, "local-user", "账单有误")

    assert len(events) == 2
    assert all(item.status == "rejected" for item in service.list_candidates("rejected"))
    assert store.is_canonical_deleted(refund.canonical_id)
    assert store.get_canonical(refund.canonical_id) is not None


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
