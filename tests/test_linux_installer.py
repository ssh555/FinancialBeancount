from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_linux_appimage_metadata_and_lifecycle_are_defined() -> None:
    desktop = (ROOT / "installer/linux/FinancialBeancount.desktop").read_text(encoding="utf-8")
    build = (ROOT / "installer/linux/build_appimage.sh").read_text(encoding="utf-8")
    smoke = (ROOT / "installer/linux/smoke_appimage.sh").read_text(encoding="utf-8")

    assert "Exec=FinancialBeancount" in desktop
    assert "Categories=Office;Finance;" in desktop
    assert "usr/lib/financial-beancount" in build
    assert 'ARCH="$appimage_arch"' in build
    assert "--appimage-extract" in smoke
    assert "ledger-must-survive" in smoke
    assert "mv -f" in smoke


def test_linux_signing_is_fail_closed_and_fingerprint_pinned() -> None:
    signing = (ROOT / "installer/linux/sign.sh").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/desktop-build.yml").read_text(encoding="utf-8")

    assert "FINANCIAL_BEANCOUNT_LINUX_SIGNING_KEY is required" in signing
    assert '[[ "$actual" == "$expected" ]]' in signing
    assert "gpgv --keyring" in signing
    assert "FINANCIAL_BEANCOUNT_LINUX_SIGNING_FINGERPRINT" in workflow
    assert "Verify signed Linux release gate" in workflow
