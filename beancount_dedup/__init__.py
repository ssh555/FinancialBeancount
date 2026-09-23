"""Beancount 多平台账单去重工具的公共接口。

公共对象按需导入，避免启动桌面应用时加载转换器及其可选依赖。
"""

from importlib import import_module
from typing import Any

__version__ = "0.2.0"

_EXPORTS = {
    "API_VERSION": ("mobile_api", "API_VERSION"),
    "AccountType": ("account_classifier", "AccountType"),
    "ApiResponse": ("mobile_api", "ApiResponse"),
    "AppConfig": ("config", "AppConfig"),
    "AssetCategory": ("account_classifier", "AssetCategory"),
    "AutoConverter": ("converters", "AutoConverter"),
    "BackupError": ("backup", "BackupError"),
    "BackupManifest": ("backup", "BackupManifest"),
    "BeancountAccountClassifier": ("account_classifier", "BeancountAccountClassifier"),
    "CandidateReviewEvent": ("candidate_review", "CandidateReviewEvent"),
    "CandidateReviewGroup": ("candidate_review", "CandidateReviewGroup"),
    "CandidateReviewService": ("candidate_review", "CandidateReviewService"),
    "CanonicalTransaction": ("ledger_models", "CanonicalTransaction"),
    "CategoryStatistics": ("statistics", "CategoryStatistics"),
    "ClassificationCandidate": ("transaction_classification", "ClassificationCandidate"),
    "ClassificationEvent": ("transaction_classification", "ClassificationEvent"),
    "ConservativeMatcher": ("canonical_matcher", "ConservativeMatcher"),
    "DedupResult": ("deduplicator", "DedupResult"),
    "DeduplicationEngine": ("deduplicator", "DeduplicationEngine"),
    "ExpenseCategory": ("account_classifier", "ExpenseCategory"),
    "FunctionStatementAdapter": ("statement_adapters", "FunctionStatementAdapter"),
    "ImportBatch": ("ledger_store", "ImportBatch"),
    "ImportCoverageReport": ("ledger_store", "ImportCoverageReport"),
    "ImportOccurrence": ("ledger_store", "ImportOccurrence"),
    "ImportReviewService": ("review", "ImportReviewService"),
    "ImportSummary": ("statement_importer", "ImportSummary"),
    "IncomeCategory": ("account_classifier", "IncomeCategory"),
    "LedgerStore": ("ledger_store", "LedgerStore"),
    "LedgerMigrationError": ("ledger_store", "LedgerMigrationError"),
    "MatchCandidate": ("canonical_matcher", "MatchCandidate"),
    "MatchEvidence": ("canonical_matcher", "MatchEvidence"),
    "MobileLedgerApi": ("mobile_api", "MobileLedgerApi"),
    "Platform": ("models", "Platform"),
    "PortableArchiveError": ("portable_archive", "PortableArchiveError"),
    "PortableArchiveManifest": ("portable_archive", "PortableArchiveManifest"),
    "PreparedUpdate": ("updater", "PreparedUpdate"),
    "RawImportResult": ("ledger_store", "RawImportResult"),
    "RawTransaction": ("ledger_models", "RawTransaction"),
    "RefundCandidate": ("refund_relationships", "RefundCandidate"),
    "RefundRelationshipService": ("refund_relationships", "RefundRelationshipService"),
    "RefundReviewEvent": ("refund_relationships", "RefundReviewEvent"),
    "ReviewEvent": ("review", "ReviewEvent"),
    "ReviewItem": ("review", "ReviewItem"),
    "ReviewSession": ("review", "ReviewSession"),
    "ReviewStatus": ("ledger_models", "ReviewStatus"),
    "SourceRecordLink": ("ledger_models", "SourceRecordLink"),
    "StateStore": ("state", "StateStore"),
    "StatementAdapter": ("statement_adapters", "StatementAdapter"),
    "StatementAdapterRegistry": ("statement_adapters", "StatementAdapterRegistry"),
    "StatementImportError": ("statement_importer", "StatementImportError"),
    "StatementImporter": ("statement_importer", "StatementImporter"),
    "StatisticsReport": ("statistics", "StatisticsReport"),
    "StatisticsService": ("statistics", "StatisticsService"),
    "Transaction": ("models", "Transaction"),
    "TransactionClassificationService": ("transaction_classification", "TransactionClassificationService"),
    "TransactionFingerprinter": ("fingerprinter", "TransactionFingerprinter"),
    "UpdateCheckError": ("updater", "UpdateCheckError"),
    "UpdateInfo": ("updater", "UpdateInfo"),
    "check_for_update": ("updater", "check_for_update"),
    "download_and_verify_update": ("updater", "download_and_verify_update"),
    "prepare_update_installation": ("updater", "prepare_update_installation"),
    "convert_to_csv": ("converters", "convert_to_csv"),
    "create_builtin_statement_registry": ("statement_adapters", "create_builtin_statement_registry"),
    "export_backup": ("backup", "export_backup"),
    "export_portable_archive": ("portable_archive", "export_portable_archive"),
    "import_portable_archive": ("portable_archive", "import_portable_archive"),
    "inspect_backup": ("backup", "inspect_backup"),
    "inspect_portable_archive": ("portable_archive", "inspect_portable_archive"),
    "load_config": ("config", "load_config"),
    "restore_backup": ("backup", "restore_backup"),
    "serve_mobile_api": ("mobile_api", "serve_mobile_api"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    """Resolve and cache a public object on first access."""
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(f".{module_name}", __name__), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
