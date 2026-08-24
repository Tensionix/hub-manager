from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
import json
import os
import re
import subprocess

from .terminal_render import decode_output_bytes


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

    def status_map(self) -> dict[str, str]:
        return {item.path: item.label for item in self.files}


@dataclass(frozen=True)
class RemoteDefinition:
    name: str
    url: str
    title: str = ""
    enabled: bool = True


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
    stdout = decode_output_bytes(completed.stdout) if isinstance(completed.stdout, bytes) else str(completed.stdout or "")
    stderr = decode_output_bytes(completed.stderr) if isinstance(completed.stderr, bytes) else str(completed.stderr or "")
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


def diff(root: Path, path: str | None = None, cached: bool = False) -> CommandResult:
    args = ["diff"]
    if cached:
        args.append("--cached")
    if path:
        args.extend(["--", path])
    return git(root, *args, timeout=120)


def remotes(root: Path) -> CommandResult:
    return git(root, "remote", "-v")


def remote_names(root: Path) -> tuple[list[str], CommandResult]:
    result = git(root, "remote")
    names = [line.strip() for line in result.stdout.splitlines() if line.strip()] if result.ok else []
    return names, result


def remote_push_urls(root: Path, remote: str = "origin") -> tuple[list[str], CommandResult]:
    result = git(root, "config", "--get-all", f"remote.{remote}.pushurl")
    if result.returncode == 1 and not result.stdout.strip() and not result.stderr.strip():
        result = CommandResult(result.command, result.cwd, 0, "", "")
    urls = [line.strip() for line in result.stdout.splitlines() if line.strip()] if result.ok else []
    return urls, result


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


def enabled_remotes_from_config(config_path: Path) -> list[RemoteDefinition]:
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    items = payload.get("global_remotes", []) if isinstance(payload, dict) else []
    remotes_config: list[RemoteDefinition] = []
    for item in items:
        if not isinstance(item, dict) or not item.get("enabled", False):
            continue
        name = str(item.get("name", "")).strip()
        url = str(item.get("url", "")).strip()
        if not name or not url:
            continue
        if not re.match(r"^[A-Za-z0-9._-]+$", name):
            raise ValueError(f"Unsafe remote name: {name}")
        validate_remote_url(url)
        remotes_config.append(
            RemoteDefinition(
                name=name,
                url=url,
                title=str(item.get("title", "")).strip(),
                enabled=True,
            )
        )
    return remotes_config


def apply_remotes_from_config(root: Path, config_path: Path) -> list[CommandResult]:
    configured = enabled_remotes_from_config(config_path)
    names, names_result = remote_names(root)
    results = [names_result]
    if not names_result.ok:
        return results
    existing = set(names)
    for remote in configured:
        if remote.name in existing:
            result = git(root, "remote", "set-url", remote.name, remote.url)
        else:
            result = git(root, "remote", "add", remote.name, remote.url)
            if result.ok:
                existing.add(remote.name)
        results.append(result)
        if not result.ok:
            break
    return results


def configure_origin_push_urls_from_config(root: Path, config_path: Path, remote: str = "origin") -> list[CommandResult]:
    configured = enabled_remotes_from_config(config_path)
    if not configured:
        return [CommandResult(["git", "remote", "configure-origin-push-urls"], str(root), 1, "", "No enabled remotes in config.")]

    names, names_result = remote_names(root)
    results = [names_result]
    if not names_result.ok:
        return results

    if remote not in set(names):
        add_result = git(root, "remote", "add", remote, configured[0].url)
        results.append(add_result)
        if not add_result.ok:
            return results

    existing_urls, push_urls_result = remote_push_urls(root, remote)
    results.append(push_urls_result)
    if not push_urls_result.ok:
        return results

    existing = set(existing_urls)
    for item in configured:
        if item.url in existing:
            continue
        result = git(root, "remote", "set-url", "--add", "--push", remote, item.url)
        results.append(result)
        if not result.ok:
            break
        existing.add(item.url)
    return results


def clone(parent_dir: Path, url: str, directory: str = "") -> CommandResult:
    """Clone into `parent_dir`.

    Runs git as an argument list, never through a shell, and passes `--` so a
    URL can never be read as an option.
    """
    validate_remote_url(url)
    parent_dir.mkdir(parents=True, exist_ok=True)
    args = ["clone", "--", url]
    if directory:
        args.append(directory)
    # Without a usable credential Git would sit waiting for a password that the
    # GUI has no way to show, so fail fast instead of hanging the application.
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    return run_command(["git", *args], cwd=parent_dir, timeout=None, env=env)


def directory_name_from_url(url: str) -> str:
    """The folder name `git clone` would pick for this URL."""
    text = str(url or "").strip().rstrip("/")
    if not text:
        return ""
    tail = re.split(r"[/:]", text)[-1]
    if tail.endswith(".git"):
        tail = tail[:-4]
    return tail.strip()


def fetch_all(root: Path) -> CommandResult:
    return git(root, "fetch", "--all", "--prune", timeout=None)


def pull_ff_only(root: Path, remote: str = "origin", branch: str = "main") -> CommandResult:
    return git(root, "pull", "--ff-only", remote, branch, timeout=None)


def stage(root: Path, paths: Iterable[str]) -> CommandResult:
    path_list = [item for item in paths if item]
    return git(root, "add", "--", *path_list)


def unstage(root: Path, paths: Iterable[str]) -> CommandResult:
    path_list = [item for item in paths if item]
    return git(root, "restore", "--staged", "--", *path_list)


def commit(root: Path, message: str) -> CommandResult:
    return git(root, "commit", "-m", message, timeout=None)


def commit_paths(root: Path, message: str, paths: Iterable[str]) -> CommandResult:
    path_list = [item for item in paths if item]
    return git(root, "commit", "--only", "-m", message, "--", *path_list, timeout=None)


def create_annotated_tag(root: Path, tag: str, message: str) -> CommandResult:
    return git(root, "tag", "-a", tag, "-m", message, timeout=None)


def push(root: Path, remote: str = "origin", branch: str = "main", *, follow_tags: bool = True) -> CommandResult:
    args = ["push"]
    if follow_tags:
        args.append("--follow-tags")
    args.extend([remote, branch])
    return git(root, *args, timeout=None)


def push_all_remotes(root: Path, branch: str = "main", *, follow_tags: bool = True) -> list[CommandResult]:
    names, names_result = remote_names(root)
    results = [names_result]
    if not names_result.ok:
        return results
    for remote in names:
        result = push(root, remote, branch, follow_tags=follow_tags)
        results.append(result)
        if not result.ok:
            break
    return results


def create_bundle(root: Path, output_path: Path, branch: str = "main") -> CommandResult:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return git(root, "bundle", "create", str(output_path), branch, "--tags", timeout=None)
