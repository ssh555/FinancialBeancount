"""Tests for canonical-only statistics and refund accounting."""

from datetime import date

import pytest
from beancount_dedup.ledger_models import CanonicalTransaction
from beancount_dedup.ledger_store import LedgerStore
from beancount_dedup.models import TransactionType
from beancount_dedup.refund_relationships import RefundRelationshipService
from beancount_dedup.statistics import StatisticsService
from beancount_dedup.transaction_classification import TransactionClassificationService


@pytest.fixture
def store(tmp_path):
    with LedgerStore(tmp_path / "ledger.sqlite3") as ledger_store:
        yield ledger_store


def transaction(day: int, amount: str, merchant: str, tx_type: TransactionType, category=""):
    return CanonicalTransaction(
        transaction_time=None,
        booking_date=date(2026, 3, day),
        amount=amount,
        direction="expense" if amount.startswith("-") else "income",
        merchant=merchant,
        category=category,
        tx_type=tx_type,
        status="退款成功" if "退款" in merchant else "",
    )


def test_statistics_use_canonical_transactions_and_net_confirmed_refunds(store):
    expense = transaction(1, "-100", "星巴克", TransactionType.EXPENSE, "餐饮")
    income = transaction(2, "1000", "工资", TransactionType.INCOME, "工资")
    refund = transaction(5, "30", "星巴克退款", TransactionType.INCOME)
    transfer = transaction(6, "-500", "信用卡还款", TransactionType.TRANSFER, "信用卡还款")
    investment = transaction(7, "-200", "基金申购", TransactionType.INVESTMENT, "理财资产转移")
    for item in (expense, income, refund, transfer, investment):
        store.add_canonical(item)
    refund_service = RefundRelationshipService(store)
    refund_candidate = refund_service.generate_candidates()[0]
    refund_service.confirm(refund_candidate.relationship_id, "local-user")

    report = StatisticsService(store).summarize()

    assert report.gross_expense == 100
    assert report.refunds == 30
    assert report.net_expense == 70
    assert report.ordinary_income == 1000
    assert report.net_cash_flow == 930
    assert report.expense_count == 1
    assert report.income_count == 1
    assert report.refund_count == 1
    assert report.excluded_non_consumption_count == 2
    assert report.categories[0].to_dict() == {
        "category": "餐饮",
        "gross_expense": "100",
        "refunds": "30",
        "net_expense": "70",
    }


def test_pending_refund_and_transfer_candidates_are_excluded_until_review(store):
    expense = transaction(1, "-100", "星巴克", TransactionType.EXPENSE, "餐饮")
    refund = transaction(5, "100", "星巴克退款", TransactionType.INCOME)
    possible_transfer = transaction(6, "-500", "招商银行信用卡还款", TransactionType.EXPENSE)
    for item in (expense, refund, possible_transfer):
        store.add_canonical(item)
    RefundRelationshipService(store).generate_candidates()
    TransactionClassificationService(store).generate_candidates()

    report = StatisticsService(store).summarize()

    assert report.gross_expense == 100
    assert report.ordinary_income == 0
    assert report.refunds == 0
    assert report.pending_review_excluded_count == 2


def test_statistics_date_filter_applies_to_cash_flow_and_refund_date(store):
    old_expense = transaction(1, "-100", "星巴克", TransactionType.EXPENSE, "餐饮")
    refund = transaction(5, "100", "星巴克退款", TransactionType.INCOME)
    april_income = CanonicalTransaction(
        transaction_time=None,
        booking_date=date(2026, 4, 1),
        amount="500",
        direction="income",
        merchant="工资",
        tx_type=TransactionType.INCOME,
    )
    store.add_canonical(old_expense)
    store.add_canonical(refund)
    store.add_canonical(april_income)
    service = RefundRelationshipService(store)
    service.confirm(service.generate_candidates()[0].relationship_id, "local-user")

    march = StatisticsService(store).summarize(date(2026, 3, 4), date(2026, 3, 31))
    april = StatisticsService(store).summarize(date(2026, 4, 1), date(2026, 4, 30))

    assert march.gross_expense == 0
    assert march.refunds == 100
    assert march.net_cash_flow == 100
    assert april.ordinary_income == 500
    assert april.refunds == 0


def test_reversed_statistics_range_is_rejected(store):
    with pytest.raises(ValueError, match="date_from"):
        StatisticsService(store).summarize(date(2026, 4, 1), date(2026, 3, 1))
