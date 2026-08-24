from __future__ import annotations

import pytest

from system_core.core.git_engine import validate_remote_url


@pytest.mark.parametrize(
    "hostile",
    [
        "ext::sh -c 'calc.exe'",
        "EXT::sh -c id",
        "fd::7",
        "--upload-pack=calc.exe",
        "-oProxyCommand=calc.exe",
        "https://git.example.org/repo.git\nfetch = evil",
    ],
)
def test_validate_remote_url_refuses_command_bearing_and_option_like_urls(hostile: str) -> None:
    # remotes.json can arrive with someone else's project; `ext::` makes Git run
    # a command, and a leading dash turns the URL into an option.
    with pytest.raises(ValueError):
        validate_remote_url(hostile)


def test_directory_name_from_url_matches_what_git_clone_would_pick() -> None:
    from system_core.core.git_engine import directory_name_from_url

    assert directory_name_from_url("https://git.audion.dev/audion/hub-manager-smoketest.git") == "hub-manager-smoketest"
    assert directory_name_from_url("git@git.audion.dev:audion/Audion_Hub.git") == "Audion_Hub"
    assert directory_name_from_url("ssh://git@host:2222/owner/repo.git") == "repo"
    assert directory_name_from_url("https://git.audion.dev/audion/repo/") == "repo"
    assert directory_name_from_url("") == ""


def test_validate_remote_url_accepts_the_forms_hub_manager_builds() -> None:
    for url in (
        "git@github.com:audion/Audion_Hub.git",
        "ssh://git@git.audion.dev:2222/audion/Audion_Hub.git",
        "https://git.audion.dev/audion/Audion_Hub.git",
        "file:///Z:/git-mirrors/Audion_Hub.git",
    ):
        assert validate_remote_url(url) == url

import json
from pathlib import Path

from system_core.core import git_engine
from system_core.core.git_engine import parse_status


def test_parse_status_labels_git_porcelain_states(tmp_path: Path) -> None:
    status = parse_status(
        tmp_path,
        "\n".join(
            [
                "## main...origin/main [ahead 1, behind 2]",
                " M README.md",
                "A  staged.py",
                "?? new.txt",
                "UU conflict.md",
            ]
        ),
    )

    assert status.branch == "main"
    assert status.ahead == 1
    assert status.behind == 2
    assert status.status_map() == {
        "README.md": "modified",
        "staged.py": "staged",
        "new.txt": "untracked",
        "conflict.md": "conflict",
    }


def test_commit_paths_uses_git_commit_only_with_pathspec(tmp_path: Path, monkeypatch) -> None:
    calls: list[tuple[Path, tuple[str, ...], int | None]] = []

    def fake_git(root: Path, *args: str, timeout: int | None = 120):
        calls.append((root, args, timeout))
        return git_engine.CommandResult(["git", *args], str(root), 0, "", "")

    monkeypatch.setattr(git_engine, "git", fake_git)

    git_engine.commit_paths(tmp_path, "docs(hub): update projection", ["docs/a.md", "", "README.md"])

    assert calls == [
        (
            tmp_path,
            ("commit", "--only", "-m", "docs(hub): update projection", "--", "docs/a.md", "README.md"),
            None,
        )
    ]


def test_semver_helpers_normalize_and_bump() -> None:
    assert git_engine.parse_semver("v2.3") == (2, 3, 0)
    assert git_engine.parse_semver("2.3.4") == (2, 3, 4)
    assert git_engine.bump_semver("v0.1.9") == "v0.1.10"
    assert git_engine.bump_semver("v0.1.9", "minor") == "v0.2.0"
    assert git_engine.bump_semver("v0.1.9", "major") == "v1.0.0"
    assert git_engine.build_version_tag("Auth UI", "v0.2") == "auth-ui-v0.2.0"


def test_next_version_for_series_reads_matching_tags(tmp_path: Path, monkeypatch) -> None:
    calls: list[tuple[Path, tuple[str, ...], int | None]] = []

    def fake_git(root: Path, *args: str, timeout: int | None = 120):
        calls.append((root, args, timeout))
        return git_engine.CommandResult(["git", *args], str(root), 0, "auth-ui-v0.1.0\nauth-ui-v0.1.3\nother-v9.9.9\n", "")

    monkeypatch.setattr(git_engine, "git", fake_git)

    version, result = git_engine.next_version_for_series(tmp_path, "Auth UI")

    assert version == "v0.1.4"
    assert result.ok
    assert calls == [(tmp_path, ("tag", "--list", "auth-ui-v*"), 120)]


