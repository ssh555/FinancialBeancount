"""Tests for desktop defaults without starting a graphical session."""

import queue
import threading
from pathlib import Path
from unittest.mock import Mock, patch

from beancount_dedup.desktop_app import DesktopController, application_data_directory
from beancount_dedup.ledger_store import LedgerMigrationError
from beancount_dedup.updater import PreparedUpdate, ReleaseAsset, UpdateCheckError, UpdateInfo


def test_windows_data_directory_uses_local_app_data():
    result = application_data_directory("win32", {"LOCALAPPDATA": r"C:\Users\tester\AppData\Local"})

    assert result == Path(r"C:\Users\tester\AppData\Local") / "FinancialBeancount"


def test_linux_data_directory_honors_xdg_data_home():
    result = application_data_directory("linux", {"XDG_DATA_HOME": "/home/tester/data"})

    assert result == Path("/home/tester/data/financial-beancount")


def test_worker_ready_event_is_applied_by_gui_poll(tmp_path):
    controller = object.__new__(DesktopController)
    controller.events = queue.SimpleQueue()
    controller.stop_event = threading.Event()
    controller.root = Mock()
    controller._show_ready = Mock()
    controller.local_url = ""
    controller.health_marker = None
    controller.log_path = tmp_path / "desktop-startup.log"

    controller._ready("http://127.0.0.1:12345")
    controller._poll_events()

    assert controller.local_url == "http://127.0.0.1:12345"
    controller._show_ready.assert_called_once_with()
    controller.root.after.assert_called_once()


def test_worker_ready_writes_update_health_marker(tmp_path):
    controller = object.__new__(DesktopController)
    controller.events = queue.SimpleQueue()
    controller.log_path = tmp_path / "desktop-startup.log"
    controller.log_path.write_text("", encoding="utf-8")
    controller.health_marker = tmp_path / "update" / "healthy.txt"

    controller._ready("http://127.0.0.1:12345")

    assert controller.health_marker.read_text(encoding="utf-8") == "ready\n"


def test_show_update_requires_consent_before_starting_download():
    controller = object.__new__(DesktopController)
    controller.update_button = Mock()
    controller.status = Mock()
    controller._messagebox = Mock()
    controller._messagebox.askyesno.return_value = True
    update = UpdateInfo(
        version="0.3.0",
        title="Preview",
        notes="Safer updates",
        publisher="ssh555",
        published_at="2026-09-22T00:00:00Z",
        release_url="https://example.test/release",
        archive=ReleaseAsset("app.zip", "https://example.test/app.zip", 10485760),
        checksum=ReleaseAsset("app.zip.sha256", "https://example.test/sum", 100),
        signature=ReleaseAsset("app.zip.sha256.sig", "https://example.test/sig", 89),
    )

    with patch("beancount_dedup.desktop_app.threading.Thread") as thread:
        controller._show_update(update)

    controller._messagebox.askyesno.assert_called_once()
    thread.assert_called_once()
    thread.return_value.start.assert_called_once_with()


def test_launch_update_helper_copies_helper_outside_installation(tmp_path):
    installation = tmp_path / "installed"
    installation.mkdir()
    executable = installation / "FinancialBeancount.exe"
    executable.write_bytes(b"application")
    (installation / "FinancialBeancountUpdater.exe").write_bytes(b"helper")
    stage = tmp_path / "updates" / "0.3.0"
    stage.mkdir(parents=True)
    plan = stage / "install-plan.json"
    plan.write_text("{}", encoding="utf-8")
    prepared = PreparedUpdate("0.3.0", stage / "unpacked", plan)
    controller = object.__new__(DesktopController)
    controller.close = Mock()

    with (
        patch("beancount_dedup.desktop_app.sys.executable", str(executable)),
        patch("beancount_dedup.desktop_app.sys.platform", "win32"),
        patch("beancount_dedup.desktop_app.subprocess.Popen") as popen,
    ):
        controller._launch_update_helper(prepared)

    staged_helper = stage / "FinancialBeancountUpdater.exe"
    assert staged_helper.read_bytes() == b"helper"
    command = popen.call_args.args[0]
    assert command[0] == str(staged_helper)
    assert command[command.index("--install-dir") + 1] == str(installation)
    controller.close.assert_called_once_with()


def test_staged_update_permission_failure_offers_manual_path_without_closing(tmp_path):
    prepared = PreparedUpdate(
        "0.3.0", tmp_path / "unpacked" / "FinancialBeancount", tmp_path / "plan"
    )
    controller = object.__new__(DesktopController)
    controller.update_button = Mock()
    controller.status = Mock()
    controller._messagebox = Mock()
    controller.close = Mock()

    with (
        patch("beancount_dedup.desktop_app.sys.frozen", True, create=True),
        patch("beancount_dedup.desktop_app.sys.platform", "linux"),
        patch(
            "beancount_dedup.desktop_app.verify_installation_permissions",
            side_effect=UpdateCheckError("permission denied"),
        ),
    ):
        controller._show_staged_update(prepared)

    controller._messagebox.showwarning.assert_called_once()
    assert (
        str(prepared.application_directory) in controller._messagebox.showwarning.call_args.args[1]
    )
    controller.close.assert_not_called()


def test_elevated_update_uses_windows_uac_and_only_then_closes(tmp_path):
    installation = tmp_path / "installed"
    installation.mkdir()
    executable = installation / "FinancialBeancount.exe"
    executable.write_bytes(b"application")
    (installation / "FinancialBeancountUpdater.exe").write_bytes(b"helper")
    stage = tmp_path / "updates"
    stage.mkdir()
    prepared = PreparedUpdate("0.3.0", stage / "unpacked", stage / "install-plan.json")
    controller = object.__new__(DesktopController)
    controller.close = Mock()

    with (
        patch("beancount_dedup.desktop_app.sys.executable", str(executable)),
        patch("beancount_dedup.desktop_app.sys.platform", "win32"),
        patch("ctypes.windll", create=True) as windll,
    ):
        windll.shell32.ShellExecuteW.return_value = 42
        controller._launch_update_helper(prepared, elevated=True)

    shell_execute = windll.shell32.ShellExecuteW
    assert shell_execute.call_args.args[1] == "runas"
    assert "--install-dir" in shell_execute.call_args.args[3]
    controller.close.assert_called_once_with()


def test_migration_failure_restore_requires_confirmation(tmp_path):
    controller = object.__new__(DesktopController)
    controller.status = Mock()
    controller._messagebox = Mock()
    controller._messagebox.askyesno.return_value = True
    controller.database_path = tmp_path / "ledger.sqlite3"
    backup = tmp_path / "backup.financial-beancount.zip"
    error = LedgerMigrationError("migration failed", backup)

    with patch("beancount_dedup.desktop_app.restore_backup") as restore:
        controller._migration_failed(error)

    controller._messagebox.askyesno.assert_called_once()
    restore.assert_called_once_with(backup, controller.database_path, overwrite=True)
    controller._messagebox.showinfo.assert_called_once()
