from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIGN_SCRIPT = ROOT / "installer" / "windows" / "sign.ps1"
WORKFLOW = ROOT / ".github" / "workflows" / "desktop-build.yml"


def test_windows_signing_requires_protected_credentials_and_rfc3161_timestamp() -> None:
    script = SIGN_SCRIPT.read_text(encoding="utf-8")
    assert "FINANCIAL_BEANCOUNT_WINDOWS_CERTIFICATE" in script
    assert "FINANCIAL_BEANCOUNT_WINDOWS_CERTIFICATE_PASSWORD" in script
    assert 'StartsWith("https://"' in script
    assert "/fd SHA256" in script
    assert "/tr $TimestampUrl" in script
    assert "/td SHA256" in script
    assert "verify /pa /tw /v" in script
    assert "Remove-Item -LiteralPath $temporaryCertificate" in script


def test_signed_windows_workflow_signs_binaries_before_msi_and_release_gate() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    binaries = workflow.index("Sign Windows application binaries")
    build_msi = workflow.index("Build Windows MSI")
    sign_msi = workflow.index("Sign Windows MSI")
    evidence = workflow.index("Record Windows native signature evidence")
    release_gate = workflow.index("Verify signed Windows release gate")
    assert binaries < build_msi < sign_msi < evidence < release_gate
    assert "secrets.FINANCIAL_BEANCOUNT_WINDOWS_CERTIFICATE" in workflow
    assert "secrets.FINANCIAL_BEANCOUNT_WINDOWS_CERTIFICATE_PASSWORD" in workflow
    assert "vars.FINANCIAL_BEANCOUNT_WINDOWS_TIMESTAMP_URL" in workflow
    assert "vars.FINANCIAL_BEANCOUNT_WINDOWS_PUBLISHER" in workflow
