from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Iterable


def norm_rel(value: str | Path) -> str:
    return str(value).replace("\\", "/").strip("/")


def split_patterns(raw_values: Iterable[str] | None) -> list[str]:
    result: list[str] = []
    if not raw_values:
        return result
    for raw in raw_values:
        if raw is None:
            continue
        for piece in str(raw).replace("\n", ";").replace(",", ";").split(";"):
            item = piece.strip()
            if item:
                result.append(item)
    return result


def normalize_dir_rules(items: Iterable[str]) -> list[str]:
    rules: list[str] = []
    seen: set[str] = set()
    for item in items:
        rule = norm_rel(str(item)).lower()
        if not rule or rule in seen:
            continue
        seen.add(rule)
        rules.append(rule)
    return rules


def split_path(path_value: str) -> list[str]:
    return [part for part in norm_rel(path_value).lower().split("/") if part]


def match_dir_rule(rel_path: str, rules: Iterable[str]) -> bool:
    rel = norm_rel(rel_path).lower()
    parts = split_path(rel)
    for raw_rule in rules:
        rule = norm_rel(str(raw_rule)).lower()
        if not rule:
            continue
        if "/" in rule:
            if rel == rule or rel.startswith(rule + "/"):
                return True
        elif rule in parts:
            return True
    return False


def matches_any(path_value: str, name: str, patterns: Iterable[str]) -> bool:
    rel = norm_rel(path_value).lower()
    file_name = name.lower()
    for pattern in patterns:
        p = str(pattern).strip().lower()
        if not p:
            continue
        if p.endswith("/**") and rel == p[:-3]:
            return True
        if fnmatchcase(rel, p) or fnmatchcase(file_name, p):
            return True
    return False


def protected_target_path(rel_path: str, profile: Any) -> bool:
    name = Path(rel_path).name
    return matches_any(rel_path, name, getattr(profile, "protected_target_globs", []))


def include_file(rel_path: str, size: int, profile: Any) -> tuple[bool, str]:
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
        return False, "include_miss"
    return True, "ok"
