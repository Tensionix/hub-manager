"""Hub Manager's own operations, without a window: the registry, the profile check of paths, the
batches over every project, the VS Code workspaces, the BLAKE3 probe, the lab.

Until 2.0.0 these lived inside the NiceGUI window (app.py) and could not be run without it. The
console command (system_core/cli.py) and through it the window on Avalonia call them here.
Each returns a JSON-ready dict; none prints.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable
import ctypes
import os
import subprocess

from .copy_engine import hash_file_blake3
from .git_engine import status as git_status
from .json_utils import load_json_safe, save_json
from .mask_engine import include_file, match_dir_rule, norm_rel
from .paths import get_project_paths
from .project_registry import ProjectEntry, load_project_registry, path_value, rebase_record, registry_path
from .projection_engine import get_projection_profile, plan_projection, verify_projection_mirror
from .safety import scan_safety
from .scan_engine import ignored_by_project, output_rules

LAYERS = ("source", "mirror", "docs")


def projects_config_path(root: Path | None = None) -> Path:
    """The registry: hub_projects.json in the root of the projects (project_registry.registry_path)."""
    return registry_path(root)


def config_path_value(path: Path, base: Path | None = None) -> str:
    """How a path is written into the registry: inside the root of the projects, where the registry lies, relative to it -
    the root and its projects move together; anywhere else as it is."""
    return path_value(path, base or projects_config_path().parent)


def export_registry(target: Path) -> dict[str, Any]:
    """The registry into a file of one's own choice, every path in full: it reads the same wherever the file goes."""
    source = projects_config_path()
    payload, error = load_json_safe(source, default={"active_project_id": "", "projects": []})
    if error:
        raise ValueError(error)
    items = [_absolute_record(item, source.parent) for item in payload.get("projects", []) if isinstance(item, dict)]
    target = target.expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    save_json(target, {**payload, "projects": items})
    return {"registry": str(source), "file": str(target), "projects": len(items)}


def _absolute_record(item: dict[str, Any], base: Path) -> dict[str, Any]:
    out = dict(item)
    for key in ("source_path", "projection_path", "docs_path"):
        text = str(item.get(key, "") or "").strip()
        if text:
            path = Path(text).expanduser()
            out[key] = str(Path(os.path.normpath(path if path.is_absolute() else base / path)))
    return out


def import_registry(source: Path, *, replace: bool = False, dry_run: bool = False) -> dict[str, Any]:
    """Projects from a registry file into the registry of the root: its paths read from where the file lies, written
    for the root. A project whose id the registry has is left as it is; `replace` takes the file's list instead."""
    source = source.expanduser()
    loaded, error = load_json_safe(source, default=None)
    if error or not isinstance(loaded, dict) or not isinstance(loaded.get("projects"), list):
        raise ValueError(error or f"{source}: not a registry of projects")
    target = projects_config_path()
    payload, error = load_json_safe(target, default={"active_project_id": "", "projects": []})
    if error:
        raise ValueError(error)
    incoming = [rebase_record(item, source.parent, target.parent) for item in loaded["projects"] if isinstance(item, dict)]
    kept = [] if replace else [item for item in payload.get("projects", []) if isinstance(item, dict)]
    known = {str(item.get("id", "")) for item in kept}
    added = [item for item in incoming if str(item.get("id", "")) not in known]
    payload["projects"] = kept + added
    if replace or not payload.get("active_project_id"):
        payload["active_project_id"] = str(loaded.get("active_project_id", "") or (added[0].get("id", "") if added else ""))
    if not dry_run:
        save_json(target, payload)
    return {"registry": str(target), "file": str(source), "dry_run": dry_run, "replace": replace,
            "added": [str(item.get("id", "")) for item in added], "skipped": len(incoming) - len(added)}


