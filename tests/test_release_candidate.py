from pathlib import Path

import pytest
from scripts.validate_release_candidate import validate_candidate


def _repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / "pyproject.toml").write_text(
        '[project]\nname = "financial-beancount"\nversion = "1.2.3"\n', encoding="utf-8"
    )
    return repository


def _assets(path: Path) -> None:
    path.mkdir()
    archives = [
        "FinancialBeancount-windows-X64.zip",
        "FinancialBeancount-macos-ARM64.zip",
        "FinancialBeancount-linux-X64.zip",
    ]
    native = [
        "FinancialBeancount-windows-X64.msi",
        "FinancialBeancount-macos-ARM64.dmg",
        "FinancialBeancount-linux-X64.AppImage",
    ]
    names = (
        archives
        + native
        + [
            suffix
            for archive in archives
            for suffix in (f"{archive}.sha256", f"{archive}.sha256.sig")
        ]
    )
    names += [f"{installer}.signature.json" for installer in native]
    names += [
        "FinancialBeancount-linux-X64.AppImage.asc",
        "FinancialBeancount-linux-release-keyring.gpg",
    ]
    for name in names:
        (path / name).write_bytes(b"asset")


def test_candidate_requires_exact_source_version_and_complete_assets(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    artifacts = tmp_path / "assets"
    _assets(artifacts)

    names = validate_candidate(repository, "v1.2.3", artifacts)

    assert len(names) == 17


@pytest.mark.parametrize("tag", ["1.2.3", "v1.2", "v1.2.4", "v1.2.3-rc1"])
def test_candidate_rejects_invalid_or_mismatched_tag(tmp_path: Path, tag: str) -> None:
    with pytest.raises(ValueError):
        validate_candidate(_repository(tmp_path), tag)


def test_candidate_rejects_incomplete_inventory(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    artifacts = tmp_path / "assets"
    _assets(artifacts)
    (artifacts / "FinancialBeancount-linux-X64.AppImage.asc").unlink()

    with pytest.raises(ValueError, match=r"AppImage\.asc"):
        validate_candidate(repository, "v1.2.3", artifacts)


def test_candidate_rejects_unexpected_asset(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    artifacts = tmp_path / "assets"
    _assets(artifacts)
    (artifacts / "unreviewed.bin").write_bytes(b"unexpected")

    with pytest.raises(ValueError, match="unexpected release assets"):
        validate_candidate(repository, "v1.2.3", artifacts)


def test_candidate_rejects_empty_asset(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    artifacts = tmp_path / "assets"
    _assets(artifacts)
    (artifacts / "FinancialBeancount-windows-X64.msi").write_bytes(b"")

    with pytest.raises(ValueError, match="must not be empty"):
        validate_candidate(repository, "v1.2.3", artifacts)


def test_workflow_creates_only_a_draft_after_signed_build() -> None:
    workflow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/release-candidate.yml"
    ).read_text(encoding="utf-8")

    assert "signed_release: true" in workflow
    assert "needs: signed-build" in workflow
    assert "--draft" in workflow
    assert "contents: write" in workflow
    assert "release tag already exists" in workflow
    assert "--prerelease" not in workflow

    desktop_workflow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/desktop-build.yml"
    ).read_text(encoding="utf-8")
    assert "Verify signed macOS DMG replacement and data preservation" in desktop_workflow
    assert "matrix.platform == 'windows' && !inputs.signed_release" not in desktop_workflow
