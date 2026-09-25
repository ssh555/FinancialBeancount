"""Built-in official statement adapters, isolated from the ledger import core."""

from __future__ import annotations

import csv
from decimal import InvalidOperation
from pathlib import Path
from typing import Any

from .models import Platform
from .statement_importer import (
    ALIPAY_HEADERS,
    WECHAT_HEADERS,
    ImportSummary,
    StatementImporter,
    _alipay_raw,
    _balance_chain_errors,
    _cell_text,
    _cmb_raw,
    _decode_csv,
    _extract_cmb_page,
    _file_sha256,
    _filename_password,
    _find_header,
    _icbc_raw,
    _icbc_row,
    _is_icbc_header,
    _load_pdfplumber,
    _row_dict,
    _wechat_raw,
)


def import_wechat_xlsx(
    importer: StatementImporter, path: str | Path, source_account: str, **options: Any
) -> ImportSummary:
    del options
    try:
        import openpyxl
    except ImportError as exc:
        raise RuntimeError("openpyxl is required for WeChat XLSX import") from exc

    statement_path = Path(path)
    file_hash = _file_sha256(statement_path)
    workbook = openpyxl.load_workbook(statement_path, read_only=True, data_only=True)
    try:
        worksheet = workbook.active
        rows = list(worksheet.iter_rows(values_only=True))
    finally:
        workbook.close()

    header_index, headers = _find_header(rows, WECHAT_HEADERS)
    parsed = []
    errors = []
    for zero_based_index, values in enumerate(rows[header_index + 1 :], header_index + 1):
        row_number = zero_based_index + 1
        row = _row_dict(headers, values)
        if not any(row.values()):
            continue
        try:
            parsed.append(
                _wechat_raw(
                    row,
                    row_number=row_number,
                    source_account=source_account,
                    source_file=statement_path.name,
                    source_file_hash=file_hash,
                )
            )
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            errors.append(f"row {row_number}: {exc}")
    return importer.persist(Platform.WECHAT, statement_path.name, file_hash, parsed, errors)


def import_alipay_csv(
    importer: StatementImporter, path: str | Path, source_account: str, **options: Any
) -> ImportSummary:
    del options
    statement_path = Path(path)
    file_hash = _file_sha256(statement_path)
    text = _decode_csv(statement_path.read_bytes())
    rows = list(csv.reader(text.splitlines()))
    header_index, headers = _find_header(rows, ALIPAY_HEADERS)
    parsed = []
    errors = []
    for zero_based_index, values in enumerate(rows[header_index + 1 :], header_index + 1):
        row_number = zero_based_index + 1
        row = _row_dict(headers, values)
        if not any(row.values()):
            continue
        try:
            parsed.append(
                _alipay_raw(
                    row,
                    row_number=row_number,
                    source_account=source_account,
                    source_file=statement_path.name,
                    source_file_hash=file_hash,
                )
            )
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            errors.append(f"row {row_number}: {exc}")
    return importer.persist(Platform.ALIPAY, statement_path.name, file_hash, parsed, errors)


def import_cmb_pdf(
    importer: StatementImporter, path: str | Path, source_account: str, **options: Any
) -> ImportSummary:
    del options
    pdfplumber = _load_pdfplumber()
    statement_path = Path(path)
    file_hash = _file_sha256(statement_path)
    parsed = []
    errors = []
    with pdfplumber.open(statement_path) as pdf:
        for page_number, page in enumerate(pdf.pages, 1):
            records = _extract_cmb_page(page, page_number)
            for record_number, row in enumerate(records, 1):
                row_number = page_number * 10000 + record_number
                try:
                    parsed.append(
                        _cmb_raw(
                            row,
                            row_number=row_number,
                            source_account=source_account,
                            source_file=statement_path.name,
                            source_file_hash=file_hash,
                        )
                    )
                except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
                    errors.append(f"page {page_number} record {record_number}: {exc}")
    errors.extend(_balance_chain_errors(parsed))
    return importer.persist(Platform.BANK, statement_path.name, file_hash, parsed, errors)


def import_icbc_pdf(
    importer: StatementImporter, path: str | Path, source_account: str, **options: Any
) -> ImportSummary:
    pdfplumber = _load_pdfplumber()
    statement_path = Path(path)
    file_hash = _file_sha256(statement_path)
    effective_password = options.get("password") or _filename_password(statement_path)
    parsed = []
    errors = []
    with pdfplumber.open(statement_path, password=effective_password) as pdf:
        for page_number, page in enumerate(pdf.pages, 1):
            transaction_layer = page.filter(
                lambda obj: obj.get("object_type") != "char" or float(obj.get("size", 0)) <= 7.1
            )
            tables = transaction_layer.extract_tables()
            if len(tables) != 1:
                errors.append(
                    f"page {page_number}: expected one transaction table, found {len(tables)}"
                )
                continue
            table = tables[0]
            if not table or not _is_icbc_header(table[0]):
                errors.append(f"page {page_number}: ICBC table header is invalid")
                continue
            for record_number, values in enumerate(table[1:], 1):
                if not any(_cell_text(value) for value in values):
                    continue
                row_number = page_number * 10000 + record_number
                row = _icbc_row(values)
                try:
                    parsed.append(
                        _icbc_raw(
                            row,
                            row_number=row_number,
                            source_account=source_account,
                            source_file=statement_path.name,
                            source_file_hash=file_hash,
                        )
                    )
                except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
                    errors.append(f"page {page_number} record {record_number}: {exc}")
    errors.extend(_balance_chain_errors(parsed))
    return importer.persist(Platform.BANK, statement_path.name, file_hash, parsed, errors)
