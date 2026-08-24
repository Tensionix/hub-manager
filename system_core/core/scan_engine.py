from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
import os

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

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScanBundle:
    files: dict[str, FileRecord]
    dirs: set[str]
    stats: ScanStats


def rel_path(path: Path, root: Path) -> str:
    return norm_rel(path.relative_to(root).as_posix())


def scan_source(root: Path, profile: Any) -> ScanBundle:
    root = root.resolve()
    files: dict[str, FileRecord] = {}
    dirs: set[str] = set()
    stats = ScanStats()

    if not root.exists():
        raise FileNotFoundError(f"Source path not found: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Source is not a directory: {root}")

    for dirpath, dirnames, filenames in os.walk(root):
        dir_path = Path(dirpath)
        rel_dir = "" if dir_path == root else rel_path(dir_path, root)
        if rel_dir:
            stats.total_dirs += 1
            dirs.add(rel_dir)

        next_dirs: list[str] = []
        for dirname in list(dirnames):
            child = dir_path / dirname
            rel_child = rel_path(child, root)
            if match_dir_rule(rel_child, getattr(profile, "forbidden_dirs", [])):
                stats.content_excluded_dirs += 1
                continue
            if match_dir_rule(rel_child, getattr(profile, "hide_dirs", [])):
                stats.hidden_dirs += 1
                continue
            dirs.add(rel_child)
            if match_dir_rule(rel_child, getattr(profile, "exclude_dir_contents", [])):
                stats.content_excluded_dirs += 1
                continue
            next_dirs.append(dirname)
        dirnames[:] = next_dirs

        for filename in filenames:
            full = dir_path / filename
            rel = rel_path(full, root)
            try:
                stat = full.stat()
            except OSError:
                stats.skipped_by_exclude += 1
                continue
            stats.total_files += 1
            ok, reason = include_file(rel, stat.st_size, profile)
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

    stats.considered_dirs = len(dirs)
    return ScanBundle(files=files, dirs=dirs, stats=stats)


def scan_projection(root: Path, profile: Any) -> ScanBundle:
    root = root.resolve()
    files: dict[str, FileRecord] = {}
    dirs: set[str] = set()
    stats = ScanStats()

    if not root.exists():
        return ScanBundle(files={}, dirs=set(), stats=stats)

    for dirpath, dirnames, filenames in os.walk(root):
        dir_path = Path(dirpath)
        rel_dir = "" if dir_path == root else rel_path(dir_path, root)
        if rel_dir:
            dirs.add(rel_dir)
            stats.total_dirs += 1

        next_dirs: list[str] = []
        for dirname in list(dirnames):
            child_rel = rel_path(dir_path / dirname, root)
            if protected_target_path(child_rel, profile):
                continue
            if match_dir_rule(child_rel, getattr(profile, "hide_dirs", [])) and not match_dir_rule(child_rel, getattr(profile, "forbidden_dirs", [])):
                continue
            next_dirs.append(dirname)
        dirnames[:] = next_dirs

        for filename in filenames:
            full = dir_path / filename
            rel = rel_path(full, root)
            if filename == getattr(profile, "marker_file", ".gitkeep"):
                continue
            if protected_target_path(rel, profile):
                continue
            try:
                stat = full.stat()
            except OSError:
                continue
            stats.total_files += 1
            files[rel] = FileRecord(rel, str(full), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
            stats.considered_files += 1
            stats.considered_bytes += stat.st_size
    stats.considered_dirs = len(dirs)
    return ScanBundle(files=files, dirs=dirs, stats=stats)
