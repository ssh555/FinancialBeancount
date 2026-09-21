"""Extensible registry for official statement format adapters."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable

    from .statement_importer import ImportSummary, StatementImporter


class StatementAdapter(Protocol):
    """Public extension boundary implemented by built-in and third-party formats."""

    @property
    def format_id(self) -> str: ...

    @property
    def display_name(self) -> str: ...

    @property
    def extensions(self) -> tuple[str, ...]: ...

    def import_statement(
        self,
        importer: StatementImporter,
        path: str | Path,
        source_account: str,
        **options: Any,
    ) -> ImportSummary: ...


@dataclass(frozen=True)
class FunctionStatementAdapter:
    format_id: str
    display_name: str
    extensions: tuple[str, ...]
    function: Callable[..., ImportSummary]

    def import_statement(
        self,
        importer: StatementImporter,
        path: str | Path,
        source_account: str,
        **options: Any,
    ) -> ImportSummary:
        return self.function(importer, path, source_account, **options)


class StatementAdapterRegistry:
    """Explicit registry; PDF formats remain user-selected to avoid unsafe guessing."""

    def __init__(self) -> None:
        self._adapters: dict[str, StatementAdapter] = {}

    def register(self, adapter: StatementAdapter, *, replace: bool = False) -> None:
        format_id = adapter.format_id.strip().lower()
        if not format_id:
            raise ValueError("adapter format_id is required")
        if format_id in self._adapters and not replace:
            raise ValueError(f"statement adapter is already registered: {format_id}")
        extensions = tuple(_normalize_extension(value) for value in adapter.extensions)
        if not extensions:
            raise ValueError("adapter must declare at least one extension")
        if format_id != adapter.format_id or extensions != adapter.extensions:
            adapter = FunctionStatementAdapter(
                format_id=format_id,
                display_name=adapter.display_name,
                extensions=extensions,
                function=adapter.import_statement,
            )
        self._adapters[format_id] = adapter

    def get(self, format_id: str) -> StatementAdapter:
        try:
            return self._adapters[format_id.strip().lower()]
        except KeyError as exc:
            raise KeyError(f"unknown statement format: {format_id}") from exc

    def list_formats(self) -> tuple[StatementAdapter, ...]:
        return tuple(self._adapters[key] for key in sorted(self._adapters))

    def import_statement(
        self,
        importer: StatementImporter,
        format_id: str,
        path: str | Path,
        source_account: str,
        **options: Any,
    ) -> ImportSummary:
        adapter = self.get(format_id)
        suffix = Path(path).suffix.lower()
        if suffix not in adapter.extensions:
            raise ValueError(
                f"{adapter.format_id} expects {adapter.extensions}, received {suffix or 'no extension'}"
            )
        return adapter.import_statement(importer, path, source_account, **options)


def create_builtin_statement_registry() -> StatementAdapterRegistry:
    registry = StatementAdapterRegistry()
    registry.register(
        FunctionStatementAdapter(
            "wechat.xlsx",
            "微信支付官方 XLSX",
            (".xlsx",),
            lambda importer, path, account, **options: importer.import_wechat_xlsx(path, account),
        )
    )
    registry.register(
        FunctionStatementAdapter(
            "alipay.csv",
            "支付宝官方 CSV",
            (".csv",),
            lambda importer, path, account, **options: importer.import_alipay_csv(path, account),
        )
    )
    registry.register(
        FunctionStatementAdapter(
            "cmb.pdf",
            "招商银行官方 PDF",
            (".pdf",),
            lambda importer, path, account, **options: importer.import_cmb_pdf(path, account),
        )
    )
    registry.register(
        FunctionStatementAdapter(
            "icbc.pdf",
            "工商银行官方 PDF",
            (".pdf",),
            lambda importer, path, account, **options: importer.import_icbc_pdf(
                path, account, password=options.get("password")
            ),
        )
    )
    return registry


def _normalize_extension(value: str) -> str:
    extension = value.strip().lower()
    if not extension:
        raise ValueError("empty adapter extension")
    return extension if extension.startswith(".") else f".{extension}"
