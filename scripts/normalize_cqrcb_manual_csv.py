"""Normalize the manually repaired CQRCB CSV without changing its evidence file."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

FIELDS = (
    "交易日期",
    "交易时间",
    "交易发生额",
    "账户余额",
    "本方账号",
    "对方账号",
    "对方户名",
    "摘要",
    "备注",
    "数据性质",
)
ACCOUNT = "6215281073756235"


def _date(value: str) -> datetime:
    for pattern in ("%Y/%m/%d %H:%M", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, pattern)
        except ValueError:
            continue
    raise ValueError(f"无法识别交易时间：{value}")


def _money(value: Decimal | str) -> str:
    return f"{Decimal(value).quantize(Decimal('0.01')):.2f}"


def normalize(source: Path, output: Path) -> dict[str, object]:
    with source.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError("手工修订文件为空")

    normalized: list[dict[str, str]] = []
    first_balance = Decimal(rows[0]["账户余额"])
    normalized.append(
        {
            "交易日期": "2019-06-03",
            "交易时间": "2019-06-03 00:00:00",
            "交易发生额": _money(first_balance),
            "账户余额": _money(first_balance),
            "本方账号": ACCOUNT,
            "对方账号": "",
            "对方户名": "",
            "摘要": "期初余额",
            "备注": "依据手工核对的2019-06-03首个余额锚点；此前交易明细不可得",
            "数据性质": "余额锚点",
        }
    )

    previous_balance = first_balance
    inserted_rows = []
    for source_row in rows[1:]:
        row = {field: (source_row.get(field) or "").strip() for field in FIELDS}
        timestamp = _date(row["交易时间"])
        amount = Decimal(row["交易发生额"])
        balance = Decimal(row["账户余额"])
        unexplained = balance - previous_balance - amount
        if unexplained:
            if timestamp.date().isoformat() == "2019-06-25" and unexplained == Decimal("4.12"):
                interest_time = datetime(2019, 6, 21)
                previous_balance += unexplained
                normalized.append(
                    {
                        "交易日期": interest_time.date().isoformat(),
                        "交易时间": interest_time.strftime("%Y-%m-%d %H:%M:%S"),
                        "交易发生额": _money(unexplained),
                        "账户余额": _money(previous_balance),
                        "本方账号": ACCOUNT,
                        "对方账号": "",
                        "对方户名": "",
                        "摘要": "活期结息",
                        "备注": "由2019-06-03与2019-06-25相邻余额锚点精确反推",
                        "数据性质": "推算-余额链结息",
                    }
                )
                inserted_rows.append(
                    {"time": interest_time.isoformat(), "amount": _money(unexplained)}
                )
            else:
                raise ValueError(
                    f"无法解释的余额差：{row['交易时间']} 差额 {_money(unexplained)}"
                )
        row["交易日期"] = timestamp.date().isoformat()
        row["交易时间"] = timestamp.strftime("%Y-%m-%d %H:%M:%S")
        row["交易发生额"] = _money(amount)
        row["账户余额"] = _money(balance)
        row["本方账号"] = ACCOUNT
        if not row["备注"]:
            row["备注"] = "来源95389短信交易提醒；手工核对"
        if not row["数据性质"]:
            row["数据性质"] = "短信原始交易提醒"
        normalized.append(row)
        previous_balance = balance

    verified = 0
    previous = None
    for row in normalized:
        balance = Decimal(row["账户余额"])
        amount = Decimal(row["交易发生额"])
        if previous is not None:
            if previous + amount != balance:
                raise RuntimeError(f"规范化后余额链断裂：{row['交易时间']}")
            verified += 1
        previous = balance

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(normalized)
    return {
        "source": str(source.resolve()),
        "output": str(output.resolve()),
        "source_rows": len(rows),
        "output_rows": len(normalized),
        "inserted_rows": inserted_rows,
        "verified_transitions": verified,
        "opening_balance": _money(normalized[0]["账户余额"]),
        "closing_balance": _money(normalized[-1]["账户余额"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            normalize(args.source.resolve(), args.output.resolve()),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
