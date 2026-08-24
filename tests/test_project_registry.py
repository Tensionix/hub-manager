from __future__ import annotations

from system_core.core.project_registry import ProjectEntry
from system_core.core.paths import get_project_paths


def test_project_entry_reads_legacy_docs_path_keys() -> None:
    project = ProjectEntry.from_dict(
        {
            "id": "legacy",
            "title": "Legacy",
            "source_path": "source",
            "projection_path": "hub",
            "profile": "audion_python_project_projection",
            "obsidian_path": "docs",
            "obsidian_vault_name": "Old App",
            "obsidian_file": "README.md",
        }
    )

    assert str(project.docs_path).endswith("docs")
    assert project.docs_app_name == "Old App"
    assert project.docs_file == "README.md"
    assert "docs_path" in project.to_dict()
    assert "obsidian_path" not in project.to_dict()


def test_project_entry_resolves_relative_paths_from_manager_root() -> None:
    root = get_project_paths().root

    project = ProjectEntry.from_dict(
        {
            "id": "portable",
            "title": "Portable",
            "source_path": "examples/demo_full_project",
            "projection_path": "examples/demo_hub_projection/Portable",
            "profile": "audion_python_project_projection",
            "docs_path": "docs/Portable",
        }
    )

    assert project.source_path == root / "examples/demo_full_project"
    assert project.projection_path == root / "examples/demo_hub_projection/Portable"
    assert project.docs_path == root / "docs/Portable"
