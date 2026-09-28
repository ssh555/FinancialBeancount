from datetime import date

from beancount_dedup.balance_reconciliation import BalanceReconciliationService
from beancount_dedup.ledger_models import RawTransaction
from beancount_dedup.ledger_store import LedgerStore
from beancount_dedup.models import Platform


def _row(identity: str, amount: str, balance: str, row_number: int) -> RawTransaction:
    return RawTransaction(
        source=Platform.BANK,
        source_account="招商银行",
        booking_date=date(2026, 7, 1),
        amount=amount,
        direction="income" if not amount.startswith("-") else "expense",
        merchant=identity,
        description=identity,
        balance=balance,
        transaction_id=identity,
        raw_row_number=row_number,
        original_row={"identity": identity},
    )


def test_reconciliation_reports_verified_transitions_and_exact_breaks(tmp_path):
    with LedgerStore(tmp_path / "ledger.sqlite3") as store:
        for row in (
            _row("opening", "100", "100", 1),
            _row("purchase", "-20", "80", 2),
            _row("impossible-second-purchase", "-20", "80", 3),
        ):
            store.add_raw(row)

        report = BalanceReconciliationService(store).summarize()

    assert report["anchored_account_count"] == 1
    assert report["anchored_row_count"] == 3
    assert report["verified_transition_count"] == 1
    assert report["break_count"] == 1
    broken = report["accounts"][0]["breaks"][0]
    assert broken["expected_balance"] == "60"
    assert broken["actual_balance"] == "80"
    assert broken["difference"] == "20"
