from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
import os
import time

from .json_utils import load_json, save_json
from .copy_engine import hash_file_blake3, safe_copy2 as _safe_copy2, timestamp_slug
from .mask_engine import (
    match_dir_rule as _match_dir_rule,
    norm_rel as _norm_rel,
    protected_target_path as _protected_target_path,
)
from .paths import get_project_paths
from .project_registry import ProjectEntry
from .scan_engine import (
    FileRecord,
    ScanBundle,
    ScanStats,
    scan_projection,
    scan_source,
)


DEFAULT_COMPARE_MODE = "metadata_then_blake3"


@dataclass
class ProjectionProfile:
    id: str
    title: str = ""
    description: str = ""
    compare_mode: str = DEFAULT_COMPARE_MODE
    mirror: bool = True
    mirror_scope: str = "filtered"
    preserve_empty_dirs: bool = True
    marker_file: str = ".gitkeep"
    max_file_bytes: int | None = 10 * 1024 * 1024
    include_globs: list[str] = field(default_factory=list)
    exclude_globs: list[str] = field(default_factory=list)
    small_include_globs: list[str] = field(default_factory=list)
    small_include_max_file_bytes: int | None = None
    hide_dirs: list[str] = field(default_factory=list)
    exclude_dir_contents: list[str] = field(default_factory=list)
    forbidden_dirs: list[str] = field(default_factory=list)
    protected_target_globs: list[str] = field(default_factory=list)
    dry_run_default: bool = True
    require_include_filter: bool = True
    min_include_globs: int = 1
    delete_after_successful_copy: bool = True
    allow_unfiltered_full: bool = False

    @classmethod
    def from_dict(cls, profile_id: str, data: dict[str, Any]) -> "ProjectionProfile":
        return cls(
            id=profile_id,
            title=str(data.get("title", profile_id)),
            description=str(data.get("description", "")),
            compare_mode=str(data.get("compare_mode", DEFAULT_COMPARE_MODE)),
            mirror=bool(data.get("mirror", True)),
            mirror_scope=str(data.get("mirror_scope", "filtered")).strip().lower() or "projection_exact",
            preserve_empty_dirs=bool(data.get("preserve_empty_dirs", True)),
            marker_file=str(data.get("marker_file", ".gitkeep")),
            max_file_bytes=data.get("max_file_bytes"),
            include_globs=[str(item) for item in data.get("include_globs", [])],
            exclude_globs=[str(item) for item in data.get("exclude_globs", [])],
            small_include_globs=[str(item) for item in data.get("small_include_globs", [])],
            small_include_max_file_bytes=data.get("small_include_max_file_bytes"),
            hide_dirs=[_norm_rel(str(item)).lower() for item in data.get("hide_dirs", [])],
            exclude_dir_contents=[_norm_rel(str(item)).lower() for item in data.get("exclude_dir_contents", [])],
            forbidden_dirs=[_norm_rel(str(item)).lower() for item in data.get("forbidden_dirs", [])],
            protected_target_globs=[str(item) for item in data.get("protected_target_globs", [])],
            dry_run_default=bool(data.get("dry_run_default", True)),
            require_include_filter=bool(data.get("require_include_filter", True)),
            min_include_globs=int(data.get("min_include_globs", 1)),
            delete_after_successful_copy=bool(data.get("delete_after_successful_copy", True)),
            allow_unfiltered_full=bool(data.get("allow_unfiltered_full", False)),
        )

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def _rel_path(path: Path, root: Path) -> str:
    return _norm_rel(path.relative_to(root).as_posix())


def _canonical_compare_mode(mode: str) -> str:
    """Normalize comparison mode.

    quick:
        Trust size + mtime. No hash.
    safe:
        Disk Auditor legacy hybrid: trust same size + same mtime; hash same-size
        files only when mtime differs.
    metadata_then_blake3 / strict:
        Hash same-size files, including the dangerous case where size and mtime
        both look identical but content differs. Recommended for Hub Projection
        checkpoints when BLAKE3 is available.
    """
    value = str(mode or DEFAULT_COMPARE_MODE).strip().lower().replace("-", "_")
    aliases = {
        "safe_blake3": "safe",
        "hybrid": "metadata_then_blake3",
        "metadata_blake3": "metadata_then_blake3",
        "blake3": "strict",
        "strict_blake3": "strict",
        "hash_all": "strict",
    }
    value = aliases.get(value, value)
    if value not in {"quick", "safe", "metadata_then_blake3", "strict"}:
        raise ValueError(f"Unsupported compare_mode: {mode}")
    return value


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def load_projection_profiles(path: Path | None = None) -> dict[str, ProjectionProfile]:
    paths = get_project_paths()
    config_path = path or paths.config / "projection_profiles.json"
    payload = load_json(config_path, default={"profiles": {}})
    raw_profiles = payload.get("profiles", {}) if isinstance(payload, dict) else {}
    return {
        str(profile_id): ProjectionProfile.from_dict(str(profile_id), data)
        for profile_id, data in raw_profiles.items()
        if isinstance(data, dict)
    }


