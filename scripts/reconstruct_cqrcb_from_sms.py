"""Create an auditable CQRCB history from 95389 SMS balance anchors."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

EXPENSE_TYPES = {"支付宝付", "财付通付"}


def _money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')):.2f}"


def reconstruct(input_path: Path, output_path: Path) -> dict[str, object]:
    records = json.loads(input_path.read_text(encoding="utf-8"))
    records = [
        row
        for row in records
        if "2019-09-03T00:00" <= row["transaction_time"] < "2021-01-30T00:00"
    ]
    if not records:
        raise ValueError("目标日期范围内没有95389交易记录")

    first = records[0]
    first_amount = Decimal(first["amount"])
    first_balance = Decimal(first["balance"])
    if first["type"] not in EXPENSE_TYPES:
        raise ValueError("首笔短信不是可确定方向的平台支出")
    opening_balance = first_balance + first_amount
    output_rows: list[dict[str, str]] = []

    def append(
        timestamp: str,
        amount: Decimal,
        balance: Decimal,
        summary: str,
        note: str,
        nature: str,
    ) -> None:
        transaction_time = datetime.fromisoformat(timestamp)
        output_rows.append(
            {
                "交易日期": transaction_time.date().isoformat(),
                "交易时间": transaction_time.strftime("%Y-%m-%d %H:%M:%S"),
                "交易发生额": _money(amount),
                "账户余额": _money(balance),
                "本方账号": "6215281073756235",
                "对方账号": "",
                "对方户名": "",
                "摘要": summary,
                "备注": note,
                "数据性质": nature,
            }
        )

    append(
        "2019-09-03T00:00:00",
        opening_balance,
        opening_balance,
        "反推期初余额",
        "根据2019-09-03首笔95389短信的交易金额及交易后余额倒推；非银行原始流水",
        "推算-期初余额",
    )
    previous_balance = opening_balance
    inferred = []
    for record in records:
        timestamp = datetime.fromisoformat(record["transaction_time"])
        amount = Decimal(record["amount"])
        balance = Decimal(record["balance"])
        delta = balance - previous_balance
        if delta == amount:
            signed_amount = amount
        elif delta == -amount:
            signed_amount = -amount
        elif record["type"] in EXPENSE_TYPES:
            signed_amount = -amount
            adjustment = balance - previous_balance - signed_amount
            if adjustment:
                if timestamp == datetime(2020, 7, 9, 15, 30):
                    adjustment_time = "2020-07-09T14:52:00"
                    summary = "支付宝付"
                    note = "支付宝账单存在、95389未单独展示；由相邻短信余额差确认"
                    nature = "平台交叉确认"
                else:
                    interest_dates = {
                        (2019, 9): "2019-09-21T00:00:00",
                        (2020, 1): "2019-12-21T00:00:00",
                        (2020, 3): "2020-03-21T00:00:00",
                        (2020, 7): "2020-06-21T00:00:00",
                        (2020, 9): "2020-09-21T00:00:00",
                    }
                    adjustment_time = interest_dates[(timestamp.year, timestamp.month)]
                    summary = "活期结息"
                    note = "由前后95389短信余额与已知交易金额精确反推"
                    nature = "推算-余额链结息"
                append(
                    adjustment_time,
                    adjustment,
                    previous_balance + adjustment,
                    summary,
                    note,
                    nature,
                )
                inferred.append((adjustment_time, adjustment, summary))
                previous_balance += adjustment
        else:
            raise ValueError(
                f"无法确定短信交易方向：{record['transaction_time']} {record['type']}"
            )
        append(
            timestamp.isoformat(timespec="seconds"),
            signed_amount,
            balance,
            record["type"],
            f"来源95389短信交易提醒；日期依据：{record['date_evidence']}",
            "短信原始交易提醒",
        )
        previous_balance = balance

    final_interest = Decimal("2286.37") - previous_balance
    if final_interest != Decimal("1.82"):
        raise RuntimeError(f"末端结息不是预期的1.82元：{final_interest}")
    append(
        "2020-12-21T00:00:00",
        final_interest,
        Decimal("2286.37"),
        "活期结息",
        "由2020-12-08短信余额与2021-01-30官方首笔前余额精确反推",
        "推算-余额链结息",
    )
    inferred.append(("2020-12-21T00:00:00", final_interest, "活期结息"))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(output_rows[0]))
        writer.writeheader()
        writer.writerows(output_rows)
    return {
        "output": str(output_path.resolve()),
        "sms_transactions": len(records),
        "generated_rows": len(output_rows),
        "opening_balance": _money(opening_balance),
        "closing_balance": _money(Decimal("2286.37")),
        "inferred_rows": [
            {"time": time, "amount": _money(amount), "summary": summary}
            for time, amount, summary in inferred
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            reconstruct(args.input.resolve(), args.output.resolve()),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
