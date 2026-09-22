"""Small native controller for the bundled local-first web application."""

from __future__ import annotations

import argparse
import os
import queue
import shutil
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import __version__
from .mobile_api import serve_mobile_api
from .updater import (
    PreparedUpdate,
    UpdateCheckError,
    UpdateInfo,
    check_for_update,
    configured_releases_api,
    download_and_verify_update,
    prepare_update_installation,
)

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

    def __init__(self, root: tk.Tk, database_path: Path, health_marker: Path | None = None):
        import tkinter
        from tkinter import messagebox, ttk

        self.root = root
        self.database_path = database_path
        self.health_marker = health_marker
        self.stop_event = threading.Event()
        self.events: queue.SimpleQueue[tuple[str, Any]] = queue.SimpleQueue()
        self.local_url = ""
        self._messagebox = messagebox
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path = database_path.parent / "desktop-startup.log"
        self.log_path.write_text("controller initialized\n", encoding="utf-8")

        root.title(f"FinancialBeancount {__version__} 本地账本")
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
        self.update_button = ttk.Button(buttons, text="检查更新", command=self.check_updates)
        self.update_button.pack(side=tkinter.LEFT, padx=(8, 0))
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
        if self.health_marker is not None:
            self.health_marker.parent.mkdir(parents=True, exist_ok=True)
            self.health_marker.write_text("ready\n", encoding="utf-8")
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
            elif action == "update_checked":
                self._show_update(value)
            elif action == "update_failed":
                self.update_button.configure(state="normal")
                self._messagebox.showwarning("检查更新", value)
            elif action == "update_staged":
                self._show_staged_update(value)
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

    def check_updates(self) -> None:
        """Check only after an explicit click; never download automatically."""
        try:
            source = configured_releases_api()
        except UpdateCheckError as exc:
            self._messagebox.showwarning("检查更新", str(exc))
            return
        if source is None:
            self._messagebox.showinfo("检查更新", "更新检查已通过环境配置禁用。")
            return
        self.update_button.configure(state="disabled")
        threading.Thread(
            target=self._check_updates, args=(source,), name="update-check", daemon=True
        ).start()

    def _check_updates(self, source: str) -> None:
        try:
            result = check_for_update(__version__, api_url=source)
            self.events.put(("update_checked", result))
        except UpdateCheckError as exc:
            self.events.put(("update_failed", str(exc)))

    def _show_update(self, update: UpdateInfo | None) -> None:
        self.update_button.configure(state="normal")
        if update is None:
            self._messagebox.showinfo("检查更新", f"当前已是最新版本（{__version__}）。")
            return
        size_mib = update.archive.size / (1024 * 1024)
        notes = update.notes.strip() or "本次发布未提供说明。"
        message = (
            f"发现新版本 {update.version}\n"
            f"发布者：{update.publisher}\n"
            f"下载大小：{size_mib:.1f} MiB\n\n"
            f"{notes[:800]}\n\n"
            "是否下载到独立暂存区并验证 SHA-256？\n"
            "下载完成后不会自动安装或替换当前程序。"
        )
        if self._messagebox.askyesno("发现更新", message):
            self.update_button.configure(state="disabled")
            self.status.set(f"正在下载并校验版本 {update.version}…")
            threading.Thread(
                target=self._download_update,
                args=(update,),
                name="update-download",
                daemon=True,
            ).start()

    def _download_update(self, update: UpdateInfo) -> None:
        try:
            staged = download_and_verify_update(update, self.database_path.parent / "updates")
            prepared = prepare_update_installation(staged)
            self.events.put(("update_staged", prepared))
        except UpdateCheckError as exc:
            self.events.put(("update_failed", str(exc)))

    def _show_staged_update(self, staged: PreparedUpdate) -> None:
        self.update_button.configure(state="normal")
        self.status.set(f"版本 {staged.version} 已下载、校验并安全解包。")
        if not getattr(sys, "frozen", False):
            self._messagebox.showinfo(
                "更新已安全暂存",
                f"版本 {staged.version} 已准备完成。开发环境不会执行程序替换。\n\n"
                f"安装计划：{staged.plan_path}",
            )
            return
        if not self._messagebox.askyesno(
            "准备安装更新",
            f"版本 {staged.version} 已通过 SHA-256 校验。\n\n"
            "安装需要退出当前程序，旧版本程序文件将保留用于失败恢复；"
            "账本数据库不会移动或删除。是否现在安装？",
        ):
            return
        try:
            self._launch_update_helper(staged)
        except UpdateCheckError as exc:
            self._messagebox.showerror("无法安装更新", str(exc))

    def _launch_update_helper(self, staged: PreparedUpdate) -> None:
        suffix = ".exe" if sys.platform == "win32" else ""
        helper_name = f"FinancialBeancountUpdater{suffix}"
        installation_directory = Path(sys.executable).resolve().parent
        bundled_helper = installation_directory / helper_name
        if not bundled_helper.is_file():
            raise UpdateCheckError(f"应用包缺少更新助手：{helper_name}")
        staged_helper = staged.plan_path.parent / helper_name
        try:
            shutil.copy2(bundled_helper, staged_helper)
            subprocess.Popen(
                [
                    str(staged_helper),
                    "--plan",
                    str(staged.plan_path),
                    "--install-dir",
                    str(installation_directory),
                    "--launcher",
                    Path(sys.executable).name,
                    "--wait-pid",
                    str(os.getpid()),
                ],
                close_fds=True,
            )
        except OSError as exc:
            raise UpdateCheckError(f"无法启动更新助手：{exc}") from exc
        self.close()

    def close(self) -> None:
        self.stop_event.set()
        self.root.after(300, self.root.destroy)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="FinancialBeancount desktop application")
    parser.add_argument("--database", type=Path, default=default_database_path())
    parser.add_argument("--update-health-marker", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    import tkinter

    root = tkinter.Tk()
    controller = DesktopController(
        root,
        args.database.expanduser().resolve(),
        args.update_health_marker.resolve() if args.update_health_marker else None,
    )
    controller.start()
    root.mainloop()


if __name__ == "__main__":
    main()