def layer_path(project: ProjectEntry, layer: str) -> Path | None:
    if layer == "source":
        return project.source_path
    if layer == "mirror":
        return project.projection_path
    if layer == "docs":
        return project.docs_path
    raise ValueError(f"unknown layer: {layer}")


def _repo_state(path: Path | None) -> dict[str, Any]:
    """Is this folder there, and is it a repository of its own (not a folder inside someone else's)?"""
    if path is None:
        return {"path": "", "exists": False, "repo": "none"}
    state: dict[str, Any] = {"path": str(path), "exists": path.is_dir()}
    if not path.is_dir():
        state["repo"] = "none"
        return state
    if (path / ".git").exists():
        state["repo"] = "own"
        return state
    done = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=path, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    if done.returncode == 0 and done.stdout.strip():
        # A layer inside another repository: git commands there would act on that one.
        state["repo"] = "parent"
        state["parent"] = str(Path(done.stdout.strip()))
    else:
        state["repo"] = "none"
    return state


def list_projects(*, with_repo_state: bool = True) -> dict[str, Any]:
    registry = load_project_registry()
    items = []
    for project in registry.projects:
        item = project.to_dict()
        if with_repo_state:
            item["layers"] = {layer: _repo_state(layer_path(project, layer)) for layer in LAYERS}
        items.append(item)
    active = registry.active_project_id if any(p.id == registry.active_project_id for p in registry.projects) else (
        registry.projects[0].id if registry.projects else "")
    return {"active_project_id": active, "projects": items, "load_error": registry.load_error,
            "config": str(projects_config_path())}


def set_active_project(project_id: str) -> dict[str, Any]:
    path = projects_config_path()
    payload, error = load_json_safe(path, default={"active_project_id": "", "projects": []})
    if error:
        raise ValueError(error)
    ids = [str(item.get("id", "")) for item in payload.get("projects", []) if isinstance(item, dict)]
    if project_id not in ids:
        raise KeyError(f"no project {project_id!r} in {path.name}")
    payload["active_project_id"] = project_id
    save_json(path, payload)
    return {"active_project_id": project_id}


def set_project_fields(project_id: str, **fields: str) -> dict[str, Any]:
    """Write fields of one record; path fields inside the root of the projects are stored relative to it."""
    allowed = {"title", "source_path", "projection_path", "docs_path", "profile", "default_branch", "vscode_workspace", "notes"}
    path = projects_config_path()
    payload, error = load_json_safe(path, default={"active_project_id": "", "projects": []})
    if error:
        raise ValueError(error)
    for item in payload.get("projects", []):
        if isinstance(item, dict) and str(item.get("id", "")) == project_id:
            for key, value in fields.items():
                if value is None:
                    continue
                if key not in allowed:
                    raise KeyError(f"field {key!r} cannot be set")
                if key == "profile":
                    # A record with a profile that does not exist would leave every check of its paths without an answer.
                    try:
                        get_projection_profile(str(value))
                    except Exception:
                        raise KeyError(f"no profile {value!r} in projection_profiles.json") from None
                if key in {"source_path", "projection_path", "docs_path"} and str(value).strip():
                    value = config_path_value(Path(str(value)))
                item[key] = str(value)
            save_json(path, payload)
            return {"project": item}
    raise KeyError(f"no project {project_id!r} in {path.name}")


def remove_project(project_id: str, *, dry_run: bool = False) -> dict[str, Any]:
    """Takes the record(s) of one id out of the registry. The folders - SOURCE, GIT COPY, DOCS - are never touched."""
    path = projects_config_path()
    payload, error = load_json_safe(path, default={"active_project_id": "", "projects": []})
    if error:
        raise ValueError(error)
    items = payload.get("projects", [])
    removed = [item for item in items if isinstance(item, dict) and item.get("id") == project_id]
    if not removed:
        raise KeyError(f"no project {project_id!r} in {path.name}")
    payload["projects"] = kept = [item for item in items if not (isinstance(item, dict) and item.get("id") == project_id)]
    if payload.get("active_project_id") == project_id:
        payload["active_project_id"] = next((str(item.get("id", "")) for item in kept if isinstance(item, dict)), "")
    if not dry_run:
        save_json(path, payload)
    return {"config": str(path), "dry_run": dry_run, "active_project_id": payload["active_project_id"],
            "removed": [{"id": item.get("id", ""), "title": item.get("title", ""), "source_path": item.get("source_path", "")}
                        for item in removed]}


