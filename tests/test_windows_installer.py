from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
PRODUCT = ROOT / "installer" / "windows" / "Product.wxs"
BUILD_SCRIPT = ROOT / "installer" / "windows" / "build.ps1"
SMOKE_SCRIPT = ROOT / "installer" / "windows" / "smoke_upgrade.ps1"
NS = {"w": "http://schemas.microsoft.com/wix/2006/wi"}


def _product_tree() -> ElementTree.Element:
    return ElementTree.parse(PRODUCT).getroot()


def test_windows_installer_is_per_user_and_major_upgrade_capable() -> None:
    root = _product_tree()
    product = root.find("w:Product", NS)
    assert product is not None
    assert product.attrib["Id"] == "*"
    assert product.attrib["Version"] == "$(var.ProductVersion)"
    assert product.attrib["UpgradeCode"] == "6DDB14D2-AC47-4FB6-A916-412544FE96D2"
    package = product.find("w:Package", NS)
    assert package is not None
    assert package.attrib["InstallScope"] == "perUser"
    upgrade = product.find("w:MajorUpgrade", NS)
    assert upgrade is not None
    assert upgrade.attrib["AllowSameVersionUpgrades"] == "yes"
    assert upgrade.attrib["Schedule"] == "afterInstallInitialize"


def test_installer_files_are_separate_from_persistent_ledger_directory() -> None:
    root = _product_tree()
    install = root.find(".//w:Directory[@Id='INSTALLFOLDER']", NS)
    assert install is not None
    assert install.attrib["Name"] == "FinancialBeancount"
    parent = root.find(".//w:Directory[@Id='LocalProgramsFolder']", NS)
    assert parent is not None
    assert parent.attrib["Name"] == "Programs"
    assert not root.findall(".//w:RemoveFolder[@Id='FinancialBeancountData']", NS)


def test_installer_exposes_start_menu_shortcut_and_complete_payload() -> None:
    root = _product_tree()
    shortcut = root.find(".//w:Shortcut", NS)
    assert shortcut is not None
    assert shortcut.attrib["Target"] == "[INSTALLFOLDER]FinancialBeancount.exe"
    assert root.find(".//w:ComponentGroupRef[@Id='ApplicationFiles']", NS) is not None


def test_build_script_harvests_payload_with_stable_component_guids() -> None:
    script = BUILD_SCRIPT.read_text(encoding="utf-8")
    assert "heat.exe dir" in script
    assert "-ag" in script
    assert "-gg" not in script
    assert "-sreg" in script
    assert "candle.exe -nologo -arch x64" in script
    assert "& light.exe @lightArguments" in script
    for expected_ice in ("ICE38", "ICE61", "ICE64", "ICE91"):
        assert f'"-sice:{expected_ice}"' in script
    assert '"-sval"' in script
    assert "[switch]$SkipValidation" in script
    assert "if ($SkipValidation)" in script
    assert '@("-sval")' in script
    assert "FinancialBeancount.exe" in script


def test_upgrade_smoke_preserves_user_data_through_upgrade_and_uninstall() -> None:
    script = SMOKE_SCRIPT.read_text(encoding="utf-8")
    assert 'Join-Path $env:LOCALAPPDATA "FinancialBeancount"' in script
    assert 'Join-Path $env:LOCALAPPDATA "Programs\\FinancialBeancount' in script
    assert 'Version = "0.0.1"' in script
    assert "SkipValidation = $SkipValidation" in script
    assert 'Invoke-Msi -Arguments @("/i", $previousMsi' in script
    assert 'Invoke-Msi -Arguments @("/i", $currentMsiPath' in script
    assert 'Invoke-Msi -Arguments @("/x", $currentMsiPath' in script
    assert "major upgrade modified per-user ledger data" in script
    assert "MSI uninstall removed or modified per-user ledger data" in script
    assert "Remove-TemporaryDirectory" in script
    assert "Wait-PathState" in script
    assert "$currentInstalled = $false" in script
