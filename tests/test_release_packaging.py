import hashlib
import zipfile
from pathlib import Path

import pytest
from scripts.package_desktop_artifact import package_directory


def test_package_directory_creates_archive_and_checksum(tmp_path: Path) -> None:
    source = tmp_path / "FinancialBeancount"
    (source / "assets").mkdir(parents=True)
    (source / "FinancialBeancount.exe").write_bytes(b"application")
    (source / "assets" / "manifest.webmanifest").write_text("{}", encoding="utf-8")
    output = tmp_path / "artifacts" / "FinancialBeancount-windows-X64.zip"

    digest = package_directory(source, output)

    assert digest == hashlib.sha256(output.read_bytes()).hexdigest()
    assert output.with_suffix(".zip.sha256").read_text(encoding="utf-8") == (
        f"{digest}  {output.name}\n"
    )
    with zipfile.ZipFile(output) as archive:
        assert archive.namelist() == [
            "FinancialBeancount/assets/manifest.webmanifest",
            "FinancialBeancount/FinancialBeancount.exe",
        ]


def test_package_directory_rejects_empty_build(tmp_path: Path) -> None:
    source = tmp_path / "empty"
    source.mkdir()
    with pytest.raises(ValueError, match="empty"):
        package_directory(source, tmp_path / "release.zip")
