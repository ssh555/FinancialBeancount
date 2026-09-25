"""Fail-closed release readiness report for desktop artifacts."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class GateCheck:
    name: str
    passed: bool
    detail: str


def inspect_release(
    repository: Path,
    artifacts: Path,
    *,
    mode: str,
    platform_name: str,
    architecture: str,
) -> list[GateCheck]:
    """Inspect one platform's artifacts without changing the repository."""

    checks: list[GateCheck] = []
    pyproject_text = (repository / "pyproject.toml").read_text(encoding="utf-8")
    project_match = re.search(r'^version = "([^"]+)"$', pyproject_text, re.MULTILINE)
    project_version = project_match.group(1) if project_match else ""
    init_text = (repository / "beancount_dedup" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "([^"]+)"$', init_text, re.MULTILINE)
    package_version = match.group(1) if match else ""
    checks.append(
        GateCheck(
            "version-consistency",
            bool(package_version) and package_version == project_version,
            f"pyproject={project_version}, package={package_version or 'missing'}",
        )
    )
    for document in ("docs/PRIVACY.md", "docs/RELEASE.md", "docs/ROADMAP.md"):
        checks.append(
            GateCheck(
                f"document:{document}",
                (repository / document).is_file(),
                document,
            )
        )

    suffix = f"{platform_name}-{architecture}"
    archive = artifacts / f"FinancialBeancount-{suffix}.zip"
    checksum = archive.with_suffix(".zip.sha256")
    checks.extend(_archive_checks(archive, checksum))

    if mode == "release":
        signature = checksum.with_suffix(".sha256.sig")
        public_key = _embedded_public_key(repository)
        checks.append(
            GateCheck(
                "embedded-update-public-key",
                _valid_public_key(public_key),
                "valid embedded Ed25519 public key" if public_key else "public key is empty",
            )
        )
        checks.append(_signed_manifest_check(checksum, signature, public_key))
        installer = _native_installer(artifacts, suffix, platform_name)
        checks.append(GateCheck("native-installer", installer.is_file(), str(installer)))
        checks.append(_signature_evidence_check(installer))
    return checks


def _archive_checks(archive: Path, checksum: Path) -> list[GateCheck]:
    archive_exists = archive.is_file()
    checksum_exists = checksum.is_file()
    digest_matches = False
    if archive_exists and checksum_exists:
        fields = checksum.read_text(encoding="utf-8").strip().split()
        digest_matches = (
            len(fields) == 2
            and fields[1].lstrip("*") == archive.name
            and fields[0].lower() == hashlib.sha256(archive.read_bytes()).hexdigest()
        )
    return [
        GateCheck("desktop-archive", archive_exists, str(archive)),
        GateCheck("archive-checksum", checksum_exists and digest_matches, str(checksum)),
    ]


def _embedded_public_key(repository: Path) -> str:
    text = (repository / "beancount_dedup" / "_release_public_key.py").read_text(encoding="utf-8")
    match = re.search(r'^BUILTIN_UPDATE_PUBLIC_KEY = "([^"]*)"$', text, re.MULTILINE)
    return match.group(1) if match else ""


def _valid_public_key(value: str) -> bool:
    try:
        return len(base64.b64decode(value, validate=True)) == 32
    except ValueError:
        return False


def _signed_manifest_check(checksum: Path, signature: Path, public_key: str) -> GateCheck:
    valid = False
    if checksum.is_file() and signature.is_file() and _valid_public_key(public_key):
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        try:
            key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key, validate=True))
            encoded = signature.read_bytes().strip()
            key.verify(base64.b64decode(encoded, validate=True), checksum.read_bytes())
            valid = True
        except (ValueError, InvalidSignature):
            valid = False
    return GateCheck("signed-update-manifest", valid, str(signature))


def _native_installer(artifacts: Path, suffix: str, platform_name: str) -> Path:
    extensions = {"windows": ".msi", "macos": ".dmg", "linux": ".AppImage"}
    extension = extensions.get(platform_name, ".installer")
    return artifacts / f"FinancialBeancount-{suffix}{extension}"


def _signature_evidence_check(installer: Path) -> GateCheck:
    evidence = installer.with_suffix(f"{installer.suffix}.signature.json")
    valid = False
    if installer.is_file() and evidence.is_file():
        try:
            payload = json.loads(evidence.read_text(encoding="utf-8"))
            valid = (
                payload.get("verified") is True
                and payload.get("artifact_sha256")
                == hashlib.sha256(installer.read_bytes()).hexdigest()
            )
        except (OSError, json.JSONDecodeError):
            valid = False
    return GateCheck("os-signature-verification", valid, str(evidence))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--mode", choices=("preview", "release"), required=True)
    parser.add_argument("--platform", choices=("windows", "macos", "linux"), required=True)
    parser.add_argument("--architecture", required=True)
    args = parser.parse_args(argv)
    checks = inspect_release(
        args.repository.resolve(),
        args.artifacts.resolve(),
        mode=args.mode,
        platform_name=args.platform,
        architecture=args.architecture,
    )
    report = {
        "mode": args.mode,
        "ready": all(check.passed for check in checks),
        "checks": [asdict(check) for check in checks],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
