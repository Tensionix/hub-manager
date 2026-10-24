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


def test_the_mirror_leaves_out_what_the_project_gitignore_hides(tmp_path: Path) -> None:
    import subprocess

    # The source lies inside another repository whose .gitignore would hide its README: only its own one counts.
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("*.md\n", encoding="utf-8")
    source, target = tmp_path / "source", tmp_path / "target"
    for rel in ("README.md", "src/app.py", "build-ui/src/moc_app.py", "config/api_key.py", "sub/notes.py"):
        (source / rel).parent.mkdir(parents=True, exist_ok=True)
        (source / rel).write_text("x\n", encoding="utf-8")
    (source / ".gitignore").write_text("build*/\nconfig/api_key.py\n", encoding="utf-8")
    (source / "sub" / ".gitignore").write_text("notes.py\n", encoding="utf-8")
    profile = ProjectionProfile(id="test", include_globs=["*.md", "*.py", ".gitignore"], preserve_empty_dirs=False, compare_mode="quick")

    plan = plan_projection(source, target, profile)
    copied = sorted(item["rel_path"] for item in plan["items"] if item["action"] == "copy")
    assert copied == [".gitignore", "README.md", "src/app.py", "sub/.gitignore"]
    scan = plan["summary"]["source_scan"]
    assert scan["skipped_by_gitignore"] == 2 and scan["gitignored_dirs"] >= 1, scan

    profile.respect_gitignore = False
    copied = {item["rel_path"] for item in plan_projection(source, target, profile)["items"] if item["action"] == "copy"}
    assert {"build-ui/src/moc_app.py", "config/api_key.py", "sub/notes.py"} <= copied


def test_folder_guesses_give_way_to_the_project_gitignore_and_text_without_extension_passes(tmp_path: Path) -> None:
    # Next.js keeps its pages in app/, Electron its icons in build/, fzf its scripts in bin/ and install without extension.
    profile = ProjectionProfile(id="test", include_globs=["*.tsx", "*.png", ".gitignore"], output_dirs=["/app", "build", "bin"],
                                extensionless_text_bytes=4096, preserve_empty_dirs=False, compare_mode="quick")
    source = tmp_path / "web"
    for rel, data in (("app/page.tsx", b"x"), ("build/icon.png", b"x"), ("bin/fzf-tmux", b"#!/bin/sh\n"), ("install", b"#!/bin/sh\n"),
                      ("tool", b"MZ\x00\x00binary"), ("out/main.js", b"x")):
        (source / rel).parent.mkdir(parents=True, exist_ok=True)
        (source / rel).write_bytes(data)

    def copied() -> set[str]:
        return {i["rel_path"] for i in plan_projection(source, tmp_path / "copy", profile)["items"] if i["action"] == "copy"}

    # No .gitignore: the guesses hold; a text without extension passes, a binary does not.
    assert copied() == {"install"}
    # With one, the project's word decides what is a build.
    (source / ".gitignore").write_text("out/\n", encoding="utf-8")
    assert copied() == {".gitignore", "app/page.tsx", "build/icon.png", "bin/fzf-tmux", "install"}


def test_a_gitkeep_of_the_project_is_a_file_when_the_profile_puts_no_markers(tmp_path: Path) -> None:
    # hono keeps perf-measures/*/generated/.gitkeep in its history: copied once, then the same - not "missing" for ever.
    from system_core.core.projection_engine import verify_projection_mirror

    source, target = tmp_path / "source", tmp_path / "target"
    (source / "generated").mkdir(parents=True)
    (source / "generated" / ".gitkeep").write_bytes(b"")
    (source / "README.md").write_text("# x\n", encoding="utf-8")
    profile = ProjectionProfile(id="test", include_globs=["*.md", ".gitkeep"], preserve_empty_dirs=False, compare_mode="quick")
    apply_projection_plan(plan_projection(source, target, profile), dry_run=False)
    assert (target / "generated" / ".gitkeep").is_file()
    assert verify_projection_mirror(source, target, profile)["summary"]["missing"] == 0
    assert not any(i["action"] == "copy" for i in plan_projection(source, target, profile)["items"])


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
