"""Tests for the public statement-adapter extension boundary."""

import hashlib
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from beancount_dedup.ledger_models import RawTransaction
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
    @dataclass(frozen=True)
    class ExampleAdapter:
        format_id: str = "example.json"
        display_name: str = "示例银行 JSON"
        extensions: tuple[str, ...] = (".json",)

        def import_statement(self, importer, path, source_account, **options):
            statement = Path(path)
            return importer.persist(
                "example-bank",
                statement.name,
                hashlib.sha256(statement.read_bytes()).hexdigest(),
                [
                    RawTransaction(
                        source="example-bank",
                        source_account=source_account,
                        booking_date=date(2026, 9, 25),
                        amount=Decimal("12.34"),
                        direction="expense",
                        merchant="示例商户",
                        original_row={"provider_field": "kept"},
                        source_file=statement.name,
                        source_file_hash="adapter-owned",
                        raw_row_number=1,
                    )
                ],
                [],
            )

    registry = StatementAdapterRegistry()
    registry.register(ExampleAdapter())
    statement = tmp_path / "statement.json"
    statement.write_text("{}", encoding="utf-8")
    with LedgerStore(tmp_path / "ledger.sqlite3") as store:
        importer = StatementImporter(store, registry)
        result = importer.import_statement(
            "example.json", statement, "example-account", locale="zh-CN"
        )
        raw_id = store.connection.execute(
            "SELECT raw_id FROM raw_transactions WHERE import_batch_id = ?", (result.batch_id,)
        ).fetchone()[0]
        raw = store.get_raw(raw_id)

    assert result.source == "example-bank"
    assert raw is not None and raw.source == "example-bank"
    assert raw.original_row == {"provider_field": "kept"}


def test_duplicate_adapter_requires_explicit_replace():
    registry = create_builtin_statement_registry()
    adapter = registry.get("alipay.csv")

    with pytest.raises(ValueError, match="already registered"):
        registry.register(adapter)

    registry.register(adapter, replace=True)
