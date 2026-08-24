# GIT_AUTH_STRATEGY — GitHub/GitLab/Forgejo login policy

## Decision

Audion Hub Manager must **not** become a password/token vault.

The application is portable, but Git credentials are not stored inside the portable project. Authentication is delegated to the normal Git ecosystem:

- SSH keys + ssh-agent;
- Git Credential Manager for HTTPS;
- GitHub CLI (`gh auth login`) when useful;
- GitLab CLI (`glab auth login`) when useful;
- VS Code / GitKraken for manual login, conflict resolution and visual Git work.

Hub Manager executes real `git` commands and displays them in the terminal dock. If the user is already authenticated through Git, VS Code, Git Credential Manager, SSH agent, GitKraken, GitHub CLI or GitLab CLI, push/pull/fetch should work without Hub Manager knowing any secret.

Current UI policy:

- Auth Doctor is a support panel, not a credential editor.
- Git remotes, remote form, push/pull/fetch and Auth setup live in the
  `Remote` pane. The `Quick` pane keeps local/frequent repository operations.
- Push/checkpoint commands should be gated by Safety Scan and explicit user
  intent.
- Use Material icon buttons for Git actions; avoid emoji command labels.
- The Auth block inside `Remote` exposes external setup/probe buttons:
  Check Auth, paired SSH probes for GitHub/GitLab, paired `gh auth login` /
  `glab auth login`, Windows Credential Manager, VS Code and GitKraken folder.

## Remote mechanics

A Git remote is only a named URL. Typical examples:

```bash
git remote add github git@github.com:audion/Audion_Hub.git
git remote add gitlab git@gitlab.com:audion/Audion_Hub.git
git remote add local_nas file:///Z:/git-mirrors/Audion_Hub.git
```

Push/pull/fetch authenticate according to the URL type:

```text
SSH URL    -> SSH key / ssh-agent
HTTPS URL  -> Git Credential Manager / token / CLI OAuth helper
file://    -> local filesystem permissions
```

Hub Manager can build remote URLs from platform/login/repository fields and
save enabled records to `config/remotes.json`. Field history lives in
`config/remote_field_cache.json` and is applied only by an explicit use button,
never by automatic overlay into the typed field.

For ordinary publishing, push with annotated checkpoint tags:

```bash
git push --follow-tags origin main
```

`push all remotes` should enumerate Git remote names in Python and run
`git push --follow-tags <remote> <branch>` sequentially. Do not use a
PowerShell-only pipeline for GUI actions.

## Recommended default

Use SSH for GitHub/GitLab remotes:

```text
git@github.com:OWNER/REPO.git
git@gitlab.com:OWNER/REPO.git
```

Reasons:

- same pattern works across GitHub/GitLab/Codeberg/self-hosted Git;
- no PAT in JSON config;
- no password prompts in the app;
- can be tested with `ssh -T`;
- works well with multi-remote push.

For a single-button GitHub+GitLab publish path, configure `origin` with multiple
push URLs while keeping pull/fetch anchored to one canonical fetch URL. Pulling
from multiple platforms at once is not a normal sync operation; divergent
platform histories should be resolved deliberately.

## HTTPS fallback

HTTPS is acceptable, especially behind restrictive networks, but Hub Manager must still avoid storing tokens.

For GitHub, use Git Credential Manager or GitHub CLI. For GitLab, use a credential helper or a token stored outside this project.

Do not put credentials in `config/*.json` and do not embed tokens in remote URLs.

Bad:

```text
https://username:TOKEN@gitlab.com/user/repo.git
```

Good:

```text
https://gitlab.com/user/repo.git
```

A credential-bearing URL is worse than it looks, and not only because it may be
pasted into a config or a chat. Cloning with one makes Git write the token, in
the clear, into `.git/config` of the working copy — where it then survives every
backup, mirror and archive of that folder. Observed directly while testing this
feature. Going through the credential helper avoids that entirely: `.git/config`
keeps a clean URL and the secret stays in the OS store. It is the same family of
mistake as putting a secret in a URL query parameter.

