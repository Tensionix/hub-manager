from __future__ import annotations

from pathlib import Path


from system_core.core.safety import classify_path, scan_safety


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


def test_scan_safety_knows_the_keys_of_vpn_and_s3_by_their_content(tmp_path: Path) -> None:
    # A config of WireGuard or AmneziaWG and a remote of rclone may be named anything: the content tells.
    root = tmp_path / "project"
    (root / "vpn").mkdir(parents=True)
    key = "yAnz5TF+lXXJte14tji3zlMNq+hd2rYUIgJBgB3fBmk="
    (root / "vpn" / "peer.conf").write_text(f"[Interface]\nPrivateKey = {key}\nAddress = 10.0.0.2/32\n", encoding="utf-8")
    (root / "remotes.conf").write_text("[s3]\ntype = s3\nsecret_access_key = abcdefghijklmnopqrstuvwxyz0123\n", encoding="utf-8")
    (root / "sftp.conf").write_text("[box]\ntype = sftp\npass = Xk3mZq9vR2tLw8yHb5nC\n", encoding="utf-8")
    (root / "public.conf").write_text("[Peer]\nPublicKey = " + key + "\nAllowedIPs = 0.0.0.0/0\n", encoding="utf-8")

    payload = scan_safety(root)
    flags = {f["rel_path"]: f["flags"] for f in payload["findings"]}

    assert "wireguard_private_key" in flags["vpn/peer.conf"] and "s3_secret_access_key" in flags["remotes.conf"]
    assert "secret_assignment" in flags["sftp.conf"] and "public.conf" not in flags
    assert payload["summary"]["blockers"] == 3 and key not in str(payload)


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


def test_a_file_held_open_by_another_program_is_not_a_clean_file(tmp_path: Path) -> None:
    # The audit of 24.10.2026: a file locked with no sharing passed the scan with a secret in it.
    import ctypes
    from ctypes import wintypes

    root = tmp_path / "project"
    root.mkdir()
    notes = root / "notes.txt"
    notes.write_text("password = " + "Xk3mZq9vR2tLw8yHb5nC\n", encoding="utf-8")
    assert scan_safety(root)["summary"]["blockers"] == 1
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.restype = wintypes.HANDLE
    handle = kernel.CreateFileW(str(notes), 0x80000000, 0, None, 3, 0x80, None)  # GENERIC_READ, no sharing, OPEN_EXISTING
    try:
        locked = scan_safety(root)
    finally:
        kernel.CloseHandle(handle)
    assert locked["ok"] is False and locked["summary"]["errors"] == 1 and "notes.txt" in locked["errors"][0]
    assert scan_safety(root)["summary"]["blockers"] == 1