import sqlite3
from pathlib import Path

import pytest
from beancount_dedup.backup import inspect_backup, restore_backup
from beancount_dedup.ledger_store import SCHEMA_VERSION, LedgerMigrationError, LedgerStore


def create_legacy_ledger(path: Path, version: int) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            f"""
            CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO schema_meta(key, value) VALUES('schema_version', '{version}');
            CREATE TABLE canonical_transactions (
                canonical_id TEXT PRIMARY KEY,
                transaction_time TEXT,
                booking_date TEXT NOT NULL,
                amount TEXT NOT NULL,
                direction TEXT NOT NULL,
                merchant TEXT NOT NULL,
                normalized_merchant TEXT NOT NULL,
                category TEXT NOT NULL,
                payment_channel TEXT NOT NULL,
                funding_account TEXT NOT NULL,
                tx_type TEXT NOT NULL,
                status TEXT NOT NULL,
                review_status TEXT NOT NULL,
                notes TEXT NOT NULL
            );
            INSERT INTO canonical_transactions VALUES(
                'legacy-entry', NULL, '2026-01-02', '-12.50', 'expense',
                '历史商户', '历史商户', '餐饮', '支付宝', '余额',
                'expense', 'completed', 'confirmed', '必须保留'
            );
            CREATE TABLE import_batches (
                batch_id TEXT PRIMARY KEY, source TEXT NOT NULL, source_file TEXT NOT NULL,
                source_file_hash TEXT NOT NULL UNIQUE, imported_at TEXT NOT NULL
            );
            INSERT INTO import_batches VALUES(
                'legacy-batch', 'alipay', 'legacy.csv', 'legacy-hash', '2026-01-03T00:00:00'
            );
            CREATE TABLE raw_transactions (
                raw_id TEXT PRIMARY KEY, deduplication_key TEXT NOT NULL UNIQUE,
                source TEXT NOT NULL, source_account TEXT NOT NULL,
                transaction_time TEXT, booking_date TEXT, amount TEXT NOT NULL,
                direction TEXT NOT NULL, merchant TEXT NOT NULL, counterparty TEXT NOT NULL,
                description TEXT NOT NULL, payment_method TEXT NOT NULL,
                bank_card_suffix TEXT, transaction_id TEXT, merchant_order_id TEXT,
                status TEXT NOT NULL, balance TEXT, currency TEXT NOT NULL,
                import_batch_id TEXT, source_file TEXT NOT NULL, source_file_hash TEXT NOT NULL,
                raw_row_number INTEGER, original_row_json TEXT NOT NULL,
                FOREIGN KEY (import_batch_id) REFERENCES import_batches(batch_id)
            );
            INSERT INTO raw_transactions VALUES(
                'legacy-raw', 'legacy-key', 'alipay', 'legacy-account',
                '2026-01-02T12:00:00', '2026-01-02', '-12.50', 'expense',
                '历史商户', '历史商户', '历史原始记录', '余额', NULL,
                'legacy-order', NULL, 'completed', NULL, 'CNY', 'legacy-batch',
                'legacy.csv', 'legacy-hash', 8, '{{"protected": true}}'
            );
            CREATE TABLE source_record_links (
                canonical_id TEXT NOT NULL, raw_id TEXT NOT NULL UNIQUE,
                confidence TEXT NOT NULL, reasons_json TEXT NOT NULL,
                matcher_version TEXT NOT NULL, linked_at TEXT NOT NULL, linked_by TEXT NOT NULL,
                PRIMARY KEY (canonical_id, raw_id)
            );
            INSERT INTO source_record_links VALUES(
                'legacy-entry', 'legacy-raw', '1', '["legacy"]',
                'legacy-v1', '2026-01-03T00:00:00', 'system'
            );
            CREATE TABLE review_sessions (
                session_id TEXT PRIMARY KEY, import_batch_id TEXT NOT NULL,
                status TEXT NOT NULL, created_at TEXT NOT NULL, completed_at TEXT
            );
            INSERT INTO review_sessions VALUES(
                'legacy-session', 'legacy-batch', 'pending', '2026-01-03T00:00:00', NULL
            );
            CREATE TABLE review_items (
                review_item_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, raw_id TEXT NOT NULL,
                canonical_id TEXT, item_type TEXT NOT NULL, status TEXT NOT NULL,
                snapshot_json TEXT NOT NULL, created_at TEXT NOT NULL, reviewed_at TEXT,
                reviewed_by TEXT
            );
            INSERT INTO review_items VALUES(
                'legacy-review', 'legacy-session', 'legacy-raw', 'legacy-entry',
                'imported', 'pending', '{{"keep": true}}', '2026-01-03T00:00:00', NULL, NULL
            );
            CREATE TABLE review_events (
                event_id TEXT PRIMARY KEY, review_item_id TEXT NOT NULL, action TEXT NOT NULL,
                before_json TEXT NOT NULL, after_json TEXT NOT NULL, actor TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            INSERT INTO review_events VALUES(
                'legacy-event', 'legacy-review', 'created', '{{}}', '{{"keep": true}}',
                'system', '2026-01-03T00:00:00'
            );
            """
        )
        if version >= 9:
            connection.executescript(
                """
                CREATE TABLE canonical_deletions (
                    canonical_id TEXT PRIMARY KEY, actor TEXT NOT NULL,
                    reason TEXT NOT NULL, deleted_at TEXT NOT NULL,
                    FOREIGN KEY (canonical_id)
                        REFERENCES canonical_transactions(canonical_id) ON DELETE CASCADE
                );
                CREATE TABLE canonical_events (
                    event_id TEXT PRIMARY KEY, canonical_id TEXT NOT NULL,
                    action TEXT NOT NULL, before_json TEXT NOT NULL,
                    after_json TEXT NOT NULL, actor TEXT NOT NULL, created_at TEXT NOT NULL,
                    FOREIGN KEY (canonical_id)
                        REFERENCES canonical_transactions(canonical_id) ON DELETE CASCADE
                );
                CREATE INDEX idx_canonical_events_transaction
                    ON canonical_events(canonical_id, created_at);
                """
            )
        connection.commit()
    finally:
        connection.close()


