from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess

from .output_decode import decode_process_bytes


@dataclass
class CommandResult:
    command: list[str]
    cwd: str
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def joined_command(self) -> str:
        return " ".join(self.command)


@dataclass
class GitFileStatus:
    path: str
    index: str
    worktree: str
    raw: str

    @property
    def label(self) -> str:
        if self.raw.startswith("??"):
            return "untracked"
        if "U" in self.raw or self.index == "U" or self.worktree == "U":
            return "conflict"
        if self.index.strip() and self.index != " ":
            return "staged"
        if self.worktree.strip() and self.worktree != " ":
            return "modified"
        return "changed"


@dataclass
class GitStatus:
    root: Path
    branch: str = ""
    ahead: int = 0
    behind: int = 0
    files: list[GitFileStatus] = None  # type: ignore[assignment]
    raw: str = ""

    def __post_init__(self) -> None:
        if self.files is None:
            self.files = []


def run_command(
    args: list[str],
    cwd: Path | str | None = None,
    timeout: int | None = 120,
    env: dict[str, str] | None = None,
) -> CommandResult:
    cwd_path = Path(cwd).resolve() if cwd else Path.cwd()
    completed = subprocess.run(
        args,
        cwd=str(cwd_path),
        capture_output=True,
        timeout=timeout,
        check=False,
        env=env,
    )
    stdout = decode_process_bytes(completed.stdout) if isinstance(completed.stdout, bytes) else str(completed.stdout or "")
    stderr = decode_process_bytes(completed.stderr) if isinstance(completed.stderr, bytes) else str(completed.stderr or "")
    return CommandResult(args, str(cwd_path), completed.returncode, stdout, stderr)


def git(root: Path, *args: str, timeout: int | None = 120) -> CommandResult:
    return run_command(["git", *args], cwd=root, timeout=timeout)


SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?$")


def parse_semver(value: str) -> tuple[int, int, int] | None:
    match = SEMVER_RE.match(str(value or "").strip())
    if not match:
        return None
    patch = int(match.group(3) or "0")
    return int(match.group(1)), int(match.group(2)), patch


def format_semver(version: tuple[int, int, int]) -> str:
    return f"v{version[0]}.{version[1]}.{version[2]}"


def bump_semver(value: str, bump: str = "patch") -> str:
    version = parse_semver(value) or (0, 0, 0)
    major, minor, patch = version
    if bump == "major":
        return format_semver((major + 1, 0, 0))
    if bump == "minor":
        return format_semver((major, minor + 1, 0))
    return format_semver((major, minor, patch + 1))


def slugify_version_series(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9._-]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-._")
    return text or "checkpoint"


def build_version_tag(series: str, version: str) -> str:
    parsed = parse_semver(version) or (0, 1, 0)
    return f"{slugify_version_series(series)}-{format_semver(parsed)}"


def next_version_for_series(root: Path, series: str, bump: str = "patch", default: str = "v0.1.0") -> tuple[str, CommandResult]:
    prefix = f"{slugify_version_series(series)}-"
    result = git(root, "tag", "--list", f"{prefix}v*")
    versions: list[tuple[int, int, int]] = []
    if result.ok:
        for line in result.stdout.splitlines():
            tag = line.strip()
            if not tag.startswith(prefix):
                continue
            parsed = parse_semver(tag[len(prefix):])
            if parsed:
                versions.append(parsed)
    if not versions:
        return format_semver(parse_semver(default) or (0, 1, 0)), result
    return bump_semver(format_semver(max(versions)), bump), result


def parse_status(root: Path, text: str) -> GitStatus:
    status = GitStatus(root=root, raw=text)
    for line in text.splitlines():
        if line.startswith("##"):
            head = line[2:].strip()
            branch = head.split("...", 1)[0].strip()
            status.branch = branch
            if "ahead" in head:
                try:
                    status.ahead = int(head.split("ahead", 1)[1].split("]", 1)[0].split(",", 1)[0].strip())
                except Exception:
                    pass
            if "behind" in head:
                try:
                    status.behind = int(head.split("behind", 1)[1].split("]", 1)[0].split(",", 1)[0].strip())
                except Exception:
                    pass
            continue
        if not line:
            continue
        raw = line[:2]
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        status.files.append(GitFileStatus(path=path, index=raw[0], worktree=raw[1], raw=raw))
    return status


def status(root: Path) -> tuple[GitStatus, CommandResult]:
    result = git(root, "status", "--porcelain=v1", "-b")
    return parse_status(root, result.stdout), result


# `ext::` and `fd::` let a remote URL name a command for Git to run, and a URL
# starting with `-` can be read as an option by the Git command it is passed to.
# Remote URLs can arrive from a config file shipped with someone else's project.
UNSAFE_URL_TRANSPORTS = ("ext::", "fd::")


def validate_remote_url(url: str) -> str:
    text = str(url or "").strip()
    if not text:
        raise ValueError("Remote URL is empty.")
    lowered = text.lower()
    for transport in UNSAFE_URL_TRANSPORTS:
        if lowered.startswith(transport):
            raise ValueError(f"Remote URL uses a command-executing transport: {transport}")
    if text.startswith("-"):
        raise ValueError("Remote URL must not start with '-': Git would read it as an option.")
    if any(char in text for char in ("\n", "\r", "\0")):
        raise ValueError("Remote URL must not contain control characters.")
    return text


