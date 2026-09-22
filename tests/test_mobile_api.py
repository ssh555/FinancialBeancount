"""Tests for the versioned local-first mobile JSON API."""

import base64
from datetime import date, datetime

import pytest
from beancount_dedup import mobile_api as mobile_api_module
from beancount_dedup.canonical_matcher import ConservativeMatcher
from beancount_dedup.ledger_models import CanonicalTransaction, RawTransaction
from beancount_dedup.ledger_store import LedgerStore
from beancount_dedup.mobile_api import MobileLedgerApi, load_web_asset, serve_mobile_api
from beancount_dedup.models import Platform, TransactionType
from beancount_dedup.review import ImportReviewService


@pytest.fixture
def store(tmp_path):
    with LedgerStore(tmp_path / "ledger.sqlite3") as ledger_store:
        yield ledger_store


def raw(source: Platform, identity: str) -> RawTransaction:
    merchant = "高德打车" if source != Platform.BANK else "高德信息技术有限公司"
    return RawTransaction(
        source=source,
        source_account=f"account-{identity}",
        transaction_time=datetime(2026, 6, 1, 12, 0) if source != Platform.BANK else None,
        booking_date=date(2026, 6, 1),
        amount="-20.00",
        direction="expense",
        merchant=merchant,
        counterparty=merchant,
        payment_method="招商银行",
        bank_card_suffix="5066",
        transaction_id=identity,
        original_row={"sensitive_source_value": identity},
    )


def candidate(store):
    store.add_raw(raw(Platform.ALIPAY, "payment"))
    store.add_raw(raw(Platform.BANK, "bank"))
    return ConservativeMatcher(store).generate_candidates()[0]


def test_health_and_unknown_route(store):
    api = MobileLedgerApi(store)

    health = api.dispatch("GET", "/api/v1/health")
    missing = api.dispatch("GET", "/api/v1/missing")

    assert health.status == 200
    assert health.body["data"]["api_version"] == "v1"
    assert missing.status == 404
    assert missing.body["error"]["code"] == "not_found"


def test_bundled_web_client_assets_are_available_and_whitelisted():
    index = load_web_asset("/")
    script = load_web_asset("/app.js")
    manifest = load_web_asset("/manifest.webmanifest")

    assert index is not None
    assert index.content_type == "text/html; charset=utf-8"
    assert "本地账本".encode() in index.body
    assert script is not None
    assert b"/api/v1/statistics/summary" in script.body
    assert manifest is not None
    assert load_web_asset("/../ledger.sqlite3") is None


def test_cli_can_request_browser_launch(monkeypatch):
    received = {}

    def fake_serve(database_path, **options):
        received.update({"database_path": database_path, **options})

    monkeypatch.setattr(mobile_api_module, "serve_mobile_api", fake_serve)
    mobile_api_module.main(
        ["--database", "test.sqlite3", "--port", "9000", "--open-browser"]
    )

    assert received["database_path"] == "test.sqlite3"
    assert received["port"] == 9000
    assert received["open_browser"] is True


def test_transaction_list_is_compact_but_detail_contains_all_sources(store):
    payment = store.add_raw(raw(Platform.ALIPAY, "payment")).raw_transaction
    bank = store.add_raw(raw(Platform.BANK, "bank")).raw_transaction
    canonical = CanonicalTransaction(
        transaction_time=payment.transaction_time,
        booking_date=date(2026, 6, 1),
        amount="-20.00",
        direction="expense",
        merchant="高德打车",
    )
    for item in (payment, bank):
        canonical.add_source(
            item,
            confidence="1",
            reasons=["manual_confirmed"],
            matcher_version="test-v1",
        )
    store.add_canonical(canonical)
    api = MobileLedgerApi(store)

    listing = api.dispatch("GET", "/api/v1/transactions?page=1&page_size=20")
    detail = api.dispatch("GET", f"/api/v1/transactions/{canonical.canonical_id}")

    assert listing.status == 200
    assert listing.body["data"][0]["source_count"] == 2
    assert "sources" not in listing.body["data"][0]
    assert len(detail.body["data"]["sources"]) == 2
    assert detail.body["data"]["sources"][0]["raw_transaction"]["original_row"]


