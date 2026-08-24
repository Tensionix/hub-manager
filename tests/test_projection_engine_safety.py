from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from system_core.core import projection_engine
from system_core.core.projection_engine import (
    ProjectionProfile,
    apply_projection_plan,
    plan_projection,
    timestamp_slug,
    verify_projection_mirror,
)


def _profile(**overrides) -> ProjectionProfile:
    data = {
        "id": "safety_test",
        "include_globs": ["*.py", "*.bin", "*.md"],
        "exclude_globs": [],
        "hide_dirs": [".git", "__pycache__"],
        "exclude_dir_contents": [],
        "compare_mode": "strict_blake3",
        "max_file_bytes": None,
        "mirror": True,
        "mirror_scope": "filtered",
        "dry_run_default": True,
        "require_include_filter": True,
        "min_include_globs": 1,
        "delete_after_successful_copy": True,
    }
    data.update(overrides)
    return ProjectionProfile(**data)


def test_profile_requires_include_masks(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    profile = _profile(include_globs=[])

    with pytest.raises(ValueError, match="requires at least"):
        plan_projection(source, target, profile)


def test_full_mirror_refuses_empty_include_set(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    profile = _profile(
        include_globs=[],
        small_include_globs=[],
        mirror_scope="full",
        require_include_filter=False,
    )

    with pytest.raises(ValueError, match="Refusing unfiltered MIRROR"):
        plan_projection(source, target, profile)


def test_strict_mode_detects_same_size_same_mtime_different_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    src = source / "a.bin"
    dst = target / "a.bin"
    src.write_bytes(b"AAAA")
    dst.write_bytes(b"BBBB")
    stamp = 1_700_000_000_123_456_789
    os.utime(src, ns=(stamp, stamp))
    os.utime(dst, ns=(stamp, stamp))

    monkeypatch.setattr(projection_engine, "hash_file_blake3", lambda path: Path(path).read_bytes().hex())

    plan = plan_projection(source, target, _profile(compare_mode="strict_blake3"))
    item = next(item for item in plan["items"] if item["rel_path"] == "a.bin")

    assert item["action"] == "copy"


def test_safe_mode_keeps_disk_auditor_fast_path_same_size_same_mtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    src = source / "a.bin"
    dst = target / "a.bin"
    src.write_bytes(b"AAAA")
    dst.write_bytes(b"BBBB")
    stamp = 1_700_000_000_123_456_789
    os.utime(src, ns=(stamp, stamp))
    os.utime(dst, ns=(stamp, stamp))

    def should_not_hash(path: Path) -> str:  # pragma: no cover - called only on regression
        raise AssertionError("safe mode must keep the quick same-size/same-mtime fast path")

    monkeypatch.setattr(projection_engine, "hash_file_blake3", should_not_hash)

    plan = plan_projection(source, target, _profile(compare_mode="safe_blake3"))
    item = next(item for item in plan["items"] if item["rel_path"] == "a.bin")

    assert item["action"] == "same"
    assert item["reason"] in {"size_and_mtime_match", "size_and_mtime_match_safe"}


def test_delete_phase_is_skipped_when_copy_phase_fails(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "new.py").write_text("print('new')\n", encoding="utf-8")
    (target / "old.py").write_text("print('old')\n", encoding="utf-8")

    plan = plan_projection(source, target, _profile(compare_mode="quick"))
    # Simulate a copy failure after planning, e.g. source disappeared or disk changed.
    (source / "new.py").unlink()

    result = apply_projection_plan(plan, dry_run=False)

    assert result["summary"]["errors"] == 1
    assert result["summary"]["delete_phase_skipped"] is True
    assert (target / "old.py").exists()


def test_source_projection_overlap_is_blocked(tmp_path: Path) -> None:
    source = tmp_path / "source"
    projection = source / "projection"
    source.mkdir()

    with pytest.raises(ValueError, match="Projection is inside source"):
        plan_projection(source, projection, _profile())


def test_protected_target_glob_protects_root_directory(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    protected = target / ".git"
    protected.mkdir()

    plan = plan_projection(source, target, _profile(include_globs=["*.md"], protected_target_globs=[".git/**"]))
    result = apply_projection_plan(plan, dry_run=False)

    assert result["summary"]["errors"] == 0
    assert protected.exists()
    assert not any(item.get("rel_path") == ".git" for item in result["details"]["deleted_dirs"])


def test_timestamp_slug_uses_microseconds() -> None:
    assert re.fullmatch(r"\d{8}_\d{6}_\d{6}", timestamp_slug())


def test_generated_gitkeep_is_removed_from_non_empty_dirs(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    (source / "docs").mkdir(parents=True)
    (target / "docs").mkdir(parents=True)
    (source / "docs" / "note.md").write_text("# Note\n", encoding="utf-8")
    (target / "docs" / ".gitkeep").write_text("", encoding="utf-8")

    plan = plan_projection(source, target, _profile(include_globs=["*.md"]))
    result = apply_projection_plan(plan, dry_run=False)

    assert result["summary"]["errors"] == 0
    assert (target / "docs" / "note.md").exists()
    assert not (target / "docs" / ".gitkeep").exists()
    assert "docs" in result["details"]["gitkeep"]["removed"]


def test_filtered_mirror_reports_scope(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "README.md").write_text("# Demo\n", encoding="utf-8")

    plan = plan_projection(source, target, _profile(include_globs=["*.md"], mirror_scope="filtered"))
    result = apply_projection_plan(plan, dry_run=True)

    assert plan["summary"]["mirror_scope"] == "filtered"
    assert plan["profile"]["mirror_scope"] == "filtered"
    assert result["summary"]["mirror_scope"] == "filtered"


def test_verify_projection_mirror_reports_digest_drift(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "same.md").write_text("same\n", encoding="utf-8")
    (target / "same.md").write_text("same\n", encoding="utf-8")
    (source / "changed.md").write_text("source\n", encoding="utf-8")
    (target / "changed.md").write_text("target\n", encoding="utf-8")
    (source / "missing.md").write_text("missing\n", encoding="utf-8")
    (target / "extra.md").write_text("extra\n", encoding="utf-8")

    result = verify_projection_mirror(source, target, _profile(include_globs=["*.md"]))

    assert result["summary"]["same"] == 1
    assert result["summary"]["changed"] == 1
    assert result["summary"]["missing"] == 1
    assert result["summary"]["extra"] == 1
    assert result["summary"]["exit_code"] == 1
    actions = {item["rel_path"]: item["action"] for item in result["items"]}
    assert actions == {
        "changed.md": "changed",
        "extra.md": "extra",
        "missing.md": "missing",
        "same.md": "same",
    }
