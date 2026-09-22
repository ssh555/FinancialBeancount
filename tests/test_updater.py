import json
import zipfile
from hashlib import sha256
from io import BytesIO
from unittest.mock import patch

import pytest
from beancount_dedup.updater import (
    DEFAULT_RELEASES_API,
    ReleaseAsset,
    StagedUpdate,
    UpdateCheckError,
    UpdateInfo,
    check_for_update,
    configured_releases_api,
    download_and_verify_update,
    evaluate_release,
    parse_version,
    platform_asset_suffix,
    prepare_update_installation,
)


def release_payload(version: str = "v0.3.0") -> dict:
    archive = "FinancialBeancount-windows-X64.zip"
    return {
        "tag_name": version,
        "name": "Desktop preview",
        "body": "Fixes and improvements",
        "draft": False,
        "prerelease": False,
        "published_at": "2026-09-22T00:00:00Z",
        "html_url": "https://github.com/ssh555/FinancialBeancount/releases/tag/v0.3.0",
        "author": {"login": "ssh555"},
        "assets": [
            {
                "name": archive,
                "browser_download_url": f"https://example.test/{archive}",
                "size": 10485760,
            },
            {
                "name": f"{archive}.sha256",
                "browser_download_url": f"https://example.test/{archive}.sha256",
                "size": 100,
            },
        ],
    }


def test_update_source_defaults_can_be_overridden_or_disabled() -> None:
    assert configured_releases_api({}) == DEFAULT_RELEASES_API
    assert configured_releases_api({"FINANCIAL_BEANCOUNT_UPDATE_API": "off"}) is None
    assert configured_releases_api(
        {"FINANCIAL_BEANCOUNT_UPDATE_API": "https://updates.example.test/latest"}
    ) == "https://updates.example.test/latest"
    with pytest.raises(UpdateCheckError, match="HTTPS"):
        configured_releases_api({"FINANCIAL_BEANCOUNT_UPDATE_API": "http://unsafe.test"})


@pytest.mark.parametrize(
    ("system", "machine", "expected"),
    [("Windows", "AMD64", "windows-X64"), ("Darwin", "arm64", "macos-ARM64")],
)
def test_platform_asset_suffix(system: str, machine: str, expected: str) -> None:
    assert platform_asset_suffix(system, machine) == expected


def test_evaluate_release_selects_newer_compatible_pair() -> None:
    update = evaluate_release(release_payload(), "0.2.0", system="Windows", machine="AMD64")

    assert update is not None
    assert update.version == "0.3.0"
    assert update.publisher == "ssh555"
    assert update.archive.size == 10485760
    assert update.checksum.name.endswith(".zip.sha256")


def test_evaluate_release_ignores_current_draft_and_prerelease() -> None:
    assert evaluate_release(release_payload("v0.2.0"), "0.2.0") is None
    assert evaluate_release(release_payload("v1.0.0"), "1.0") is None
    draft = release_payload()
    draft["draft"] = True
    assert evaluate_release(draft, "0.2.0") is None
    prerelease = release_payload()
    prerelease["prerelease"] = True
    assert evaluate_release(prerelease, "0.2.0") is None


def test_evaluate_release_requires_checksum_for_matching_archive() -> None:
    payload = release_payload()
    payload["assets"] = payload["assets"][:1]
    with pytest.raises(UpdateCheckError, match="完整更新文件"):
        evaluate_release(payload, "0.2.0", system="Windows", machine="AMD64")


def test_evaluate_release_rejects_insecure_download_url() -> None:
    payload = release_payload()
    payload["assets"][0]["browser_download_url"] = "http://unsafe.test/app.zip"
    with pytest.raises(UpdateCheckError, match="HTTPS"):
        evaluate_release(payload, "0.2.0", system="Windows", machine="AMD64")


