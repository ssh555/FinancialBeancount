from pathlib import Path

import pytest
from beancount_dedup.update_helper import (
    apply_prepared_application,
    rollback_applied_update,
    wait_for_process_exit,
)
from beancount_dedup.updater import UpdateCheckError


def test_apply_prepared_application_swaps_and_keeps_backup(tmp_path: Path) -> None:
    source = tmp_path / "staged" / "FinancialBeancount"
    source.mkdir(parents=True)
    (source / "FinancialBeancount.exe").write_bytes(b"new")
    target = tmp_path / "installed" / "FinancialBeancount"
    target.mkdir(parents=True)
    (target / "FinancialBeancount.exe").write_bytes(b"old")

    result = apply_prepared_application(
        source, target, launcher_relative=Path("FinancialBeancount.exe")
    )

    assert result.launcher.read_bytes() == b"new"
    assert (result.backup_directory / "FinancialBeancount.exe").read_bytes() == b"old"
    assert not (target.parent / ".FinancialBeancount.update-pending").exists()


def test_apply_prepared_application_rotates_prior_successful_backup(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "app").write_text("new", encoding="utf-8")
    target = tmp_path / "app-dir"
    target.mkdir()
    (target / "app").write_text("old", encoding="utf-8")
    previous = tmp_path / "app-dir.previous"
    previous.mkdir()
    (previous / "app").write_text("older", encoding="utf-8")

    result = apply_prepared_application(source, target, launcher_relative=Path("app"))

    assert (target / "app").read_text(encoding="utf-8") == "new"
    assert (result.backup_directory / "app").read_text(encoding="utf-8") == "old"


def test_apply_prepared_application_validates_launcher_before_swap(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    target = tmp_path / "app-dir"
    target.mkdir()
    (target / "app").write_text("old", encoding="utf-8")

    with pytest.raises(UpdateCheckError, match="启动程序"):
        apply_prepared_application(source, target, launcher_relative=Path("missing"))

    assert (target / "app").read_text(encoding="utf-8") == "old"
    assert not (tmp_path / ".app-dir.update-pending").exists()


def test_rollback_applied_update_restores_old_application(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "app").write_text("new", encoding="utf-8")
    target = tmp_path / "app-dir"
    target.mkdir()
    (target / "app").write_text("old", encoding="utf-8")
    applied = apply_prepared_application(source, target, launcher_relative=Path("app"))

    rollback_applied_update(applied)

    assert (target / "app").read_text(encoding="utf-8") == "old"
    assert not applied.backup_directory.exists()
    assert not (tmp_path / "app-dir.failed-update").exists()


def test_wait_for_missing_process_returns_without_side_effects() -> None:
    wait_for_process_exit(2_147_483_647, timeout=0.01)
