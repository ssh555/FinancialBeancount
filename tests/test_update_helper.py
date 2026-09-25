from pathlib import Path
from unittest.mock import patch

import pytest
from beancount_dedup.update_helper import (
    apply_prepared_application,
    main,
    rollback_applied_update,
    verify_installation_permissions,
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


def test_permission_preflight_reports_manual_install_without_mutating_target(tmp_path: Path) -> None:
    target = tmp_path / "installed"
    target.mkdir()
    (target / "app").write_text("unchanged", encoding="utf-8")

    with (
        pytest.MonkeyPatch.context() as monkeypatch,
        pytest.raises(UpdateCheckError, match="手动替换"),
    ):
        monkeypatch.setattr(Path, "open", lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError()))
        verify_installation_permissions(target)

    assert (target / "app").read_text(encoding="utf-8") == "unchanged"
    assert not list(tmp_path.rglob(".financial-beancount-write-test-*"))


def test_late_helper_failure_restarts_retained_application(tmp_path: Path) -> None:
    install = tmp_path / "installed"
    install.mkdir()
    launcher = install / "app.exe"
    launcher.write_bytes(b"old")
    plan = tmp_path / "install-plan.json"
    plan.write_text(
        '{"format_version": 1, "application_directory": "staged"}', encoding="utf-8"
    )

    with (
        patch("beancount_dedup.update_helper.wait_for_process_exit"),
        patch(
            "beancount_dedup.update_helper.apply_prepared_application",
            side_effect=UpdateCheckError("permission changed"),
        ),
        patch("beancount_dedup.update_helper.subprocess.Popen") as popen,
    ):
        result = main(
            [
                "--plan",
                str(plan),
                "--install-dir",
                str(install),
                "--launcher",
                launcher.name,
                "--wait-pid",
                "123",
            ]
        )

    assert result == 1
    popen.assert_called_once_with([str(launcher)], close_fds=True)
    assert "permission changed" in plan.with_name("install-error.log").read_text(encoding="utf-8")