def clean_registry(*, dry_run: bool = False) -> dict[str, Any]:
    """Drop records whose ИСХОДНИК folder is gone and duplicates (by id, by folder). Folders are never touched."""
    path = projects_config_path()
    payload, error = load_json_safe(path, default={"active_project_id": "", "projects": []})
    if error:
        raise ValueError(error)
    cleaned: list[dict[str, Any]] = []
    removed: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    seen_sources: set[str] = set()
    for item in payload.get("projects", []):
        if not isinstance(item, dict):
            removed.append({"id": "", "title": "", "reason": "invalid record"})
            continue
        project = ProjectEntry.from_dict(item, path.parent)
        source_key = str(project.source_path).lower()
        if not project.source_path.is_dir():
            removed.append({"id": project.id, "title": project.title, "reason": f"missing source: {project.source_path}"})
        elif project.id in seen_ids:
            removed.append({"id": project.id, "title": project.title, "reason": "duplicate id"})
        elif source_key in seen_sources:
            removed.append({"id": project.id, "title": project.title, "reason": f"duplicate source: {project.source_path}"})
        else:
            seen_ids.add(project.id)
            seen_sources.add(source_key)
            cleaned.append(item)
    payload["projects"] = cleaned
    if str(payload.get("active_project_id", "")).strip() not in seen_ids:
        payload["active_project_id"] = str(cleaned[0].get("id", "")) if cleaned else ""
    if not dry_run:
        save_json(path, payload)
    return {"config": str(path), "dry_run": dry_run,
            "summary": {"kept": len(cleaned), "removed": len(removed), "active_project_id": payload["active_project_id"]},
            "removed": removed}


def check_paths(root: Path, profile_id: str, paths: Iterable[str]) -> dict[str, Any]:
    """Which of these paths the profile lets into a commit. A folder counts as every file under it;
    the marker file (.gitkeep) always passes. The window asks this before add and commit."""
    profile = get_projection_profile(profile_id)
    marker = str(getattr(profile, "marker_file", ".gitkeep") or ".gitkeep")
    outputs = output_rules(root, profile)
    allowed: list[str] = []
    blocked: list[dict[str, str]] = []
    for raw in paths:
        rel = norm_rel(raw)
        if not rel:
            continue
        target = root / rel
        candidates = [item for item in target.rglob("*") if item.is_file() and ".git" not in item.relative_to(root).parts] \
            if rel == "." or target.is_dir() else [target]
        for candidate in candidates:
            try:
                candidate_rel = norm_rel(candidate.relative_to(root).as_posix())
            except ValueError:
                candidate_rel = rel
            if Path(candidate_rel).name == marker:
                allowed.append(candidate_rel)
                continue
            # The folder rules of the profile hold here as in the mirror: a file of a hidden or emptied folder stays out.
            folder = norm_rel(Path(candidate_rel).parent.as_posix())
            if folder not in ("", ".") and (any(
                    match_dir_rule(folder, getattr(profile, key, [])) for key in ("hide_dirs", "forbidden_dirs", "exclude_dir_contents"))
                    or match_dir_rule(folder, outputs)):
                blocked.append({"path": candidate_rel, "reason": "excluded_dir"})
                continue
            size = candidate.stat().st_size if candidate.is_file() else 0
            ok, reason = include_file(candidate_rel, size, profile, candidate if candidate.is_file() else None)
            if ok:
                allowed.append(candidate_rel)
            else:
                blocked.append({"path": candidate_rel, "reason": reason})
    ignored = _ignored_by_git(root, sorted(set(allowed)))
    return {"root": str(root), "profile": profile_id,
            "allowed": sorted(set(allowed) - ignored, key=str.casefold),
            "blocked": sorted({b["path"]: b for b in blocked}.values(), key=lambda b: b["path"].casefold()),
            "ignored": sorted(ignored, key=str.casefold)}


