from pathlib import Path

from scripts.acceptance_full_ledger import discover_statements, run_acceptance


def _alipay_statement(path: Path) -> None:
    path.parent.mkdir(parents=True)
    path.write_text(
        "交易时间,交易分类,交易对方,商品说明,收/支,金额,收/付款方式,交易状态,交易订单号,商家订单号\n"
        "2026-09-01 12:30:00,餐饮美食,测试商户,午餐,支出,12.34,余额,交易成功,order-1,merchant-1\n",
        encoding="utf-8",
    )


def test_discovery_skips_archives_but_keeps_extracted_supported_statements(tmp_path: Path) -> None:
    root = tmp_path / "账单文件"
    _alipay_statement(root / "支付宝" / "账单.csv")
    (root / "支付宝" / "原始包.zip").write_bytes(b"archive")

    statements, skipped = discover_statements(root)

    assert [(item.relative_path, item.format_id) for item in statements] == [
        ("支付宝/账单.csv", "alipay.csv")
    ]
    assert skipped[0].status == "skipped"
    assert "已解压" in skipped[0].message


def test_complete_acceptance_exports_one_restorable_mobile_archive(tmp_path: Path) -> None:
    root = tmp_path / "账单文件"
    _alipay_statement(root / "支付宝" / "账单.csv")
    output = tmp_path / "acceptance"

    report = run_acceptance(root, output)

    assert report["success"] is True
    assert report["discovered_count"] == 1
    assert report["unprocessed_count"] == 0
    assert report["table_counts"] == report["restored_table_counts"]
    assert report["table_counts"]["raw_transactions"] == 1
    assert report["table_counts"]["canonical_transactions"] == 1
    assert report["safe_confirmed_review_count"] == 1
    assert report["pending_match_candidate_count"] == 0
    assert Path(report["portable_archive"]).is_file()
