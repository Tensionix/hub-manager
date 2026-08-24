from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from shutil import which
from typing import Any, Mapping
import json
import os
import subprocess
from urllib.parse import urlparse


@dataclass
class ProbeResult:
    name: str
    command: list[str]
    returncode: int | None
    stdout: str = ""
    stderr: str = ""
    ok: bool = False
    skipped: bool = False
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_probe(name: str, command: list[str], cwd: Path | None = None, timeout: int = 15) -> ProbeResult:
    env = os.environ.copy()
    # Background probes must not freeze the GUI waiting for username/password.
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        return ProbeResult(
            name=name,
            command=command,
            returncode=completed.returncode,
            stdout=completed.stdout.strip(),
            stderr=completed.stderr.strip(),
            ok=completed.returncode == 0,
        )
    except FileNotFoundError:
        return ProbeResult(name=name, command=command, returncode=None, skipped=True, notes="executable not found")
    except subprocess.TimeoutExpired as exc:
        return ProbeResult(
            name=name,
            command=command,
            returncode=None,
            stdout=(exc.stdout or "").strip() if isinstance(exc.stdout, str) else "",
            stderr=(exc.stderr or "").strip() if isinstance(exc.stderr, str) else "",
            ok=False,
            notes="timeout",
        )


def ssh_probe(host: str, port: int = 22, user: str = "git") -> ProbeResult:
    # GitHub/GitLab/Forgejo may return non-zero on successful auth because shell access is not provided.
    # The UI should show raw output and let later logic classify provider-specific success strings.
    name = f"ssh:{host}" if port == 22 else f"ssh:{host}:{port}"
    command = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8"]
    if port and port != 22:
        command.extend(["-p", str(port)])
    command.extend(["-T", f"{user or 'git'}@{host}"])
    result = run_probe(name=name, command=command, timeout=12)
    output = f"{result.stdout}\n{result.stderr}".lower()
    # Forgejo and Gitea answer "Hi there, NAME! You've successfully authenticated,
    # but Forgejo does not provide shell access." — same shape as GitHub.
    if "successfully authenticated" in output or "welcome to gitlab" in output:
        result.ok = True
    return result


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def remote_url_type(url: str) -> str:
    text = str(url or "").strip()
    lower = text.lower()
    if not text:
        return "missing"
    if lower.startswith("git@") or "@" in text.split(":", 1)[0]:
        return "ssh"
    if lower.startswith("ssh://"):
        return "ssh"
    if lower.startswith("https://") or lower.startswith("http://"):
        return "https"
    if lower.startswith("file://"):
        return "file"
    if "://" not in lower and (text.startswith("/") or ":" in text[:3]):
        return "local"
    return "unknown"


def remote_host(url: str) -> str:
    text = str(url or "").strip().lower()
    parsed = urlparse(text)
    host = parsed.hostname or ""
    if not host and "@" in text and ":" in text:
        host = text.split("@", 1)[1].split(":", 1)[0]
    return host


def remote_provider(url: str, known_hosts: Mapping[str, str] | None = None) -> str:
    """Classify a remote URL.

    `known_hosts` maps a hostname to a provider label so self-hosted instances
    (Forgejo, Gitea, self-managed GitLab) are recognised instead of falling
    back to a bare hostname.
    """
    text = str(url or "").strip().lower()
    host = remote_host(text)
    if known_hosts and host:
        label = known_hosts.get(host)
        if label:
            return label
    if "github.com" in host:
        return "github"
    if "gitlab.com" in host:
        return "gitlab"
    if "codeberg.org" in host:
        return "codeberg"
    if text.startswith("file://") or remote_url_type(text) == "local":
        return "local"
    return host or "unknown"


def has_embedded_credentials(url: str) -> bool:
    parsed = urlparse(str(url or ""))
    return bool(parsed.username or parsed.password)


def parse_git_remote_v(text: str, known_hosts: Mapping[str, str] | None = None) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        usage = parts[2].strip("()") if len(parts) >= 3 else ""
        items.append(
            {
                "name": parts[0],
                "url": parts[1],
                "usage": usage,
                "url_type": remote_url_type(parts[1]),
                "provider": remote_provider(parts[1], known_hosts),
            }
        )
    return items


