"""Tests for desktop defaults without starting a graphical session."""

import queue
import threading
from pathlib import Path
from unittest.mock import Mock

from beancount_dedup.desktop_app import DesktopController, application_data_directory


def test_windows_data_directory_uses_local_app_data():
    result = application_data_directory(
        "win32", {"LOCALAPPDATA": r"C:\Users\tester\AppData\Local"}
    )

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
    controller.log_path = tmp_path / "desktop-startup.log"

    controller._ready("http://127.0.0.1:12345")
    controller._poll_events()

    assert controller.local_url == "http://127.0.0.1:12345"
    controller._show_ready.assert_called_once_with()
    controller.root.after.assert_called_once()
