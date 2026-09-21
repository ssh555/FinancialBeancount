"""Persistence tests for list, detail, re-import, and unlink behavior."""

import sqlite3
from datetime import date, datetime
from decimal import Decimal

import pytest
from beancount_dedup.ledger_models import CanonicalTransaction, RawTransaction, ReviewStatus
from beancount_dedup.ledger_store import LedgerStore
from beancount_dedup.models import Platform, TransactionType


@pytest.fixture
def store(tmp_path):
    with LedgerStore(tmp_path / "ledger.sqlite3") as ledger_store:
        yield ledger_store


def make_raw(
    source: Platform,
    transaction_id: str,
    *,
    import_batch_id: str | None = None,
) -> RawTransaction:
    return RawTransaction(
        source=source,
        source_account="private-account-token",
        transaction_time=datetime(2026, 3, 1, 11, 31, 44),
        booking_date=date(2026, 3, 1),
        amount="-57.96",
        direction="expense",
        merchant="高德打车" if source == Platform.ALIPAY else "高德信息技术有限公司",
        payment_method="工商银行储蓄卡(4000)" if source == Platform.ALIPAY else "快捷支付",
        bank_card_suffix="4000",
        transaction_id=transaction_id,
        import_batch_id=import_batch_id,
        source_file="redacted-statement",
        source_file_hash="source-file-hash",
        raw_row_number=8,
        original_row={"amount": "57.96", "redacted": True},
    )


def make_canonical() -> CanonicalTransaction:
    return CanonicalTransaction(
        transaction_time=datetime(2026, 3, 1, 11, 31, 44),
        booking_date=date(2026, 3, 1),
        amount=Decimal("-57.96"),
        direction="expense",
        merchant="高德打车",
        normalized_merchant="高德",
        category="交通出行",
        payment_channel="支付宝",
        funding_account="工商银行储蓄卡(4000)",
        tx_type=TransactionType.EXPENSE,
        review_status=ReviewStatus.AUTO_CONFIRMED,
    )


def test_import_batch_is_idempotent_by_file_hash(store):
    first, first_created = store.start_import_batch(
        Platform.ALIPAY, "statement.csv", "same-content-hash"
    )
    second, second_created = store.start_import_batch(
        Platform.ALIPAY, "renamed-statement.csv", "same-content-hash"
    )

    assert first_created is True
    assert second_created is False
    assert first.batch_id == second.batch_id


def test_raw_import_is_idempotent_by_source_identity(store):
    first = make_raw(Platform.ALIPAY, "same-order")
    repeated = make_raw(Platform.ALIPAY, "same-order")

    first_result = store.add_raw(first)
    repeated_result = store.add_raw(repeated)

    assert first_result.created is True
    assert repeated_result.created is False
    assert repeated_result.raw_transaction.raw_id == first.raw_id


def test_overlapping_bank_export_only_adds_new_observations(store):
    partial_batch, _ = store.start_import_batch(Platform.BANK, "jan-sep.pdf", "partial-hash")
    annual_batch, _ = store.start_import_batch(Platform.BANK, "jan-dec.pdf", "annual-hash")

    def bank_row(
        identity: str,
        balance: str,
        file_hash: str,
        row_number: int,
        batch_id: str,
    ):
        raw = make_raw(Platform.BANK, identity)
        return RawTransaction(
            **{
                **raw.__dict__,
                "transaction_id": None,
                "balance": balance,
                "source_file_hash": file_hash,
                "raw_row_number": row_number,
                "import_batch_id": batch_id,
            }
        )

    partial = [
        bank_row("ignored-a", "980.00", "partial-hash", 10, partial_batch.batch_id),
        bank_row("ignored-b", "950.00", "partial-hash", 11, partial_batch.batch_id),
    ]
    annual = [
        bank_row("ignored-a", "980.00", "annual-hash", 210, annual_batch.batch_id),
        bank_row("ignored-b", "950.00", "annual-hash", 211, annual_batch.batch_id),
        bank_row("ignored-c", "900.00", "annual-hash", 212, annual_batch.batch_id),
    ]

    first = store.add_raws(partial)
    second = store.add_raws(annual)

    assert [item.created for item in first] == [True, True]
    assert [item.created for item in second] == [False, False, True]
    assert len(store.list_unlinked_raw()) == 3
    annual_occurrences = store.list_import_occurrences(annual_batch.batch_id)
    assert len(annual_occurrences) == 3
    assert [item.created for item in annual_occurrences] == [False, False, True]
    assert [item.observed["raw_row_number"] for item in annual_occurrences] == [210, 211, 212]
    assert all(item.observed["source_file_hash"] == "annual-hash" for item in annual_occurrences)


def test_import_coverage_lists_prior_rows_missing_from_new_file(store):
    old_batch, _ = store.start_import_batch(Platform.BANK, "old.pdf", "old-hash")
    new_batch, _ = store.start_import_batch(Platform.BANK, "new.pdf", "new-hash")

    def observation(day: int, balance: str, batch_id: str, file_hash: str):
        template = make_raw(Platform.BANK, f"ignored-{day}-{balance}")
        return RawTransaction(
            **{
                **template.__dict__,
                "transaction_id": None,
                "booking_date": date(2026, 1, day),
                "transaction_time": None,
                "balance": balance,
                "import_batch_id": batch_id,
                "source_file_hash": file_hash,
                "raw_row_number": day,
            }
        )

    old_results = store.add_raws(
        [
            observation(1, "990", old_batch.batch_id, "old-hash"),
            observation(2, "980", old_batch.batch_id, "old-hash"),
            observation(3, "970", old_batch.batch_id, "old-hash"),
        ]
    )
    new_results = store.add_raws(
        [
            observation(1, "990", new_batch.batch_id, "new-hash"),
            observation(3, "970", new_batch.batch_id, "new-hash"),
        ]
    )
    run_id = new_results[0].import_run_id
    assert run_id is not None

    report = store.analyze_import_coverage(new_batch.batch_id, run_id)

    assert report.occurrence_count == 2
    assert report.existing_count == 2
    assert report.missing_raw_ids == (old_results[1].raw_transaction.raw_id,)