def test_check_for_update_uses_timeout_and_identifying_headers() -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _size):
            return json.dumps(release_payload()).encode()

    with patch("urllib.request.urlopen", return_value=Response()) as urlopen:
        update = check_for_update(
            "0.2.0",
            api_url="https://updates.example.test/latest",
            system="Windows",
            machine="AMD64",
            timeout=2.5,
        )

    assert update is not None
    request = urlopen.call_args.args[0]
    assert request.headers["User-agent"] == "FinancialBeancount/0.2.0"
    assert urlopen.call_args.kwargs["timeout"] == 2.5


def test_download_and_verify_update_stages_matching_archive(tmp_path) -> None:
    content = b"verified desktop archive"
    digest = sha256(content).hexdigest()
    archive_name = "FinancialBeancount-windows-X64.zip"
    update = UpdateInfo(
        version="0.3.0",
        title="Preview",
        notes="",
        publisher="ssh555",
        published_at="2026-09-22T00:00:00Z",
        release_url="https://example.test/release",
        archive=ReleaseAsset(archive_name, "https://example.test/app.zip", len(content)),
        checksum=ReleaseAsset(
            f"{archive_name}.sha256", "https://example.test/app.zip.sha256", 100
        ),
    )
    checksum = BytesIO(f"{digest}  {archive_name}\n".encode())
    archive = BytesIO(content)

    with patch("urllib.request.urlopen", side_effect=[checksum, archive]):
        staged = download_and_verify_update(update, tmp_path, timeout=1)

    assert staged.archive_path.read_bytes() == content
    assert staged.sha256 == digest
    assert staged.checksum_path.read_text(encoding="utf-8") == f"{digest}  {archive_name}\n"
    assert not list(tmp_path.rglob("*.part"))


def test_download_and_verify_update_removes_partial_file_on_hash_failure(tmp_path) -> None:
    content = b"tampered"
    archive_name = "FinancialBeancount-windows-X64.zip"
    update = UpdateInfo(
        version="0.3.0",
        title="Preview",
        notes="",
        publisher="ssh555",
        published_at="",
        release_url="https://example.test/release",
        archive=ReleaseAsset(archive_name, "https://example.test/app.zip", len(content)),
        checksum=ReleaseAsset(f"{archive_name}.sha256", "https://example.test/sum", 100),
    )
    checksum = BytesIO(f"{'0' * 64}  {archive_name}\n".encode())

    with (
        patch("urllib.request.urlopen", side_effect=[checksum, BytesIO(content)]),
        pytest.raises(UpdateCheckError, match="SHA-256"),
    ):
        download_and_verify_update(update, tmp_path)

    assert not list(tmp_path.rglob("*.part"))
    assert not list(tmp_path.rglob("*.zip"))


def test_prepare_update_installation_extracts_valid_application(tmp_path) -> None:
    archive_path = tmp_path / "FinancialBeancount-windows-X64.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("FinancialBeancount/FinancialBeancount.exe", b"executable")
        archive.writestr("FinancialBeancount/_internal/app.txt", b"runtime")
    staged = StagedUpdate("0.3.0", archive_path, tmp_path / "sum", sha256(b"x").hexdigest())

    prepared = prepare_update_installation(staged)

    assert (prepared.application_directory / "FinancialBeancount.exe").read_bytes() == b"executable"
    plan = json.loads(prepared.plan_path.read_text(encoding="utf-8"))
    assert plan["version"] == "0.3.0"
    assert plan["application_directory"] == str(prepared.application_directory)


@pytest.mark.parametrize("member", ["../outside.txt", "/absolute.txt"])
def test_prepare_update_installation_rejects_path_traversal(tmp_path, member: str) -> None:
    archive_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(member, b"unsafe")
        archive.writestr("FinancialBeancount/app", b"application")
    staged = StagedUpdate("0.3.0", archive_path, tmp_path / "sum", "0" * 64)

    with pytest.raises(UpdateCheckError, match="不安全路径"):
        prepare_update_installation(staged)

    assert not (tmp_path.parent / "outside.txt").exists()
    assert not (tmp_path / "unpacked.part").exists()


@pytest.mark.parametrize("value", ["main", "v1.2-beta", ""])
def test_parse_version_rejects_non_stable_tags(value: str) -> None:
    with pytest.raises(UpdateCheckError):
        parse_version(value)
