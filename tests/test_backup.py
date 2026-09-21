"""Tests for portable, validated ledger backup and restore."""

import json
import zipfile
from datetime import date, datetime

import pytest
from beancount_dedup.backup import BackupError, export_backup, inspect_backup, restore_backup
from beancount_dedup.ledger_models import CanonicalTransaction, RawTransaction
from beancount_dedup.ledger_store import LedgerStore
from beancount_dedup.models import Platform


def populate(store: LedgerStore) -> str:
    raw = RawTransaction(
        source=Platform.WECHAT,
        source_account="private-account-token",
        transaction_time=datetime(2026, 5, 1, 8, 30),
        booking_date=date(2026, 5, 1),
        amount="-12.50",
        direction="expense",
        merchant="脱敏商户",
        transaction_id="redacted-order",
        original_row={"redacted": True},
    )
    raw = store.add_raw(raw).raw_transaction
    canonical = CanonicalTransaction(
        transaction_time=raw.transaction_time,
        booking_date=date(2026, 5, 1),
        amount="-12.50",
        direction="expense",
        merchant="脱敏商户",
    )
    canonical.add_source(
        raw,
        confidence="1",
        reasons=["transaction_id_exact"],
        matcher_version="test-v1",
    )
    store.add_canonical(canonical)
    return canonical.canonical_id


def test_backup_restore_preserves_list_and_source_detail(tmp_path):
    source_database = tmp_path / "source.sqlite3"
    backup_path = tmp_path / "ledger-backup.zip"
    restored_database = tmp_path / "restored.sqlite3"
    with LedgerStore(source_database) as store:
        canonical_id = populate(store)
        manifest = export_backup(store, backup_path)

    inspected = inspect_backup(backup_path)
    restored_manifest = restore_backup(backup_path, restored_database)
    with LedgerStore(restored_database) as restored_store:
        detail = restored_store.get_canonical(canonical_id)

    assert inspected == manifest
    assert restored_manifest == manifest
    assert detail is not None
    assert detail.source_count == 1
    assert detail.raw_transactions[0].original_row == {"redacted": True}


def test_restore_refuses_to_overwrite_existing_ledger(tmp_path):
    backup_path = tmp_path / "ledger-backup.zip"
    destination = tmp_path / "existing.sqlite3"
    with LedgerStore(tmp_path / "source.sqlite3") as store:
        populate(store)
        export_backup(store, backup_path)
    destination.write_bytes(b"keep-me")

    with pytest.raises(FileExistsError, match="already exists"):
        restore_backup(backup_path, destination)

    assert destination.read_bytes() == b"keep-me"


def test_checksum_detects_tampered_database(tmp_path):
    original_backup = tmp_path / "original.zip"
    tampered_backup = tmp_path / "tampered.zip"
    with LedgerStore(tmp_path / "source.sqlite3") as store:
        populate(store)
        export_backup(store, original_backup)

    with zipfile.ZipFile(original_backup) as source_archive:
        manifest = source_archive.read("manifest.json")
    with zipfile.ZipFile(tampered_backup, "w") as destination_archive:
        destination_archive.writestr("manifest.json", manifest)
        destination_archive.writestr("ledger.sqlite3", b"tampered")

    with pytest.raises(BackupError, match="checksum"):
        inspect_backup(tampered_backup)


def test_manifest_schema_mismatch_is_rejected(tmp_path):
    original_backup = tmp_path / "original.zip"
    incompatible_backup = tmp_path / "incompatible.zip"
    with LedgerStore(tmp_path / "source.sqlite3") as store:
        populate(store)
        export_backup(store, original_backup)

    with zipfile.ZipFile(original_backup) as source_archive:
        manifest = json.loads(source_archive.read("manifest.json"))
        database = source_archive.read("ledger.sqlite3")
    manifest["schema_version"] = 999
    with zipfile.ZipFile(incompatible_backup, "w") as destination_archive:
        destination_archive.writestr("manifest.json", json.dumps(manifest))
        destination_archive.writestr("ledger.sqlite3", database)

    with pytest.raises(BackupError, match="newer"):
        inspect_backup(incompatible_backup)
