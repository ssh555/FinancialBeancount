"""
Beancount 多平台账单去重工具

支持支付宝、微信、银行卡账单的导入、去重和导出为 Beancount 格式。
支持从 PDF、XLSX 等格式自动转换为 CSV。
"""

__version__ = "0.2.0"

from .account_classifier import (
    AccountType,
    AssetCategory,
    BeancountAccountClassifier,
    ExpenseCategory,
    IncomeCategory,
)
from .backup import BackupError, BackupManifest, export_backup, inspect_backup, restore_backup
from .candidate_review import CandidateReviewEvent, CandidateReviewGroup, CandidateReviewService
from .canonical_matcher import ConservativeMatcher, MatchCandidate, MatchEvidence
from .config import AppConfig, load_config
from .converters import AutoConverter, convert_to_csv
from .deduplicator import DeduplicationEngine, DedupResult
from .fingerprinter import TransactionFingerprinter
from .ledger_models import (
    CanonicalTransaction,
    RawTransaction,
    ReviewStatus,
    SourceRecordLink,
)
from .ledger_store import (
    ImportBatch,
    ImportCoverageReport,
    ImportOccurrence,
    LedgerStore,
    RawImportResult,
)
from .mobile_api import API_VERSION, ApiResponse, MobileLedgerApi, serve_mobile_api
from .models import Platform, Transaction
from .portable_archive import (
    PortableArchiveError,
    PortableArchiveManifest,
    export_portable_archive,
    import_portable_archive,
    inspect_portable_archive,
)
from .refund_relationships import RefundCandidate, RefundRelationshipService, RefundReviewEvent
from .review import ImportReviewService, ReviewEvent, ReviewItem, ReviewSession
from .state import StateStore
from .statement_adapters import (
    FunctionStatementAdapter,
    StatementAdapter,
    StatementAdapterRegistry,
    create_builtin_statement_registry,
)
from .statement_importer import ImportSummary, StatementImporter, StatementImportError
from .statistics import CategoryStatistics, StatisticsReport, StatisticsService
from .transaction_classification import (
    ClassificationCandidate,
    ClassificationEvent,
    TransactionClassificationService,
)

__all__ = [
    "API_VERSION",
    "AccountType",
    "ApiResponse",
    "AppConfig",
    "AssetCategory",
    "AutoConverter",
    "BackupError",
    "BackupManifest",
    "BeancountAccountClassifier",
    "CandidateReviewEvent",
    "CandidateReviewGroup",
    "CandidateReviewService",
    "CanonicalTransaction",
    "CategoryStatistics",
    "ClassificationCandidate",
    "ClassificationEvent",
    "ConservativeMatcher",
    "DedupResult",
    "DeduplicationEngine",
    "ExpenseCategory",
    "FunctionStatementAdapter",
    "ImportBatch",
    "ImportCoverageReport",
    "ImportOccurrence",
    "ImportReviewService",
    "ImportSummary",
    "IncomeCategory",
    "LedgerStore",
    "MatchCandidate",
    "MatchEvidence",
    "MobileLedgerApi",
    "Platform",
    "PortableArchiveError",
    "PortableArchiveManifest",
    "RawImportResult",
    "RawTransaction",
    "RefundCandidate",
    "RefundRelationshipService",
    "RefundReviewEvent",
    "ReviewEvent",
    "ReviewItem",
    "ReviewSession",
    "ReviewStatus",
    "SourceRecordLink",
    "StateStore",
    "StatementAdapter",
    "StatementAdapterRegistry",
    "StatementImportError",
    "StatementImporter",
    "StatisticsReport",
    "StatisticsService",
    "Transaction",
    "TransactionClassificationService",
    "TransactionFingerprinter",
    "convert_to_csv",
    "create_builtin_statement_registry",
    "export_backup",
    "export_portable_archive",
    "import_portable_archive",
    "inspect_backup",
    "inspect_portable_archive",
    "load_config",
    "restore_backup",
    "serve_mobile_api",
]