def test_create_annotated_tag_uses_git_tag(tmp_path: Path, monkeypatch) -> None:
    calls: list[tuple[Path, tuple[str, ...], int | None]] = []

    def fake_git(root: Path, *args: str, timeout: int | None = 120):
        calls.append((root, args, timeout))
        return git_engine.CommandResult(["git", *args], str(root), 0, "", "")

    monkeypatch.setattr(git_engine, "git", fake_git)

    git_engine.create_annotated_tag(tmp_path, "auth-ui-v0.1.4", "docs(hub): auth-ui v0.1.4 - update")

    assert calls == [
        (
            tmp_path,
            ("tag", "-a", "auth-ui-v0.1.4", "-m", "docs(hub): auth-ui v0.1.4 - update"),
            None,
        )
    ]


def test_push_uses_follow_tags_by_default(tmp_path: Path, monkeypatch) -> None:
    calls: list[tuple[Path, tuple[str, ...], int | None]] = []

    def fake_git(root: Path, *args: str, timeout: int | None = 120):
        calls.append((root, args, timeout))
        return git_engine.CommandResult(["git", *args], str(root), 0, "", "")

    monkeypatch.setattr(git_engine, "git", fake_git)

    git_engine.push(tmp_path, "origin", "main")

    assert calls == [(tmp_path, ("push", "--follow-tags", "origin", "main"), None)]


def test_push_all_remotes_uses_git_remote_names_without_shell_loop(tmp_path: Path, monkeypatch) -> None:
    calls: list[tuple[Path, tuple[str, ...], int | None]] = []

    def fake_git(root: Path, *args: str, timeout: int | None = 120):
        calls.append((root, args, timeout))
        if args == ("remote",):
            return git_engine.CommandResult(["git", *args], str(root), 0, "github\ngitlab\n", "")
        return git_engine.CommandResult(["git", *args], str(root), 0, "", "")

    monkeypatch.setattr(git_engine, "git", fake_git)

    results = git_engine.push_all_remotes(tmp_path, "main")

    assert all(result.ok for result in results)
    assert calls == [
        (tmp_path, ("remote",), 120),
        (tmp_path, ("push", "--follow-tags", "github", "main"), None),
        (tmp_path, ("push", "--follow-tags", "gitlab", "main"), None),
    ]


def test_apply_remotes_from_config_adds_and_updates_enabled_remotes(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "remotes.json"
    config_path.write_text(
        json.dumps(
            {
                "global_remotes": [
                    {"name": "github", "enabled": True, "url": "git@github.com:audion/Audion_Hub.git"},
                    {"name": "gitlab", "enabled": True, "url": "git@gitlab.com:audion/Audion_Hub.git"},
                    {"name": "codeberg", "enabled": False, "url": "git@codeberg.org:audion/Audion_Hub.git"},
                ]
            }
        ),
        encoding="utf-8",
    )
    calls: list[tuple[Path, tuple[str, ...], int | None]] = []

    def fake_git(root: Path, *args: str, timeout: int | None = 120):
        calls.append((root, args, timeout))
        if args == ("remote",):
            return git_engine.CommandResult(["git", *args], str(root), 0, "github\n", "")
        return git_engine.CommandResult(["git", *args], str(root), 0, "", "")

    monkeypatch.setattr(git_engine, "git", fake_git)

    results = git_engine.apply_remotes_from_config(tmp_path, config_path)

    assert all(result.ok for result in results)
    assert calls == [
        (tmp_path, ("remote",), 120),
        (tmp_path, ("remote", "set-url", "github", "git@github.com:audion/Audion_Hub.git"), 120),
        (tmp_path, ("remote", "add", "gitlab", "git@gitlab.com:audion/Audion_Hub.git"), 120),
    ]


def test_configure_origin_push_urls_adds_missing_urls_without_clearing_existing(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "remotes.json"
    config_path.write_text(
        json.dumps(
            {
                "global_remotes": [
                    {"name": "github", "enabled": True, "url": "git@github.com:audion/Audion_Hub.git"},
                    {"name": "gitlab", "enabled": True, "url": "git@gitlab.com:audion/Audion_Hub.git"},
                ]
            }
        ),
        encoding="utf-8",
    )
    calls: list[tuple[Path, tuple[str, ...], int | None]] = []

    def fake_git(root: Path, *args: str, timeout: int | None = 120):
        calls.append((root, args, timeout))
        if args == ("remote",):
            return git_engine.CommandResult(["git", *args], str(root), 0, "origin\n", "")
        if args == ("config", "--get-all", "remote.origin.pushurl"):
            return git_engine.CommandResult(["git", *args], str(root), 0, "git@github.com:audion/Audion_Hub.git\n", "")
        return git_engine.CommandResult(["git", *args], str(root), 0, "", "")

    monkeypatch.setattr(git_engine, "git", fake_git)

    results = git_engine.configure_origin_push_urls_from_config(tmp_path, config_path)

    assert all(result.ok for result in results)
    assert calls == [
        (tmp_path, ("remote",), 120),
        (tmp_path, ("config", "--get-all", "remote.origin.pushurl"), 120),
        (tmp_path, ("remote", "set-url", "--add", "--push", "origin", "git@gitlab.com:audion/Audion_Hub.git"), 120),
    ]
