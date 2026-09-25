import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest
from scripts.verify_platform_signature import verify_installer


def _runner(stdout: str = "", stderr: str = "", returncode: int = 0):
    def run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, returncode, stdout, stderr)

    return run


def test_windows_signature_evidence_is_bound_to_hash_and_publisher(tmp_path: Path) -> None:
    installer = tmp_path / "FinancialBeancount-windows-X64.msi"
    installer.write_bytes(b"msi")

    evidence = verify_installer(
        installer,
        platform_name="windows",
        expected_identity="Financial Beancount Project",
        runner=_runner("Issued to: Financial Beancount Project\nSuccessfully verified"),
    )

    assert evidence["verified"] is True
    assert evidence["artifact_name"] == installer.name
    assert evidence["identity"] == "Financial Beancount Project"
    assert len(evidence["artifact_sha256"]) == 64


def test_windows_signature_rejects_unexpected_publisher(tmp_path: Path) -> None:
    installer = tmp_path / "app.msi"
    installer.write_bytes(b"msi")

    with pytest.raises(ValueError, match="expected publisher"):
        verify_installer(
            installer,
            platform_name="windows",
            expected_identity="Expected Publisher",
            runner=_runner("Issued to: Different Publisher\nSuccessfully verified"),
        )


def test_macos_requires_both_codesign_and_gatekeeper(tmp_path: Path) -> None:
    installer = tmp_path / "FinancialBeancount-macos-ARM64.dmg"
    installer.write_bytes(b"dmg")
    calls = 0

    def run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        output = "origin=Developer ID Application: Example Publisher" if calls == 2 else "valid"
        return subprocess.CompletedProcess(command, 0, output, "")

    evidence = verify_installer(
        installer,
        platform_name="macos",
        expected_identity="Example Publisher",
        runner=run,
    )

    assert calls == 2
    assert evidence["verifier"] == "codesign --verify + spctl --assess"


def test_linux_pins_validsig_fingerprint(tmp_path: Path) -> None:
    installer = tmp_path / "FinancialBeancount-linux-X64.AppImage"
    signature = tmp_path / "FinancialBeancount-linux-X64.AppImage.asc"
    keyring = tmp_path / "release.gpg"
    installer.write_bytes(b"appimage")
    signature.write_bytes(b"signature")
    keyring.write_bytes(b"keyring")
    fingerprint = "ABCDEF0123456789ABCDEF0123456789ABCDEF01"

    evidence = verify_installer(
        installer,
        platform_name="linux",
        expected_identity=fingerprint,
        detached_signature=signature,
        keyring=keyring,
        runner=_runner(f"[GNUPG:] VALIDSIG {fingerprint} 2026-09-25 0 4 0 1 10 00"),
    )

    assert evidence["identity"] == fingerprint


def test_nonzero_native_verifier_exit_is_rejected(tmp_path: Path) -> None:
    installer = tmp_path / "app.msi"
    installer.write_bytes(b"msi")

    with pytest.raises(ValueError, match="signature verification failed"):
        verify_installer(
            installer,
            platform_name="windows",
            expected_identity="Publisher",
            runner=_runner(stderr="invalid signature", returncode=1),
        )
