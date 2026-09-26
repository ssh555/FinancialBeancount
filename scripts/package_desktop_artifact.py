"""Create a deterministic desktop release archive and its SHA-256 manifest."""

from __future__ import annotations

import argparse
import base64
import hashlib
import os
import zipfile
from pathlib import Path


def package_directory(
    source: Path,
    output: Path,
    *,
    signing_key: str | None = None,
    trusted_public_key: str | None = None,
    require_signature: bool = False,
) -> str:
    """Archive *source* and return the lowercase SHA-256 digest."""
    if not source.is_dir():
        raise ValueError(f"desktop build directory does not exist: {source}")
    if output.suffix.lower() != ".zip":
        raise ValueError("release archive must use the .zip extension")

    output.parent.mkdir(parents=True, exist_ok=True)
    files = sorted(
        (path for path in source.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(source).as_posix().casefold(),
    )
    if not files:
        raise ValueError(f"desktop build directory is empty: {source}")

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            info = zipfile.ZipInfo(path.relative_to(source.parent).as_posix())
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (path.stat().st_mode & 0xFFFF) << 16
            archive.writestr(info, path.read_bytes(), compresslevel=9)

    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    checksum_path = output.with_suffix(f"{output.suffix}.sha256")
    checksum_path.write_text(f"{digest}  {output.name}\n", encoding="utf-8", newline="\n")
    if signing_key:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        try:
            private_bytes = base64.b64decode(signing_key, validate=True)
            if len(private_bytes) != 32:
                raise ValueError
            private_key = Ed25519PrivateKey.from_private_bytes(private_bytes)
        except ValueError as exc:
            raise ValueError("release signing key must be a base64 Ed25519 private key") from exc
        if trusted_public_key:
            from cryptography.hazmat.primitives import serialization

            derived = private_key.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw
            )
            try:
                trusted = base64.b64decode(trusted_public_key, validate=True)
            except ValueError as exc:
                raise ValueError("trusted public key must be valid base64") from exc
            if derived != trusted:
                raise ValueError("release private key does not match the trusted public key")
        signature = private_key.sign(checksum_path.read_bytes())
        checksum_path.with_suffix(f"{checksum_path.suffix}.sig").write_text(
            base64.b64encode(signature).decode("ascii") + "\n", encoding="ascii", newline="\n"
        )
    elif require_signature:
        raise ValueError("a signing key is required for a signed release")
    return digest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-signature", action="store_true")
    args = parser.parse_args()
    digest = package_directory(
        args.source.resolve(),
        args.output.resolve(),
        signing_key=os.environ.get("FINANCIAL_BEANCOUNT_RELEASE_SIGNING_KEY"),
        trusted_public_key=os.environ.get("FINANCIAL_BEANCOUNT_UPDATE_PUBLIC_KEY"),
        require_signature=args.require_signature,
    )
    print(f"{args.output}: {digest}")


if __name__ == "__main__":
    main()
