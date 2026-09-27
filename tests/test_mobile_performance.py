from datetime import date, timedelta
from pathlib import Path

from beancount_dedup.ledger_models import CanonicalTransaction
from beancount_dedup.ledger_store import LedgerStore
from beancount_dedup.models import TransactionType
from scripts.benchmark_mobile import benchmark_database


def test_mobile_performance_gate_exercises_primary_read_paths(tmp_path: Path) -> None:
    database = tmp_path / "ledger.sqlite3"
    with LedgerStore(database) as store:
        for index in range(100):
            store.add_canonical(
                CanonicalTransaction(
                    transaction_time=None,
                    booking_date=date(2026, 1, 1) + timedelta(days=index % 30),
                    amount="-10.00",
                    direction="expense",
                    merchant=f"支付测试 {index}",
                    tx_type=TransactionType.EXPENSE,
                )
            )

    report = benchmark_database(
        database,
        iterations=1,
        limits_ms={
            name: 10_000
            for name in (
                "overview_summary",
                "overview_timeline",
                "transaction_first_page",
                "transaction_search",
            )
        },
    )

    assert report["success"] is True
    assert set(report["results"]) == {
        "overview_summary",
        "overview_timeline",
        "transaction_first_page",
        "transaction_search",
    }
