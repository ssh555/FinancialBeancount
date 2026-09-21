"""Tests for the public statement-adapter extension boundary."""

from dataclasses import dataclass
from pathlib import Path

import pytest
from beancount_dedup.ledger_store import LedgerStore
from beancount_dedup.statement_adapters import (
    StatementAdapterRegistry,
    create_builtin_statement_registry,
)
from beancount_dedup.statement_importer import StatementImporter


def test_builtin_registry_exposes_stable_format_capabilities():
    formats = create_builtin_statement_registry().list_formats()

    assert [item.format_id for item in formats] == [
        "alipay.csv",
        "cmb.pdf",
        "icbc.pdf",
        "wechat.xlsx",
    ]
    assert next(item for item in formats if item.format_id == "cmb.pdf").extensions == (".pdf",)


def test_unknown_and_wrong_extension_are_rejected_before_parsing(tmp_path):
    registry = create_builtin_statement_registry()
    with LedgerStore(tmp_path / "ledger.sqlite3") as store:
        importer = StatementImporter(store, registry)
        with pytest.raises(KeyError, match="unknown statement format"):
            importer.import_statement("future.bank", tmp_path / "statement.pdf", "account")
        with pytest.raises(ValueError, match="expects"):
            importer.import_statement("alipay.csv", tmp_path / "statement.xlsx", "account")


def test_third_party_adapter_can_be_registered_without_core_changes(tmp_path):
    calls = []

    @dataclass(frozen=True)
    class ExampleAdapter:
        format_id: str = "example.json"
        display_name: str = "示例银行 JSON"
        extensions: tuple[str, ...] = (".json",)

        def import_statement(self, importer, path, source_account, **options):
            calls.append((Path(path).name, source_account, options))
            return "extension-result"

    registry = StatementAdapterRegistry()
    registry.register(ExampleAdapter())
    with LedgerStore(tmp_path / "ledger.sqlite3") as store:
        importer = StatementImporter(store, registry)
        result = importer.import_statement(
            "example.json", tmp_path / "statement.json", "example-account", locale="zh-CN"
        )

    assert result == "extension-result"
    assert calls == [("statement.json", "example-account", {"locale": "zh-CN"})]


def test_duplicate_adapter_requires_explicit_replace():
    registry = create_builtin_statement_registry()
    adapter = registry.get("alipay.csv")

    with pytest.raises(ValueError, match="already registered"):
        registry.register(adapter)

    registry.register(adapter, replace=True)
