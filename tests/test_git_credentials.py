from __future__ import annotations

import pytest

from system_core.core.git_credentials import (
    CredentialResult,
    CredentialTarget,
    encode_fields,
    parse_fields,
    target_from_url,
)


def test_target_from_url_keeps_only_a_non_default_port() -> None:
    assert target_from_url("https://git.audion.dev").host == "git.audion.dev"
    assert target_from_url("https://git.audion.dev:443").host == "git.audion.dev"
    assert target_from_url("https://git.audion.dev:8443").host == "git.audion.dev:8443"
    assert target_from_url("git.audion.dev").protocol == "https"


def test_target_from_url_rejects_values_git_cannot_use() -> None:
    with pytest.raises(ValueError):
        target_from_url("")
    with pytest.raises(ValueError):
        target_from_url("ssh://git@git.audion.dev")


def test_encode_and_parse_round_trip_the_credential_protocol() -> None:
    payload = encode_fields({"protocol": "https", "host": "git.audion.dev", "username": "audion", "password": "t0ken"})
    assert payload.endswith("\n\n")
    assert parse_fields(payload) == {
        "protocol": "https",
        "host": "git.audion.dev",
        "username": "audion",
        "password": "t0ken",
    }


def test_encode_fields_drops_empty_values() -> None:
    assert "username" not in encode_fields({"protocol": "https", "host": "git.audion.dev", "username": ""})


def test_result_dict_never_carries_the_secret() -> None:
    result = CredentialResult(
        action="fill",
        target=CredentialTarget("https", "git.audion.dev", "audion"),
        returncode=0,
        fields={"username": "audion", "password": "t0ken"},
    )

    payload = result.to_dict()
    assert payload["has_secret"] is True
    assert "t0ken" not in str(payload)
    assert "t0ken" not in result.joined_command()
