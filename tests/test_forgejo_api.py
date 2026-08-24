from __future__ import annotations

import pytest

from system_core.core.forgejo_api import (
    ApiResult,
    ForgejoHost,
    build_https_remote_url,
    build_remote_url,
    build_ssh_remote_url,
    hosts_from_config,
    normalize_base_url,
    parse_missing_scopes,
    redact_token,
    repo_summary,
    user_summary,
)
from system_core.core.forgejo_service import token_failure_detail, token_failure_message_key


def test_normalize_base_url_accepts_bare_host_and_trims_trailing_slash() -> None:
    assert normalize_base_url("git.audion.dev") == "https://git.audion.dev"
    assert normalize_base_url("https://git.audion.dev/") == "https://git.audion.dev"
    assert normalize_base_url("https://example.org/git/") == "https://example.org/git"


def test_normalize_base_url_rejects_unusable_values() -> None:
    with pytest.raises(ValueError):
        normalize_base_url("")
    with pytest.raises(ValueError):
        normalize_base_url("ssh://git.audion.dev")


@pytest.mark.parametrize(
    "hostile",
    [
        "https://evil.example.org;calc.exe",
        "https://host$(whoami)",
        "https://a&&b",
        "https://host`id`",
        "https://host with space",
        "https://user:token@git.example.org",
    ],
)
def test_normalize_base_url_rejects_hosts_that_could_reach_a_shell(hostile: str) -> None:
    # The hostname is interpolated into `ssh -T <user>@<host>`, which the GUI
    # runs through a shell, and the value can come from a project's config file.
    with pytest.raises(ValueError):
        normalize_base_url(hostile)


def test_normalize_base_url_still_accepts_ordinary_addresses() -> None:
    assert normalize_base_url("https://127.0.0.1:3000") == "https://127.0.0.1:3000"
    assert normalize_base_url("http://git.lan") == "http://git.lan"
    assert normalize_base_url("https://sub.domain.example.org/git") == "https://sub.domain.example.org/git"


def test_host_construction_rejects_a_shell_bearing_ssh_user_or_port() -> None:
    with pytest.raises(ValueError):
        ForgejoHost(id="x", title="t", url="https://git.example.org", ssh_user="git; calc")
    with pytest.raises(ValueError):
        ForgejoHost(id="x", title="t", url="https://git.example.org", ssh_port=0)
    with pytest.raises(ValueError):
        ForgejoHost(id="x", title="t", url="https://git.example.org", ssh_port=99999)


def test_hosts_from_config_drops_hostile_records_instead_of_raising() -> None:
    hosts = hosts_from_config(
        {"hosts": [{"url": "https://a;calc.exe"}, {"url": "https://ok.example.org"}, {"url": "https://b", "ssh_user": "x;y"}]}
    )
    assert [host.hostname for host in hosts] == ["ok.example.org"]


def test_ssh_url_uses_scp_form_on_default_port_and_ssh_scheme_otherwise() -> None:
    host = ForgejoHost(id="audion", title="Audion", url="https://git.audion.dev")
    assert build_ssh_remote_url(host, "audion", "Audion_Hub") == "git@git.audion.dev:audion/Audion_Hub.git"

    custom_port = ForgejoHost(id="alt", title="Alt", url="https://git.example.org", ssh_port=2222)
    assert build_ssh_remote_url(custom_port, "audion", "Repo") == "ssh://git@git.example.org:2222/audion/Repo.git"


def test_remote_urls_drop_a_trailing_git_suffix_and_need_both_parts() -> None:
    host = ForgejoHost(id="audion", title="Audion", url="https://git.audion.dev")
    assert build_ssh_remote_url(host, "audion", "Repo.git") == "git@git.audion.dev:audion/Repo.git"
    assert build_https_remote_url(host, "audion", "Repo.git") == "https://git.audion.dev/audion/Repo.git"
    assert build_ssh_remote_url(host, "", "Repo") == ""
    assert build_https_remote_url(host, "audion", "") == ""