Credentials belong to the OS credential store, Git Credential Manager, SSH agent, GitHub CLI, GitLab CLI, or another external credential manager.

## Hub Manager Auth Doctor

The app should provide a non-destructive **Auth Doctor** panel:

```text
Git installed?
Git config user.name/user.email?
Remotes configured?
SSH to GitHub works?
SSH to GitLab works?
SSH to each configured Forgejo host and port works?
gh installed / authenticated?
glab installed / authenticated?
git ls-remote works for selected remotes?
Which credential helpers are configured?
For each Forgejo host: server reachable, token stored, token still valid?
```

Auth Doctor should use non-interactive probes by default. For background probes use fail-fast settings so the GUI does not hang waiting for a password prompt.

Example policy:

```text
background checks: non-interactive, timeout, no credential prompts
user-triggered push/pull: visible command, clear progress, cancellable
setup/login: open external terminal or external app
```

`fetch --all --prune` is safe as a frequent remote-status command: it updates
remote tracking refs and prunes deleted remote refs without modifying working
tree files. `pull --ff-only` is the deliberate branch-advance operation.

## Forgejo and Gitea instances

Forgejo and Gitea are self-hosted, so the server address is part of the
configuration rather than a fixed constant. `config/forgejo_hosts.json` lists
the instances: id, title, URL, SSH user and port, preferred URL type and a
cached account login. It holds no secrets and is safe to publish.

The account contract is the ordinary one every Forgejo client uses:

```text
personal access token  -> Settings -> Applications -> Generate New Token
API authentication     -> Authorization: token <TOKEN>
token storage          -> the Git credential helper the user already has
git push / git pull    -> SSH key, or the same token over HTTPS
```

### Token scopes

Verified empirically against Forgejo 15.0.6, one isolated token per operation,
because the documentation does not spell this out:

| Operation | Scope |
|---|---|
| `GET /api/v1/version` | none, no token needed |
| `GET /api/v1/user` — who am I | `read:user` |
| `GET /api/v1/user/repos` — list | `read:user` |
| `POST /api/v1/user/repos` — create a repository | `write:user` |
| `git clone` / `git push` over HTTPS | a repository scope |

Two things here contradict the obvious guess:

- **Scopes follow the route, not the object.** Creating a repository lives under
  `/api/v1/user/*`, so it needs `write:user`. A token holding
  `write:repository` gets `403 ... required scope(s): [write:user]`.
- **API access and git access are judged separately.** A token with
  `read:user,write:user` still fails at `git clone` with `remote: Forbidden`,
  so covering the API says nothing about covering git.

Forgejo also collapses scopes on save: a token created with
`read:user,write:user,write:repository` is stored as `write:repository,write:user`,
because the write scope implies the read one. There is no need to list both.

Because of that, a 403 is treated separately from a 401 everywhere in the app:
a 401 means the token is wrong, expired or revoked, while a 403 means the token
is genuine but was issued without the scope the route needs. Forgejo names the
missing scope in the response body, and `parse_missing_scopes` lifts it out so
the UI can show it instead of a bare status code.

### Why a token and not "Sign in with Forgejo"

Forgejo does implement OAuth2 / OpenID Connect, and an Authorization Code +
PKCE flow would work. It was considered and deliberately not chosen:

- **Scope.** Forgejo's own documentation states that OAuth2 scopes are not yet
  implemented and that a third-party application obtaining a token this way
  gets administrative rights over the account. A manually created personal
  access token, by contrast, is issued with exactly the scopes the user picks —
  `read:repository` alone is enough to list repositories.
- **Push.** An OAuth access token is short-lived, so `git push` over HTTPS
  would need a dedicated credential helper feeding it a fresh token on every
  operation. A personal access token placed in the credential store is picked
  up by plain `git` with no help from Hub Manager at all.
