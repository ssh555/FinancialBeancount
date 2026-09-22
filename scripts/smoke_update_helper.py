"""Exercise the packaged update helper against disposable application directories."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    suffix = ".exe" if sys.platform == "win32" else ""
    helper = Path("dist") / "FinancialBeancount" / f"FinancialBeancountUpdater{suffix}"
    if not helper.is_file():
        raise RuntimeError(f"packaged update helper is missing: {helper}")

    with tempfile.TemporaryDirectory(prefix="financial-beancount-update-") as temporary:
        root = Path(temporary)
        source = root / "staged" / "FinancialBeancount"
        target = root / "installed" / "FinancialBeancount"
        source.mkdir(parents=True)
        target.mkdir(parents=True)
        launcher_name = f"launcher{suffix}"
        if sys.platform == "win32":
            system_launcher = Path(os.environ["SYSTEMROOT"]) / "System32" / "where.exe"
        else:
            system_launcher = Path("/bin/true")
        if sys.platform == "win32":
            launcher_name = "launcher.cmd"
            (source / launcher_name).write_text(
                "@echo off\r\necho ready>\"%2\"\r\n",
                encoding="utf-8",
            )
        else:
            launcher_name = "launcher"
            (source / launcher_name).write_text(
                "#!/bin/sh\nprintf 'ready\\n' > \"$2\"\n",
                encoding="utf-8",
            )
            (source / launcher_name).chmod(0o755)
        shutil.copy2(system_launcher, target / launcher_name)
        (source / "build-marker.txt").write_text("new", encoding="utf-8")
        (target / "build-marker.txt").write_text("old", encoding="utf-8")
        plan = root / "staged" / "install-plan.json"
        plan.write_text(
            json.dumps(
                {
                    "format_version": 1,
                    "version": "smoke-test",
                    "application_directory": str(source),
                }
            ),
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                str(helper.resolve()),
                "--plan",
                str(plan),
                "--install-dir",
                str(target),
                "--launcher",
                launcher_name,
                "--wait-pid",
                "2147483647",
            ],
            check=False,
            timeout=60,
        )
        if result.returncode != 0:
            error = plan.with_name("install-error.log")
            detail = error.read_text(encoding="utf-8") if error.exists() else "no error log"
            raise RuntimeError(f"update helper failed: {detail}")
        backup = target.with_name(f"{target.name}.previous")
        assert (target / "build-marker.txt").read_text(encoding="utf-8") == "new"
        assert (backup / "build-marker.txt").read_text(encoding="utf-8") == "old"
        print(f"verified packaged update helper: {helper}")


if __name__ == "__main__":
    main()
