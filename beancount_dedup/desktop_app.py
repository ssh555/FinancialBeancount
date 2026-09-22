"""Small native controller for the bundled local-first web application."""

from __future__ import annotations

import argparse
import os
import queue
import sys
import threading
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING

from .mobile_api import serve_mobile_api

if TYPE_CHECKING:
    import tkinter as tk


def application_data_directory(
    platform: str | None = None, environment: dict[str, str] | None = None
) -> Path:
    """Return a per-user, non-synchronized default data directory."""

    current_platform = platform or sys.platform
    values = environment or os.environ
    if current_platform == "win32":
        root = Path(values.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return root / "FinancialBeancount"
    if current_platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "FinancialBeancount"
    root = Path(values.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return root / "financial-beancount"


def default_database_path() -> Path:
    return application_data_directory() / "ledger.sqlite3"


class DesktopController:
    """Own the local server lifecycle and a minimal native control window."""

    def __init__(self, root: tk.Tk, database_path: Path):
        import tkinter
        from tkinter import messagebox, ttk

        self.root = root
        self.database_path = database_path
        self.stop_event = threading.Event()
        self.events: queue.SimpleQueue[tuple[str, str]] = queue.SimpleQueue()
        self.local_url = ""
        self._messagebox = messagebox
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path = database_path.parent / "desktop-startup.log"
        self.log_path.write_text("controller initialized\n", encoding="utf-8")

        root.title("FinancialBeancount 本地账本")
        root.geometry("520x280")
        root.minsize(440, 250)
        root.protocol("WM_DELETE_WINDOW", self.close)

        frame = ttk.Frame(root, padding=24)
        frame.pack(fill=tkinter.BOTH, expand=True)
        ttk.Label(frame, text="FinancialBeancount", font=("Segoe UI", 20, "bold")).pack(
            anchor=tkinter.W
        )
        ttk.Label(frame, text="纯本地、离线优先的统一账本").pack(anchor=tkinter.W, pady=(2, 18))
        self.status = tkinter.StringVar(value="正在启动本地服务…")
        ttk.Label(frame, textvariable=self.status).pack(anchor=tkinter.W)
        ttk.Label(frame, text=f"数据文件：{database_path}", wraplength=460).pack(
            anchor=tkinter.W, pady=(8, 20)
        )
        buttons = ttk.Frame(frame)
        buttons.pack(fill=tkinter.X)
        self.open_button = ttk.Button(
            buttons, text="打开账本", command=self.open_ledger, state=tkinter.DISABLED
        )
        self.open_button.pack(side=tkinter.LEFT)
        ttk.Button(buttons, text="退出", command=self.close).pack(side=tkinter.RIGHT)
        root.after(50, self._poll_events)

    def start(self) -> None:
        self._log("starting server thread")
        threading.Thread(target=self._serve, name="ledger-server", daemon=True).start()

    def _serve(self) -> None:
        try:
            self._log("server thread entered")
            serve_mobile_api(
                str(self.database_path),
                host="127.0.0.1",
                port=0,
                ready_callback=self._ready,
                stop_event=self.stop_event,
            )
        except Exception as exc:  # pragma: no cover - native startup boundary
            error_log = self.database_path.parent / "last-startup-error.log"
            error_log.write_text(str(exc), encoding="utf-8")
            self.events.put(("failed", str(exc)))

    def _ready(self, local_url: str) -> None:
        self._log(f"server ready at {local_url}")
        self.events.put(("ready", local_url))

    def _log(self, message: str) -> None:
        with self.log_path.open("a", encoding="utf-8") as stream:
            stream.write(f"{message}\n")

    def _poll_events(self) -> None:
        while not self.events.empty():
            action, value = self.events.get()
            if action == "ready":
                self.local_url = value
                self._show_ready()
            elif action == "failed":
                self._failed(value)
        if not self.stop_event.is_set():
            self.root.after(50, self._poll_events)

    def _show_ready(self) -> None:
        self.status.set(f"本地服务已就绪：{self.local_url}")
        self.open_button.configure(state="normal")
        self.open_ledger()

    def _failed(self, message: str) -> None:
        self.status.set("本地服务启动失败")
        self._messagebox.showerror("FinancialBeancount", message)

    def open_ledger(self) -> None:
        if self.local_url:
            webbrowser.open(self.local_url)

    def close(self) -> None:
        self.stop_event.set()
        self.root.after(300, self.root.destroy)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="FinancialBeancount desktop application")
    parser.add_argument("--database", type=Path, default=default_database_path())
    args = parser.parse_args(argv)

    import tkinter

    root = tkinter.Tk()
    controller = DesktopController(root, args.database.expanduser().resolve())
    controller.start()
    root.mainloop()


if __name__ == "__main__":
    main()
