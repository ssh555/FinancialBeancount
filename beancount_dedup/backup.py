"""Versioned, checksummed ledger backup and restore."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .ledger_store import SCHEMA_VERSION, LedgerStore

BACKUP_FORMAT = "financial-beancount-ledger"
BACKUP_FORMAT_VERSION = 1
DATABASE_MEMBER = "ledger.sqlite3"
MANIFEST_MEMBER = "manifest.json"


class BackupError(ValueError):
    """Raised when a backup is invalid, incompatible, or unsafe to restore."""


@dataclass(frozen=True)
class BackupManifest:
    format: str
    format_version: int
    schema_version: int
    created_at: str
    database_sha256: str

    def to_dict(self) -> dict[str, str | int]:
        return {
            "format": self.format,
            "format_version": self.format_version,
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "database_sha256": self.database_sha256,
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def export_backup(store: LedgerStore, output_path: str | Path) -> BackupManifest:
    """Create a consistent backup while the application database is open."""

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp_directory:
        database_copy = Path(temp_directory) / DATABASE_MEMBER
        copy_connection = sqlite3.connect(database_copy)
        try:
            store.connection.backup(copy_connection)
        finally:
            copy_connection.close()

        manifest = BackupManifest(
            format=BACKUP_FORMAT,
            format_version=BACKUP_FORMAT_VERSION,
            schema_version=_connection_schema_version(store.connection),
            created_at=datetime.now(timezone.utc).isoformat(),
            database_sha256=_sha256(database_copy),
        )
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(database_copy, DATABASE_MEMBER)
            archive.writestr(
                MANIFEST_MEMBER,
                json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2, sort_keys=True),
            )
    return manifest


def _connection_schema_version(connection: sqlite3.Connection) -> int:
    try:
        row = connection.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()
        if row is None:
            raise BackupError("ledger does not declare a schema version")
        return int(row[0])
    except (sqlite3.DatabaseError, TypeError, ValueError) as exc:
        raise BackupError("ledger schema version cannot be read") from exc


def inspect_backup(backup_path: str | Path) -> BackupManifest:
    """Validate a backup without changing any local ledger."""

    source = Path(backup_path)
    with tempfile.TemporaryDirectory() as temp_directory:
        extracted_database, manifest = _validate_and_extract(source, Path(temp_directory))
        _validate_database(extracted_database, manifest.schema_version)
    return manifest


def restore_backup(
    backup_path: str | Path,
    destination_path: str | Path,
    *,
    overwrite: bool = False,
) -> BackupManifest:
    """Restore a validated ledger backup, refusing overwrite by default."""

    source = Path(backup_path)
    destination = Path(destination_path)
    if destination.exists() and not overwrite:
        raise FileExistsError(f"destination already exists: {destination}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temp_directory:
        extracted_database, manifest = _validate_and_extract(source, Path(temp_directory))
        _validate_database(extracted_database, manifest.schema_version)
        staged_destination = Path(temp_directory) / "restored.sqlite3"
        shutil.copy2(extracted_database, staged_destination)
        staged_destination.replace(destination)
    return manifest


def _validate_and_extract(source: Path, destination: Path) -> tuple[Path, BackupManifest]:
    try:
        with zipfile.ZipFile(source) as archive:
            names = set(archive.namelist())
            required = {MANIFEST_MEMBER, DATABASE_MEMBER}
            if not required.issubset(names):
                raise BackupError("backup is missing manifest.json or ledger.sqlite3")
            manifest_data = json.loads(archive.read(MANIFEST_MEMBER))
            database_bytes = archive.read(DATABASE_MEMBER)
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        raise BackupError("backup cannot be read") from exc

    try:
        manifest = BackupManifest(
            format=str(manifest_data["format"]),
            format_version=int(manifest_data["format_version"]),
            schema_version=int(manifest_data["schema_version"]),
            created_at=str(manifest_data["created_at"]),
            database_sha256=str(manifest_data["database_sha256"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise BackupError("backup manifest is invalid") from exc

    if manifest.format != BACKUP_FORMAT:
        raise BackupError("unsupported backup format")
    if manifest.format_version > BACKUP_FORMAT_VERSION:
        raise BackupError("backup format is newer than this application")
    if manifest.schema_version > SCHEMA_VERSION:
        raise BackupError("ledger schema is newer than this application")

    database_path = destination / DATABASE_MEMBER
    database_path.write_bytes(database_bytes)
    if _sha256(database_path) != manifest.database_sha256:
        raise BackupError("database checksum does not match the manifest")
    return database_path, manifest


def _validate_database(database_path: Path, expected_schema_version: int) -> None:
    try:
        connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
        try:
            integrity = connection.execute("PRAGMA quick_check").fetchone()
            schema_row = connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
        finally:
            connection.close()
    except sqlite3.DatabaseError as exc:
        raise BackupError("backup does not contain a valid ledger database") from exc

    if not integrity or integrity[0] != "ok":
        raise BackupError("ledger database integrity check failed")
    if not schema_row or int(schema_row[0]) != expected_schema_version:
        raise BackupError("manifest and ledger schema versions do not match")
