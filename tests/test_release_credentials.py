import base64
from pathlib import Path

import pytest
from scripts.validate_release_credentials import validate_credentials


def _common() -> dict[str, str]:
    return {
        "FINANCIAL_BEANCOUNT_RELEASE_SIGNING_KEY": base64.b64encode(b"s" * 32).decode(),
        "FINANCIAL_BEANCOUNT_UPDATE_PUBLIC_KEY": base64.b64encode(b"p" * 32).decode(),
    }


def test_windows_preflight_validates_formats_without_returning_values() -> None:
    environment = _common() | {
        "FINANCIAL_BEANCOUNT_WINDOWS_CERTIFICATE": base64.b64encode(b"pfx").decode(),
        "FINANCIAL_BEANCOUNT_WINDOWS_CERTIFICATE_PASSWORD": "secret",
        "FINANCIAL_BEANCOUNT_WINDOWS_TIMESTAMP_URL": "https://timestamp.example.test",
        "FINANCIAL_BEANCOUNT_WINDOWS_PUBLISHER": "Example Publisher",
    }

    validated = validate_credentials("windows", environment)

    assert set(validated) == set(environment)
    assert not set(environment.values()) & set(validated)


def test_macos_preflight_requires_developer_identity_and_team() -> None:
    environment = _common() | {
        "FINANCIAL_BEANCOUNT_MACOS_CERTIFICATE": base64.b64encode(b"p12").decode(),
        "FINANCIAL_BEANCOUNT_MACOS_CERTIFICATE_PASSWORD": "secret",
        "FINANCIAL_BEANCOUNT_APPLE_ID": "publisher@example.test",
        "FINANCIAL_BEANCOUNT_APPLE_APP_PASSWORD": "app-password",
        "FINANCIAL_BEANCOUNT_MACOS_SIGNING_IDENTITY": "Developer ID Application: Example (ABCDE12345)",
        "FINANCIAL_BEANCOUNT_APPLE_TEAM_ID": "ABCDE12345",
    }
    assert validate_credentials("macos", environment)
    environment["FINANCIAL_BEANCOUNT_APPLE_TEAM_ID"] = "short"
    with pytest.raises(ValueError, match="TEAM_ID"):
        validate_credentials("macos", environment)


def test_linux_preflight_requires_full_fingerprint() -> None:
    environment = _common() | {
        "FINANCIAL_BEANCOUNT_LINUX_SIGNING_KEY": base64.b64encode(b"private-key").decode(),
        "FINANCIAL_BEANCOUNT_LINUX_SIGNING_FINGERPRINT": "A" * 40,
    }
    assert validate_credentials("linux", environment)
    environment["FINANCIAL_BEANCOUNT_LINUX_SIGNING_FINGERPRINT"] = "A" * 16
    with pytest.raises(ValueError, match="40 hexadecimal"):
        validate_credentials("linux", environment)


def test_preflight_lists_missing_names_but_never_values() -> None:
    environment = _common()
    with pytest.raises(ValueError) as error:
        validate_credentials("windows", environment)
    assert "FINANCIAL_BEANCOUNT_WINDOWS_CERTIFICATE" in str(error.value)
    assert not any(value in str(error.value) for value in environment.values())


def test_preflight_rejects_malformed_base64_and_insecure_timestamp() -> None:
    environment = _common() | {
        "FINANCIAL_BEANCOUNT_WINDOWS_CERTIFICATE": "not base64!",
        "FINANCIAL_BEANCOUNT_WINDOWS_CERTIFICATE_PASSWORD": "secret",
        "FINANCIAL_BEANCOUNT_WINDOWS_TIMESTAMP_URL": "http://timestamp.example.test",
        "FINANCIAL_BEANCOUNT_WINDOWS_PUBLISHER": "Example Publisher",
    }
    with pytest.raises(ValueError, match="valid base64"):
        validate_credentials("windows", environment)
    environment["FINANCIAL_BEANCOUNT_WINDOWS_CERTIFICATE"] = base64.b64encode(b"pfx").decode()
    with pytest.raises(ValueError, match="HTTPS"):
        validate_credentials("windows", environment)


def test_signed_workflow_runs_preflight_without_exposing_values() -> None:
    workflow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/desktop-build.yml"
    ).read_text(encoding="utf-8")
    assert "Preflight protected release configuration" in workflow
    assert "validate_release_credentials.py --platform ${{ matrix.platform }}" in workflow
    assert "if: ${{ inputs.signed_release }}" in workflow
