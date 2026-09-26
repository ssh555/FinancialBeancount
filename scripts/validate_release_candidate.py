"""Validate a requested version tag and the complete signed release asset set."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def validate_candidate(repository: Path, tag: str, artifacts: Path | None = None) -> list[str]:
    normalized = tag.strip()
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", normalized):
        raise ValueError("release tag must use the exact vMAJOR.MINOR.PATCH form")
    project = (repository / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"$', project, re.MULTILINE)
    version = match.group(1) if match else ""
    if normalized != f"v{version}":
        raise ValueError(f"release tag {normalized!r} does not match source version v{version}")
    if artifacts is None:
        return []
    if not artifacts.is_dir():
        raise ValueError(f"release artifact directory does not exist: {artifacts}")

    names = sorted(path.name for path in artifacts.iterdir() if path.is_file())
    empty = sorted(
        path.name for path in artifacts.iterdir() if path.is_file() and path.stat().st_size == 0
    )
    if empty:
        raise ValueError(f"release assets must not be empty: {empty}")
    _require_one(names, r"FinancialBeancount-windows-[^.]+\.zip")
    _require_one(names, r"FinancialBeancount-macos-[^.]+\.zip")
    _require_one(names, r"FinancialBeancount-linux-[^.]+\.zip")
    archives = [name for name in names if name.endswith(".zip")]
    for archive in archives:
        _require_exact(names, f"{archive}.sha256")
        _require_exact(names, f"{archive}.sha256.sig")

    native = {
        "windows": _require_one(names, r"FinancialBeancount-windows-[^.]+\.msi"),
        "macos": _require_one(names, r"FinancialBeancount-macos-[^.]+\.dmg"),
        "linux": _require_one(names, r"FinancialBeancount-linux-[^.]+\.AppImage"),
    }
    for installer in native.values():
        _require_exact(names, f"{installer}.signature.json")
    _require_exact(names, f"{native['linux']}.asc")
    _require_exact(names, "FinancialBeancount-linux-release-keyring.gpg")
    expected = set(archives) | {
        *(f"{archive}.sha256" for archive in archives),
        *(f"{archive}.sha256.sig" for archive in archives),
        *native.values(),
        *(f"{installer}.signature.json" for installer in native.values()),
        f"{native['linux']}.asc",
        "FinancialBeancount-linux-release-keyring.gpg",
    }
    unexpected = sorted(set(names) - expected)
    if unexpected:
        raise ValueError(f"unexpected release assets are present: {unexpected}")
    return names


def _require_one(names: list[str], pattern: str) -> str:
    matches = [name for name in names if re.fullmatch(pattern, name)]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one asset matching {pattern!r}, found {matches}")
    return matches[0]


def _require_exact(names: list[str], expected: str) -> None:
    if names.count(expected) != 1:
        raise ValueError(f"required release asset is missing or duplicated: {expected}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--tag", required=True)
    parser.add_argument("--artifacts", type=Path)
    args = parser.parse_args(argv)
    try:
        assets = validate_candidate(
            args.repository.resolve(),
            args.tag,
            args.artifacts.resolve() if args.artifacts else None,
        )
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"release candidate {args.tag} is valid ({len(assets)} assets)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
