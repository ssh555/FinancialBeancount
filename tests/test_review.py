"""Tests for complete batch review, modification, and audit history."""

from datetime import date, datetime

import pytest
from beancount_dedup.ledger_models import CanonicalTransaction, RawTransaction
from beancount_dedup.ledger_store import LedgerStore
from beancount_dedup.models import Platform
from beancount_dedup.review import ImportReviewService


def make_raw(transaction_id: str) -> RawTransaction:
    return RawTransaction(
        source=Platform.ALIPAY,
        source_account="private-token",
        transaction_time=datetime(2026, 6, 1, 12, 0),
        booking_date=date(2026, 6, 1),
        amount="-20.00",
        direction="expense",
        merchant="脱敏商户",
        transaction_id=transaction_id,
        original_row={"redacted": True},
    )


@pytest.fixture
def store(tmp_path):
    with LedgerStore(tmp_path / "ledger.sqlite3") as ledger_store:
        yield ledger_store


def start_batch(store):
    batch, _ = store.start_import_batch(Platform.ALIPAY, "statement.csv", "file-hash")
    return batch


def test_review_includes_new_and_existing_rows(store):
    batch = start_batch(store)
    first = store.add_raw(make_raw("existing-order"))
    repeated = store.add_raw(make_raw("existing-order"))
    new = store.add_raw(make_raw("new-order"))

    session = ImportReviewService(store).create_session(batch.batch_id, [repeated, new])
    items = ImportReviewService(store).list_items(session.session_id)

    assert first.created is True
    assert {item.item_type for item in items} == {"existing_unmatched", "new_unmatched"}
    assert all(item.status == "pending" for item in items)


def test_existing_overlap_review_preserves_current_file_occurrence(store):
    first = make_raw("overlapping-order")
    store.add_raw(first)
    batch = start_batch(store)
    annual_observation = RawTransaction(
        **{
            **first.__dict__,
            "import_batch_id": batch.batch_id,
            "source_file": "annual-statement.csv",
            "source_file_hash": "annual-file-hash",
            "raw_row_number": 999,
        }
    )
    result = store.add_raw(annual_observation)

    session = ImportReviewService(store).create_session(batch.batch_id, [result])
    item = ImportReviewService(store).list_items(session.session_id)[0]

    assert result.created is False
    assert item.snapshot["persisted_raw"]["source_file"] == ""
    assert item.snapshot["imported_observation"]["source_file"] == "annual-statement.csv"
    assert item.snapshot["imported_observation"]["raw_row_number"] == 999


def test_coverage_gap_is_a_separate_human_review_item(store):
    batch = start_batch(store)
    current = store.add_raw(make_raw("current-order"))
    missing = store.add_raw(make_raw("missing-order")).raw_transaction

    session = ImportReviewService(store).create_session(
        batch.batch_id, [current], missing_from_import=[missing]
    )
    items = ImportReviewService(store).list_items(session.session_id)
    gap = next(item for item in items if item.item_type == "existing_missing_from_import")

    assert gap.raw_transaction.raw_id == missing.raw_id
    assert gap.snapshot["missing_from_import"] is True
    assert gap.snapshot["imported_observation"] is None


def test_confirming_unmatched_record_creates_single_source_canonical(store):
    batch = start_batch(store)
    result = store.add_raw(make_raw("standalone-order"))
    service = ImportReviewService(store)
    session = service.create_session(batch.batch_id, [result])
    item = service.list_items(session.session_id)[0]

    event = service.decide(item.review_item_id, "confirmed", actor="local-user")

    canonical = store.find_canonical_for_raw(result.raw_transaction.raw_id)
    refreshed = service.get_item(item.review_item_id)
    assert canonical is not None
    assert canonical.source_count == 1
    assert canonical.source_links[0].reasons == ("human_confirmed_unmatched",)
    assert canonical.tx_type.value == "expense"
    assert refreshed.canonical_transaction is not None
    assert event.before["canonical"] is None
    assert event.after["canonical"]["canonical_id"] == canonical.canonical_id


def test_modifying_unmatched_record_creates_corrected_canonical_atomically(store):
    batch = start_batch(store)
    result = store.add_raw(make_raw("corrected-standalone"))
    service = ImportReviewService(store)
    session = service.create_session(batch.batch_id, [result])
    item = service.list_items(session.session_id)[0]

    event = service.modify_canonical(
        item.review_item_id,
        {"merchant": "人工修正商户", "category": "餐饮"},
        actor="local-user",
    )

    canonical = store.find_canonical_for_raw(result.raw_transaction.raw_id)
    assert canonical is not None
    assert canonical.merchant == "人工修正商户"
    assert canonical.category == "餐饮"
    assert event.action == "modified"
    assert event.after["canonical"]["source_count"] == 1


