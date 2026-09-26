import json

from beancount_dedup.backup import export_backup
from beancount_dedup.backup_cli import main
from beancount_dedup.ledger_store import LedgerStore


def test_backup_cli_inspects_and_restores_database(tmp_path, capsys) -> None:
    database = tmp_path / "ledger.sqlite3"
    backup = tmp_path / "ledger.financial-beancount.zip"
    restored = tmp_path / "restored.sqlite3"
    with LedgerStore(database) as store:
        export_backup(store, backup)

    assert main(["inspect", "--backup", str(backup)]) == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["valid"] is True

    assert main(["restore", "--backup", str(backup), "--database", str(restored)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["restored"] is True
    with LedgerStore(restored) as store:
        assert store.last_migration_backup is None


def test_backup_cli_requires_explicit_overwrite(tmp_path, capsys) -> None:
    database = tmp_path / "ledger.sqlite3"
    backup = tmp_path / "ledger.financial-beancount.zip"
    with LedgerStore(database) as store:
        export_backup(store, backup)

    assert main(["restore", "--backup", str(backup), "--database", str(database)]) == 2
    error = json.loads(capsys.readouterr().err)
    assert error["error"]["code"] == "backup_error"

    assert (
        main(
            [
                "restore",
                "--backup",
                str(backup),
                "--database",
                str(database),
                "--overwrite",
            ]
        )
        == 0
    )
