from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import os

from system_core.core.config import load_yaml_or_json

# The roots this machine chose over the shipped layout - the folder of the live projects. Not in git and taken by the
# release cleaner (*.local.json): a release carries the layout of the program, not of the machine it was made on.
LOCAL_FILE = "storage_layout.local.json"


def _resolve_root(value: Any, app_root: Path, default: Path) -> Path:
    """A root of the layout: ${APP_ROOT} is the program folder for every root, `..` is folded; empty - the default."""
    text = str(value or "").strip()
    if not text:
        return default
    text = text.replace("${APP_ROOT}", str(app_root))
    return Path(os.path.normpath(Path(text).expanduser()))


def _normalized(path: Path) -> str:
    return str(path.resolve()).rstrip("\\/").lower()


def _same_or_inside(path: Path, parent: Path) -> bool:
    child_text = _normalized(path)
    parent_text = _normalized(parent)
    return child_text == parent_text or child_text.startswith(parent_text + "\\") or child_text.startswith(parent_text + "/")


def _project_counts_for_layout(project_id: str) -> bool:
    """The demo and the Git lab keep their copies inside the program and are not held to the layout."""
    value = str(project_id).strip().lower()
    return not (value.startswith("demo") or value.startswith("sample") or value.startswith("lab_"))


def _local_roots(root: Path) -> dict[str, Any]:
    try:
        data = load_yaml_or_json(root / "config" / LOCAL_FILE)
    except (ValueError, OSError):
        return {}  # a broken file of the machine must not take the layout down: the shipped roots stand
    roots = data.get("roots") if isinstance(data, dict) else None
    return dict(roots) if isinstance(roots, dict) else {}


def _resolved(roots: dict[str, Any], root: Path) -> dict[str, Path]:
    return {
        "manager_root": _resolve_root(roots.get("manager_root"), root, root),
        "hub_data_root": _resolve_root(roots.get("hub_data_root"), root, root.parent / "Hub Data"),
        "docs_root": _resolve_root(roots.get("docs_root", roots.get("obsidian" + "_vault_root")), root, root.parent / "Hub Docs"),
        "full_projects_root": _resolve_root(roots.get("full_projects_root"), root, root.parent),
    }


def layout_roots(root: Path, *, shipped: bool = False) -> dict[str, Path]:
    """The roots as paths, without the checks of storage_layout_status - for whom only needs where they are (the
    registry lies in the root of the projects). `shipped` - the roots of the program, without the choice of this machine."""
    root = root.resolve()
    try:
        data = load_yaml_or_json(root / "config" / "storage_layout.json") if shipped else load_storage_layout(root)
    except (ValueError, OSError):
        data = {}
    roots = data.get("roots", {}) if isinstance(data, dict) else {}
    return _resolved(roots if isinstance(roots, dict) else {}, root)


def load_storage_layout(root: Path) -> dict[str, Any]:
    data = load_yaml_or_json(root / "config" / "storage_layout.json")
    local = _local_roots(root)
    if local and isinstance(data, dict):
        data = {**data, "roots": {**(data.get("roots") or {}), **local}}
    return data


def set_projects_root(root: Path, folder: str | None) -> dict[str, Any]:
    """Makes `folder` the root of the live projects of this machine; None gives the shipped root back.

    Written into config/storage_layout.local.json - beside the program, so the choice moves with it: a folder beside the
    program is kept as ${APP_ROOT}/.., one elsewhere in full. The root may not lie inside the GIT COPIES or DOCS.
    """
    root = root.resolve()
    local_file = root / "config" / LOCAL_FILE
    local = _local_roots(root)
    if folder is None:
        local.pop("full_projects_root", None)
    else:
        path = Path(os.path.normpath(Path(folder).expanduser()))
        if not path.is_dir():
            raise ValueError(f"not a folder: {path}")
        status = storage_layout_status(root)
        for key in ("hub_data_root", "docs_root"):
            other = Path(status["roots"][key]["path"])
            if _same_or_inside(path, other):
                raise ValueError(f"{path} lies inside the {key.replace('_root', '').replace('_', ' ')} root {other}: projects live beside it, not in it")
        beside = root.parent
        if _normalized(path) == _normalized(beside):
            value = "${APP_ROOT}/.."
        elif _same_or_inside(path, beside):
            value = "${APP_ROOT}/../" + path.resolve().relative_to(beside.resolve()).as_posix()
        else:
            value = str(path)
        local["full_projects_root"] = value
    if local:
        local_file.write_text(json.dumps({"roots": local}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    elif local_file.exists():
        local_file.unlink()
    return storage_layout_status(root)


def storage_layout_status(root: Path, projects: list[Any] | None = None) -> dict[str, Any]:
    root = root.resolve()
    data = load_storage_layout(root)
    roots = data.get("roots", {}) if isinstance(data, dict) else {}
    roles = data.get("roles", {}) if isinstance(data, dict) else {}
    chosen_here = set(_local_roots(root))
    resolved = _resolved(roots, root)

    root_status = {
        key: {
            "path": str(path),
            "exists": path.exists(),
            "is_dir": path.is_dir(),
            "role": str(roles.get(key, "")),
            # Chosen on this machine (config/storage_layout.local.json) rather than shipped with the program.
            "chosen_here": key in chosen_here,
        }
        for key, path in resolved.items()
    }
    root_status["full_projects_root"]["shipped"] = str(layout_roots(root, shipped=True)["full_projects_root"])

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

    # The docs root is needed only when a project keeps a DOCS layer.
    uses_docs = any(item["docs_configured"] for item in project_status if _project_counts_for_layout(str(item["id"])))
    root_ok = all(item["exists"] and item["is_dir"] for key, item in root_status.items() if key != "docs_root" or uses_docs)
    separation_ok = all(separation.values())
    counted = [item for item in project_status if _project_counts_for_layout(str(item["id"]))]
    # The projects the layout does not hold, by what is off: no SOURCE folder, a GIT COPY outside the GIT COPIES root,
    # a DOCS outside its root (DOCS is optional: a project without it is fine).
    off_layout = {
        "source": [item["id"] for item in counted if not (item["source_exists"] and item["source_is_dir"])],
        "projection": [item["id"] for item in counted if not item["projection_under_hub"]],
        "docs": [item["id"] for item in counted if item["docs_configured"] and not item["docs_under_root"]],
    }

    return {
        "ok": bool(root_ok and separation_ok and not any(off_layout.values())),
        "layout_version": data.get("layout_version") if isinstance(data, dict) else None,
        "roots": root_status,
        "separation": separation,
        "projects": project_status,
        "off_layout": off_layout,
        "warnings": [
            "Storage view reports project paths from the registry; it must not invent projection or Docs targets.",
            "Projection and Docs folders may be absent before the first apply; DOCS is optional for a project.",
        ],
    }
