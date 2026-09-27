from datetime import date
from pathlib import Path

from beancount_dedup.account_balances import AccountBalanceService
from beancount_dedup.ledger_models import RawTransaction
from beancount_dedup.ledger_store import LedgerStore
from beancount_dedup.models import Platform


def _raw(
    identity: str,
    *,
    account: str,
    day: date,
    amount: str,
    balance: str,
    description: str,
    counterparty: str = "",
) -> RawTransaction:
    return RawTransaction(
        source=Platform.BANK,
        source_account=account,
        transaction_time=None,
        booking_date=day,
        amount=amount,
        direction="expense" if amount.startswith("-") else "income",
        merchant=counterparty,
        counterparty=counterparty,
        description=description,
        balance=balance,
        transaction_id=identity,
        source_file="statement.pdf",
        source_file_hash="hash",
        original_row={"identity": identity},
    )


def test_account_balance_uses_latest_cash_and_internal_products_only(tmp_path: Path) -> None:
    with LedgerStore(tmp_path / "ledger.sqlite3") as store:
        rows = (
            _raw(
                "cmb-old",
                account="招商银行",
                day=date(2026, 1, 1),
                amount="100",
                balance="100",
                description="收入",
            ),
            _raw(
                "cmb-new",
                account="招商银行",
                day=date(2026, 9, 18),
                amount="25",
                balance="1125.01",
                description="收入",
            ),
            _raw(
                "icbc",
                account="工商银行",
                day=date(2026, 9, 21),
                amount="-20",
                balance="1673.99",
                description="消费",
            ),
            _raw(
                "zhao-in",
                account="招商银行",
                day=date(2026, 5, 1),
                amount="-10000",
                balance="0",
                description="朝朝宝转入",
            ),
            _raw(
                "zhao-out",
                account="招商银行",
                day=date(2026, 8, 1),
                amount="2047.12",
                balance="2047.12",
                description="朝朝宝转出",
            ),
            _raw(
                "tiantianying",
                account="工商银行",
                day=date(2026, 9, 1),
                amount="-1802.05",
                balance="500",
                description="基金购买",
                counterparty="本人",
            ),
            _raw(
                "external",
                account="工商银行",
                day=date(2026, 9, 7),
                amount="-6000",
                balance="4535.49",
                description="天天9074959683",
                counterparty="上海天天基金销售有限公司",
            ),
        )
        for row in rows:
            store.add_raw(row)

        report = AccountBalanceService(store).summarize()

    assert report["cash_total"] == "2799.00"
    assert report["internal_product_total"] == "9754.93"
    assert report["known_balance"] == "12553.93"
    assert report["as_of"] == "2026-09-21"
    assert len(report["internal_products"]) == 2
    assert "外部基金平台" in report["scope_note"]