def get_projection_profile(profile_id: str, path: Path | None = None) -> ProjectionProfile:
    profiles = load_projection_profiles(path)
    if profile_id not in profiles:
        raise KeyError(f"Projection profile not found: {profile_id}")
    return profiles[profile_id]


def validate_profile(profile: ProjectionProfile) -> None:
    if profile.mirror_scope not in {"filtered", "full"}:
        raise ValueError(f"Unsupported mirror_scope: {profile.mirror_scope!r}")
    include_count = len([p for p in profile.include_globs if str(p).strip()])
    small_include_count = len([p for p in profile.small_include_globs if str(p).strip()])
    if profile.require_include_filter and include_count < profile.min_include_globs:
        raise ValueError(
            f"Projection profile '{profile.id}' requires at least {profile.min_include_globs} include_globs entry. "
            "Refusing copy-all MIRROR."
        )
    if profile.mirror and not profile.allow_unfiltered_full and include_count + small_include_count == 0:
        raise ValueError(
            f"Projection profile '{profile.id}' has mirror enabled but no include_globs/small_include_globs. "
            "Refusing unfiltered MIRROR."
        )
    _canonical_compare_mode(profile.compare_mode)


# ---------------------------------------------------------------------------
# Path safety and hashing
# ---------------------------------------------------------------------------


def ensure_non_overlapping_dirs(source: Path, target: Path) -> None:
    source = source.resolve()
    target = target.resolve()
    if source == target:
        raise ValueError("Source and projection paths must be different directories.")
    try:
        source.relative_to(target)
        raise ValueError("Source is inside projection. Refusing overlapping MIRROR.")
    except ValueError as exc:
        if "Refusing" in str(exc):
            raise
    try:
        target.relative_to(source)
        raise ValueError("Projection is inside source. Refusing overlapping MIRROR.")
    except ValueError as exc:
        if "Refusing" in str(exc):
            raise


def _same_size_hash_decision(src: FileRecord, dst: FileRecord) -> tuple[bool, str]:
    src.hash_hex = src.hash_hex or hash_file_blake3(Path(src.abs_path))
    dst.hash_hex = dst.hash_hex or hash_file_blake3(Path(dst.abs_path))
    if src.hash_hex == dst.hash_hex:
        if src.mtime_ns == dst.mtime_ns:
            return True, "same_blake3_verified"
        return True, "same_blake3_touch_mtime"
    return False, "same_size_different_blake3"


def _summary(items: list[dict[str, Any]], source: ScanBundle, target: ScanBundle, profile: ProjectionProfile) -> dict[str, Any]:
    counts: dict[str, int] = {}
    bytes_to_copy = 0
    for item in items:
        action = str(item.get("action", ""))
        counts[action] = counts.get(action, 0) + 1
        if action == "copy" and item.get("source"):
            bytes_to_copy += int(item["source"].get("size", 0))
    copy_count = counts.get("copy", 0)
    delete_count = counts.get("delete", 0)
    touch_count = counts.get("touch", 0)
    same_count = counts.get("same", 0)
    error_count = counts.get("error", 0)
    conflict_count = counts.get("conflict", 0)
    return {
        "source_files": source.stats.considered_files,
        "source_dirs": source.stats.considered_dirs,
        "target_files": target.stats.considered_files,
        "target_dirs": target.stats.considered_dirs,
        "copy": copy_count,
        "delete": delete_count,
        "touch": touch_count,
        "same": same_count,
        "error": error_count,
        "conflict": conflict_count,
        "files_to_copy": copy_count,
        "files_to_delete": delete_count,
        "files_to_touch": touch_count,
        "same_files": same_count,
        "errors": error_count,
        "conflicts": conflict_count,
        "bytes_to_copy": bytes_to_copy,
        "mirror_scope": profile.mirror_scope,
        "compare_mode": _canonical_compare_mode(profile.compare_mode),
        "source_scan": source.stats.to_json(),
        "target_scan": target.stats.to_json(),
    }


