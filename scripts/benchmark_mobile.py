"""Measure the local mobile API against a real ledger database."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any

from beancount_dedup.android_bridge import dispatch

DEFAULT_LIMITS_MS = {
    "overview_summary": 1000.0,
    "overview_timeline": 1000.0,
    "transaction_first_page": 500.0,
    "transaction_search": 750.0,
}


def benchmark_database(
    database: Path,
    *,
    iterations: int = 5,
    limits_ms: dict[str, float] | None = None,
) -> dict[str, Any]:
    if iterations < 1:
        raise ValueError("iterations must be positive")
    endpoints = {
        "overview_summary": "/api/v1/statistics/summary",
        "overview_timeline": "/api/v1/statistics/timeline?period=month",
        "transaction_first_page": "/api/v1/transactions?page=1&page_size=30",
        "transaction_search": "/api/v1/transactions?page=1&page_size=30&search=%E6%94%AF%E4%BB%98",
    }
    selected_limits = limits_ms or DEFAULT_LIMITS_MS
    results: dict[str, Any] = {}
    for name, target in endpoints.items():
        samples = []
        dispatch(str(database.resolve()), _request(target))
        for _ in range(iterations):
            started = perf_counter()
            response = json.loads(dispatch(str(database.resolve()), _request(target)))
            samples.append((perf_counter() - started) * 1000)
            if response["status"] != 200:
                raise RuntimeError(f"{name} returned HTTP {response['status']}")
        ordered = sorted(samples)
        p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
        limit = selected_limits[name]
        results[name] = {
            "median_ms": round(median(samples), 2),
            "p95_ms": round(p95, 2),
            "limit_ms": limit,
            "passed": p95 <= limit,
        }
    return {
        "success": all(item["passed"] for item in results.values()),
        "database": str(database.resolve()),
        "iterations": iterations,
        "results": results,
    }


def _request(target: str) -> str:
    return json.dumps({"method": "GET", "target": target}, separators=(",", ":"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = benchmark_database(args.database, iterations=args.iterations)
    except (OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    content = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(content, encoding="utf-8", newline="\n")
    print(content)
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
