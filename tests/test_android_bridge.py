import json
import base64
from pathlib import Path

import pytest
from beancount_dedup.android_bridge import (
    dispatch,
    restore_archive,
    web_asset,
    web_asset_content_type,
)
from beancount_dedup.ledger_store import LedgerStore
from beancount_dedup.portable_archive import export_portable_archive


def _call(database: Path, method: str, target: str, body=None) -> dict:
    request = {"method": method, "target": target}
    if body is not None:
        request["body"] = body
    return json.loads(dispatch(str(database.resolve()), json.dumps(request, ensure_ascii=False)))


def test_android_bridge_uses_same_health_schema_and_private_database(tmp_path: Path) -> None:
    database = tmp_path / "app-private" / "ledger.sqlite3"
    response = _call(database, "GET", "/api/v1/health")
    assert response["status"] == 200
    assert response["body"]["data"]["api_version"] == "v1"
    assert database.is_file()


def test_android_bridge_supports_canonical_crud_without_localhost(tmp_path: Path) -> None:
    database = tmp_path / "ledger.sqlite3"
    created = _call(
        database,
        "POST",
        "/api/v1/transactions",
        {
            "booking_date": "2026-09-27",
            "transaction_time": "2026-09-27T08:00:00",
            "amount": "-25.50",
            "direction": "expense",
            "merchant": "移动端测试",
            "tx_type": "expense",
            "actor": "android-user",
        },
    )
    canonical_id = created["body"]["data"]["canonical_id"]
    listed = _call(database, "GET", "/api/v1/transactions?page=1&page_size=20")
    assert listed["status"] == 200
    assert listed["body"]["data"][0]["canonical_id"] == canonical_id
    assert listed["body"]["data"][0]["merchant"] == "移动端测试"


def test_android_bridge_rejects_non_object_body_and_relative_database(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="body"):
        dispatch(
            str((tmp_path / "ledger.sqlite3").resolve()),
            '{"method":"POST","target":"/api/v1/transactions","body":[]}',
        )
    with pytest.raises(ValueError, match="absolute"):
        dispatch("ledger.sqlite3", '{"method":"GET","target":"/api/v1/health"}')


def test_android_web_assets_are_allowlisted() -> None:
    assert b"<!doctype html>" in web_asset("/index.html").lower()
    assert web_asset_content_type("/app.js").startswith("text/javascript")
    with pytest.raises(ValueError, match="allowlisted"):
        web_asset("/../../ledger.sqlite3")


def test_android_bridge_restores_complete_archive_atomically(tmp_path: Path) -> None:
    source_database = tmp_path / "source.sqlite3"
    _call(
        source_database,
        "POST",
        "/api/v1/transactions",
        {
            "booking_date": "2026-09-27",
            "amount": "-88.00",
            "direction": "expense",
            "merchant": "完整账本迁移",
            "tx_type": "expense",
            "actor": "acceptance",
        },
    )
    archive = tmp_path / "complete-ledger.financial-beancount.zip"
    source = LedgerStore(source_database)
    export_portable_archive(source, archive)
    source.close()

    destination = tmp_path / "android-private" / "ledger.sqlite3"
    _call(destination, "GET", "/api/v1/health")
    manifest = json.loads(
        restore_archive(str(destination.resolve()), base64.b64encode(archive.read_bytes()).decode())
    )

    assert manifest["format"] == "financial-beancount-portable"
    listed = _call(destination, "GET", "/api/v1/transactions?page=1&page_size=20")
    assert listed["body"]["data"][0]["merchant"] == "完整账本迁移"


def test_android_bridge_rejects_invalid_archive_without_replacing_ledger(tmp_path: Path) -> None:
    destination = tmp_path / "ledger.sqlite3"
    _call(destination, "GET", "/api/v1/health")
    before = destination.read_bytes()
    with pytest.raises(ValueError, match="archive"):
        restore_archive(str(destination.resolve()), base64.b64encode(b"not-a-zip").decode())
    assert destination.read_bytes() == before
