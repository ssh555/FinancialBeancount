"""Strict import of official Alipay CSV and WeChat XLSX statements."""

from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .statement_adapters import StatementAdapterRegistry

from .ledger_models import RawTransaction
from .ledger_store import LedgerStore
from .models import Platform
from .review import ImportReviewService

WECHAT_HEADERS = {
    "交易时间",
    "交易类型",
    "交易对方",
    "商品",
    "收/支",
    "金额(元)",
    "支付方式",
    "当前状态",
    "交易单号",
    "商户单号",
}
ALIPAY_HEADERS = {
    "交易时间",
    "交易分类",
    "交易对方",
    "商品说明",
    "收/支",
    "金额",
    "收/付款方式",
    "交易状态",
    "交易订单号",
    "商家订单号",
}


class StatementImportError(ValueError):
    """Raised when any transaction row cannot be imported safely."""


@dataclass(frozen=True)
class ImportSummary:
    batch_id: str
    import_run_id: str
    source: Platform
    parsed_count: int
    created_count: int
    existing_count: int
    file_already_imported: bool
    review_session_id: str
    pending_review_count: int
    missing_prior_count: int
    duplicate_occurrence_count: int


class StatementImporter:
    """Convert platform statements into immutable raw observations."""

    def __init__(
        self, store: LedgerStore, adapter_registry: StatementAdapterRegistry | None = None
    ):
        self.store = store
        if adapter_registry is None:
            from .statement_adapters import create_builtin_statement_registry

            adapter_registry = create_builtin_statement_registry()
        self.adapter_registry = adapter_registry

    def import_statement(
        self,
        format_id: str,
        path: str | Path,
        source_account: str,
        **options: Any,
    ) -> ImportSummary:
        """Import through the public adapter boundary used by future formats."""

        return self.adapter_registry.import_statement(
            self, format_id, path, source_account, **options
        )

    def supported_formats(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            {
                "format_id": adapter.format_id,
                "display_name": adapter.display_name,
                "extensions": adapter.extensions,
            }
            for adapter in self.adapter_registry.list_formats()
        )

    def import_wechat_xlsx(self, path: str | Path, source_account: str) -> ImportSummary:
        """Import an official WeChat payment statement without modifying it."""

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
        return self._persist(Platform.WECHAT, statement_path.name, file_hash, parsed, errors)

    def import_alipay_csv(self, path: str | Path, source_account: str) -> ImportSummary:
        """Import the current official Alipay CSV format."""

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
        return self._persist(Platform.ALIPAY, statement_path.name, file_hash, parsed, errors)

    def import_cmb_pdf(self, path: str | Path, source_account: str) -> ImportSummary:
        """Import a date-only China Merchants Bank statement by page coordinates."""

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
        return self._persist(Platform.BANK, statement_path.name, file_hash, parsed, errors)

    def import_icbc_pdf(
        self,
        path: str | Path,
        source_account: str,
        password: str | None = None,
    ) -> ImportSummary:
        """Import an ICBC table statement, including encrypted official exports."""

        pdfplumber = _load_pdfplumber()
        statement_path = Path(path)
        file_hash = _file_sha256(statement_path)
        effective_password = password or _filename_password(statement_path)
        parsed = []
        errors = []
        with pdfplumber.open(statement_path, password=effective_password) as pdf:
            for page_number, page in enumerate(pdf.pages, 1):
                # The official PDF overlays large diagonal watermark text on the table.
                # Transaction text is 6.5-7pt; filtering larger characters prevents
                # watermark digits from contaminating dates, amounts, and balances.
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
        return self._persist(Platform.BANK, statement_path.name, file_hash, parsed, errors)

    def _persist(
        self,
        source: Platform,
        source_file: str,
        file_hash: str,
        parsed: list[RawTransaction],
        errors: list[str],
    ) -> ImportSummary:
        if errors:
            preview = "; ".join(errors[:10])
            remainder = len(errors) - min(len(errors), 10)
            suffix = f"; and {remainder} more" if remainder else ""
            raise StatementImportError(f"statement import rejected: {preview}{suffix}")
        if not parsed:
            raise StatementImportError("statement contains no transaction rows")

        batch, batch_created = self.store.start_import_batch(source, source_file, file_hash)
        with_batch = [
            RawTransaction(
                **{
                    **raw.__dict__,
                    "import_batch_id": batch.batch_id,
                }
            )
            for raw in parsed
        ]
        results = self.store.add_raws(with_batch)
        import_run_id = results[0].import_run_id
        if import_run_id is None:
            raise RuntimeError("statement import did not create an import run")
        coverage = self.store.analyze_import_coverage(batch.batch_id, import_run_id)
        missing_raws = [
            raw
            for raw_id in coverage.missing_raw_ids
            if (raw := self.store.get_raw(raw_id)) is not None
        ]
        created_count = sum(result.created for result in results)
        review_session = ImportReviewService(self.store).create_session(
            batch.batch_id, results, missing_raws
        )
        return ImportSummary(
            batch_id=batch.batch_id,
            import_run_id=import_run_id,
            source=source,
            parsed_count=len(parsed),
            created_count=created_count,
            existing_count=len(results) - created_count,
            file_already_imported=not batch_created,
            review_session_id=review_session.session_id,
            pending_review_count=len(results) + len(missing_raws),
            missing_prior_count=len(missing_raws),
            duplicate_occurrence_count=coverage.duplicate_occurrence_count,
        )


