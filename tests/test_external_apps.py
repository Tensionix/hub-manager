from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from system_core.core import external_apps


def test_vscode_command_prefers_configured_code_exe(tmp_path: Path, monkeypatch) -> None:
    config = tmp_path / "config"
    config.mkdir()
    code = tmp_path / "Code.exe"
    code.write_text("", encoding="utf-8")
    (config / "apps.json").write_text(
        '{"apps": {"vscode": {"command": "%s"}, "vscode_folder": {"command": "%s"}}}'
        % (str(code).replace("\\", "\\\\"), str(code).replace("\\", "\\\\")),
        encoding="utf-8",
    )

    monkeypatch.setattr(external_apps, "get_project_paths", lambda: SimpleNamespace(config=config))

    assert external_apps._vscode_command() == str(code)
    assert external_apps._vscode_command(folder=True) == str(code)


def test_vscode_command_prefers_local_override(tmp_path: Path, monkeypatch) -> None:
    config = tmp_path / "config"
    config.mkdir()
    base_code = tmp_path / "BaseCode.exe"
    local_code = tmp_path / "LocalCode.exe"
    base_code.write_text("", encoding="utf-8")
    local_code.write_text("", encoding="utf-8")
    (config / "apps.json").write_text(
        '{"apps": {"vscode": {"command": "%s"}, "vscode_folder": {"command": "%s"}}}'
        % (str(base_code).replace("\\", "\\\\"), str(base_code).replace("\\", "\\\\")),
        encoding="utf-8",
    )
    (config / "apps.local.json").write_text(
        '{"apps": {"vscode": {"command": "%s"}, "vscode_folder": {"command": "%s"}}}'
        % (str(local_code).replace("\\", "\\\\"), str(local_code).replace("\\", "\\\\")),
        encoding="utf-8",
    )

    monkeypatch.setattr(external_apps, "get_project_paths", lambda: SimpleNamespace(config=config))

    assert external_apps.configured_vscode_command() == str(local_code)
    assert external_apps._vscode_command() == str(local_code)


def test_vscode_command_accepts_quoted_path(tmp_path: Path, monkeypatch) -> None:
    config = tmp_path / "config"
    config.mkdir()
    code = tmp_path / "Code With Spaces.exe"
    code.write_text("", encoding="utf-8")
    (config / "apps.json").write_text(
        '{"apps": {"vscode": {"command": "\\"%s\\""}, "vscode_folder": {"command": "\\"%s\\""}}}'
        % (str(code).replace("\\", "\\\\"), str(code).replace("\\", "\\\\")),
        encoding="utf-8",
    )

    monkeypatch.setattr(external_apps, "get_project_paths", lambda: SimpleNamespace(config=config))

    assert external_apps.configured_vscode_command() == str(code)
    assert external_apps._vscode_command() == str(code)
