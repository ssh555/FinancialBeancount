"""Versioned, local-first JSON API for mobile clients."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

from .candidate_review import CandidateReviewEvent, CandidateReviewGroup, CandidateReviewService
from .ledger_models import CanonicalTransaction, RawTransaction
from .ledger_store import SCHEMA_VERSION, LedgerStore
from .refund_relationships import RefundCandidate, RefundRelationshipService, RefundReviewEvent
from .review import ImportReviewService, ReviewEvent, ReviewItem, ReviewSession
from .statistics import StatisticsService
from .transaction_classification import (
    ClassificationCandidate,
    ClassificationEvent,
    TransactionClassificationService,
)

API_VERSION = "v1"


@dataclass(frozen=True)
class ApiResponse:
    status: int
    body: dict[str, Any]


class MobileLedgerApi:
    """Framework-independent API contract shared by tests and the HTTP server."""

    def __init__(self, store: LedgerStore):
        self.store = store
        self.review = CandidateReviewService(store)
        self.import_review = ImportReviewService(store)
        self.refund_review = RefundRelationshipService(store)
        self.classification_review = TransactionClassificationService(store)
        self.statistics = StatisticsService(store)

    def dispatch(  # noqa: PLR0911
        self,
        method: str,
        target: str,
        body: dict[str, Any] | None = None,
    ) -> ApiResponse:
        """Dispatch one API request without requiring a network connection."""

        parsed = urlsplit(target)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        try:
            if method == "GET" and path == "/api/v1/health":
                return self._ok(
                    {
                        "status": "ok",
                        "api_version": API_VERSION,
                        "schema_version": SCHEMA_VERSION,
                    }
                )
            if method == "GET" and path == "/api/v1/transactions":
                return self._list_transactions(query)
            if method == "GET" and path.startswith("/api/v1/transactions/"):
                return self._transaction_detail(path.rsplit("/", 1)[-1])
            if method == "GET" and path == "/api/v1/statistics/summary":
                report = self.statistics.summarize(
                    _optional_date(query, "date_from"), _optional_date(query, "date_to")
                )
                return self._ok(report.to_dict())
            if method == "GET" and path == "/api/v1/review/candidates":
                return self._list_candidates(query)
            if path.startswith("/api/v1/review/candidates/"):
                return self._candidate_route(method, path, body or {})
            if method == "GET" and path == "/api/v1/review/refunds":
                return self._list_refunds(query)
            if method == "POST" and path == "/api/v1/review/refunds/scan":
                refund_candidates = self.refund_review.generate_candidates()
                return self._ok(
                    {
                        "candidate_count": len(refund_candidates),
                        "ambiguous_count": sum(item.is_ambiguous for item in refund_candidates),
                    }
                )
            if path.startswith("/api/v1/review/refunds/"):
                return self._refund_route(method, path, body or {})
            if method == "GET" and path == "/api/v1/review/classifications":
                return self._list_classifications(query)
            if method == "POST" and path == "/api/v1/review/classifications/scan":
                classification_candidates = self.classification_review.generate_candidates()
                return self._ok({"candidate_count": len(classification_candidates)})
            if path.startswith("/api/v1/review/classifications/"):
                return self._classification_route(method, path, body or {})
            if method == "GET" and path == "/api/v1/import-reviews":
                return self._list_import_reviews(query)
            if path.startswith("/api/v1/import-reviews/"):
                return self._import_review_route(method, path, query, body or {})
            return self._error(HTTPStatus.NOT_FOUND, "not_found", "API route not found")
        except KeyError as exc:
            return self._error(
                HTTPStatus.NOT_FOUND, "not_found", f"record not found: {exc.args[0]}"
            )
        except (TypeError, ValueError) as exc:
            return self._error(HTTPStatus.CONFLICT, "invalid_request", str(exc))

    def _list_transactions(self, query: dict[str, list[str]]) -> ApiResponse:
        page, page_size = _pagination(query)
        date_from = _optional_date(query, "date_from")
        date_to = _optional_date(query, "date_to")
        selected, total = self.store.list_canonical_page(
            limit=page_size,
            offset=(page - 1) * page_size,
            date_from=date_from,
            date_to=date_to,
            direction=_optional_text(query, "direction"),
            category=_optional_text(query, "category"),
            search=_optional_text(query, "search"),
        )
        return self._ok(
            [_canonical_summary(item, self.store) for item in selected],
            {"page": page, "page_size": page_size, "total": total},
        )

    def _transaction_detail(self, canonical_id: str) -> ApiResponse:
        canonical = self.store.get_canonical(canonical_id)
        if canonical is None:
            raise KeyError(canonical_id)
        return self._ok(canonical.to_dict(include_sources=True))

    def _list_candidates(self, query: dict[str, list[str]]) -> ApiResponse:
        page, page_size = _pagination(query)
        status = query.get("status", ["pending"])[0]
        status_filter = None if status == "all" else status
        groups = self.review.list_groups(status_filter)
        start = (page - 1) * page_size
        selected = groups[start : start + page_size]
        return self._ok(
            [_candidate_summary(group) for group in selected],
            {"page": page, "page_size": page_size, "total": len(groups), "status": status},
        )

    def _candidate_route(self, method: str, path: str, body: dict[str, Any]) -> ApiResponse:
        parts = path.split("/")
        candidate_id = parts[5] if len(parts) > 5 else ""
        action = parts[6] if len(parts) > 6 else ""
        if not candidate_id:
            raise KeyError(candidate_id)
        if method == "GET" and not action:
            return self._ok(_candidate_detail(self.review.get_group(candidate_id)))
        if method == "GET" and action == "events":
            return self._ok([_event_dict(item) for item in self.review.list_events(candidate_id)])
        actor = body.get("actor")
        if method == "POST" and action in {"confirm", "reject"}:
            if not isinstance(actor, str) or not actor.strip():
                raise ValueError("actor is required")
            actor = actor.strip()
        if method == "POST" and action == "reject":
            assert isinstance(actor, str)
            return self._ok(_event_dict(self.review.reject(candidate_id, actor)))
        if method == "POST" and action == "confirm":
            assert isinstance(actor, str)
            changes = body.get("changes", {})
            if not isinstance(changes, dict):
                raise TypeError("changes must be an object")
            canonical, event = self.review.confirm(candidate_id, actor, changes)
            return self._ok(
                {"canonical": canonical.to_dict(include_sources=True), "event": _event_dict(event)}
            )
        return self._error(HTTPStatus.NOT_FOUND, "not_found", "API route not found")

    def _list_import_reviews(self, query: dict[str, list[str]]) -> ApiResponse:
        page, page_size = _pagination(query)
        sessions = self.import_review.list_sessions(_optional_text(query, "status"))
        start = (page - 1) * page_size
        return self._ok(
            [
                _review_session_dict(item, self.store)
                for item in sessions[start : start + page_size]
            ],
            {"page": page, "page_size": page_size, "total": len(sessions)},
        )

    def _list_refunds(self, query: dict[str, list[str]]) -> ApiResponse:
        page, page_size = _pagination(query)
        status = query.get("status", ["pending"])[0]
        status_filter = None if status == "all" else status
        candidates = self.refund_review.list_candidates(status_filter)
        start = (page - 1) * page_size
        selected = candidates[start : start + page_size]
        return self._ok(
            [_refund_summary(item, self.store) for item in selected],
            {"page": page, "page_size": page_size, "total": len(candidates), "status": status},
        )

    def _refund_route(self, method: str, path: str, body: dict[str, Any]) -> ApiResponse:
        parts = path.split("/")
        relationship_id = parts[5] if len(parts) > 5 else ""
        action = parts[6] if len(parts) > 6 else ""
        if not relationship_id:
            raise KeyError(relationship_id)
        candidate = self.refund_review.get_candidate(relationship_id)
        if method == "GET" and not action:
            return self._ok(_refund_detail(candidate, self.store))
        if method == "GET" and action == "events":
            events = self.refund_review.list_events(relationship_id)
            return self._ok([_refund_event_dict(event) for event in events])
        actor = _required_actor(body) if method == "POST" else ""
        if method == "POST" and action == "confirm":
            return self._ok(_refund_event_dict(self.refund_review.confirm(relationship_id, actor)))
        if method == "POST" and action == "reject":
            return self._ok(_refund_event_dict(self.refund_review.reject(relationship_id, actor)))
        return self._error(HTTPStatus.NOT_FOUND, "not_found", "API route not found")

    def _list_classifications(self, query: dict[str, list[str]]) -> ApiResponse:
        page, page_size = _pagination(query)
        status = query.get("status", ["pending"])[0]
        status_filter = None if status == "all" else status
        candidates = self.classification_review.list_candidates(status_filter)
        start = (page - 1) * page_size
        selected = candidates[start : start + page_size]
        return self._ok(
            [_classification_summary(item, self.store) for item in selected],
            {"page": page, "page_size": page_size, "total": len(candidates), "status": status},
        )

    def _classification_route(self, method: str, path: str, body: dict[str, Any]) -> ApiResponse:
        parts = path.split("/")
        candidate_id = parts[5] if len(parts) > 5 else ""
        action = parts[6] if len(parts) > 6 else ""
        if not candidate_id:
            raise KeyError(candidate_id)
        candidate = self.classification_review.get_candidate(candidate_id)
        if method == "GET" and not action:
            return self._ok(_classification_detail(candidate, self.store))
        if method == "GET" and action == "events":
            events = self.classification_review.list_events(candidate_id)
            return self._ok([_classification_event_dict(event) for event in events])
        actor = _required_actor(body) if method == "POST" else ""
        if method == "POST" and action == "confirm":
            event = self.classification_review.confirm(candidate_id, actor)
            return self._ok(_classification_event_dict(event))
        if method == "POST" and action == "reject":
            event = self.classification_review.reject(candidate_id, actor)
            return self._ok(_classification_event_dict(event))
        return self._error(HTTPStatus.NOT_FOUND, "not_found", "API route not found")

    def _import_review_route(  # noqa: PLR0911
        self,
        method: str,
        path: str,
        query: dict[str, list[str]],
        body: dict[str, Any],
    ) -> ApiResponse:
        parts = path.split("/")
        session_id = parts[4] if len(parts) > 4 else ""
        if not session_id:
            raise KeyError(session_id)
        if len(parts) == 5 and method == "GET":
            session = self.import_review.get_session(session_id)
            return self._ok(_review_session_dict(session, self.store))
        if len(parts) == 6 and parts[5] == "items" and method == "GET":
            page, page_size = _pagination(query)
            items = self.import_review.list_items(session_id)
            start = (page - 1) * page_size
            return self._ok(
                [_review_item_summary(item) for item in items[start : start + page_size]],
                {"page": page, "page_size": page_size, "total": len(items)},
            )
        if len(parts) < 7 or parts[5] != "items":
            return self._error(HTTPStatus.NOT_FOUND, "not_found", "API route not found")
        item_id = parts[6]
        item = self.import_review.get_item(item_id)
        if item.session_id != session_id:
            raise KeyError(item_id)
        action = parts[7] if len(parts) > 7 else ""
        if method == "GET" and not action:
            return self._ok(_review_item_detail(item))
        if method == "GET" and action == "events":
            events = self.import_review.list_events(item_id)
            return self._ok([_review_event_dict(event) for event in events])
        actor = _required_actor(body) if method == "POST" else ""
        if method == "POST" and action == "confirm":
            event = self.import_review.decide(item_id, "confirmed", actor)
            return self._ok(_review_event_dict(event))
        if method == "POST" and action == "reject":
            event = self.import_review.decide(item_id, "rejected", actor)
            return self._ok(_review_event_dict(event))
        if method == "POST" and action == "modify":
            changes = body.get("changes", {})
            if not isinstance(changes, dict):
                raise TypeError("changes must be an object")
            event = self.import_review.modify_canonical(item_id, changes, actor)
            return self._ok(_review_event_dict(event))
        return self._error(HTTPStatus.NOT_FOUND, "not_found", "API route not found")

    @staticmethod
    def _ok(data: Any, meta: dict[str, Any] | None = None) -> ApiResponse:
        body = {"data": data}
        if meta is not None:
            body["meta"] = meta
        return ApiResponse(HTTPStatus.OK, body)

    @staticmethod
    def _error(status: int, code: str, message: str) -> ApiResponse:
        return ApiResponse(status, {"error": {"code": code, "message": message}})


def serve_mobile_api(
    database_path: str,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    api_token: str | None = None,
) -> None:
    """Serve the API locally; non-loopback callers should always use a token."""

    if host not in {"127.0.0.1", "localhost", "::1"} and not api_token:
        raise ValueError("api_token is required when listening beyond localhost")
    store = LedgerStore(database_path)
    api = MobileLedgerApi(store)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self._dispatch()

        def do_POST(self) -> None:
            self._dispatch()

        def _dispatch(self) -> None:
            if api_token and self.headers.get("Authorization") != f"Bearer {api_token}":
                self._write(
                    ApiResponse(
                        HTTPStatus.UNAUTHORIZED,
                        {"error": {"code": "unauthorized", "message": "invalid API token"}},
                    )
                )
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                request_body = json.loads(self.rfile.read(length)) if length else None
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                self._write(
                    ApiResponse(
                        HTTPStatus.BAD_REQUEST,
                        {"error": {"code": "invalid_json", "message": "invalid JSON body"}},
                    )
                )
                return
            self._write(api.dispatch(self.command, self.path, request_body))

        def _write(self, response: ApiResponse) -> None:
            payload = json.dumps(response.body, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(response.status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: Any) -> None:
            return

    server = HTTPServer((host, port), Handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        store.close()


def main(argv: list[str] | None = None) -> None:
    """Run the local API from the installed console command."""

    parser = argparse.ArgumentParser(description="FinancialBeancount local mobile API")
    parser.add_argument("--database", default="ledger.sqlite3")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    serve_mobile_api(
        args.database,
        host=args.host,
        port=args.port,
        api_token=os.environ.get("FINANCIAL_BEANCOUNT_API_TOKEN"),
    )


def _pagination(query: dict[str, list[str]]) -> tuple[int, int]:
    page = int(query.get("page", ["1"])[0])
    page_size = int(query.get("page_size", ["50"])[0])
    if page < 1 or not 1 <= page_size <= 200:
        raise ValueError("page must be positive and page_size must be between 1 and 200")
    return page, page_size


def _optional_text(query: dict[str, list[str]], name: str) -> str | None:
    value = query.get(name, [""])[0].strip()
    return value or None


def _optional_date(query: dict[str, list[str]], name: str) -> date | None:
    value = _optional_text(query, name)
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} must use YYYY-MM-DD") from exc


def _canonical_summary(canonical: CanonicalTransaction, store: LedgerStore) -> dict[str, Any]:
    data = canonical.to_dict(include_sources=False)
    data["source_count"] = store.connection.execute(
        "SELECT COUNT(*) FROM source_record_links WHERE canonical_id = ?",
        (canonical.canonical_id,),
    ).fetchone()[0]
    return cast("dict[str, Any]", data)


def _raw_summary(raw: RawTransaction) -> dict[str, Any]:
    return cast("dict[str, Any]", raw.to_dict(include_original_row=False))


def _candidate_summary(group: CandidateReviewGroup) -> dict[str, Any]:
    return {
        "candidate_id": group.candidate.candidate_id,
        "status": group.candidate.status,
        "confidence": str(group.candidate.confidence),
        "is_ambiguous": group.candidate.is_ambiguous,
        "evidence": [item.to_dict() for item in group.candidate.evidence],
        "payment": _raw_summary(group.payment),
        "bank": _raw_summary(group.bank),
        "conflict_count": len(group.conflicts),
    }


def _candidate_detail(group: CandidateReviewGroup) -> dict[str, Any]:
    data = _candidate_summary(group)
    data["payment"] = group.payment.to_dict(include_original_row=True)
    data["bank"] = group.bank.to_dict(include_original_row=True)
    data["conflicts"] = [
        {
            "candidate_id": item.candidate_id,
            "status": item.status,
            "confidence": str(item.confidence),
            "is_ambiguous": item.is_ambiguous,
        }
        for item in group.conflicts
    ]
    return data


def _event_dict(event: CandidateReviewEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "candidate_id": event.candidate_id,
        "action": event.action,
        "before": event.before,
        "after": event.after,
        "actor": event.actor,
        "created_at": event.created_at.isoformat(),
    }


def _required_actor(body: dict[str, Any]) -> str:
    actor = body.get("actor")
    if not isinstance(actor, str) or not actor.strip():
        raise ValueError("actor is required")
    return actor.strip()


def _review_session_dict(session: ReviewSession, store: LedgerStore) -> dict[str, Any]:
    counts = store.connection.execute(
        """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending
        FROM review_items WHERE session_id = ?
        """,
        (session.session_id,),
    ).fetchone()
    return {
        "session_id": session.session_id,
        "import_batch_id": session.import_batch_id,
        "status": session.status,
        "created_at": session.created_at.isoformat(),
        "completed_at": session.completed_at.isoformat() if session.completed_at else None,
        "item_count": counts["total"],
        "pending_count": counts["pending"] or 0,
    }


def _review_item_summary(item: ReviewItem) -> dict[str, Any]:
    return {
        "review_item_id": item.review_item_id,
        "session_id": item.session_id,
        "item_type": item.item_type,
        "status": item.status,
        "raw": item.raw_transaction.to_dict(include_original_row=False),
        "canonical": item.canonical_transaction.to_dict(include_sources=False)
        if item.canonical_transaction
        else None,
        "created_at": item.created_at.isoformat(),
        "reviewed_at": item.reviewed_at.isoformat() if item.reviewed_at else None,
        "reviewed_by": item.reviewed_by,
    }


def _review_item_detail(item: ReviewItem) -> dict[str, Any]:
    data = _review_item_summary(item)
    data["raw"] = item.raw_transaction.to_dict(include_original_row=True)
    data["canonical"] = (
        item.canonical_transaction.to_dict(include_sources=True)
        if item.canonical_transaction
        else None
    )
    data["snapshot"] = item.snapshot
    return data


def _review_event_dict(event: ReviewEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "review_item_id": event.review_item_id,
        "action": event.action,
        "before": event.before,
        "after": event.after,
        "actor": event.actor,
        "created_at": event.created_at.isoformat(),
    }


def _refund_summary(candidate: RefundCandidate, store: LedgerStore) -> dict[str, Any]:
    refund = store.get_canonical(candidate.refund_canonical_id)
    original = store.get_canonical(candidate.original_canonical_id)
    if refund is None or original is None:
        raise RuntimeError(
            f"refund relationship is missing a transaction: {candidate.relationship_id}"
        )
    return {
        "relationship_id": candidate.relationship_id,
        "status": candidate.status,
        "amount": str(candidate.amount),
        "confidence": str(candidate.confidence),
        "evidence": list(candidate.evidence),
        "is_ambiguous": candidate.is_ambiguous,
        "refund": refund.to_dict(include_sources=False),
        "original": original.to_dict(include_sources=False),
    }


def _refund_detail(candidate: RefundCandidate, store: LedgerStore) -> dict[str, Any]:
    data = _refund_summary(candidate, store)
    refund = store.get_canonical(candidate.refund_canonical_id)
    original = store.get_canonical(candidate.original_canonical_id)
    if refund is None or original is None:
        raise RuntimeError(
            f"refund relationship is missing a transaction: {candidate.relationship_id}"
        )
    data["refund"] = refund.to_dict(include_sources=True)
    data["original"] = original.to_dict(include_sources=True)
    return data


def _refund_event_dict(event: RefundReviewEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "relationship_id": event.relationship_id,
        "action": event.action,
        "before": event.before,
        "after": event.after,
        "actor": event.actor,
        "created_at": event.created_at.isoformat(),
    }


def _classification_summary(
    candidate: ClassificationCandidate, store: LedgerStore
) -> dict[str, Any]:
    transaction = store.get_canonical(candidate.canonical_id)
    if transaction is None:
        raise RuntimeError(f"classification transaction is missing: {candidate.candidate_id}")
    return {
        "candidate_id": candidate.candidate_id,
        "status": candidate.status,
        "proposed_type": candidate.proposed_type.value,
        "proposed_category": candidate.proposed_category,
        "confidence": str(candidate.confidence),
        "evidence": list(candidate.evidence),
        "transaction": transaction.to_dict(include_sources=False),
    }


def _classification_detail(
    candidate: ClassificationCandidate, store: LedgerStore
) -> dict[str, Any]:
    data = _classification_summary(candidate, store)
    transaction = store.get_canonical(candidate.canonical_id)
    if transaction is None:
        raise RuntimeError(f"classification transaction is missing: {candidate.candidate_id}")
    data["transaction"] = transaction.to_dict(include_sources=True)
    return data


def _classification_event_dict(event: ClassificationEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "candidate_id": event.candidate_id,
        "action": event.action,
        "before": event.before,
        "after": event.after,
        "actor": event.actor,
        "created_at": event.created_at.isoformat(),
    }