def _wechat_raw(
    row: dict[str, str],
    *,
    row_number: int,
    source_account: str,
    source_file: str,
    source_file_hash: str,
) -> RawTransaction:
    transaction_time = _parse_datetime(row["交易时间"])
    amount, direction = _signed_amount(row["金额(元)"], row["收/支"])
    payment_method = row.get("支付方式", "")
    return RawTransaction(
        source=Platform.WECHAT,
        source_account=source_account,
        transaction_time=transaction_time,
        booking_date=transaction_time.date(),
        amount=amount,
        direction=direction,
        merchant=row.get("交易对方", ""),
        counterparty=row.get("交易对方", ""),
        description=row.get("商品", ""),
        payment_method=payment_method,
        bank_card_suffix=_card_suffix(payment_method),
        transaction_id=row.get("交易单号") or None,
        merchant_order_id=row.get("商户单号") or None,
        status=row.get("当前状态", ""),
        source_file=source_file,
        source_file_hash=source_file_hash,
        raw_row_number=row_number,
        original_row=row,
    )


def _alipay_raw(
    row: dict[str, str],
    *,
    row_number: int,
    source_account: str,
    source_file: str,
    source_file_hash: str,
) -> RawTransaction:
    transaction_time = _parse_datetime(row["交易时间"])
    amount, direction = _signed_amount(row["金额"], row["收/支"])
    payment_method = row.get("收/付款方式", "")
    return RawTransaction(
        source=Platform.ALIPAY,
        source_account=source_account,
        transaction_time=transaction_time,
        booking_date=transaction_time.date(),
        amount=amount,
        direction=direction,
        merchant=row.get("交易对方", ""),
        counterparty=row.get("交易对方", ""),
        description=row.get("商品说明", ""),
        payment_method=payment_method,
        bank_card_suffix=_card_suffix(payment_method),
        transaction_id=row.get("交易订单号") or None,
        merchant_order_id=row.get("商家订单号") or None,
        status=row.get("交易状态", ""),
        source_file=source_file,
        source_file_hash=source_file_hash,
        raw_row_number=row_number,
        original_row=row,
    )


