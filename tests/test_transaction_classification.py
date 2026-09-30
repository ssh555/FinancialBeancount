"""Tests for review-first non-consumption classification."""

from datetime import date

import pytest
from beancount_dedup.ledger_models import CanonicalTransaction, RawTransaction
from beancount_dedup.ledger_store import LedgerStore
from beancount_dedup.models import Platform, TransactionType
from beancount_dedup.transaction_classification import TransactionClassificationService


@pytest.fixture
def store(tmp_path):
    with LedgerStore(tmp_path / "ledger.sqlite3") as ledger_store:
        yield ledger_store


def transaction(description: str, amount: str = "-100", **changes):
    values = {
        "transaction_time": None,
        "booking_date": date(2026, 3, 1),
        "amount": amount,
        "direction": "expense" if amount.startswith("-") else "income",
        "merchant": description,
        "tx_type": TransactionType.EXPENSE if amount.startswith("-") else TransactionType.INCOME,
    }
    values.update(changes)
    return CanonicalTransaction(
        **values,
    )


@pytest.mark.parametrize(
    ("description", "expected_type", "expected_category"),
    [
        ("微信零钱充值", TransactionType.TRANSFER, "账户内部转移"),
        ("招商银行信用卡还款", TransactionType.TRANSFER, "信用卡还款"),
        ("朝朝宝转入", TransactionType.INVESTMENT, "理财资产转移"),
        ("酒店预授权撤销", TransactionType.PREAUTHORIZATION, "酒店预授权"),
        ("充值完成", TransactionType.TRANSFER, "账户内部转移"),
        ("提现已到账", TransactionType.TRANSFER, "账户内部转移"),
        ("交易关闭", TransactionType.PREAUTHORIZATION, "未发生或已关闭交易"),
        ("退款成功", TransactionType.REFUND, "退款"),
        ("因公付(携程商旅)", TransactionType.TRANSFER, "企业支付（非个人收支）"),
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


def test_wallet_to_bank_movement_is_an_internal_transfer(store):
    store.add_canonical(
        transaction(
            "招商银行",
            amount="5000",
            tx_type=TransactionType.UNKNOWN,
            direction="neutral",
            payment_channel="alipay",
            funding_account="余额",
            status="交易成功",
        )
    )

    candidate = TransactionClassificationService(store).generate_candidates()[0]

    assert candidate.proposed_type == TransactionType.TRANSFER
    assert candidate.proposed_category == "支付账户与银行卡互转"


def test_internal_fund_purchase_is_not_consumption_but_external_fund_stays_expense(store):
    internal = transaction("本人")
    internal.add_source(
        RawTransaction(
            source=Platform.BANK,
            source_account="工商银行",
            booking_date=date(2026, 9, 1),
            amount="-1802.05",
            direction="expense",
            merchant="本人",
            counterparty="本人",
            description="基金购买",
            original_row={"kind": "internal"},
        ),
        confidence="1",
        reasons=["statement"],
        matcher_version="test",
    )
    external = transaction("上海天天基金销售有限公司", amount="-6000")
    external.add_source(
        RawTransaction(
            source=Platform.BANK,
            source_account="工商银行",
            booking_date=date(2026, 9, 7),
            amount="-6000",
            direction="expense",
            merchant="上海天天基金销售有限公司",
            counterparty="上海天天基金销售有限公司",
            description="天天9074959683",
            original_row={"kind": "external"},
        ),
        confidence="1",
        reasons=["statement"],
        matcher_version="test",
    )
    for item in (*internal.source_links, *external.source_links):
        store.add_raw(item.raw_transaction)
    store.add_canonical(internal)
    store.add_canonical(external)

    candidates = TransactionClassificationService(store).generate_candidates()

    assert len(candidates) == 1
    assert candidates[0].canonical_id == internal.canonical_id
    assert candidates[0].proposed_category == "银行内部理财转移"


def test_bank_backed_closed_platform_order_remains_a_real_expense(store):
    item = transaction("交易关闭", status="交易关闭")
    bank = RawTransaction(
        source=Platform.BANK,
        source_account="招商银行",
        booking_date=date(2026, 3, 1),
        amount="-100",
        direction="expense",
        description="快捷支付",
        original_row={"kind": "bank-debit"},
    )
    store.add_raw(bank)
    item.add_source(bank, confidence="1", reasons=("statement",), matcher_version="test")
    store.add_canonical(item)

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


def test_high_confidence_keyword_classifications_can_be_confirmed_in_batch(store):
    item = transaction("微信零钱充值")
    store.add_canonical(item)
    service = TransactionClassificationService(store)
    service.generate_candidates()

    assert service.confirm_high_confidence("acceptance") == 1
    assert store.get_canonical(item.canonical_id).tx_type == TransactionType.TRANSFER


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