def test_transaction_list_supports_generic_filters(store):
    matching = CanonicalTransaction(
        transaction_time=datetime(2026, 6, 1, 12, 0),
        booking_date=date(2026, 6, 1),
        amount="-20.00",
        direction="expense",
        merchant="高德打车",
        category="交通",
        notes="机场行程",
    )
    other = CanonicalTransaction(
        transaction_time=datetime(2025, 6, 1, 12, 0),
        booking_date=date(2025, 6, 1),
        amount="-10.00",
        direction="expense",
        merchant="早餐店",
        category="餐饮",
    )
    store.add_canonical(matching)
    store.add_canonical(other)
    api = MobileLedgerApi(store)

    response = api.dispatch(
        "GET",
        "/api/v1/transactions?date_from=2026-01-01&date_to=2026-12-31"
        "&direction=expense&category=交通&search=机场",
    )

    assert response.status == 200
    assert response.body["meta"]["total"] == 1
    assert response.body["data"][0]["canonical_id"] == matching.canonical_id


def test_transaction_crud_uses_soft_delete_and_audit_events(store):
    api = MobileLedgerApi(store)
    created = api.dispatch(
        "POST",
        "/api/v1/transactions",
        {
            "actor": "local-user",
            "booking_date": "2026-09-22",
            "amount": "-18.50",
            "direction": "expense",
            "merchant": "手工记录",
            "category": "餐饮",
            "tx_type": "expense",
        },
    )
    canonical_id = created.body["data"]["canonical_id"]

    updated = api.dispatch(
        "PATCH",
        f"/api/v1/transactions/{canonical_id}",
        {"actor": "local-user", "changes": {"merchant": "修正后的商户"}},
    )
    deleted = api.dispatch(
        "DELETE",
        f"/api/v1/transactions/{canonical_id}",
        {"actor": "local-user", "reason": "录入错误"},
    )
    hidden = api.dispatch("GET", f"/api/v1/transactions/{canonical_id}")
    listing = api.dispatch("GET", "/api/v1/transactions")
    deleted_listing = api.dispatch("GET", "/api/v1/deleted-transactions")
    restored = api.dispatch(
        "POST", f"/api/v1/transactions/{canonical_id}/restore", {"actor": "local-user"}
    )
    events = api.dispatch("GET", f"/api/v1/transactions/{canonical_id}/events")

    assert created.status == 200
    assert updated.body["data"]["merchant"] == "修正后的商户"
    assert deleted.body["data"]["deleted"] is True
    assert hidden.status == 404
    assert listing.body["meta"]["total"] == 0
    assert deleted_listing.body["meta"]["total"] == 1
    assert deleted_listing.body["data"][0]["deletion_reason"] == "录入错误"
    assert restored.body["data"]["canonical_id"] == canonical_id
    assert [item["action"] for item in events.body["data"]] == [
        "created",
        "updated",
        "deleted",
        "restored",
    ]


def test_statement_import_and_canonical_export_api(store):
    api = MobileLedgerApi(store)
    sample = (
        "支付宝交易记录明细查询\n"
        "交易时间,交易分类,交易对方,商品说明,收/支,金额,收/付款方式,交易状态,"
        "交易订单号,商家订单号\n"
        "2026-09-01 08:30:00,餐饮美食,测试早餐店,早餐,支出,18.50,余额,交易成功,"
        "202609010001,MERCHANT001\n"
    ).encode("utf-8-sig")
    formats = api.dispatch("GET", "/api/v1/import-formats")
    imported = api.dispatch(
        "POST",
        "/api/v1/imports",
        {
            "format_id": "alipay.csv",
            "source_account": "test-account",
            "filename": "sample_alipay.csv",
            "content_base64": base64.b64encode(sample).decode(),
        },
    )
    exported = api.dispatch("GET", "/api/v1/exports/transactions?format=json")

    assert any(item["format_id"] == "alipay.csv" for item in formats.body["data"])
    assert imported.status == 200
    assert imported.body["data"]["parsed_count"] > 0
    assert imported.body["data"]["pending_review_count"] > 0
    assert exported.body["meta"]["format"] == "json"


def test_candidate_list_redacts_original_row_and_detail_expands_it(store):
    match = candidate(store)
    api = MobileLedgerApi(store)

    listing = api.dispatch("GET", "/api/v1/review/candidates")
    detail = api.dispatch("GET", f"/api/v1/review/candidates/{match.candidate_id}")

    assert listing.status == 200
    assert "original_row" not in listing.body["data"][0]["payment"]
    assert detail.body["data"]["payment"]["original_row"]["sensitive_source_value"]