def _ignored_by_git(root: Path, paths: list[str]) -> set[str]:
    """The paths the project's own .gitignore hides: its word on what never to commit stands over the profile's."""
    return ignored_by_project(root, paths)


def describe_profile(profile_id: str) -> dict[str, Any]:
    profile = get_projection_profile(profile_id)
    data = profile.to_json()
    return {key: data[key] for key in ("id", "title", "description", "compare_mode", "mirror", "preserve_empty_dirs",
                                       "marker_file", "respect_gitignore", "max_file_bytes", "include_globs", "exclude_globs",
                                       "small_include_globs", "hide_dirs", "exclude_dir_contents", "output_dirs",
                                       "extensionless_text_bytes", "forbidden_dirs",
                                       "protected_target_globs", "dry_run_default")}


# --- batches over the registry ---

def _each_project(run) -> tuple[list[dict[str, Any]], int]:  # noqa: ANN001
    results: list[dict[str, Any]] = []
    errors = 0
    for project in load_project_registry().projects:
        item: dict[str, Any] = {"project_id": project.id, "title": project.title, "source": str(project.source_path),
                                "hub": str(project.projection_path)}
        try:
            item.update(run(project))
            # A result may carry errors without raising - a SOURCE missing, a hash not read. They are errors of the batch:
            # counting only what was raised once let a batch answer ok for a project it never checked.
            nested = int((item.get("summary") or {}).get("errors", 0) or 0)
            if nested:
                errors += nested
                item["ok"] = False
        except Exception as exc:  # one broken project must not stop the batch
            errors += 1
            item["error"] = f"{exc.__class__.__name__}: {exc}"
        results.append(item)
    return results, errors


def batch_status() -> dict[str, Any]:
    totals = {"projects": 0, "clean": 0, "dirty": 0, "no_git": 0, "errors": 0}

    def one(project: ProjectEntry) -> dict[str, Any]:
        # The history of a project lives in its GIT COPY. A copy without a repository of its own is read in the
        # SOURCE: the lessons of the lab keep their history there.
        mirror = _repo_state(project.projection_path)
        layer = "mirror" if mirror["repo"] == "own" else "source"
        state = mirror if layer == "mirror" else _repo_state(project.source_path)
        # A folder without a repository of its own is a state, not an error: the first lesson of the lab is to make one.
        # Inside an outer repository git would answer for that one, so it is not asked at all.
        if state["exists"] and state["repo"] in ("none", "parent"):
            totals["no_git"] += 1
            return {"ok": True, "layer": layer, "repo": "none", "inside": state.get("parent", "")}
        stat, command = git_status(layer_path(project, layer))
        if not command.ok:
            raise RuntimeError(command.stderr.strip() or "git status failed")
        totals["clean" if not stat.files else "dirty"] += 1
        return {"ok": True, "layer": layer, "branch": stat.branch, "ahead": stat.ahead, "behind": stat.behind,
                "files": len(stat.files)}

    results, errors = _each_project(one)
    totals["projects"], totals["errors"] = len(results), errors
    return {"operation": "batch_status", "summary": totals, "results": results}


def batch_mirror_plan() -> dict[str, Any]:
    totals = {"projects": 0, "copy": 0, "delete": 0, "touch": 0, "same": 0, "errors": 0}

    def one(project: ProjectEntry) -> dict[str, Any]:
        summary = plan_projection(project.source_path, project.projection_path, get_projection_profile(project.profile)).get("summary", {})
        for key in ("copy", "delete", "touch", "same"):
            totals[key] += int(summary.get(key, 0))
        return {"summary": summary}

    results, errors = _each_project(one)
    totals["projects"], totals["errors"] = len(results), errors
    return {"operation": "batch_mirror_plan", "summary": totals, "results": results}


