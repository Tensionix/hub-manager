from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable
import os
import shutil
import stat as stat_module
import subprocess
import tempfile

from .mask_engine import include_file, match_dir_rule, norm_rel, protected_target_path


@dataclass
class FileRecord:
    rel_path: str
    abs_path: str
    size: int
    mtime_ns: int
    ctime_ns: int
    hash_hex: str | None = None

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScanStats:
    total_files: int = 0
    total_dirs: int = 0
    considered_files: int = 0
    considered_dirs: int = 0
    considered_bytes: int = 0
    skipped_by_include: int = 0
    skipped_by_exclude: int = 0
    skipped_by_size: int = 0
    hidden_dirs: int = 0
    content_excluded_dirs: int = 0
    skipped_by_gitignore: int = 0
    gitignored_dirs: int = 0
    links_skipped: int = 0
    scan_errors: int = 0

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScanBundle:
    files: dict[str, FileRecord]
    dirs: set[str]
    stats: ScanStats
    # What could not be read: the scan is incomplete, and a file missing from it is not a file gone - nothing may be
    # deleted on its word.
    errors: list[dict[str, str]] = field(default_factory=list)
    # Junctions and symbolic links met and not followed.
    links: list[str] = field(default_factory=list)


def rel_path(path: Path, root: Path) -> str:
    return norm_rel(path.relative_to(root).as_posix())


def _is_link_stat(st: os.stat_result) -> bool:
    return stat_module.S_ISLNK(st.st_mode) or getattr(st, "st_reparse_tag", 0) in (
        stat_module.IO_REPARSE_TAG_MOUNT_POINT, stat_module.IO_REPARSE_TAG_SYMLINK)


def is_link(path: Path | str) -> bool:
    """A symbolic link or a junction of Windows (which Python does not call a link): never followed and never written
    through. Either can lead out of the project - a junction in a GIT COPY once let the mirror rewrite the SOURCE."""
    try:
        return _is_link_stat(os.lstat(path))
    except OSError:
        return False


def _problem(path: Path | str | None, root: Path, error: OSError) -> dict[str, str]:
    try:
        rel = rel_path(Path(path), root) if path else ""
    except ValueError:
        rel = str(path)
    return {"rel_path": rel, "error": f"{error.__class__.__name__}: {error.strerror or error}"}