def test_confirm_modify_and_audit_through_api(store):
    match = candidate(store)
    api = MobileLedgerApi(store)

    confirmed = api.dispatch(
        "POST",
        f"/api/v1/review/candidates/{match.candidate_id}/confirm",
        {"actor": "mobile-user", "changes": {"merchant": "人工修正", "category": "交通"}},
    )
    events = api.dispatch("GET", f"/api/v1/review/candidates/{match.candidate_id}/events")

    assert confirmed.status == 200
    assert confirmed.body["data"]["canonical"]["merchant"] == "人工修正"
    assert confirmed.body["data"]["canonical"]["source_count"] == 2
    assert events.body["data"][0]["action"] == "modified_confirmed"
    assert events.body["data"][0]["actor"] == "mobile-user"


def test_reject_and_validation_errors_are_structured(store):
    match = candidate(store)
    api = MobileLedgerApi(store)

    missing_actor = api.dispatch(
        "POST", f"/api/v1/review/candidates/{match.candidate_id}/reject", {}
    )
    rejected = api.dispatch(
        "POST",
        f"/api/v1/review/candidates/{match.candidate_id}/reject",
        {"actor": "mobile-user"},
    )
    repeated = api.dispatch(
        "POST",
        f"/api/v1/review/candidates/{match.candidate_id}/reject",
        {"actor": "mobile-user"},
    )

    assert missing_actor.status == 409
    assert rejected.status == 200
    assert repeated.status == 409


def test_invalid_pagination_and_nonlocal_server_without_token(store):
    api = MobileLedgerApi(store)

    response = api.dispatch("GET", "/api/v1/transactions?page=0&page_size=500")

    assert response.status == 409
    with pytest.raises(ValueError, match="api_token"):
        serve_mobile_api(store.path, host="0.0.0.0")


def test_import_review_api_lists_details_decisions_and_events(store):
    batch, _ = store.start_import_batch(Platform.ALIPAY, "annual.csv", "annual-hash")
    current_raw = raw(Platform.ALIPAY, "current")
    current_raw = RawTransaction(**{**current_raw.__dict__, "import_batch_id": batch.batch_id})
    current = store.add_raw(current_raw)
    missing = store.add_raw(raw(Platform.ALIPAY, "missing")).raw_transaction
    session = ImportReviewService(store).create_session(
        batch.batch_id, [current], missing_from_import=[missing]
    )
    api = MobileLedgerApi(store)

    sessions = api.dispatch("GET", "/api/v1/import-reviews?status=pending")
    items = api.dispatch("GET", f"/api/v1/import-reviews/{session.session_id}/items")
    gap = next(
        item for item in items.body["data"] if item["item_type"].endswith("missing_from_import")
    )
    detail = api.dispatch(
        "GET",
        f"/api/v1/import-reviews/{session.session_id}/items/{gap['review_item_id']}",
    )
    confirmed = api.dispatch(
        "POST",
        f"/api/v1/import-reviews/{session.session_id}/items/{gap['review_item_id']}/confirm",
        {"actor": "mobile-user"},
    )
    events = api.dispatch(
        "GET",
        f"/api/v1/import-reviews/{session.session_id}/items/{gap['review_item_id']}/events",
    )

    assert sessions.status == 200
    assert sessions.body["data"][0]["pending_count"] == 2
    assert detail.body["data"]["snapshot"]["missing_from_import"] is True
    assert confirmed.body["data"]["action"] == "confirmed"
    assert events.body["data"][0]["actor"] == "mobile-user"


def test_import_review_api_rejects_item_from_another_session(store):
    first_batch, _ = store.start_import_batch(Platform.ALIPAY, "first.csv", "first-hash")
    second_batch, _ = store.start_import_batch(Platform.ALIPAY, "second.csv", "second-hash")
    first_result = store.add_raw(raw(Platform.ALIPAY, "first"))
    second_result = store.add_raw(raw(Platform.ALIPAY, "second"))
    first = ImportReviewService(store).create_session(first_batch.batch_id, [first_result])
    second = ImportReviewService(store).create_session(second_batch.batch_id, [second_result])
    second_item = ImportReviewService(store).list_items(second.session_id)[0]

    response = MobileLedgerApi(store).dispatch(
        "GET", f"/api/v1/import-reviews/{first.session_id}/items/{second_item.review_item_id}"
    )

    assert response.status == 404


