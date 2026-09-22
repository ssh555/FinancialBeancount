"""SQLite persistence for the auditable raw-to-canonical ledger."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

from .ledger_models import (
    CanonicalTransaction,
    RawTransaction,
    ReviewStatus,
    SourceRecordLink,
)
from .models import Platform, TransactionType

SCHEMA_VERSION = 9


@dataclass(frozen=True)
class ImportBatch:
    """One source file import attempt, identified by its content hash."""

    batch_id: str
    source: Platform
    source_file: str
    source_file_hash: str
    imported_at: datetime


@dataclass(frozen=True)
class RawImportResult:
    """Result of idempotently storing one raw observation."""

    raw_transaction: RawTransaction
    created: bool
    imported_observation: RawTransaction
    import_run_id: str | None = None


@dataclass(frozen=True)
class ImportOccurrence:
    """Evidence that one source observation appeared in a specific import file."""

    occurrence_id: str
    import_run_id: str
    batch_id: str
    raw_id: str
    created: bool
    observed: dict[str, object]
    recorded_at: datetime


@dataclass(frozen=True)
class ImportCoverageReport:
    """Completeness comparison for one concrete import attempt."""

    batch_id: str
    import_run_id: str
    occurrence_count: int
    unique_observation_count: int
    created_count: int
    existing_count: int
    duplicate_occurrence_count: int
    missing_raw_ids: tuple[str, ...]


class LedgerStore:
    """Persistent store used by importers, matching, review, and mobile APIs."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self._initialize_schema()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> LedgerStore:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Commit a complete import/link operation or roll it back atomically."""

        try:
            yield self.connection
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def _initialize_schema(self) -> None:
        with self.transaction() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS import_batches (
                    batch_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    source_file TEXT NOT NULL,
                    source_file_hash TEXT NOT NULL UNIQUE,
                    imported_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS raw_transactions (
                    raw_id TEXT PRIMARY KEY,
                    deduplication_key TEXT NOT NULL UNIQUE,
                    source TEXT NOT NULL,
                    source_account TEXT NOT NULL,
                    transaction_time TEXT,
                    booking_date TEXT,
                    amount TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    merchant TEXT NOT NULL,
                    counterparty TEXT NOT NULL,
                    description TEXT NOT NULL,
                    payment_method TEXT NOT NULL,
                    bank_card_suffix TEXT,
                    transaction_id TEXT,
                    merchant_order_id TEXT,
                    status TEXT NOT NULL,
                    balance TEXT,
                    currency TEXT NOT NULL,
                    import_batch_id TEXT,
                    source_file TEXT NOT NULL,
                    source_file_hash TEXT NOT NULL,
                    raw_row_number INTEGER,
                    original_row_json TEXT NOT NULL,
                    FOREIGN KEY (import_batch_id) REFERENCES import_batches(batch_id)
                );

                CREATE TABLE IF NOT EXISTS import_occurrences (
                    occurrence_id TEXT PRIMARY KEY,
                    import_run_id TEXT NOT NULL,
                    batch_id TEXT NOT NULL,
                    raw_id TEXT NOT NULL,
                    was_created INTEGER NOT NULL,
                    observed_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    FOREIGN KEY (batch_id) REFERENCES import_batches(batch_id) ON DELETE CASCADE,
                    FOREIGN KEY (raw_id) REFERENCES raw_transactions(raw_id) ON DELETE RESTRICT
                );

                CREATE INDEX IF NOT EXISTS idx_import_occurrences_batch
                    ON import_occurrences(batch_id, import_run_id, raw_id);

                CREATE TABLE IF NOT EXISTS canonical_transactions (
                    canonical_id TEXT PRIMARY KEY,
                    transaction_time TEXT,
                    booking_date TEXT NOT NULL,
                    amount TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    merchant TEXT NOT NULL,
                    normalized_merchant TEXT NOT NULL,
                    category TEXT NOT NULL,
                    payment_channel TEXT NOT NULL,
                    funding_account TEXT NOT NULL,
                    tx_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    review_status TEXT NOT NULL,
                    notes TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS source_record_links (
                    canonical_id TEXT NOT NULL,
                    raw_id TEXT NOT NULL UNIQUE,
                    confidence TEXT NOT NULL,
                    reasons_json TEXT NOT NULL,
                    matcher_version TEXT NOT NULL,
                    linked_at TEXT NOT NULL,
                    linked_by TEXT NOT NULL,
                    PRIMARY KEY (canonical_id, raw_id),
                    FOREIGN KEY (canonical_id)
                        REFERENCES canonical_transactions(canonical_id) ON DELETE CASCADE,
                    FOREIGN KEY (raw_id)
                        REFERENCES raw_transactions(raw_id) ON DELETE RESTRICT
                );

                CREATE INDEX IF NOT EXISTS idx_raw_source_time
                    ON raw_transactions(source, transaction_time);
                CREATE INDEX IF NOT EXISTS idx_canonical_booking_date
                    ON canonical_transactions(booking_date);
                CREATE INDEX IF NOT EXISTS idx_links_canonical
                    ON source_record_links(canonical_id);

                CREATE TABLE IF NOT EXISTS review_sessions (
                    session_id TEXT PRIMARY KEY,
                    import_batch_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    FOREIGN KEY (import_batch_id) REFERENCES import_batches(batch_id)
                );

                CREATE TABLE IF NOT EXISTS review_items (
                    review_item_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    raw_id TEXT NOT NULL,
                    canonical_id TEXT,
                    item_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    reviewed_at TEXT,
                    reviewed_by TEXT,
                    FOREIGN KEY (session_id) REFERENCES review_sessions(session_id) ON DELETE CASCADE,
                    FOREIGN KEY (raw_id) REFERENCES raw_transactions(raw_id) ON DELETE RESTRICT,
                    FOREIGN KEY (canonical_id)
                        REFERENCES canonical_transactions(canonical_id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS review_events (
                    event_id TEXT PRIMARY KEY,
                    review_item_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    before_json TEXT NOT NULL,
                    after_json TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (review_item_id)
                        REFERENCES review_items(review_item_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_review_items_session
                    ON review_items(session_id, status);
                CREATE INDEX IF NOT EXISTS idx_review_events_item
                    ON review_events(review_item_id, created_at);

                CREATE TABLE IF NOT EXISTS match_candidates (
                    candidate_id TEXT PRIMARY KEY,
                    left_raw_id TEXT NOT NULL,
                    right_raw_id TEXT NOT NULL,
                    confidence TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    matcher_version TEXT NOT NULL,
                    status TEXT NOT NULL,
                    is_ambiguous INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    reviewed_at TEXT,
                    reviewed_by TEXT,
                    UNIQUE(left_raw_id, right_raw_id, matcher_version),
                    FOREIGN KEY (left_raw_id)
                        REFERENCES raw_transactions(raw_id) ON DELETE CASCADE,
                    FOREIGN KEY (right_raw_id)
                        REFERENCES raw_transactions(raw_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_match_candidates_status
                    ON match_candidates(status, is_ambiguous, confidence);

                CREATE TABLE IF NOT EXISTS match_candidate_events (
                    event_id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    before_json TEXT NOT NULL,
                    after_json TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (candidate_id)
                        REFERENCES match_candidates(candidate_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_match_candidate_events_candidate
                    ON match_candidate_events(candidate_id, created_at);

                CREATE TABLE IF NOT EXISTS transaction_relationships (
                    relationship_id TEXT PRIMARY KEY,
                    relationship_type TEXT NOT NULL,
                    from_canonical_id TEXT NOT NULL,
                    to_canonical_id TEXT NOT NULL,
                    amount TEXT NOT NULL,
                    confidence TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    is_ambiguous INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    reviewed_at TEXT,
                    reviewed_by TEXT,
                    UNIQUE(relationship_type, from_canonical_id, to_canonical_id),
                    FOREIGN KEY (from_canonical_id)
                        REFERENCES canonical_transactions(canonical_id) ON DELETE CASCADE,
                    FOREIGN KEY (to_canonical_id)
                        REFERENCES canonical_transactions(canonical_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_transaction_relationships_review
                    ON transaction_relationships(relationship_type, status, is_ambiguous);

                CREATE TABLE IF NOT EXISTS transaction_relationship_events (
                    event_id TEXT PRIMARY KEY,
                    relationship_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    before_json TEXT NOT NULL,
                    after_json TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (relationship_id)
                        REFERENCES transaction_relationships(relationship_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS classification_candidates (
                    candidate_id TEXT PRIMARY KEY,
                    canonical_id TEXT NOT NULL,
                    proposed_type TEXT NOT NULL,
                    proposed_category TEXT NOT NULL,
                    confidence TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    classifier_version TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    reviewed_at TEXT,
                    reviewed_by TEXT,
                    UNIQUE(canonical_id, proposed_type, proposed_category, classifier_version),
                    FOREIGN KEY (canonical_id)
                        REFERENCES canonical_transactions(canonical_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS classification_events (
                    event_id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    before_json TEXT NOT NULL,
                    after_json TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (candidate_id)
                        REFERENCES classification_candidates(candidate_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS canonical_deletions (
                    canonical_id TEXT PRIMARY KEY,
                    actor TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    deleted_at TEXT NOT NULL,
                    FOREIGN KEY (canonical_id)
                        REFERENCES canonical_transactions(canonical_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS canonical_events (
                    event_id TEXT PRIMARY KEY,
                    canonical_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    before_json TEXT NOT NULL,
                    after_json TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (canonical_id)
                        REFERENCES canonical_transactions(canonical_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_canonical_events_transaction
                    ON canonical_events(canonical_id, created_at);
                """
            )
            connection.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    def start_import_batch(
        self, source: Platform, source_file: str, source_file_hash: str
    ) -> tuple[ImportBatch, bool]:
        """Create an import batch, or return the prior batch for the same file."""

        existing = self.connection.execute(
            "SELECT * FROM import_batches WHERE source_file_hash = ?", (source_file_hash,)
        ).fetchone()
        if existing:
            return self._batch_from_row(existing), False

        batch = ImportBatch(
            batch_id=str(uuid.uuid4()),
            source=source,
            source_file=source_file,
            source_file_hash=source_file_hash,
            imported_at=datetime.now(),
        )
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO import_batches(
                    batch_id, source, source_file, source_file_hash, imported_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    batch.batch_id,
                    batch.source.value,
                    batch.source_file,
                    batch.source_file_hash,
                    batch.imported_at.isoformat(),
                ),
            )
        return batch, True

    def list_import_batches_page(
        self, *, limit: int, offset: int
    ) -> tuple[list[dict[str, object]], int]:
        """Return import history with observation and review counts."""

        if limit < 1 or offset < 0:
            raise ValueError("limit must be positive and offset must not be negative")
        total = self.connection.execute("SELECT COUNT(*) FROM import_batches").fetchone()[0]
        rows = self.connection.execute(
            """
            SELECT batches.*,
                   (SELECT COUNT(*) FROM import_occurrences AS occurrences
                    WHERE occurrences.batch_id = batches.batch_id) AS occurrence_count,
                   (SELECT COUNT(DISTINCT raw_id) FROM import_occurrences AS occurrences
                    WHERE occurrences.batch_id = batches.batch_id) AS unique_observation_count,
                   (SELECT COUNT(*) FROM review_sessions AS sessions
                    WHERE sessions.import_batch_id = batches.batch_id) AS review_session_count,
                   (SELECT COUNT(*) FROM review_items AS items
                    JOIN review_sessions AS sessions ON sessions.session_id = items.session_id
                    WHERE sessions.import_batch_id = batches.batch_id
                      AND items.status = 'pending') AS pending_count
            FROM import_batches AS batches
            ORDER BY batches.imported_at DESC, batches.batch_id
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
        return [
            {
                "batch_id": row["batch_id"],
                "source": row["source"],
                "source_file": row["source_file"],
                "source_file_hash": row["source_file_hash"],
                "imported_at": row["imported_at"],
                "occurrence_count": row["occurrence_count"],
                "unique_observation_count": row["unique_observation_count"],
                "review_session_count": row["review_session_count"],
                "pending_count": row["pending_count"] or 0,
            }
            for row in rows
        ], total

    def add_raw(self, raw: RawTransaction) -> RawImportResult:
        """Store a raw observation once, even when the same statement is re-imported."""

        with self.transaction() as connection:
            run_id = str(uuid.uuid4()) if raw.import_batch_id else None
            return self._add_raw(connection, raw, run_id)

    def add_raws(self, raw_transactions: list[RawTransaction]) -> list[RawImportResult]:
        """Atomically store a parsed statement without partial imports."""

        with self.transaction() as connection:
            run_id = (
                str(uuid.uuid4()) if any(raw.import_batch_id for raw in raw_transactions) else None
            )
            return [self._add_raw(connection, raw, run_id) for raw in raw_transactions]

    def _add_raw(
        self, connection: sqlite3.Connection, raw: RawTransaction, import_run_id: str | None
    ) -> RawImportResult:
        existing = connection.execute(
            "SELECT * FROM raw_transactions WHERE deduplication_key = ?",
            (raw.deduplication_key,),
        ).fetchone()
        if existing:
            persisted = self._raw_from_row(existing)
            result = RawImportResult(persisted, False, raw, import_run_id)
            self._record_import_occurrence(connection, result)
            return result

        connection.execute(
            """
            INSERT INTO raw_transactions(
                raw_id, deduplication_key, source, source_account,
                transaction_time, booking_date, amount, direction, merchant,
                counterparty, description, payment_method, bank_card_suffix,
                transaction_id, merchant_order_id, status, balance, currency,
                import_batch_id, source_file, source_file_hash, raw_row_number,
                original_row_json
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                raw.raw_id,
                raw.deduplication_key,
                raw.source.value,
                raw.source_account,
                raw.transaction_time.isoformat() if raw.transaction_time else None,
                raw.booking_date.isoformat() if raw.booking_date else None,
                str(raw.amount),
                raw.direction,
                raw.merchant,
                raw.counterparty,
                raw.description,
                raw.payment_method,
                raw.bank_card_suffix,
                raw.transaction_id,
                raw.merchant_order_id,
                raw.status,
                str(raw.balance) if raw.balance is not None else None,
                raw.currency,
                raw.import_batch_id,
                raw.source_file,
                raw.source_file_hash,
                raw.raw_row_number,
                json.dumps(raw.original_row, ensure_ascii=False, sort_keys=True, default=str),
            ),
        )
        result = RawImportResult(raw, True, raw, import_run_id)
        self._record_import_occurrence(connection, result)
        return result

    def _record_import_occurrence(
        self, connection: sqlite3.Connection, result: RawImportResult
    ) -> None:
        observed = result.imported_observation
        if observed.import_batch_id is None:
            return
        if result.import_run_id is None:
            raise RuntimeError("batched observation is missing import_run_id")
        connection.execute(
            """
            INSERT INTO import_occurrences(
                occurrence_id, import_run_id, batch_id, raw_id,
                was_created, observed_json, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                result.import_run_id,
                observed.import_batch_id,
                result.raw_transaction.raw_id,
                int(result.created),
                json.dumps(observed.to_dict(), ensure_ascii=False, sort_keys=True, default=str),
                datetime.now().isoformat(),
            ),
        )

    def list_import_occurrences(
        self, batch_id: str, import_run_id: str | None = None
    ) -> list[ImportOccurrence]:
        """Return every row seen in an import, including overlap with earlier files."""

        where = "batch_id = ?"
        parameters: tuple[str, ...] = (batch_id,)
        if import_run_id:
            where += " AND import_run_id = ?"
            parameters = (batch_id, import_run_id)
        rows = self.connection.execute(
            f"SELECT * FROM import_occurrences WHERE {where} ORDER BY rowid", parameters
        ).fetchall()
        return [
            ImportOccurrence(
                occurrence_id=row["occurrence_id"],
                import_run_id=row["import_run_id"],
                batch_id=row["batch_id"],
                raw_id=row["raw_id"],
                created=bool(row["was_created"]),
                observed=json.loads(row["observed_json"]),
                recorded_at=datetime.fromisoformat(row["recorded_at"]),
            )
            for row in rows
        ]

    def analyze_import_coverage(self, batch_id: str, import_run_id: str) -> ImportCoverageReport:
        """Find prior observations missing inside this import's observed date ranges."""

        rows = self.connection.execute(
            """
            SELECT occurrences.raw_id, occurrences.was_created,
                   raw.source, raw.source_account, raw.booking_date
            FROM import_occurrences AS occurrences
            JOIN raw_transactions AS raw ON raw.raw_id = occurrences.raw_id
            WHERE occurrences.batch_id = ? AND occurrences.import_run_id = ?
            ORDER BY occurrences.rowid
            """,
            (batch_id, import_run_id),
        ).fetchall()
        observed_ids = {row["raw_id"] for row in rows}
        ranges: dict[tuple[str, str], list[date]] = {}
        for row in rows:
            if row["booking_date"]:
                ranges.setdefault((row["source"], row["source_account"]), []).append(
                    date.fromisoformat(row["booking_date"])
                )
        missing_ids: set[str] = set()
        for (source, source_account), dates in ranges.items():
            candidates = self.connection.execute(
                """
                SELECT raw_id FROM raw_transactions
                WHERE source = ? AND source_account = ?
                  AND booking_date BETWEEN ? AND ?
                """,
                (source, source_account, min(dates).isoformat(), max(dates).isoformat()),
            ).fetchall()
            missing_ids.update(
                row["raw_id"] for row in candidates if row["raw_id"] not in observed_ids
            )
        created_count = sum(bool(row["was_created"]) for row in rows)
        return ImportCoverageReport(
            batch_id=batch_id,
            import_run_id=import_run_id,
            occurrence_count=len(rows),
            unique_observation_count=len(observed_ids),
            created_count=created_count,
            existing_count=len(rows) - created_count,
            duplicate_occurrence_count=len(rows) - len(observed_ids),
            missing_raw_ids=tuple(sorted(missing_ids)),
        )

    def add_canonical(self, canonical: CanonicalTransaction) -> None:
        """Store a display/statistics transaction and any attached source links."""

        with self.transaction() as connection:
            self._insert_canonical(connection, canonical)

    def add_canonical_with_event(self, canonical: CanonicalTransaction, actor: str) -> None:
        """Store a manually created transaction and its audit event atomically."""

        now = datetime.now()
        after = canonical.to_dict(include_sources=True)
        with self.transaction() as connection:
            self._insert_canonical(connection, canonical)
            self._insert_canonical_event(
                connection,
                canonical.canonical_id,
                "created",
                {},
                after,
                actor,
                now,
            )

    def _insert_canonical(
        self, connection: sqlite3.Connection, canonical: CanonicalTransaction
    ) -> None:
        connection.execute(
            """
            INSERT INTO canonical_transactions(
                canonical_id, transaction_time, booking_date, amount, direction,
                merchant, normalized_merchant, category, payment_channel,
                funding_account, tx_type, status, review_status, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                canonical.canonical_id,
                canonical.transaction_time.isoformat() if canonical.transaction_time else None,
                canonical.booking_date.isoformat(),
                str(canonical.amount),
                canonical.direction,
                canonical.merchant,
                canonical.normalized_merchant,
                canonical.category,
                canonical.payment_channel,
                canonical.funding_account,
                canonical.tx_type.value,
                canonical.status,
                canonical.review_status.value,
                canonical.notes,
            ),
        )
        for link in canonical.source_links:
            self._insert_link(connection, canonical.canonical_id, link)

    def link_source(self, canonical_id: str, link: SourceRecordLink) -> None:
        """Persist one reviewed or automatic raw-to-canonical association."""

        with self.transaction() as connection:
            self._insert_link(connection, canonical_id, link)

    def _insert_link(
        self, connection: sqlite3.Connection, canonical_id: str, link: SourceRecordLink
    ) -> None:
        connection.execute(
            """
            INSERT INTO source_record_links(
                canonical_id, raw_id, confidence, reasons_json, matcher_version,
                linked_at, linked_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                canonical_id,
                link.raw_transaction.raw_id,
                str(link.confidence),
                json.dumps(link.reasons, ensure_ascii=False),
                link.matcher_version,
                link.linked_at.isoformat(),
                link.linked_by,
            ),
        )

    def unlink_source(self, canonical_id: str, raw_id: str) -> bool:
        """Remove a mistaken association without deleting the raw observation."""

        with self.transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM source_record_links WHERE canonical_id = ? AND raw_id = ?",
                (canonical_id, raw_id),
            )
        return cursor.rowcount == 1

    def get_canonical(self, canonical_id: str) -> CanonicalTransaction | None:
        row = self.connection.execute(
            "SELECT * FROM canonical_transactions WHERE canonical_id = ?", (canonical_id,)
        ).fetchone()
        if not row:
            return None
        canonical = self._canonical_from_row(row)
        link_rows = self.connection.execute(
            """
            SELECT links.*, raw.*
            FROM source_record_links AS links
            JOIN raw_transactions AS raw ON raw.raw_id = links.raw_id
            WHERE links.canonical_id = ?
            ORDER BY links.linked_at, links.raw_id
            """,
            (canonical_id,),
        ).fetchall()
        canonical.source_links = [self._link_from_joined_row(link_row) for link_row in link_rows]
        return canonical

    def list_canonical(self) -> list[CanonicalTransaction]:
        """Return one row per economic transaction for list and statistics views."""

        rows = self.connection.execute(
            """
            SELECT canonical.* FROM canonical_transactions AS canonical
            LEFT JOIN canonical_deletions AS deletions
              ON deletions.canonical_id = canonical.canonical_id
            WHERE deletions.canonical_id IS NULL
            ORDER BY booking_date DESC, transaction_time DESC
            """
        ).fetchall()
        return [self._canonical_from_row(row) for row in rows]

    def list_canonical_page(
        self,
        *,
        limit: int,
        offset: int,
        date_from: date | None = None,
        date_to: date | None = None,
        direction: str | None = None,
        category: str | None = None,
        search: str | None = None,
    ) -> tuple[list[CanonicalTransaction], int]:
        """Return a filtered page without loading the complete ledger into memory."""

        if limit < 1 or offset < 0:
            raise ValueError("limit must be positive and offset must not be negative")
        clauses: list[str] = [
            "NOT EXISTS (SELECT 1 FROM canonical_deletions AS deletions "
            "WHERE deletions.canonical_id = canonical_transactions.canonical_id)"
        ]
        parameters: list[object] = []
        if date_from:
            clauses.append("booking_date >= ?")
            parameters.append(date_from.isoformat())
        if date_to:
            clauses.append("booking_date <= ?")
            parameters.append(date_to.isoformat())
        if date_from and date_to and date_from > date_to:
            raise ValueError("date_from must not be after date_to")
        if direction:
            clauses.append("direction = ?")
            parameters.append(direction)
        if category:
            clauses.append("category = ?")
            parameters.append(category)
        if search:
            clauses.append("(merchant LIKE ? OR normalized_merchant LIKE ? OR notes LIKE ?)")
            pattern = f"%{search}%"
            parameters.extend((pattern, pattern, pattern))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        total = self.connection.execute(
            f"SELECT COUNT(*) FROM canonical_transactions {where}", parameters
        ).fetchone()[0]
        rows = self.connection.execute(
            f"""
            SELECT * FROM canonical_transactions
            {where}
            ORDER BY booking_date DESC, transaction_time DESC, canonical_id
            LIMIT ? OFFSET ?
            """,
            (*parameters, limit, offset),
        ).fetchall()
        return [self._canonical_from_row(row) for row in rows], total

    def list_deleted_canonical_page(
        self, *, limit: int, offset: int
    ) -> tuple[list[tuple[CanonicalTransaction, dict[str, str]]], int]:
        """Return soft-deleted transactions with deletion metadata."""

        if limit < 1 or offset < 0:
            raise ValueError("limit must be positive and offset must not be negative")
        total = self.connection.execute("SELECT COUNT(*) FROM canonical_deletions").fetchone()[0]
        rows = self.connection.execute(
            """
            SELECT canonical.*, deletions.actor AS deleted_by,
                   deletions.reason AS deletion_reason, deletions.deleted_at
            FROM canonical_deletions AS deletions
            JOIN canonical_transactions AS canonical
              ON canonical.canonical_id = deletions.canonical_id
            ORDER BY deletions.deleted_at DESC, canonical.canonical_id
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
        return [
            (
                self._canonical_from_row(row),
                {
                    "deleted_by": row["deleted_by"],
                    "deletion_reason": row["deletion_reason"],
                    "deleted_at": row["deleted_at"],
                },
            )
            for row in rows
        ], total

    def find_canonical_for_raw(self, raw_id: str) -> CanonicalTransaction | None:
        row = self.connection.execute(
            "SELECT canonical_id FROM source_record_links WHERE raw_id = ?", (raw_id,)
        ).fetchone()
        return self.get_canonical(row["canonical_id"]) if row else None

    def get_raw(self, raw_id: str) -> RawTransaction | None:
        """Return one immutable source observation by its stable identifier."""

        row = self.connection.execute(
            "SELECT * FROM raw_transactions WHERE raw_id = ?", (raw_id,)
        ).fetchone()
        return self._raw_from_row(row) if row else None

    def list_unlinked_raw(self) -> list[RawTransaction]:
        rows = self.connection.execute(
            """
            SELECT raw.*
            FROM raw_transactions AS raw
            LEFT JOIN source_record_links AS links ON links.raw_id = raw.raw_id
            WHERE links.raw_id IS NULL
            ORDER BY raw.booking_date, raw.transaction_time, raw.raw_id
            """
        ).fetchall()
        return [self._raw_from_row(row) for row in rows]

    def update_canonical_fields(
        self, canonical_id: str, changes: dict[str, str | None]
    ) -> CanonicalTransaction:
        """Update only human-editable canonical fields; raw records remain immutable."""

        with self.transaction() as connection:
            self._update_canonical_fields(connection, canonical_id, changes)
        updated = self.get_canonical(canonical_id)
        if updated is None:
            raise KeyError(canonical_id)
        return updated

    def update_canonical_with_event(
        self, canonical_id: str, changes: dict[str, str | None], actor: str
    ) -> CanonicalTransaction:
        """Update a visible transaction and append its audit event atomically."""

        current = self.get_canonical(canonical_id)
        if current is None:
            raise KeyError(canonical_id)
        before = current.to_dict(include_sources=True)
        with self.transaction() as connection:
            self._update_canonical_fields(connection, canonical_id, changes)
            updated = self.get_canonical(canonical_id)
            if updated is None:
                raise KeyError(canonical_id)
            self._insert_canonical_event(
                connection,
                canonical_id,
                "updated",
                before,
                updated.to_dict(include_sources=True),
                actor,
                datetime.now(),
            )
        return updated

    def is_canonical_deleted(self, canonical_id: str) -> bool:
        return (
            self.connection.execute(
                "SELECT 1 FROM canonical_deletions WHERE canonical_id = ?", (canonical_id,)
            ).fetchone()
            is not None
        )

    def soft_delete_canonical(self, canonical_id: str, actor: str, reason: str = "") -> None:
        """Hide a canonical transaction while retaining it, its sources, and an audit event."""

        canonical = self.get_canonical(canonical_id)
        if canonical is None:
            raise KeyError(canonical_id)
        if self.is_canonical_deleted(canonical_id):
            raise ValueError("transaction is already deleted")
        now = datetime.now()
        before = canonical.to_dict(include_sources=True)
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO canonical_deletions(canonical_id, actor, reason, deleted_at) "
                "VALUES (?, ?, ?, ?)",
                (canonical_id, actor, reason, now.isoformat()),
            )
            self._insert_canonical_event(
                connection, canonical_id, "deleted", before, {"deleted": True, "reason": reason}, actor, now
            )

    def restore_canonical(self, canonical_id: str, actor: str) -> None:
        """Restore a soft-deleted canonical transaction and retain the audit trail."""

        row = self.connection.execute(
            "SELECT * FROM canonical_deletions WHERE canonical_id = ?", (canonical_id,)
        ).fetchone()
        if row is None:
            raise ValueError("transaction is not deleted")
        now = datetime.now()
        with self.transaction() as connection:
            connection.execute(
                "DELETE FROM canonical_deletions WHERE canonical_id = ?", (canonical_id,)
            )
            self._insert_canonical_event(
                connection,
                canonical_id,
                "restored",
                {"deleted": True, "reason": row["reason"]},
                {"deleted": False},
                actor,
                now,
            )

    def record_canonical_event(
        self,
        canonical_id: str,
        action: str,
        before: dict[str, object],
        after: dict[str, object],
        actor: str,
    ) -> None:
        with self.transaction() as connection:
            self._insert_canonical_event(
                connection, canonical_id, action, before, after, actor, datetime.now()
            )

    def list_canonical_events(self, canonical_id: str) -> list[dict[str, object]]:
        rows = self.connection.execute(
            "SELECT * FROM canonical_events WHERE canonical_id = ? ORDER BY created_at, event_id",
            (canonical_id,),
        ).fetchall()
        return [
            {
                "event_id": row["event_id"],
                "canonical_id": row["canonical_id"],
                "action": row["action"],
                "before": json.loads(row["before_json"]),
                "after": json.loads(row["after_json"]),
                "actor": row["actor"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    @staticmethod
    def _insert_canonical_event(  # noqa: PLR0917
        connection: sqlite3.Connection,
        canonical_id: str,
        action: str,
        before: dict[str, object],
        after: dict[str, object],
        actor: str,
        created_at: datetime,
    ) -> None:
        connection.execute(
            """
            INSERT INTO canonical_events(
                event_id, canonical_id, action, before_json, after_json, actor, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                canonical_id,
                action,
                json.dumps(before, ensure_ascii=False, sort_keys=True, default=str),
                json.dumps(after, ensure_ascii=False, sort_keys=True, default=str),
                actor,
                created_at.isoformat(),
            ),
        )

    def _update_canonical_fields(
        self,
        connection: sqlite3.Connection,
        canonical_id: str,
        changes: dict[str, str | None],
    ) -> None:
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
            "review_status",
            "notes",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"canonical fields are not editable: {sorted(unknown)}")
        if not changes:
            exists = connection.execute(
                "SELECT 1 FROM canonical_transactions WHERE canonical_id = ?", (canonical_id,)
            ).fetchone()
            if exists is None:
                raise KeyError(canonical_id)
            return

        assignments = ", ".join(f"{field} = ?" for field in changes)
        values = list(changes.values())
        cursor = connection.execute(
            f"UPDATE canonical_transactions SET {assignments} WHERE canonical_id = ?",
            (*values, canonical_id),
        )
        if cursor.rowcount != 1:
            raise KeyError(canonical_id)

    @staticmethod
    def _batch_from_row(row: sqlite3.Row) -> ImportBatch:
        return ImportBatch(
            batch_id=row["batch_id"],
            source=Platform(row["source"]),
            source_file=row["source_file"],
            source_file_hash=row["source_file_hash"],
            imported_at=datetime.fromisoformat(row["imported_at"]),
        )

    @staticmethod
    def _raw_from_row(row: sqlite3.Row) -> RawTransaction:
        return RawTransaction(
            raw_id=row["raw_id"],
            source=Platform(row["source"]),
            source_account=row["source_account"],
            transaction_time=datetime.fromisoformat(row["transaction_time"])
            if row["transaction_time"]
            else None,
            booking_date=date.fromisoformat(row["booking_date"]) if row["booking_date"] else None,
            amount=Decimal(row["amount"]),
            direction=row["direction"],
            merchant=row["merchant"],
            counterparty=row["counterparty"],
            description=row["description"],
            payment_method=row["payment_method"],
            bank_card_suffix=row["bank_card_suffix"],
            transaction_id=row["transaction_id"],
            merchant_order_id=row["merchant_order_id"],
            status=row["status"],
            balance=Decimal(row["balance"]) if row["balance"] is not None else None,
            currency=row["currency"],
            import_batch_id=row["import_batch_id"],
            source_file=row["source_file"],
            source_file_hash=row["source_file_hash"],
            raw_row_number=row["raw_row_number"],
            original_row=json.loads(row["original_row_json"]),
        )

    @staticmethod
    def _canonical_from_row(row: sqlite3.Row) -> CanonicalTransaction:
        return CanonicalTransaction(
            canonical_id=row["canonical_id"],
            transaction_time=datetime.fromisoformat(row["transaction_time"])
            if row["transaction_time"]
            else None,
            booking_date=date.fromisoformat(row["booking_date"]),
            amount=Decimal(row["amount"]),
            direction=row["direction"],
            merchant=row["merchant"],
            normalized_merchant=row["normalized_merchant"],
            category=row["category"],
            payment_channel=row["payment_channel"],
            funding_account=row["funding_account"],
            tx_type=TransactionType(row["tx_type"]),
            status=row["status"],
            review_status=ReviewStatus(row["review_status"]),
            notes=row["notes"],
        )

    def _link_from_joined_row(self, row: sqlite3.Row) -> SourceRecordLink:
        return SourceRecordLink(
            raw_transaction=self._raw_from_row(row),
            confidence=Decimal(row["confidence"]),
            reasons=tuple(json.loads(row["reasons_json"])),
            matcher_version=row["matcher_version"],
            linked_at=datetime.fromisoformat(row["linked_at"]),
            linked_by=row["linked_by"],
        )
