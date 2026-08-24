from __future__ import annotations

from pathlib import Path
from typing import Any

from system_core.core.config import load_yaml_or_json


def _resolve_root(value: Any, app_root: Path) -> Path:
    text = str(value or "").strip()
    if not text:
        return app_root
    text = text.replace("${APP_ROOT}", str(app_root))
    return Path(text).expanduser()


def _normalized(path: Path) -> str:
    return str(path.resolve()).rstrip("\\/").lower()


def _same_or_inside(path: Path, parent: Path) -> bool:
    child_text = _normalized(path)
    parent_text = _normalized(parent)
    return child_text == parent_text or child_text.startswith(parent_text + "\\") or child_text.startswith(parent_text + "/")


def _project_counts_for_layout(project_id: str) -> bool:
    value = str(project_id).strip().lower()
    return not (value.startswith("demo") or value.startswith("sample"))


def load_storage_layout(root: Path) -> dict[str, Any]:
    return load_yaml_or_json(root / "config" / "storage_layout.json")


def storage_layout_status(root: Path, projects: list[Any] | None = None) -> dict[str, Any]:
    root = root.resolve()
    data = load_storage_layout(root)
    roots = data.get("roots", {}) if isinstance(data, dict) else {}
    roles = data.get("roles", {}) if isinstance(data, dict) else {}

    resolved = {
        "manager_root": _resolve_root(roots.get("manager_root"), root),
        "hub_data_root": _resolve_root(roots.get("hub_data_root"), root.parent / "Hub Data"),
        "docs_root": _resolve_root(roots.get("docs_root", roots.get("obsidian" + "_vault_root")), root.parent / "Docs"),
        "full_projects_root": _resolve_root(roots.get("full_projects_root"), root.parent),
    }

    root_status = {
        key: {
            "path": str(path),
            "exists": path.exists(),
            "is_dir": path.is_dir(),
            "role": str(roles.get(key, "")),
        }
        for key, path in resolved.items()
    }

    hub = resolved["hub_data_root"]
    docs = resolved["docs_root"]
    manager = resolved["manager_root"]
    full_projects = resolved["full_projects_root"]
    separation = {
        "hub_not_inside_docs": not _same_or_inside(hub, docs),
        "docs_not_inside_hub": not _same_or_inside(docs, hub),
        "manager_not_inside_hub": not _same_or_inside(manager, hub),
        "manager_not_inside_docs": not _same_or_inside(manager, docs),
        "full_projects_not_inside_hub": not _same_or_inside(full_projects, hub),
        "full_projects_not_inside_docs": not _same_or_inside(full_projects, docs),
    }

    project_status = []
    for project in projects or []:
        source_path = Path(project.source_path).expanduser()
        projection_path = Path(project.projection_path).expanduser()
        docs_path = Path(project.docs_path).expanduser() if getattr(project, "docs_path", None) is not None else None
        project_status.append(
            {
                "id": project.id,
                "title": project.title,
                "source_path": str(source_path),
                "source_exists": source_path.exists(),
                "source_is_dir": source_path.is_dir(),
                "projection_path": str(projection_path),
                "projection_exists": projection_path.exists(),
                "projection_under_hub": _same_or_inside(projection_path, hub),
                "docs_path": str(docs_path or ""),
                "docs_configured": docs_path is not None,
                "docs_exists": bool(docs_path and docs_path.exists()),
                "docs_under_root": bool(docs_path and _same_or_inside(docs_path, docs)),
            }
        )

    root_ok = all(item["exists"] and item["is_dir"] for item in root_status.values())
    separation_ok = all(separation.values())
    project_sources_ok = all(
        item["source_exists"] and item["source_is_dir"]
        for item in project_status
        if _project_counts_for_layout(str(item["id"]))
    )
    project_projection_ok = all(
        item["projection_under_hub"]
        for item in project_status
        if _project_counts_for_layout(str(item["id"]))
    )
    project_docs_ok = all(
        item["docs_configured"] and item["docs_under_root"]
        for item in project_status
        if _project_counts_for_layout(str(item["id"]))
    )

    return {
        "ok": bool(root_ok and separation_ok and project_sources_ok and project_projection_ok and project_docs_ok),
        "layout_version": data.get("layout_version") if isinstance(data, dict) else None,
        "roots": root_status,
        "separation": separation,
        "projects": project_status,
        "warnings": [
            "Storage view reports project paths from projects.json; it must not invent projection or Docs targets.",
            "Projection and Docs folders may be absent before first apply, but their paths must be configured in projects.json.",
        ],
    }
