"""Tests for strict official Alipay and WeChat statement import."""

import csv
from pathlib import Path

import pytest
from beancount_dedup.ledger_store import LedgerStore
from beancount_dedup.models import Platform
from beancount_dedup.statement_importer import (
    StatementImporter,
    StatementImportError,
    _balance_chain_errors,
    _cmb_raw,
    _icbc_raw,
    _is_icbc_header,
    _signed_amount,
)


@pytest.fixture
def store(tmp_path):
    with LedgerStore(tmp_path / "ledger.sqlite3") as ledger_store:
        yield ledger_store


def write_alipay_fixture(path: Path) -> None:
    rows = [
        ["支付宝交易明细证明"],
        ["以下内容全部脱敏"],
        [
            "交易时间",
            "交易分类",
            "交易对方",
            "对方账号",
            "商品说明",
            "收/支",
            "金额",
            "收/付款方式",
            "交易状态",
            "交易订单号",
            "商家订单号",
            "备注",
        ],
        [
            "2026-03-01 11:31:44",
            "交通出行",
            "脱敏出行商户",
            "已脱敏",
            "网约车",
            "支出",
            "57.96",
            "工商银行储蓄卡(4000)",
            "交易成功",
            "alipay-order-redacted",
            "merchant-order-redacted",
            "",
        ],
    ]
    with path.open("w", encoding="gb18030", newline="") as stream:
        csv.writer(stream).writerows(rows)


def write_wechat_fixture(path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    for _ in range(3):
        worksheet.append(["微信支付账单"])
    worksheet.append(
        [
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
            "备注",
        ]
    )
    worksheet.append(
        [
            "2026-03-02 08:15:00",
            "商户消费",
            "脱敏早餐商户",
            "早餐",
            "支出",
            "12.50",
            "招商银行储蓄卡(5066)",
            "支付成功",
            "wechat-order-redacted",
            "wechat-merchant-redacted",
            "",
        ]
    )
    workbook.save(path)


def test_alipay_current_csv_fields_are_preserved(store, tmp_path):
    statement = tmp_path / "alipay.csv"
    write_alipay_fixture(statement)
    importer = StatementImporter(store)

    summary = importer.import_alipay_csv(statement, "alipay-private-token")
    raw = store.connection.execute("SELECT * FROM raw_transactions").fetchone()

    assert summary.created_count == 1
    assert raw["source"] == Platform.ALIPAY.value
    assert raw["amount"] == "-57.96"
    assert raw["payment_method"] == "工商银行储蓄卡(4000)"
    assert raw["bank_card_suffix"] == "4000"
    assert raw["transaction_id"] == "alipay-order-redacted"


def test_wechat_xlsx_header_can_follow_preamble(store, tmp_path):
    statement = tmp_path / "wechat.xlsx"
    write_wechat_fixture(statement)
    importer = StatementImporter(store)

    summary = importer.import_wechat_xlsx(statement, "wechat-private-token")
    raw = store.connection.execute("SELECT * FROM raw_transactions").fetchone()

    assert summary.created_count == 1
    assert raw["source"] == Platform.WECHAT.value
    assert raw["raw_row_number"] == 5
    assert raw["bank_card_suffix"] == "5066"
    assert raw["transaction_id"] == "wechat-order-redacted"


def test_reimport_of_same_alipay_file_creates_no_raw_duplicates(store, tmp_path):
    statement = tmp_path / "alipay.csv"
    write_alipay_fixture(statement)
    importer = StatementImporter(store)

    first = importer.import_alipay_csv(statement, "alipay-private-token")
    second = importer.import_alipay_csv(statement, "alipay-private-token")

    assert first.created_count == 1
    assert second.created_count == 0
    assert second.existing_count == 1
    assert second.file_already_imported is True


def test_malformed_row_rejects_entire_file_without_partial_import(store, tmp_path):
    statement = tmp_path / "alipay.csv"
    write_alipay_fixture(statement)
    with statement.open("a", encoding="gb18030", newline="") as stream:
        csv.writer(stream).writerow(
            [
                "not-a-time",
                "交通出行",
                "脱敏商户",
                "已脱敏",
                "打车",
                "支出",
                "10.00",
                "余额",
                "交易成功",
                "bad-order",
                "",
                "",
            ]
        )
    importer = StatementImporter(store)

    with pytest.raises(StatementImportError, match="row 5"):
        importer.import_alipay_csv(statement, "alipay-private-token")

    count = store.connection.execute("SELECT COUNT(*) FROM raw_transactions").fetchone()[0]
    assert count == 0


def test_cmb_date_only_row_preserves_balance_and_counterparty():
    raw = _cmb_raw(
        {
            "记账日期": "2026-03-01",
            "货币": "CNY",
            "交易金额": "-57.96",
            "联机余额": "1,000.00",
            "交易摘要": "快捷支付",
            "对手信息": "脱敏信息",
        },
        row_number=10001,
        source_account="cmb-account-token-5066",
        source_file="cmb.pdf",
        source_file_hash="hash",
    )

    assert raw.transaction_time is None
    assert raw.booking_date.isoformat() == "2026-03-01"
    assert str(raw.amount) == "-57.96"
    assert str(raw.balance) == "1000.00"
    assert raw.bank_card_suffix == "5066"


def test_icbc_precise_row_preserves_channel_and_card_suffix():
    raw = _icbc_raw(
        {
            "交易日期": "2026-03-01 11:31:44",
            "账号": "0000000000004000",
            "储种": "活期",
            "序号": "00001",
            "币种": "人民币",
            "钞汇": "钞",
            "摘要": "快捷支付",
            "地区": "0000",
            "收入/支出金额": "-57.96",
            "余额": "1000.00",
            "对方户名": "脱敏商户",
            "对方账号": "已脱敏",
            "渠道": "网银",
        },
        row_number=10001,
        source_account="icbc-account-token",
        source_file="icbc.pdf",
        source_file_hash="hash",
    )

    assert raw.transaction_time.isoformat() == "2026-03-01T11:31:44"
    assert raw.bank_card_suffix == "4000"
    assert raw.payment_method == "工商银行 网银"


def test_icbc_header_tolerates_watermark_digits_and_spaces():
    headers = [
        "交易日期",
        "账号",
        "储种",
        "序号",
        "币种",
        "钞汇",
        "摘要",
        "地区",
        "3 1 7 收入/支出金额",
        "余额",
        "对方户名",
        "对方账号",
        "渠道",
    ]

    assert _is_icbc_header(headers) is True


def test_bank_balance_chain_detects_a_misparsed_amount():
    first = _cmb_raw(
        {
            "记账日期": "2026-03-01",
            "货币": "CNY",
            "交易金额": "-10.00",
            "联机余额": "90.00",
            "交易摘要": "消费",
            "对手信息": "脱敏商户",
        },
        row_number=10001,
        source_account="token-5066",
        source_file="cmb.pdf",
        source_file_hash="hash",
    )
    inconsistent = _cmb_raw(
        {
            "记账日期": "2026-03-02",
            "货币": "CNY",
            "交易金额": "-5.00",
            "联机余额": "80.00",
            "交易摘要": "消费",
            "对手信息": "脱敏商户",
        },
        row_number=10002,
        source_account="token-5066",
        source_file="cmb.pdf",
        source_file_hash="hash",
    )

    assert _balance_chain_errors([first, inconsistent]) == [
        "record 10002: balance chain does not reconcile"
    ]


def test_wechat_slash_direction_is_a_neutral_transfer():
    amount, direction = _signed_amount("100.00", "/")

    assert str(amount) == "100.00"
    assert direction == "neutral"
