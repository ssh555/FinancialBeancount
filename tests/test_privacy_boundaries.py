"""Release gates for the local-only ledger privacy boundary."""

import ast
from pathlib import Path

from beancount_dedup.mobile_api import load_web_asset

PACKAGE = Path(__file__).parents[1] / "beancount_dedup"


def test_only_updater_contains_outbound_network_client_imports() -> None:
    outbound_modules = {"requests", "httpx", "urllib.request", "aiohttp"}
    observed: dict[str, set[str]] = {}
    for source_path in PACKAGE.rglob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
        used = imports & outbound_modules
        if used:
            observed[source_path.relative_to(PACKAGE).as_posix()] = used

    assert observed == {"updater.py": {"urllib.request"}}


def test_bundled_web_application_has_no_external_resource_urls() -> None:
    for name in ("index.html", "app.js", "service-worker.js", "styles.css"):
        asset = load_web_asset(f"/{name}")
        assert asset is not None
        text = asset.body.decode("utf-8")
        assert "https://" not in text
        assert "http://" not in text


def test_service_worker_never_caches_ledger_api_responses() -> None:
    worker = load_web_asset("/service-worker.js")
    assert worker is not None
    source = worker.body.decode("utf-8")
    assert 'url.pathname.startsWith("/api/")' in source
    assert 'event.request.method !== "GET"' in source
