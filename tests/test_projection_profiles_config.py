from __future__ import annotations

import json
from pathlib import Path

from system_core.core.mask_engine import include_file, match_dir_rule
from system_core.core.projection_engine import ProjectionProfile


ROOT = Path(__file__).resolve().parents[1]


def _profile(profile_id: str) -> ProjectionProfile:
    payload = json.loads((ROOT / "config" / "projection_profiles.json").read_text(encoding="utf-8"))
    return ProjectionProfile.from_dict(profile_id, payload["profiles"][profile_id])


def test_python_projection_includes_dev_git_files() -> None:
    profile = _profile("audion_python_project_projection")
    included = [
        ".gitmodules",
        ".git-blame-ignore-revs",
        "CODEOWNERS",
        "Makefile",
        "CMakeLists.txt",
        "Cargo.lock",
        "go.mod",
        "src/main.rs",
        "src/App.vue",
        "package/yarn.lock",
        ".vscode/tasks.json",
    ]

    for rel_path in included:
        assert include_file(rel_path, 100, profile) == (True, "ok")


def test_python_projection_excludes_local_and_build_noise() -> None:
    profile = _profile("audion_python_project_projection")
    excluded = [
        "config/apps.local.json",
        "web/app.min.js",
        "web/app.js.map",
        "native/module.obj",
        "target/classes/App.class",
    ]

    for rel_path in excluded:
        assert include_file(rel_path, 100, profile)[0] is False

    for rel_path in ["dist/app.js", ".next/server/page.js", "target/debug/app"]:
        assert match_dir_rule(rel_path, profile.exclude_dir_contents) or match_dir_rule(rel_path, profile.hide_dirs)