def _dirs_for_included_files(files: dict[str, FileRecord]) -> set[str]:
    dirs: set[str] = set()
    for rel in files:
        parent = Path(rel).parent
        while str(parent) not in ("", "."):
            dirs.add(_norm_rel(parent.as_posix()))
            parent = parent.parent
    return dirs


def plan_projection(source: Path, projection: Path, profile: ProjectionProfile) -> dict[str, Any]:
    source = source.expanduser().resolve()
    projection = projection.expanduser().resolve()
    validate_profile(profile)
    ensure_non_overlapping_dirs(source, projection)

    source_bundle = scan_source(source, profile)
    target_bundle = scan_projection(projection, profile)
    compare_mode = _canonical_compare_mode(profile.compare_mode)
    items: list[dict[str, Any]] = []

    for rel in sorted(set(source_bundle.files) | set(target_bundle.files)):
        src = source_bundle.files.get(rel)
        dst = target_bundle.files.get(rel)
        if src and not dst:
            items.append({"action": "copy", "reason": "missing_in_projection", "rel_path": rel, "source": src.to_json(), "target": None})
            continue
        if dst and not src:
            if profile.mirror:
                items.append({"action": "delete", "reason": "missing_in_source_allowed_set", "rel_path": rel, "source": None, "target": dst.to_json()})
            else:
                items.append({"action": "extra_target", "reason": "target_only", "rel_path": rel, "source": None, "target": dst.to_json()})
            continue
        assert src is not None and dst is not None

        same_size = src.size == dst.size
        same_mtime = src.mtime_ns == dst.mtime_ns

        if same_size and compare_mode == "quick":
            if same_mtime:
                items.append({"action": "same", "reason": "size_and_mtime_match_quick", "rel_path": rel, "source": src.to_json(), "target": dst.to_json()})
            else:
                items.append({"action": "copy", "reason": "same_size_different_mtime_quick", "rel_path": rel, "source": src.to_json(), "target": dst.to_json()})
            continue

        if same_size and compare_mode == "safe":
            if same_mtime:
                items.append({"action": "same", "reason": "size_and_mtime_match", "rel_path": rel, "source": src.to_json(), "target": dst.to_json()})
                continue
            try:
                same_hash, reason = _same_size_hash_decision(src, dst)
                if same_hash:
                    action = "same" if reason == "same_blake3_verified" else "touch"
                    items.append({"action": action, "reason": reason, "rel_path": rel, "source": src.to_json(), "target": dst.to_json()})
                else:
                    items.append({"action": "copy", "reason": "content_or_metadata_diff", "hash_reason": reason, "rel_path": rel, "source": src.to_json(), "target": dst.to_json()})
                continue
            except Exception as exc:
                items.append({"action": "error", "reason": f"hash_failed: {exc.__class__.__name__}: {exc}", "rel_path": rel, "source": src.to_json(), "target": dst.to_json()})
                continue

        if same_size and compare_mode in {"metadata_then_blake3", "strict"}:
            try:
                same_hash, reason = _same_size_hash_decision(src, dst)
                if same_hash:
                    action = "same" if reason == "same_blake3_verified" else "touch"
                    items.append({"action": action, "reason": reason, "rel_path": rel, "source": src.to_json(), "target": dst.to_json()})
                else:
                    items.append({"action": "copy", "reason": "content_or_metadata_diff", "hash_reason": reason, "rel_path": rel, "source": src.to_json(), "target": dst.to_json()})
                continue
            except Exception as exc:
                items.append({"action": "error", "reason": f"hash_failed: {exc.__class__.__name__}: {exc}", "rel_path": rel, "source": src.to_json(), "target": dst.to_json()})
                continue

        items.append({"action": "copy", "reason": "content_or_metadata_diff", "rel_path": rel, "source": src.to_json(), "target": dst.to_json()})

    source_dirs = source_bundle.dirs if profile.preserve_empty_dirs else _dirs_for_included_files(source_bundle.files)
    plan = {
        "action": "projection_plan",
        "created_at": datetime.now().isoformat(timespec="microseconds"),
        "source_root": str(source),
        "projection_root": str(projection),
        "profile": profile.to_json(),
        "source_dirs": sorted(source_dirs),
        "summary": _summary(items, source_bundle, target_bundle, profile),
        "items": items,
    }
    return plan


