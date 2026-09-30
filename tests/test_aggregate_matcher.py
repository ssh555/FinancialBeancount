from datetime import date

from beancount_dedup.aggregate_matcher import AggregateMatcher
from beancount_dedup.ledger_models import RawTransaction
from beancount_dedup.ledger_store import LedgerStore
from beancount_dedup.models import Platform


def _payment(amount: str, identity: str) -> RawTransaction:
    return RawTransaction(
        source=Platform.ALIPAY,
        source_account="支付宝",
        booking_date=date(2026, 1, 2),
        amount=amount,
        direction="expense",
        merchant=identity,
        payment_method="招商银行储蓄卡(5066)",
        transaction_id=identity,
        original_row={},
    )


def test_unique_aggregate_is_confirmed_as_one_auditable_canonical(tmp_path):
    with LedgerStore(tmp_path / "ledger.sqlite3") as store:
        first = store.add_raw(_payment("-10", "a")).raw_transaction
        second = store.add_raw(_payment("-20", "b")).raw_transaction
        bank = store.add_raw(
            RawTransaction(
                source=Platform.BANK,
                source_account="招商银行",
                booking_date=date(2026, 1, 2),
                amount="-30",
                direction="expense",
                merchant="支付宝",
                payment_method="招商银行",
                balance="70",
                transaction_id="bank",
                original_row={},
            )
        ).raw_transaction

        assert AggregateMatcher(store).confirm_unique("test") == 1
        canonical = store.find_canonical_for_raw(bank.raw_id)

        assert canonical is not None
        assert canonical.amount == bank.amount
        assert {row.raw_id for row in canonical.raw_transactions} == {
            first.raw_id,
            second.raw_id,
            bank.raw_id,
        }
        assert canonical.source_count == 3
        assert store.list_canonical_events(canonical.canonical_id)[0]["action"] == (
            "aggregate_auto_confirmed"
        )


def test_ambiguous_equal_small_rows_are_not_auto_confirmed(tmp_path):
    with LedgerStore(tmp_path / "ledger.sqlite3") as store:
        for identity in ("fee-a", "fee-b"):
            store.add_raw(_payment("-0.76", identity))
        store.add_raw(_payment("-7.80", "purchase"))
        store.add_raw(
            RawTransaction(
                source=Platform.BANK,
                source_account="招商银行",
                booking_date=date(2026, 1, 2),
                amount="-8.56",
                direction="expense",
                balance="70",
                transaction_id="bank",
                original_row={},
            )
        )

        candidates = AggregateMatcher(store).generate_candidates()

        assert len(candidates) == 2
        assert not any(item.is_unique for item in candidates)
        assert AggregateMatcher(store).confirm_unique("test") == 0
        assert store.list_canonical() == []
