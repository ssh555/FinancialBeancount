"""Create a deterministic desktop release archive and its SHA-256 manifest."""

from __future__ import annotations

import argparse
import hashlib
import zipfile
from pathlib import Path


def package_directory(source: Path, output: Path) -> str:
    """Archive *source* and return the lowercase SHA-256 digest."""
    if not source.is_dir():
        raise ValueError(f"desktop build directory does not exist: {source}")
    if output.suffix.lower() != ".zip":
        raise ValueError("release archive must use the .zip extension")

    output.parent.mkdir(parents=True, exist_ok=True)
    files = sorted(path for path in source.rglob("*") if path.is_file())
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
    return digest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    digest = package_directory(args.source.resolve(), args.output.resolve())
    print(f"{args.output}: {digest}")


if __name__ == "__main__":
    main()
