"""Tests for grouped duplicate-candidate review and audit history."""

from dataclasses import replace
from datetime import date, datetime

import pytest
from beancount_dedup.candidate_review import CandidateReviewService
from beancount_dedup.canonical_matcher import ConservativeMatcher
from beancount_dedup.ledger_models import RawTransaction
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
    merchant: str,
    suffix: str | None,
    bank_time: datetime | None = None,
):
    return RawTransaction(
        source=source,
        source_account=f"account-{identity}",
        transaction_time=(datetime(2026, 6, 1, 12, 0) if source != Platform.BANK else bank_time),
        booking_date=date(2026, 6, 1),
        amount="-20.00",
        direction="expense",
        merchant=merchant,
        counterparty=merchant,
        payment_method="招商银行" if suffix else "未知银行",
        bank_card_suffix=suffix,
        transaction_id=identity,
        original_row={"identity": identity},
    )


def generate_pair(store):
    payment = store.add_raw(
        raw(Platform.ALIPAY, "payment", merchant="高德打车", suffix="5066")
    ).raw_transaction
    bank = store.add_raw(
        raw(Platform.BANK, "bank", merchant="高德信息技术有限公司", suffix="5066")
    ).raw_transaction
    candidate = ConservativeMatcher(store).generate_candidates()[0]
    return payment, bank, candidate


def test_group_contains_full_raw_records_and_competing_candidates(store):
    store.add_raw(raw(Platform.WECHAT, "payment", merchant="高德打车", suffix="5066"))
    store.add_raw(raw(Platform.BANK, "bank-one", merchant="高德信息技术有限公司", suffix="5066"))
    store.add_raw(raw(Platform.BANK, "bank-two", merchant="高德信息技术有限公司", suffix="5066"))
    ConservativeMatcher(store).generate_candidates()

    groups = CandidateReviewService(store).list_groups()

    assert len(groups) == 2
    assert all(group.candidate.is_ambiguous for group in groups)
    assert all(len(group.conflicts) == 1 for group in groups)
    assert all(group.payment.original_row for group in groups)
    assert all(group.bank.original_row for group in groups)


def test_reject_keeps_both_raw_observations_and_writes_event(store):
    payment, bank, candidate = generate_pair(store)
    service = CandidateReviewService(store)

    event = service.reject(candidate.candidate_id, actor="local-user")

    assert event.action == "rejected"
    assert store.get_raw(payment.raw_id) == payment
    assert store.get_raw(bank.raw_id) == bank
    assert store.list_canonical() == []
    assert service.get_group(candidate.candidate_id).candidate.status == "rejected"
    assert service.list_events(candidate.candidate_id) == [event]


def test_confirm_creates_one_canonical_with_two_sources(store):
    payment, bank, candidate = generate_pair(store)
    service = CandidateReviewService(store)

    canonical, event = service.confirm(candidate.candidate_id, actor="local-user")

    loaded = store.get_canonical(canonical.canonical_id)
    assert loaded is not None
    assert loaded.source_count == 2
    assert {item.raw_transaction.raw_id for item in loaded.source_links} == {
        payment.raw_id,
        bank.raw_id,
    }
    assert event.action == "confirmed"
    assert event.after["canonical"]["source_count"] == 2
    assert service.get_group(candidate.candidate_id).candidate.status == "confirmed"


def test_exact_payment_match_can_be_safely_confirmed_in_batch(store):
    store.add_raw(raw(Platform.ALIPAY, "payment", merchant="高德打车", suffix="4000"))
    store.add_raw(
        raw(
            Platform.BANK,
            "bank",
            merchant="高德信息技术有限公司",
            suffix="6357",
            bank_time=datetime(2026, 6, 1, 12, 0, 2),
        )
    )
    ConservativeMatcher(store).generate_candidates()

    confirmed = CandidateReviewService(store).confirm_exact_payment_matches("acceptance")

    assert confirmed == 1
    assert len(store.list_canonical()) == 1
    canonical = store.get_canonical(store.list_canonical()[0].canonical_id)
    assert canonical is not None
    assert canonical.source_count == 2


def test_unique_exact_time_edge_wins_over_same_amount_weak_conflict(store):
    payment = store.add_raw(
        raw(Platform.ALIPAY, "payment", merchant="同额商户", suffix="4000")
    ).raw_transaction
    exact_bank = store.add_raw(
        raw(
            Platform.BANK,
            "exact-bank",
            merchant="同额商户",
            suffix="4000",
            bank_time=datetime(2026, 6, 1, 12, 0, 1),
        )
    ).raw_transaction
    store.add_raw(
        raw(
            Platform.BANK,
            "weak-bank",
            merchant="同额商户",
            suffix="4000",
            bank_time=None,
        )
    )
    assert all(item.is_ambiguous for item in ConservativeMatcher(store).generate_candidates())

    confirmed = CandidateReviewService(store).confirm_exact_payment_matches("acceptance")

    assert confirmed == 1
    canonical = store.find_canonical_for_raw(payment.raw_id)
    assert canonical is not None
    assert {item.raw_transaction.raw_id for item in canonical.source_links} == {
        payment.raw_id,
        exact_bank.raw_id,
    }


