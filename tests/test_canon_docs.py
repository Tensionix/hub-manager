from __future__ import annotations

from pathlib import Path

from system_core.core import canon_docs, git_canon

ROOT = Path(__file__).resolve().parents[1]


def test_the_documents_agree_with_the_canon() -> None:
    # The reference tables are written by `hub_cli.cmd canon --docs`; an entry changed in git_canon.py
    # without writing them again leaves a document that tells another command.
    assert canon_docs.stale(ROOT) == []


def test_the_git_wiki_holds_every_section_in_both_languages() -> None:
    for name in ("GIT_WIKI_HUB_MANAGER_RU.md", "GIT_WIKI_HUB_MANAGER_EN.md"):
        text = (ROOT / "docs" / name).read_text(encoding="utf-8")
        for section in git_canon.SECTIONS:
            assert f"<!-- canon:{section} -->" in text, (name, section)


def test_every_operation_stands_in_the_wiki_once() -> None:
    text = (ROOT / "docs" / "GIT_WIKI_HUB_MANAGER_EN.md").read_text(encoding="utf-8")
    for item in git_canon.CANON:
        assert f"`{item.display()}`".replace("|", "\\|") in text, item.id


def test_a_block_is_written_in_the_language_of_its_document(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    for name in ("A_RU.md", "A_EN.md"):
        (tmp_path / "docs" / name).write_text("x\n<!-- canon:service -->\nold\n<!-- /canon -->\ny\n", encoding="utf-8")
    result = canon_docs.write_docs(tmp_path)
    assert sorted(result["written"]) == [str(Path("docs/A_EN.md")), str(Path("docs/A_RU.md"))]
    assert "Что делает" in (tmp_path / "docs" / "A_RU.md").read_text(encoding="utf-8")
    assert "What it does" in (tmp_path / "docs" / "A_EN.md").read_text(encoding="utf-8")
    assert canon_docs.write_docs(tmp_path)["written"] == []