def test_same_file_reimports_have_separate_run_ids(store):
    batch, _ = store.start_import_batch(Platform.ALIPAY, "same.csv", "same-hash")
    raw = make_raw(Platform.ALIPAY, "same-order")
    observed = RawTransaction(**{**raw.__dict__, "import_batch_id": batch.batch_id})

    first = store.add_raws([observed])[0]
    second = store.add_raws([observed])[0]

    assert first.import_run_id != second.import_run_id
    assert first.import_run_id is not None
    assert second.import_run_id is not None
    assert len(store.list_import_occurrences(batch.batch_id, first.import_run_id)) == 1
    assert len(store.list_import_occurrences(batch.batch_id, second.import_run_id)) == 1


def test_list_has_one_transaction_and_detail_has_two_sources(store):
    canonical = make_canonical()
    alipay = store.add_raw(make_raw(Platform.ALIPAY, "alipay-order")).raw_transaction
    bank = store.add_raw(make_raw(Platform.BANK, "bank-reference")).raw_transaction
    canonical.add_source(
        alipay,
        confidence="1",
        reasons=["transaction_id_exact"],
        matcher_version="test-v1",
    )
    canonical.add_source(
        bank,
        confidence="0.99",
        reasons=["amount_exact", "datetime_exact", "bank_suffix_exact"],
        matcher_version="test-v1",
    )
    store.add_canonical(canonical)

    list_rows = store.list_canonical()
    detail = store.get_canonical(canonical.canonical_id)

    assert len(list_rows) == 1
    assert list_rows[0].source_count == 0
    assert detail is not None
    assert detail.source_count == 2
    assert {raw.source for raw in detail.raw_transactions} == {Platform.ALIPAY, Platform.BANK}


def test_canonical_page_filters_and_counts_without_loading_full_ledger(store):
    matching = make_canonical()
    matching.category = "交通出行"
    matching.notes = "机场行程"
    other = make_canonical()
    other.booking_date = date(2025, 1, 1)
    other.merchant = "早餐商户"
    other.category = "餐饮"
    store.add_canonical(matching)
    store.add_canonical(other)

    rows, total = store.list_canonical_page(
        limit=20,
        offset=0,
        date_from=date(2026, 1, 1),
        date_to=date(2026, 12, 31),
        direction="expense",
        category="交通出行",
        search="机场",
    )

    assert total == 1
    assert [item.canonical_id for item in rows] == [matching.canonical_id]


def test_canonical_page_rejects_reversed_date_range(store):
    with pytest.raises(ValueError, match="date_from"):
        store.list_canonical_page(
            limit=20,
            offset=0,
            date_from=date(2026, 2, 1),
            date_to=date(2026, 1, 1),
        )


def test_unlink_keeps_raw_record_available(store):
    raw = store.add_raw(make_raw(Platform.BANK, "bank-reference")).raw_transaction
    canonical = make_canonical()
    canonical.add_source(
        raw,
        confidence="0.7",
        reasons=["manual_candidate"],
        matcher_version="test-v1",
    )
    store.add_canonical(canonical)

    assert store.unlink_source(canonical.canonical_id, raw.raw_id) is True
    detail = store.get_canonical(canonical.canonical_id)
    repeated_import = store.add_raw(make_raw(Platform.BANK, "bank-reference"))

    assert detail is not None
    assert detail.source_count == 0
    assert repeated_import.created is False
    assert repeated_import.raw_transaction.raw_id == raw.raw_id


def test_one_raw_record_cannot_link_to_two_canonical_transactions(store):
    raw = store.add_raw(make_raw(Platform.ALIPAY, "single-owner")).raw_transaction
    first = make_canonical()
    second = make_canonical()
    first.add_source(
        raw,
        confidence="1",
        reasons=["confirmed"],
        matcher_version="test-v1",
    )
    second.add_source(
        raw,
        confidence="1",
        reasons=["confirmed"],
        matcher_version="test-v1",
    )
    store.add_canonical(first)

    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
        store.add_canonical(second)

    assert store.get_canonical(second.canonical_id) is None


def test_database_reopen_restores_canonical_and_all_sources(tmp_path):
    database_path = tmp_path / "persistent-ledger.sqlite3"
    canonical = make_canonical()
    with LedgerStore(database_path) as first_session:
        alipay = first_session.add_raw(make_raw(Platform.ALIPAY, "alipay-order")).raw_transaction
        bank = first_session.add_raw(make_raw(Platform.BANK, "bank-reference")).raw_transaction
        canonical.add_source(
            alipay,
            confidence="1",
            reasons=["transaction_id_exact"],
            matcher_version="test-v1",
        )
        canonical.add_source(
            bank,
            confidence="0.99",
            reasons=["amount_exact", "bank_suffix_exact"],
            matcher_version="test-v1",
        )
        first_session.add_canonical(canonical)

    with LedgerStore(database_path) as second_session:
        restored = second_session.get_canonical(canonical.canonical_id)

    assert restored is not None
    assert restored.source_count == 2
    bank_link = next(
        link for link in restored.source_links if link.raw_transaction.source == Platform.BANK
    )
    assert bank_link.reasons == ("amount_exact", "bank_suffix_exact")