def test_refund_review_api_scans_details_confirms_and_audits(store):
    original = CanonicalTransaction(
        transaction_time=datetime(2026, 3, 1, 12, 0),
        booking_date=date(2026, 3, 1),
        amount="-100",
        direction="expense",
        merchant="星巴克咖啡",
        tx_type=TransactionType.EXPENSE,
    )
    refund = CanonicalTransaction(
        transaction_time=datetime(2026, 3, 5, 12, 0),
        booking_date=date(2026, 3, 5),
        amount="100",
        direction="income",
        merchant="星巴克退款",
        status="退款成功",
        tx_type=TransactionType.INCOME,
    )
    store.add_canonical(original)
    store.add_canonical(refund)
    api = MobileLedgerApi(store)

    scan = api.dispatch("POST", "/api/v1/review/refunds/scan", {})
    listing = api.dispatch("GET", "/api/v1/review/refunds")
    relationship_id = listing.body["data"][0]["relationship_id"]
    detail = api.dispatch("GET", f"/api/v1/review/refunds/{relationship_id}")
    missing_actor = api.dispatch("POST", f"/api/v1/review/refunds/{relationship_id}/confirm", {})
    confirmed = api.dispatch(
        "POST",
        f"/api/v1/review/refunds/{relationship_id}/confirm",
        {"actor": "mobile-user"},
    )
    events = api.dispatch("GET", f"/api/v1/review/refunds/{relationship_id}/events")

    assert scan.body["data"] == {"candidate_count": 1, "ambiguous_count": 0}
    assert "sources" not in listing.body["data"][0]["refund"]
    assert "sources" in detail.body["data"]["refund"]
    assert missing_actor.status == 409
    assert confirmed.body["data"]["action"] == "confirmed"
    assert events.body["data"][0]["actor"] == "mobile-user"
    assert store.get_canonical(refund.canonical_id).tx_type == TransactionType.REFUND


def test_non_consumption_classification_api_scans_and_reviews(store):
    item = CanonicalTransaction(
        transaction_time=datetime(2026, 3, 1, 12, 0),
        booking_date=date(2026, 3, 1),
        amount="-500",
        direction="expense",
        merchant="招商银行信用卡还款",
        tx_type=TransactionType.EXPENSE,
    )
    store.add_canonical(item)
    api = MobileLedgerApi(store)

    scan = api.dispatch("POST", "/api/v1/review/classifications/scan", {})
    listing = api.dispatch("GET", "/api/v1/review/classifications")
    candidate_id = listing.body["data"][0]["candidate_id"]
    detail = api.dispatch("GET", f"/api/v1/review/classifications/{candidate_id}")
    missing_actor = api.dispatch(
        "POST", f"/api/v1/review/classifications/{candidate_id}/confirm", {}
    )
    confirmed = api.dispatch(
        "POST",
        f"/api/v1/review/classifications/{candidate_id}/confirm",
        {"actor": "mobile-user"},
    )
    events = api.dispatch("GET", f"/api/v1/review/classifications/{candidate_id}/events")

    assert scan.body["data"]["candidate_count"] == 1
    assert listing.body["data"][0]["proposed_type"] == "transfer"
    assert "sources" not in listing.body["data"][0]["transaction"]
    assert "sources" in detail.body["data"]["transaction"]
    assert missing_actor.status == 409
    assert confirmed.body["data"]["after"]["tx_type"] == "transfer"
    assert events.body["data"][0]["actor"] == "mobile-user"
    assert store.get_canonical(item.canonical_id).category == "信用卡还款"


def test_statistics_summary_api_uses_date_filters(store):
    march = CanonicalTransaction(
        transaction_time=None,
        booking_date=date(2026, 3, 1),
        amount="-80",
        direction="expense",
        merchant="餐饮商户",
        category="餐饮",
        tx_type=TransactionType.EXPENSE,
    )
    april = CanonicalTransaction(
        transaction_time=None,
        booking_date=date(2026, 4, 1),
        amount="-20",
        direction="expense",
        merchant="交通商户",
        category="交通",
        tx_type=TransactionType.EXPENSE,
    )
    store.add_canonical(march)
    store.add_canonical(april)

    response = MobileLedgerApi(store).dispatch(
        "GET", "/api/v1/statistics/summary?date_from=2026-03-01&date_to=2026-03-31"
    )

    assert response.status == 200
    assert response.body["data"]["gross_expense"] == "80"
    assert response.body["data"]["net_expense"] == "80"
    assert response.body["data"]["categories"][0]["category"] == "餐饮"
