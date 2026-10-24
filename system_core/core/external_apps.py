from __future__ import annotations

from pathlib import Path
import os
import shutil

from .json_utils import load_json
from .paths import get_project_paths


def _deep_merge(left: dict, right: dict) -> dict:
    result = dict(left)
    for key, value in right.items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _apps_payload() -> dict:
    paths = get_project_paths()
    payload = load_json(paths.config / "apps.json", default={})
    local_payload = load_json(paths.config / "apps.local.json", default={})
    if isinstance(payload, dict) and isinstance(local_payload, dict):
        return _deep_merge(payload, local_payload)
    return payload if isinstance(payload, dict) else {}


def _configured_app_command(app_id: str) -> str:
    payload = _apps_payload()
    apps = payload.get("apps", {}) if isinstance(payload, dict) else {}
    app = apps.get(app_id, {}) if isinstance(apps, dict) else {}
    command = _clean_command(str(app.get("command", "") if isinstance(app, dict) else ""))
    return command


def _clean_command(command: str) -> str:
    return command.strip().strip('"').strip("'").strip()


def _usable_command(command: str) -> str | None:
    if not command:
        return None
    path = Path(command).expanduser()
    if path.exists():
        return str(path)
    found = shutil.which(command)
    if found:
        return found
    return None


def _vscode_command(*, folder: bool = False) -> str:
    configured = _usable_command(_configured_app_command("vscode_folder" if folder else "vscode"))
    if configured:
        return configured
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        str(Path(local_appdata) / "Programs" / "Microsoft VS Code" / "Code.exe") if local_appdata else "",
        "Code.exe",
        "code.exe",
        "code.cmd",
        "code",
    ]
    for name in candidates:
        found = shutil.which(name)
        path = Path(name).expanduser()
        if path.exists():
            return str(path)
        if found:
            return found
    return "code"


def resolved_vscode_command(*, folder: bool = False) -> str:
    return _vscode_command(folder=folder)


