"""Open, versioned JSONL archive for moving a complete ledger between devices."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .ledger_store import SCHEMA_VERSION, LedgerStore

PORTABLE_FORMAT_VERSION = 1
TABLE_ORDER = (
    "import_batches",
    "raw_transactions",
    "import_occurrences",
    "canonical_transactions",
    "source_record_links",
    "review_sessions",
    "review_items",
    "review_events",
    "match_candidates",
    "match_candidate_events",
    "transaction_relationships",
    "transaction_relationship_events",
    "classification_candidates",
    "classification_events",
)


class PortableArchiveError(ValueError):
    """The archive is invalid, incompatible, or unsafe to import."""


@dataclass(frozen=True)
class PortableArchiveManifest:
    format_version: int
    schema_version: int
    exported_at: datetime
    tables: dict[str, dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": "financial-beancount-portable",
            "format_version": self.format_version,
            "schema_version": self.schema_version,
            "exported_at": self.exported_at.isoformat(),
            "tables": self.tables,
        }


def export_portable_archive(store: LedgerStore, destination: str | Path) -> PortableArchiveManifest:
    """Export every durable ledger and audit table as checksum-protected JSONL."""

    destination_path = Path(destination)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    payloads: dict[str, bytes] = {}
    table_metadata: dict[str, dict[str, Any]] = {}
    for table in TABLE_ORDER:
        rows = store.connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
        payload = "".join(
            json.dumps(dict(row), ensure_ascii=False, sort_keys=True, default=str) + "\n"
            for row in rows
        ).encode("utf-8")
        name = f"data/{table}.jsonl"
        payloads[name] = payload
        table_metadata[table] = {
            "file": name,
            "rows": len(rows),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    manifest = PortableArchiveManifest(
        format_version=PORTABLE_FORMAT_VERSION,
        schema_version=SCHEMA_VERSION,
        exported_at=datetime.now(),
        tables=table_metadata,
    )
    with zipfile.ZipFile(destination_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2, sort_keys=True),
        )
        for name, payload in payloads.items():
            archive.writestr(name, payload)
    return manifest


def inspect_portable_archive(source: str | Path) -> PortableArchiveManifest:
    """Validate archive structure, checksums, table names, and row counts."""

    try:
        with zipfile.ZipFile(source, "r") as archive:
            manifest_data = json.loads(archive.read("manifest.json"))
            manifest = _manifest_from_dict(manifest_data)
            _validate_manifest(manifest)
            for table, metadata in manifest.tables.items():
                payload = archive.read(metadata["file"])
                if hashlib.sha256(payload).hexdigest() != metadata["sha256"]:
                    raise PortableArchiveError(f"checksum mismatch: {table}")
                rows = [line for line in payload.splitlines() if line.strip()]
                if len(rows) != metadata["rows"]:
                    raise PortableArchiveError(f"row count mismatch: {table}")
                for line in rows:
                    value = json.loads(line)
                    if not isinstance(value, dict):
                        raise PortableArchiveError(f"JSONL row is not an object: {table}")
    except (KeyError, OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        raise PortableArchiveError(f"invalid portable archive: {exc}") from exc
    return manifest


def import_portable_archive(source: str | Path, destination: str | Path) -> LedgerStore:
    """Restore an archive into an empty local database while preserving all IDs."""

    manifest = inspect_portable_archive(source)
    destination_path = Path(destination)
    if destination_path.exists():
        raise PortableArchiveError(f"destination already exists: {destination_path}")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, staged_name = tempfile.mkstemp(
        prefix=f".{destination_path.name}.", suffix=".staging", dir=destination_path.parent
    )
    os.close(descriptor)
    Path(staged_name).unlink()
    store = LedgerStore(staged_name)
    try:
        with zipfile.ZipFile(source, "r") as archive, store.transaction() as connection:
            for table in TABLE_ORDER:
                metadata = manifest.tables[table]
                expected_columns = {
                    row["name"]
                    for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
                }
                for line in archive.read(metadata["file"]).decode("utf-8").splitlines():
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    if set(row) != expected_columns:
                        raise PortableArchiveError(f"invalid column set for table: {table}")
                    columns = tuple(row)
                    placeholders = ", ".join("?" for _ in columns)
                    names = ", ".join(columns)
                    connection.execute(
                        f"INSERT INTO {table} ({names}) VALUES ({placeholders})",
                        tuple(row[column] for column in columns),
                    )
        store.close()
        Path(staged_name).replace(destination_path)
        return LedgerStore(destination_path)
    except Exception:
        store.close()
        Path(staged_name).unlink(missing_ok=True)
        raise


def _manifest_from_dict(value: dict[str, Any]) -> PortableArchiveManifest:
    if value.get("format") != "financial-beancount-portable":
        raise PortableArchiveError("unsupported archive format")
    return PortableArchiveManifest(
        format_version=int(value["format_version"]),
        schema_version=int(value["schema_version"]),
        exported_at=datetime.fromisoformat(value["exported_at"]),
        tables=value["tables"],
    )


def _validate_manifest(manifest: PortableArchiveManifest) -> None:
    if manifest.format_version != PORTABLE_FORMAT_VERSION:
        raise PortableArchiveError("unsupported portable format version")
    if manifest.schema_version > SCHEMA_VERSION:
        raise PortableArchiveError("archive schema is newer than this application")
    if set(manifest.tables) != set(TABLE_ORDER):
        raise PortableArchiveError("archive table set is incomplete or unexpected")
    for table, metadata in manifest.tables.items():
        if metadata.get("file") != f"data/{table}.jsonl":
            raise PortableArchiveError(f"invalid archive path for table: {table}")
        if not isinstance(metadata.get("rows"), int) or metadata["rows"] < 0:
            raise PortableArchiveError(f"invalid row count for table: {table}")
        checksum = metadata.get("sha256")
        if not isinstance(checksum, str) or len(checksum) != 64:
            raise PortableArchiveError(f"invalid checksum for table: {table}")
