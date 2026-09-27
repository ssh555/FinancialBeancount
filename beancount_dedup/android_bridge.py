"""Small JSON boundary for an embedded Android Python runtime."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .ledger_store import LedgerStore
from .mobile_api import MobileLedgerApi, load_web_asset


def dispatch(database_path: str, request_json: str) -> str:
    """Dispatch one native request without opening a socket or exposing filesystem access."""
    request = _object(json.loads(request_json))
    method = _text(request, "method").upper()
    target = _text(request, "target")
    body = request.get("body")
    if body is not None and not isinstance(body, dict):
        raise TypeError("body must be an object or null")
    store = LedgerStore(_private_database_path(database_path))
    response = MobileLedgerApi(store).dispatch(method, target, body)
    return json.dumps(
        {"status": response.status, "body": response.body},
        ensure_ascii=False,
        separators=(",", ":"),
    )


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
