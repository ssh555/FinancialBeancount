"""Tests for grouped duplicate-candidate review and audit history."""

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


def raw(source: Platform, identity: str, *, merchant: str, suffix: str | None):
    return RawTransaction(
        source=source,
        source_account=f"account-{identity}",
        transaction_time=datetime(2026, 6, 1, 12, 0) if source != Platform.BANK else None,
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
