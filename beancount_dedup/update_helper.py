"""External helper for atomically replacing a prepared desktop application."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from .updater import UpdateCheckError


@dataclass(frozen=True)
class AppliedUpdate:
    installation_directory: Path
    backup_directory: Path
    launcher: Path


def verify_installation_permissions(installation_directory: Path) -> None:
    """Probe the exact directories needed for an in-place swap without changing the install."""

    target = installation_directory.resolve()
    if not target.is_dir():
        raise UpdateCheckError("当前安装目录不存在")
    probes = (target, target.parent)
    created: list[Path] = []
    try:
        for directory in probes:
            probe = directory / f".financial-beancount-write-test-{os.getpid()}"
            with probe.open("xb") as stream:
                stream.write(b"permission-test")
            created.append(probe)
    except OSError as exc:
        raise UpdateCheckError(
            "当前用户无权修改应用安装目录；可使用管理员权限安装，或手动替换程序文件"
        ) from exc
    finally:
        for probe in created:
            with suppress(OSError):
                probe.unlink(missing_ok=True)


def rollback_applied_update(applied: AppliedUpdate) -> None:
    """Restore the retained binary backup when the new launcher cannot start."""
    failed = applied.installation_directory.with_name(
        f"{applied.installation_directory.name}.failed-update"
    )
    if failed.exists():
        raise UpdateCheckError(f"检测到尚未处理的失败更新目录：{failed}")
    try:
        applied.installation_directory.replace(failed)
        applied.backup_directory.replace(applied.installation_directory)
        shutil.rmtree(failed)
    except OSError as exc:
        raise UpdateCheckError(f"新版本启动失败且自动恢复未完成：{exc}") from exc


def wait_for_health_marker(
    process: subprocess.Popen[bytes], marker: Path, timeout: float = 60.0
) -> None:
    """Require the replacement application to report server readiness."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if marker.is_file():
            return
        if process.poll() is not None:
            raise UpdateCheckError("新版本在完成启动前退出")
        time.sleep(0.25)
    raise UpdateCheckError("新版本未在限定时间内完成启动")


def wait_for_process_exit(process_id: int, timeout: float = 300.0) -> None:
    """Wait until the old desktop process exits before replacing its files."""
    if sys.platform == "win32":
        _wait_for_windows_process(process_id, timeout)
        return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(process_id, 0)
        except OSError:
            return
        time.sleep(0.25)
    raise UpdateCheckError("等待旧版本退出超时，更新未安装")


def _wait_for_windows_process(process_id: int, timeout: float) -> None:
    """Wait without sending a signal; ``os.kill(pid, 0)`` terminates on Windows."""
    import ctypes

    synchronize = 0x00100000
    wait_object_0 = 0x00000000
    wait_timeout = 0x00000102
    handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, process_id)
    if not handle:
        return
    try:
        result = ctypes.windll.kernel32.WaitForSingleObject(handle, max(0, int(timeout * 1000)))
        if result == wait_object_0:
            return
        if result == wait_timeout:
            raise UpdateCheckError("等待旧版本退出超时，更新未安装")
        raise UpdateCheckError("无法确认旧版本是否已退出，更新未安装")
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def apply_prepared_application(
    source_directory: Path,
    installation_directory: Path,
    *,
    launcher_relative: Path,
) -> AppliedUpdate:
    """Copy, validate, swap, and retain one rollback-ready binary backup."""
    source = source_directory.resolve()
    target = installation_directory.resolve()
    parent = target.parent
    pending = parent / f".{target.name}.update-pending"
    backup = parent / f"{target.name}.previous"
    if not source.is_dir() or not target.is_dir():
        raise UpdateCheckError("更新源目录或当前安装目录不存在")
    if source == target or source.is_relative_to(target) or target.is_relative_to(source):
        raise UpdateCheckError("更新源目录与安装目录不能互相包含")
    if pending.exists():
        raise UpdateCheckError(f"检测到未完成的更新目录：{pending}")
    verify_installation_permissions(target)

    try:
        if backup.exists():
            shutil.rmtree(backup)
        shutil.copytree(source, pending)
        pending_launcher = pending / launcher_relative
        if not pending_launcher.is_file():
            raise UpdateCheckError(f"更新包缺少启动程序：{launcher_relative}")
        target.replace(backup)
        try:
            pending.replace(target)
        except Exception:
            if not target.exists() and backup.exists():
                backup.replace(target)
            raise
    except UpdateCheckError:
        _remove_pending(pending, parent)
        raise
    except OSError as exc:
        _remove_pending(pending, parent)
        raise UpdateCheckError(f"替换应用文件失败，已尝试恢复旧版本：{exc}") from exc
    return AppliedUpdate(target, backup, target / launcher_relative)


def load_install_plan(plan_path: Path) -> dict[str, object]:
    try:
        value = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError) as exc:
        raise UpdateCheckError(f"无法读取安装计划：{exc}") from exc
    if not isinstance(value, dict) or value.get("format_version") != 1:
        raise UpdateCheckError("安装计划格式不受支持")
    return value


def _remove_pending(path: Path, parent: Path) -> None:
    resolved = path.resolve()
    if resolved.parent != parent.resolve() or not resolved.name.startswith("."):
        raise UpdateCheckError("拒绝清理安装目录以外的路径")
    if resolved.exists():
        shutil.rmtree(resolved)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--install-dir", type=Path, required=True)
    parser.add_argument("--launcher", type=Path, required=True)
    parser.add_argument("--wait-pid", type=int, required=True)
    args = parser.parse_args(argv)
    old_application_exited = False
    try:
        plan = load_install_plan(args.plan)
        source = plan.get("application_directory")
        if not isinstance(source, str):
            raise UpdateCheckError("安装计划缺少应用目录")
        wait_for_process_exit(args.wait_pid)
        old_application_exited = True
        applied = apply_prepared_application(
            Path(source), args.install_dir, launcher_relative=args.launcher
        )
        health_marker = args.plan.with_name("install-health.ok")
        health_marker.unlink(missing_ok=True)
        try:
            process = subprocess.Popen(
                [str(applied.launcher), "--update-health-marker", str(health_marker)],
                close_fds=True,
            )
            wait_for_health_marker(process, health_marker)
        except (OSError, UpdateCheckError):
            rollback_applied_update(applied)
            raise UpdateCheckError("新版本未能健康启动，已自动恢复旧版本") from None
    except UpdateCheckError as exc:
        error_path = args.plan.with_name("install-error.log")
        error_path.write_text(str(exc), encoding="utf-8")
        if old_application_exited:
            launcher = args.install_dir / args.launcher
            if launcher.is_file():
                with suppress(OSError):
                    subprocess.Popen([str(launcher)], close_fds=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
