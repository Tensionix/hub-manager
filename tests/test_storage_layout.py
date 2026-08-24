from __future__ import annotations

import json
from pathlib import Path

from system_core.core.project_registry import ProjectEntry
from system_core.core.storage_layout import storage_layout_status


def test_storage_layout_status_accepts_separate_roots(tmp_path: Path) -> None:
    app = tmp_path / "Manager"
    hub = tmp_path / "Hub Git"
    docs = tmp_path / "Docs"
    projects = tmp_path / "TOOLS"
    source = projects / "Demo"
    projection = hub / "projects" / "Demo"
    docs_project = docs / "Projects" / "Demo"
    for path in [app / "config", hub, docs, source, projection.parent, docs_project]:
        path.mkdir(parents=True)
    (app / "config" / "storage_layout.json").write_text(
        json.dumps(
            {
                "layout_version": 1,
                "roots": {
                    "manager_root": "${APP_ROOT}",
                    "hub_data_root": str(hub),
                    "docs_root": str(docs),
                    "full_projects_root": str(projects),
                },
            }
        ),
        encoding="utf-8",
    )

    result = storage_layout_status(
        app,
        [
            ProjectEntry(
                id="real_project",
                title="Demo",
                source_path=source,
                projection_path=projection,
                docs_path=docs_project,
                profile="audion_python_project_projection",
            )
        ],
    )

    assert result["ok"] is True
    assert result["roots"]["hub_data_root"]["exists"] is True
    assert result["roots"]["docs_root"]["exists"] is True
    assert result["separation"]["hub_not_inside_docs"] is True
    assert result["projects"][0]["projection_under_hub"] is True
    assert result["projects"][0]["docs_under_root"] is True


def test_storage_layout_status_rejects_projection_outside_hub(tmp_path: Path) -> None:
    app = tmp_path / "Manager"
    hub = tmp_path / "Hub Git"
    docs = tmp_path / "Docs"
    projects = tmp_path / "TOOLS"
    source = projects / "Demo"
    projection = tmp_path / "Wrong Hub" / "Demo"
    docs_project = docs / "Projects" / "Demo"
    for path in [app / "config", hub, docs, source, projects, docs_project]:
        path.mkdir(parents=True, exist_ok=True)
    (app / "config" / "storage_layout.json").write_text(
        json.dumps(
            {
                "layout_version": 1,
                "roots": {
                    "manager_root": "${APP_ROOT}",
                    "hub_data_root": str(hub),
                    "docs_root": str(docs),
                    "full_projects_root": str(projects),
                },
            }
        ),
        encoding="utf-8",
    )

    result = storage_layout_status(
        app,
        [
            ProjectEntry(
                id="real_project",
                title="Demo",
                source_path=source,
                projection_path=projection,
                docs_path=docs_project,
                profile="audion_python_project_projection",
            )
        ],
    )

    assert result["ok"] is False
    assert result["projects"][0]["projection_under_hub"] is False