def ignored_by_project(root: Path, paths: Iterable[str]) -> set[str]:
    """The paths the project's own .gitignore hides: its word on what never goes into history, which stands over the
    profile. A folder with a repository of its own is asked as it is, and its tracked files are never hidden. Any other
    folder is asked through a throwaway git folder, so that only its own .gitignore counts - not the one of a repository
    it happens to lie in (the lessons of the lab lie inside Hub Manager)."""
    asked = [path for path in paths if path]
    if not asked:
        return set()
    feed = "\0".join(asked) + "\0"
    if (root / ".git").exists():
        hidden = _check_ignore(["git", "-C", str(root)], feed, root)
        if hidden is not None:
            return hidden
    scratch = tempfile.mkdtemp(prefix="hub_gitignore_")
    try:
        if _check_ignore(["git", "init", "--bare", "-q", scratch], None, root) is None:
            return set()
        return _check_ignore(["git", f"--git-dir={scratch}", f"--work-tree={root}"], feed, root) or set()
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _check_ignore(prefix: list[str], feed: str | None, root: Path) -> set[str] | None:
    """`git check-ignore --stdin -z` after `prefix`, or `prefix` alone when there is nothing to feed. None: git failed."""
    argv = prefix if feed is None else [*prefix, "-c", "core.quotepath=false", "check-ignore", "--stdin", "-z"]
    try:
        done = subprocess.run(argv, input=feed, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              cwd=str(root), timeout=300, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode not in (0, 1):  # 128: not a repository, or git broke
        return None
    return {item for item in done.stdout.split("\0") if item}


def output_rules(root: Path, profile: Any) -> list[str]:
    """The folders that hold builds and dependencies in most projects and sources in some - `app/` of Next.js, `build/`
    of Electron, `bin/` of scripts, `vendor/` of Go: out by guess only where the project has no .gitignore of its own.
    Where it has one, its word decides what is a build."""
    if getattr(profile, "respect_gitignore", True) and (root / ".gitignore").is_file():
        return []
    return list(getattr(profile, "output_dirs", []))


def _upper_dirs(root: Path, profile: Any, outputs: list[str], depth: int = 2) -> list[str]:
    """The folders of the first levels the walk would enter: asked of .gitignore before the walk, so that a hidden
    build tree (`build-ui/`, a toolchain) is not walked at all."""
    found: list[str] = []
    level = [""]
    for _ in range(depth):
        below: list[str] = []
        for rel in level:
            try:
                children = [entry.name for entry in os.scandir(root / rel) if entry.is_dir(follow_symlinks=False)]
            except OSError:
                continue
            for name in children:
                child = f"{rel}/{name}" if rel else name
                if any(match_dir_rule(child, getattr(profile, key, [])) for key in ("forbidden_dirs", "hide_dirs", "exclude_dir_contents")) \
                        or match_dir_rule(child, outputs):
                    continue
                found.append(child)
                below.append(child)
        level = below
    return found


def scan_source(root: Path, profile: Any) -> ScanBundle:
    root = root.resolve()
    files: dict[str, FileRecord] = {}
    dirs: set[str] = set()
    stats = ScanStats()

    if not root.exists():
        raise FileNotFoundError(f"Source path not found: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Source is not a directory: {root}")

    # The project's .gitignore stands over the profile: what it hides is neither walked nor copied.
    respect_gitignore = bool(getattr(profile, "respect_gitignore", True))
    own_repo = (root / ".git").exists()
    seen_gitignore = (root / ".gitignore").is_file()
    outputs = output_rules(root, profile)
    hidden_upper = ignored_by_project(root, _upper_dirs(root, profile, outputs)) if respect_gitignore and (own_repo or seen_gitignore) else set()
    errors: list[dict[str, str]] = []
    links: list[str] = []

    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda error: errors.append(_problem(error.filename, root, error))):
        dir_path = Path(dirpath)
        rel_dir = "" if dir_path == root else rel_path(dir_path, root)
        if rel_dir:
            stats.total_dirs += 1
            dirs.add(rel_dir)
        seen_gitignore = seen_gitignore or ".gitignore" in filenames

        next_dirs: list[str] = []
        for dirname in list(dirnames):
            child = dir_path / dirname
            rel_child = rel_path(child, root)
            if is_link(child):
                links.append(rel_child)
                continue
            if match_dir_rule(rel_child, getattr(profile, "forbidden_dirs", [])):
                stats.content_excluded_dirs += 1
                continue
            if match_dir_rule(rel_child, getattr(profile, "hide_dirs", [])):
                stats.hidden_dirs += 1
                continue
            if rel_child in hidden_upper:
                stats.gitignored_dirs += 1
                continue
            dirs.add(rel_child)
            if match_dir_rule(rel_child, getattr(profile, "exclude_dir_contents", [])) or match_dir_rule(rel_child, outputs):
                stats.content_excluded_dirs += 1
                continue
            next_dirs.append(dirname)
        dirnames[:] = next_dirs

        for filename in filenames:
            full = dir_path / filename
            rel = rel_path(full, root)
            try:
                stat = os.lstat(full)
            except OSError as error:
                errors.append(_problem(full, root, error))
                continue
            if _is_link_stat(stat):
                links.append(rel)
                continue
            stats.total_files += 1
            ok, reason = include_file(rel, stat.st_size, profile, full)
            if not ok:
                if reason == "include_miss":
                    stats.skipped_by_include += 1
                elif reason == "size_gt":
                    stats.skipped_by_size += 1
                else:
                    stats.skipped_by_exclude += 1
                continue
            files[rel] = FileRecord(rel, str(full), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
            stats.considered_files += 1
            stats.considered_bytes += stat.st_size
            parent = Path(rel).parent
            while str(parent) not in ("", "."):
                dirs.add(norm_rel(parent.as_posix()))
                parent = parent.parent

    if respect_gitignore and (own_repo or seen_gitignore):
        hidden = ignored_by_project(root, [*sorted(files), *sorted(dirs)])
        for rel in hidden & files.keys():
            record = files.pop(rel)
            stats.considered_files -= 1
            stats.considered_bytes -= record.size
            stats.skipped_by_gitignore += 1
        stats.gitignored_dirs += len(hidden & dirs)
        dirs -= hidden

    stats.considered_dirs = len(dirs)
    stats.links_skipped, stats.scan_errors = len(links), len(errors)
    return ScanBundle(files=files, dirs=dirs, stats=stats, errors=errors, links=links)


def scan_projection(root: Path, profile: Any) -> ScanBundle:
    root = root.resolve()
    files: dict[str, FileRecord] = {}
    dirs: set[str] = set()
    stats = ScanStats()
    errors: list[dict[str, str]] = []
    links: list[str] = []

    if not root.exists():
        return ScanBundle(files={}, dirs=set(), stats=stats)

    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda error: errors.append(_problem(error.filename, root, error))):
        dir_path = Path(dirpath)
        rel_dir = "" if dir_path == root else rel_path(dir_path, root)
        if rel_dir:
            dirs.add(rel_dir)
            stats.total_dirs += 1

        next_dirs: list[str] = []
        for dirname in list(dirnames):
            child_rel = rel_path(dir_path / dirname, root)
            if is_link(dir_path / dirname):
                links.append(child_rel)
                continue
            if protected_target_path(child_rel, profile):
                continue
            if match_dir_rule(child_rel, getattr(profile, "hide_dirs", [])) and not match_dir_rule(child_rel, getattr(profile, "forbidden_dirs", [])):
                continue
            next_dirs.append(dirname)
        dirnames[:] = next_dirs

        for filename in filenames:
            full = dir_path / filename
            rel = rel_path(full, root)
            # A marker is the mirror's only where the profile puts markers; otherwise a .gitkeep is a file of the project.
            if getattr(profile, "preserve_empty_dirs", True) and filename == getattr(profile, "marker_file", ".gitkeep"):
                continue
            if protected_target_path(rel, profile):
                continue
            try:
                stat = os.lstat(full)
            except OSError as error:
                errors.append(_problem(full, root, error))
                continue
            if _is_link_stat(stat):
                links.append(rel)
                continue
            stats.total_files += 1
            files[rel] = FileRecord(rel, str(full), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
            stats.considered_files += 1
            stats.considered_bytes += stat.st_size
    stats.considered_dirs = len(dirs)
    stats.links_skipped, stats.scan_errors = len(links), len(errors)
    return ScanBundle(files=files, dirs=dirs, stats=stats, errors=errors, links=links)
