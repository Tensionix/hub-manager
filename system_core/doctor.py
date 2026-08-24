from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audion Hub Manager portable environment doctor")
    parser.add_argument("--project-root", default="", help="Project root override")
    args = parser.parse_args(argv)

    root = Path(args.project_root).resolve() if args.project_root else Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    print(f"Root: {root}")
    for package in ["nicegui", "blake3", "yaml", "webview", "rich", "tqdm", "pytest"]:
        print(f"{package}: {'OK' if importlib.util.find_spec(package) else 'missing'}")
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
        algorithm = digest.partition(":")[0]
        print(f"blake3_backend: {algorithm}")
    except Exception as exc:
        print(f"blake3_backend: error ({exc.__class__.__name__}: {exc})")
    for path in [
        "AGENTS.md",
        "builder_main.cmd",
        "cleanup_project.cmd",
        "config/projects.json",
        "config/projection_profiles.json",
        "install/requirements_full.in",
        "licenses/RELEASE_POLICY.md",
        "system_core/main.py",
        "system_core/ui_nicegui/app.py",
    ]:
        print(f"{path}: {'OK' if (root / path).exists() else 'missing'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
