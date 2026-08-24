from __future__ import annotations

from pathlib import Path

from system_core.core.projection_engine import ProjectionProfile, apply_projection_plan, plan_projection


def test_projection_mirror_preserves_empty_service_dirs(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    (source / "system_core" / "app").mkdir(parents=True)
    (source / "logs").mkdir()
    (source / "output").mkdir()
    (source / "runtime" / "Lib").mkdir(parents=True)
    (source / "README.md").write_text("# Demo\n", encoding="utf-8")
    (source / "system_core" / "app" / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (source / "logs" / "debug.log").write_text("skip me\n", encoding="utf-8")
    (source / "runtime" / "python.exe").write_text("skip me\n", encoding="utf-8")
    target.mkdir(parents=True)
    (target / "old.py").write_text("old\n", encoding="utf-8")

    profile = ProjectionProfile(
        id="test",
        include_globs=["*.md", "*.py"],
        exclude_globs=["*.log", "*.exe"],
        hide_dirs=[".git", "__pycache__"],
        exclude_dir_contents=["logs", "output", "runtime"],
        preserve_empty_dirs=True,
        compare_mode="quick",
    )
    plan = plan_projection(source, target, profile)
    result = apply_projection_plan(plan, dry_run=False)

    assert result["summary"]["errors"] == 0
    assert (target / "README.md").exists()
    assert (target / "system_core" / "app" / "main.py").exists()
    assert not (target / "old.py").exists()
    assert (target / "logs" / ".gitkeep").exists()
    assert not (target / "logs" / "debug.log").exists()
    assert (target / "output" / ".gitkeep").exists()
    assert (target / "runtime" / ".gitkeep").exists()
    assert not (target / "runtime" / "python.exe").exists()


def test_strict_blake3_detects_same_size_same_mtime_different_content(tmp_path: Path, monkeypatch) -> None:
    from system_core.core import projection_engine as engine

    def fake_hash(path: Path) -> str:
        return path.read_bytes().hex()

    monkeypatch.setattr(engine, "hash_file_blake3", fake_hash)

    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    src = source / "a.bin"
    dst = target / "a.bin"
    src.write_bytes(b"AAAA")
    dst.write_bytes(b"BBBB")
    same_ns = 1_700_000_000_000_000_000
    os_utime = __import__("os").utime
    os_utime(src, ns=(same_ns, same_ns))
    os_utime(dst, ns=(same_ns, same_ns))

    profile = ProjectionProfile(id="strict", include_globs=["*.bin"], compare_mode="strict_blake3")
    plan = plan_projection(source, target, profile)
    items = [item for item in plan["items"] if item["rel_path"] == "a.bin"]

    assert len(items) == 1
    assert items[0]["action"] == "copy"
    assert items[0]["reason"] == "content_or_metadata_diff"


def test_delete_phase_is_skipped_after_copy_errors(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    stale = target / "stale.txt"
    stale.write_text("do not delete if copy failed\n", encoding="utf-8")

    plan = {
        "source_root": str(source),
        "projection_root": str(target),
        "source_dirs": [],
        "profile": ProjectionProfile(id="manual", include_globs=["*.txt"]).to_json(),
        "items": [
            {
                "action": "copy",
                "rel_path": "missing.txt",
                "source": {"abs_path": str(source / "missing.txt"), "size": 10, "mtime_ns": 0},
                "target": None,
            },
            {
                "action": "delete",
                "rel_path": "stale.txt",
                "source": None,
                "target": {"abs_path": str(stale), "size": stale.stat().st_size, "mtime_ns": stale.stat().st_mtime_ns},
            },
        ],
    }

    result = apply_projection_plan(plan, dry_run=False)

    assert result["summary"]["errors"] == 1
    assert stale.exists()
    assert any(item.get("reason") == "delete_phase_skipped_after_errors_or_conflicts" for item in result["details"]["skipped"])


def test_small_license_files_can_be_included_without_opening_runtime_noise(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    (source / "licenses" / "pkg").mkdir(parents=True)
    (source / "runtime").mkdir()
    (source / "licenses" / "pkg" / "LICENSE").write_text("license\n", encoding="utf-8")
    (source / "runtime" / "LICENSE").write_text("runtime noise\n", encoding="utf-8")
    (source / "README.md").write_text("# Demo\n", encoding="utf-8")

    profile = ProjectionProfile(
        id="licenses",
        include_globs=["*.md"],
        small_include_globs=["licenses/**/LICENSE*"],
        small_include_max_file_bytes=100 * 1024,
        exclude_dir_contents=["runtime"],
        compare_mode="quick",
    )
    plan = plan_projection(source, target, profile)
    result = apply_projection_plan(plan, dry_run=False)

    assert result["summary"]["errors"] == 0
    assert (target / "README.md").exists()
    assert (target / "licenses" / "pkg" / "LICENSE").exists()
    assert not (target / "runtime" / "LICENSE").exists()


def test_forbidden_dirs_are_purged_from_projection(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    (source / "_pwsh_tmp").mkdir(parents=True)
    (target / "_pwsh_tmp").mkdir(parents=True)
    (source / "_pwsh_tmp" / "new.txt").write_text("skip\n", encoding="utf-8")
    (target / "_pwsh_tmp" / "old.txt").write_text("delete\n", encoding="utf-8")
    (source / "README.md").write_text("# Demo\n", encoding="utf-8")

    profile = ProjectionProfile(
        id="forbidden",
        include_globs=["*.md", "*.txt"],
        forbidden_dirs=["_pwsh_tmp"],
        preserve_empty_dirs=True,
        compare_mode="quick",
    )
    plan = plan_projection(source, target, profile)
    result = apply_projection_plan(plan, dry_run=False)

    assert result["summary"]["errors"] == 0
    assert (target / "README.md").exists()
    assert not (target / "_pwsh_tmp").exists()
