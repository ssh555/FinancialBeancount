"""Validate release credential presence and public metadata without printing secrets."""

from __future__ import annotations

import argparse
import base64
import os
import re
import sys
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from collections.abc import Mapping


COMMON_SECRETS = ("FINANCIAL_BEANCOUNT_RELEASE_SIGNING_KEY",)
COMMON_VARIABLES = ("FINANCIAL_BEANCOUNT_UPDATE_PUBLIC_KEY",)
PLATFORM_FIELDS = {
    "windows": {
        "secrets": (
            "FINANCIAL_BEANCOUNT_WINDOWS_CERTIFICATE",
            "FINANCIAL_BEANCOUNT_WINDOWS_CERTIFICATE_PASSWORD",
        ),
        "variables": (
            "FINANCIAL_BEANCOUNT_WINDOWS_TIMESTAMP_URL",
            "FINANCIAL_BEANCOUNT_WINDOWS_PUBLISHER",
        ),
    },
    "macos": {
        "secrets": (
            "FINANCIAL_BEANCOUNT_MACOS_CERTIFICATE",
            "FINANCIAL_BEANCOUNT_MACOS_CERTIFICATE_PASSWORD",
            "FINANCIAL_BEANCOUNT_APPLE_ID",
            "FINANCIAL_BEANCOUNT_APPLE_APP_PASSWORD",
        ),
        "variables": (
            "FINANCIAL_BEANCOUNT_MACOS_SIGNING_IDENTITY",
            "FINANCIAL_BEANCOUNT_APPLE_TEAM_ID",
        ),
    },
    "linux": {
        "secrets": ("FINANCIAL_BEANCOUNT_LINUX_SIGNING_KEY",),
        "variables": ("FINANCIAL_BEANCOUNT_LINUX_SIGNING_FINGERPRINT",),
    },
}


def validate_credentials(platform_name: str, environment: Mapping[str, str]) -> list[str]:
    """Return validated field names; never return or include secret values in errors."""
    if platform_name not in PLATFORM_FIELDS:
        raise ValueError(f"unsupported release platform: {platform_name}")
    required = (
        *COMMON_SECRETS,
        *COMMON_VARIABLES,
        *PLATFORM_FIELDS[platform_name]["secrets"],
        *PLATFORM_FIELDS[platform_name]["variables"],
    )
    missing = [name for name in required if not environment.get(name, "").strip()]
    if missing:
        raise ValueError("missing release configuration: " + ", ".join(missing))

    _base64_length(environment, "FINANCIAL_BEANCOUNT_RELEASE_SIGNING_KEY", 32)
    _base64_length(environment, "FINANCIAL_BEANCOUNT_UPDATE_PUBLIC_KEY", 32)
    if platform_name == "windows":
        _nonempty_base64(environment, "FINANCIAL_BEANCOUNT_WINDOWS_CERTIFICATE")
        timestamp = environment["FINANCIAL_BEANCOUNT_WINDOWS_TIMESTAMP_URL"]
        parsed = urlparse(timestamp)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("FINANCIAL_BEANCOUNT_WINDOWS_TIMESTAMP_URL must be an HTTPS URL")
    elif platform_name == "macos":
        _nonempty_base64(environment, "FINANCIAL_BEANCOUNT_MACOS_CERTIFICATE")
        if not re.fullmatch(r"[A-Z0-9]{10}", environment["FINANCIAL_BEANCOUNT_APPLE_TEAM_ID"]):
            raise ValueError(
                "FINANCIAL_BEANCOUNT_APPLE_TEAM_ID must contain 10 uppercase characters"
            )
        if (
            "Developer ID Application:"
            not in environment["FINANCIAL_BEANCOUNT_MACOS_SIGNING_IDENTITY"]
        ):
            raise ValueError(
                "FINANCIAL_BEANCOUNT_MACOS_SIGNING_IDENTITY must name a Developer ID Application identity"
            )
    else:
        _nonempty_base64(environment, "FINANCIAL_BEANCOUNT_LINUX_SIGNING_KEY")
        fingerprint = environment["FINANCIAL_BEANCOUNT_LINUX_SIGNING_FINGERPRINT"]
        if not re.fullmatch(r"[0-9A-Fa-f]{40}", fingerprint.replace(" ", "")):
            raise ValueError(
                "FINANCIAL_BEANCOUNT_LINUX_SIGNING_FINGERPRINT must contain 40 hexadecimal characters"
            )
    return list(required)


def _base64_length(environment: Mapping[str, str], name: str, expected: int) -> None:
    decoded = _decode_base64(environment, name)
    if len(decoded) != expected:
        raise ValueError(f"{name} must decode to exactly {expected} bytes")


def _nonempty_base64(environment: Mapping[str, str], name: str) -> None:
    if not _decode_base64(environment, name):
        raise ValueError(f"{name} must decode to non-empty data")


def _decode_base64(environment: Mapping[str, str], name: str) -> bytes:
    try:
        return base64.b64decode(environment[name], validate=True)
    except (KeyError, ValueError) as exc:
        raise ValueError(f"{name} must be valid base64") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=tuple(PLATFORM_FIELDS), required=True)
    args = parser.parse_args(argv)
    try:
        validated = validate_credentials(args.platform, os.environ)
    except ValueError as exc:
        print(f"release credential preflight failed: {exc}", file=sys.stderr)
        return 1
    print(f"release credential preflight passed for {args.platform}: {len(validated)} fields")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