def test_unique_pass_recomputes_graph_after_exact_conflict_is_removed(store):
    first_payment = store.add_raw(
        raw(Platform.ALIPAY, "first-payment", merchant="同额商户", suffix="4000")
    ).raw_transaction
    second_payment = store.add_raw(
        replace(
            raw(Platform.ALIPAY, "second-payment", merchant="同额商户", suffix="4000"),
            transaction_time=datetime(2026, 6, 1, 13, 0),
        )
    ).raw_transaction
    first_bank = store.add_raw(
        raw(
            Platform.BANK,
            "first-bank",
            merchant="同额商户",
            suffix="4000",
            bank_time=datetime(2026, 6, 1, 12, 0, 1),
        )
    ).raw_transaction
    second_bank = store.add_raw(
        raw(
            Platform.BANK,
            "second-bank",
            merchant="同额商户",
            suffix="4000",
            bank_time=datetime(2026, 6, 1, 13, 0, 9),
        )
    ).raw_transaction
    ConservativeMatcher(store).generate_candidates()
    service = CandidateReviewService(store)

    assert service.confirm_exact_payment_matches("acceptance") == 1
    assert service.confirm_unique_statement_matches("acceptance") == 1
    assert store.find_canonical_for_raw(first_payment.raw_id) is not None
    assert store.find_canonical_for_raw(first_bank.raw_id) is not None
    assert store.find_canonical_for_raw(second_payment.raw_id) is not None
    assert store.find_canonical_for_raw(second_bank.raw_id) is not None


def test_exact_refund_credit_is_confirmed_once_as_refund(store):
    payment = raw(Platform.ALIPAY, "refund", merchant="高德顺风车", suffix="4000")
    payment = replace(
        payment,
        amount=payment.amount.copy_abs(),
        direction="neutral",
        description="退款-高德顺风车订单",
        status="退款成功",
    )
    bank = raw(
        Platform.BANK,
        "bank-refund",
        merchant="支付宝-高德",
        suffix="6357",
        bank_time=datetime(2026, 6, 1, 12, 0, 1),
    )
    bank = replace(
        bank,
        amount=bank.amount.copy_abs(),
        direction="income",
        description="退款",
    )
    store.add_raw(payment)
    store.add_raw(bank)
    ConservativeMatcher(store).generate_candidates()

    assert CandidateReviewService(store).confirm_exact_payment_matches("acceptance") == 1
    canonical = store.get_canonical(store.list_canonical()[0].canonical_id)
    assert canonical is not None
    assert canonical.source_count == 2
    assert canonical.tx_type.value == "refund"


def test_unique_named_bank_match_without_bank_time_is_safely_confirmed(store):
    payment = store.add_raw(
        raw(Platform.ALIPAY, "unique-payment", merchant="高德打车", suffix="5066")
    ).raw_transaction
    bank = store.add_raw(
        raw(Platform.BANK, "unique-bank", merchant="高德信息技术有限公司", suffix="5066")
    ).raw_transaction
    ConservativeMatcher(store).generate_candidates()

    confirmed = CandidateReviewService(store).confirm_unique_statement_matches("acceptance")

    assert confirmed == 1
    canonical = store.find_canonical_for_raw(payment.raw_id)
    assert canonical is not None
    assert {item.raw_transaction.raw_id for item in canonical.source_links} == {
        payment.raw_id,
        bank.raw_id,
    }


def test_equal_ambiguous_group_is_resolved_by_platform_and_statement_order(store):
    payments = []
    banks = []
    for index, minute in enumerate((5, 40), 1):
        payment = raw(
            Platform.ALIPAY,
            f"ordered-payment-{index}",
            merchant="同一商户",
            suffix="5066",
        )
        payment = replace(payment, transaction_time=datetime(2026, 6, 1, 12, minute))
        payments.append(store.add_raw(payment).raw_transaction)
        bank = raw(
            Platform.BANK,
            f"ordered-bank-{index}",
            merchant="同一商户",
            suffix="5066",
        )
        bank = replace(bank, raw_row_number=100 + index)
        banks.append(store.add_raw(bank).raw_transaction)
    ConservativeMatcher(store).generate_candidates()

    confirmed = CandidateReviewService(store).confirm_ordered_statement_matches("acceptance")

    assert confirmed == 2
    for payment, bank in zip(payments, banks):
        canonical = store.find_canonical_for_raw(payment.raw_id)
        assert canonical is not None
        assert {item.raw_transaction.raw_id for item in canonical.source_links} == {
            payment.raw_id,
            bank.raw_id,
        }
        assert "流水行序" in canonical.notes


def test_modified_confirmation_and_conflicts_are_fully_audited(store):
    store.add_raw(raw(Platform.ALIPAY, "payment", merchant="高德打车", suffix="5066"))
    store.add_raw(raw(Platform.BANK, "bank-one", merchant="高德信息技术有限公司", suffix="5066"))
    store.add_raw(raw(Platform.BANK, "bank-two", merchant="高德信息技术有限公司", suffix="5066"))
    candidates = ConservativeMatcher(store).generate_candidates()
    selected = candidates[0]
    conflict = candidates[1]
    service = CandidateReviewService(store)

    canonical, event = service.confirm(
        selected.candidate_id,
        actor="local-user",
        changes={"merchant": "人工修正商户", "category": "交通出行"},
    )

    assert canonical.merchant == "人工修正商户"
    assert canonical.category == "交通出行"
    assert event.action == "modified_confirmed"
    assert service.get_group(conflict.candidate_id).candidate.status == "superseded"
    conflict_events = service.list_events(conflict.candidate_id)
    assert len(conflict_events) == 1
    assert conflict_events[0].action == "superseded"
    assert conflict_events[0].after["selected_candidate_id"] == selected.candidate_id


def test_invalid_modification_rolls_back_without_deciding_candidate(store):
    _, _, candidate = generate_pair(store)
    service = CandidateReviewService(store)

    with pytest.raises(ValueError, match="not editable"):
        service.confirm(
            candidate.candidate_id,
            actor="local-user",
            changes={"original_row": "forbidden"},
        )

    assert store.list_canonical() == []
    assert service.get_group(candidate.candidate_id).candidate.status == "pending"
    assert service.list_events(candidate.candidate_id) == []
