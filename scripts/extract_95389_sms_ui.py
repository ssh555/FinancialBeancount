"""Read only the already-open 95389 SMS conversation through Android UI dumps."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path

DATE_RE = re.compile(r"(20\d{2})年(\d{1,2})月(\d{1,2})日")


def _adb(*args: str) -> bytes:
    return subprocess.run(["adb", *args], check=True, capture_output=True).stdout


def _dump() -> bytes:
    _adb("shell", "uiautomator", "dump", "/sdcard/window.xml")
    return _adb("exec-out", "cat", "/sdcard/window.xml")


def _items(xml_bytes: bytes) -> list[list[str]]:
    root = ET.fromstring(xml_bytes.decode("utf-8"))
    results = []
    for node in root.iter("node"):
        resource_id = node.attrib.get("resource-id", "")
        if resource_id not in {
            "com.android.mms:id/msg_list_item_recv",
            "com.android.mms:id/msg_list_item_send",
        }:
            continue
        texts = [
            child.attrib["text"].strip()
            for child in node.iter("node")
            if child.attrib.get("text", "").strip()
        ]
        if texts:
            results.append(texts)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-swipes", type=int, default=160)
    parser.add_argument("--stop-date", default="2021-01-30")
    args = parser.parse_args()
    stop_compact = args.stop_date.replace("-", "")
    seen_items: set[str] = set()
    records: list[dict[str, object]] = []
    unchanged = 0
    previous_hash = ""
    latest_date = ""
    for page in range(args.max_swipes + 1):
        xml_bytes = _dump()
        digest = hashlib.sha256(xml_bytes).hexdigest()
        unchanged = unchanged + 1 if digest == previous_hash else 0
        previous_hash = digest
        page_items = _items(xml_bytes)
        for texts in page_items:
            key = hashlib.sha256("\n".join(texts).encode()).hexdigest()
            if key in seen_items:
                continue
            seen_items.add(key)
            records.append({"page": page, "texts": texts})
            for text in texts:
                match = DATE_RE.search(text)
                if match:
                    latest_date = "".join(f"{int(value):02d}" for value in match.groups())
        if latest_date >= stop_compact or unchanged >= 2:
            break
        # Move by roughly half a screen so every rich transaction card is fully
        # visible in at least one dump; large jumps split cards and lose fields.
        _adb("shell", "input", "swipe", "540", "1450", "540", "1020", "220")
        time.sleep(0.35)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "conversation": "95389",
                "pages": page + 1,
                "latest_date": latest_date,
                "items": records,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps({"pages": page + 1, "items": len(records), "latest_date": latest_date}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
