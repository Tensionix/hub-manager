from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
import re

COMMAND_SEPARATORS = {"&&", "||", "&", ";", "|"}
SHELL_COMMANDS = {"sh", "bash", "zsh", "cmd", "powershell", "pwsh"}
WINDOWS_RECURSIVE_DELETE_COMMANDS = {"del", "erase", "rd", "rmdir"}
POWERSHELL_REMOVE_ITEM_COMMANDS = {"remove-item", "rm", "ri", "del", "erase", "rd", "rmdir"}

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
    ("aws_access_key_id", re.compile(r"\bA[KS]IA[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")),
    ("openai_api_key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    (
        "secret_assignment",
        re.compile(
            r"(?i)\b(api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|password|passwd|secret)\b"
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


def _command_name(token: str) -> str:
    name = token.strip().strip("'\"").replace("\\", "/").rsplit("/", 1)[-1].lower()
    for suffix in (".exe", ".cmd", ".bat", ".ps1"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _tokenize_command(command: str) -> list[str]:
    tokens: list[str] = []
    current: list[str] = []
    quote: str | None = None
    index = 0

    def flush() -> None:
        if current:
            tokens.append("".join(current))
            current.clear()

    while index < len(command):
        char = command[index]
        if quote:
            if char == quote:
                quote = None
            elif char == "\\" and quote == '"' and index + 1 < len(command):
                index += 1
                current.append(command[index])
            else:
                current.append(char)
            index += 1
            continue

        if char in {"'", '"'}:
            quote = char
            index += 1
            continue
        if char in "\r\n":
            flush()
            tokens.append(";")
            index += 1
            continue
        if char.isspace():
            flush()
            index += 1
            continue
        two = command[index : index + 2]
        if two in {"&&", "||"}:
            flush()
            tokens.append(two)
            index += 2
            continue
        if char in {"&", ";", "|"}:
            flush()
            tokens.append(char)
            index += 1
            continue
        current.append(char)
        index += 1

    flush()
    return tokens


def _iter_command_segments(tokens: list[str]) -> list[list[str]]:
    segments: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in COMMAND_SEPARATORS:
            if current:
                segments.append(current)
                current = []
            continue
        current.append(token)
    if current:
        segments.append(current)
    return segments


def _short_flag_chars(token: str) -> set[str]:
    if not token.startswith("-") or token.startswith("--") or token == "-":
        return set()
    return {char.lower() for char in token[1:] if char.isalpha()}


def _has_any_flag(tokens: list[str], long_flags: set[str], short_flags: set[str]) -> bool:
    for token in tokens:
        lowered = token.lower()
        if lowered in long_flags or any(lowered.startswith(f"{flag}=") for flag in long_flags):
            return True
        if _short_flag_chars(token) & short_flags:
            return True
    return False


def _has_windows_switch(tokens: list[str], switch: str) -> bool:
    needle = f"/{switch.lower()}"
    return any(token.lower().startswith(needle) for token in tokens)


def _rm_is_dangerous(args: list[str]) -> bool:
    has_recursive = _has_any_flag(args, {"--recursive", "--dir"}, {"r"})
    return has_recursive


def _windows_delete_is_dangerous(args: list[str]) -> bool:
    return _has_windows_switch(args, "s")


def _powershell_remove_item_is_dangerous(args: list[str]) -> bool:
    lowered = [arg.lower() for arg in args]
    if any(arg.startswith("-whatif") for arg in lowered):
        return False
    return any(arg in {"-recurse", "-recursive", "-r"} or arg.startswith("-recurse:") for arg in lowered)


def _git_clean_is_dangerous(args: list[str]) -> bool:
    has_force = _has_any_flag(args, {"--force"}, {"f"})
    dry_run = _has_any_flag(args, {"--dry-run"}, {"n"}) or _has_any_flag(args, {"--interactive"}, {"i"})
    return has_force and not dry_run


def _git_push_is_dangerous(args: list[str]) -> bool:
    force_flags = {"--force", "--force-with-lease", "--force-if-includes"}
    return _has_any_flag(args, force_flags, {"f"})


def _git_is_dangerous(tokens: list[str]) -> bool:
    index = 1
    options_with_value = {"-c", "-C", "--git-dir", "--work-tree", "--namespace", "--config-env"}
    while index < len(tokens):
        token = tokens[index]
        if token in options_with_value:
            index += 2
            continue
        if token.startswith("--git-dir=") or token.startswith("--work-tree=") or token.startswith("--namespace="):
            index += 1
            continue
        if token.startswith("-"):
            index += 1
            continue
        break
    if index >= len(tokens):
        return False

    subcommand = tokens[index].lower()
    args = tokens[index + 1 :]
    if subcommand == "reset":
        return any(arg.lower() == "--hard" for arg in args)
    if subcommand == "clean":
        return _git_clean_is_dangerous(args)
    if subcommand == "push":
        return _git_push_is_dangerous(args)
    return False


def _shell_payload_is_dangerous(tokens: list[str], depth: int) -> bool:
    command = _command_name(tokens[0])
    lowered = [token.lower() for token in tokens[1:]]
    if command in {"sh", "bash", "zsh"}:
        for index, token in enumerate(lowered):
            if token == "-c" or (token.startswith("-") and "c" in token[1:]):
                payload_index = index + 2
                if payload_index < len(tokens):
                    return _is_dangerous_command(tokens[payload_index], depth + 1)
        return False

    if command == "cmd":
        for index, token in enumerate(lowered):
            if token in {"/c", "-c"}:
                payload = " ".join(tokens[index + 2 :])
                return bool(payload and _is_dangerous_command(payload, depth + 1))
        return False

    if command in {"powershell", "pwsh"}:
        for index, token in enumerate(lowered):
            if token in {"-encodedcommand", "-enc", "/encodedcommand", "/enc"}:
                return True
            if token in {"-command", "-c", "/command", "/c"}:
                payload = " ".join(tokens[index + 2 :])
                return bool(payload and _is_dangerous_command(payload, depth + 1))
        return False

    return False


def _strip_env_and_wrappers(tokens: list[str]) -> list[str]:
    index = 0
    assignment_re = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
    while index < len(tokens) and assignment_re.match(tokens[index]):
        index += 1
    if index < len(tokens) and _command_name(tokens[index]) == "sudo":
        index += 1
        while index < len(tokens) and tokens[index].startswith("-"):
            index += 1
    if index < len(tokens) and _command_name(tokens[index]) in {"command", "exec"}:
        index += 1
    if index < len(tokens) and _command_name(tokens[index]) == "env":
        index += 1
        while index < len(tokens) and (tokens[index].startswith("-") or assignment_re.match(tokens[index])):
            index += 1
    return tokens[index:]


def _segment_is_dangerous(segment: list[str], depth: int) -> bool:
    segment = _strip_env_and_wrappers(segment)
    if not segment:
        return False
    command = _command_name(segment[0])
    args = segment[1:]
    if command in SHELL_COMMANDS and _shell_payload_is_dangerous(segment, depth):
        return True
    if command == "git":
        return _git_is_dangerous(segment)
    if command == "rm" and _rm_is_dangerous(args):
        return True
    if command in WINDOWS_RECURSIVE_DELETE_COMMANDS and _windows_delete_is_dangerous(args):
        return True
    if command in POWERSHELL_REMOVE_ITEM_COMMANDS and _powershell_remove_item_is_dangerous(args):
        return True
    return False


def _extract_dollar_subcommands(command: str) -> list[str]:
    payloads: list[str] = []
    index = 0
    while index < len(command):
        start = command.find("$(", index)
        if start < 0:
            break
        depth = 1
        quote: str | None = None
        cursor = start + 2
        while cursor < len(command):
            char = command[cursor]
            if quote:
                if char == quote:
                    quote = None
                elif char == "\\" and quote == '"':
                    cursor += 1
            else:
                if char in {"'", '"'}:
                    quote = char
                elif command.startswith("$(", cursor):
                    depth += 1
                    cursor += 1
                elif char == ")":
                    depth -= 1
                    if depth == 0:
                        payloads.append(command[start + 2 : cursor])
                        index = cursor + 1
                        break
            cursor += 1
        else:
            break
    return payloads


def _extract_backtick_subcommands(command: str) -> list[str]:
    return [match.group(1) for match in re.finditer(r"`([^`]*)`", command)]


def _is_dangerous_command(command: str, depth: int = 0) -> bool:
    if depth > 4:
        return True
    for payload in [*_extract_dollar_subcommands(command), *_extract_backtick_subcommands(command)]:
        if _is_dangerous_command(payload, depth + 1):
            return True
    tokens = _tokenize_command(command)
    return any(_segment_is_dangerous(segment, depth) for segment in _iter_command_segments(tokens))


def is_dangerous_command(command: str) -> bool:
    return _is_dangerous_command(str(command or ""))


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


def _secret_content_flags(path: Path, max_content_bytes: int) -> list[str]:
    try:
        if path.stat().st_size > max_content_bytes:
            return []
        data = path.read_bytes()
    except OSError:
        return []
    if not data or _is_probably_binary(data):
        return []
    text = data.decode("utf-8", errors="ignore")
    flags: list[str] = []
    for name, pattern in SECRET_PATTERNS:
        for match in pattern.finditer(text):
            if name == "secret_assignment" and match.lastindex and match.lastindex >= 2:
                if _placeholder_value(match.group(2)):
                    continue
            flags.append(name)
            break
    return flags


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
            content_flags = _secret_content_flags(entry, max_content_bytes=max_content_bytes)
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
