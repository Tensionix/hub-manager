from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import platform
import subprocess


@dataclass(frozen=True)
class ProjectPaths:
    root: Path
    system_core: Path
    config: Path
    input: Path
    output: Path
    logs: Path
    backup: Path
    release: Path
    report: Path
    workspace: Path


def get_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def get_project_paths(root: Path | None = None) -> ProjectPaths:
    root = (root or get_project_root()).resolve()
    return ProjectPaths(
        root=root,
        system_core=root / "system_core",
        config=root / "config",
        input=root / "input",
        output=root / "output",
        logs=root / "logs",
        backup=root / "backup",
        release=root / "release",
        report=root / "report",
        workspace=root / "workspace",
    )


def ensure_project_dirs(paths: ProjectPaths) -> None:
    for path in [paths.config, paths.input, paths.output, paths.logs, paths.backup, paths.release, paths.report, paths.workspace]:
        path.mkdir(parents=True, exist_ok=True)


def open_path(path: Path) -> None:
    path = path.resolve()
    if not path.exists():
        raise FileNotFoundError(f"Path does not exist: {path}")
    system = platform.system().lower()
    try:
        if system == "windows":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif system == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except OSError as exc:
        raise RuntimeError(f"Could not open path: {path}") from exc
