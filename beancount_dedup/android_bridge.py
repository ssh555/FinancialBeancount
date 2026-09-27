"""Small JSON boundary for an embedded Android Python runtime."""

from __future__ import annotations

import json
import base64
import binascii
import os
import tempfile
from pathlib import Path
from typing import Any

from .ledger_store import LedgerStore
from .mobile_api import MobileLedgerApi, load_web_asset
from .portable_archive import import_portable_archive, inspect_portable_archive


def dispatch(database_path: str, request_json: str) -> str:
    """Dispatch one native request without opening a socket or exposing filesystem access."""
    request = _object(json.loads(request_json))
    method = _text(request, "method").upper()
    target = _text(request, "target")
    body = request.get("body")
    if body is not None and not isinstance(body, dict):
        raise TypeError("body must be an object or null")
    store = LedgerStore(_private_database_path(database_path))
    try:
        response = MobileLedgerApi(store).dispatch(method, target, body)
    finally:
        store.close()
    return json.dumps(
        {"status": response.status, "body": response.body},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def restore_archive(database_path: str, content_base64: str) -> str:
    """Validate and atomically replace the app-private ledger with a portable archive."""
    destination = _private_database_path(database_path)
    try:
        content = base64.b64decode(content_base64, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("portable archive content is not valid base64") from exc
    if len(content) > 200 * 1024 * 1024:
        raise ValueError("portable archive exceeds the 200 MiB limit")

    descriptor, staged_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".restore", dir=destination.parent
    )
    os.close(descriptor)
    staged = Path(staged_name)
    staged.unlink()
    try:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "ledger.financial-beancount.zip"
            archive.write_bytes(content)
            manifest = inspect_portable_archive(archive)
            restored = import_portable_archive(archive, staged)
            restored.close()
        staged.replace(destination)
        return json.dumps(manifest.to_dict(), ensure_ascii=False, separators=(",", ":"))
    finally:
        staged.unlink(missing_ok=True)


def web_asset(asset_path: str) -> bytes:
    """Return only a bundled allowlisted web asset for Android WebViewAssetLoader."""
    asset = load_web_asset(asset_path)
    if asset is None:
        raise ValueError("web asset is not allowlisted")
    return asset.body


def web_asset_content_type(asset_path: str) -> str:
    asset = load_web_asset(asset_path)
    if asset is None:
        raise ValueError("web asset is not allowlisted")
    return asset.content_type


def _private_database_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("database path must be absolute")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError("request must be an object")
    return value


def _text(value: dict[str, Any], key: str) -> str:
    selected = value.get(key)
    if not isinstance(selected, str) or not selected.strip():
        raise TypeError(f"{key} must be a non-empty string")
    return selected