def _cmb_raw(
    row: dict[str, str],
    *,
    row_number: int,
    source_account: str,
    source_file: str,
    source_file_hash: str,
) -> RawTransaction:
    booking_date = datetime.strptime(row["记账日期"], "%Y-%m-%d").date()
    amount = _decimal_amount(row["交易金额"])
    return RawTransaction(
        source=Platform.BANK,
        source_account=source_account,
        transaction_time=None,
        booking_date=booking_date,
        amount=amount,
        direction="expense" if amount < 0 else "income",
        merchant=row.get("对手信息", ""),
        counterparty=row.get("对手信息", ""),
        description=row.get("交易摘要", ""),
        payment_method="招商银行",
        bank_card_suffix=_card_suffix(source_account),
        balance=_decimal_amount(row["联机余额"]),
        currency=row.get("货币") or "CNY",
        source_file=source_file,
        source_file_hash=source_file_hash,
        raw_row_number=row_number,
        original_row=row,
    )


def _icbc_raw(
    row: dict[str, str],
    *,
    row_number: int,
    source_account: str,
    source_file: str,
    source_file_hash: str,
) -> RawTransaction:
    transaction_time = _parse_datetime(row["交易日期"])
    amount = _decimal_amount(row["收入/支出金额"])
    account = row.get("账号", "")
    return RawTransaction(
        source=Platform.BANK,
        source_account=source_account,
        transaction_time=transaction_time,
        booking_date=transaction_time.date(),
        amount=amount,
        direction="expense" if amount < 0 else "income",
        merchant=_blank_marker(row.get("对方户名", "")),
        counterparty=_blank_marker(row.get("对方户名", "")),
        description=row.get("摘要", ""),
        payment_method=f"工商银行 {row.get('渠道', '')}".strip(),
        bank_card_suffix=_card_suffix(account) or _card_suffix(source_account),
        balance=_decimal_amount(row["余额"]),
        currency="CNY" if row.get("币种") in {"人民币", "CNY"} else row.get("币种", "CNY"),
        source_file=source_file,
        source_file_hash=source_file_hash,
        raw_row_number=row_number,
        original_row=row,
    )


def _extract_cmb_page(page: Any, page_number: int) -> list[dict[str, str]]:
    """Rebuild CMB rows from stable official PDF column coordinates."""

    words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
    anchors = [
        word
        for word in words
        if word["x0"] < 90 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", word["text"])
    ]
    anchors.sort(key=lambda word: word["top"])
    records = []
    for index, anchor in enumerate(anchors):
        previous_top = anchors[index - 1]["top"] if index else None
        next_top = anchors[index + 1]["top"] if index + 1 < len(anchors) else None
        lower = (
            (previous_top + anchor["top"]) / 2 if previous_top is not None else anchor["top"] - 12
        )
        upper = (anchor["top"] + next_top) / 2 if next_top is not None else anchor["top"] + 18
        block = [word for word in words if lower <= word["top"] < upper]
        columns = {
            "记账日期": [word for word in block if word["x0"] < 90],
            "货币": [word for word in block if 90 <= word["x0"] < 145],
            "交易金额": [word for word in block if 145 <= word["x0"] < 225],
            "联机余额": [word for word in block if 225 <= word["x0"] < 300],
            "交易摘要": [word for word in block if 300 <= word["x0"] < 410],
            "对手信息": [word for word in block if word["x0"] >= 410],
        }
        record = {
            key: " ".join(word["text"] for word in sorted(column, key=_word_order)).strip()
            for key, column in columns.items()
        }
        record["记账日期"] = anchor["text"]
        if record["货币"] and record["交易金额"] and record["联机余额"]:
            records.append(record)
        else:
            raise StatementImportError(
                f"page {page_number}: incomplete CMB row near {anchor['text']}"
            )
    return records


def _word_order(word: dict[str, Any]) -> tuple[float, float]:
    return (round(float(word["top"]), 1), float(word["x0"]))


ICBC_HEADERS = [
    "交易日期",
    "账号",
    "储种",
    "序号",
    "币种",
    "钞汇",
    "摘要",
    "地区",
    "收入/支出金额",
    "余额",
    "对方户名",
    "对方账号",
    "渠道",
]


def _is_icbc_header(values: list[Any]) -> bool:
    normalized = [re.sub(r"[^\u4e00-\u9fff]", "", _cell_text(value)) for value in values]
    expected = [re.sub(r"[^\u4e00-\u9fff]", "", header) for header in ICBC_HEADERS]
    return len(normalized) == len(expected) and normalized == expected


