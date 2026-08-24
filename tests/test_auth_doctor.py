from __future__ import annotations

from system_core.core.auth_doctor import parse_git_remote_v, remote_provider, remote_url_type


def test_remote_url_type_classifies_hub_mirror_urls() -> None:
    assert remote_url_type("git@github.com:audion/Audion_Hub.git") == "ssh"
    assert remote_url_type("ssh://git@gitlab.com/audion/Audion_Hub.git") == "ssh"
    assert remote_url_type("https://gitlab.com/audion/Audion_Hub.git") == "https"
    assert remote_url_type("file:///Z:/git-mirrors/Audion_Hub.git") == "file"


def test_remote_provider_detects_github_gitlab_and_local() -> None:
    assert remote_provider("git@github.com:audion/Audion_Hub.git") == "github"
    assert remote_provider("https://gitlab.com/audion/Audion_Hub.git") == "gitlab"
    assert remote_provider("file:///Z:/git-mirrors/Audion_Hub.git") == "local"


def test_remote_provider_labels_self_hosted_instances_from_known_hosts() -> None:
    known = {"git.audion.dev": "forgejo"}
    assert remote_provider("git@git.audion.dev:audion/Audion_Hub.git", known) == "forgejo"
    assert remote_provider("https://git.audion.dev/audion/Audion_Hub.git", known) == "forgejo"
    assert remote_provider("ssh://git@git.audion.dev:2222/audion/Audion_Hub.git", known) == "forgejo"
    # Without the mapping the bare hostname is still the honest answer.
    assert remote_provider("https://git.audion.dev/audion/Audion_Hub.git") == "git.audion.dev"


def test_parse_git_remote_v_keeps_fetch_and_push_rows() -> None:
    rows = parse_git_remote_v(
        "\n".join(
            [
                "github\tgit@github.com:audion/Audion_Hub.git (fetch)",
                "github\tgit@github.com:audion/Audion_Hub.git (push)",
                "gitlab\thttps://gitlab.com/audion/Audion_Hub.git (push)",
            ]
        )
    )

    assert rows == [
        {
            "name": "github",
            "url": "git@github.com:audion/Audion_Hub.git",
            "usage": "fetch",
            "url_type": "ssh",
            "provider": "github",
        },
        {
            "name": "github",
            "url": "git@github.com:audion/Audion_Hub.git",
            "usage": "push",
            "url_type": "ssh",
            "provider": "github",
        },
        {
            "name": "gitlab",
            "url": "https://gitlab.com/audion/Audion_Hub.git",
            "usage": "push",
            "url_type": "https",
            "provider": "gitlab",
        },
    ]
