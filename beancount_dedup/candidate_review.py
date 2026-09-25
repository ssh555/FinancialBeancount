"""Human review workflow for cross-platform duplicate candidates."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from .canonical_matcher import ConservativeMatcher, MatchCandidate
from .ledger_models import CanonicalTransaction, RawTransaction, ReviewStatus
from .ledger_store import LedgerStore
from .models import TransactionType, source_id_value


@dataclass(frozen=True)
class CandidateReviewGroup:
    """One candidate with both observations and every competing candidate."""

    candidate: MatchCandidate
    payment: RawTransaction
    bank: RawTransaction
    conflicts: tuple[MatchCandidate, ...]


@dataclass(frozen=True)
class CandidateReviewEvent:
    event_id: str
    candidate_id: str
    action: str
    before: dict[str, Any]
    after: dict[str, Any]
    actor: str
    created_at: datetime


class CandidateReviewService:
    """Resolve duplicate candidates without ever deleting source observations."""

    def __init__(self, store: LedgerStore):
        self.store = store

    def list_groups(self, status: str | None = "pending") -> list[CandidateReviewGroup]:
        candidates = ConservativeMatcher(self.store).list_candidates(status)
        all_candidates = ConservativeMatcher(self.store).list_candidates(None)
        return [self._group(candidate, all_candidates) for candidate in candidates]

    def get_group(self, candidate_id: str) -> CandidateReviewGroup:
        candidates = ConservativeMatcher(self.store).list_candidates(None)
        candidate = next((item for item in candidates if item.candidate_id == candidate_id), None)
        if candidate is None:
            raise KeyError(candidate_id)
        return self._group(candidate, candidates)

    def reject(self, candidate_id: str, actor: str) -> CandidateReviewEvent:
        """Reject one proposed match while retaining both raw observations."""

        group = self.get_group(candidate_id)
        if group.candidate.status != "pending":
            raise ValueError("candidate has already been decided")
        now = datetime.now()
        before = self._snapshot(group)
        after = {**before, "candidate_status": "rejected"}
        event = CandidateReviewEvent(
            event_id=str(uuid.uuid4()),
            candidate_id=candidate_id,
            action="rejected",
            before=before,
            after=after,
            actor=actor,
            created_at=now,
        )
        with self.store.transaction() as connection:
            updated = connection.execute(
                """
                UPDATE match_candidates
                SET status = 'rejected', reviewed_at = ?, reviewed_by = ?
                WHERE candidate_id = ? AND status = 'pending'
                """,
                (now.isoformat(), actor, candidate_id),
            )
            if updated.rowcount != 1:
                raise ValueError("candidate has already been decided")
            self._insert_event(connection, event)
        return event

    def confirm(
        self,
        candidate_id: str,
        actor: str,
        changes: dict[str, Any] | None = None,
    ) -> tuple[CanonicalTransaction, CandidateReviewEvent]:
        """Create one reviewed economic transaction linked to both observations."""

        group = self.get_group(candidate_id)
        if group.candidate.status != "pending":
            raise ValueError("candidate has already been decided")
        canonical = self._build_canonical(group, changes or {})
        reasons = tuple(item.code for item in group.candidate.evidence)
        for raw in (group.payment, group.bank):
            canonical.add_source(
                raw,
                confidence=group.candidate.confidence,
                reasons=reasons,
                matcher_version=group.candidate.matcher_version,
                linked_by=actor,
            )

        now = datetime.now()
        before = self._snapshot(group)
        action = "modified_confirmed" if changes else "confirmed"
        after = {
            **before,
            "candidate_status": "confirmed",
            "canonical": canonical.to_dict(),
            "changes": changes or {},
        }
        event = CandidateReviewEvent(
            event_id=str(uuid.uuid4()),
            candidate_id=candidate_id,
            action=action,
            before=before,
            after=after,
            actor=actor,
            created_at=now,
        )

        with self.store.transaction() as connection:
            linked = connection.execute(
                """
                SELECT raw_id FROM source_record_links
                WHERE raw_id IN (?, ?)
                """,
                (group.payment.raw_id, group.bank.raw_id),
            ).fetchall()
            if linked:
                raise ValueError("candidate contains an observation that is already linked")
            updated = connection.execute(
                """
                UPDATE match_candidates
                SET status = 'confirmed', reviewed_at = ?, reviewed_by = ?
                WHERE candidate_id = ? AND status = 'pending'
                """,
                (now.isoformat(), actor, candidate_id),
            )
            if updated.rowcount != 1:
                raise ValueError("candidate has already been decided")
            self.store._insert_canonical(connection, canonical)
            self._insert_event(connection, event)
            self._supersede_conflicts(connection, group, actor, now, canonical.canonical_id)
        return canonical, event

    def list_events(self, candidate_id: str) -> list[CandidateReviewEvent]:
        rows = self.store.connection.execute(
            """
            SELECT * FROM match_candidate_events
            WHERE candidate_id = ? ORDER BY created_at, event_id
            """,
            (candidate_id,),
        ).fetchall()
        return [self._event_from_row(row) for row in rows]

    def _group(
        self, candidate: MatchCandidate, all_candidates: list[MatchCandidate]
    ) -> CandidateReviewGroup:
        payment = self.store.get_raw(candidate.payment_raw_id)
        bank = self.store.get_raw(candidate.bank_raw_id)
        if payment is None or bank is None:
            raise RuntimeError(f"candidate source record is missing: {candidate.candidate_id}")
        conflicts = tuple(
            item
            for item in all_candidates
            if item.candidate_id != candidate.candidate_id
            and (
                item.payment_raw_id == candidate.payment_raw_id
                or item.bank_raw_id == candidate.bank_raw_id
            )
        )
        return CandidateReviewGroup(candidate, payment, bank, conflicts)

    @staticmethod
    def _build_canonical(
        group: CandidateReviewGroup, changes: dict[str, Any]
    ) -> CanonicalTransaction:
        allowed = {
            "transaction_time",
            "booking_date",
            "amount",
            "direction",
            "merchant",
            "normalized_merchant",
            "category",
            "payment_channel",
            "funding_account",
            "tx_type",
            "status",
            "notes",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"canonical fields are not editable: {sorted(unknown)}")
        payment = group.payment
        if payment.booking_date is None:
            raise ValueError("candidate payment has no booking date")
        values: dict[str, Any] = {
            "transaction_time": payment.transaction_time,
            "booking_date": payment.booking_date,
            "amount": payment.amount,
            "direction": payment.direction,
            "merchant": payment.merchant or payment.counterparty,
            "payment_channel": source_id_value(payment.source),
            "funding_account": group.bank.source_account,
            "status": payment.status,
            "review_status": ReviewStatus.CONFIRMED,
        }
        values.update(changes)
        if isinstance(values.get("transaction_time"), str):
            values["transaction_time"] = datetime.fromisoformat(values["transaction_time"])
        if isinstance(values.get("booking_date"), str):
            values["booking_date"] = date.fromisoformat(values["booking_date"])
        if "amount" in values:
            values["amount"] = Decimal(str(values["amount"]))
        if isinstance(values.get("tx_type"), str):
            values["tx_type"] = TransactionType(values["tx_type"])
        return CanonicalTransaction(**values)

    @staticmethod
    def _snapshot(group: CandidateReviewGroup) -> dict[str, Any]:
        return {
            "candidate_status": group.candidate.status,
            "candidate": {
                "candidate_id": group.candidate.candidate_id,
                "confidence": str(group.candidate.confidence),
                "is_ambiguous": group.candidate.is_ambiguous,
                "evidence": [item.to_dict() for item in group.candidate.evidence],
            },
            "payment": group.payment.to_dict(),
            "bank": group.bank.to_dict(),
            "conflict_candidate_ids": [item.candidate_id for item in group.conflicts],
        }

    def _supersede_conflicts(
        self,
        connection: Any,
        group: CandidateReviewGroup,
        actor: str,
        now: datetime,
        canonical_id: str,
    ) -> None:
        for conflict in group.conflicts:
            updated = connection.execute(
                """
                UPDATE match_candidates
                SET status = 'superseded', reviewed_at = ?, reviewed_by = ?
                WHERE candidate_id = ? AND status = 'pending'
                """,
                (now.isoformat(), actor, conflict.candidate_id),
            )
            if updated.rowcount != 1:
                continue
            event = CandidateReviewEvent(
                event_id=str(uuid.uuid4()),
                candidate_id=conflict.candidate_id,
                action="superseded",
                before={"candidate_status": "pending"},
                after={
                    "candidate_status": "superseded",
                    "selected_candidate_id": group.candidate.candidate_id,
                    "canonical_id": canonical_id,
                },
                actor=actor,
                created_at=now,
            )
            self._insert_event(connection, event)

    @staticmethod
    def _insert_event(connection: Any, event: CandidateReviewEvent) -> None:
        connection.execute(
            """
            INSERT INTO match_candidate_events(
                event_id, candidate_id, action, before_json, after_json, actor, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.candidate_id,
                event.action,
                json.dumps(event.before, ensure_ascii=False, sort_keys=True, default=str),
                json.dumps(event.after, ensure_ascii=False, sort_keys=True, default=str),
                event.actor,
                event.created_at.isoformat(),
            ),
        )

    @staticmethod
    def _event_from_row(row: Any) -> CandidateReviewEvent:
        return CandidateReviewEvent(
            event_id=row["event_id"],
            candidate_id=row["candidate_id"],
            action=row["action"],
            before=json.loads(row["before_json"]),
            after=json.loads(row["after_json"]),
            actor=row["actor"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
