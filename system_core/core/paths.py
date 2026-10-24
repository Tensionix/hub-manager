from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProjectPaths:
    root: Path
    system_core: Path
    config: Path
    input: Path
    output: Path
    logs: Path
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
        report=root / "report",
        workspace=root / "workspace",
    )


