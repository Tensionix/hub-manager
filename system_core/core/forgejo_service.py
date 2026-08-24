"""Sign-in and repository operations for Forgejo / Gitea instances.

This ties three pieces together:

- `config/forgejo_hosts.json` — which servers exist (no secrets);
- `git_credentials` — where the token lives (OS credential store);
- `forgejo_api` — what the token can do (identify, list, create).

Every function returns plain data so the GUI, the CLI and Auth Doctor can
share one implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import forgejo_api, git_credentials
from .forgejo_api import ApiResult, ForgejoHost
from .git_credentials import CredentialResult, CredentialTarget
from .json_utils import load_json, save_json


HOSTS_FILE = "forgejo_hosts.json"
DEFAULT_CONFIG: dict[str, Any] = {"active_host_id": "", "policy": "personal_access_token", "hosts": []}


@dataclass
class SignInOutcome:
    ok: bool
    host_id: str
    login: str = ""
    message_key: str = ""
    detail: str = ""
    api: ApiResult | None = None
    credential: CredentialResult | None = None
    user: dict[str, Any] | None = None


def token_failure_message_key(result: ApiResult) -> str:
    """Name the actual problem: bad token, insufficient scope, or anything else."""
    if result.forbidden:
        return "forgejo_token_scope_missing"
    if result.unauthorized:
        return "forgejo_token_unauthorized"
    return "forgejo_token_rejected"


def token_failure_detail(result: ApiResult) -> str:
    """Prefer the scope names Forgejo names in a 403 body over the raw HTTP text."""
    scopes = result.missing_scopes
    if scopes:
        return ", ".join(scopes)
    return result.error


def hosts_config_path(config_dir: Path) -> Path:
    return Path(config_dir) / HOSTS_FILE


def load_hosts_payload(config_dir: Path) -> dict[str, Any]:
    try:
        payload = load_json(hosts_config_path(config_dir), default=dict(DEFAULT_CONFIG))
    except (ValueError, OSError):
        # A hand-edited file with a stray comma must not take the GUI down: the
        # Remote pane reads this on every platform switch and keystroke.
        return dict(DEFAULT_CONFIG)
    if not isinstance(payload, dict):
        return dict(DEFAULT_CONFIG)
    payload.setdefault("active_host_id", "")
    payload.setdefault("policy", "personal_access_token")
    if not isinstance(payload.get("hosts"), list):
        payload["hosts"] = []
    return payload


def load_hosts(config_dir: Path) -> list[ForgejoHost]:
    return forgejo_api.hosts_from_config(load_hosts_payload(config_dir))


def active_host(config_dir: Path, host_id: str = "") -> ForgejoHost | None:
    payload = load_hosts_payload(config_dir)
    hosts = forgejo_api.hosts_from_config(payload)
    if not hosts:
        return None
    wanted = str(host_id or payload.get("active_host_id", "")).strip()
    if wanted:
        for host in hosts:
            if host.id == wanted:
                return host
    enabled = [host for host in hosts if host.enabled]
    return enabled[0] if enabled else hosts[0]


def upsert_host(config_dir: Path, host: ForgejoHost, *, make_active: bool = True) -> dict[str, Any]:
    """Insert or update one host record and persist the file."""
    payload = load_hosts_payload(config_dir)
    items = payload["hosts"]
    record = host.to_dict()
    for index, item in enumerate(items):
        if isinstance(item, dict) and str(item.get("id", "")).strip() == host.id:
            items[index] = {**item, **record}
            break
    else:
        items.append(record)
    if make_active:
        payload["active_host_id"] = host.id
    save_json(hosts_config_path(config_dir), payload)
    return payload


def remember_login(config_dir: Path, host: ForgejoHost, login: str) -> None:
    """Cache the account name so the UI can show who is signed in."""
    if not login or host.login == login:
        return
    upsert_host(config_dir, ForgejoHost(**{**host.to_dict(), "login": login}), make_active=False)


def remember_host(config_dir: Path, host: ForgejoHost, login: str = "") -> None:
    """Persist a host after a successful sign-in, whether or not it is new.

    This cannot delegate to `remember_login`: that one returns early when the
    login already matches, which would silently drop a server the user just
    typed into the form and never write it to the config.
    """
    record = ForgejoHost(**{**host.to_dict(), "login": login or host.login})
    upsert_host(config_dir, record, make_active=True)


def credential_target(host: ForgejoHost, login: str = "") -> CredentialTarget:
    return git_credentials.target_from_url(host.base_url, username=login or host.login)


def stored_token(host: ForgejoHost, login: str = "", cwd: Path | None = None) -> tuple[str, CredentialResult]:
    """Read the token from the OS credential store. Returns ('', result) when absent."""
    result = git_credentials.fill(credential_target(host, login), cwd=cwd)
    return (result.secret if result.ok else ""), result


def sign_in(config_dir: Path, host: ForgejoHost, login: str, token: str, cwd: Path | None = None) -> SignInOutcome:
    """Verify a personal access token, then hand it to the credential helper.

    The token is verified before it is stored, so a typo never ends up saved.
    """
    login = str(login or "").strip()
    token = str(token or "").strip()
    if not token:
        return SignInOutcome(ok=False, host_id=host.id, message_key="forgejo_token_required")

    api_result = forgejo_api.current_user(host.base_url, token)
    if not api_result.ok:
        # A valid token with the wrong scopes is a different problem from a bad
        # token, and the server says which scope is missing — pass that through.
        return SignInOutcome(
            ok=False,
            host_id=host.id,
            message_key=token_failure_message_key(api_result),
            detail=token_failure_detail(api_result),
            api=api_result,
        )

    user = forgejo_api.user_summary(api_result.data)
    resolved_login = user.get("login", "") or login
    if not resolved_login:
        return SignInOutcome(ok=False, host_id=host.id, message_key="forgejo_login_unknown", api=api_result)

    credential = git_credentials.approve(credential_target(host, resolved_login), token, cwd=cwd)
    if not credential.ok:
        detail = credential.stderr or credential.notes
        return SignInOutcome(
            ok=False,
            host_id=host.id,
            login=resolved_login,
            message_key="forgejo_credential_store_failed",
            detail=detail,
            api=api_result,
            credential=credential,
            user=user,
        )

    remember_host(config_dir, host, resolved_login)
    return SignInOutcome(
        ok=True,
        host_id=host.id,
        login=resolved_login,
        message_key="forgejo_signed_in",
        api=api_result,
        credential=credential,
        user=user,
    )


def sign_out(host: ForgejoHost, login: str = "", cwd: Path | None = None) -> CredentialResult:
    """Erase the stored token. The token on the server stays valid until revoked there."""
    return git_credentials.reject(credential_target(host, login), cwd=cwd)


def resolve_token(
    host: ForgejoHost,
    login: str = "",
    cwd: Path | None = None,
    *,
    token: str = "",
) -> tuple[str, CredentialResult | None]:
    """Use a token supplied by the caller, else read the stored one.

    A token typed into the form works immediately; saving it is a separate,
    optional step that only decides whether it survives a restart.
    """
    supplied = str(token or "").strip()
    if supplied:
        return supplied, None
    return stored_token(host, login, cwd=cwd)


def whoami(
    host: ForgejoHost, login: str = "", cwd: Path | None = None, *, token: str = ""
) -> tuple[ApiResult | None, CredentialResult | None]:
    """Identify the account behind the token, without prompting."""
    resolved, credential = resolve_token(host, login, cwd=cwd, token=token)
    if not resolved:
        return None, credential
    return forgejo_api.current_user(host.base_url, resolved), credential


def list_repos(
    host: ForgejoHost, login: str = "", cwd: Path | None = None, *, token: str = ""
) -> tuple[ApiResult | None, CredentialResult | None]:
    resolved, credential = resolve_token(host, login, cwd=cwd, token=token)
    if not resolved:
        return None, credential
    return forgejo_api.list_user_repos(host.base_url, resolved), credential


def create_repo(
    host: ForgejoHost,
    name: str,
    *,
    login: str = "",
    private: bool = True,
    description: str = "",
    default_branch: str = "main",
    cwd: Path | None = None,
    token: str = "",
) -> tuple[ApiResult | None, CredentialResult | None]:
    resolved, credential = resolve_token(host, login, cwd=cwd, token=token)
    if not resolved:
        return None, credential
    result = forgejo_api.create_user_repo(
        host.base_url,
        resolved,
        name,
        private=private,
        description=description,
        default_branch=default_branch,
    )
    return result, credential


def host_report(host: ForgejoHost, cwd: Path | None = None, *, check_server: bool = True) -> dict[str, Any]:
    """Non-interactive diagnostics for one host, used by Auth Doctor.

    Never prints the token: only whether one is stored and which account it maps to.
    Set `check_server=False` to keep the report entirely offline.
    """
    report: dict[str, Any] = {
        "id": host.id,
        "title": host.title,
        "url": host.base_url,
        "hostname": host.hostname,
        "ssh_port": host.ssh_port,
        "preferred_url_type": host.preferred_url_type,
        "configured_login": host.login,
        "enabled": host.enabled,
    }

    token, credential = stored_token(host, cwd=cwd)
    report["credential"] = credential.to_dict()
    report["token_stored"] = bool(token)

    if not check_server:
        # Keep the shape stable for consumers; unknown is not the same as false.
        report.update({"server_checked": False, "server_reachable": None, "token_valid": None, "login": ""})
        return report

    version = forgejo_api.server_version(host.base_url)
    report["server_checked"] = True
    report["server_reachable"] = version.ok
    report["server_version"] = str(version.data.get("version", "")) if isinstance(version.data, dict) else ""
    report["server_error"] = version.error

    if not token:
        report["token_valid"] = False
        report["login"] = ""
        return report

    user_result = forgejo_api.current_user(host.base_url, token)
    report["token_valid"] = user_result.ok
    report["token_error"] = user_result.error
    report["token_problem"] = "" if user_result.ok else token_failure_message_key(user_result)
    report["token_missing_scopes"] = user_result.missing_scopes
    report["login"] = forgejo_api.user_summary(user_result.data).get("login", "") if user_result.ok else ""
    return report


def forgejo_doctor(config_dir: Path, cwd: Path | None = None, *, check_server: bool = True) -> dict[str, Any]:
    hosts = load_hosts(config_dir)
    payload = load_hosts_payload(config_dir)
    helpers, helper_error = git_credentials.configured_helpers(cwd=cwd)
    return {
        "policy": str(payload.get("policy", "personal_access_token")),
        "active_host_id": str(payload.get("active_host_id", "")),
        "credential_helpers": helpers,
        "credential_helper_error": helper_error,
        "hosts": [host_report(host, cwd=cwd, check_server=check_server) for host in hosts if host.enabled],
    }
