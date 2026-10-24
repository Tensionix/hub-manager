"""The reference part of the documents, made from the Git canon: `hub_cli.cmd canon --docs`.

A document holds a block between `<!-- canon:NAME -->` and `<!-- /canon -->`; the block is written from
git_canon.py and never by hand. NAME is a section of the canon (changes, history, branches, sync,
projects, service) - a table of its operations with what each does and how to undo it - or
`compact` - one line per operation for an agent. The language is the document's: a name ending in
_RU.md is Russian, any other English. tests/test_canon_docs.py fails when a block and the canon part.
"""
from __future__ import annotations

from pathlib import Path
import re

from . import git_canon

BLOCK_RE = re.compile(r"(<!-- canon:([a-z_-]+) -->)(.*?)(<!-- /canon -->)", re.S)

RISK = {
    "ru": {"read": "читает", "local": "меняет", "net": "сеть", "danger": "опасно"},
    "en": {"read": "reads", "local": "changes", "net": "network", "danger": "danger"},
}
MODE = {
    "ru": {"run": "сразу", "ask": "спросит", "template": "заготовка"},
    "en": {"run": "at once", "ask": "asks first", "template": "template"},
}
HEAD = {
    "ru": "| Команда | Что делает | Как отменить | Риск |\n|---|---|---|---|",
    "en": "| Command | What it does | How to undo it | Risk |\n|---|---|---|---|",
}


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _code(text: str) -> str:
    return "`" + text.replace("|", "\\|") + "`"


def render(name: str, lang: str) -> str:
    """The text of one block: a table of a section, or the compact list of every operation."""
    if name == "compact":
        rows = ["| id | command | risk | mode | section |", "|---|---|---|---|---|"]
        for item in git_canon.CANON:
            rows.append(f"| `{item.id}` | {_code(item.display())} | {item.risk} | {item.mode} | {item.section} |")
        return "\n".join(rows)
    if name not in git_canon.SECTIONS:
        raise KeyError(f"no section {name!r} in the canon")
    rows = [HEAD[lang]]
    for item in git_canon.CANON:
        if item.section != name:
            continue
        what, undo = item.ru if lang == "ru" else item.en
        risk = f"{RISK[lang][item.risk]} · {MODE[lang][item.mode]}"
        rows.append(f"| {_code(item.display())} | {_cell(what)} | {_cell(undo)} | {risk} |")
    return "\n".join(rows)


def language(path: Path) -> str:
    return "ru" if path.name.upper().endswith("_RU.MD") else "en"


def rewrite(text: str, lang: str) -> str:
    return BLOCK_RE.sub(lambda m: f"{m.group(1)}\n{render(m.group(2), lang)}\n{m.group(4)}", text)


def documents(root: Path) -> list[Path]:
    """The documents that hold a canon block: docs\\*.md and SKILL.md."""
    found = sorted((root / "docs").glob("*.md")) + [root / "SKILL.md"]
    return [p for p in found if p.is_file() and BLOCK_RE.search(p.read_text(encoding="utf-8"))]


def write_docs(root: Path) -> dict[str, list[str]]:
    """Writes every canon block of the documents anew; a file whose blocks already agree is left as it is."""
    written, unchanged = [], []
    for path in documents(root):
        raw = path.read_bytes().decode("utf-8")
        eol = "\r\n" if "\r\n" in raw else "\n"
        text = raw.replace("\r\n", "\n")
        new = rewrite(text, language(path))
        if new == text:
            unchanged.append(str(path.relative_to(root)))
            continue
        path.write_bytes(new.replace("\n", eol).encode("utf-8"))
        written.append(str(path.relative_to(root)))
    return {"written": written, "unchanged": unchanged}


def stale(root: Path) -> list[str]:
    """The documents whose canon blocks differ from the canon now."""
    out = []
    for path in documents(root):
        text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        if rewrite(text, language(path)) != text:
            out.append(str(path.relative_to(root)))
    return out
