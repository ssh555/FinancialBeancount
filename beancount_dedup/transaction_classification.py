"""Review-first classification of transfers and other non-consumption transactions."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import sqlite3

from .ledger_models import CanonicalTransaction
from .ledger_store import LedgerStore
from .models import TransactionType

CLASSIFIER_VERSION = "non-consumption-v1"

CLASSIFICATION_RULES = (
    (
        TransactionType.PREAUTHORIZATION,
        "酒店预授权",
        ("预授权撤销", "预授权完成", "预授权"),
        Decimal("0.95"),
    ),
    (
        TransactionType.INVESTMENT,
        "理财资产转移",
        ("朝朝宝转入", "朝朝宝转出", "基金申购", "基金赎回", "理财申购", "理财赎回"),
        Decimal("0.92"),
    ),
    (
        TransactionType.TRANSFER,
        "信用卡还款",
        ("信用卡还款", "信用卡自动还款"),
        Decimal("0.95"),
    ),
    (
        TransactionType.TRANSFER,
        "账户内部转移",
        (
            "零钱充值",
            "零钱提现",
            "余额充值",
            "余额提现",
            "充值到余额",
            "提现到银行卡",
            "转到余额宝",
            "转出到银行卡",
            "本人转账",
        ),
        Decimal("0.88"),
    ),
)


@dataclass(frozen=True)
class ClassificationCandidate:
    candidate_id: str
    canonical_id: str
    proposed_type: TransactionType
    proposed_category: str
    confidence: Decimal
    evidence: tuple[str, ...]
    classifier_version: str = CLASSIFIER_VERSION
    status: str = "pending"
    created_at: datetime = field(default_factory=datetime.now)


@dataclass(frozen=True)
class ClassificationEvent:
    event_id: str
    candidate_id: str
    action: str
    before: dict[str, Any]
    after: dict[str, Any]
    actor: str
    created_at: datetime


class TransactionClassificationService:
    """Generate explicit, human-reviewed non-consumption classifications."""

    def __init__(self, store: LedgerStore):
        self.store = store

    def generate_candidates(self) -> list[ClassificationCandidate]:
        candidates = []
        for transaction in self.store.list_canonical():
            candidate = self._classify(transaction)
            if candidate:
                candidates.append(candidate)
        self._persist(candidates)
        return candidates

    def list_candidates(self, status: str | None = "pending") -> list[ClassificationCandidate]:
        where = ""
        parameters: tuple[str, ...] = ()
        if status is not None:
            where = "WHERE status = ?"
            parameters = (status,)
        rows = self.store.connection.execute(
            f"""
            SELECT * FROM classification_candidates {where}
            ORDER BY CAST(confidence AS REAL) DESC, created_at, candidate_id
            """,
            parameters,
        ).fetchall()
        return [self._from_row(row) for row in rows]

    def get_candidate(self, candidate_id: str) -> ClassificationCandidate:
        row = self.store.connection.execute(
            "SELECT * FROM classification_candidates WHERE candidate_id = ?", (candidate_id,)
        ).fetchone()
        if row is None:
            raise KeyError(candidate_id)
        return self._from_row(row)

    def confirm(self, candidate_id: str, actor: str) -> ClassificationEvent:
        candidate = self.get_candidate(candidate_id)
        if candidate.status != "pending":
            raise ValueError("classification candidate has already been decided")
        transaction = self.store.get_canonical(candidate.canonical_id)
        if transaction is None:
            raise KeyError(candidate.canonical_id)
        before = transaction.to_dict()
        now = datetime.now()
        with self.store.transaction() as connection:
            connection.execute(
                """
                UPDATE canonical_transactions
                SET tx_type = ?, category = ?, review_status = 'confirmed'
                WHERE canonical_id = ?
                """,
                (
                    candidate.proposed_type.value,
                    candidate.proposed_category,
                    candidate.canonical_id,
                ),
            )
            connection.execute(
                """
                UPDATE classification_candidates
                SET status = 'confirmed', reviewed_at = ?, reviewed_by = ?
                WHERE candidate_id = ? AND status = 'pending'
                """,
                (now.isoformat(), actor, candidate_id),
            )
            updated = self.store.get_canonical(candidate.canonical_id)
            if updated is None:
                raise RuntimeError("classified transaction is missing")
            event = ClassificationEvent(
                event_id=str(uuid.uuid4()),
                candidate_id=candidate_id,
                action="confirmed",
                before=before,
                after=updated.to_dict(),
                actor=actor,
                created_at=now,
            )
            self._insert_event(connection, event)
        return event

    def reject(self, candidate_id: str, actor: str) -> ClassificationEvent:
        candidate = self.get_candidate(candidate_id)
        if candidate.status != "pending":
            raise ValueError("classification candidate has already been decided")
        transaction = self.store.get_canonical(candidate.canonical_id)
        if transaction is None:
            raise KeyError(candidate.canonical_id)
        now = datetime.now()
        snapshot = transaction.to_dict()
        event = ClassificationEvent(
            event_id=str(uuid.uuid4()),
            candidate_id=candidate_id,
            action="rejected",
            before=snapshot,
            after=snapshot,
            actor=actor,
            created_at=now,
        )
        with self.store.transaction() as connection:
            connection.execute(
                """
                UPDATE classification_candidates
                SET status = 'rejected', reviewed_at = ?, reviewed_by = ?
                WHERE candidate_id = ? AND status = 'pending'
                """,
                (now.isoformat(), actor, candidate_id),
            )
            self._insert_event(connection, event)
        return event

    def list_events(self, candidate_id: str) -> list[ClassificationEvent]:
        rows = self.store.connection.execute(
            """
            SELECT * FROM classification_events
            WHERE candidate_id = ? ORDER BY created_at, event_id
            """,
            (candidate_id,),
        ).fetchall()
        return [
            ClassificationEvent(
                event_id=row["event_id"],
                candidate_id=row["candidate_id"],
                action=row["action"],
                before=json.loads(row["before_json"]),
                after=json.loads(row["after_json"]),
                actor=row["actor"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    @staticmethod
    def _classify(transaction: CanonicalTransaction) -> ClassificationCandidate | None:
        if transaction.tx_type not in {
            TransactionType.EXPENSE,
            TransactionType.INCOME,
            TransactionType.UNKNOWN,
        }:
            return None
        text = " ".join(
            (
                transaction.merchant,
                transaction.normalized_merchant,
                transaction.status,
                transaction.notes,
            )
        ).lower()
        for proposed_type, category, keywords, confidence in CLASSIFICATION_RULES:
            matched = next((keyword for keyword in keywords if keyword.lower() in text), None)
            if matched:
                return ClassificationCandidate(
                    candidate_id=str(uuid.uuid4()),
                    canonical_id=transaction.canonical_id,
                    proposed_type=proposed_type,
                    proposed_category=category,
                    confidence=confidence,
                    evidence=(f"keyword:{matched}",),
                )
        return None

    def _persist(self, candidates: list[ClassificationCandidate]) -> None:
        with self.store.transaction() as connection:
            for item in candidates:
                connection.execute(
                    """
                    INSERT INTO classification_candidates(
                        candidate_id, canonical_id, proposed_type, proposed_category,
                        confidence, evidence_json, classifier_version, status,
                        created_at, reviewed_at, reviewed_by
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                    ON CONFLICT(canonical_id, proposed_type, proposed_category, classifier_version)
                    DO UPDATE SET confidence = excluded.confidence,
                                  evidence_json = excluded.evidence_json
                    """,
                    (
                        item.candidate_id,
                        item.canonical_id,
                        item.proposed_type.value,
                        item.proposed_category,
                        str(item.confidence),
                        json.dumps(item.evidence, ensure_ascii=False),
                        item.classifier_version,
                        item.status,
                        item.created_at.isoformat(),
                    ),
                )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> ClassificationCandidate:
        return ClassificationCandidate(
            candidate_id=row["candidate_id"],
            canonical_id=row["canonical_id"],
            proposed_type=TransactionType(row["proposed_type"]),
            proposed_category=row["proposed_category"],
            confidence=Decimal(row["confidence"]),
            evidence=tuple(json.loads(row["evidence_json"])),
            classifier_version=row["classifier_version"],
            status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    @staticmethod
    def _insert_event(connection: Any, event: ClassificationEvent) -> None:
        connection.execute(
            """
            INSERT INTO classification_events(
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
