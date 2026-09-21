"""Command-line access to the open portable ledger archive."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .ledger_store import LedgerStore
from .portable_archive import (
    PortableArchiveError,
    export_portable_archive,
    import_portable_archive,
    inspect_portable_archive,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="financial-beancount-archive",
        description="Export, validate, and restore an offline portable ledger archive",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export", help="Export a database to JSONL ZIP")
    export_parser.add_argument("--database", required=True)
    export_parser.add_argument("--output", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="Validate an archive")
    inspect_parser.add_argument("--archive", required=True)

    import_parser = subparsers.add_parser("import", help="Restore into a new empty database")
    import_parser.add_argument("--archive", required=True)
    import_parser.add_argument("--database", required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "export":
            with LedgerStore(args.database) as store:
                manifest = export_portable_archive(store, args.output)
            _write_json(
                {
                    "action": "export",
                    "archive": str(Path(args.output).resolve()),
                    "manifest": manifest.to_dict(),
                }
            )
        elif args.command == "inspect":
            manifest = inspect_portable_archive(args.archive)
            _write_json(
                {
                    "action": "inspect",
                    "archive": str(Path(args.archive).resolve()),
                    "valid": True,
                    "manifest": manifest.to_dict(),
                }
            )
        else:
            destination = Path(args.database)
            if destination.exists():
                raise PortableArchiveError(f"destination already exists: {destination}")
            restored = import_portable_archive(args.archive, destination)
            restored.close()
            _write_json(
                {
                    "action": "import",
                    "archive": str(Path(args.archive).resolve()),
                    "database": str(destination.resolve()),
                    "restored": True,
                }
            )
    except (OSError, PortableArchiveError) as exc:
        _write_json({"error": {"code": "archive_error", "message": str(exc)}}, stream=sys.stderr)
        return 2
    return 0


def _write_json(value: dict[str, Any], *, stream: Any | None = None) -> None:
    output = stream if stream is not None else sys.stdout
    output.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
