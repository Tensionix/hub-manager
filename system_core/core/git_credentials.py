"""Standard Git credential storage access.

Audion Hub Manager never stores tokens itself. It talks to the credential
helper the user already has configured (Git Credential Manager, wincred,
libsecret, osxkeychain) through the documented `git credential` protocol.

That keeps three promises at once:

- the secret lands in the OS credential store, not in `config/*.json`;
- plain `git push` / `git pull` picks the same credential up without any
  help from this application;
- removing the credential is a normal, reversible operation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse
import os
import subprocess

from .terminal_render import decode_output_bytes


DEFAULT_PORTS = {"https": 443, "http": 80}


@dataclass
class CredentialTarget:
    protocol: str
    host: str
    username: str = ""

    @property
    def display(self) -> str:
        return f"{self.protocol}://{self.host}"

    def to_fields(self, *, with_username: bool = True) -> dict[str, str]:
        fields = {"protocol": self.protocol, "host": self.host}
        if with_username and self.username:
            fields["username"] = self.username
        return fields


@dataclass
class CredentialResult:
    action: str
    target: CredentialTarget
    returncode: int | None
    fields: dict[str, str] = field(default_factory=dict)
    stderr: str = ""
    notes: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def username(self) -> str:
        return self.fields.get("username", "")

    @property
    def secret(self) -> str:
        return self.fields.get("password", "")

    @property
    def has_secret(self) -> bool:
        return bool(self.secret)

    def joined_command(self) -> str:
        """Loggable command text. The secret is passed on stdin and never shown."""
        return f"git credential {self.action}  [{self.target.display}]"

    def to_dict(self) -> dict[str, object]:
        """Redacted view suitable for Auth Doctor output and logs."""
        return {
            "action": self.action,
            "target": self.target.display,
            "username": self.username,
            "has_secret": self.has_secret,
            "returncode": self.returncode,
            "stderr": self.stderr,
            "notes": self.notes,
        }


def target_from_url(url: str, username: str = "") -> CredentialTarget:
    """Build a credential target from a server URL.

    A non-default port stays part of the host, exactly as Git records it.
    """
    text = str(url or "").strip()
    if not text:
        raise ValueError("Server URL is required.")
    if "://" not in text:
        text = f"https://{text}"
    parsed = urlparse(text)
    protocol = (parsed.scheme or "https").lower()
    if protocol not in ("https", "http"):
        raise ValueError(f"Unsupported credential protocol: {protocol}")
    hostname = (parsed.hostname or "").strip()
    if not hostname:
        raise ValueError(f"Server URL has no host: {url}")
    host = hostname
    if parsed.port and parsed.port != DEFAULT_PORTS.get(protocol):
        host = f"{hostname}:{parsed.port}"
    return CredentialTarget(protocol=protocol, host=host, username=str(username or "").strip())


def encode_fields(fields: dict[str, str]) -> str:
    lines = [f"{key}={value}" for key, value in fields.items() if value != ""]
    return "\n".join(lines) + "\n\n"


def parse_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in str(text or "").splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        fields[key.strip()] = value
    return fields


def _run_credential(action: str, payload: str, cwd: Path | None = None, timeout: int = 30) -> tuple[int | None, str, str, str]:
    env = os.environ.copy()
    # A missing helper must fail fast instead of blocking on a console prompt.
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.setdefault("GCM_INTERACTIVE", "never")
    try:
        completed = subprocess.run(
            ["git", "credential", action],
            input=payload.encode("utf-8"),
            cwd=str(cwd) if cwd else None,
            env=env,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return None, "", "", "git executable not found"
    except subprocess.TimeoutExpired:
        return None, "", "", "timeout"
    stdout = decode_output_bytes(completed.stdout) if isinstance(completed.stdout, bytes) else str(completed.stdout or "")
    stderr = decode_output_bytes(completed.stderr) if isinstance(completed.stderr, bytes) else str(completed.stderr or "")
    return completed.returncode, stdout, stderr.strip(), ""


PROMPT_SUPPRESSED_MARKERS = (
    "terminal prompts disabled",
    "cannot prompt because user interactivity has been disabled",
    "could not read username",
    "could not read password",
)


def fill(target: CredentialTarget, cwd: Path | None = None) -> CredentialResult:
    """Ask the configured helper for a stored credential. Never prompts.

    With no stored credential the helper wants to ask the user interactively.
    Prompting is disabled on purpose, so Git exits non-zero — that is a plain
    "nothing stored", not a failure worth alarming anyone about.
    """
    returncode, stdout, stderr, notes = _run_credential("fill", encode_fields(target.to_fields()), cwd=cwd)
    fields = parse_fields(stdout)
    result = CredentialResult(action="fill", target=target, returncode=returncode, fields=fields, stderr=stderr, notes=notes)
    if not result.has_secret:
        lowered = stderr.lower()
        if any(marker in lowered for marker in PROMPT_SUPPRESSED_MARKERS):
            result.returncode = 0
            result.stderr = ""
            result.notes = "no stored credential"
        elif result.ok:
            result.notes = result.notes or "no stored credential"
    return result


def approve(target: CredentialTarget, secret: str, cwd: Path | None = None) -> CredentialResult:
    """Store a credential through the configured helper."""
    token = str(secret or "").strip()
    if not token:
        return CredentialResult(action="approve", target=target, returncode=None, notes="empty secret")
    if not target.username:
        return CredentialResult(action="approve", target=target, returncode=None, notes="username is required")
    payload_fields = target.to_fields()
    payload_fields["password"] = token
    returncode, _stdout, stderr, notes = _run_credential("approve", encode_fields(payload_fields), cwd=cwd)
    return CredentialResult(action="approve", target=target, returncode=returncode, stderr=stderr, notes=notes)


def reject(target: CredentialTarget, cwd: Path | None = None) -> CredentialResult:
    """Erase a stored credential through the configured helper."""
    returncode, _stdout, stderr, notes = _run_credential("reject", encode_fields(target.to_fields()), cwd=cwd)
    return CredentialResult(action="reject", target=target, returncode=returncode, stderr=stderr, notes=notes)


def configured_helpers(cwd: Path | None = None) -> tuple[list[str], str]:
    """Return configured credential helpers and the raw stderr of the probe."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        completed = subprocess.run(
            ["git", "config", "--get-all", "credential.helper"],
            cwd=str(cwd) if cwd else None,
            env=env,
            capture_output=True,
            timeout=15,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return [], "git config probe failed"
    stdout = decode_output_bytes(completed.stdout) if isinstance(completed.stdout, bytes) else str(completed.stdout or "")
    stderr = decode_output_bytes(completed.stderr) if isinstance(completed.stderr, bytes) else str(completed.stderr or "")
    helpers = [line.strip() for line in stdout.splitlines() if line.strip()]
    return helpers, stderr.strip()
