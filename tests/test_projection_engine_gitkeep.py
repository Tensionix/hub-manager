from __future__ import annotations

from pathlib import Path

from system_core.core.projection_engine import ProjectionProfile, apply_projection_plan, plan_projection


def test_projection_preserves_empty_dirs_with_gitkeep(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    (source / "logs").mkdir(parents=True)
    (source / "system_core").mkdir()
    (source / "system_core" / "main.py").write_text("print('ok')\n", encoding="utf-8")

    profile = ProjectionProfile(
        id="test",
        include_globs=["*.py", "*.md"],
        exclude_dir_contents=["logs"],
        hide_dirs=[".git", "__pycache__"],
        preserve_empty_dirs=True,
        compare_mode="quick",
    )
    plan = plan_projection(source, target, profile)
    result = apply_projection_plan(plan, dry_run=False)

    assert (target / "system_core" / "main.py").exists()
    assert (target / "logs" / ".gitkeep").exists()
    assert result["summary"]["errors"] == 0
