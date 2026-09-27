from datetime import date
from pathlib import Path

from beancount_dedup.ledger_models import RawTransaction
from beancount_dedup.ledger_store import LedgerStore
from beancount_dedup.models import Platform
from scripts.audit_complete_ledger import audit_database


def test_audit_flags_same_balance_and_counterparty_without_mutation(tmp_path: Path) -> None:
    database = tmp_path / "ledger.sqlite3"
    with LedgerStore(database) as store:
        for identity, row_number in (("one", 10), ("two", 12)):
            store.add_raw(
                RawTransaction(
                    source=Platform.BANK,
                    source_account="测试银行",
                    transaction_time=None,
                    booking_date=date(2026, 1, 1),
                    amount="-100",
                    direction="expense",
                    merchant="同一商户",
                    counterparty="同一商户",
                    description="转账汇款",
                    balance="500",
                    transaction_id=identity,
                    source_file="statement.pdf",
                    raw_row_number=row_number,
                    original_row={"identity": identity},
                )
            )

    report = audit_database(database)

    assert report["read_only"] is True
    assert report["bank_balance_collisions"]["group_count"] == 1
    assert report["bank_balance_collisions"]["high_priority_count"] == 1
    assert report["bank_balance_collisions"]["groups"][0]["row_count"] == 2
    with LedgerStore(database) as store:
        assert store.connection.total_changes == 0
        assert store.connection.execute("SELECT COUNT(*) FROM raw_transactions").fetchone()[0] == 2


def test_audit_downgrades_repeated_rows_separated_by_reversal(tmp_path: Path) -> None:
    database = tmp_path / "ledger.sqlite3"
    with LedgerStore(database) as store:
        for identity, amount, balance, row_number in (
            ("out-one", "-100", "500", 10),
            ("return", "100", "600", 11),
            ("out-two", "-100", "500", 12),
        ):
            store.add_raw(
                RawTransaction(
                    source=Platform.BANK,
                    source_account="测试银行",
                    transaction_time=None,
                    booking_date=date(2026, 1, 1),
                    amount=amount,
                    direction="expense" if amount.startswith("-") else "income",
                    merchant="同一商户",
                    counterparty="同一商户",
                    description="转账汇款" if amount.startswith("-") else "转账退回",
                    balance=balance,
                    transaction_id=identity,
                    source_file="statement.pdf",
                    raw_row_number=row_number,
                    original_row={"identity": identity},
                )
            )

    report = audit_database(database)
    group = report["bank_balance_collisions"]["groups"][0]

    assert group["interleaved_reversal"] is True
    assert group["priority"] == "review"
    assert report["bank_balance_collisions"]["high_priority_count"] == 0
