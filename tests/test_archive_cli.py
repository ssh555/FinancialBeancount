"""Tests for user-facing portable archive commands."""

import json

from beancount_dedup.archive_cli import main
from beancount_dedup.ledger_store import LedgerStore
from beancount_dedup.models import Platform


def test_archive_cli_export_inspect_and_import(tmp_path, capsys):
    database = tmp_path / "source.sqlite3"
    with LedgerStore(database) as store:
        store.start_import_batch(Platform.ALIPAY, "statement.csv", "hash")
    archive = tmp_path / "portable.zip"
    restored = tmp_path / "restored.sqlite3"

    assert main(["export", "--database", str(database), "--output", str(archive)]) == 0
    exported = json.loads(capsys.readouterr().out)
    assert exported["action"] == "export"
    assert archive.exists()

    assert main(["inspect", "--archive", str(archive)]) == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["valid"] is True
    assert inspected["manifest"]["tables"]["import_batches"]["rows"] == 1

    assert main(["import", "--archive", str(archive), "--database", str(restored)]) == 0
    imported = json.loads(capsys.readouterr().out)
    assert imported["restored"] is True
    with LedgerStore(restored) as store:
        assert store.connection.execute("SELECT COUNT(*) FROM import_batches").fetchone()[0] == 1


def test_archive_cli_refuses_existing_destination(tmp_path, capsys):
    source = tmp_path / "source.sqlite3"
    with LedgerStore(source):
        pass
    archive = tmp_path / "portable.zip"
    assert main(["export", "--database", str(source), "--output", str(archive)]) == 0
    capsys.readouterr()
    destination = tmp_path / "existing.sqlite3"
    destination.write_text("keep me", encoding="utf-8")

    result = main(["import", "--archive", str(archive), "--database", str(destination)])
    error = json.loads(capsys.readouterr().err)

    assert result == 2
    assert error["error"]["code"] == "archive_error"
    assert destination.read_text(encoding="utf-8") == "keep me"
