from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .json_utils import load_json_safe
from .paths import get_project_paths


def _portable_existing_path(path: Path, current_root: Path) -> Path:
    path = path.expanduser()
    if not path.is_absolute():
        return (current_root / path).resolve(strict=False)
    if path.exists():
        return path
    current_drive = current_root.drive
    if path.drive and current_drive and path.drive.lower() != current_drive.lower():
        candidate = Path(current_drive + "\\", *path.parts[1:])
        if candidate.exists():
            return candidate
    return path


@dataclass(frozen=True)
class ProjectEntry:
    id: str
    title: str
    source_path: Path
    projection_path: Path
    profile: str
    default_branch: str = "main"
    docs_app_name: str = ""
    docs_file: str = ""
    docs_path: Path | None = None
    vscode_workspace: str = ""
    notes: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectEntry":
        paths = get_project_paths()
        project_id = str(data.get("id", "")).strip()
        title = str(data.get("title", data.get("id", "Untitled"))).strip()
        source_text = str(data.get("source_path", "")).strip()
        projection_text = str(data.get("projection_path", "")).strip()
        legacy_path_key = "obsidian" + "_path"
        legacy_app_key = "obsidian" + "_vault_name"
        legacy_file_key = "obsidian" + "_file"
        docs_text = str(data.get("docs_path", data.get(legacy_path_key, ""))).strip()
        safe_title = "".join(ch if ch.isalnum() else "_" for ch in title).strip("_") or project_id or "Project"
        return cls(
            id=project_id,
            title=title,
            source_path=(_portable_existing_path(Path(source_text), paths.root) if source_text else paths.root),
            projection_path=(
                _portable_existing_path(Path(projection_text), paths.root)
                if projection_text
                else paths.root.parent / "Hub Data" / "projects" / safe_title
            ),
            profile=str(data.get("profile", "audion_python_project_projection")).strip(),
            default_branch=str(data.get("default_branch", "main")).strip() or "main",
            docs_app_name=str(data.get("docs_app_name", data.get(legacy_app_key, ""))).strip(),
            docs_file=str(data.get("docs_file", data.get(legacy_file_key, ""))).strip(),
            docs_path=(_portable_existing_path(Path(docs_text), paths.root) if docs_text else None),
            vscode_workspace=str(data.get("vscode_workspace", "")).strip(),
            notes=str(data.get("notes", "")).strip(),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "title": self.title,
            "source_path": str(self.source_path),
            "projection_path": str(self.projection_path),
            "profile": self.profile,
            "default_branch": self.default_branch,
            "docs_app_name": self.docs_app_name,
            "docs_file": self.docs_file,
            "docs_path": str(self.docs_path or ""),
            "vscode_workspace": self.vscode_workspace,
            "notes": self.notes,
        }


def fallback_project() -> ProjectEntry:
    """A usable entry when the registry is empty or unreadable.

    Points at the Hub Manager folder itself, so the GUI opens and can be used to
    fix the config instead of refusing to start.
    """
    return ProjectEntry.from_dict({"id": "unconfigured", "title": "Hub Manager", "source_path": "."})


@dataclass(frozen=True)
class ProjectRegistry:
    active_project_id: str
    projects: list[ProjectEntry]
    load_error: str = ""

    def by_id(self, project_id: str) -> ProjectEntry:
        for project in self.projects:
            if project.id == project_id:
                return project
        raise KeyError(f"Project not found: {project_id}")

    def active_project(self) -> ProjectEntry:
        if self.active_project_id:
            try:
                return self.by_id(self.active_project_id)
            except KeyError:
                pass
        if not self.projects:
            return fallback_project()
        return self.projects[0]


def load_project_registry(path: Path | None = None) -> ProjectRegistry:
    paths = get_project_paths()
    config_path = path or paths.config / "projects.json"
    payload, error = load_json_safe(config_path, default={"active_project_id": "", "projects": []})
    if not isinstance(payload, dict):
        payload, error = {"active_project_id": "", "projects": []}, error or f"{config_path.name}: expected an object"
    entries = payload.get("projects", [])
    projects: list[ProjectEntry] = []
    for item in entries if isinstance(entries, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            projects.append(ProjectEntry.from_dict(item))
        except Exception as exc:  # one broken record must not hide the rest
            error = error or f"{config_path.name}: skipped a project record ({exc.__class__.__name__})"
    return ProjectRegistry(
        active_project_id=str(payload.get("active_project_id", "")).strip(),
        projects=projects,
        load_error=error,
    )
