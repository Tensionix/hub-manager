from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
import re

from .scan_engine import is_link


HEAVY_EXTENSIONS = {
    ".zip",
    ".7z",
    ".rar",
    ".iso",
    ".img",
    ".mp4",
    ".mov",
    ".mkv",
    ".avi",
    ".wav",
    ".flac",
    ".whl",
    ".exe",
    ".dll",
    ".pyd",
    ".msi",
}

SECRET_EXTENSIONS = {".key", ".pem", ".p12", ".pfx", ".ppk", ".kdbx"}
SECRET_FILENAMES = {".env", ".npmrc", ".pypirc", ".netrc", "id_rsa", "id_ed25519"}
SECRET_EXAMPLE_FILENAMES = {".env.example", ".env.sample", ".env.template"}
DEFAULT_SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".cache",
    "node_modules",
    "runtime",
    "wheelhouse",
    "logs",
    "output",
    "backup",
    "release",
    "report",
    "temp",
    "tmp",
}
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private_key_block", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
    # The [Interface] of WireGuard and AmneziaWG: a file of any name, a key of 32 bytes in base64.
    ("wireguard_private_key", re.compile(r"(?im)^\s*PrivateKey\s*=\s*[A-Za-z0-9+/]{42,43}=")),
    ("aws_access_key_id", re.compile(r"\bA[KS]IA[0-9A-Z]{16}\b")),
    # rclone.conf and ~/.aws/credentials: the secret of S3 is a line of its own, not a word "secret".
    ("s3_secret_access_key", re.compile(r"(?im)^\s*(?:aws_)?secret_access_key\s*=\s*\S{16,}")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")),
    ("openai_api_key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    (
        "secret_assignment",
        re.compile(
            r"(?i)\b(api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|password|passwd|pass|secret)\b"
            r"\s*[:=]\s*['\"]?([A-Za-z0-9_./+=:@-]{12,})"
        ),
    ),
)
PLACEHOLDER_VALUES = {
    "changeme",
    "change_me",
    "change-me",
    "example",
    "sample",
    "placeholder",
    "your_token_here",
    "your-api-key",
    "your_api_key",
    "insert-token-here",
}


@dataclass(frozen=True)
class SafetyFinding:
    rel_path: str
    abs_path: str
    size: int
    flags: list[str]
    reasons: list[str]
    severity: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _looks_like_secret_name(path: Path) -> bool:
    name = path.name.lower()
    if name in SECRET_EXAMPLE_FILENAMES:
        return False
    return name in SECRET_FILENAMES or (name.startswith(".env.") and name not in SECRET_EXAMPLE_FILENAMES)


def classify_path(path: Path, heavy_threshold: int = 25 * 1024 * 1024) -> list[str]:
    flags: list[str] = []
    suffix = path.suffix.lower()
    if suffix in HEAVY_EXTENSIONS:
        flags.append("heavy_ext")
    if suffix in SECRET_EXTENSIONS or _looks_like_secret_name(path):
        flags.append("secret_candidate")
    try:
        if path.is_file() and path.stat().st_size > heavy_threshold:
            flags.append("large_file")
    except OSError:
        pass
    return flags


def _safe_rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _is_probably_binary(data: bytes) -> bool:
    return b"\x00" in data[:4096]


def _placeholder_value(value: str) -> bool:
    normalized = value.strip().strip("'\"").strip().lower()
    normalized = re.sub(r"[^a-z0-9_-]+", "", normalized)
    return normalized in PLACEHOLDER_VALUES


def _secret_content_flags(path: Path, max_content_bytes: int) -> tuple[list[str], str]:
    """The flags of what the text holds, and why it could not be read ("" when it was). A file not read is not a clean
    file: a file held open by another program once passed the scan with a secret in it."""
    try:
        if path.stat().st_size > max_content_bytes:
            return [], ""
        data = path.read_bytes()
    except OSError as exc:
        return [], f"{exc.__class__.__name__}: {exc.strerror or exc}"
    if not data or _is_probably_binary(data):
        return [], ""
    text = data.decode("utf-8", errors="ignore")
    flags: list[str] = []
    for name, pattern in SECRET_PATTERNS:
        for match in pattern.finditer(text):
            if name == "secret_assignment" and match.lastindex and match.lastindex >= 2:
                if _placeholder_value(match.group(2)):
                    continue
            flags.append(name)
            break
    return flags, ""


