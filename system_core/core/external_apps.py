from __future__ import annotations

from pathlib import Path
import os
import platform
import shutil
import subprocess
import webbrowser

from .json_utils import load_json, save_json
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


def configured_vscode_command() -> str:
    return _configured_app_command("vscode") or _configured_app_command("vscode_folder")


def resolved_vscode_command(*, folder: bool = False) -> str:
    return _vscode_command(folder=folder)


def save_local_vscode_command(command: str) -> Path:
    command = _clean_command(command)
    config_path = get_project_paths().config / "apps.local.json"
    payload = load_json(config_path, default={})
    if not isinstance(payload, dict):
        payload = {}
    apps = payload.setdefault("apps", {})
    if not isinstance(apps, dict):
        apps = {}
        payload["apps"] = apps
    apps["vscode"] = {"command": command}
    apps["vscode_folder"] = {"command": command}
    save_json(config_path, payload)
    return config_path


def _open_vscode(args: list[str], *, folder: bool = False) -> None:
    command = _vscode_command(folder=folder)
    if platform.system().lower() == "windows" and command.lower().endswith((".cmd", ".bat")):
        subprocess.Popen([os.environ.get("COMSPEC", "cmd.exe"), "/c", command, *args], shell=False)
        return
    subprocess.Popen([command, *args], shell=False)


def open_in_vscode(path: Path, *, line: int | None = None) -> None:
    target = str(path.resolve())
    if line:
        target = f"{target}:{line}"
    _open_vscode(["-g", target], folder=False)


def open_folder_in_vscode(path: Path) -> None:
    _open_vscode([str(path.resolve())], folder=True)


def open_terminal_command(command: str, cwd: Path | None = None) -> None:
    cwd_arg = str(cwd.resolve()) if cwd else None
    system = platform.system().lower()
    if system == "windows":
        subprocess.Popen(["cmd.exe", "/k", command], cwd=cwd_arg, creationflags=subprocess.CREATE_NEW_CONSOLE)
    elif system == "darwin":
        script = f'tell app "Terminal" to do script "cd {sh_quote(cwd_arg or ".")} && {command}"'
        subprocess.Popen(["osascript", "-e", script])
    else:
        subprocess.Popen(["x-terminal-emulator", "-e", f"sh -lc {sh_quote(command + '; exec sh')}"], cwd=cwd_arg)


def sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def open_windows_credential_manager() -> None:
    if platform.system().lower() == "windows":
        subprocess.Popen(["rundll32.exe", "keymgr.dll,KRShowKeyMgr"], shell=False)
    else:
        webbrowser.open("https://github.com/git-ecosystem/git-credential-manager")


def open_web_url(url: str) -> None:
    """Open an http(s) address in the system browser. Other schemes are refused."""
    text = str(url or "").strip()
    if not text.lower().startswith(("http://", "https://")):
        raise ValueError(f"Only http/https addresses can be opened: {url}")
    webbrowser.open(text)


def open_default(path: Path) -> None:
    path = path.resolve()
    system = platform.system().lower()
    if system == "windows":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif system == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])
