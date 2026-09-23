"""Tests for the open JSONL device-migration archive."""

import hashlib
import json
import zipfile
from datetime import date, datetime

import pytest
from beancount_dedup.ledger_models import RawTransaction
from beancount_dedup.ledger_store import LedgerStore
from beancount_dedup.models import Platform
from beancount_dedup.portable_archive import (
    PortableArchiveError,
    export_portable_archive,
    import_portable_archive,
    inspect_portable_archive,
)
from beancount_dedup.review import ImportReviewService


def raw(batch_id: str | None = None) -> RawTransaction:
    return RawTransaction(
        source=Platform.ALIPAY,
        source_account="portable-account",
        transaction_time=datetime(2026, 3, 1, 12, 0),
        booking_date=date(2026, 3, 1),
        amount="-20",
        direction="expense",
        merchant="脱敏商户",
        transaction_id="portable-order",
        import_batch_id=batch_id,
        source_file="statement.csv",
        source_file_hash="file-hash",
        raw_row_number=10,
        original_row={"脱敏字段": "原始值"},
    )


def populated_store(path):
    store = LedgerStore(path)
    batch, _ = store.start_import_batch(Platform.ALIPAY, "statement.csv", "file-hash")
    result = store.add_raws([raw(batch.batch_id)])[0]
    review = ImportReviewService(store)
    session = review.create_session(batch.batch_id, [result])
    item = review.list_items(session.session_id)[0]
    review.decide(item.review_item_id, "confirmed", "local-user")
    return store, result, item


def test_portable_archive_round_trip_preserves_raw_canonical_and_audit(tmp_path):
    source, result, item = populated_store(tmp_path / "source.sqlite3")
    source_canonical = source.find_canonical_for_raw(result.raw_transaction.raw_id)
    assert source_canonical is not None
    source.record_canonical_event(
        source_canonical.canonical_id,
        "updated",
        {"notes": ""},
        {"notes": "已核对"},
        "local-user",
    )
    source.soft_delete_canonical(source_canonical.canonical_id, "local-user", "archive-test")
    archive = tmp_path / "ledger.financial.zip"
    manifest = export_portable_archive(source, archive)
    source.close()

    inspected = inspect_portable_archive(archive)
    restored = import_portable_archive(archive, tmp_path / "restored.sqlite3")
    try:
        restored_raw = restored.get_raw(result.raw_transaction.raw_id)
        canonical = restored.find_canonical_for_raw(result.raw_transaction.raw_id)
        events = ImportReviewService(restored).list_events(item.review_item_id)
        assert inspected == manifest
        assert restored_raw is not None
        assert restored_raw.original_row == {"脱敏字段": "原始值"}
        assert canonical is not None
        assert canonical.source_count == 1
        assert restored.is_canonical_deleted(canonical.canonical_id)
        assert [event["action"] for event in restored.list_canonical_events(canonical.canonical_id)] == [
            "updated",
            "deleted",
        ]
        assert events[0].actor == "local-user"
        assert manifest.tables["raw_transactions"]["rows"] == 1
    finally:
        restored.close()


def test_checksum_tampering_is_rejected(tmp_path):
    store, _, _ = populated_store(tmp_path / "source.sqlite3")
    archive = tmp_path / "valid.zip"
    export_portable_archive(store, archive)
    store.close()
    corrupted = tmp_path / "corrupted.zip"
    with zipfile.ZipFile(archive, "r") as source, zipfile.ZipFile(corrupted, "w") as target:
        for name in source.namelist():
            payload = source.read(name)
            if name == "data/raw_transactions.jsonl":
                payload += b"{}\n"
            target.writestr(name, payload)

    with pytest.raises(PortableArchiveError, match="checksum"):
        inspect_portable_archive(corrupted)


def test_unknown_table_in_manifest_is_rejected(tmp_path):
    store, _, _ = populated_store(tmp_path / "source.sqlite3")
    archive = tmp_path / "valid.zip"
    export_portable_archive(store, archive)
    store.close()
    invalid = tmp_path / "invalid.zip"
    with zipfile.ZipFile(archive, "r") as source, zipfile.ZipFile(invalid, "w") as target:
        for name in source.namelist():
            if name == "manifest.json":
                manifest = json.loads(source.read(name))
                manifest["tables"]["unexpected"] = {
                    "file": "data/unexpected.jsonl",
                    "rows": 0,
                    "sha256": "0" * 64,
                }
                target.writestr(name, json.dumps(manifest))
            else:
                target.writestr(name, source.read(name))

    with pytest.raises(PortableArchiveError, match="table set"):
        inspect_portable_archive(invalid)


def test_import_refuses_nonempty_destination(tmp_path):
    source, _, _ = populated_store(tmp_path / "source.sqlite3")
    archive = tmp_path / "ledger.zip"
    export_portable_archive(source, archive)
    source.close()
    destination, _, _ = populated_store(tmp_path / "destination.sqlite3")
    destination.close()

    with pytest.raises(PortableArchiveError, match="already exists"):
        import_portable_archive(archive, tmp_path / "destination.sqlite3")


def test_import_accepts_legacy_v1_schema_9_archive(tmp_path):
    store, result, _ = populated_store(tmp_path / "source.sqlite3")
    current = tmp_path / "current.zip"
    export_portable_archive(store, current)
    store.close()
    legacy = tmp_path / "legacy-v1.zip"
    with zipfile.ZipFile(current, "r") as source:
        entries = {name: source.read(name) for name in source.namelist()}
    manifest = json.loads(entries["manifest.json"])
    manifest["format_version"] = 1
    manifest["schema_version"] = 9
    manifest["tables"].pop("schema_migrations")
    entries.pop("data/schema_migrations.jsonl")
    entries["manifest.json"] = json.dumps(manifest).encode("utf-8")
    with zipfile.ZipFile(legacy, "w") as target:
        for name, payload in entries.items():
            target.writestr(name, payload)

    restored = import_portable_archive(legacy, tmp_path / "restored.sqlite3")
    try:
        assert restored.get_raw(result.raw_transaction.raw_id) is not None
    finally:
        restored.close()


def test_import_rejects_forged_column_even_with_matching_checksum(tmp_path):
    store, _, _ = populated_store(tmp_path / "source.sqlite3")
    archive = tmp_path / "valid.zip"
    export_portable_archive(store, archive)
    store.close()
    forged = tmp_path / "forged.zip"
    with zipfile.ZipFile(archive, "r") as source:
        entries = {name: source.read(name) for name in source.namelist()}
    raw_name = "data/raw_transactions.jsonl"
    row = json.loads(entries[raw_name].decode("utf-8"))
    row["forged_column"] = "unsafe"
    entries[raw_name] = (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")
    manifest = json.loads(entries["manifest.json"])
    manifest["tables"]["raw_transactions"]["sha256"] = hashlib.sha256(entries[raw_name]).hexdigest()
    entries["manifest.json"] = json.dumps(manifest).encode("utf-8")
    with zipfile.ZipFile(forged, "w") as target:
        for name, payload in entries.items():
            target.writestr(name, payload)

    with pytest.raises(PortableArchiveError, match="column set"):
        import_portable_archive(forged, tmp_path / "restored.sqlite3")
