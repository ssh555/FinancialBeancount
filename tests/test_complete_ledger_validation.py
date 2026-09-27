from datetime import date
from pathlib import Path

from beancount_dedup.ledger_models import CanonicalTransaction
from beancount_dedup.ledger_store import LedgerStore
from beancount_dedup.models import TransactionType
from scripts.validate_complete_ledger import validate_database


def test_complete_ledger_validation_checks_period_conservation(tmp_path: Path) -> None:
    database = tmp_path / "ledger.sqlite3"
    with LedgerStore(database) as store:
        store.add_canonical(
            CanonicalTransaction(
                transaction_time=None,
                booking_date=date(2025, 12, 31),
                amount="-20",
                direction="expense",
                merchant="年末消费",
                tx_type=TransactionType.EXPENSE,
            )
        )
        store.add_canonical(
            CanonicalTransaction(
                transaction_time=None,
                booking_date=date(2026, 1, 1),
                amount="100",
                direction="income",
                merchant="年初收入",
                tx_type=TransactionType.INCOME,
            )
        )

    report = validate_database(database)

    assert report["success"] is True
    assert report["date_from"] == "2025-12-31"
    assert report["date_to"] == "2026-01-01"
    assert report["canonical_count"] == 2
    assert report["checks"]["gross_expense_matches_years"] is True
    assert report["checks"]["ordinary_income_matches_years"] is True