def test_existing_linked_item_shows_all_historical_sources(store):
    batch = start_batch(store)
    imported = store.add_raw(make_raw("imported-order"))
    historical = store.add_raw(make_raw("historical-order"))
    canonical = CanonicalTransaction(
        transaction_time=datetime(2026, 6, 1, 12, 0),
        booking_date=date(2026, 6, 1),
        amount="-20.00",
        direction="expense",
        merchant="脱敏商户",
    )
    for result in (imported, historical):
        canonical.add_source(
            result.raw_transaction,
            confidence="1",
            reasons=["manual_confirmed"],
            matcher_version="test-v1",
        )
    store.add_canonical(canonical)
    repeated = store.add_raw(make_raw("imported-order"))

    session = ImportReviewService(store).create_session(batch.batch_id, [repeated])
    item = ImportReviewService(store).list_items(session.session_id)[0]

    assert item.item_type == "existing_linked"
    assert item.canonical_transaction is not None
    assert item.canonical_transaction.source_count == 2
    assert len(item.snapshot["affected_canonical"]["sources"]) == 2


def test_human_modification_updates_canonical_and_writes_audit_event(store):
    batch = start_batch(store)
    raw_result = store.add_raw(make_raw("linked-order"))
    canonical = CanonicalTransaction(
        transaction_time=datetime(2026, 6, 1, 12, 0),
        booking_date=date(2026, 6, 1),
        amount="-20.00",
        direction="expense",
        merchant="修改前商户",
        category="未分类",
    )
    canonical.add_source(
        raw_result.raw_transaction,
        confidence="0.7",
        reasons=["candidate"],
        matcher_version="test-v1",
    )
    store.add_canonical(canonical)
    session = ImportReviewService(store).create_session(batch.batch_id, [raw_result])
    service = ImportReviewService(store)
    item = service.list_items(session.session_id)[0]

    event = service.modify_canonical(
        item.review_item_id,
        {"merchant": "修改后商户", "category": "交通出行"},
        actor="local-user",
    )
    updated = store.get_canonical(canonical.canonical_id)
    events = service.list_events(item.review_item_id)

    assert updated is not None
    assert updated.merchant == "修改后商户"
    assert updated.category == "交通出行"
    assert event.before["canonical"]["merchant"] == "修改前商户"
    assert event.after["canonical"]["merchant"] == "修改后商户"
    assert events == [event]


def test_raw_fields_cannot_be_modified_through_review(store):
    batch = start_batch(store)
    raw_result = store.add_raw(make_raw("linked-order"))
    session = ImportReviewService(store).create_session(batch.batch_id, [raw_result])
    item = ImportReviewService(store).list_items(session.session_id)[0]

    with pytest.raises(ValueError, match="not editable"):
        ImportReviewService(store).modify_canonical(
            item.review_item_id,
            {"original_row": "forbidden"},
            actor="local-user",
        )

    assert store.find_canonical_for_raw(raw_result.raw_transaction.raw_id) is None


def test_failed_modification_leaves_canonical_and_review_pending(store):
    batch = start_batch(store)
    raw_result = store.add_raw(make_raw("linked-order"))
    canonical = CanonicalTransaction(
        transaction_time=datetime(2026, 6, 1, 12, 0),
        booking_date=date(2026, 6, 1),
        amount="-20.00",
        direction="expense",
        merchant="原商户",
    )
    canonical.add_source(
        raw_result.raw_transaction,
        confidence="1",
        reasons=["confirmed"],
        matcher_version="test-v1",
    )
    store.add_canonical(canonical)
    service = ImportReviewService(store)
    session = service.create_session(batch.batch_id, [raw_result])
    item = service.list_items(session.session_id)[0]

    with pytest.raises(ValueError, match="not editable"):
        service.modify_canonical(
            item.review_item_id,
            {"original_row": "forbidden"},
            actor="local-user",
        )

    unchanged = store.get_canonical(canonical.canonical_id)
    still_pending = service.list_items(session.session_id)[0]
    assert unchanged is not None
    assert unchanged.merchant == "原商户"
    assert still_pending.status == "pending"
    assert service.list_events(item.review_item_id) == []
