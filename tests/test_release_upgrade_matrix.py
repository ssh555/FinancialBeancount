"""End-to-end release upgrade gates across every supported ledger generation."""

import sqlite3
from pathlib import Path

import pytest
from beancount_dedup.ledger_store import SCHEMA_VERSION, LedgerMigrationError, LedgerStore
from beancount_dedup.update_helper import apply_prepared_application, rollback_applied_update

SUPPORTED_RELEASE_SCHEMAS = (8, 9, SCHEMA_VERSION)


def _create_release_ledger(path: Path, schema_version: int) -> None:
    if schema_version == SCHEMA_VERSION:
        with LedgerStore(path) as store:
            store.connection.execute(
                """
                INSERT INTO canonical_transactions VALUES(
                    'release-entry', NULL, '2026-01-02', '-12.50', 'expense',
                    '升级测试商户', '升级测试商户', '餐饮', 'alipay', '余额',
                    'expense', 'completed', 'confirmed', '跨版本保留'
                )
                """
            )
            store.connection.commit()
        return

    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            f"""
            CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO schema_meta VALUES('schema_version', '{schema_version}');
            CREATE TABLE canonical_transactions (
                canonical_id TEXT PRIMARY KEY, transaction_time TEXT,
                booking_date TEXT NOT NULL, amount TEXT NOT NULL, direction TEXT NOT NULL,
                merchant TEXT NOT NULL, normalized_merchant TEXT NOT NULL,
                category TEXT NOT NULL, payment_channel TEXT NOT NULL,
                funding_account TEXT NOT NULL, tx_type TEXT NOT NULL, status TEXT NOT NULL,
                review_status TEXT NOT NULL, notes TEXT NOT NULL
            );
            INSERT INTO canonical_transactions VALUES(
                'release-entry', NULL, '2026-01-02', '-12.50', 'expense',
                '升级测试商户', '升级测试商户', '餐饮', 'alipay', '余额',
                'expense', 'completed', 'confirmed', '跨版本保留'
            );
            """
        )
        if schema_version >= 9:
            connection.executescript(
                """
                CREATE TABLE canonical_deletions (
                    canonical_id TEXT PRIMARY KEY, actor TEXT NOT NULL,
                    reason TEXT NOT NULL, deleted_at TEXT NOT NULL
                );
                CREATE TABLE canonical_events (
                    event_id TEXT PRIMARY KEY, canonical_id TEXT NOT NULL,
                    action TEXT NOT NULL, before_json TEXT NOT NULL,
                    after_json TEXT NOT NULL, actor TEXT NOT NULL, created_at TEXT NOT NULL
                );
                """
            )
        connection.commit()
    finally:
        connection.close()


def _application_directories(tmp_path: Path) -> tuple[Path, Path]:
    staged = tmp_path / "staged" / "FinancialBeancount"
    staged.mkdir(parents=True)
    (staged / "app").write_text("new-release", encoding="utf-8")
    installed = tmp_path / "installed" / "FinancialBeancount"
    installed.mkdir(parents=True)
    (installed / "app").write_text("old-release", encoding="utf-8")
    return staged, installed


@pytest.mark.parametrize("schema_version", SUPPORTED_RELEASE_SCHEMAS)
def test_release_upgrade_matrix_preserves_ledger_and_swaps_binary(
    tmp_path: Path, schema_version: int
) -> None:
    database = tmp_path / "user-data" / "ledger.sqlite3"
    database.parent.mkdir()
    _create_release_ledger(database, schema_version)
    staged, installed = _application_directories(tmp_path)

    applied = apply_prepared_application(staged, installed, launcher_relative=Path("app"))
    with LedgerStore(database) as store:
        version = store.connection.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()[0]
        preserved = store.connection.execute(
            "SELECT merchant, notes FROM canonical_transactions WHERE canonical_id='release-entry'"
        ).fetchone()
        backup = store.last_migration_backup

    assert applied.launcher.read_text(encoding="utf-8") == "new-release"
    assert (applied.backup_directory / "app").read_text(encoding="utf-8") == "old-release"
    assert version == str(SCHEMA_VERSION)
    assert tuple(preserved) == ("升级测试商户", "跨版本保留")
    assert (backup is not None) is (schema_version < SCHEMA_VERSION)


def test_failed_release_migration_rolls_back_database_and_binary(
    tmp_path: Path, monkeypatch
) -> None:
    database = tmp_path / "user-data" / "ledger.sqlite3"
    database.parent.mkdir()
    _create_release_ledger(database, 9)
    staged, installed = _application_directories(tmp_path)
    applied = apply_prepared_application(staged, installed, launcher_relative=Path("app"))

    def fail_migration(_store):
        raise RuntimeError("release migration failure")

    monkeypatch.setattr(LedgerStore, "_migrate_9_to_10", fail_migration)
    with pytest.raises(LedgerMigrationError):
        LedgerStore(database)
    rollback_applied_update(applied)

    assert (installed / "app").read_text(encoding="utf-8") == "old-release"
    with sqlite3.connect(database) as connection:
        assert (
            connection.execute(
                "SELECT value FROM schema_meta WHERE key='schema_version'"
            ).fetchone()[0]
            == "9"
        )
        assert (
            connection.execute(
                "SELECT notes FROM canonical_transactions WHERE canonical_id='release-entry'"
            ).fetchone()[0]
            == "跨版本保留"
        )
