"""Audion Hub Manager: is the portable environment whole?

Step [71] of the builder and the last step of a build of the environment run it. It checks what the console door
(system_core\\cli.py) and the engine import, that BLAKE3 hashes, that the canon of Git reads, that git is there for
the window to call, and the files a release cannot go without. A missing package or file ends with exit code 1.
"""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys

# The packages of the engine: blake3 checks a mirror, httpx talks to Forgejo, yaml reads a layout written in YAML.
REQUIRED_PACKAGES = ("blake3", "httpx", "yaml")
# The test layer: the builder runs the tests with it, the program does not need it.
TEST_PACKAGES = ("pytest",)
REQUIRED_FILES = (
    "AGENTS.md",
    "builder_main.cmd",
    "cleanup_project.cmd",
    "hub_cli.cmd",
    "config/version.json",
    "config/projects.example.json",
    "config/projection_profiles.json",
    "install/requirements_full.in",
    "system_core/cli.py",
    "system_core/core/git_canon.py",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audion Hub Manager portable environment doctor")
    parser.add_argument("--project-root", default="", help="Project root override")
    args = parser.parse_args(argv)

    root = Path(args.project_root).resolve() if args.project_root else Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    print(f"Root: {root}")
    problems = 0

    for package in REQUIRED_PACKAGES + TEST_PACKAGES:
        found = importlib.util.find_spec(package) is not None
        print(f"{package}: {'OK' if found else 'missing'}")
        if not found and package in REQUIRED_PACKAGES:
            problems += 1

    try:
        from system_core.core.copy_engine import hash_file_blake3

        probe_dir = root / "._runtime"
        probe_dir.mkdir(parents=True, exist_ok=True)
        probe = probe_dir / "doctor_blake3_probe.bin"
        probe.write_bytes(b"Audion Hub Manager doctor BLAKE3 probe\n")
        try:
            digest = hash_file_blake3(probe)
        finally:
            try:
                probe.unlink()
            except OSError:
                pass
        print(f"blake3_backend: {digest.partition(':')[0]}")
    except Exception as exc:
        print(f"blake3_backend: error ({exc.__class__.__name__}: {exc})")
        problems += 1

    try:
        from system_core.core import git_canon

        print(f"git_canon: {len(git_canon.CANON)} operations")
    except Exception as exc:
        print(f"git_canon: error ({exc.__class__.__name__}: {exc})")
        problems += 1

    # The window calls git itself; without it the program shows nothing. Not a fault of the environment - a warning.
    git = shutil.which("git")
    if git:
        answer = subprocess.run([git, "--version"], capture_output=True, text=True, check=False)
        print(f"git: {answer.stdout.strip() or git}")
    else:
        print("git: missing - [WARN] the window needs git on PATH")

    for path in REQUIRED_FILES:
        found = (root / path).exists()
        print(f"{path}: {'OK' if found else 'missing'}")
        if not found:
            problems += 1

    print("[OK] the environment is whole" if problems == 0 else f"[FAIL] {problems} problem(s)")
    return 0 if problems == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
