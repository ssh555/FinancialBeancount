"""Tests for review-first non-consumption classification."""

from datetime import date

import pytest
from beancount_dedup.ledger_models import CanonicalTransaction
from beancount_dedup.ledger_store import LedgerStore
from beancount_dedup.models import TransactionType
from beancount_dedup.transaction_classification import TransactionClassificationService


@pytest.fixture
def store(tmp_path):
    with LedgerStore(tmp_path / "ledger.sqlite3") as ledger_store:
        yield ledger_store


def transaction(description: str, amount: str = "-100"):
    return CanonicalTransaction(
        transaction_time=None,
        booking_date=date(2026, 3, 1),
        amount=amount,
        direction="expense" if amount.startswith("-") else "income",
        merchant=description,
        tx_type=TransactionType.EXPENSE if amount.startswith("-") else TransactionType.INCOME,
    )


@pytest.mark.parametrize(
    ("description", "expected_type", "expected_category"),
    [
        ("微信零钱充值", TransactionType.TRANSFER, "账户内部转移"),
        ("招商银行信用卡还款", TransactionType.TRANSFER, "信用卡还款"),
        ("朝朝宝转入", TransactionType.INVESTMENT, "理财资产转移"),
        ("酒店预授权撤销", TransactionType.PREAUTHORIZATION, "酒店预授权"),
    ],
)
def test_explicit_keywords_generate_review_candidates(
    store, description, expected_type, expected_category
):
    item = transaction(description)
    store.add_canonical(item)

    candidates = TransactionClassificationService(store).generate_candidates()

    assert len(candidates) == 1
    assert candidates[0].proposed_type == expected_type
    assert candidates[0].proposed_category == expected_category
    assert candidates[0].status == "pending"


def test_generic_external_transfer_is_not_automatically_classified(store):
    store.add_canonical(transaction("转账给张三"))

    assert TransactionClassificationService(store).generate_candidates() == []


def test_confirm_updates_type_and_category_with_audit(store):
    item = transaction("基金赎回", amount="100")
    store.add_canonical(item)
    service = TransactionClassificationService(store)
    candidate = service.generate_candidates()[0]

    event = service.confirm(candidate.candidate_id, "local-user")

    updated = store.get_canonical(item.canonical_id)
    assert updated is not None
    assert updated.tx_type == TransactionType.INVESTMENT
    assert updated.category == "理财资产转移"
    assert event.before["tx_type"] == "income"
    assert event.after["tx_type"] == "investment"
    assert service.list_events(candidate.candidate_id) == [event]


def test_reject_preserves_original_transaction_type(store):
    item = transaction("余额提现", amount="100")
    store.add_canonical(item)
    service = TransactionClassificationService(store)
    candidate = service.generate_candidates()[0]

    event = service.reject(candidate.candidate_id, "local-user")

    updated = store.get_canonical(item.canonical_id)
    assert updated is not None
    assert updated.tx_type == TransactionType.INCOME
    assert event.action == "rejected"
    assert service.get_candidate(candidate.candidate_id).status == "rejected"


def test_confirmed_non_consumption_is_not_proposed_again(store):
    item = transaction("零钱充值")
    store.add_canonical(item)
    service = TransactionClassificationService(store)
    candidate = service.generate_candidates()[0]
    service.confirm(candidate.candidate_id, "local-user")

    assert service.generate_candidates() == []
