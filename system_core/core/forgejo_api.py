"""Minimal Forgejo / Gitea API v1 client.

The contract is the ordinary one every Forgejo client uses: a personal
access token created by the user in `Settings -> Applications`, sent as
`Authorization: token <TOKEN>` over HTTPS.

Scope of this module: identify the server, identify the user, list and create
repositories. Fetch and push stay with `git` itself, authenticated by SSH keys
or by the same token read from the OS credential store.

Tokens are passed in as arguments and never written to disk here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse
import re


DEFAULT_TIMEOUT = 20.0
REPO_PAGE_LIMIT = 50
MAX_REPO_PAGES = 20

# Verified against a live Forgejo 15.0.6 instance, not taken from the docs.
# Scopes follow the ROUTE, not the object being acted on: everything under
# /api/v1/user/* is gated by the user scopes, including repository creation.
# Git transport over HTTPS is judged separately and needs a repository scope,
# so API access and git access require different scopes on the same token.
SCOPE_IDENTITY = "read:user"
SCOPE_CREATE_REPOSITORY = "write:user"
SCOPE_READ_REPOSITORY = "read:repository"
SCOPE_WRITE_REPOSITORY = "write:repository"

# What each capability actually needs, keyed by what the user is trying to do.
SCOPES_BY_CAPABILITY = {
    "server_version": (),
    "identity": (SCOPE_IDENTITY,),
    "list_repositories": (SCOPE_IDENTITY,),
    "create_repository": (SCOPE_CREATE_REPOSITORY,),
    "git_over_https": (SCOPE_READ_REPOSITORY,),
    "git_push_over_https": (SCOPE_WRITE_REPOSITORY,),
}
MINIMUM_SCOPES = (SCOPE_IDENTITY, SCOPE_READ_REPOSITORY)

# `urlparse` keeps whatever sits in the authority, including `;`, `&` and `$(...)`.
# These values reach `ssh -T <user>@<host>`, which the GUI runs through a shell,
# and a hostile `forgejo_hosts.json` could arrive with a cloned project — so the
# shape is enforced here, at the one place every path goes through.
HOSTNAME_RE = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$")
IPV6_RE = re.compile(r"^[0-9A-Fa-f:.]{2,45}$")
SSH_USER_RE = re.compile(r"^[A-Za-z0-9._-]{1,32}$")


def valid_hostname(hostname: str) -> bool:
    text = str(hostname or "").strip()
    if not text:
        return False
    return bool(HOSTNAME_RE.match(text) or IPV6_RE.match(text))


def valid_ssh_user(user: str) -> bool:
    return bool(SSH_USER_RE.match(str(user or "").strip()))


@dataclass(frozen=True)
class ForgejoHost:
    """A configured Forgejo/Gitea server. Holds no secrets."""

    id: str
    title: str
    url: str
    ssh_port: int = 22
    ssh_user: str = "git"
    preferred_url_type: str = "ssh"
    login: str = ""
    enabled: bool = True

    def __post_init__(self) -> None:
        # Validate on construction so no caller can hand a hostile host onward.
        normalize_base_url(self.url)
        if not valid_ssh_user(self.ssh_user):
            raise ValueError(f"Unsafe SSH user: {self.ssh_user}")
        if not 1 <= int(self.ssh_port) <= 65535:
            raise ValueError(f"SSH port out of range: {self.ssh_port}")

    @property
    def base_url(self) -> str:
        return normalize_base_url(self.url)

    @property
    def hostname(self) -> str:
        return urlparse(self.base_url).hostname or ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "url": self.url,
            "ssh_port": self.ssh_port,
            "ssh_user": self.ssh_user,
            "preferred_url_type": self.preferred_url_type,
            "login": self.login,
            "enabled": self.enabled,
        }


@dataclass
class ApiResult:
    """Uniform outcome of one API call. `data` is only set when ok."""

    method: str
    url: str
    status: int | None = None
    data: Any = None
    error: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    truncated: bool = False

    @property
    def ok(self) -> bool:
        return self.status is not None and 200 <= self.status < 300 and not self.error

    @property
    def unauthorized(self) -> bool:
        """The token is missing, wrong or revoked."""
        return self.status == 401

    @property
    def forbidden(self) -> bool:
        """The token is valid but was issued without the scope this route needs."""
        return self.status == 403

    @property
    def missing_scopes(self) -> list[str]:
        return parse_missing_scopes(self.error)

    def joined_command(self) -> str:
        return f"{self.method} {self.url}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "url": self.url,
            "status": self.status,
            "error": self.error,
            "missing_scopes": self.missing_scopes,
        }


def normalize_base_url(url: str) -> str:
    """Accept `git.example.org`, `https://git.example.org/`, `https://host/path/`."""
    text = str(url or "").strip()
    if not text:
        raise ValueError("Forgejo server URL is required.")
    if "://" not in text:
        text = f"https://{text}"
    parsed = urlparse(text)
    if parsed.scheme not in ("https", "http"):
        raise ValueError(f"Unsupported Forgejo URL scheme: {parsed.scheme}")
    if not parsed.hostname:
        raise ValueError(f"Forgejo URL has no host: {url}")
    if not valid_hostname(parsed.hostname):
        raise ValueError(f"Unsafe host in Forgejo URL: {parsed.hostname}")
    if parsed.username or parsed.password:
        raise ValueError("Forgejo URL must not embed credentials.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"Invalid port in Forgejo URL: {url}") from exc
    if port is not None and not 1 <= port <= 65535:
        raise ValueError(f"Port out of range in Forgejo URL: {port}")
    path = parsed.path.rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def host_from_dict(payload: dict[str, Any]) -> ForgejoHost:
    ssh_port = payload.get("ssh_port", 22)
    try:
        ssh_port = int(ssh_port)
    except (TypeError, ValueError):
        ssh_port = 22
    url = str(payload.get("url", "")).strip()
    host_id = str(payload.get("id", "")).strip()
    if not host_id and url:
        host_id = urlparse(normalize_base_url(url)).hostname or "forgejo"
    return ForgejoHost(
        id=host_id,
        title=str(payload.get("title", "")).strip(),
        url=url,
        ssh_port=ssh_port,
        ssh_user=str(payload.get("ssh_user", "git")).strip() or "git",
        preferred_url_type=str(payload.get("preferred_url_type", "ssh")).strip().lower() or "ssh",
        login=str(payload.get("login", "")).strip(),
        enabled=bool(payload.get("enabled", True)),
    )


def hosts_from_config(payload: dict[str, Any]) -> list[ForgejoHost]:
    items = payload.get("hosts", []) if isinstance(payload, dict) else []
    hosts: list[ForgejoHost] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if not str(item.get("url", "")).strip():
            continue
        try:
            hosts.append(host_from_dict(item))
        except ValueError:
            continue
    return hosts


def build_ssh_remote_url(host: ForgejoHost, owner: str, repo: str) -> str:
    """SCP-like form on port 22, explicit ssh:// URL otherwise."""
    owner = str(owner or "").strip().strip("/")
    repo = str(repo or "").strip().strip("/")
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not owner or not repo:
        return ""
    hostname = host.hostname
    if not hostname:
        return ""
    user = host.ssh_user or "git"
    if host.ssh_port and host.ssh_port != 22:
        return f"ssh://{user}@{hostname}:{host.ssh_port}/{owner}/{repo}.git"
    return f"{user}@{hostname}:{owner}/{repo}.git"


