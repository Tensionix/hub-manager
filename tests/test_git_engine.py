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


def test_validate_remote_url_accepts_the_forms_hub_manager_builds() -> None:
    for url in (
        "git@github.com:audion/Audion_Hub.git",
        "ssh://git@git.audion.dev:2222/audion/Audion_Hub.git",
        "https://git.audion.dev/audion/Audion_Hub.git",
        "file:///Z:/git-mirrors/Audion_Hub.git",
    ):
        assert validate_remote_url(url) == url

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
    assert {item.path: item.label for item in status.files} == {
        "README.md": "modified",
        "staged.py": "staged",
        "new.txt": "untracked",
        "conflict.md": "conflict",
    }


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