def _finding_severity(flags: list[str]) -> str:
    blocker_markers = ("secret", "private_key", "api_key", "access_key", "token", "password", "passwd", "client_secret")
    if any(any(marker in flag for marker in blocker_markers) for flag in flags):
        return "blocker"
    return "warning"


def scan_safety(
    root: Path,
    *,
    heavy_threshold: int = 25 * 1024 * 1024,
    max_content_bytes: int = 512 * 1024,
    skip_dirs: set[str] | None = None,
) -> dict[str, object]:
    root = root.expanduser()
    try:
        root = root.resolve()
    except OSError:
        root = root.absolute()
    skipped_dir_names = {item.lower() for item in (skip_dirs or DEFAULT_SKIP_DIRS)}
    findings: list[SafetyFinding] = []
    skipped_dirs: list[str] = []
    errors: list[str] = []
    files_scanned = 0
    dirs_scanned = 0

    if not root.exists() or not root.is_dir():
        return {
            "action": "safety_scan",
            "created_at": datetime.now().isoformat(),
            "root": str(root),
            "ok": False,
            "summary": {
                "root_exists": root.exists(),
                "files_scanned": 0,
                "dirs_scanned": 0,
                "dirs_skipped": 0,
                "findings": 0,
                "blockers": 0,
                "warnings": 0,
                "errors": 1,
            },
            "findings": [],
            "skipped_dirs": [],
            "errors": [f"Root is missing or not a directory: {root}"],
        }

    stack = [root]
    while stack:
        current = stack.pop()
        dirs_scanned += 1
        try:
            entries = sorted(current.iterdir(), key=lambda path: (not path.is_dir(), path.name.lower()))
        except OSError as exc:
            errors.append(f"{_safe_rel(current, root)}: {exc}")
            continue
        for entry in entries:
            if is_link(entry):
                # A junction or a link leads out of the project: not followed, as the mirror does not follow it.
                skipped_dirs.append(_safe_rel(entry, root))
                continue
            if entry.is_dir():
                if entry.name.lower() in skipped_dir_names:
                    skipped_dirs.append(_safe_rel(entry, root))
                    continue
                stack.append(entry)
                continue
            if not entry.is_file():
                continue
            files_scanned += 1
            flags = classify_path(entry, heavy_threshold=heavy_threshold)
            content_flags, unread = _secret_content_flags(entry, max_content_bytes=max_content_bytes)
            if unread:
                errors.append(f"{_safe_rel(entry, root)}: not read - {unread}")
            all_flags = list(dict.fromkeys([*flags, *content_flags]))
            if not all_flags:
                continue
            try:
                size = entry.stat().st_size
            except OSError:
                size = 0
            reasons = []
            if "heavy_ext" in all_flags:
                reasons.append("heavy extension")
            if "large_file" in all_flags:
                reasons.append(f"larger than {heavy_threshold} bytes")
            if "secret_candidate" in all_flags:
                reasons.append("secret-like filename or extension")
            reasons.extend(flag for flag in content_flags if flag not in {"secret_candidate", "large_file", "heavy_ext"})
            findings.append(
                SafetyFinding(
                    rel_path=_safe_rel(entry, root),
                    abs_path=str(entry),
                    size=size,
                    flags=all_flags,
                    reasons=reasons,
                    severity=_finding_severity(all_flags),
                )
            )

    findings.sort(key=lambda item: (0 if item.severity == "blocker" else 1, item.rel_path.lower()))
    blockers = sum(1 for item in findings if item.severity == "blocker")
    warnings = len(findings) - blockers
    return {
        "action": "safety_scan",
        "created_at": datetime.now().isoformat(),
        "root": str(root),
        "ok": blockers == 0 and warnings == 0 and not errors,
        "summary": {
            "root_exists": True,
            "files_scanned": files_scanned,
            "dirs_scanned": dirs_scanned,
            "dirs_skipped": len(skipped_dirs),
            "findings": len(findings),
            "blockers": blockers,
            "warnings": warnings,
            "errors": len(errors),
            "heavy_threshold": heavy_threshold,
            "max_content_bytes": max_content_bytes,
        },
        "findings": [item.to_dict() for item in findings],
        "skipped_dirs": skipped_dirs[:500],
        "errors": errors,
    }
