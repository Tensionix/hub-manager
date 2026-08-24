from __future__ import annotations

from pathlib import Path

from system_core.core import forgejo_service
from system_core.core.forgejo_api import ForgejoHost


def write_config(config_dir: Path, text: str) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "forgejo_hosts.json").write_text(text, encoding="utf-8")


def test_load_hosts_payload_survives_a_broken_file(tmp_path: Path) -> None:
    # The Remote pane reads this on every platform switch; a stray comma must
    # not raise into a NiceGUI event handler.
    write_config(tmp_path, '{"hosts": [ , ] }')

    payload = forgejo_service.load_hosts_payload(tmp_path)

    assert payload["hosts"] == []
    assert forgejo_service.load_hosts(tmp_path) == []
    assert forgejo_service.active_host(tmp_path) is None


def test_load_hosts_payload_normalises_a_wrong_shape(tmp_path: Path) -> None:
    write_config(tmp_path, '{"hosts": "not a list"}')
    assert forgejo_service.load_hosts_payload(tmp_path)["hosts"] == []

    write_config(tmp_path, "[]")
    assert forgejo_service.load_hosts_payload(tmp_path)["hosts"] == []


def test_missing_file_yields_the_default_config(tmp_path: Path) -> None:
    assert forgejo_service.load_hosts_payload(tmp_path)["policy"] == "personal_access_token"
    assert forgejo_service.load_hosts(tmp_path) == []


def test_remember_host_stores_a_server_typed_into_the_form(tmp_path: Path) -> None:
    # The login already matches, which is exactly the case remember_login skips.
    host = ForgejoHost(id="git.example.org", title="Example", url="https://git.example.org", login="audion")

    forgejo_service.remember_host(tmp_path, host, "audion")

    payload = forgejo_service.load_hosts_payload(tmp_path)
    assert [item["id"] for item in payload["hosts"]] == ["git.example.org"]
    assert payload["hosts"][0]["login"] == "audion"
    assert payload["active_host_id"] == "git.example.org"


def test_remember_host_updates_an_existing_record_without_duplicating_it(tmp_path: Path) -> None:
    host = ForgejoHost(id="git.example.org", title="Example", url="https://git.example.org", ssh_port=2222)
    forgejo_service.remember_host(tmp_path, host, "audion")
    forgejo_service.remember_host(tmp_path, host, "other")

    hosts = forgejo_service.load_hosts_payload(tmp_path)["hosts"]
    assert len(hosts) == 1
    assert hosts[0]["login"] == "other"
    assert hosts[0]["ssh_port"] == 2222


def test_active_host_prefers_the_active_id_then_an_enabled_record(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        """
        {
          "active_host_id": "second",
          "hosts": [
            {"id": "first", "url": "https://one.example.org", "enabled": false},
            {"id": "second", "url": "https://two.example.org"}
          ]
        }
        """,
    )
    assert forgejo_service.active_host(tmp_path).id == "second"
    assert forgejo_service.active_host(tmp_path, "first").id == "first"

    write_config(
        tmp_path,
        """
        {
          "active_host_id": "gone",
          "hosts": [
            {"id": "first", "url": "https://one.example.org", "enabled": false},
            {"id": "second", "url": "https://two.example.org"}
          ]
        }
        """,
    )
    # An unknown active id falls back to the first enabled host, not the first row.
    assert forgejo_service.active_host(tmp_path).id == "second"
