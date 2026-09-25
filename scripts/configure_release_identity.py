"""Inject and validate the public Ed25519 update key before an official build."""

from __future__ import annotations

import argparse
import base64
import os
from pathlib import Path


def configure(public_key: str, destination: Path) -> None:
    try:
        decoded = base64.b64decode(public_key, validate=True)
    except ValueError as exc:
        raise ValueError("public key must be valid base64") from exc
    if len(decoded) != 32:
        raise ValueError("public key must contain exactly 32 Ed25519 bytes")
    destination.write_text(
        '"""Build-time trusted update identity."""\n\n'
        f'BUILTIN_UPDATE_PUBLIC_KEY = "{public_key}"\n',
        encoding="utf-8",
        newline="\n",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-key")
    parser.add_argument(
        "--destination", type=Path, default=Path("beancount_dedup/_release_public_key.py")
    )
    args = parser.parse_args()
    public_key = args.public_key or os.environ.get("FINANCIAL_BEANCOUNT_UPDATE_PUBLIC_KEY", "")
    if not public_key:
        parser.error("a public key is required")
    configure(public_key, args.destination)


if __name__ == "__main__":
    main()
