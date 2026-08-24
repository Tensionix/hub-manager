from __future__ import annotations

import re
from pathlib import Path
from typing import Any


DEFAULT_PROFILE = "audion_python_project_projection"
DEFAULT_BRANCH = "main"
MIN_PROJECT_SCORE = 5

SKIP_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "venv",
    "__pycache__",
    "_pwsh_tmp",
    "backup",
    "build",
    "dist",
    "logs",
    "node_modules",
    "output",
    "release",
    "report",
    "runtime",
    "wheelhouse",
}

ROOT_FILES_HIGH = {
    "Cargo.toml",
    "CMakeLists.txt",
    "composer.json",
    "go.mod",
    "package.json",
    "pom.xml",
    "pyproject.toml",
}

ROOT_FILES_MEDIUM = {
    "AGENTS.md",
    "CHANGELOG.md",
    "README.md",
    "README_EN.md",
    "README_RU.md",
    "TECH_SPEC.md",
}

ROOT_DIRS_HIGH = {
    "app",
    "src",
    "system_core",
}

ROOT_DIRS_MEDIUM = {
    "config",
    "docs",
    "install",
    "tests",
}

LANGUAGE_EXTENSIONS = {
    ".bat",
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".css",
    ".go",
    ".h",
    ".hpp",
    ".html",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".lua",
    ".php",
    ".ps1",
    ".py",
    ".rs",
    ".scss",
    ".sh",
    ".sql",
    ".swift",
    ".ts",
    ".tsx",
    ".vue",
}


def _portable_absolute(path: Path) -> Path:
    try:
        return path.expanduser().resolve(strict=False)
    except OSError:
        return path.expanduser().absolute()


def _path_key(path: Path) -> str:
    return str(_portable_absolute(path)).casefold()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        _portable_absolute(path).relative_to(_portable_absolute(parent))
        return True
    except ValueError:
        return False


def _slugify(text: str) -> str:
    value = re.sub(r"[^0-9A-Za-zА-Яа-я]+", "_", text).strip("_").lower()
    value = re.sub(r"_+", "_", value)
    return value or "project"


def _unique_id(base: str, used_ids: set[str]) -> str:
    candidate = base
    index = 2
    while candidate in used_ids:
        candidate = f"{base}_{index}"
        index += 1
    used_ids.add(candidate)
    return candidate


def _score_project_root(path: Path) -> int:
    if not path.is_dir():
        return 0

    names = {child.name for child in path.iterdir()}
    lower_names = {name.lower() for name in names}
    score = 0

    if ".git" in lower_names:
        score += 6

    for filename in ROOT_FILES_HIGH:
        if filename.lower() in lower_names:
            score += 5

    if any(path.glob("*.sln")):
        score += 5

    for dirname in ROOT_DIRS_HIGH:
        if dirname.lower() in lower_names and (path / dirname).is_dir():
            score += 4

    for filename in ROOT_FILES_MEDIUM:
        if filename.lower() in lower_names:
            score += 3

    for dirname in ROOT_DIRS_MEDIUM:
        if dirname.lower() in lower_names and (path / dirname).is_dir():
            score += 2

    if any(child.suffix.lower() == ".cmd" for child in path.iterdir() if child.is_file()):
        score += 1

    code_score = _score_code_shape(path)
    score += code_score

    return score


def _score_code_shape(path: Path) -> int:
    code_files = 0
    code_dirs: set[Path] = set()

    def visit(current: Path, depth: int) -> None:
        nonlocal code_files
        if depth > 2 or current.name.lower() in SKIP_DIR_NAMES:
            return
        try:
            children = list(current.iterdir())
        except OSError:
            return
        for child in children:
            if child.is_dir():
                visit(child, depth + 1)
            elif child.suffix.lower() in LANGUAGE_EXTENSIONS:
                code_files += 1
                code_dirs.add(child.parent)

    visit(path, 0)
    if code_files >= 12 and len(code_dirs) >= 2:
        return 7
    if code_files >= 6:
        return 5
    if code_files >= 3 and len(code_dirs) >= 2:
        return 5
    if code_files >= 3:
        return 3
    return 0


def _has_explicit_root_marker(path: Path) -> bool:
    try:
        lower_names = {child.name.lower() for child in path.iterdir()}
    except OSError:
        return False
    explicit_files = {name.lower() for name in ROOT_FILES_HIGH | ROOT_FILES_MEDIUM}
    return ".git" in lower_names or bool(explicit_files & lower_names) or any(path.glob("*.sln"))


