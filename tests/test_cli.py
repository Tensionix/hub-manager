"""The console command (system_core/cli.py, hub_cli.cmd): what the window calls for Hub Manager's own work.

Commands that write (the registry, remotes.json, the lab) run on a copy of the program's config in a
temporary root, never on config/ of this folder.
"""
from __future__ import annotations

from pathlib import Path
import io
import json
import shutil
import subprocess

import pytest

from system_core import cli
from system_core.core import paths as paths_module

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A program root of its own: the profiles of this one, a registry of two projects. The root of its projects is the
    program folder itself, so the registry (hub_projects.json) lies in the temporary folder of this test and no other."""
    (tmp_path / "config").mkdir()
    shutil.copy2(ROOT / "config" / "projection_profiles.json", tmp_path / "config" / "projection_profiles.json")
    (tmp_path / "config" / "storage_layout.json").write_text(json.dumps({"roots": {"full_projects_root": "${APP_ROOT}"}}), encoding="utf-8")
    for name in ("alpha", "beta"):
        (tmp_path / "projects" / name).mkdir(parents=True)
        (tmp_path / "projects" / name / "README.md").write_text(f"# {name}\n", encoding="utf-8")
    registry = {"active_project_id": "alpha", "projects": [
        {"id": "alpha", "title": "Alpha", "source_path": "projects/alpha", "projection_path": "hub/alpha", "profile": "audion_python_project_projection"},
        {"id": "beta", "title": "Beta", "source_path": "projects/beta", "projection_path": "hub/beta", "profile": "audion_python_project_projection"},
        {"id": "gone", "title": "Gone", "source_path": "projects/gone", "projection_path": "hub/gone", "profile": "audion_python_project_projection"},
        {"id": "alpha", "title": "Alpha again", "source_path": "projects/alpha", "projection_path": "hub/alpha2", "profile": "audion_python_project_projection"},
    ]}
    (tmp_path / "hub_projects.json").write_text(json.dumps(registry), encoding="utf-8")
    monkeypatch.setattr(paths_module, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr("system_core.core.projection_engine.get_project_paths", lambda root=None: paths_module.get_project_paths(tmp_path))
    return tmp_path


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict]:
    code = cli.main(list(argv))
    return code, json.loads(capsys.readouterr().out)


def test_version_and_canon(capsys: pytest.CaptureFixture[str]) -> None:
    code, payload = run(capsys, "version")
    assert code == 0 and payload["version"]
    code, payload = run(capsys, "canon")
    assert code == 0 and {"status", "commit", "push", "reset_hard"} <= {item["id"] for item in payload["canon"]}
    reset = next(item for item in payload["canon"] if item["id"] == "reset_hard")
    assert reset["risk"] == "danger" and reset["mode"] == "ask" and reset["places"] == ["commit"]


def test_projects_list_marks_missing_folders(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, payload = run(capsys, "projects", "list")
    assert code == 0 and payload["active_project_id"] == "alpha"
    layers = {item["id"] + item["title"]: item["layers"] for item in payload["projects"]}
    assert layers["alphaAlpha"]["source"]["exists"] and not layers["goneGone"]["source"]["exists"]


def test_a_missing_registry_starts_from_the_example(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = root / "hub_projects.json"
    config.unlink()
    shutil.copy2(ROOT / "config" / "projects.example.json", root / "config" / "projects.example.json")
    code, payload = run(capsys, "projects", "list", "--fast")
    assert code == 0 and {item["id"] for item in payload["projects"]} == {"demo_local", "audion_hub_manager"}
    assert config.is_file(), "the registry of this machine is written from the example"


def test_projects_active_and_set(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(capsys, "projects", "active", "beta")[0] == 0
    assert run(capsys, "projects", "active", "nosuch")[0] == 2
    code, payload = run(capsys, "projects", "set", "beta", "--docs", str(root / "docs" / "beta"), "--branch", "trunk")
    assert code == 0 and payload["project"]["docs_path"] == "docs/beta" and payload["project"]["default_branch"] == "trunk"
    # A profile that does not exist is refused: the record would leave every check of its paths without an answer.
    assert run(capsys, "projects", "set", "beta", "--profile", "no_such_profile")[0] == 2
    saved = json.loads((root / "hub_projects.json").read_text(encoding="utf-8"))
    assert saved["active_project_id"] == "beta"


def test_projects_clean_drops_missing_and_duplicates(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, payload = run(capsys, "projects", "clean", "--dry-run")
    assert code == 0 and payload["summary"]["removed"] == 2
    assert len(json.loads((root / "hub_projects.json").read_text(encoding="utf-8"))["projects"]) == 4, "a dry run writes nothing"
    code, payload = run(capsys, "projects", "clean")
    kept = json.loads((root / "hub_projects.json").read_text(encoding="utf-8"))["projects"]
    assert [item["title"] for item in kept] == ["Alpha", "Beta"]
    assert (root / "projects" / "alpha").is_dir(), "folders are never touched"


def test_projects_remove_and_a_dry_scan_write_nothing_they_should_not(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = root / "hub_projects.json"
    before = config.read_bytes()
    (root / "new" / "Gamma").mkdir(parents=True)
    (root / "new" / "Gamma" / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    code, payload = run(capsys, "projects", "scan", str(root / "new"), "--import", "--dry-run")
    assert code == 0 and payload["dry_run"] and payload["summary"]["imported"] == 1
    assert config.read_bytes() == before, "a dry run writes nothing"
    code, payload = run(capsys, "projects", "remove", "beta", "--dry-run")
    assert code == 0 and [item["id"] for item in payload["removed"]] == ["beta"] and config.read_bytes() == before
    code, payload = run(capsys, "projects", "remove", "alpha")
    saved = json.loads(config.read_text(encoding="utf-8"))
    assert code == 0 and len(payload["removed"]) == 2 and [item["id"] for item in saved["projects"]] == ["beta", "gone"]
    assert saved["active_project_id"] == "beta", "the active record went - the first one left takes its place"
    assert (root / "projects" / "alpha").is_dir(), "folders are never touched"
    assert run(capsys, "projects", "remove", "nosuch")[0] == 2


def test_check_paths_by_profile(root: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    source = root / "projects" / "alpha"
    (source / "logs").mkdir()
    (source / "logs" / "run.log").write_text("x", encoding="utf-8")
    (source / ".env").write_text("TOKEN=x", encoding="utf-8")
    (source / ".gitkeep").write_text("", encoding="utf-8")
    code, payload = run(capsys, "check-paths", "alpha", "--layer", "source", "README.md", "logs", ".env", ".gitkeep")
    assert code == 1
    assert payload["allowed"] == [".gitkeep", "README.md"]
    assert {item["path"] for item in payload["blocked"]} == {"logs/run.log", ".env"}
    # Thousands of paths do not fit a command line: the window gives them a line each on the input.
    monkeypatch.setattr("sys.stdin", io.StringIO("README.md\n.env\n"))
    code, payload = run(capsys, "check-paths", "alpha", "--layer", "source", "--stdin")
    assert payload["allowed"] == ["README.md"] and [item["path"] for item in payload["blocked"]] == [".env"]


def test_remote_url_and_saved_remotes(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(capsys, "remote", "url", "--platform", "github", "--owner", "me", "--repo", "lab.git")[1]["url"] == "git@github.com:me/lab.git"
    assert run(capsys, "remote", "url", "--platform", "codeberg", "--owner", "me", "--repo", "lab", "--type", "https")[1]["url"] == "https://codeberg.org/me/lab.git"
    assert run(capsys, "remote", "url", "--platform", "gitea", "--owner", "me", "--repo", "lab", "--server", "git.example.org", "--ssh-port", "2222")[1]["url"] \
        == "ssh://git@git.example.org:2222/me/lab.git"
    assert run(capsys, "remote", "url", "--platform", "github", "--owner", "", "--repo", "x")[0] == 2
    assert run(capsys, "remote", "save", "--name", "origin", "--url", "https://me:TOKEN@gitlab.com/me/lab.git")[0] == 2
    assert run(capsys, "remote", "save", "--name", "bad name", "--url", "git@github.com:me/lab.git")[0] == 2
    assert run(capsys, "remote", "save", "--name", "origin", "--url", "git@github.com:me/lab.git", "--platform", "github", "--repo", "lab")[0] == 0
    code, payload = run(capsys, "remote", "list")
    assert [(item["name"], item["provider"], item["type"]) for item in payload["remotes"]] == [("origin", "github", "ssh")]


def test_lab_create_refuses_over_an_existing_folder(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, payload = run(capsys, "lab", "create", "--dir", str(tmp_path / "lab"))
    assert code == 0 and len(payload["repos"]) == 10 and (tmp_path / "lab" / "LAB.md").exists()
    assert run(capsys, "lab", "create", "--dir", str(tmp_path / "lab"))[0] == 2


def test_mirror_plan_and_dry_apply(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, payload = run(capsys, "mirror", "plan", "alpha")
    assert code == 0 and payload["result"]["summary"]["copy"] == 1 and Path(payload["report"]).exists()
    code, payload = run(capsys, "mirror", "apply", "alpha", "--dry-run")
    assert code == 0 and not (root / "hub" / "alpha" / "README.md").exists()
    code, payload = run(capsys, "mirror", "apply", "alpha", "--apply")
    assert code == 0 and (root / "hub" / "alpha" / "README.md").exists()
    code, payload = run(capsys, "mirror", "verify", "alpha")
    assert code == 0, payload


def test_batch_status_reads_the_layer_the_history_lives_in(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # Alpha keeps its history in its GIT COPY; beta has a repository only in the source, as the lessons of the lab.
    copy = root / "hub" / "alpha"
    subprocess.run(["git", "init", "-q", "-b", "main", str(copy)], check=True)
    (copy / "README.md").write_text("# alpha\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(copy), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(copy), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x"], check=True)
    subprocess.run(["git", "init", "-q", "-b", "trunk", str(root / "projects" / "beta")], check=True)
    # "Alpha again" has no copy, and its source lies inside an outer repository: that one's status is not its own -
    # the project has no git yet, which is a state (the first lesson of the lab), not an error.
    subprocess.run(["git", "init", "-q", str(root / "projects")], check=True)
    code, payload = run(capsys, "batch", "status")
    rows = {(item["project_id"], item["title"]): item for item in payload["results"]}
    alpha, beta = rows[("alpha", "Alpha")], rows[("beta", "Beta")]
    again = rows[("alpha", "Alpha again")]
    assert again["repo"] == "none" and "error" not in again and again["inside"].endswith("projects")
    assert payload["summary"]["no_git"] == 1 and payload["summary"]["errors"] == 1, payload["summary"]  # "gone" has no folder
    assert (alpha["layer"], alpha["branch"], alpha["files"]) == ("mirror", "main", 0)
    # A repository without commits: git names the branch "No commits yet on trunk", in the language of the machine.
    assert (beta["layer"], beta["files"]) == ("source", 1) and beta["branch"].endswith("trunk")


def test_the_cmd_door_runs_the_same() -> None:
    done = subprocess.run(["cmd", "/d", "/c", str(ROOT / "hub_cli.cmd"), "version"], capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 0 and json.loads(done.stdout)["ok"] is True


def test_paths_inside_the_root_of_the_projects_are_written_relative(tmp_path: Path) -> None:
    from system_core.core.hub_ops import config_path_value

    base = tmp_path / "TOOLS"  # the root of the projects, where the registry lies
    base.mkdir()
    assert config_path_value(base / "Audion Hub Manager" / "examples" / "lab", base) == "Audion Hub Manager/examples/lab"
    assert config_path_value(base / "Hub Data" / "Audion Hub Manager", base) == "Hub Data/Audion Hub Manager"
    assert config_path_value(base, base) == "."
    # Elsewhere - another folder tree or disk - as it is.
    elsewhere = tmp_path / "Archive" / "Copies"
    assert config_path_value(elsewhere, base) == str(elsewhere)


def test_the_registry_the_program_kept_moves_to_the_root_of_the_projects(tmp_path: Path) -> None:
    # Before 2.0.0 the registry lay in config/projects.json, its paths read from the program folder.
    from system_core.core.project_registry import load_project_registry, registry_path

    app = tmp_path / "Audion Hub Manager"
    (app / "config").mkdir(parents=True)
    elsewhere = tmp_path.parent / (tmp_path.name + "-elsewhere") / "Lab"  # outside the root: stays in full
    legacy = {"active_project_id": "me", "projects": [
        {"id": "me", "title": "Me", "source_path": ".", "projection_path": "../Hub Data/Me"},
        {"id": "lab", "title": "Lab", "source_path": "examples/lab/01", "projection_path": str(elsewhere)},
    ]}
    (app / "config" / "projects.json").write_text(json.dumps(legacy), encoding="utf-8")

    path = registry_path(app)  # the shipped root: the folder the program lies in

    assert path == tmp_path / "hub_projects.json" and not (app / "config" / "projects.json").exists()
    moved = json.loads(path.read_text(encoding="utf-8"))
    assert [(p["source_path"], p["projection_path"]) for p in moved["projects"]] == [
        ("Audion Hub Manager", "Hub Data/Me"), ("Audion Hub Manager/examples/lab/01", str(elsewhere))]
    entries = load_project_registry(path).projects
    assert entries[0].source_path == app and entries[0].projection_path == tmp_path / "Hub Data" / "Me"


def test_another_root_of_the_projects_has_a_registry_of_its_own(tmp_path: Path) -> None:
    from system_core.core.project_registry import registry_path
    from system_core.core.storage_layout import set_projects_root

    app = tmp_path / "Manager"
    (app / "config").mkdir(parents=True)
    shutil.copy2(ROOT / "config" / "projects.example.json", app / "config" / "projects.example.json")
    (tmp_path / "Code").mkdir()
    shipped = registry_path(app)
    assert {p["id"] for p in json.loads(shipped.read_text(encoding="utf-8"))["projects"]} == {"demo_local", "audion_hub_manager"}
    set_projects_root(app, str(tmp_path / "Code"))
    own = registry_path(app)
    assert own == tmp_path / "Code" / "hub_projects.json" and json.loads(own.read_text(encoding="utf-8"))["projects"] == []
    set_projects_root(app, None)
    assert registry_path(app) == shipped, "back to the shipped root - back to its registry"


def test_a_new_root_is_set_even_when_the_layout_does_not_hold_its_projects(root: Path, tmp_path_factory: pytest.TempPathFactory,
                                                                         capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "ROOT", root)
    other = tmp_path_factory.mktemp("Code")
    (other / "lone").mkdir()
    (other / "hub_projects.json").write_text(json.dumps({"active_project_id": "lone", "projects": [
        {"id": "lone", "title": "Lone", "source_path": "lone", "projection_path": str(other / "copy")}]}), encoding="utf-8")
    code, payload = run(capsys, "storage", "--projects-root", str(other))
    result = payload["result"]
    assert code == 0, "the root is written: what was asked is done"
    assert result["ok"] is False and result["off_layout"] == {"source": [], "projection": ["lone"], "docs": []}
    code, payload = run(capsys, "storage", "--reset-projects-root")
    assert code == 0 and Path(payload["result"]["roots"]["full_projects_root"]["path"]) == root
    assert not (root / "config" / "storage_layout.local.json").exists()


def test_the_registry_goes_out_to_a_file_and_comes_back(root: Path, tmp_path_factory: pytest.TempPathFactory, capsys: pytest.CaptureFixture[str]) -> None:
    file = tmp_path_factory.mktemp("exchange") / "registry.json"
    code, payload = run(capsys, "projects", "export", str(file))
    assert code == 0 and payload["projects"] == 4
    exported = json.loads(file.read_text(encoding="utf-8"))
    assert exported["projects"][0]["source_path"] == str(root / "projects" / "alpha"), "in full: it reads the same wherever it goes"
    assert run(capsys, "projects", "remove", "beta")[0] == 0
    code, payload = run(capsys, "projects", "import", str(file))
    saved = json.loads((root / "hub_projects.json").read_text(encoding="utf-8"))
    assert code == 0 and payload["added"] == ["beta"] and [p["id"] for p in saved["projects"]] == ["alpha", "gone", "alpha", "beta"]
    assert saved["projects"][-1]["source_path"] == "projects/beta", "written for the root of the projects again"
    code, payload = run(capsys, "projects", "import", str(file), "--replace")
    assert code == 0 and len(json.loads((root / "hub_projects.json").read_text(encoding="utf-8"))["projects"]) == 4
    assert run(capsys, "projects", "import", str(file.parent / "missing.json"))[0] == 2


def test_check_paths_keeps_the_folder_rules_of_the_profile(tmp_path: Path) -> None:
    from system_core.core.hub_ops import check_paths

    for rel in ("README.md", "logs/run.json", "App/config/i18n.json", "system_core/app/main.py"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x", encoding="utf-8")
    result = check_paths(tmp_path, "audion_python_project_projection", ["."])
    assert result["allowed"] == ["README.md", "system_core/app/main.py"]
    assert {b["path"]: b["reason"] for b in result["blocked"]} == {"App/config/i18n.json": "excluded_dir", "logs/run.json": "excluded_dir"}


def test_check_paths_keeps_out_what_the_repository_gitignore_hides(tmp_path: Path) -> None:
    import subprocess

    from system_core.core.hub_ops import check_paths

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("private.json\n", encoding="utf-8")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "private.json").write_text("{}", encoding="utf-8")
    (tmp_path / "config" / "app.json").write_text("{}", encoding="utf-8")
    result = check_paths(tmp_path, "audion_python_project_projection", ["."])
    assert result["allowed"] == [".gitignore", "config/app.json"]
    assert result["ignored"] == ["config/private.json"]
    # A folder without a repository of its own: its own .gitignore counts, not that of the repository it lies in.
    plain = tmp_path / "plain"
    (plain / "config").mkdir(parents=True)
    (plain / "config" / "private.json").write_text("{}", encoding="utf-8")
    (plain / "config" / "app.json").write_text("{}", encoding="utf-8")
    (plain / ".gitignore").write_text("app.json\n", encoding="utf-8")
    result = check_paths(plain, "audion_python_project_projection", ["."])
    assert result["ignored"] == ["config/app.json"] and "config/private.json" in result["allowed"]


# --- what the audit of 24.10.2026 found the console command answering wrong ---

def test_a_wrong_call_is_answered_with_one_json(capsys: pytest.CaptureFixture[str]) -> None:
    code, payload = run(capsys, "mirror", "apply")
    assert code == 2 and payload["ok"] is False and payload["kind"] == "usage" and "id" in payload["error"]
    code, payload = run(capsys, "no-such-command")
    assert code == 2 and payload["kind"] == "usage"


def test_a_batch_counts_the_errors_its_projects_return(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # "gone" has no SOURCE: its scan returns an error without raising one - the batch is not ok.
    code, payload = run(capsys, "batch", "safety")
    gone = [item for item in payload["results"] if item["project_id"] == "gone"][0]
    assert code == 1 and payload["summary"]["errors"] >= 1 and gone["ok"] is False


def test_docs_apply_that_failed_to_copy_is_no_success(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    docs = root / "docs" / "alpha"
    (docs / "README.md").mkdir(parents=True)  # a folder where the document should go
    assert run(capsys, "projects", "set", "alpha", "--docs", str(docs))[0] == 0
    code, payload = run(capsys, "docs", "apply", "alpha")
    assert code == 1 and payload["ok"] is False and payload["result"]["summary"]["errors"] >= 1


def test_check_paths_of_a_record_whose_profile_is_gone_gives_no_permission(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = root / "hub_projects.json"
    registry = json.loads(config.read_text(encoding="utf-8"))
    registry["projects"][1]["profile"] = "no_such_profile"
    config.write_text(json.dumps(registry), encoding="utf-8")
    code, payload = run(capsys, "check-paths", "beta", "--layer", "source", "README.md")
    assert code != 0 and "allowed" not in payload and payload["ok"] is False