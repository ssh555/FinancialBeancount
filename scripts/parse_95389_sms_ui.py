"""Parse transaction cards captured from the 95389 SMS conversation UI."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path

FULL_DATE_RE = re.compile(r"(20\d{2})年(\d{1,2})月(\d{1,2})日")
DAY_TIME_RE = re.compile(r"(\d{1,2})日\s*(\d{2}):(\d{2})")
MONEY_RE = re.compile(r"([0-9,]+\.\d{2})元")


def _after(texts: list[str], label: str, offset: int = 1) -> str:
    try:
        return texts[texts.index(label) + offset]
    except (ValueError, IndexError):
        return ""


def parse_items(payload: dict) -> list[dict[str, str]]:
    year_month_by_page: dict[int, tuple[int, int]] = {}
    last_year_month: tuple[int, int] | None = None
    for item in payload["items"]:
        page = int(item["page"])
        for text in item["texts"]:
            match = FULL_DATE_RE.search(text)
            if match:
                last_year_month = (int(match.group(1)), int(match.group(2)))
                year_month_by_page[page] = last_year_month
                break
    pages = sorted({int(item["page"]) for item in payload["items"]})
    context = None
    page_context: dict[int, tuple[int, int]] = {}
    for page in pages:
        if page in year_month_by_page:
            context = year_month_by_page[page]
        if context:
            page_context[page] = context

    candidates: list[dict[str, str]] = []
    current_year_month: tuple[int, int] | None = None
    for item in payload["items"]:
        page = int(item["page"])
        texts = item["texts"]
        explicit_date = False
        for text in texts:
            match = FULL_DATE_RE.search(text)
            if match:
                current_year_month = (int(match.group(1)), int(match.group(2)))
                explicit_date = True
                break
        if current_year_month is None:
            current_year_month = page_context.get(page)
        amount_text = _after(texts, "金额")
        balance_text = _after(texts, "时间")
        type_text = _after(texts, "类型", 2)
        time_text = ""
        for text in texts:
            if DAY_TIME_RE.fullmatch(text):
                time_text = text
                break
        amount_match = MONEY_RE.fullmatch(amount_text)
        balance_match = MONEY_RE.fullmatch(balance_text)
        time_match = DAY_TIME_RE.fullmatch(time_text)
        if not (amount_match and balance_match and time_match and type_text and current_year_month):
            continue
        year, month = current_year_month
        day, hour, minute = map(int, time_match.groups())
        timestamp = datetime(year, month, day, hour, minute)
        amount = Decimal(amount_match.group(1).replace(",", ""))
        balance = Decimal(balance_match.group(1).replace(",", ""))
        candidates.append({
            "transaction_time": timestamp.isoformat(timespec="minutes"),
            "amount": f"{amount:.2f}",
            "balance": f"{balance:.2f}",
            "type": type_text,
            "source": "95389短信交易提醒",
            "date_evidence": "短信完整日期" if explicit_date else "同屏日期继承",
        })
    records: dict[tuple[str, str, str, str], dict[str, str]] = {}
    for candidate in candidates:
        signature = (
            candidate["transaction_time"][11:],
            candidate["amount"],
            candidate["balance"],
            candidate["type"],
        )
        existing = records.get(signature)
        if existing is None or (
            existing["date_evidence"] != "短信完整日期"
            and candidate["date_evidence"] == "短信完整日期"
        ):
            records[signature] = candidate
    return sorted(records.values(), key=lambda row: row["transaction_time"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    records = parse_items(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"records": len(records), "first": records[:1], "last": records[-1:]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
