from __future__ import annotations

from datetime import datetime
from pathlib import Path
import hashlib
import os
import shutil
import subprocess

try:
    from blake3 import blake3 as _blake3_factory
except Exception:  # pragma: no cover - optional runtime dependency
    _blake3_factory = None

from .paths import get_project_paths


def timestamp_slug() -> str:
    """Return a collision-resistant timestamp for reports and temp files."""
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def external_b3sum_path() -> str | None:
    root = get_project_paths().root
    candidates = [root / "b3sum.exe", root / "system_core" / "b3sum.exe"]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return shutil.which("b3sum.exe") or shutil.which("b3sum")


def hash_file_blake3(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Return an algorithm-tagged digest for file comparison.

    The SHA-256 fallback is a same-run correctness fallback for minimal
    portable/test environments. It is not a BLAKE3-compatible digest, so the
    returned value is prefixed with the active algorithm name.
    """
    if _blake3_factory is not None:
        hasher = _blake3_factory()
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(chunk_size)
                if not chunk:
                    break
                hasher.update(chunk)
        return f"blake3:{hasher.hexdigest()}"

    external = external_b3sum_path()
    if external:
        completed = subprocess.run([external, str(path)], capture_output=True, text=True, check=False)
        if completed.returncode == 0 and completed.stdout.strip():
            digest = completed.stdout.strip().splitlines()[0].split(" ", 1)[0]
            return f"blake3:{digest}"

    # Correctness fallback for tests/minimal portable builds. Production bundles should
    # still ship Python package `blake3` or `b3sum.exe` for the intended fast path.
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
    return f"sha256:{hasher.hexdigest()}"


def safe_copy2(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    # Keep the temp file next to dst: os.replace is atomic only on the same volume.
    tmp = dst.with_name(f".{dst.name}.audion_tmp_{timestamp_slug()}")
    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
