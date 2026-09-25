import base64
import hashlib
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from scripts.configure_release_identity import configure
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


def test_package_directory_signs_exact_checksum_manifest(tmp_path: Path) -> None:
    source = tmp_path / "FinancialBeancount"
    source.mkdir()
    (source / "FinancialBeancount.exe").write_bytes(b"application")
    output = tmp_path / "release.zip"
    private_key = Ed25519PrivateKey.generate()
    encoded_key = base64.b64encode(private_key.private_bytes_raw()).decode()

    package_directory(source, output, signing_key=encoded_key, require_signature=True)

    checksum = output.with_suffix(".zip.sha256").read_bytes()
    signature = base64.b64decode(
        output.with_suffix(".zip.sha256.sig").read_bytes().strip(), validate=True
    )
    private_key.public_key().verify(signature, checksum)


def test_signed_release_refuses_missing_private_key(tmp_path: Path) -> None:
    source = tmp_path / "FinancialBeancount"
    source.mkdir()
    (source / "app").write_bytes(b"application")

    with pytest.raises(ValueError, match="signing key"):
        package_directory(source, tmp_path / "release.zip", require_signature=True)


def test_release_identity_configuration_writes_validated_public_key(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate().public_key().public_bytes_raw()
    encoded = base64.b64encode(key).decode()
    destination = tmp_path / "identity.py"

    configure(encoded, destination)

    assert f'BUILTIN_UPDATE_PUBLIC_KEY = "{encoded}"' in destination.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="32"):
        configure(base64.b64encode(b"short").decode(), destination)
