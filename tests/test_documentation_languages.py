from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


def test_maintainer_documents_have_reciprocal_language_links() -> None:
    for stem in ("PRIVACY", "ROADMAP", "RELEASE"):
        english = (DOCS / f"{stem}.md").read_text(encoding="utf-8")
        chinese = (DOCS / f"{stem}.zh-CN.md").read_text(encoding="utf-8")
        assert f"[{stem}.zh-CN.md]" not in english
        assert f"({stem}.zh-CN.md)" in "\n".join(english.splitlines()[:5])
        assert f"({stem}.md)" in "\n".join(chinese.splitlines()[:5])


def test_documentation_indexes_link_every_language_pair() -> None:
    chinese_index = (DOCS / "README.md").read_text(encoding="utf-8")
    english_index = (DOCS / "README.en.md").read_text(encoding="utf-8")
    for stem in ("PRIVACY", "ROADMAP", "RELEASE"):
        for index in (chinese_index, english_index):
            assert f"({stem}.md)" in index
            assert f"({stem}.zh-CN.md)" in index


def test_root_readme_has_bidirectional_language_navigation() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "[English](#beancount-multi-platform-bill-deduplicator)" in readme
    assert "[简体中文](#beancount-多平台账单去重工具)" in readme