# ---------------------------------------------------------------------------
# Apply and .gitkeep
# ---------------------------------------------------------------------------


def _remove_obsolete_empty_dirs(projection: Path, allowed_dirs: set[str], profile: ProjectionProfile, applied: dict[str, Any]) -> None:
    if not projection.exists():
        return
    for dirpath, _dirnames, _filenames in os.walk(projection, topdown=False):
        path = Path(dirpath)
        if path == projection:
            continue
        rel = _rel_path(path, projection)
        if _protected_target_path(rel, profile):
            continue
        if rel in allowed_dirs:
            continue
        try:
            marker = path / profile.marker_file
            if marker.exists() and marker.is_file():
                marker.unlink()
            path.rmdir()
            applied["deleted_dirs"].append({"rel_path": rel})
        except OSError:
            pass


def ensure_gitkeep_for_empty_dirs(projection: Path, allowed_dirs: Iterable[str], profile: ProjectionProfile) -> dict[str, Any]:
    result = {"created": [], "removed": [], "kept": []}
    if not profile.preserve_empty_dirs:
        return result
    projection.mkdir(parents=True, exist_ok=True)
    allowed = {""} | {_norm_rel(item) for item in allowed_dirs}

    for rel in sorted(allowed, key=lambda p: (p.count("/"), p)):
        if not rel:
            continue
        if _protected_target_path(rel, profile) or _match_dir_rule(rel, profile.hide_dirs) or _match_dir_rule(rel, profile.forbidden_dirs):
            continue
        (projection / rel).mkdir(parents=True, exist_ok=True)

    for dirpath, dirnames, filenames in os.walk(projection, topdown=False):
        path = Path(dirpath)
        if path == projection:
            continue
        rel = _rel_path(path, projection)
        if rel not in allowed:
            continue
        marker = path / profile.marker_file
        real_files = [name for name in filenames if name != profile.marker_file]
        real_dirs = [name for name in dirnames if name]
        if not real_files and not real_dirs:
            if not marker.exists():
                marker.write_text("", encoding="utf-8")
                result["created"].append(rel)
            else:
                result["kept"].append(rel)
        else:
            if marker.exists() and marker.is_file():
                marker.unlink()
                result["removed"].append(rel)
    return result