def build_https_remote_url(host: ForgejoHost, owner: str, repo: str) -> str:
    """Clean HTTPS URL. Credentials are never embedded."""
    owner = str(owner or "").strip().strip("/")
    repo = str(repo or "").strip().strip("/")
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not owner or not repo:
        return ""
    return f"{host.base_url}/{owner}/{repo}.git"


def build_remote_url(host: ForgejoHost, owner: str, repo: str, url_type: str = "") -> str:
    kind = (url_type or host.preferred_url_type or "ssh").strip().lower()
    if kind == "https":
        return build_https_remote_url(host, owner, repo)
    return build_ssh_remote_url(host, owner, repo)


def _request(
    method: str,
    base_url: str,
    path: str,
    token: str = "",
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> ApiResult:
    url = f"{normalize_base_url(base_url)}{path}"
    headers = {"Accept": "application/json", "User-Agent": "Audion-Hub-Manager"}
    if token:
        headers["Authorization"] = f"token {str(token).strip()}"
    if json_body is not None:
        headers["Content-Type"] = "application/json"
    try:
        import httpx
    except Exception as exc:  # pragma: no cover - depends on the portable runtime
        return ApiResult(method=method, url=url, error=f"httpx is not available: {exc}")

    try:
        response = httpx.request(
            method,
            url,
            headers=headers,
            params=params,
            json=json_body,
            timeout=timeout,
            follow_redirects=True,
        )
    except Exception as exc:
        return ApiResult(method=method, url=url, error=f"{exc.__class__.__name__}: {exc}")

    result = ApiResult(method=method, url=url, status=response.status_code, headers=dict(response.headers))
    if response.status_code >= 400:
        result.error = redact_token(_error_text(response), token)
        return result
    if not response.content:
        result.data = None
        return result
    try:
        result.data = response.json()
    except Exception:
        result.error = "response is not valid JSON"
    return result


TOKEN_ECHO_RE = re.compile(r"\[sha:\s*[^\]]*\]", re.IGNORECASE)
REDACTED = "***"


def redact_token(text: str, token: str = "") -> str:
    """Strip any echo of the token out of server text before it reaches a log.

    Forgejo answers a bad token with `access token does not exist [sha: <TOKEN>]`,
    quoting the value back. That text flows into the terminal dock and `logs/`,
    so a revoked-but-real token would otherwise be written to disk in the clear.
    """
    cleaned = TOKEN_ECHO_RE.sub(f"[sha: {REDACTED}]", str(text or ""))
    secret = str(token or "").strip()
    if secret and len(secret) >= 8:
        cleaned = cleaned.replace(secret, REDACTED)
    return cleaned


def parse_missing_scopes(error: str) -> list[str]:
    """Pull the scope names out of a Forgejo 403 body.

    Forgejo answers a scope mismatch with, verbatim:
    `token does not have at least one of required scope(s): [read:user]`
    """
    text = str(error or "")
    if "scope" not in text.lower():
        return []
    match = re.search(r"\[([^\]]*)\]", text)
    if not match:
        return []
    scopes = [item.strip().strip("'\"") for item in match.group(1).split(",")]
    return [scope for scope in scopes if scope]


def _error_text(response: Any) -> str:
    reason = f"HTTP {response.status_code}"
    try:
        payload = response.json()
    except Exception:
        text = (response.text or "").strip()
        return f"{reason}: {text[:300]}" if text else reason
    if isinstance(payload, dict):
        message = str(payload.get("message") or payload.get("errors") or "").strip()
        if message:
            return f"{reason}: {message}"
    return reason


def server_version(base_url: str, timeout: float = DEFAULT_TIMEOUT) -> ApiResult:
    """Identify the server. Works without a token on public instances."""
    return _request("GET", base_url, "/api/v1/version", timeout=timeout)


def current_user(base_url: str, token: str, timeout: float = DEFAULT_TIMEOUT) -> ApiResult:
    """Verify the token and return the account it belongs to."""
    return _request("GET", base_url, "/api/v1/user", token=token, timeout=timeout)


def list_user_repos(base_url: str, token: str, timeout: float = DEFAULT_TIMEOUT) -> ApiResult:
    """All repositories the token can see, following pagination."""
    collected: list[dict[str, Any]] = []
    last: ApiResult | None = None
    complete = False
    for page in range(1, MAX_REPO_PAGES + 1):
        last = _request(
            "GET",
            base_url,
            "/api/v1/user/repos",
            token=token,
            params={"page": page, "limit": REPO_PAGE_LIMIT},
            timeout=timeout,
        )
        if not last.ok:
            return last
        batch = last.data if isinstance(last.data, list) else []
        collected.extend(item for item in batch if isinstance(item, dict))
        if len(batch) < REPO_PAGE_LIMIT:
            complete = True
            break
    result = last or ApiResult(method="GET", url=f"{normalize_base_url(base_url)}/api/v1/user/repos")
    result.data = collected
    # Hitting the page ceiling means the list is cut short. Say so rather than
    # presenting a partial list as if it were everything.
    result.truncated = not complete
    return result


def create_user_repo(
    base_url: str,
    token: str,
    name: str,
    *,
    private: bool = True,
    description: str = "",
    default_branch: str = "main",
    auto_init: bool = False,
    timeout: float = DEFAULT_TIMEOUT,
) -> ApiResult:
    """Create a repository owned by the token's own account."""
    repo_name = str(name or "").strip().strip("/")
    if repo_name.endswith(".git"):
        repo_name = repo_name[:-4]
    if not repo_name:
        return ApiResult(method="POST", url=f"{normalize_base_url(base_url)}/api/v1/user/repos", error="Repository name is required.")
    body: dict[str, Any] = {
        "name": repo_name,
        "private": bool(private),
        "auto_init": bool(auto_init),
        "default_branch": str(default_branch or "main").strip() or "main",
    }
    if description:
        body["description"] = str(description).strip()
    return _request("POST", base_url, "/api/v1/user/repos", token=token, json_body=body, timeout=timeout)


def repo_summary(item: dict[str, Any]) -> dict[str, Any]:
    """Flatten one API repository record into the fields the UI needs."""
    owner = item.get("owner") if isinstance(item.get("owner"), dict) else {}
    return {
        "full_name": str(item.get("full_name", "")).strip(),
        "name": str(item.get("name", "")).strip(),
        "owner": str(owner.get("login", "")).strip(),
        "private": bool(item.get("private", False)),
        "ssh_url": str(item.get("ssh_url", "")).strip(),
        "clone_url": str(item.get("clone_url", "")).strip(),
        "default_branch": str(item.get("default_branch", "")).strip(),
        "empty": bool(item.get("empty", False)),
        "updated_at": str(item.get("updated_at", "")).strip(),
    }


def user_summary(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    return {
        "login": str(payload.get("login", "")).strip(),
        "full_name": str(payload.get("full_name", "")).strip(),
        "email": str(payload.get("email", "")).strip(),
        "is_admin": bool(payload.get("is_admin", False)),
        "id": payload.get("id"),
    }