def test_build_remote_url_follows_the_requested_type_then_the_host_preference() -> None:
    host = ForgejoHost(id="audion", title="Audion", url="https://git.audion.dev", preferred_url_type="https")
    assert build_remote_url(host, "audion", "Repo") == "https://git.audion.dev/audion/Repo.git"
    assert build_remote_url(host, "audion", "Repo", "ssh") == "git@git.audion.dev:audion/Repo.git"


def test_hosts_from_config_skips_broken_records_and_defaults_the_id() -> None:
    hosts = hosts_from_config(
        {
            "hosts": [
                {"title": "No URL"},
                {"url": "https://git.audion.dev", "ssh_port": "2222"},
                {"id": "named", "url": "git.example.org", "preferred_url_type": "HTTPS"},
                "not a record",
            ]
        }
    )

    assert [host.id for host in hosts] == ["git.audion.dev", "named"]
    assert hosts[0].ssh_port == 2222
    assert hosts[1].preferred_url_type == "https"
    assert hosts[1].base_url == "https://git.example.org"


def test_redact_token_removes_the_value_forgejo_echoes_back() -> None:
    # Forgejo 15 answers an unknown token by quoting it back in the error body.
    raw = "HTTP 401: access token does not exist [sha: 1a2b3c4d5e6f7a8b9c0d]"
    cleaned = redact_token(raw, "1a2b3c4d5e6f7a8b9c0d")
    assert "1a2b3c4d5e6f7a8b9c0d" not in cleaned
    assert cleaned == "HTTP 401: access token does not exist [sha: ***]"

    # The bracket form is stripped even when the token itself is not known here.
    assert "secret" not in redact_token("access token does not exist [sha: secretvalue]")

    # Short strings are never used as a replacement pattern: that would redact prose.
    assert redact_token("HTTP 403: forbidden", "abc") == "HTTP 403: forbidden"


def test_parse_missing_scopes_reads_the_forgejo_403_body() -> None:
    # Verbatim shape returned by Forgejo 15 when a token lacks a scope.
    error = "HTTP 403: token does not have at least one of required scope(s): [read:user]"
    assert parse_missing_scopes(error) == ["read:user"]
    assert parse_missing_scopes("HTTP 403: required scope(s): [read:user, write:repository]") == [
        "read:user",
        "write:repository",
    ]
    assert parse_missing_scopes("HTTP 401: unauthorized") == []
    assert parse_missing_scopes("") == []


def test_a_scope_failure_is_reported_separately_from_a_bad_token() -> None:
    scope_denied = ApiResult(
        method="GET",
        url="https://git.example.org/api/v1/user",
        status=403,
        error="HTTP 403: token does not have at least one of required scope(s): [read:user]",
    )
    assert scope_denied.forbidden is True
    assert scope_denied.unauthorized is False
    assert token_failure_message_key(scope_denied) == "forgejo_token_scope_missing"
    assert token_failure_detail(scope_denied) == "read:user"

    bad_token = ApiResult(method="GET", url="https://git.example.org/api/v1/user", status=401, error="HTTP 401")
    assert token_failure_message_key(bad_token) == "forgejo_token_unauthorized"

    server_down = ApiResult(method="GET", url="https://git.example.org/api/v1/user", error="ConnectError: refused")
    assert token_failure_message_key(server_down) == "forgejo_token_rejected"
    assert token_failure_detail(server_down) == "ConnectError: refused"


def test_summaries_flatten_only_the_fields_the_ui_needs() -> None:
    repo = repo_summary(
        {
            "full_name": "audion/Audion_Hub",
            "name": "Audion_Hub",
            "owner": {"login": "audion", "id": 1},
            "private": True,
            "ssh_url": "git@git.audion.dev:audion/Audion_Hub.git",
            "clone_url": "https://git.audion.dev/audion/Audion_Hub.git",
            "default_branch": "main",
        }
    )
    assert repo["owner"] == "audion"
    assert repo["private"] is True
    assert repo["default_branch"] == "main"

    assert user_summary({"login": "audion", "full_name": "Audion", "email": "a@example.org"})["login"] == "audion"
    assert user_summary("not a record") == {}