def batch_safety() -> dict[str, Any]:
    totals = {"projects": 0, "findings": 0, "blockers": 0, "warnings": 0, "errors": 0}

    def one(project: ProjectEntry) -> dict[str, Any]:
        summary = scan_safety(project.source_path).get("summary", {})
        for key in ("findings", "blockers", "warnings"):
            totals[key] += int(summary.get(key, 0))
        return {"summary": summary}

    results, errors = _each_project(one)
    totals["projects"], totals["errors"] = len(results), errors
    return {"operation": "batch_safety", "root_role": "source", "summary": totals, "results": results}


def batch_verify() -> dict[str, Any]:
    totals = {"projects": 0, "same": 0, "changed": 0, "missing": 0, "extra": 0, "errors": 0}

    def one(project: ProjectEntry) -> dict[str, Any]:
        summary = verify_projection_mirror(project.source_path, project.projection_path,
                                           get_projection_profile(project.profile)).get("summary", {})
        for key in ("same", "changed", "missing", "extra"):
            totals[key] += int(summary.get(key, 0))
        return {"summary": summary}

    results, errors = _each_project(one)
    totals["projects"], totals["errors"] = len(results), errors
    return {"operation": "batch_verify", "summary": totals, "results": results}


# --- VS Code workspaces ---

