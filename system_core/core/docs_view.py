from __future__ import annotations

from pathlib import Path
from typing import Any

from system_core.core.project_registry import ProjectEntry
from system_core.core.projection_engine import get_projection_profile, plan_projection


DOCS_VIEW_PROFILE_ID = "markdown_only_projection"


def docs_target(app_root: Path, project: ProjectEntry) -> Path:
    if project.docs_path is not None:
        return project.docs_path.expanduser()
    raise ValueError(f"Project '{project.id}' has no docs_path configured in projects.json")


def plan_docs_view(app_root: Path, project: ProjectEntry) -> dict[str, Any]:
    profile = get_projection_profile(DOCS_VIEW_PROFILE_ID)
    return plan_projection(project.source_path, docs_target(app_root, project), profile)
