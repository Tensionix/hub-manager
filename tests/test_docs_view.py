from __future__ import annotations

from pathlib import Path

import pytest

from system_core.core.docs_view import docs_target
from system_core.core.project_registry import ProjectEntry
from system_core.core.projection_engine import ProjectionProfile, apply_projection_plan, plan_projection


def test_docs_target_requires_project_docs_path(tmp_path: Path) -> None:
    project = ProjectEntry(
        id="audion_hub_manager",
        title="Audion Hub Manager",
        source_path=tmp_path / "source",
        projection_path=tmp_path / "hub" / "projects" / "Audion_Hub_Manager",
        profile="audion_python_project_projection",
    )

    with pytest.raises(ValueError, match="docs_path"):
        docs_target(tmp_path / "Manager", project)


def test_project_docs_path_overrides_storage_layout_folder(tmp_path: Path) -> None:
    app = tmp_path / "Manager"
    docs = tmp_path / "Docs"
    configured_target = docs / "Projects" / "Configured"
    (app / "config").mkdir(parents=True)
    project = ProjectEntry(
        id="configured",
        title="Configured",
        source_path=tmp_path / "source",
        projection_path=tmp_path / "hub" / "Configured",
        profile="audion_python_project_projection",
        docs_path=configured_target,
    )

    assert docs_target(app, project) == configured_target


def test_docs_profile_copies_docs_only_without_gitkeep(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "docs" / "Projects" / "Demo"
    (source / "docs" / "empty").mkdir(parents=True)
    (source / "README.md").write_text("# Demo\n", encoding="utf-8")
    (source / "docs" / "note.txt").write_text("note\n", encoding="utf-8")
    (source / "config").mkdir()
    (source / "config" / "settings.json").write_text("{}\n", encoding="utf-8")
    (source / "system_core").mkdir()
    (source / "system_core" / "main.py").write_text("print('skip')\n", encoding="utf-8")
    (source / "system_core" / "license").mkdir()
    (source / "system_core" / "license" / "LICENSE.txt").write_text("skip license\n", encoding="utf-8")
    (source / ".pytest_cache").mkdir()
    (source / ".pytest_cache" / "README.md").write_text("skip cache\n", encoding="utf-8")

    profile = ProjectionProfile(
        id="markdown_only_projection",
        include_globs=["*.md", "*.markdown", "*.txt", "*.rst"],
        exclude_globs=["*.json", "*.py"],
        hide_dirs=[".pytest_cache"],
        exclude_dir_contents=["runtime", "wheelhouse", "logs", "output", "backup", "system_core", "tests", "config"],
        preserve_empty_dirs=False,
        compare_mode="quick",
    )
    plan = plan_projection(source, target, profile)
    result = apply_projection_plan(plan, dry_run=False)

    assert result["summary"]["errors"] == 0
    assert (target / "README.md").exists()
    assert (target / "docs" / "note.txt").exists()
    assert not (target / "docs" / "empty").exists()
    assert not (target / "config" / "settings.json").exists()
    assert not (target / "system_core" / "main.py").exists()
    assert not (target / "system_core" / "license" / "LICENSE.txt").exists()
    assert not (target / ".pytest_cache" / "README.md").exists()
    assert not list(target.rglob(".gitkeep"))
