from __future__ import annotations

import json
from pathlib import Path

from system_core.core.project_registry import ProjectEntry
from system_core.core.storage_layout import storage_layout_status


def test_storage_layout_status_accepts_separate_roots(tmp_path: Path) -> None:
    app = tmp_path / "Manager"
    hub = tmp_path / "Hub Git"
    docs = tmp_path / "Docs"
    projects = tmp_path / "TOOLS"
    source = projects / "Demo"
    projection = hub / "projects" / "Demo"
    docs_project = docs / "Projects" / "Demo"
    for path in [app / "config", hub, docs, source, projection.parent, docs_project]:
        path.mkdir(parents=True)
    (app / "config" / "storage_layout.json").write_text(
        json.dumps(
            {
                "layout_version": 1,
                "roots": {
                    "manager_root": "${APP_ROOT}",
                    "hub_data_root": str(hub),
                    "docs_root": str(docs),
                    "full_projects_root": str(projects),
                },
            }
        ),
        encoding="utf-8",
    )

    result = storage_layout_status(
        app,
        [
            ProjectEntry(
                id="real_project",
                title="Demo",
                source_path=source,
                projection_path=projection,
                docs_path=docs_project,
                profile="audion_python_project_projection",
            )
        ],
    )

    assert result["ok"] is True
    assert result["roots"]["hub_data_root"]["exists"] is True
    assert result["roots"]["docs_root"]["exists"] is True
    assert result["separation"]["hub_not_inside_docs"] is True
    assert result["projects"][0]["projection_under_hub"] is True
    assert result["projects"][0]["docs_under_root"] is True


def test_storage_layout_status_rejects_projection_outside_hub(tmp_path: Path) -> None:
    app = tmp_path / "Manager"
    hub = tmp_path / "Hub Git"
    docs = tmp_path / "Docs"
    projects = tmp_path / "TOOLS"
    source = projects / "Demo"
    projection = tmp_path / "Wrong Hub" / "Demo"
    docs_project = docs / "Projects" / "Demo"
    for path in [app / "config", hub, docs, source, projects, docs_project]:
        path.mkdir(parents=True, exist_ok=True)
    (app / "config" / "storage_layout.json").write_text(
        json.dumps(
            {
                "layout_version": 1,
                "roots": {
                    "manager_root": "${APP_ROOT}",
                    "hub_data_root": str(hub),
                    "docs_root": str(docs),
                    "full_projects_root": str(projects),
                },
            }
        ),
        encoding="utf-8",
    )

    result = storage_layout_status(
        app,
        [
            ProjectEntry(
                id="real_project",
                title="Demo",
                source_path=source,
                projection_path=projection,
                docs_path=docs_project,
                profile="audion_python_project_projection",
            )
        ],
    )

    assert result["ok"] is False
    assert result["projects"][0]["projection_under_hub"] is False


def test_app_root_names_the_program_folder_in_every_root(tmp_path: Path) -> None:
    # The layout the program ships: the GIT COPIES and DOCS beside the program folder, the projects its parent.
    app = tmp_path / "Manager"
    (app / "config").mkdir(parents=True)
    (tmp_path / "Hub Data").mkdir()
    (tmp_path / "Hub Docs").mkdir()
    (app / "config" / "storage_layout.json").write_text(json.dumps({"layout_version": 1, "roots": {
        "manager_root": "${APP_ROOT}", "hub_data_root": "${APP_ROOT}/../Hub Data",
        "docs_root": "${APP_ROOT}/../Hub Docs", "full_projects_root": "${APP_ROOT}/.."}}), encoding="utf-8")

    result = storage_layout_status(app, [])

    assert Path(result["roots"]["hub_data_root"]["path"]) == tmp_path / "Hub Data"
    assert Path(result["roots"]["docs_root"]["path"]) == tmp_path / "Hub Docs"
    assert Path(result["roots"]["full_projects_root"]["path"]) == tmp_path
    assert result["ok"] is True


def test_the_root_of_projects_is_chosen_on_the_machine_and_given_back(tmp_path: Path) -> None:
    from system_core.core.storage_layout import LOCAL_FILE, set_projects_root

    app = tmp_path / "Manager"
    (app / "config").mkdir(parents=True)
    (tmp_path / "Hub Data").mkdir()
    (tmp_path / "Work" / "Code").mkdir(parents=True)
    elsewhere = tmp_path.parent / (tmp_path.name + "-elsewhere")
    elsewhere.mkdir()
    shipped = {"layout_version": 1, "roots": {"hub_data_root": "${APP_ROOT}/../Hub Data", "full_projects_root": "${APP_ROOT}/.."}}
    (app / "config" / "storage_layout.json").write_text(json.dumps(shipped), encoding="utf-8")

    # Beside the program: kept from it, so the choice moves with the program; the shipped file is not touched.
    result = set_projects_root(app, str(tmp_path / "Work" / "Code"))
    root = result["roots"]["full_projects_root"]
    assert Path(root["path"]) == tmp_path / "Work" / "Code" and root["chosen_here"] is True and Path(root["shipped"]) == tmp_path
    assert json.loads((app / "config" / LOCAL_FILE).read_text(encoding="utf-8"))["roots"]["full_projects_root"] == "${APP_ROOT}/../Work/Code"
    assert json.loads((app / "config" / "storage_layout.json").read_text(encoding="utf-8")) == shipped
    # Elsewhere: in full.
    assert Path(set_projects_root(app, str(elsewhere))["roots"]["full_projects_root"]["path"]) == elsewhere
    # Not a folder, or inside the GIT COPIES: refused, the choice stays.
    for bad in (tmp_path / "missing", tmp_path / "Hub Data"):
        try:
            set_projects_root(app, str(bad))
            raise AssertionError(f"{bad} was taken")
        except ValueError:
            pass
    # Given back: the file of the machine goes, the shipped root stands.
    result = set_projects_root(app, None)
    assert Path(result["roots"]["full_projects_root"]["path"]) == tmp_path and result["roots"]["full_projects_root"]["chosen_here"] is False
    assert not (app / "config" / LOCAL_FILE).exists()


def test_a_project_without_docs_and_the_lab_keep_the_layout_ok(tmp_path: Path) -> None:
    app = tmp_path / "Manager"
    hub = tmp_path / "Hub Data"
    source = tmp_path / "Project"
    for path in [app / "config", hub, source]:  # no docs root: no project keeps a DOCS layer
        path.mkdir(parents=True)
    (app / "config" / "storage_layout.json").write_text(json.dumps({"layout_version": 1, "roots": {
        "hub_data_root": str(hub), "docs_root": str(tmp_path / "Hub Docs"), "full_projects_root": str(tmp_path)}}),
        encoding="utf-8")
    projects = [
        ProjectEntry(id="project", title="Project", source_path=source, projection_path=hub / "Project",
                     docs_path=None, profile="audion_python_project_projection"),
        ProjectEntry(id="lab_01", title="Lab", source_path=app / "examples" / "lab" / "01",
                     projection_path=app / "examples" / "lab" / "_git-copies" / "01", docs_path=None,
                     profile="audion_python_project_projection"),
    ]

    assert storage_layout_status(app, projects)["ok"] is True
