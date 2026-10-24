from __future__ import annotations

from fnmatch import fnmatchcase, translate
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable
import re


def norm_rel(value: str | Path) -> str:
    return str(value).replace("\\", "/").strip("/")


def split_path(path_value: str) -> list[str]:
    return [part for part in norm_rel(path_value).lower().split("/") if part]


def match_dir_rule(rel_path: str, rules: Iterable[str]) -> bool:
    """A rule names a folder: by its name anywhere (`logs`), by its path from the root (`install/download`), or - with a
    leading slash - by its name at the root only (`/App`: the built window, not an `app` folder of sources deeper down).
    A name may be a mask (`cmake-build-*`)."""
    rel = norm_rel(rel_path).lower()
    parts = split_path(rel)
    for raw_rule in rules:
        anchored = str(raw_rule).strip().startswith(("/", "\\"))
        rule = norm_rel(str(raw_rule)).lower()
        if not rule:
            continue
        wild = any(char in rule for char in "*?[")
        if "/" in rule or anchored:
            depth = rule.count("/") + 1
            if wild and len(parts) >= depth and fnmatchcase("/".join(parts[:depth]), rule):
                return True
            if not wild and (rel == rule or rel.startswith(rule + "/")):
                return True
        elif any(fnmatchcase(part, rule) for part in parts) if wild else rule in parts:
            return True
    return False


@lru_cache(maxsize=256)
def _matcher(patterns: tuple[str, ...]) -> Callable[[str, str], bool]:
    """One test for a whole list of masks, answering as fnmatch of every mask on the path and on the name would.

    A profile holds hundreds of masks and a project thousands of files, so the masks are sorted once: an exact name
    (`makefile`) goes into a set, an ending (`*.py`, `*.min.js`) into one endswith, `folder/**` also matches the folder
    itself; every other mask goes into one compiled expression tried on the path and on the name.
    """
    names: set[str] = set()
    endings: list[str] = []
    folders: set[str] = set()
    rest: list[str] = []
    for raw in patterns:
        p = str(raw).strip().lower()
        if not p:
            continue
        wild = any(ch in p for ch in "*?[")
        if not wild and "/" not in p:
            names.add(p)
        elif p.startswith("*") and "/" not in p and not any(ch in p[1:] for ch in "*?["):
            endings.append(p[1:])
        else:
            if p.endswith("/**"):
                folders.add(p[:-3])
            rest.append(p)
    suffixes = tuple(endings)
    expression = re.compile("|".join(translate(p) for p in rest)) if rest else None

    def match(rel: str, name: str) -> bool:
        if name in names or (suffixes and name.endswith(suffixes)) or rel in folders:
            return True
        return bool(expression and (expression.match(rel) or expression.match(name)))

    return match


def matches_any(path_value: str, name: str, patterns: Iterable[str]) -> bool:
    return _matcher(tuple(patterns))(norm_rel(path_value).lower(), name.lower())


def protected_target_path(rel_path: str, profile: Any) -> bool:
    name = Path(rel_path).name
    return matches_any(rel_path, name, getattr(profile, "protected_target_globs", []))


def include_file(rel_path: str, size: int, profile: Any, path: Path | None = None) -> tuple[bool, str]:
    """Whether a file goes into the GIT COPY, and why. Given the file itself (`path`), a file without an extension the
    list does not name is read for a moment: small and text, it passes (_text_without_extension)."""
    rel = norm_rel(rel_path)
    name = Path(rel).name

    include_globs = getattr(profile, "include_globs", [])
    exclude_globs = getattr(profile, "exclude_globs", [])
    small_include_globs = getattr(profile, "small_include_globs", [])
    small_include_max_file_bytes = getattr(profile, "small_include_max_file_bytes", None)
    max_file_bytes = getattr(profile, "max_file_bytes", None)

    if exclude_globs and matches_any(rel, name, exclude_globs):
        return False, "exclude_glob"
    if max_file_bytes is not None and size > int(max_file_bytes):
        return False, "size_gt"
    if include_globs and matches_any(rel, name, include_globs):
        return True, "ok"
    if small_include_globs and matches_any(rel, name, small_include_globs):
        if small_include_max_file_bytes is not None and size > int(small_include_max_file_bytes):
            return False, "small_include_size_gt"
        return True, "small_include"
    if include_globs:
        if path is not None and _text_without_extension(name, size, path, profile):
            return True, "text"
        return False, "include_miss"
    return True, "ok"


def _text_without_extension(name: str, size: int, path: Path, profile: Any) -> bool:
    """A file without an extension the list does not name - a script (install, ci/test-complete), a licence (UNLICENSE),
    a hook of git (.husky/pre-commit) - passes when it is small and text: no zero byte in its first 8 KB. Exclusions are
    asked before: keys without an extension (id_rsa, credentials) never get here."""
    limit = getattr(profile, "extensionless_text_bytes", None)
    if not limit or size > int(limit) or Path(name).suffix:
        return False
    try:
        with open(path, "rb") as handle:
            return b"\0" not in handle.read(8192)
    except OSError:
        return False