- **Setup burden.** Hub Manager is published for anyone with their own Forgejo.
  A token needs no server-side preparation; an OAuth flow would require every
  user to register an OAuth2 application on their instance first.

A browser sign-in can still be added later as a second, optional path. It would
not replace the token contract, only sit next to it.

### What Hub Manager does with the token

The token is typed into the `Remote` pane, verified against `/api/v1/user`, and
only then handed to `git credential approve`. Hub Manager keeps no copy: the
field is cleared, nothing is written to `config/*.json`, and later reads go
back through `git credential fill`. `forget token` runs `git credential reject`;
revoking the token on the server stays a deliberate action by the user.

Background probes disable prompting (`GIT_TERMINAL_PROMPT=0`), so a missing
credential is reported as "nothing stored" instead of blocking the GUI.

Server error text is redacted before it is shown. Forgejo answers an unknown
token with `access token does not exist [sha: <TOKEN>]`, quoting the value back;
a revoked or expired token would otherwise appear verbatim in the terminal dock,
and from there in screenshots, copied output and bug reports. `redact_token`
strips the echoed value and any literal occurrence of the token in use. The dock
itself keeps its lines in memory only and does not write them to `logs/`.

### Untrusted config input

`config/forgejo_hosts.json` and `config/remotes.json` are ordinary project files
and can arrive with a cloned repository, so their contents are treated as
untrusted input rather than as settings the user personally typed:

```text
hostname   must match a DNS name or an IP literal — `urlparse` keeps `;`,
           `&&` and `$(...)`, and the value reaches `ssh -T <user>@<host>`,
           which runs through a shell
ssh_user   [A-Za-z0-9._-] only
ssh_port   1..65535
URLs       no embedded credentials, no `ext::` or `fd::` (both make Git run a
           command), no leading `-` (Git would read it as an option), no
           control characters
```

Records that fail validation are dropped when the config is loaded, and the
Remote pane refuses to save such a value in the first place.

### Remote URLs for self-hosted instances

```text
port 22        -> git@host:owner/repo.git
other SSH port -> ssh://git@host:PORT/owner/repo.git
HTTPS          -> https://host/owner/repo.git
```

HTTPS URLs never carry embedded credentials; the stored token supplies them.

## External tools

VS Code and GitKraken are useful, but they should not become hard dependencies.

Hub Manager should be able to:

- open a repo in VS Code;
- open a repo folder for GitKraken/manual Git work;
- open Windows Credential Manager for HTTPS/GCM cleanup;
- start `gh auth login` and `glab auth login` in visible external terminals;
- run `ssh -T` probes for GitHub/GitLab without asking the app to store secrets;
- show exact commands;
- run `git` directly for its own workflows.

The user can still solve complex auth/conflict problems in VS Code or GitKraken, then return to Hub Manager.

## Forbidden by design

Hub Manager must not:

- store GitHub/GitLab/Forgejo passwords;
- store PATs in JSON config;
- silently create tokens;
- silently modify global Git credentials;
- force-push by default;
- upload private SSH keys;
- copy SSH private keys into release ZIPs.

## Optional advanced mode: portable SSH

A portable SSH profile can be added later, but must be opt-in and heavily warned.

Possible config shape:

```json
{
  "strategy": "portable_ssh",
  "private_key_path": "secrets/ssh/id_ed25519",
  "require_passphrase": true,
  "enabled": false
}
```

This is risky because a portable app archive can accidentally leak the key. Default policy remains external SSH agent / OS credential store.

## Official references

- GitHub: authentication can use personal access tokens or SSH keys; command-line Git supports HTTPS and SSH remotes.
- GitHub: Git Credential Manager and GitHub CLI can cache HTTPS credentials.
- GitLab: SSH is the recommended authentication method for clone/push/pull; HTTPS with 2FA requires tokens or credential helpers.
- GitLab repository mirroring exists, but client-side multi-remote push remains more transparent and portable for Audion Hub Manager.
