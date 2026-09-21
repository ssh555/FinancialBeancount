"""Auditable raw and canonical transaction models.

The existing :class:`Transaction` model remains available for the legacy
parser/deduplicator pipeline.  These models introduce the target ledger shape:
many immutable source observations can describe one economic transaction.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from .models import Platform, TransactionType


class ReviewStatus(Enum):
    """Human-review state of a canonical transaction."""

    AUTO_CONFIRMED = "auto_confirmed"
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


@dataclass(frozen=True)
class RawTransaction:
    """One immutable observation from one imported statement row.

    ``deduplication_key`` identifies the source observation itself.  It is not
    an economic-transaction fingerprint and must never be used to merge two
    different platforms automatically.
    """

    source: Platform
    source_account: str
    amount: Decimal
    direction: str
    original_row: dict[str, Any]
    transaction_time: datetime | None = None
    booking_date: date | None = None
    merchant: str = ""
    counterparty: str = ""
    description: str = ""
    payment_method: str = ""
    bank_card_suffix: str | None = None
    transaction_id: str | None = None
    merchant_order_id: str | None = None
    status: str = ""
    balance: Decimal | None = None
    currency: str = "CNY"
    import_batch_id: str | None = None
    source_file: str = ""
    source_file_hash: str = ""
    raw_row_number: int | None = None
    raw_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", Decimal(str(self.amount)))
        if self.balance is not None:
            object.__setattr__(self, "balance", Decimal(str(self.balance)))
        if isinstance(self.source, str):
            object.__setattr__(self, "source", Platform(self.source))
        if self.bank_card_suffix and not (
            self.bank_card_suffix.isdigit() and len(self.bank_card_suffix) == 4
        ):
            raise ValueError("bank_card_suffix must contain exactly four digits")

    @property
    def deduplication_key(self) -> str:
        """Stable key for idempotent re-import of the same source record."""

        primary_external_id = self.transaction_id or self.merchant_order_id
        if primary_external_id:
            identity: dict[str, Any] = {
                "source": self.source.value,
                "source_account": self.source_account,
                "external_id": primary_external_id,
            }
        elif self.source == Platform.BANK and self.balance is not None:
            # Bank exports commonly overlap (for example Jan-Sep followed by
            # Jan-Dec).  A running balance makes the source observation stable
            # across those files without merging two distinct same-day spends.
            identity = {
                "source": self.source.value,
                "source_account": self.source_account,
                "transaction_time": self.transaction_time.isoformat()
                if self.transaction_time
                else None,
                "booking_date": self.booking_date.isoformat() if self.booking_date else None,
                "amount": str(self.amount),
                "direction": self.direction,
                "balance": str(self.balance),
                "currency": self.currency,
                "merchant": self.merchant.strip(),
                "counterparty": self.counterparty.strip(),
                "description": self.description.strip(),
                "payment_method": self.payment_method.strip(),
            }
        else:
            # Without an external identifier or a bank running balance, the
            # file row remains the safest identity; collapsing identical rows
            # here could erase two genuinely separate transactions.
            identity = {
                "source": self.source.value,
                "source_account": self.source_account,
                "source_file_hash": self.source_file_hash,
                "raw_row_number": self.raw_row_number,
                "original_row": self.original_row,
            }
        payload = json.dumps(identity, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self, include_original_row: bool = True) -> dict[str, Any]:
        result = {
            "raw_id": self.raw_id,
            "source": self.source.value,
            "source_account": self.source_account,
            "transaction_time": self.transaction_time.isoformat()
            if self.transaction_time
            else None,
            "booking_date": self.booking_date.isoformat() if self.booking_date else None,
            "amount": str(self.amount),
            "direction": self.direction,
            "merchant": self.merchant,
            "counterparty": self.counterparty,
            "description": self.description,
            "payment_method": self.payment_method,
            "bank_card_suffix": self.bank_card_suffix,
            "transaction_id": self.transaction_id,
            "merchant_order_id": self.merchant_order_id,
            "status": self.status,
            "balance": str(self.balance) if self.balance is not None else None,
            "currency": self.currency,
            "import_batch_id": self.import_batch_id,
            "source_file": self.source_file,
            "source_file_hash": self.source_file_hash,
            "raw_row_number": self.raw_row_number,
            "deduplication_key": self.deduplication_key,
        }
        if include_original_row:
            result["original_row"] = self.original_row
        return result


@dataclass(frozen=True)
class SourceRecordLink:
    """Auditable evidence connecting a raw observation to a canonical entry."""

    raw_transaction: RawTransaction
    confidence: Decimal
    reasons: tuple[str, ...]
    matcher_version: str
    linked_at: datetime = field(default_factory=datetime.now)
    linked_by: str = "system"

    def __post_init__(self) -> None:
        confidence = Decimal(str(self.confidence))
        if not Decimal("0") <= confidence <= Decimal("1"):
            raise ValueError("confidence must be between 0 and 1")
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "reasons", tuple(self.reasons))


@dataclass
class CanonicalTransaction:
    """One economic transaction shown once in lists and statistics."""

    transaction_time: datetime | None
    booking_date: date
    amount: Decimal
    direction: str
    merchant: str
    normalized_merchant: str = ""
    category: str = ""
    payment_channel: str = ""
    funding_account: str = ""
    tx_type: TransactionType = TransactionType.UNKNOWN
    status: str = ""
    review_status: ReviewStatus = ReviewStatus.PENDING
    notes: str = ""
    canonical_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_links: list[SourceRecordLink] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.amount = Decimal(str(self.amount))
        if isinstance(self.tx_type, str):
            self.tx_type = TransactionType(self.tx_type)
        if isinstance(self.review_status, str):
            self.review_status = ReviewStatus(self.review_status)

    @property
    def source_count(self) -> int:
        return len(self.source_links)

    @property
    def raw_transactions(self) -> tuple[RawTransaction, ...]:
        return tuple(link.raw_transaction for link in self.source_links)

    def add_source(
        self,
        raw_transaction: RawTransaction,
        *,
        confidence: Decimal | str,
        reasons: tuple[str, ...] | list[str],
        matcher_version: str,
        linked_by: str = "system",
    ) -> SourceRecordLink:
        """Attach one source observation without duplicating an existing row."""

        key = raw_transaction.deduplication_key
        if any(link.raw_transaction.deduplication_key == key for link in self.source_links):
            raise ValueError("raw transaction is already linked")
        link = SourceRecordLink(
            raw_transaction=raw_transaction,
            confidence=Decimal(str(confidence)),
            reasons=tuple(reasons),
            matcher_version=matcher_version,
            linked_by=linked_by,
        )
        self.source_links.append(link)
        return link

    def remove_source(self, raw_id: str) -> RawTransaction:
        """Detach a source observation so a mistaken match can be corrected."""

        for index, link in enumerate(self.source_links):
            if link.raw_transaction.raw_id == raw_id:
                return self.source_links.pop(index).raw_transaction
        raise KeyError(raw_id)

    def to_dict(self, include_sources: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "canonical_id": self.canonical_id,
            "transaction_time": self.transaction_time.isoformat()
            if self.transaction_time
            else None,
            "booking_date": self.booking_date.isoformat(),
            "amount": str(self.amount),
            "direction": self.direction,
            "merchant": self.merchant,
            "normalized_merchant": self.normalized_merchant,
            "category": self.category,
            "payment_channel": self.payment_channel,
            "funding_account": self.funding_account,
            "tx_type": self.tx_type.value,
            "status": self.status,
            "review_status": self.review_status.value,
            "notes": self.notes,
            "source_count": self.source_count,
        }
        if include_sources:
            result["sources"] = [
                {
                    "raw_transaction": link.raw_transaction.to_dict(),
                    "confidence": str(link.confidence),
                    "reasons": list(link.reasons),
                    "matcher_version": link.matcher_version,
                    "linked_at": link.linked_at.isoformat(),
                    "linked_by": link.linked_by,
                }
                for link in self.source_links
            ]
        return result
