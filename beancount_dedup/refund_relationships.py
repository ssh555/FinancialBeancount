"""Auditable full and partial refund relationships between canonical transactions."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import sqlite3

from .ledger_models import CanonicalTransaction
from .ledger_store import LedgerStore
from .models import TransactionType

REFUND_MARKERS = ("退款", "退回", "退还", "refund")
REFUND_MATCHER_VERSION = "canonical-refund-v1"
WARNING_ACKNOWLEDGED = "warning_acknowledged"


@dataclass(frozen=True)
class RefundCandidate:
    relationship_id: str
    refund_canonical_id: str
    original_canonical_id: str
    amount: Decimal
    confidence: Decimal
    evidence: tuple[str, ...]
    status: str = "pending"
    is_ambiguous: bool = False
    created_at: datetime = datetime.min


@dataclass(frozen=True)
class RefundReviewEvent:
    event_id: str
    relationship_id: str
    action: str
    before: dict[str, Any]
    after: dict[str, Any]
    actor: str
    created_at: datetime


class RefundRelationshipService:
    """Generate and review refunds without treating them as ordinary income."""

    def __init__(self, store: LedgerStore, match_window_days: int = 180):
        self.store = store
        self.match_window = timedelta(days=match_window_days)

    def generate_candidates(self) -> list[RefundCandidate]:
        transactions = self.store.list_canonical()
        refunds = [item for item in transactions if self._is_refund(item)]
        expenses = [item for item in transactions if item.amount < 0]
        candidates: list[RefundCandidate] = []
        for refund in refunds:
            for original in expenses:
                candidate = self._candidate(refund, original)
                if candidate:
                    candidates.append(candidate)
        counts: dict[str, int] = {}
        for candidate in candidates:
            counts[candidate.refund_canonical_id] = counts.get(candidate.refund_canonical_id, 0) + 1
        candidates = [
            replace(item, is_ambiguous=counts[item.refund_canonical_id] > 1) for item in candidates
        ]
        self._persist(candidates)
        return candidates

    def list_candidates(self, status: str | None = "pending") -> list[RefundCandidate]:
        where = "WHERE relationship_type = 'refund'"
        parameters: tuple[str, ...] = ()
        if status is not None:
            where += " AND status = ?"
            parameters = (status,)
        rows = self.store.connection.execute(
            f"""
            SELECT * FROM transaction_relationships {where}
            ORDER BY is_ambiguous DESC, CAST(confidence AS REAL) DESC, created_at
            """,
            parameters,
        ).fetchall()
        return [self._from_row(row) for row in rows]

    def get_candidate(self, relationship_id: str) -> RefundCandidate:
        return self._get(relationship_id)

    def confirm_preferred_refunds(self, actor: str) -> dict[str, int]:
        """Assign refunds deterministically and retain ambiguous/partial assignments as warnings."""

        groups: dict[str, list[RefundCandidate]] = {}
        for candidate in self.list_candidates("pending"):
            groups.setdefault(candidate.refund_canonical_id, []).append(candidate)

        ordered_groups = sorted(
            groups.values(),
            key=lambda items: (
                not any("amount_full" in item.evidence for item in items),
                self._transaction_order(items[0].refund_canonical_id),
            ),
        )
        confirmed = 0
        warnings = 0
        for candidates in ordered_groups:
            full = [item for item in candidates if "amount_full" in item.evidence]
            ranked = sorted(full or candidates, key=self._refund_rank)
            selected = next((item for item in ranked if self._has_refund_capacity(item)), None)
            if selected is None:
                continue
            self.confirm(selected.relationship_id, actor)
            confirmed += 1
            if selected.is_ambiguous or "amount_partial" in selected.evidence:
                warnings += 1
        return {"confirmed": confirmed, "warnings": warnings}

    def acknowledge_warning(self, relationship_id: str, actor: str) -> RefundReviewEvent:
        """Accept an automatic ambiguous/partial assignment without changing its accounting."""

        candidate = self._get(relationship_id)
        if candidate.status != "confirmed" or not self._is_warning(candidate):
            raise ValueError("refund relationship is not an active warning")
        now = datetime.now()
        evidence = (*candidate.evidence, WARNING_ACKNOWLEDGED)
        event = RefundReviewEvent(
            event_id=str(uuid.uuid4()),
            relationship_id=relationship_id,
            action="warning_acknowledged",
            before={"status": "warning", "evidence": list(candidate.evidence)},
            after={"status": "confirmed", "evidence": list(evidence)},
            actor=actor,
            created_at=now,
        )
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE transaction_relationships SET evidence_json = ?, reviewed_at = ?, "
                "reviewed_by = ? WHERE relationship_id = ? AND status = 'confirmed'",
                (json.dumps(evidence, ensure_ascii=False), now.isoformat(), actor, relationship_id),
            )
            self._insert_event(connection, event)
        return event

    def escalate_warning(self, relationship_id: str, actor: str) -> RefundReviewEvent:
        """Undo an automatic warning decision and restore all choices for required review."""

        candidate = self._get(relationship_id)
        if candidate.status != "confirmed" or not self._is_warning(candidate):
            raise ValueError("refund relationship is not an active warning")
        now = datetime.now()
        event = RefundReviewEvent(
            event_id=str(uuid.uuid4()),
            relationship_id=relationship_id,
            action="warning_escalated",
            before={"status": "warning", "selected_relationship_id": relationship_id},
            after={"status": "pending", "requires_manual_review": True},
            actor=actor,
            created_at=now,
        )
        with self.store.transaction() as connection:
            connection.execute(
                """
                UPDATE transaction_relationships
                SET status = 'pending', reviewed_at = NULL, reviewed_by = NULL
                WHERE relationship_type = 'refund' AND from_canonical_id = ?
                  AND status IN ('confirmed', 'superseded')
                """,
                (candidate.refund_canonical_id,),
            )
            connection.execute(
                "UPDATE canonical_transactions SET review_status = 'pending' WHERE canonical_id = ?",
                (candidate.refund_canonical_id,),
            )
            self._insert_event(connection, event)
        return event

    def resolve_warnings(
        self, relationship_ids: list[str], decision: str, actor: str
    ) -> list[RefundReviewEvent]:
        """Resolve a user-selected warning batch as accepted or escalated."""

        if decision not in {"acknowledge", "escalate", "restore"}:
            raise ValueError("decision must be acknowledge, escalate, or restore")
        if not relationship_ids:
            raise ValueError("relationship_ids must not be empty")
        if len(set(relationship_ids)) != len(relationship_ids):
            raise ValueError("relationship_ids must not contain duplicates")
        operation = {
            "acknowledge": self.acknowledge_warning,
            "escalate": self.escalate_warning,
            "restore": self.restore_warning,
        }[decision]
        return [operation(relationship_id, actor) for relationship_id in relationship_ids]

    def restore_warning(self, relationship_id: str, actor: str) -> RefundReviewEvent:
        """Undo acknowledgement and return a resolved warning to the active warning queue."""

        candidate = self._get(relationship_id)
        if candidate.status != "confirmed" or WARNING_ACKNOWLEDGED not in candidate.evidence:
            raise ValueError("refund relationship is not an acknowledged warning")
        now = datetime.now()
        evidence = tuple(item for item in candidate.evidence if item != WARNING_ACKNOWLEDGED)
        event = RefundReviewEvent(
            event_id=str(uuid.uuid4()),
            relationship_id=relationship_id,
            action="warning_restored",
            before={"status": "acknowledged", "evidence": list(candidate.evidence)},
            after={"status": "warning", "evidence": list(evidence)},
            actor=actor,
            created_at=now,
        )
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE transaction_relationships SET evidence_json = ?, reviewed_at = ?, "
                "reviewed_by = ? WHERE relationship_id = ? AND status = 'confirmed'",
                (json.dumps(evidence, ensure_ascii=False), now.isoformat(), actor, relationship_id),
            )
            self._insert_event(connection, event)
        return event

    @staticmethod
    def _is_warning(candidate: RefundCandidate) -> bool:
        return WARNING_ACKNOWLEDGED not in candidate.evidence and (
            candidate.is_ambiguous or "amount_partial" in candidate.evidence
        )

    def _refund_rank(self, candidate: RefundCandidate) -> tuple[Any, ...]:
        refund = self.store.get_canonical(candidate.refund_canonical_id)
        original = self.store.get_canonical(candidate.original_canonical_id)
        if refund is None or original is None:
            raise KeyError(candidate.relationship_id)
        return (
            not _orders_match(refund, original),
            (refund.booking_date - original.booking_date).days,
            original.transaction_time
            or datetime.combine(original.booking_date, datetime.min.time()),
            original.canonical_id,
        )

    def _transaction_order(self, canonical_id: str) -> tuple[Any, ...]:
        transaction = self.store.get_canonical(canonical_id)
        if transaction is None:
            raise KeyError(canonical_id)
        return (
            transaction.transaction_time
            or datetime.combine(transaction.booking_date, datetime.min.time()),
            transaction.canonical_id,
        )

    def _has_refund_capacity(self, candidate: RefundCandidate) -> bool:
        original = self.store.get_canonical(candidate.original_canonical_id)
        if original is None:
            return False
        rows = self.store.connection.execute(
            """
            SELECT amount FROM transaction_relationships
            WHERE relationship_type = 'refund' AND to_canonical_id = ?
              AND status = 'confirmed'
            """,
            (original.canonical_id,),
        ).fetchall()
        allocated = sum((Decimal(row["amount"]) for row in rows), Decimal("0"))
        return allocated + candidate.amount <= abs(original.amount)

    def confirm(self, relationship_id: str, actor: str) -> RefundReviewEvent:
        candidate = self._get(relationship_id)
        if candidate.status != "pending":
            raise ValueError("refund candidate has already been decided")
        original = self.store.get_canonical(candidate.original_canonical_id)
        refund = self.store.get_canonical(candidate.refund_canonical_id)
        if original is None or refund is None:
            raise KeyError(relationship_id)
        now = datetime.now()
        with self.store.transaction() as connection:
            already_linked = connection.execute(
                """
                SELECT 1 FROM transaction_relationships
                WHERE relationship_type = 'refund' AND from_canonical_id = ?
                  AND status = 'confirmed'
                """,
                (refund.canonical_id,),
            ).fetchone()
            if already_linked:
                raise ValueError("refund transaction is already linked")
            allocated = connection.execute(
                """
                SELECT amount FROM transaction_relationships
                WHERE relationship_type = 'refund' AND to_canonical_id = ?
                  AND status = 'confirmed'
                """,
                (original.canonical_id,),
            ).fetchall()
            allocated_amount = sum((Decimal(row["amount"]) for row in allocated), Decimal("0"))
            if allocated_amount + candidate.amount > abs(original.amount):
                raise ValueError("confirmed refunds would exceed the original expense")
            connection.execute(
                """
                UPDATE transaction_relationships
                SET status = 'confirmed', reviewed_at = ?, reviewed_by = ?
                WHERE relationship_id = ? AND status = 'pending'
                """,
                (now.isoformat(), actor, relationship_id),
            )
            superseded_rows = connection.execute(
                """
                SELECT * FROM transaction_relationships
                WHERE relationship_type = 'refund' AND from_canonical_id = ?
                  AND relationship_id != ? AND status = 'pending'
                """,
                (refund.canonical_id, relationship_id),
            ).fetchall()
            connection.execute(
                """
                UPDATE transaction_relationships
                SET status = 'superseded', reviewed_at = ?, reviewed_by = ?
                WHERE relationship_type = 'refund' AND from_canonical_id = ?
                  AND relationship_id != ? AND status = 'pending'
                """,
                (now.isoformat(), actor, refund.canonical_id, relationship_id),
            )
            connection.execute(
                """
                UPDATE canonical_transactions
                SET tx_type = ?, review_status = 'confirmed'
                WHERE canonical_id = ?
                """,
                (TransactionType.REFUND.value, refund.canonical_id),
            )
            event = self._event(candidate, "confirmed", actor, now)
            self._insert_event(connection, event)
            for row in superseded_rows:
                superseded = self._event(self._from_row(row), "superseded", actor, now)
                self._insert_event(connection, superseded)
        return event

    def reject(self, relationship_id: str, actor: str) -> RefundReviewEvent:
        candidate = self._get(relationship_id)
        if candidate.status != "pending":
            raise ValueError("refund candidate has already been decided")
        now = datetime.now()
        event = self._event(candidate, "rejected", actor, now)
        with self.store.transaction() as connection:
            connection.execute(
                """
                UPDATE transaction_relationships
                SET status = 'rejected', reviewed_at = ?, reviewed_by = ?
                WHERE relationship_id = ? AND status = 'pending'
                """,
                (now.isoformat(), actor, relationship_id),
            )
            self._insert_event(connection, event)
        return event

    def exclude_refund(
        self, relationship_id: str, actor: str, reason: str
    ) -> list[RefundReviewEvent]:
        """Reject every pending relationship and soft-delete the reviewed refund transaction."""

        candidate = self._get(relationship_id)
        related = [
            item
            for item in self.list_candidates("pending")
            if item.refund_canonical_id == candidate.refund_canonical_id
        ]
        if not related:
            raise ValueError("refund candidate has already been decided")
        events = [self.reject(item.relationship_id, actor) for item in related]
        self.store.soft_delete_canonical(candidate.refund_canonical_id, actor, reason)
        return events

    def list_events(self, relationship_id: str) -> list[RefundReviewEvent]:
        rows = self.store.connection.execute(
            """
            SELECT * FROM transaction_relationship_events
            WHERE relationship_id = ? ORDER BY created_at, event_id
            """,
            (relationship_id,),
        ).fetchall()
        return [
            RefundReviewEvent(
                event_id=row["event_id"],
                relationship_id=row["relationship_id"],
                action=row["action"],
                before=json.loads(row["before_json"]),
                after=json.loads(row["after_json"]),
                actor=row["actor"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    def _candidate(
        self, refund: CanonicalTransaction, original: CanonicalTransaction
    ) -> RefundCandidate | None:
        if refund.booking_date < original.booking_date:
            return None
        if refund.booking_date - original.booking_date > self.match_window:
            return None
        amount = abs(refund.amount)
        if amount > abs(original.amount):
            return None
        if not _merchant_matches(refund.merchant, original.merchant):
            return None
        full = amount == abs(original.amount)
        evidence = (
            "refund_marker",
            "merchant_match",
            "amount_full" if full else "amount_partial",
            "within_refund_window",
        )
        return RefundCandidate(
            relationship_id=str(uuid.uuid4()),
            refund_canonical_id=refund.canonical_id,
            original_canonical_id=original.canonical_id,
            amount=amount,
            confidence=Decimal("0.90") if full else Decimal("0.75"),
            evidence=evidence,
            created_at=datetime.now(),
        )

    @staticmethod
    def _is_refund(transaction: CanonicalTransaction) -> bool:
        if transaction.amount <= 0:
            return False
        if transaction.tx_type == TransactionType.REFUND:
            return True
        text = " ".join((transaction.merchant, transaction.status, transaction.notes)).lower()
        return any(marker in text for marker in REFUND_MARKERS)

    def _persist(self, candidates: list[RefundCandidate]) -> None:
        with self.store.transaction() as connection:
            for item in candidates:
                connection.execute(
                    """
                    INSERT INTO transaction_relationships(
                        relationship_id, relationship_type, from_canonical_id,
                        to_canonical_id, amount, confidence, evidence_json,
                        status, is_ambiguous, created_at, reviewed_at, reviewed_by
                    ) VALUES (?, 'refund', ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                    ON CONFLICT(relationship_type, from_canonical_id, to_canonical_id)
                    DO UPDATE SET confidence = excluded.confidence,
                                  evidence_json = excluded.evidence_json,
                                  is_ambiguous = excluded.is_ambiguous
                    """,
                    (
                        item.relationship_id,
                        item.refund_canonical_id,
                        item.original_canonical_id,
                        str(item.amount),
                        str(item.confidence),
                        json.dumps(item.evidence, ensure_ascii=False),
                        item.status,
                        int(item.is_ambiguous),
                        item.created_at.isoformat(),
                    ),
                )

    def _get(self, relationship_id: str) -> RefundCandidate:
        row = self.store.connection.execute(
            "SELECT * FROM transaction_relationships WHERE relationship_id = ?",
            (relationship_id,),
        ).fetchone()
        if row is None:
            raise KeyError(relationship_id)
        return self._from_row(row)

    @staticmethod
    def _from_row(row: sqlite3.Row) -> RefundCandidate:
        return RefundCandidate(
            relationship_id=row["relationship_id"],
            refund_canonical_id=row["from_canonical_id"],
            original_canonical_id=row["to_canonical_id"],
            amount=Decimal(row["amount"]),
            confidence=Decimal(row["confidence"]),
            evidence=tuple(json.loads(row["evidence_json"])),
            status=row["status"],
            is_ambiguous=bool(row["is_ambiguous"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    @staticmethod
    def _event(
        candidate: RefundCandidate, action: str, actor: str, now: datetime
    ) -> RefundReviewEvent:
        return RefundReviewEvent(
            event_id=str(uuid.uuid4()),
            relationship_id=candidate.relationship_id,
            action=action,
            before={"status": candidate.status},
            after={"status": action},
            actor=actor,
            created_at=now,
        )

    @staticmethod
    def _insert_event(connection: Any, event: RefundReviewEvent) -> None:
        connection.execute(
            """
            INSERT INTO transaction_relationship_events(
                event_id, relationship_id, action, before_json, after_json, actor, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.relationship_id,
                event.action,
                json.dumps(event.before, ensure_ascii=False, sort_keys=True),
                json.dumps(event.after, ensure_ascii=False, sort_keys=True),
                event.actor,
                event.created_at.isoformat(),
            ),
        )


def _merchant_matches(left: str, right: str) -> bool:
    def clean(value: str) -> str:
        return re.sub(r"退款|退回|退还|有限公司|有限责任公司|[\W_]", "", value.lower())

    left_clean = clean(left)
    right_clean = clean(right)
    if len(left_clean) < 2 or len(right_clean) < 2:
        return False
    return left_clean in right_clean or right_clean in left_clean


def _orders_match(refund: CanonicalTransaction, original: CanonicalTransaction) -> bool:
    refund_orders = {
        link.raw_transaction.merchant_order_id
        for link in refund.source_links
        if link.raw_transaction.merchant_order_id
    }
    original_orders = {
        link.raw_transaction.merchant_order_id
        for link in original.source_links
        if link.raw_transaction.merchant_order_id
    }
    if refund_orders & original_orders:
        return True
    refund_ids = {
        link.raw_transaction.transaction_id
        for link in refund.source_links
        if link.raw_transaction.transaction_id
    }
    original_ids = {
        link.raw_transaction.transaction_id
        for link in original.source_links
        if link.raw_transaction.transaction_id
    }
    return any(
        refund_id == original_id or refund_id.startswith(f"{original_id}_")
        for refund_id in refund_ids
        for original_id in original_ids
    )
