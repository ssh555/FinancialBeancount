import subprocess
import sys

import beancount_dedup


def test_package_import_does_not_load_optional_converter_stack() -> None:
    code = """
import sys
import beancount_dedup
assert 'pandas' not in sys.modules
assert 'openpyxl' not in sys.modules
assert 'pdfplumber' not in sys.modules
"""
    subprocess.run([sys.executable, "-c", code], check=True)


def test_lazy_public_exports_remain_available() -> None:
    assert beancount_dedup.LedgerStore.__name__ == "LedgerStore"
    assert beancount_dedup.MobileLedgerApi.__name__ == "MobileLedgerApi"
    assert beancount_dedup.AutoConverter.__name__ == "AutoConverter"
    assert "TransactionFingerprinter" in dir(beancount_dedup)
