from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "installer" / "macos" / "build_dmg.sh"
SMOKE = ROOT / "installer" / "macos" / "smoke_dmg.sh"
SIGN = ROOT / "installer" / "macos" / "sign_and_notarize.sh"
SPEC = ROOT / "FinancialBeancount.spec"
WORKFLOW = ROOT / ".github" / "workflows" / "desktop-build.yml"


def test_pyinstaller_builds_stable_macos_application_identity() -> None:
    spec = SPEC.read_text(encoding="utf-8")
    assert 'name="FinancialBeancount.app"' in spec
    assert 'bundle_identifier="io.github.ssh555.financialbeancount"' in spec


def test_dmg_builder_preserves_bundle_and_adds_applications_link() -> None:
    script = BUILD.read_text(encoding="utf-8")
    assert "set -euo pipefail" in script
    assert 'ditto "$app_bundle"' in script
    assert 'ln -s /Applications "$staging/Applications"' in script
    assert "hdiutil create" in script
    assert "-format UDZO" in script
    assert 'if [[ -e "$output_dmg" ]]' in script


def test_dmg_smoke_keeps_application_and_ledger_lifecycles_separate() -> None:
    script = SMOKE.read_text(encoding="utf-8")
    assert "hdiutil attach" in script
    assert "hdiutil detach" in script
    assert "Library/Application Support/FinancialBeancount" in script
    assert 'rm -rf "$applications/FinancialBeancount.app"' in script
    assert 'cat "$sentinel"' in script


def test_macos_preview_workflow_builds_and_smokes_dmg() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    build = workflow.index("Build macOS DMG preview")
    smoke = workflow.index("Verify macOS DMG replacement and data preservation")
    upload = workflow.index("actions/upload-artifact@v4")
    assert build < smoke < upload
    assert "installer/macos/build_dmg.sh" in workflow
    assert "installer/macos/smoke_dmg.sh" in workflow


def test_macos_signed_release_is_hardened_notarized_and_stapled() -> None:
    script = SIGN.read_text(encoding="utf-8")
    assert "set -euo pipefail" in script
    for variable in (
        "FINANCIAL_BEANCOUNT_MACOS_CERTIFICATE",
        "FINANCIAL_BEANCOUNT_MACOS_CERTIFICATE_PASSWORD",
        "FINANCIAL_BEANCOUNT_MACOS_SIGNING_IDENTITY",
        "FINANCIAL_BEANCOUNT_APPLE_ID",
        "FINANCIAL_BEANCOUNT_APPLE_APP_PASSWORD",
        "FINANCIAL_BEANCOUNT_APPLE_TEAM_ID",
    ):
        assert f"${{{variable}:?" in script
    assert "--options runtime" in script
    assert "--timestamp" in script
    assert "codesign --verify --deep --strict" in script
    assert "xcrun notarytool submit" in script
    assert 'payload.get("status") != "Accepted"' in script
    assert "xcrun stapler staple -v" in script
    assert "xcrun stapler validate -v" in script
    assert "spctl --assess --type open" in script
    assert 'security delete-keychain "$keychain"' in script


def test_signed_macos_workflow_records_evidence_before_release_gate() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    signing = workflow.index("Sign and notarize macOS DMG")
    evidence = workflow.index("Record macOS native signature evidence")
    packaging = workflow.index("Package signed release asset")
    gate = workflow.index("Verify signed macOS release gate")
    assert signing < evidence < packaging < gate
    assert "secrets.FINANCIAL_BEANCOUNT_MACOS_CERTIFICATE" in workflow
    assert "secrets.FINANCIAL_BEANCOUNT_APPLE_APP_PASSWORD" in workflow
    assert "vars.FINANCIAL_BEANCOUNT_MACOS_SIGNING_IDENTITY" in workflow
