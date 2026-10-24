from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import os

from .json_utils import load_json_safe, save_json
from .paths import get_project_paths

# The registry lies in the root of the projects it names (the owner, 25.10.2026: "реестр в корне"): another root, another
# registry; the program carries none of its own.
REGISTRY_FILE = "hub_projects.json"
PATH_KEYS = ("source_path", "projection_path", "docs_path")


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
    def from_dict(cls, data: dict[str, Any], base: Path | None = None) -> "ProjectEntry":
        """A record of a registry; its relative paths are read from `base` - the folder of the registry file, or with no
        file the program folder."""
        paths = get_project_paths()
        base = base or paths.root
        project_id = str(data.get("id", "")).strip()
        title = str(data.get("title", data.get("id", "Untitled"))).strip()
        source_text = str(data.get("source_path", "")).strip()
        projection_text = str(data.get("projection_path", "")).strip()
        legacy_path_key = "obsidian" + "_path"
        legacy_app_key = "obsidian" + "_vault_name"
        legacy_file_key = "obsidian" + "_file"
        docs_text = str(data.get("docs_path", data.get(legacy_path_key, ""))).strip()
        # A record without its GIT COPY gets the folder a scan would give it: Hub Data beside the program, by its title.
        folder = "".join("_" if ch in '<>:"/\\|?*' else ch for ch in title).strip(" .") or project_id or "Project"
        return cls(
            id=project_id,
            title=title,
            source_path=(_portable_existing_path(Path(source_text), base) if source_text else paths.root),
            projection_path=(
                _portable_existing_path(Path(projection_text), base)
                if projection_text
                else paths.root.parent / "Hub Data" / folder
            ),
            profile=str(data.get("profile", "audion_python_project_projection")).strip(),
            default_branch=str(data.get("default_branch", "main")).strip() or "main",
            docs_app_name=str(data.get("docs_app_name", data.get(legacy_app_key, ""))).strip(),
            docs_file=str(data.get("docs_file", data.get(legacy_file_key, ""))).strip(),
            docs_path=(_portable_existing_path(Path(docs_text), base) if docs_text else None),
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


def path_value(path: Path, base: Path) -> str:
    """How a path is written into a registry: inside its folder (the root of the projects) relative to it - the root and
    its projects move together, to another folder or disk; anywhere else as it is."""
    full = Path(os.path.normpath(path.expanduser()))
    try:
        relative = full.resolve(strict=False).relative_to(base.resolve(strict=False))
        return "." if str(relative) == "." else relative.as_posix()
    except (ValueError, OSError):
        return str(full)


def rebase_record(item: dict[str, Any], old_base: Path, new_base: Path) -> dict[str, Any]:
    """A record moved from one registry to another: each path read from where it was, written for where it goes."""
    moved = dict(item)
    for key in PATH_KEYS:
        text = str(item.get(key, "") or "").strip()
        if text:
            path = Path(text).expanduser()
            moved[key] = path_value(path if path.is_absolute() else old_base / path, new_base)
    return moved


def registry_path(app_root: Path | None = None) -> Path:
    """<the root of the projects>/hub_projects.json. Missing, it is made: from the registry the program kept in itself
    before (config/projects.json - moved here with its paths, then removed); for the shipped root from
    projects.example.json, the registry a fresh program comes with; for a root of the person's own - empty."""
    from .storage_layout import layout_roots

    paths = get_project_paths(app_root)
    base = layout_roots(paths.root)["full_projects_root"]
    path = base / REGISTRY_FILE
    if path.exists():
        return path
    legacy = paths.config / "projects.json"
    example = paths.config / "projects.example.json"
    shipped_root = os.path.normcase(str(layout_roots(paths.root, shipped=True)["full_projects_root"]))
    source = legacy if legacy.is_file() else example if example.is_file() and os.path.normcase(str(base)) == shipped_root else None
    payload: dict[str, Any] = {"active_project_id": "", "projects": []}
    if source is not None:
        loaded, error = load_json_safe(source, default=payload)
        if error or not isinstance(loaded, dict):
            # A registry that does not read is not moved: the load reports what is wrong with it, nothing is lost.
            return legacy if source == legacy else path
        items = loaded.get("projects", [])
        payload = {**loaded, "projects": [rebase_record(item, paths.root, base) for item in items if isinstance(item, dict)]
                   if isinstance(items, list) else []}
    try:
        base.mkdir(parents=True, exist_ok=True)
        save_json(path, payload)
    except OSError:
        return path
    if source == legacy:
        legacy.unlink(missing_ok=True)
    return path


def load_project_registry(path: Path | None = None) -> ProjectRegistry:
    config_path = path or registry_path()
    payload, error = load_json_safe(config_path, default={"active_project_id": "", "projects": []})
    if not isinstance(payload, dict):
        payload, error = {"active_project_id": "", "projects": []}, error or f"{config_path.name}: expected an object"
    # The legacy registry inside the program read its paths from the program folder; any other from its own folder.
    base = get_project_paths().root if config_path.name == "projects.json" and config_path.parent.name == "config" else config_path.parent
    entries = payload.get("projects", [])
    projects: list[ProjectEntry] = []
    for item in entries if isinstance(entries, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            projects.append(ProjectEntry.from_dict(item, base))
        except Exception as exc:  # one broken record must not hide the rest
            error = error or f"{config_path.name}: skipped a project record ({exc.__class__.__name__})"
    return ProjectRegistry(
        active_project_id=str(payload.get("active_project_id", "")).strip(),
        projects=projects,
        load_error=error,
    )
