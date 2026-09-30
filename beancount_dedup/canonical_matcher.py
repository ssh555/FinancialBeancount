"""Conservative cross-platform candidate matching for human review."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3

from .ledger_models import RawTransaction
from .ledger_store import LedgerStore
from .models import Platform

MATCHER_VERSION = "canonical-candidate-v1"
PAYMENT_PLATFORMS = {Platform.ALIPAY, Platform.WECHAT}


@dataclass(frozen=True)
class MatchEvidence:
    code: str
    weight: Decimal

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "weight": str(self.weight)}


@dataclass(frozen=True)
class MatchCandidate:
    candidate_id: str
    payment_raw_id: str
    bank_raw_id: str
    confidence: Decimal
    evidence: tuple[MatchEvidence, ...]
    matcher_version: str = MATCHER_VERSION
    status: str = "pending"
    is_ambiguous: bool = False
    created_at: datetime = field(default_factory=datetime.now)


class ConservativeMatcher:
    """Generate review candidates without deleting or automatically linking rows."""

    def __init__(self, store: LedgerStore):
        self.store = store

    def generate_candidates(self) -> list[MatchCandidate]:
        raws = self.store.list_unlinked_raw()
        payments = [raw for raw in raws if raw.source in PAYMENT_PLATFORMS]
        banks = [raw for raw in raws if raw.source == Platform.BANK]
        bank_index: dict[Decimal, list[RawTransaction]] = {}
        for bank in banks:
            bank_index.setdefault(bank.amount, []).append(bank)

        exact_candidates = []
        fuzzy_candidates = []
        for payment in payments:
            for bank in bank_index.get(payment.amount, []):
                candidate = self._candidate(payment, bank)
                if candidate is not None:
                    codes = {item.code for item in candidate.evidence}
                    if "match_phase_exact" in codes:
                        exact_candidates.append(candidate)
                    else:
                        fuzzy_candidates.append(candidate)
        # Exact observations always win.  Fuzzy matching is a fallback only;
        # it must never add alternatives around a row that already has an
        # exact candidate.
        exact_payment_ids = {item.payment_raw_id for item in exact_candidates}
        exact_bank_ids = {item.bank_raw_id for item in exact_candidates}
        candidates = exact_candidates + [
            item
            for item in fuzzy_candidates
            if item.payment_raw_id not in exact_payment_ids
            and item.bank_raw_id not in exact_bank_ids
        ]
        candidates = self._mark_ambiguity(candidates)
        self._persist(candidates)
        return candidates

    def list_candidates(self, status: str | None = "pending") -> list[MatchCandidate]:
        """Return persisted candidates for the human-review queue."""

        parameters: tuple[str, ...] = ()
        where = ""
        if status is not None:
            where = "WHERE status = ?"
            parameters = (status,)
        rows = self.store.connection.execute(
            f"""
            SELECT * FROM match_candidates
            {where}
            ORDER BY is_ambiguous DESC, CAST(confidence AS REAL) DESC, created_at, candidate_id
            """,
            parameters,
        ).fetchall()
        return [self._from_row(row) for row in rows]

    def _candidate(  # noqa: PLR0911 - guard clauses document conservative rejection rules
        self, payment: RawTransaction, bank: RawTransaction
    ) -> MatchCandidate | None:
        if payment.booking_date is None or bank.booking_date is None:
            return None
        if _is_bank_internal_product(bank):
            return None
        day_difference = abs((payment.booking_date - bank.booking_date).days)
        if day_difference > 1:
            return None

        refund_credit_pair = _is_refund_credit_pair(payment, bank)
        anchored_refund_credit = _is_anchored_refund_credit(payment, bank, day_difference)
        if payment.direction != bank.direction and not (
            refund_credit_pair or anchored_refund_credit
        ):
            return None
        payment_rail = _bank_payment_rail(bank)
        if payment_rail is not None and payment.source != payment_rail:
            return None
        suffix_match = bool(
            payment.bank_card_suffix
            and bank.bank_card_suffix
            and payment.bank_card_suffix == bank.bank_card_suffix
        )
        bank_name_match = _bank_name_matches(payment.payment_method, bank.payment_method)
        # A wallet/balance-funded platform row has no corresponding bank debit.
        # Merchant and amount resemblance must never manufacture one.
        if not (payment.bank_card_suffix or bank_name_match):
            return None

        evidence = [MatchEvidence("amount_exact", Decimal("0.25"))]
        evidence.append(
            MatchEvidence(
                (
                    "refund_credit_direction"
                    if refund_credit_pair
                    else "anchored_refund_credit"
                    if anchored_refund_credit
                    else "direction_exact"
                ),
                Decimal("0.10"),
            )
        )
        if day_difference == 0:
            evidence.append(MatchEvidence("booking_date_exact", Decimal("0.15")))
        else:
            evidence.append(MatchEvidence("booking_date_adjacent", Decimal("0.05")))

        merchant_match = _merchant_similarity(payment, bank)
        exact_time = False
        close_time = False
        if payment.transaction_time and bank.transaction_time:
            seconds = abs((payment.transaction_time - bank.transaction_time).total_seconds())
            exact_time = seconds <= 5
            close_time = 5 < seconds <= 120

        if suffix_match:
            evidence.append(MatchEvidence("bank_suffix_exact", Decimal("0.25")))
        if bank_name_match:
            evidence.append(MatchEvidence("bank_name_exact", Decimal("0.10")))
        if payment_rail is not None:
            evidence.append(MatchEvidence("payment_rail_exact", Decimal("0.10")))
        if exact_time:
            evidence.append(MatchEvidence("datetime_exact", Decimal("0.20")))
        elif close_time:
            evidence.append(MatchEvidence("datetime_close", Decimal("0.12")))
        elif bank.transaction_time is None:
            evidence.append(MatchEvidence("bank_time_unavailable", Decimal("0.00")))
        if merchant_match:
            evidence.append(MatchEvidence("merchant_semantic_match", Decimal("0.10")))

        exact_phase = bool(
            day_difference == 0
            and (suffix_match or bank_name_match)
            and (exact_time or merchant_match or payment_rail is not None)
        )
        evidence.append(
            MatchEvidence(
                "match_phase_exact" if exact_phase else "match_phase_fuzzy",
                Decimal("0.00"),
            )
        )

        # A one-day settlement difference is plausible, but amount and bank
        # alone cannot distinguish two unrelated purchases on adjacent days.
        if day_difference == 1 and not (merchant_match or payment_rail is not None):
            return None

        # Amount/date alone are never enough. Require at least one independent
        # funding, time, or merchant signal before presenting a candidate.
        independent = suffix_match or bank_name_match or exact_time or close_time or merchant_match
        if not independent:
            return None
        confidence = min(sum((item.weight for item in evidence), Decimal("0")), Decimal("0.99"))
        return MatchCandidate(
            candidate_id=str(uuid.uuid4()),
            payment_raw_id=payment.raw_id,
            bank_raw_id=bank.raw_id,
            confidence=confidence,
            evidence=tuple(evidence),
            created_at=datetime.now(),
        )

    @staticmethod
    def _mark_ambiguity(candidates: list[MatchCandidate]) -> list[MatchCandidate]:
        by_payment: dict[str, list[MatchCandidate]] = {}
        by_bank: dict[str, list[MatchCandidate]] = {}
        for candidate in candidates:
            by_payment.setdefault(candidate.payment_raw_id, []).append(candidate)
            by_bank.setdefault(candidate.bank_raw_id, []).append(candidate)

        marked = []
        for candidate in candidates:
            payment_group = by_payment[candidate.payment_raw_id]
            bank_group = by_bank[candidate.bank_raw_id]
            # Any one-to-many or many-to-one possibility needs explicit human
            # attention, even when one candidate has a higher score.  Choosing
            # the top score automatically could silently hide a real duplicate.
            competing_payment = len(payment_group) > 1
            competing_bank = len(bank_group) > 1
            marked.append(
                replace(
                    candidate,
                    is_ambiguous=competing_payment or competing_bank,
                )
            )
        return marked

    def _persist(self, candidates: list[MatchCandidate]) -> None:
        with self.store.transaction() as connection:
            for candidate in candidates:
                connection.execute(
                    """
                    INSERT INTO match_candidates(
                        candidate_id, left_raw_id, right_raw_id, confidence,
                        evidence_json, matcher_version, status, is_ambiguous,
                        created_at, reviewed_at, reviewed_by
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                    ON CONFLICT(left_raw_id, right_raw_id, matcher_version)
                    DO UPDATE SET
                        confidence = excluded.confidence,
                        evidence_json = excluded.evidence_json,
                        is_ambiguous = excluded.is_ambiguous
                    """,
                    (
                        candidate.candidate_id,
                        candidate.payment_raw_id,
                        candidate.bank_raw_id,
                        str(candidate.confidence),
                        json.dumps(
                            [item.to_dict() for item in candidate.evidence],
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        candidate.matcher_version,
                        candidate.status,
                        int(candidate.is_ambiguous),
                        candidate.created_at.isoformat(),
                    ),
                )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> MatchCandidate:
        evidence_data = json.loads(row["evidence_json"])
        return MatchCandidate(
            candidate_id=row["candidate_id"],
            payment_raw_id=row["left_raw_id"],
            bank_raw_id=row["right_raw_id"],
            confidence=Decimal(row["confidence"]),
            evidence=tuple(
                MatchEvidence(code=item["code"], weight=Decimal(item["weight"]))
                for item in evidence_data
            ),
            matcher_version=row["matcher_version"],
            status=row["status"],
            is_ambiguous=bool(row["is_ambiguous"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )


def _bank_name_matches(payment_method: str, bank_method: str) -> bool:
    aliases = {
        "cmb": ("招商银行", "招商", "cmb"),
        "icbc": ("工商银行", "工行", "icbc"),
        "cqrcb": (
            "重庆农村商业银行",
            "重庆农商行",
            "农村商业银行",
            "农商行",
            "cqrcb",
        ),
    }
    payment_lower = payment_method.lower()
    bank_lower = bank_method.lower()
    return any(
        any(alias in payment_lower for alias in names)
        and any(alias in bank_lower for alias in names)
        for names in aliases.values()
    )


def _merchant_similarity(payment: RawTransaction, bank: RawTransaction) -> bool:
    payment_tokens = _merchant_tokens(
        " ".join((payment.merchant, payment.counterparty, payment.description))
    )
    bank_tokens = _merchant_tokens(" ".join((bank.merchant, bank.counterparty, bank.description)))
    return bool(payment_tokens & bank_tokens)


def _is_refund_credit_pair(payment: RawTransaction, bank: RawTransaction) -> bool:
    if payment.amount <= 0 or payment.direction not in {"neutral", "income"}:
        return False
    if bank.amount <= 0 or bank.direction != "income":
        return False
    payment_text = " ".join(
        (payment.merchant, payment.counterparty, payment.description, payment.status)
    ).lower()
    bank_text = " ".join((bank.merchant, bank.counterparty, bank.description, bank.status)).lower()
    markers = ("退款", "退回", "refund")
    return any(marker in payment_text for marker in markers) and any(
        marker in bank_text for marker in markers
    )


def _is_anchored_refund_credit(
    payment: RawTransaction, bank: RawTransaction, day_difference: int
) -> bool:
    """Allow a platform refund to match a generic bank credit via its balance chain.

    Some banks export refunds as generic credits or the real counterparty rather
    than the platform merchant.  Same-card, same-amount and same-day constraints
    are applied by the caller; the non-null bank balance supplies the auditable
    account-chain anchor.
    """

    if day_difference != 0 or payment.amount <= 0 or bank.amount <= 0:
        return False
    if bank.direction != "income" or bank.balance is None:
        return False
    text = " ".join(
        (payment.merchant, payment.counterparty, payment.description, payment.status)
    ).lower()
    return any(marker in text for marker in ("退款", "退回", "refund"))


def _bank_payment_rail(bank: RawTransaction) -> Platform | None:
    text = " ".join((bank.merchant, bank.counterparty, bank.description)).lower()
    if "支付宝" in text or "alipay" in text:
        return Platform.ALIPAY
    if "财付通" in text or "微信" in text or "wechat" in text:
        return Platform.WECHAT
    return None


def _is_bank_internal_product(bank: RawTransaction) -> bool:
    text = " ".join((bank.description, bank.counterparty)).lower()
    return any(
        marker in text
        for marker in ("朝朝宝转入", "朝朝宝转出", "理财购买", "理财赎回", "基金购买")
    )


def _merchant_tokens(value: str) -> set[str]:
    normalized = value.lower()
    aliases = {
        "高德": ("高德",),
        "滴滴": ("滴滴", "小桔"),
        "美团": ("美团", "三快"),
        "饿了么": ("饿了么", "拉扎斯"),
    }
    tokens = {
        canonical
        for canonical, names in aliases.items()
        if any(name in normalized for name in names)
    }
    cleaned = re.sub(
        r"有限公司|有限责任公司|信息技术|网络科技|科技|支付|快捷|消费|[\W_]",
        "",
        normalized,
    )
    for length in (2, 3, 4):
        tokens.update(
            cleaned[index : index + length] for index in range(max(0, len(cleaned) - length + 1))
        )
    return {token for token in tokens if len(token) >= 2}
