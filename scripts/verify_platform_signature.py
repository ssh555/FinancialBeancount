"""Verify a native installer with the host OS and emit hash-bound release evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def verify_installer(
    installer: Path,
    *,
    platform_name: str,
    expected_identity: str,
    detached_signature: Path | None = None,
    keyring: Path | None = None,
    runner: Runner | None = None,
) -> dict[str, Any]:
    """Return evidence only after native verification and publisher pinning succeed."""

    if not installer.is_file():
        raise ValueError(f"installer does not exist: {installer}")
    identity = expected_identity.strip()
    if not identity:
        raise ValueError("expected signing identity is required")
    execute = runner or _run
    if platform_name == "windows":
        command = ["signtool", "verify", "/pa", "/tw", "/v", str(installer)]
        output = _successful_output(execute, command)
        if identity.casefold() not in output.casefold():
            raise ValueError("verified Windows signature does not match the expected publisher")
        verifier = "signtool verify /pa /tw"
    elif platform_name == "macos":
        _successful_output(
            execute, ["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(installer)]
        )
        output = _successful_output(
            execute, ["spctl", "--assess", "--type", "open", "--verbose=4", str(installer)]
        )
        if identity.casefold() not in output.casefold():
            raise ValueError("verified macOS signature does not match the expected publisher")
        verifier = "codesign --verify + spctl --assess"
    elif platform_name == "linux":
        if detached_signature is None or keyring is None:
            raise ValueError("Linux verification requires a detached signature and trusted keyring")
        output = _successful_output(
            execute,
            [
                "gpgv",
                "--status-fd",
                "1",
                "--keyring",
                str(keyring),
                str(detached_signature),
                str(installer),
            ],
        )
        valid_fingerprints = [
            line.split()[2]
            for line in output.splitlines()
            if line.startswith("[GNUPG:] VALIDSIG ") and len(line.split()) > 2
        ]
        normalized = identity.replace(" ", "").upper()
        if normalized not in {fingerprint.upper() for fingerprint in valid_fingerprints}:
            raise ValueError("verified Linux signature does not match the expected fingerprint")
        verifier = "gpgv detached signature"
    else:
        raise ValueError(f"unsupported platform: {platform_name}")

    return {
        "schema": 1,
        "verified": True,
        "platform": platform_name,
        "artifact_name": installer.name,
        "artifact_sha256": hashlib.sha256(installer.read_bytes()).hexdigest(),
        "identity": identity,
        "verifier": verifier,
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }


def _successful_output(runner: Runner, command: Sequence[str]) -> str:
    result = runner(command)
    output = f"{result.stdout or ''}\n{result.stderr or ''}"
    if result.returncode != 0:
        raise ValueError(f"signature verification failed ({result.returncode}): {output.strip()}")
    return output


def _run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--platform", choices=("windows", "macos", "linux"), required=True)
    parser.add_argument("--expected-identity", required=True)
    parser.add_argument("--detached-signature", type=Path)
    parser.add_argument("--keyring", type=Path)
    args = parser.parse_args(argv)
    installer = args.installer.resolve()
    try:
        evidence = verify_installer(
            installer,
            platform_name=args.platform,
            expected_identity=args.expected_identity,
            detached_signature=args.detached_signature,
            keyring=args.keyring,
        )
        evidence_path = installer.with_suffix(f"{installer.suffix}.signature.json")
        evidence_path.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except (OSError, ValueError) as exc:
        print(json.dumps({"verified": False, "error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