def _icbc_row(values: list[Any]) -> dict[str, str]:
    if len(values) != len(ICBC_HEADERS):
        raise StatementImportError(
            f"ICBC transaction row has {len(values)} columns, expected {len(ICBC_HEADERS)}"
        )
    return {
        header: re.sub(r"\s+", "", _cell_text(value)) for header, value in zip(ICBC_HEADERS, values)
    }


def _decimal_amount(value: str) -> Decimal:
    normalized = re.sub(r"\s", "", value)
    monetary_tokens = re.findall(r"[+-]?\d[\d,]*\.\d{2}", normalized)
    cleaned = monetary_tokens[-1].replace(",", "") if monetary_tokens else ""
    if not cleaned or cleaned in {"+", "-", "."}:
        raise ValueError(f"invalid monetary value: {value!r}")
    return Decimal(cleaned)


def _blank_marker(value: str) -> str:
    return "" if value in {"（空）", "(空)", "空"} else value


def _filename_password(path: Path) -> str | None:
    prefix = path.name.split("-", 1)[0]
    return prefix if prefix.isdigit() else None


def _load_pdfplumber():
    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError("pdfplumber is required for bank PDF import") from exc
    return pdfplumber


def _balance_chain_errors(transactions: list[RawTransaction]) -> list[str]:
    """Require every adjacent bank balance to reconcile to the cent."""

    errors = []
    for previous, current in pairwise(transactions):
        if previous.balance is None or current.balance is None:
            errors.append(f"record {current.raw_row_number}: bank balance is missing")
            continue
        expected = previous.balance + current.amount
        if expected != current.balance:
            errors.append(f"record {current.raw_row_number}: balance chain does not reconcile")
    return errors


def _find_header(rows: list[Any], required: set[str]) -> tuple[int, list[str]]:
    for index, values in enumerate(rows[:100]):
        headers = [_cell_text(value) for value in values]
        if required.issubset(set(headers)):
            return index, headers
    raise StatementImportError(f"required statement headers were not found: {sorted(required)}")


def _row_dict(headers: list[str], values: Any) -> dict[str, str]:
    padded = list(values) + [None] * max(0, len(headers) - len(values))
    return {header: _cell_text(value) for header, value in zip(headers, padded) if header}


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    return str(value).strip()


def _signed_amount(value: str, direction_text: str) -> tuple[Decimal, str]:
    cleaned = re.sub(r"[^0-9.\-]", "", value.replace(",", ""))
    if not cleaned:
        raise ValueError("amount is empty")
    amount = abs(Decimal(cleaned))
    direction_map = {
        "支出": "expense",
        "收入": "income",
        "不计收支": "neutral",
        "/": "neutral",
    }
    if direction_text not in direction_map:
        raise ValueError(f"unsupported direction: {direction_text!r}")
    direction = direction_map[direction_text]
    if direction == "expense":
        amount = -amount
    return amount, direction


def _parse_datetime(value: str) -> datetime:
    compact = re.sub(r"[^0-9/\-:]", "", value)
    candidates = [value, compact]
    if re.fullmatch(r"\d{4}[-/]\d{2}[-/]\d{2}\d{2}:\d{2}:\d{2}", compact):
        candidates.append(f"{compact[:10]} {compact[10:]}")
    for candidate in candidates:
        for format_string in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
            try:
                return datetime.strptime(candidate, format_string)
            except ValueError:
                continue
    raise ValueError(f"unsupported transaction time: {value!r}")


def _card_suffix(payment_method: str) -> str | None:
    matches: list[str] = re.findall(r"(?<!\d)(\d{4})(?!\d)", payment_method)
    if matches:
        return matches[-1]
    compact = re.sub(r"\s", "", payment_method)
    return compact[-4:] if len(compact) > 4 and compact.isdigit() else None


def _decode_csv(data: bytes) -> str:
    for encoding in ("utf-8-sig", "gb18030", "utf-16"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise StatementImportError("statement encoding is not supported")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