def repo_remote_probe(repo_root: Path, known_hosts: Mapping[str, str] | None = None) -> tuple[list[dict[str, str]], ProbeResult]:
    result = run_probe("git remote -v", ["git", "remote", "-v"], cwd=repo_root, timeout=10)
    return parse_git_remote_v(result.stdout, known_hosts), result


def mirror_probe(name: str, url: str) -> ProbeResult:
    return run_probe(f"git ls-remote:{name}", ["git", "ls-remote", "--heads", url], timeout=15)


def run_auth_doctor(root: Path, repo_root: Path | None = None, check_mirrors: bool = True) -> dict[str, Any]:
    config_dir = root / "config"
    auth_profiles = load_json(config_dir / "auth_profiles.json")
    remotes = load_json(config_dir / "remotes.json")

    from .forgejo_service import forgejo_doctor, load_hosts

    forgejo_hosts = [host for host in load_hosts(config_dir) if host.enabled]
    known_hosts = {host.hostname: "forgejo" for host in forgejo_hosts if host.hostname}

    probes: list[ProbeResult] = []
    probes.append(run_probe("git --version", ["git", "--version"]))
    probes.append(run_probe("git config user.name", ["git", "config", "--global", "user.name"]))
    probes.append(run_probe("git config user.email", ["git", "config", "--global", "user.email"]))

    if which("gh"):
        probes.append(run_probe("gh auth status", ["gh", "auth", "status"]))
    else:
        probes.append(ProbeResult("gh auth status", ["gh", "auth", "status"], None, skipped=True, notes="gh not installed"))

    if which("glab"):
        probes.append(run_probe("glab auth status", ["glab", "auth", "status"]))
    else:
        probes.append(ProbeResult("glab auth status", ["glab", "auth", "status"], None, skipped=True, notes="glab not installed"))

    active_profile = auth_profiles.get("active_profile", "")
    profile = next((p for p in auth_profiles.get("profiles", []) if p.get("id") == active_profile), {})
    probed_ssh: set[tuple[str, int]] = set()
    for host in profile.get("ssh_hosts", ["github.com", "gitlab.com"]):
        hostname = str(host).strip()
        if not hostname or (hostname, 22) in probed_ssh:
            continue
        probed_ssh.add((hostname, 22))
        probes.append(ssh_probe(hostname))
    # Self-hosted Forgejo instances carry their own SSH port and login user.
    for forgejo_host in forgejo_hosts:
        key = (forgejo_host.hostname, forgejo_host.ssh_port)
        if not forgejo_host.hostname or key in probed_ssh:
            continue
        probed_ssh.add(key)
        probes.append(ssh_probe(forgejo_host.hostname, forgejo_host.ssh_port, forgejo_host.ssh_user))

    repo_remotes: list[dict[str, str]] = []
    if repo_root is not None:
        repo_remotes, repo_probe = repo_remote_probe(repo_root, known_hosts)
        probes.append(repo_probe)

    remote_entries = [item for item in remotes.get("global_remotes", []) if isinstance(item, dict)]
    remote_summary = []
    for item in remote_entries:
        url = str(item.get("url", "")).strip()
        enabled = bool(item.get("enabled", False))
        summary = {
            "name": item.get("name"),
            "title": item.get("title"),
            "enabled": enabled,
            "url": url,
            "url_type": remote_url_type(url),
            "provider": remote_provider(url, known_hosts),
            "has_embedded_credentials": has_embedded_credentials(url),
            "configured_in_repo": any(remote.get("url") == url for remote in repo_remotes),
        }
        remote_summary.append(summary)
        if check_mirrors and enabled and url and not summary["has_embedded_credentials"]:
            probes.append(mirror_probe(str(item.get("name", url)), url))

    return {
        "ok": True,
        "policy": "external_credentials_only",
        "active_auth_profile": active_profile,
        "repo_root": str(repo_root) if repo_root else "",
        "repo_remotes": repo_remotes,
        "remotes": remote_summary,
        "forgejo": forgejo_doctor(config_dir, cwd=repo_root, check_server=check_mirrors),
        "probes": [p.to_dict() for p in probes],
        "warnings": [
            "Do not store GitHub/GitLab/Forgejo tokens in config/*.json.",
            "Use SSH agent, Git Credential Manager, GitHub CLI, GitLab CLI, VS Code, or GitKraken for login setup.",
            "Forgejo access tokens are handed to the Git credential helper, never written into this project.",
            "Background checks use non-interactive probes and may fail if a passphrase prompt is required.",
        ],
    }