def apply_projection_plan(plan: dict[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
    """Apply a one-way Hub Projection plan.

    Real apply is phased deliberately:
    1. create allowed directories;
    2. copy/update files;
    3. touch mtimes for equal-content files;
    4. delete projection-only files only if copy/touch phase had no errors/conflicts;
    5. remove obsolete empty dirs and regenerate .gitkeep markers.
    """
    projection = Path(plan["projection_root"]).resolve()
    source_root = Path(plan["source_root"]).resolve()
    profile = ProjectionProfile.from_dict(plan.get("profile", {}).get("id", "inline"), plan.get("profile", {}))
    # A plan is JSON and can be stale or hand-edited, so re-check the invariants
    # before anything is deleted rather than trusting the roots it carries.
    validate_profile(profile)
    ensure_non_overlapping_dirs(source_root, projection)
    allowed_dirs = {_norm_rel(item) for item in plan.get("source_dirs", [])}
    started = time.time()
    delete_phase_skipped = False

    applied: dict[str, Any] = {
        "copied": [],
        "deleted": [],
        "touched": [],
        "deleted_dirs": [],
        "gitkeep": {"created": [], "removed": [], "kept": []},
        "errors": [],
        "conflicts": [],
        "skipped": [],
    }

    items = list(plan.get("items", []))

    if dry_run:
        for item in items:
            action = item.get("action")
            if action in {"copy", "delete", "touch"}:
                applied[{"copy": "copied", "delete": "deleted", "touch": "touched"}[action]].append({"rel_path": item.get("rel_path"), "dry_run": True})
            elif action == "conflict":
                applied["conflicts"].append({"rel_path": item.get("rel_path"), "reason": item.get("reason", "conflict"), "dry_run": True})
            elif action == "error":
                applied["errors"].append({"rel_path": item.get("rel_path"), "error": item.get("reason")})
            else:
                applied["skipped"].append({"rel_path": item.get("rel_path"), "action": action})
        applied["gitkeep"] = {"created": [], "removed": [], "kept": [], "dry_run": True, "allowed_dirs": len(allowed_dirs)}
    else:
        projection.mkdir(parents=True, exist_ok=True)
        for rel in sorted(allowed_dirs):
            if rel:
                (projection / rel).mkdir(parents=True, exist_ok=True)

        # Phase 1: copy/update only.
        for item in items:
            if item.get("action") != "copy":
                continue
            rel = _norm_rel(item.get("rel_path", ""))
            try:
                src_info = item.get("source") or {}
                src = Path(src_info.get("abs_path", source_root / rel))
                dst = projection / rel
                _safe_copy2(src, dst)
                applied["copied"].append({"rel_path": rel, "size": int(src_info.get("size", 0))})
            except Exception as exc:
                applied["errors"].append({"rel_path": rel, "error": f"{exc.__class__.__name__}: {exc}"})

        # Phase 2: touch metadata.
        for item in items:
            if item.get("action") != "touch":
                continue
            rel = _norm_rel(item.get("rel_path", ""))
            try:
                src_info = item.get("source") or {}
                dst = projection / rel
                if dst.exists():
                    mtime_ns = int(src_info.get("mtime_ns", 0))
                    os.utime(dst, ns=(mtime_ns, mtime_ns))
                    applied["touched"].append({"rel_path": rel})
                else:
                    applied["errors"].append({"rel_path": rel, "error": "touch target missing"})
            except Exception as exc:
                applied["errors"].append({"rel_path": rel, "error": f"{exc.__class__.__name__}: {exc}"})

        # Collect plan issues and non-mutating statuses.
        for item in items:
            action = item.get("action")
            rel = _norm_rel(item.get("rel_path", ""))
            if action == "error":
                applied["errors"].append({"rel_path": rel, "error": item.get("reason")})
            elif action == "conflict":
                applied["conflicts"].append({"rel_path": rel, "reason": item.get("reason", "conflict")})
            elif action not in {"copy", "touch", "delete"}:
                applied["skipped"].append({"rel_path": rel, "action": action})

        # Phase 3: delete only after successful copy/touch. This is the Disk
        # Auditor safety hardening rule ported into Hub Manager.
        # Deleting after a failed copy is how a mirror loses data that exists
        # nowhere else, so errors block the delete phase regardless of profile.
        may_delete = not applied["errors"] and not applied["conflicts"]
        if not may_delete:
            delete_phase_skipped = True
            for item in items:
                if item.get("action") == "delete":
                    applied["skipped"].append({"rel_path": item.get("rel_path"), "action": "delete", "reason": "delete_phase_skipped_after_errors_or_conflicts"})
        else:
            for item in items:
                if item.get("action") != "delete":
                    continue
                rel = _norm_rel(item.get("rel_path", ""))
                try:
                    dst = projection / rel
                    if dst.exists() and dst.is_file():
                        size = dst.stat().st_size
                        dst.unlink()
                        applied["deleted"].append({"rel_path": rel, "size": size})
                except Exception as exc:
                    applied["errors"].append({"rel_path": rel, "error": f"{exc.__class__.__name__}: {exc}"})

            if not applied["errors"] and not applied["conflicts"]:
                _remove_obsolete_empty_dirs(projection, allowed_dirs, profile, applied)

        applied["gitkeep"] = ensure_gitkeep_for_empty_dirs(projection, allowed_dirs, profile)

    summary = {
        "dry_run": dry_run,
        "mirror_scope": profile.mirror_scope,
        "compare_mode": _canonical_compare_mode(profile.compare_mode),
        "copied": len(applied["copied"]),
        "deleted": len(applied["deleted"]),
        "touched": len(applied["touched"]),
        "deleted_dirs": len(applied["deleted_dirs"]),
        "gitkeep_created": len(applied["gitkeep"].get("created", [])),
        "gitkeep_removed": len(applied["gitkeep"].get("removed", [])),
        "errors": len(applied["errors"]),
        "conflicts": len(applied["conflicts"]),
        "delete_phase_skipped": delete_phase_skipped,
        "exit_code": 0 if not applied["errors"] and not applied["conflicts"] else 1,
        "elapsed_seconds": round(time.time() - started, 3),
    }
    return {
        "action": "projection_apply",
        "dry_run": dry_run,
        "source_root": str(source_root),
        "projection_root": str(projection),
        "summary": summary,
        "details": applied,
    }


def plan_projection_from_project(project: ProjectEntry, profile_path: Path | None = None) -> dict[str, Any]:
    profile = get_projection_profile(project.profile, profile_path)
    return plan_projection(project.source_path, project.projection_path, profile)


def _manifest_entry(record: FileRecord) -> dict[str, Any]:
    digest = hash_file_blake3(Path(record.abs_path))
    return {
        "rel_path": record.rel_path,
        "size": record.size,
        "mtime_ns": record.mtime_ns,
        "digest": digest,
    }


def verify_projection_mirror(source: Path, projection: Path, profile: ProjectionProfile) -> dict[str, Any]:
    source = source.expanduser().resolve()
    projection = projection.expanduser().resolve()
    validate_profile(profile)
    ensure_non_overlapping_dirs(source, projection)
    started = time.time()

    source_bundle = scan_source(source, profile)
    target_bundle = scan_projection(projection, profile)
    items: list[dict[str, Any]] = []
    errors = 0
    total_source_bytes = 0
    total_target_bytes = 0

    for rel in sorted(set(source_bundle.files) | set(target_bundle.files)):
        src_record = source_bundle.files.get(rel)
        dst_record = target_bundle.files.get(rel)
        try:
            src_entry = _manifest_entry(src_record) if src_record else None
            dst_entry = _manifest_entry(dst_record) if dst_record else None
            if src_entry:
                total_source_bytes += int(src_entry["size"])
            if dst_entry:
                total_target_bytes += int(dst_entry["size"])
            if src_entry and dst_entry:
                action = "same" if src_entry["digest"] == dst_entry["digest"] else "changed"
                reason = "digest_match" if action == "same" else "digest_mismatch"
            elif src_entry:
                action = "missing"
                reason = "missing_in_projection"
            else:
                action = "extra"
                reason = "missing_in_source_allowed_set"
            items.append({
                "action": action,
                "reason": reason,
                "rel_path": rel,
                "source": src_entry,
                "target": dst_entry,
            })
        except Exception as exc:
            errors += 1
            items.append({
                "action": "error",
                "reason": f"hash_failed: {exc.__class__.__name__}: {exc}",
                "rel_path": rel,
                "source": src_record.to_json() if src_record else None,
                "target": dst_record.to_json() if dst_record else None,
            })

    summary = {
        "same": sum(1 for item in items if item["action"] == "same"),
        "changed": sum(1 for item in items if item["action"] == "changed"),
        "missing": sum(1 for item in items if item["action"] == "missing"),
        "extra": sum(1 for item in items if item["action"] == "extra"),
        "errors": errors,
        "source_files": len(source_bundle.files),
        "target_files": len(target_bundle.files),
        "source_bytes": total_source_bytes,
        "target_bytes": total_target_bytes,
        "mirror_scope": profile.mirror_scope,
        "exit_code": 0
        if not any(item["action"] in {"changed", "missing", "extra", "error"} for item in items)
        else 1,
        "elapsed_seconds": round(time.time() - started, 3),
    }
    return {
        "action": "mirror_verify",
        "created_at": datetime.now().isoformat(timespec="microseconds"),
        "source_root": str(source),
        "projection_root": str(projection),
        "profile": profile.to_json(),
        "summary": summary,
        "items": items,
        "source_scan": source_bundle.stats.to_json(),
        "target_scan": target_bundle.stats.to_json(),
    }


def verify_projection_mirror_from_project(project: ProjectEntry, profile_path: Path | None = None) -> dict[str, Any]:
    profile = get_projection_profile(project.profile, profile_path)
    return verify_projection_mirror(project.source_path, project.projection_path, profile)


def _safe_report_part(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "-_." else "_" for char in value.strip())
    return cleaned.strip("._")[:80] or "unknown"


def write_report(kind: str, payload: dict[str, Any], *, project_id: str | None = None) -> Path:
    paths = get_project_paths()
    log_dir = paths.logs / _safe_report_part(project_id) if project_id else paths.logs
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"{timestamp_slug()}_{_safe_report_part(kind)}.json"
    save_json(path, payload)
    return path


# Compatibility alias: earlier drafts and tests used this name.
def build_projection_plan(source: Path, projection: Path, profile: ProjectionProfile) -> dict[str, Any]:
    return plan_projection(source, projection, profile)
