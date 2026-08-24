from __future__ import annotations

from pathlib import Path

import pytest

from system_core.core.safety import classify_path, is_dangerous_command, scan_safety


@pytest.mark.parametrize(
    "command",
    [
        "git reset --hard",
        "git -C repo reset --hard HEAD",
        "git clean -fd",
        "git clean -dfx",
        "git clean -f -d",
        "git clean --force --directories",
        "git push --force origin main",
        "git push -f origin main",
        "git push --force-with-lease",
        "git push --force-with-lease=refs/heads/main",
        "rm -rf build",
        "rm -fr build",
        "rm -r -f build",
        "rm --recursive --force build",
        "rmdir /s build",
        "rd /s /q build",
        "del /s *.tmp",
        "erase /s *.tmp",
    ],
)
def test_is_dangerous_command_blocks_destructive_commands(command: str) -> None:
    assert is_dangerous_command(command)


@pytest.mark.parametrize(
    "command",
    [
        "git status && rm -fr build",
        "git status; git reset --hard",
        "git status | rm --recursive --force build",
        "echo $(rm --recursive --force build)",
        "echo `rm -rf build`",
    ],
)
def test_is_dangerous_command_blocks_compound_payloads(command: str) -> None:
    assert is_dangerous_command(command)


@pytest.mark.parametrize(
    "command",
    [
        'sh -c "rm -fr build"',
        'bash -lc "git reset --hard"',
        'cmd /c "rmdir /s /q build"',
        'powershell -NoProfile -Command "Remove-Item -Recurse -Force build"',
        'pwsh -Command "git push --force"',
        "powershell -EncodedCommand SQBFAFgA",
    ],
)
def test_is_dangerous_command_blocks_nested_shell_payloads(command: str) -> None:
    assert is_dangerous_command(command)


@pytest.mark.parametrize(
    "command",
    [
        "git status --short",
        "git clean -fdn",
        "git clean --dry-run --force --directories",
        "git push origin main",
        "rm -f single-file.txt",
        "echo rm -rf build",
        "type README.md > out.txt",
        "git status | findstr modified",
        "powershell -Command \"Write-Output 'rm -rf build'\"",
    ],
)
def test_is_dangerous_command_allows_common_safe_commands(command: str) -> None:
    assert not is_dangerous_command(command)


def test_classify_path_marks_heavy_and_secret_candidates(tmp_path: Path) -> None:
    archive = tmp_path / "payload.zip"
    archive.write_bytes(b"x")
    key = tmp_path / "id_ed25519"
    key.write_text("not a real key\n", encoding="utf-8")
    large = tmp_path / "large.txt"
    large.write_bytes(b"12345")

    assert "heavy_ext" in classify_path(archive)
    assert "secret_candidate" in classify_path(key)
    assert "large_file" in classify_path(large, heavy_threshold=4)


def test_scan_safety_detects_secret_content_without_leaking_value(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    token_file = root / "config.py"
    secret_value = "sk-" + ("a" * 40)
    token_file.write_text(f"OPENAI_API_KEY = '{secret_value}'\n", encoding="utf-8")

    payload = scan_safety(root)
    finding = payload["findings"][0]

    assert payload["summary"]["blockers"] == 1
    assert finding["rel_path"] == "config.py"
    assert "openai_api_key" in finding["flags"]
    assert secret_value not in str(payload)


def test_scan_safety_skips_generated_directories_by_default(tmp_path: Path) -> None:
    root = tmp_path / "project"
    runtime = root / "runtime"
    runtime.mkdir(parents=True)
    password_line = "PASSWORD=" + "real_secret_value_12345" + "\n"
    (runtime / ".env").write_text(password_line, encoding="utf-8")
    (root / "README.md").write_text("# clean\n", encoding="utf-8")

    payload = scan_safety(root)

    assert payload["summary"]["findings"] == 0
    assert payload["summary"]["dirs_skipped"] == 1
    assert payload["skipped_dirs"] == ["runtime"]


def test_scan_safety_warns_for_large_files_and_heavy_extensions(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    wheel = root / "package.whl"
    wheel.write_bytes(b"x")
    big = root / "data.bin"
    big.write_bytes(b"123456")

    payload = scan_safety(root, heavy_threshold=5)
    findings = {item["rel_path"]: item for item in payload["findings"]}

    assert payload["summary"]["warnings"] == 2
    assert findings["package.whl"]["severity"] == "warning"
    assert "heavy_ext" in findings["package.whl"]["flags"]
    assert "large_file" in findings["data.bin"]["flags"]


def test_scan_safety_missing_root_reports_error(tmp_path: Path) -> None:
    payload = scan_safety(tmp_path / "missing")

    assert payload["ok"] is False
    assert payload["summary"]["errors"] == 1
    assert payload["errors"]
