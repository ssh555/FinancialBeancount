"""Complete human review workflow for batch imports and existing ledger impact."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .ledger_models import CanonicalTransaction, RawTransaction, ReviewStatus
from .ledger_store import LedgerStore, RawImportResult
from .models import TransactionType, source_id_value

REVIEW_DECISIONS = {"confirmed", "rejected", "modified"}


@dataclass(frozen=True)
class ReviewSession:
    session_id: str
    import_batch_id: str
    status: str
    created_at: datetime
    completed_at: datetime | None = None


@dataclass(frozen=True)
class ReviewItem:
    review_item_id: str
    session_id: str
    raw_transaction: RawTransaction
    canonical_transaction: CanonicalTransaction | None
    item_type: str
    status: str
    snapshot: dict[str, Any]
    created_at: datetime
    reviewed_at: datetime | None = None
    reviewed_by: str | None = None


@dataclass(frozen=True)
class ReviewEvent:
    event_id: str
    review_item_id: str
    action: str
    before: dict[str, Any]
    after: dict[str, Any]
    actor: str
    created_at: datetime


class ImportReviewService:
    """Build and resolve an exhaustive audit scope for every imported row."""

    def __init__(self, store: LedgerStore):
        self.store = store

    def create_session(
        self,
        import_batch_id: str,
        results: list[RawImportResult],
        missing_from_import: list[RawTransaction] | None = None,
    ) -> ReviewSession:
        """Include new rows, prior rows, and every existing linked source."""

        session = ReviewSession(
            session_id=str(uuid.uuid4()),
            import_batch_id=import_batch_id,
            status="pending",
            created_at=datetime.now(),
        )
        with self.store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO review_sessions(
                    session_id, import_batch_id, status, created_at, completed_at
                ) VALUES (?, ?, ?, ?, NULL)
                """,
                (
                    session.session_id,
                    session.import_batch_id,
                    session.status,
                    session.created_at.isoformat(),
                ),
            )
            for result in results:
                canonical = self.store.find_canonical_for_raw(result.raw_transaction.raw_id)
                if result.created:
                    item_type = "new_linked" if canonical else "new_unmatched"
                else:
                    item_type = "existing_linked" if canonical else "existing_unmatched"
                snapshot = {
                    "imported_observation": result.imported_observation.to_dict(),
                    "persisted_raw": result.raw_transaction.to_dict(),
                    "was_created": result.created,
                    "affected_canonical": canonical.to_dict() if canonical else None,
                }
                connection.execute(
                    """
                    INSERT INTO review_items(
                        review_item_id, session_id, raw_id, canonical_id, item_type,
                        status, snapshot_json, created_at, reviewed_at, reviewed_by
                    ) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, NULL, NULL)
                    """,
                    (
                        str(uuid.uuid4()),
                        session.session_id,
                        result.raw_transaction.raw_id,
                        canonical.canonical_id if canonical else None,
                        item_type,
                        json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                        session.created_at.isoformat(),
                    ),
                )
            for raw in missing_from_import or []:
                canonical = self.store.find_canonical_for_raw(raw.raw_id)
                snapshot = {
                    "imported_observation": None,
                    "persisted_raw": raw.to_dict(),
                    "was_created": False,
                    "missing_from_import": True,
                    "affected_canonical": canonical.to_dict() if canonical else None,
                }
                connection.execute(
                    """
                    INSERT INTO review_items(
                        review_item_id, session_id, raw_id, canonical_id, item_type,
                        status, snapshot_json, created_at, reviewed_at, reviewed_by
                    ) VALUES (?, ?, ?, ?, 'existing_missing_from_import',
                              'pending', ?, ?, NULL, NULL)
                    """,
                    (
                        str(uuid.uuid4()),
                        session.session_id,
                        raw.raw_id,
                        canonical.canonical_id if canonical else None,
                        json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                        session.created_at.isoformat(),
                    ),
                )
        return session

    def list_items(self, session_id: str) -> list[ReviewItem]:
        rows = self.store.connection.execute(
            "SELECT * FROM review_items WHERE session_id = ? ORDER BY created_at, review_item_id",
            (session_id,),
        ).fetchall()
        return [self._item_from_row(row) for row in rows]

    def get_item(self, review_item_id: str) -> ReviewItem:
        return self._item_from_row(self._item_row(review_item_id))

    def list_sessions(self, status: str | None = None) -> list[ReviewSession]:
        where = "WHERE status = ?" if status else ""
        parameters = (status,) if status else ()
        rows = self.store.connection.execute(
            f"SELECT * FROM review_sessions {where} ORDER BY created_at DESC, session_id",
            parameters,
        ).fetchall()
        return [self._session_from_row(row) for row in rows]

    def get_session(self, session_id: str) -> ReviewSession:
        row = self.store.connection.execute(
            "SELECT * FROM review_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is None:
            raise KeyError(session_id)
        return self._session_from_row(row)

    def decide(self, review_item_id: str, decision: str, actor: str) -> ReviewEvent:
        """Confirm or reject an item without changing immutable source evidence."""

        if decision not in REVIEW_DECISIONS - {"modified"}:
            raise ValueError("decision must be confirmed or rejected")
        return self._record_decision(review_item_id, decision, actor, changes=None)

    def modify_canonical(
        self,
        review_item_id: str,
        changes: dict[str, str | None],
        actor: str,
    ) -> ReviewEvent:
        """Apply reviewed canonical corrections and preserve before/after values."""

        return self._record_decision(review_item_id, "modified", actor, changes=changes)

    def _record_decision(
        self,
        review_item_id: str,
        decision: str,
        actor: str,
        changes: dict[str, str | None] | None,
    ) -> ReviewEvent:
        row = self._item_row(review_item_id)
        if row["status"] != "pending":
            raise ValueError("review item has already been decided")
        canonical = (
            self.store.get_canonical(row["canonical_id"])
            if row["canonical_id"]
            else self.store.find_canonical_for_raw(row["raw_id"])
        )
        before = {
            "review_status": row["status"],
            "canonical": canonical.to_dict() if canonical else None,
        }
        now = datetime.now()
        with self.store.transaction() as connection:
            if decision in {"confirmed", "modified"} and canonical is None:
                raw = self.store.get_raw(row["raw_id"])
                if raw is None:
                    raise RuntimeError(f"review raw record is missing: {row['raw_id']}")
                canonical = self._canonical_from_confirmed_raw(raw, actor)
                self.store._insert_canonical(connection, canonical)
                connection.execute(
                    "UPDATE review_items SET canonical_id = ? WHERE review_item_id = ?",
                    (canonical.canonical_id, review_item_id),
                )
            if changes:
                if canonical is None:
                    raise RuntimeError("canonical transaction was not created")
                self.store._update_canonical_fields(connection, canonical.canonical_id, changes)
                canonical = self.store.get_canonical(canonical.canonical_id)
            after = {
                "review_status": decision,
                "canonical": canonical.to_dict() if canonical else None,
            }
            event = ReviewEvent(
                event_id=str(uuid.uuid4()),
                review_item_id=review_item_id,
                action=decision,
                before=before,
                after=after,
                actor=actor,
                created_at=now,
            )
            connection.execute(
                """
                UPDATE review_items
                SET status = ?, reviewed_at = ?, reviewed_by = ?
                WHERE review_item_id = ?
                """,
                (decision, now.isoformat(), actor, review_item_id),
            )
            connection.execute(
                """
                INSERT INTO review_events(
                    event_id, review_item_id, action, before_json, after_json,
                    actor, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.review_item_id,
                    event.action,
                    json.dumps(event.before, ensure_ascii=False, sort_keys=True),
                    json.dumps(event.after, ensure_ascii=False, sort_keys=True),
                    event.actor,
                    event.created_at.isoformat(),
                ),
            )
            pending = connection.execute(
                """
                SELECT COUNT(*) FROM review_items
                WHERE session_id = ? AND status = 'pending'
                """,
                (row["session_id"],),
            ).fetchone()[0]
            if pending == 0:
                connection.execute(
                    """
                    UPDATE review_sessions
                    SET status = 'completed', completed_at = ?
                    WHERE session_id = ?
                    """,
                    (now.isoformat(), row["session_id"]),
                )
        return event

    @staticmethod
    def _canonical_from_confirmed_raw(raw: RawTransaction, actor: str) -> CanonicalTransaction:
        booking_date = raw.booking_date or (
            raw.transaction_time.date() if raw.transaction_time else None
        )
        if booking_date is None:
            raise ValueError("raw transaction has no booking date")
        if raw.direction == "expense":
            tx_type = TransactionType.EXPENSE
        elif raw.direction == "income":
            tx_type = TransactionType.INCOME
        else:
            tx_type = TransactionType.UNKNOWN
        canonical = CanonicalTransaction(
            transaction_time=raw.transaction_time,
            booking_date=booking_date,
            amount=raw.amount,
            direction=raw.direction,
            merchant=raw.merchant or raw.counterparty,
            payment_channel=source_id_value(raw.source),
            funding_account=raw.payment_method or raw.source_account,
            tx_type=tx_type,
            status=raw.status,
            review_status=ReviewStatus.CONFIRMED,
        )
        canonical.add_source(
            raw,
            confidence="1",
            reasons=["human_confirmed_unmatched"],
            matcher_version="manual-v1",
            linked_by=actor,
        )
        return canonical

    def list_events(self, review_item_id: str) -> list[ReviewEvent]:
        rows = self.store.connection.execute(
            """
            SELECT * FROM review_events
            WHERE review_item_id = ? ORDER BY created_at, event_id
            """,
            (review_item_id,),
        ).fetchall()
        return [
            ReviewEvent(
                event_id=row["event_id"],
                review_item_id=row["review_item_id"],
                action=row["action"],
                before=json.loads(row["before_json"]),
                after=json.loads(row["after_json"]),
                actor=row["actor"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    def _item_row(self, review_item_id: str):
        row = self.store.connection.execute(
            "SELECT * FROM review_items WHERE review_item_id = ?", (review_item_id,)
        ).fetchone()
        if row is None:
            raise KeyError(review_item_id)
        return row

    def _item_from_row(self, row: Any) -> ReviewItem:
        raw = self.store.get_raw(row["raw_id"])
        if raw is None:
            raise RuntimeError(f"review raw record is missing: {row['raw_id']}")
        return ReviewItem(
            review_item_id=row["review_item_id"],
            session_id=row["session_id"],
            raw_transaction=raw,
            canonical_transaction=self.store.get_canonical(row["canonical_id"])
            if row["canonical_id"]
            else None,
            item_type=row["item_type"],
            status=row["status"],
            snapshot=json.loads(row["snapshot_json"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            reviewed_at=datetime.fromisoformat(row["reviewed_at"]) if row["reviewed_at"] else None,
            reviewed_by=row["reviewed_by"],
        )

    @staticmethod
    def _session_from_row(row: Any) -> ReviewSession:
        return ReviewSession(
            session_id=row["session_id"],
            import_batch_id=row["import_batch_id"],
            status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"]),
            completed_at=datetime.fromisoformat(row["completed_at"])
            if row["completed_at"]
            else None,
        )