def test_schema_8_upgrade_is_backed_up_recorded_and_preserves_data(tmp_path: Path) -> None:
    database = tmp_path / "ledger.sqlite3"
    create_legacy_ledger(database, 8)

    with LedgerStore(database) as store:
        assert store.last_migration_backup is not None
        backup = store.last_migration_backup
        version = store.connection.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()[0]
        merchant = store.connection.execute(
            "SELECT merchant FROM canonical_transactions WHERE canonical_id = 'legacy-entry'"
        ).fetchone()[0]
        migrations = store.connection.execute(
            "SELECT from_version, to_version, status FROM schema_migrations ORDER BY from_version"
        ).fetchall()
        preserved = {
            table: store.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "raw_transactions",
                "canonical_transactions",
                "source_record_links",
                "review_sessions",
                "review_items",
                "review_events",
            )
        }

    assert version == str(SCHEMA_VERSION)
    assert merchant == "历史商户"
    assert [tuple(row) for row in migrations] == [(8, 9, "completed"), (9, 10, "completed")]
    assert preserved == {
        "raw_transactions": 1,
        "canonical_transactions": 1,
        "source_record_links": 1,
        "review_sessions": 1,
        "review_items": 1,
        "review_events": 1,
    }
    assert backup.is_file()
    assert inspect_backup(backup).schema_version == 8


def test_schema_9_upgrade_creates_one_migration_record(tmp_path: Path) -> None:
    database = tmp_path / "ledger.sqlite3"
    create_legacy_ledger(database, 9)

    with LedgerStore(database) as store:
        rows = store.connection.execute(
            "SELECT from_version, to_version FROM schema_migrations"
        ).fetchall()

    assert [tuple(row) for row in rows] == [(9, 10)]


def test_failed_migration_rolls_back_and_keeps_restorable_backup(
    tmp_path: Path, monkeypatch
) -> None:
    database = tmp_path / "ledger.sqlite3"
    create_legacy_ledger(database, 9)

    def fail_after_schema_change(self):
        self.connection.execute("CREATE TABLE schema_migrations(test TEXT)")
        raise RuntimeError("injected migration failure")

    monkeypatch.setattr(LedgerStore, "_migrate_9_to_10", fail_after_schema_change)
    with pytest.raises(LedgerMigrationError) as raised:
        LedgerStore(database)

    backup = raised.value.backup_path
    assert backup is not None
    assert inspect_backup(backup).schema_version == 9
    connection = sqlite3.connect(database)
    try:
        version = connection.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()[0]
        migration_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone()
    finally:
        connection.close()
    assert version == "9"
    assert migration_table is None

    restored = tmp_path / "restored.sqlite3"
    restore_backup(backup, restored)
    restored_connection = sqlite3.connect(restored)
    try:
        assert restored_connection.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()[0] == "9"
    finally:
        restored_connection.close()


def test_newer_schema_is_rejected_without_modification(tmp_path: Path) -> None:
    database = tmp_path / "future.sqlite3"
    create_legacy_ledger(database, SCHEMA_VERSION + 1)

    with pytest.raises(LedgerMigrationError, match="newer"):
        LedgerStore(database)

    connection = sqlite3.connect(database)
    try:
        assert connection.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()[0] == str(SCHEMA_VERSION + 1)
    finally:
        connection.close()
    assert not (tmp_path / "backups").exists()


def test_migration_does_not_start_when_backup_verification_fails(
    tmp_path: Path, monkeypatch
) -> None:
    database = tmp_path / "ledger.sqlite3"
    create_legacy_ledger(database, 9)

    def reject_backup(_path):
        raise ValueError("injected verification failure")

    monkeypatch.setattr("beancount_dedup.backup.inspect_backup", reject_backup)
    with pytest.raises(LedgerMigrationError, match="migration was not started"):
        LedgerStore(database)

    connection = sqlite3.connect(database)
    try:
        assert connection.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()[0] == "9"
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone() is None
    finally:
        connection.close()
