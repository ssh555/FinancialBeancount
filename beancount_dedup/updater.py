"""Read-only GitHub Release update discovery for the desktop application."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from ._release_public_key import BUILTIN_UPDATE_PUBLIC_KEY

DEFAULT_RELEASES_API = "https://api.github.com/repos/ssh555/FinancialBeancount/releases/latest"
UPDATE_API_ENV = "FINANCIAL_BEANCOUNT_UPDATE_API"
DISABLED_VALUES = {"0", "disabled", "false", "off", "none"}
MAX_METADATA_BYTES = 2 * 1024 * 1024
MAX_CHECKSUM_BYTES = 4096
MAX_SIGNATURE_BYTES = 4096
MAX_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
MAX_ARCHIVE_MEMBERS = 10_000
MAX_UNCOMPRESSED_BYTES = 4 * 1024 * 1024 * 1024


class UpdateCheckError(RuntimeError):
    """Raised when update metadata cannot be safely interpreted."""


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    download_url: str
    size: int


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    title: str
    notes: str
    publisher: str
    published_at: str
    release_url: str
    archive: ReleaseAsset
    checksum: ReleaseAsset
    signature: ReleaseAsset


@dataclass(frozen=True)
class StagedUpdate:
    version: str
    archive_path: Path
    checksum_path: Path
    signature_path: Path
    sha256: str


@dataclass(frozen=True)
class PreparedUpdate:
    version: str
    application_directory: Path
    plan_path: Path


def configured_releases_api(environment: dict[str, str] | None = None) -> str | None:
    """Return the configured metadata URL, or ``None`` when checks are disabled."""
    value = (environment or os.environ).get(UPDATE_API_ENV, DEFAULT_RELEASES_API).strip()
    if value.lower() in DISABLED_VALUES:
        return None
    if not value.startswith("https://"):
        raise UpdateCheckError("更新源必须使用 HTTPS")
    return value


def platform_asset_suffix(system: str | None = None, machine: str | None = None) -> str:
    """Return the release asset platform/architecture suffix for this computer."""
    system_name = (system or platform.system()).lower()
    machine_name = (machine or platform.machine()).lower()
    systems = {"windows": "windows", "darwin": "macos", "linux": "linux"}
    architectures = {
        "amd64": "X64",
        "x86_64": "X64",
        "arm64": "ARM64",
        "aarch64": "ARM64",
    }
    try:
        return f"{systems[system_name]}-{architectures[machine_name]}"
    except KeyError as exc:
        raise UpdateCheckError(f"暂不支持当前平台：{system_name}/{machine_name}") from exc


def parse_version(value: str) -> tuple[int, ...]:
    """Parse a stable numeric release tag such as ``v1.2.3``."""
    match = re.fullmatch(r"v?(\d+(?:\.\d+)*)", value.strip())
    if not match:
        raise UpdateCheckError(f"无法识别发布版本：{value}")
    parts = [int(part) for part in match.group(1).split(".")]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def check_for_update(
    current_version: str,
    *,
    api_url: str | None = None,
    system: str | None = None,
    machine: str | None = None,
    timeout: float = 5.0,
) -> UpdateInfo | None:
    """Return compatible newer release metadata without downloading an artifact."""
    source = api_url if api_url is not None else configured_releases_api()
    if source is None:
        return None
    request = urllib.request.Request(
        source,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"FinancialBeancount/{current_version}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw_payload = response.read(MAX_METADATA_BYTES + 1)
            if len(raw_payload) > MAX_METADATA_BYTES:
                raise UpdateCheckError("更新信息超过安全大小限制")
            payload = json.loads(raw_payload.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, urllib.error.HTTPError) as exc:
        raise UpdateCheckError(f"无法获取更新信息：{exc}") from exc
    return evaluate_release(payload, current_version, system=system, machine=machine)


def evaluate_release(
    payload: Any,
    current_version: str,
    *,
    system: str | None = None,
    machine: str | None = None,
) -> UpdateInfo | None:
    """Validate GitHub metadata and select a compatible archive/checksum pair."""
    if not isinstance(payload, dict):
        raise UpdateCheckError("更新信息格式无效")
    if payload.get("draft") or payload.get("prerelease"):
        return None
    tag = payload.get("tag_name")
    if not isinstance(tag, str):
        raise UpdateCheckError("更新信息缺少版本号")
    if parse_version(tag) <= parse_version(current_version):
        return None

    suffix = platform_asset_suffix(system, machine)
    archive_name = f"FinancialBeancount-{suffix}.zip"
    checksum_name = f"{archive_name}.sha256"
    signature_name = f"{checksum_name}.sig"
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise UpdateCheckError("更新信息缺少下载文件")
    indexed = {
        asset.get("name"): asset
        for asset in assets
        if isinstance(asset, dict) and isinstance(asset.get("name"), str)
    }
    if archive_name not in indexed or checksum_name not in indexed or signature_name not in indexed:
        raise UpdateCheckError(f"此版本没有适用于 {suffix} 的完整更新文件")

    author = payload.get("author")
    publisher = author.get("login", "unknown") if isinstance(author, dict) else "unknown"
    return UpdateInfo(
        version=tag.removeprefix("v"),
        title=str(payload.get("name") or tag),
        notes=str(payload.get("body") or ""),
        publisher=str(publisher),
        published_at=str(payload.get("published_at") or ""),
        release_url=_required_https_url(payload, "html_url"),
        archive=_asset(indexed[archive_name]),
        checksum=_asset(indexed[checksum_name]),
        signature=_asset(indexed[signature_name]),
    )


def download_and_verify_update(
    update: UpdateInfo,
    staging_root: Path,
    *,
    timeout: float = 30.0,
    public_key: str | bytes | None = None,
) -> StagedUpdate:
    """Verify the signed checksum, then download and hash the approved update."""
    if update.archive.size <= 0 or update.archive.size > MAX_ARCHIVE_BYTES:
        raise UpdateCheckError("更新文件大小无效或超过安全限制")
    stage_directory = staging_root / update.version
    stage_directory.mkdir(parents=True, exist_ok=True)
    archive_path = stage_directory / update.archive.name
    checksum_path = stage_directory / update.checksum.name
    signature_path = stage_directory / update.signature.name
    temporary_path = archive_path.with_suffix(f"{archive_path.suffix}.part")

    checksum_bytes = _download_small_asset(update.checksum, MAX_CHECKSUM_BYTES, timeout, "校验文件")
    signature_bytes = _download_small_asset(
        update.signature, MAX_SIGNATURE_BYTES, timeout, "签名文件"
    )
    _verify_checksum_signature(checksum_bytes, signature_bytes, public_key)
    expected = _parse_checksum(checksum_bytes, update.checksum.name)
    checksum_path.write_bytes(checksum_bytes)
    signature_path.write_bytes(signature_bytes)
    if archive_path.is_file() and _sha256_file(archive_path) == expected:
        return StagedUpdate(update.version, archive_path, checksum_path, signature_path, expected)

    digest = hashlib.sha256()
    received = 0
    request = _asset_request(update.archive.download_url)
    try:
        with (
            urllib.request.urlopen(request, timeout=timeout) as response,
            temporary_path.open("wb") as stream,
        ):
            while chunk := response.read(DOWNLOAD_CHUNK_BYTES):
                received += len(chunk)
                if received > update.archive.size or received > MAX_ARCHIVE_BYTES:
                    raise UpdateCheckError("下载的更新文件超过声明大小")
                digest.update(chunk)
                stream.write(chunk)
        if received != update.archive.size:
            raise UpdateCheckError("下载的更新文件大小与发布信息不一致")
        actual = digest.hexdigest()
        if actual != expected:
            raise UpdateCheckError("更新文件 SHA-256 校验失败")
        temporary_path.replace(archive_path)
    except (OSError, urllib.error.HTTPError) as exc:
        raise UpdateCheckError(f"无法下载更新文件：{exc}") from exc
    finally:
        temporary_path.unlink(missing_ok=True)
    return StagedUpdate(update.version, archive_path, checksum_path, signature_path, expected)


def prepare_update_installation(staged: StagedUpdate) -> PreparedUpdate:
    """Safely extract a verified update and write a helper-consumable plan."""
    stage_directory = staged.archive_path.parent.resolve()
    extraction_directory = stage_directory / "unpacked"
    temporary_directory = stage_directory / "unpacked.part"
    _remove_scoped_directory(temporary_directory, stage_directory)
    temporary_directory.mkdir()
    try:
        with zipfile.ZipFile(staged.archive_path) as archive:
            members = archive.infolist()
            if not members or len(members) > MAX_ARCHIVE_MEMBERS:
                raise UpdateCheckError("更新压缩包文件数量无效或超过安全限制")
            total_size = sum(member.file_size for member in members)
            if total_size > MAX_UNCOMPRESSED_BYTES:
                raise UpdateCheckError("更新压缩包解压大小超过安全限制")
            for member in members:
                relative = PurePosixPath(member.filename)
                if relative.is_absolute() or ".." in relative.parts:
                    raise UpdateCheckError("更新压缩包包含不安全路径")
                mode = member.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise UpdateCheckError("更新压缩包不允许包含符号链接")
                destination = temporary_directory.joinpath(*relative.parts).resolve()
                if not destination.is_relative_to(temporary_directory.resolve()):
                    raise UpdateCheckError("更新压缩包包含越界路径")
                if member.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as source, destination.open("wb") as target:
                        shutil.copyfileobj(source, target, DOWNLOAD_CHUNK_BYTES)

        application_directory = temporary_directory / "FinancialBeancount"
        if not application_directory.is_dir():
            raise UpdateCheckError("更新压缩包缺少 FinancialBeancount 应用目录")
        _remove_scoped_directory(extraction_directory, stage_directory)
        temporary_directory.replace(extraction_directory)
        application_directory = extraction_directory / "FinancialBeancount"
        plan_path = stage_directory / "install-plan.json"
        plan_path.write_text(
            json.dumps(
                {
                    "format_version": 1,
                    "version": staged.version,
                    "archive": str(staged.archive_path),
                    "application_directory": str(application_directory),
                    "sha256": staged.sha256,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return PreparedUpdate(staged.version, application_directory, plan_path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise UpdateCheckError(f"无法准备更新安装文件：{exc}") from exc
    finally:
        _remove_scoped_directory(temporary_directory, stage_directory)


def _remove_scoped_directory(path: Path, parent: Path) -> None:
    resolved = path.resolve()
    if resolved == parent.resolve() or not resolved.is_relative_to(parent.resolve()):
        raise UpdateCheckError("拒绝清理更新暂存区以外的路径")
    if resolved.exists():
        shutil.rmtree(resolved)


def _download_small_asset(asset: ReleaseAsset, maximum: int, timeout: float, label: str) -> bytes:
    try:
        with urllib.request.urlopen(
            _asset_request(asset.download_url), timeout=timeout
        ) as response:
            raw_value = bytes(response.read(maximum + 1))
    except (OSError, urllib.error.HTTPError) as exc:
        raise UpdateCheckError(f"无法下载更新{label}：{exc}") from exc
    if len(raw_value) > maximum:
        raise UpdateCheckError(f"更新{label}超过安全大小限制")
    return raw_value


def _parse_checksum(raw_value: bytes, checksum_name: str) -> str:
    try:
        fields = raw_value.decode("utf-8").strip().split()
    except UnicodeError as exc:
        raise UpdateCheckError("更新校验文件编码无效") from exc
    if len(fields) != 2 or fields[1].lstrip("*") != checksum_name.removesuffix(".sha256"):
        raise UpdateCheckError("更新校验文件格式或文件名不匹配")
    digest = fields[0].lower()
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise UpdateCheckError("更新校验文件中的 SHA-256 无效")
    return digest


def _verify_checksum_signature(
    checksum: bytes, encoded_signature: bytes, public_key: str | bytes | None
) -> None:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    configured = (
        public_key
        or BUILTIN_UPDATE_PUBLIC_KEY
        or os.environ.get("FINANCIAL_BEANCOUNT_UPDATE_PUBLIC_KEY", "")
    )
    if not configured:
        raise UpdateCheckError("应用未配置可信更新公钥，拒绝安装更新")
    try:
        key_bytes = base64.b64decode(configured, validate=True)
        signature = base64.b64decode(encoded_signature.strip(), validate=True)
        if len(key_bytes) != 32 or len(signature) != 64:
            raise ValueError
        Ed25519PublicKey.from_public_bytes(key_bytes).verify(signature, checksum)
    except (ValueError, InvalidSignature) as exc:
        raise UpdateCheckError("更新签名验证失败，无法确认发布者身份") from exc


def _asset_request(url: str) -> urllib.request.Request:
    return urllib.request.Request(
        url,
        headers={"Accept": "application/octet-stream", "User-Agent": "FinancialBeancount-updater"},
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(DOWNLOAD_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _asset(value: dict[str, Any]) -> ReleaseAsset:
    return ReleaseAsset(
        name=_required_string(value, "name"),
        download_url=_required_https_url(value, "browser_download_url"),
        size=int(value.get("size", 0)),
    )


def _required_string(value: dict[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise UpdateCheckError(f"更新信息缺少字段：{key}")
    return result


def _required_https_url(value: dict[str, Any], key: str) -> str:
    result = _required_string(value, key)
    if not result.startswith("https://"):
        raise UpdateCheckError(f"更新信息中的 {key} 必须使用 HTTPS")
    return result
