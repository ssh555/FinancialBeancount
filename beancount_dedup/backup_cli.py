"""Command-line inspection and recovery for binary ledger backups."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .backup import BackupError, inspect_backup, restore_backup


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="financial-beancount-backup",
        description="Validate or restore a checksummed FinancialBeancount database backup",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    inspect_parser = commands.add_parser("inspect", help="Validate a backup without changing data")
    inspect_parser.add_argument("--backup", required=True)
    restore_parser = commands.add_parser("restore", help="Restore a backup while the app is closed")
    restore_parser.add_argument("--backup", required=True)
    restore_parser.add_argument("--database", required=True)
    restore_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace an existing database after validating the backup",
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            manifest = inspect_backup(args.backup)
            _write_json(
                {
                    "action": "inspect",
                    "backup": str(Path(args.backup).resolve()),
                    "valid": True,
                    "manifest": manifest.to_dict(),
                }
            )
        else:
            manifest = restore_backup(args.backup, args.database, overwrite=args.overwrite)
            _write_json(
                {
                    "action": "restore",
                    "backup": str(Path(args.backup).resolve()),
                    "database": str(Path(args.database).resolve()),
                    "restored": True,
                    "manifest": manifest.to_dict(),
                }
            )
    except (BackupError, FileExistsError, OSError) as exc:
        _write_json({"error": {"code": "backup_error", "message": str(exc)}}, stream=sys.stderr)
        return 2
    return 0


def _write_json(value: dict[str, Any], *, stream: Any | None = None) -> None:
    output = stream if stream is not None else sys.stdout
    output.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