def _walk_project_candidates(root: Path, max_depth: int) -> list[tuple[Path, int, int]]:
    candidates: list[tuple[Path, int, int]] = []

    def visit(path: Path, depth: int) -> None:
        if path.name.lower() in SKIP_DIR_NAMES:
            return
        try:
            score = _score_project_root(path)
        except OSError:
            return
        if score >= MIN_PROJECT_SCORE:
            candidates.append((path, score, depth))
        if depth >= max_depth:
            return
        try:
            children = [child for child in path.iterdir() if child.is_dir()]
        except OSError:
            return
        for child in children:
            visit(child, depth + 1)

    visit(root, 0)
    return candidates


def _best_project_root(root: Path, max_depth: int) -> tuple[Path, int, int] | None:
    candidates = _walk_project_candidates(root, max_depth)
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item[1], item[2], -len(item[0].parts)))


def scan_project_folder(
    container: Path,
    hub_root: Path,
    *,
    docs_root: Path | None = None,
    profile: str = DEFAULT_PROFILE,
    default_branch: str = DEFAULT_BRANCH,
    max_depth: int = 3,
    existing_payload: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    container = _portable_absolute(container)
    hub_root = _portable_absolute(hub_root)
    docs_root = _portable_absolute(docs_root) if docs_root is not None else None

    used_ids: set[str] = set()
    existing_sources: set[str] = set()
    if existing_payload:
        for item in existing_payload.get("projects", []):
            if not isinstance(item, dict):
                continue
            project_id = str(item.get("id", "")).strip()
            if project_id:
                used_ids.add(project_id)
            source = str(item.get("source_path", "")).strip()
            if source:
                existing_sources.add(_path_key(Path(source)))

    try:
        direct_children = [child for child in container.iterdir() if child.is_dir()]
    except OSError:
        direct_children = []

    if _has_explicit_root_marker(container):
        groups = [container]
    else:
        groups = [
            child
            for child in direct_children
            if child.name.lower() not in SKIP_DIR_NAMES
            and not _is_relative_to(child, hub_root)
            and (docs_root is None or not _is_relative_to(child, docs_root))
        ]
        if not groups and not direct_children:
            groups = [container]

    results: list[dict[str, str]] = []
    seen_sources: set[str] = set()
    for group in groups:
        best = _best_project_root(group, max_depth)
        if best is None:
            continue
        project_root, score, depth = best
        source_key = _path_key(project_root)
        if source_key in seen_sources or source_key in existing_sources:
            continue
        seen_sources.add(source_key)

        title = project_root.name
        project_id = _unique_id(_slugify(title), used_ids)
        item = {
            "id": project_id,
            "title": title,
            "source_path": str(project_root),
            "projection_path": str(hub_root / title),
            "profile": profile,
            "default_branch": default_branch,
            "docs_app_name": "",
            "docs_file": "",
            "vscode_workspace": "",
            "notes": f"Imported by project scanner from {container}; detected score={score}; depth={depth}.",
        }
        if docs_root is not None:
            item["docs_path"] = str(docs_root / title)
        results.append(item)

    return sorted(results, key=lambda item: item["title"].casefold())


def merge_project_import(
    payload: dict[str, Any],
    entries: list[dict[str, str]],
) -> tuple[dict[str, Any], int, int]:
    projects = payload.setdefault("projects", [])
    if not isinstance(projects, list):
        projects = []
        payload["projects"] = projects

    used_ids = {
        str(item.get("id", "")).strip()
        for item in projects
        if isinstance(item, dict) and str(item.get("id", "")).strip()
    }
    existing_sources = {
        _path_key(Path(str(item.get("source_path", "")).strip()))
        for item in projects
        if isinstance(item, dict) and str(item.get("source_path", "")).strip()
    }

    added = 0
    skipped = 0
    for entry in entries:
        source = str(entry.get("source_path", "")).strip()
        if not source or _path_key(Path(source)) in existing_sources:
            skipped += 1
            continue
        item = dict(entry)
        base_id = _slugify(str(item.get("id") or item.get("title") or "project"))
        item["id"] = _unique_id(base_id, used_ids)
        existing_sources.add(_path_key(Path(source)))
        projects.append(item)
        added += 1

    if not str(payload.get("active_project_id", "")).strip() and projects:
        first = projects[0]
        if isinstance(first, dict):
            payload["active_project_id"] = str(first.get("id", "")).strip()

    return payload, added, skipped
