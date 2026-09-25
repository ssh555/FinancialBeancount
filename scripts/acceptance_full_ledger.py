"""Import a complete private statement set and verify one-file portable export/restore."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from beancount_dedup.canonical_matcher import ConservativeMatcher
from beancount_dedup.ledger_store import LedgerStore
from beancount_dedup.portable_archive import (
    TABLE_ORDER,
    export_portable_archive,
    import_portable_archive,
    inspect_portable_archive,
)
from beancount_dedup.review import ImportReviewService
from beancount_dedup.statement_importer import StatementImporter

FORMAT_BY_FOLDER_SUFFIX = {
    ("微信", ".xlsx"): "wechat.xlsx",
    ("支付宝", ".csv"): "alipay.csv",
    ("招商银行", ".pdf"): "cmb.pdf",
    ("工商银行", ".pdf"): "icbc.pdf",
}


@dataclass(frozen=True)
class StatementFile:
    path: Path
    relative_path: str
    format_id: str
    source_account: str


@dataclass(frozen=True)
class FileResult:
    relative_path: str
    format_id: str
    status: str
    parsed_count: int = 0
    created_count: int = 0
    existing_count: int = 0
    message: str = ""


def discover_statements(root: Path) -> tuple[list[StatementFile], list[FileResult]]:
    statements: list[StatementFile] = []
    skipped: list[FileResult] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        folder = path.parent.name
        format_id = FORMAT_BY_FOLDER_SUFFIX.get((folder, path.suffix.lower()))
        if format_id:
            statements.append(StatementFile(path, relative, format_id, folder))
        elif path.suffix.lower() == ".zip":
            skipped.append(
                FileResult(relative, "", "skipped", message="压缩包由同目录已解压账单覆盖")
            )
        else:
            skipped.append(FileResult(relative, "", "skipped", message="不是已支持的账单内容格式"))
    return statements, skipped


def run_acceptance(bills_root: Path, output_directory: Path) -> dict[str, Any]:
    if not bills_root.is_dir():
        raise ValueError(f"账单目录不存在：{bills_root}")
    output_directory.mkdir(parents=True, exist_ok=True)
    database = output_directory / "complete-ledger.sqlite3"
    restored_database = output_directory / "restored-mobile-ledger.sqlite3"
    archive = output_directory / "complete-ledger.financial-beancount.zip"
    conflicts = [path for path in (database, restored_database, archive) if path.exists()]
    if conflicts:
        raise ValueError(f"验收输出已存在，请使用空目录：{conflicts[0]}")

    statements, results = discover_statements(bills_root)
    if not statements:
        raise ValueError("账单目录中没有可处理文件")
    failures: list[FileResult] = []
    with LedgerStore(database) as store:
        importer = StatementImporter(store)
        for statement in statements:
            try:
                summary = importer.import_statement(
                    statement.format_id, statement.path, statement.source_account
                )
                results.append(
                    FileResult(
                        statement.relative_path,
                        statement.format_id,
                        "imported",
                        summary.parsed_count,
                        summary.created_count,
                        summary.existing_count,
                    )
                )
            except Exception as exc:
                failure = FileResult(
                    statement.relative_path,
                    statement.format_id,
                    "unprocessed",
                    message=str(exc),
                )
                failures.append(failure)
                results.append(failure)

        candidates = ConservativeMatcher(store).generate_candidates()
        safe_confirmed_count = ImportReviewService(store).confirm_unmatched_without_candidates(
            "full-ledger-acceptance"
        )
        counts = _table_counts(store)
        if not failures:
            export_portable_archive(store, archive)

    restored_counts: dict[str, int] | None = None
    if not failures:
        manifest = inspect_portable_archive(archive)
        restored = import_portable_archive(archive, restored_database)
        try:
            restored_counts = _table_counts(restored)
        finally:
            restored.close()
        if restored_counts != counts:
            raise RuntimeError("便携归档恢复后的逐表数量与原账本不一致")
        if {table: metadata["rows"] for table, metadata in manifest.tables.items()} != counts:
            raise RuntimeError("便携归档清单与原账本逐表数量不一致")

    report = {
        "success": not failures,
        "bills_root": str(bills_root.resolve()),
        "database": str(database.resolve()),
        "portable_archive": str(archive.resolve()) if archive.exists() else None,
        "restored_database": str(restored_database.resolve()) if restored_database.exists() else None,
        "discovered_count": len(statements),
        "imported_count": sum(item.status == "imported" for item in results),
        "unprocessed_count": len(failures),
        "skipped_count": sum(item.status == "skipped" for item in results),
        "table_counts": counts,
        "restored_table_counts": restored_counts,
        "safe_confirmed_review_count": safe_confirmed_count,
        "pending_match_candidate_count": len(candidates),
        "files": [asdict(item) for item in results],
    }
    (output_directory / "acceptance-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    return report


def _table_counts(store: LedgerStore) -> dict[str, int]:
    return {
        table: int(store.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in TABLE_ORDER
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bills", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = run_acceptance(args.bills.resolve(), args.output.resolve())
    except (OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
