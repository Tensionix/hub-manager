from __future__ import annotations

from pathlib import Path

from system_core.core.project_importer import merge_project_import, scan_project_folder


def test_scan_project_folder_prefers_inner_project_over_outer_launcher(tmp_path: Path) -> None:
    container = tmp_path / "Source"
    outer = container / "Audion Tool"
    inner = outer / "Audion Tool"
    inner.mkdir(parents=True)
    (outer / "launcher_gui.cmd").write_text("@echo off\n", encoding="utf-8")
    (inner / "pyproject.toml").write_text("[project]\nname = 'audion-tool'\n", encoding="utf-8")
    (inner / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")

    entries = scan_project_folder(container, tmp_path / "Hub Data", docs_root=tmp_path / "Docs")

    assert len(entries) == 1
    assert Path(entries[0]["source_path"]) == inner.resolve()
    assert Path(entries[0]["projection_path"]) == (tmp_path / "Hub Data" / "Audion Tool").resolve()
    assert Path(entries[0]["docs_path"]) == (tmp_path / "Docs" / "Audion Tool").resolve()


def test_scan_project_folder_ignores_cmd_only_launcher_folder(tmp_path: Path) -> None:
    container = tmp_path / "Source"
    launcher = container / "Launcher Only"
    launcher.mkdir(parents=True)
    (launcher / "start.cmd").write_text("@echo off\n", encoding="utf-8")

    entries = scan_project_folder(container, tmp_path / "Hub Data")

    assert entries == []


def test_scan_project_folder_detects_developed_code_shape(tmp_path: Path) -> None:
    container = tmp_path / "Source"
    outer = container / "Plain Tool"
    inner = outer / "Plain Tool"
    (inner / "src").mkdir(parents=True)
    (inner / "tests").mkdir(parents=True)
    (outer / "run_gui.cmd").write_text("@echo off\n", encoding="utf-8")
    for index in range(4):
        (inner / "src" / f"module_{index}.py").write_text("print('ok')\n", encoding="utf-8")
    for index in range(2):
        (inner / "tests" / f"test_module_{index}.py").write_text("def test_ok(): pass\n", encoding="utf-8")

    entries = scan_project_folder(container, tmp_path / "Hub Data")

    assert len(entries) == 1
    assert Path(entries[0]["source_path"]) == inner.resolve()


def test_scan_project_folder_skips_hub_root_inside_scan_area(tmp_path: Path) -> None:
    container = tmp_path / "Mixed"
    source_project = container / "Source Tool"
    hub_root = container / "Hub Data"
    hub_project = hub_root / "Source Tool"
    source_project.mkdir(parents=True)
    hub_project.mkdir(parents=True)
    (source_project / "pyproject.toml").write_text("[project]\nname = 'source-tool'\n", encoding="utf-8")
    (hub_project / "pyproject.toml").write_text("[project]\nname = 'source-tool'\n", encoding="utf-8")

    entries = scan_project_folder(container, hub_root)

    assert len(entries) == 1
    assert Path(entries[0]["source_path"]) == source_project.resolve()


def test_scan_project_folder_accepts_single_project_root(tmp_path: Path) -> None:
    project = tmp_path / "Single Tool"
    project.mkdir()
    (project / "package.json").write_text('{"name":"single-tool"}\n', encoding="utf-8")

    entries = scan_project_folder(project, tmp_path / "Hub Data")

    assert len(entries) == 1
    assert Path(entries[0]["source_path"]) == project.resolve()


def test_scan_project_folder_keeps_a_marked_project_over_its_fixtures(tmp_path: Path) -> None:
    project = tmp_path / "Tool"
    fixture = project / "build-ui" / "fixtures" / "dirty-source"
    (project / "src").mkdir(parents=True)
    (project / "CMakeLists.txt").write_text("project(tool)\n", encoding="utf-8")
    for name in ("pyproject.toml", "package.json", "README.md", "AGENTS.md", "CHANGELOG.md"):
        fixture.mkdir(parents=True, exist_ok=True)
        (fixture / name).write_text("x\n", encoding="utf-8")
    (fixture / "src").mkdir()

    # The folder itself, and the same when it is one of the folders of a shared one.
    assert [Path(e["source_path"]) for e in scan_project_folder(project, tmp_path / "Hub Data")] == [project.resolve()]
    assert [Path(e["source_path"]) for e in scan_project_folder(tmp_path, tmp_path / "Hub Data")] == [project.resolve()]


def test_scan_project_folder_does_not_take_an_empty_git_folder_for_a_project(tmp_path: Path) -> None:
    shared = tmp_path / "TOOLS"
    (shared / ".git" / "info").mkdir(parents=True)
    for name in ("Alpha", "Beta"):
        (shared / name).mkdir()
        (shared / name / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
        (shared / name / "README.md").write_text("# x\n", encoding="utf-8")

    entries = scan_project_folder(shared, tmp_path / "Hub Data")

    assert [e["title"] for e in entries] == ["Alpha", "Beta"]


def test_merge_project_import_skips_existing_source(tmp_path: Path) -> None:
    source = tmp_path / "Source" / "Tool"
    source.mkdir(parents=True)
    payload = {
        "active_project_id": "tool",
        "projects": [
            {
                "id": "tool",
                "title": "Tool",
                "source_path": str(source),
                "projection_path": str(tmp_path / "Hub Data" / "Tool"),
                "profile": "audion_python_project_projection",
            }
        ],
    }
    entries = [
        {
            "id": "tool",
            "title": "Tool Again",
            "source_path": str(source),
            "projection_path": str(tmp_path / "Hub Data" / "Tool Again"),
            "profile": "audion_python_project_projection",
            "default_branch": "main",
        }
    ]

    updated, added, skipped = merge_project_import(payload, entries)

    assert updated is payload
    assert added == 0
    assert skipped == 1
    assert len(updated["projects"]) == 1