def _dedupe(folders: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for folder in folders:
        key = str(Path(folder["path"])).lower()
        if folder["path"] and key not in seen:
            seen.add(key)
            unique.append(folder)
    return unique


def _layer_folders(project: ProjectEntry) -> list[dict[str, str]]:
    folders = [{"name": f"{project.title} Source", "path": str(project.source_path)},
               {"name": f"{project.title} Hub", "path": str(project.projection_path)}]
    if project.docs_path is not None:
        folders.append({"name": f"{project.title} Docs", "path": str(project.docs_path)})
    return folders


def write_workspace(project_id: str | None = None) -> dict[str, Any]:
    """One project's layers, or with no id every project of the registry, as a .code-workspace."""
    paths = get_project_paths()
    registry = load_project_registry()
    folders = [{"name": "Audion Hub Manager", "path": str(paths.root)}]
    if project_id:
        folders += _layer_folders(registry.by_id(project_id))
        target = paths.workspace / "audion_hub_layers.code-workspace"
    else:
        for project in registry.projects:
            folders += _layer_folders(project)
        target = paths.workspace / "audion_hub_all_projects.code-workspace"
    payload = {"folders": _dedupe(folders), "settings": {"files.exclude": {"**/.git": False}}}
    save_json(target, payload)
    return {"workspace": str(target), **payload}


# --- the remote form ---

CLOUD_PLATFORM_HOSTS = {"github": "github.com", "gitlab": "gitlab.com", "codeberg": "codeberg.org"}
SELF_HOSTED_PLATFORMS = {"forgejo", "gitea", "custom"}
PLATFORM_TITLES = {"github": "GitHub", "gitlab": "GitLab", "codeberg": "Codeberg", "forgejo": "Forgejo", "gitea": "Gitea",
                   "custom": "Custom"}
REMOTE_NAME_RE = r"^[A-Za-z0-9._-]+$"


def remote_url(platform: str, owner: str, repo: str, *, url_type: str = "ssh", server: str = "", ssh_port: int = 22) -> str:
    """The address of a repository from the form: platform, owner, name; a server and an SSH port for self-hosted ones."""
    from . import forgejo_api

    platform = platform.strip().lower()
    owner = owner.strip().strip("/")
    repo = repo.strip().strip("/")
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not owner or not repo:
        raise ValueError("owner and repository are both needed")
    url_type = "https" if url_type.strip().lower() == "https" else "ssh"
    if platform in SELF_HOSTED_PLATFORMS:
        host = forgejo_api.ForgejoHost(id="form", title="", url=server, ssh_port=int(ssh_port), preferred_url_type=url_type)
        return forgejo_api.build_remote_url(host, owner, repo, url_type)
    hostname = CLOUD_PLATFORM_HOSTS.get(platform)
    if hostname is None:
        raise ValueError(f"unknown platform: {platform}")
    return f"https://{hostname}/{owner}/{repo}.git" if url_type == "https" else f"git@{hostname}:{owner}/{repo}.git"


def remotes_config_path(root: Path | None = None) -> Path:
    return (root or get_project_paths().root) / "config" / "remotes.json"


def list_saved_remotes() -> dict[str, Any]:
    from .auth_doctor import remote_provider, remote_url_type

    payload, error = load_json_safe(remotes_config_path(), default={"global_remotes": []})
    items = payload.get("global_remotes", []) if isinstance(payload, dict) else []
    remotes = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and str(item.get("name", "")).strip():
            url = str(item.get("url", "")).strip()
            remotes.append({"name": str(item["name"]).strip(), "title": str(item.get("title", "")), "url": url,
                            "enabled": bool(item.get("enabled", True)), "type": remote_url_type(url),
                            "provider": remote_provider(url)})
    return {"config": str(remotes_config_path()), "remotes": remotes, "load_error": error}


def save_remote(name: str, url: str, *, platform: str = "", repo: str = "", enabled: bool = True) -> dict[str, Any]:
    """Write one remote into config/remotes.json. The file goes into commits: an address with a password in it is refused."""
    import re

    from .auth_doctor import has_embedded_credentials
    from .git_engine import validate_remote_url

    name = name.strip()
    if not re.match(REMOTE_NAME_RE, name):
        raise ValueError(f"a remote name is letters, digits, dot, dash, underscore: {name!r}")
    url = validate_remote_url(url)
    if has_embedded_credentials(url):
        raise ValueError("the address carries a login or a token; keep it in the Credential Manager, not in the address")
    path = remotes_config_path()
    payload, error = load_json_safe(path, default={"global_remotes": []})
    if error:
        raise ValueError(error)
    items = payload.setdefault("global_remotes", [])
    entry = {"name": name, "title": f"{PLATFORM_TITLES.get(platform.lower(), platform.title() or 'Remote')} {repo or name}".strip(),
             "enabled": enabled, "url": url}
    for index, item in enumerate(items):
        if isinstance(item, dict) and str(item.get("name", "")).strip() == name:
            items[index] = {**item, **entry}
            break
    else:
        items.append(entry)
    save_json(path, payload)
    return {"config": str(path), "remote": entry}


# --- the hash engine ---

def blake3_probe() -> dict[str, Any]:
    probe = get_project_paths().logs / ".tmp" / "blake3_probe.bin"
    probe.parent.mkdir(parents=True, exist_ok=True)
    probe.write_bytes(b"Audion Hub Manager BLAKE3 probe\n")
    try:
        digest = hash_file_blake3(probe)
    finally:
        try:
            probe.unlink()
        except OSError:
            pass
    algorithm, _, value = digest.partition(":")
    return {"ok": algorithm == "blake3" and bool(value), "algorithm": algorithm, "digest": digest}


# --- the lab in the registry ---

LAB_TITLES = {
    "01-first-commit": "Лаборатория 01 · первый коммит", "02-index": "Лаборатория 02 · индекс",
    "03-branch-merge": "Лаборатория 03 · ветки и слияние", "04-conflict": "Лаборатория 04 · конфликт",
    "05-behind-remote": "Лаборатория 05 · отставание от сервера", "06-stash": "Лаборатория 06 · отложенное",
    "07-tags": "Лаборатория 07 · теги версий", "08-lost-commit": "Лаборатория 08 · потерянный коммит",
    "09-revert-reset": "Лаборатория 09 · откат", "10-source-mirror": "Лаборатория 10 · проект и GIT-КОПИЯ",
}


def register_lab(lab_dir: Path, profile: str = "audion_python_project_projection") -> dict[str, Any]:
    """Puts the ten repositories of the lab into the registry (ids lab_01 ... lab_10), or brings their paths up to date."""
    path = projects_config_path()
    payload, error = load_json_safe(path, default={"active_project_id": "", "projects": []})
    if error:
        raise ValueError(error)
    items = payload.setdefault("projects", [])
    added = updated = 0
    for name, title in LAB_TITLES.items():
        repo = lab_dir / name
        source = repo / "source" if name == "10-source-mirror" else repo
        mirror = repo / "git-copy" if name == "10-source-mirror" else lab_dir / "_git-copies" / name
        entry = {"id": "lab_" + name[:2], "title": title, "source_path": config_path_value(source), "projection_path": config_path_value(mirror),
                 "profile": profile, "default_branch": "main", "notes": "Учебный репозиторий: hub_cli lab create --replace строит его заново."}
        for index, item in enumerate(items):
            if isinstance(item, dict) and item.get("id") == entry["id"]:
                items[index] = {**item, **entry}
                updated += 1
                break
        else:
            items.append(entry)
            added += 1
    save_json(path, payload)
    return {"config": str(path), "added": added, "updated": updated}


# --- the tools of this machine ---

def _version_of(command: list[str]) -> str:
    try:
        done = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
                              env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    except (OSError, subprocess.SubprocessError):
        return ""
    import re

    found = re.search(r"(\d+\.\d+(?:\.\d+)?(?:\.windows\.\d+)?)", (done.stdout or done.stderr or ""))
    return found.group(1) if found else ""


def machine_tools() -> dict[str, Any]:
    """git, gh, glab, ssh, BLAKE3 and VS Code as this machine has them: the chips of the window's header."""
    import shutil

    from .external_apps import resolved_vscode_command

    tools: dict[str, Any] = {}
    for name, args in (("git", ["--version"]), ("gh", ["--version"]), ("glab", ["--version"]), ("ssh", ["-V"])):
        path = shutil.which(name)
        tools[name] = {"found": bool(path), "path": path or "", "version": _version_of([path, *args]) if path else ""}
    probe = blake3_probe()
    tools["blake3"] = {"found": probe["ok"], "path": probe["algorithm"], "version": ""}
    try:
        code = resolved_vscode_command(folder=True)
    except Exception:  # an odd apps.json must not hide the other tools
        code = ""
    code_path = code if code and Path(code).exists() else (shutil.which(code) if code else "") or ""
    tools["vscode"] = {"found": bool(code_path), "path": code_path, "version": ""}
    return tools


# --- the Recycle Bin (the lab is built again over the old one) ---

def send_to_recycle_bin(path: Path) -> None:
    """Moves a file or folder to the Recycle Bin (Windows); elsewhere refuses rather than deleting."""
    if os.name != "nt":
        raise OSError("the Recycle Bin is a Windows thing; move the folder away by hand")

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", ctypes.c_void_p), ("wFunc", ctypes.c_uint), ("pFrom", ctypes.c_wchar_p),
                    ("pTo", ctypes.c_wchar_p), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", ctypes.c_int),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", ctypes.c_wchar_p)]

    FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 3, 0x4, 0x10, 0x40, 0x400
    op = SHFILEOPSTRUCTW(None, FO_DELETE, str(Path(path).resolve()) + "\0", None,
                         FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI, 0, None, None)
    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if result != 0 or op.fAnyOperationsAborted or Path(path).exists():
        raise OSError(f"could not move {path} to the Recycle Bin (code {result})")
