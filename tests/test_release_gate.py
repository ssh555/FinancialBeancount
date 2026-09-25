import base64
import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from scripts.release_gate import inspect_release


def _repository(tmp_path: Path, public_key: str = "") -> Path:
    repository = tmp_path / "repository"
    (repository / "beancount_dedup").mkdir(parents=True)
    (repository / "docs").mkdir()
    (repository / "pyproject.toml").write_text(
        '[project]\nname = "financial-beancount"\nversion = "1.2.3"\n', encoding="utf-8"
    )
    (repository / "beancount_dedup" / "__init__.py").write_text(
        '__version__ = "1.2.3"\n', encoding="utf-8"
    )
    (repository / "beancount_dedup" / "_release_public_key.py").write_text(
        f'BUILTIN_UPDATE_PUBLIC_KEY = "{public_key}"\n', encoding="utf-8"
    )
    for name in ("PRIVACY.md", "RELEASE.md", "ROADMAP.md"):
        (repository / "docs" / name).write_text("gate\n", encoding="utf-8")
    return repository


def _archive(artifacts: Path) -> Path:
    artifacts.mkdir()
    archive = artifacts / "FinancialBeancount-windows-X64.zip"
    archive.write_bytes(b"desktop")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(
        f"{digest}  {archive.name}\n", encoding="utf-8"
    )
    return archive


def test_preview_gate_accepts_complete_development_archive(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    artifacts = tmp_path / "artifacts"
    _archive(artifacts)

    checks = inspect_release(
        repository, artifacts, mode="preview", platform_name="windows", architecture="X64"
    )

    assert all(check.passed for check in checks)


def test_release_gate_fails_closed_without_identity_installer_and_signature(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    artifacts = tmp_path / "artifacts"
    _archive(artifacts)

    checks = inspect_release(
        repository, artifacts, mode="release", platform_name="windows", architecture="X64"
    )

    failed = {check.name for check in checks if not check.passed}
    assert failed == {
        "embedded-update-public-key",
        "signed-update-manifest",
        "native-installer",
        "os-signature-verification",
    }


def test_release_gate_accepts_matching_signature_evidence(tmp_path: Path) -> None:
    private_key = Ed25519PrivateKey.generate()
    public_key = base64.b64encode(private_key.public_key().public_bytes_raw()).decode()
    repository = _repository(tmp_path, public_key)
    artifacts = tmp_path / "artifacts"
    archive = _archive(artifacts)
    checksum = archive.with_suffix(".zip.sha256")
    archive.with_suffix(".zip.sha256.sig").write_bytes(
        base64.b64encode(private_key.sign(checksum.read_bytes())) + b"\n"
    )
    installer = artifacts / "FinancialBeancount-windows-X64.msi"
    installer.write_bytes(b"signed-installer")
    installer.with_suffix(".msi.signature.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "verified": True,
                "platform": "windows",
                "artifact_name": installer.name,
                "artifact_sha256": hashlib.sha256(installer.read_bytes()).hexdigest(),
                "identity": "Example Publisher",
                "verifier": "signtool verify /pa /tw",
                "verified_at": "2026-09-25T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    checks = inspect_release(
        repository, artifacts, mode="release", platform_name="windows", architecture="X64"
    )

    assert all(check.passed for check in checks)


def test_release_gate_rejects_legacy_self_reported_signature_evidence(tmp_path: Path) -> None:
    private_key = Ed25519PrivateKey.generate()
    public_key = base64.b64encode(private_key.public_key().public_bytes_raw()).decode()
    repository = _repository(tmp_path, public_key)
    artifacts = tmp_path / "artifacts"
    archive = _archive(artifacts)
    checksum = archive.with_suffix(".zip.sha256")
    archive.with_suffix(".zip.sha256.sig").write_bytes(
        base64.b64encode(private_key.sign(checksum.read_bytes())) + b"\n"
    )
    installer = artifacts / "FinancialBeancount-windows-X64.msi"
    installer.write_bytes(b"signed-installer")
    installer.with_suffix(".msi.signature.json").write_text(
        json.dumps(
            {
                "verified": True,
                "artifact_sha256": hashlib.sha256(installer.read_bytes()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )

    checks = inspect_release(
        repository, artifacts, mode="release", platform_name="windows", architecture="X64"
    )

    assert next(check for check in checks if check.name == "os-signature-verification").passed is False
