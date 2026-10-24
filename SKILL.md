---
name: audion-hub-manager
description: Keep projects in Git and teach Git with Audion Hub Manager - a portable Windows program whose window runs real git and explains every command (what it did, how to undo it) from one table of 63 operations, the Git canon. Mirror a full project into a clean GIT COPY by a profile (no builds, logs or secrets), commit only what the profile allows, compose commit messages with a version, tag versions, set remotes for GitHub, GitLab, Codeberg, Forgejo or Gitea, push and pull, undo and rescue (revert, reset, reflog), branch, merge, stash, back up to a bundle, scan for secrets, build the Git lab of ten training repositories. Use when asked to put a project under Git or version it, make a checkpoint or release a version, commit, tag, push or pull, sync two machines, add a remote or a Forgejo token, undo a commit or find a lost one, get out of a stuck merge or conflict, explain or teach a Git command, mirror a project into its Git copy, check a project for secrets, or to change and check Hub Manager itself.
---

# Audion Hub Manager

A portable Windows program to keep projects in Git and to learn Git on real work. `Start.exe` opens the window
(`App\AudionHubManager.exe`, C# on Avalonia). The window runs real `git` from one table of commands, the canon, and
everything else — the registry, the mirror, the checks, the lab, Forgejo — through the console command `hub_cli.cmd`
(Python 3.12 of `runtime\`, the engine in `system_core\`). What the window does, an agent does with the same two tools.

Paths below are relative to the program folder. Sibling projects are resolved from the parent folder; never hardcode a
drive. Why things are as they are: `MEMORY.md`; the rules of a workshop: `CLAUDE.md`. For people: `docs\README_*`,
`docs\USER_GUIDE_*`, the Git wiki `docs\GIT_WIKI_HUB_MANAGER_*` (every command with its words), the console command
`docs\CLI_*`.

## The model

A project lives in three layers, each a folder of its record in the registry — `hub_projects.json` in the root of the
projects (`hub_cli.cmd storage`), each root with its own:

| Layer | `hub_cli` name | What |
|---|---|---|
| SOURCE (ИСХОДНИК) | `source` | the whole live project, the source of truth; never written by the mirror |
| GIT COPY (GIT-КОПИЯ) | `mirror` | a clean mirror by the project's profile, its own `.git`: the history for the server |
| DOCS | `docs` | Markdown and texts to read |

The work moves through four places: working folder → index (`git add`) → history (`git commit`) → server (`git push`).
Versioning a project means: mirror SOURCE into its GIT COPY, commit there only what the profile allows, tag versions,
push. The SOURCE needs no `.git` of its own for that.

## The rules

1. **Git commands come from the canon, nothing else.** Take the entry, fill its places, run its argv with `git -C
   <layer folder>`. Show the person the command whole and say in plain words what it did and how to undo it — the
   entry's `what` and `undo` (Russian or English, as the person speaks).
2. **Ask before danger.** An entry with risk `danger` or mode `ask` (restore, amend, reset --soft, reset --hard) runs only
   after the person's yes, given after you named the whole command, what is not committed now (`git status --short`) and
   how it is undone. A `template` entry (`rebase -i`) is never run by an agent: hand it to the person.
3. **Only the profile goes into a commit.** Never `git add .`, `git add -A` or `git commit -a` in a layer. Ask
   `hub_cli.cmd check-paths ID --layer mirror|source PATHS…` and add only its `allowed`; `blocked` stays out and is named.
4. **The SOURCE is read only.** The mirror writes SOURCE → GIT COPY; nothing writes back. Restoring a project from its GIT
   COPY is the person's decision.
5. **Secrets are the person's.** Never read, print, store or pass a token or a password. A Forgejo token is typed by the
   person into the window (SYNC → Forgejo) or piped by them into `hub_cli.cmd forgejo sign-in`. A remote URL with
   credentials inside is refused; do not build one.
6. **pull goes by fast-forward only.** When it refuses (the branches parted), merge on purpose (canon `merge`), then
   push. Never force-push.
7. **One question per real choice.** Where a GIT COPY lives, which remote to create, whether to push — the person decides
   once; the rest follows the procedures below.

Git runs without waiting for input: set `GIT_TERMINAL_PROMPT=0`, `GIT_EDITOR=true` and `GIT_SEQUENCE_EDITOR=true` for every
call, as the window does. Messages of git on the error stream are not errors; the exit code is.

## The console command

```
hub_cli.cmd projects list [--fast]                 the registry; each layer: path, exists, repo own|parent|none
hub_cli.cmd projects scan FOLDER [--import] [--hub-root P] [--docs-root P]
hub_cli.cmd projects set ID [--source P] [--mirror P] [--docs P] [--profile X] [--branch B]
hub_cli.cmd projects active ID | remove ID [--dry-run] | clean [--dry-run]
hub_cli.cmd profile ID                             what the profile lets through
hub_cli.cmd check-paths ID --layer source|mirror PATH... | --stdin   allowed / blocked / ignored
hub_cli.cmd mirror plan|verify ID | mirror apply ID --apply
hub_cli.cmd safety ID [--layer source|mirror]      secrets and heavy files; exit 1 on blockers
hub_cli.cmd next-version --repo P [--series S] [--bump patch|minor|major]
hub_cli.cmd remote url --platform github|gitlab|codeberg|forgejo|gitea|custom --owner O --repo R [--type ssh|https] [--server S] [--ssh-port N]
hub_cli.cmd remote list | save --name N --url U
hub_cli.cmd forgejo check|whoami|repos --url U | create --url U --name N
hub_cli.cmd batch status|mirror-plan|safety|verify
hub_cli.cmd auth | tools | storage | blake3
hub_cli.cmd lab create [--replace] [--register]
hub_cli.cmd canon [--docs]
```

One JSON document per call, always with `ok`; on an error `error` and `kind` (`usage`, `failed`). Exit codes: `0` done,
`1` a bad result or a failure, `2` a wrong call — nothing changed. Reports go to `logs\<project>\` and are named by
`report`. Every command and its answer: `docs\CLI_EN.md`.

## The canon

`hub_cli.cmd canon` gives every entry as JSON: `id`, `args` (argv with places `{path}`, `{paths}` — a list, `{commit}`,
`{branch}`, `{new_branch}`, `{remote}`, `{url}`, `{message}`, `{tag}`, `{range}`, `{dest}`, `{bundle}`), `risk` (`read`,
`local`, `net`, `danger`), `mode` (`run`, `ask`, `template`), `section`, `ru` and `en` with `what` and `undo`. In Python:
`system_core.core.git_canon.entry(ID).argv(path=..., paths=[...])` fills the places and refuses a missing one.

<!-- canon:compact -->
| id | command | risk | mode | section |
|---|---|---|---|---|
| `status` | `git status --short --branch` | read | run | changes |
| `diff` | `git diff -- ‹path›` | read | run | changes |
| `diff_cached` | `git diff --cached -- ‹path›` | read | run | changes |
| `diff_head` | `git diff HEAD -- ‹path›` | read | run | changes |
| `blame` | `git blame -- ‹path›` | read | run | changes |
| `add` | `git add -- ‹paths›` | local | run | changes |
| `add_profile` | `git add -- ‹paths›` | local | run | changes |
| `unstage` | `git restore --staged -- ‹paths›` | local | run | changes |
| `unstage_new` | `git rm --cached -- ‹paths›` | local | run | changes |
| `restore` | `git restore -- ‹paths›` | danger | ask | changes |
| `commit` | `git commit -m ‹message›` | local | run | changes |
| `commit_only` | `git commit --only -m ‹message› -- ‹paths›` | local | run | changes |
| `amend` | `git commit --amend -m ‹message›` | danger | ask | changes |
| `tag` | `git tag -a ‹tag› -m ‹message›` | local | run | changes |
| `log` | `git log --oneline --decorate -20` | read | run | history |
| `graph` | `git log --graph --oneline --decorate --all -50` | read | run | history |
| `log_file` | `git log --date=short --pretty=format:%h%x09%ad%x09%an%x09%s -40 -- ‹path›` | read | run | history |
| `reflog` | `git reflog --date=local -20` | read | run | history |
| `show` | `git show --stat ‹commit›` | read | run | history |
| `tags` | `git tag -n --sort=-creatordate` | read | run | history |
| `tag_at` | `git tag -a ‹tag› ‹commit› -m ‹message›` | local | run | history |
| `branch_at` | `git switch -c ‹new_branch› ‹commit›` | local | run | history |
| `revert` | `git revert --no-edit ‹commit›` | local | run | history |
| `cherry_pick` | `git cherry-pick ‹commit›` | local | run | history |
| `reset_soft` | `git reset --soft HEAD~1` | danger | ask | history |
| `reset_hard` | `git reset --hard ‹commit›` | danger | ask | history |
| `branches` | `git branch -vv` | read | run | branches |
| `switch` | `git switch ‹branch›` | local | run | branches |
| `switch_new` | `git switch -c ‹new_branch›` | local | run | branches |
| `switch_back` | `git switch -` | local | run | branches |
| `compare` | `git log --left-right --graph --cherry-pick --oneline HEAD...‹branch›` | read | run | branches |
| `merge` | `git merge --no-ff --no-edit ‹branch›` | local | run | branches |
| `branch_delete` | `git branch -d ‹branch›` | local | run | branches |
| `stash_push` | `git stash push -u -m ‹message›` | local | run | branches |
| `stash_pop` | `git stash pop` | local | run | branches |
| `stash_list` | `git stash list` | read | run | branches |
| `rebase` | `git rebase -i ‹range›` | danger | template | branches |
| `merge_abort` | `git merge --abort` | local | run | branches |
| `cherry_pick_abort` | `git cherry-pick --abort` | local | run | branches |
| `fetch` | `git fetch --all --prune` | net | run | sync |
| `fetch_remote` | `git fetch --prune ‹remote›` | net | run | sync |
| `pull` | `git pull --ff-only ‹remote› ‹branch›` | net | run | sync |
| `push` | `git push --follow-tags ‹remote› ‹branch›` | net | run | sync |
| `push_upstream` | `git push -u ‹remote› ‹branch›` | net | run | sync |
| `push_all` | `git push --follow-tags ‹remote› ‹branch›` | net | run | sync |
| `remotes` | `git remote -v` | read | run | sync |
| `remote_add` | `git remote add ‹remote› ‹url›` | local | run | sync |
| `remote_set_url` | `git remote set-url ‹remote› ‹url›` | local | run | sync |
| `origin_push_url` | `git remote set-url --add --push ‹remote› ‹url›` | local | run | sync |
| `clone` | `git clone ‹url› ‹dest›` | net | run | projects |
| `ssh_github` | `ssh -T -o BatchMode=yes git@github.com` | net | run | sync |
| `ssh_gitlab` | `ssh -T -o BatchMode=yes git@gitlab.com` | net | run | sync |
| `gh_runs` | `gh run list --limit 15` | net | run | sync |
| `gh_watch` | `gh run watch` | net | run | sync |
| `glab_ci` | `glab ci status` | net | run | sync |
| `init` | `git init -b ‹branch›` | local | run | service |
| `root` | `git rev-parse --show-toplevel` | read | run | service |
| `bundle` | `git bundle create ‹bundle› ‹branch› --tags` | local | run | service |
| `clean_preview` | `git clean -nd` | read | run | service |
| `gc` | `git gc` | local | run | service |
| `fsck` | `git fsck --full` | read | run | service |
| `config_list` | `git config --list --show-origin` | read | run | service |
| `config_user` | `git config --show-origin --get-regexp user\.` | read | run | service |
<!-- /canon -->

## Procedures

### Put a project under Git

1. **Register it.** `hub_cli.cmd projects scan "<project folder>" --hub-root "<folder of GIT COPIES>"` shows the
   candidate; with `--import` it enters the registry. A folder that is a project itself (`.git`, `README.md`,
   `pyproject.toml`…) finds itself. Where the GIT COPIES live is the person's choice — ask once; without `--hub-root` they
   go to `Hub Data` beside the program folder, the `hub_data_root` of `config\storage_layout.json`, and
   `hub_cli.cmd storage` checks every copy lies under it.
2. **Look.** `projects list` — the layers of the new id; `profile ID` — what will pass.
3. **Mirror.** `mirror plan ID` (read `summary`: copy, update, delete, outside the profile, hidden by `.gitignore`) →
   `mirror apply ID --apply` → `mirror verify ID` (exit 0: the copy matches) → `safety ID --layer mirror`: a blocker (a
   key, a `.env`, a token in text) stops the procedure until the person decides. Scan the copy, not the SOURCE: the
   SOURCE holds builds and toolchains the copy never gets, and its scan is slow and loud. A blocker in a file the project
   itself has long committed (test keys of a password manager, the pattern of a key scanner) is no secret of the
   person's — say so and go on; never print what a finding says.
4. **Start the history** in the GIT COPY if `layers.mirror.repo` is not `own`: canon `init` in that folder. If it is
   `parent`, the folder lies inside another repository — `init` there, never commit into the outer one. Give `init` the
   record's `default_branch` as `branch` (`git init -b main`): without it Git names the first branch by the machine's
   `init.defaultBranch`, and pull and push of the record would look for another name.
5. **First commit.** `check-paths ID --layer mirror .` → canon `add` with the `allowed` paths → canon `commit` with a
   message (below). `ignored` — what the project's own `.gitignore` hides — stays out: the project's word stands over the
   profile. Canon `tag` with the first version if the person wants one (`v0.1.0`). A big project has thousands of paths,
   more than one command line of Windows holds: take `git_canon.entry("add").argv_fit(paths=…)` — it gives the command
   with `--pathspec-from-file=- --pathspec-file-nul` and the input to feed it; `check-paths … --stdin` reads its paths a
   line each. The window does both by itself.
6. **A server**, if asked: `remote url …` → canon `remote_add` (`origin`) → canon `push_upstream` (`-u origin
   <branch>`, the branch canon `status` names).
   Check access first: canon `ssh_github` / `ssh_gitlab`, or `hub_cli.cmd auth`.

### A checkpoint of a registered project

`mirror apply ID --apply` → `mirror verify ID` → in the GIT COPY canon `status` → `check-paths ID --layer mirror` with the
changed paths → canon `add` of `allowed` → canon `commit` → canon `push` (`--follow-tags`) if the project has a server.
`batch status` and `batch verify` show every project at once; a project whose copy differs is the one to checkpoint.

### Release a version

`next-version --repo "<GIT COPY>" --series SERIES --bump patch|minor|major` → `version` and `tag` → the commit message
carries `SERIES VERSION` → canon `tag` with `tag` → canon `push`. patch — a fix, minor — a new ability, major — an
incompatible change.

### Undo and rescue

| Situation | Canon |
|---|---|
| a file put into the index by mistake | `unstage` |
| edits of a file to throw away (lost for good — ask) | `restore` |
| the last commit is wrong and not sent | `reset_soft` (files back in the index), or `amend` (ask) |
| a commit already pushed is wrong | `revert` — a new commit, history kept |
| a commit lost after a reset | `reflog`, then `branch_at` on its hash |
| a merge or a cherry-pick stopped on a conflict | resolve the files marked `U`, `add`, `commit`; or `merge_abort` / `cherry_pick_abort` |
| edits stand in the way of a switch | `stash_push`, `switch`, later `stash_pop` |
| pull refused, the branches parted | `fetch`, `merge` of `origin/<branch>`, then `push` |
| everything after a commit must go (ask, uncommitted is lost) | `reset_hard` |

### Two machines

Machine A: commit → tag → canon `push`. Machine B: canon `fetch` → canon `pull` (fast-forward). `fetch` changes nothing of
the person's; say so — it is the safe first step.

### Forgejo or Gitea

`forgejo check --url U` → the person makes a token (Settings → Applications → Generate New Token) and gives it to the
window or pipes it into `forgejo sign-in --url U --login L` → `forgejo whoami` → `forgejo repos` or `forgejo create --name
N` → `remote url --platform forgejo --server … --type https` → canon `remote_add`, `push_upstream`.

### A backup without a server

Canon `bundle` (`git bundle create <file> <branch> --tags`) in the GIT COPY; `git clone <file>` brings it back.

### Teach

`lab create --replace --register` builds ten repositories (`lab_01` … `lab_10`) in known states; `examples\lab\LAB.md` says
what to try in each. Explain by the canon's words and the plain words of `docs\GIT_WIKI_HUB_MANAGER_*`: a branch is a
draft, `main` the fair copy, merge takes a draft in, the index is the desk before a commit, a tag is a version mark.

## The commit message

```
type(scope): series version - subject
docs(readme): projection v0.1.3 - a section on the mirror
```

Types: `docs`, `code`, `fix`, `ui`, `test`, `chore`, `audit`. The scope may be empty (`docs: …`); the series and the version
come together or not at all. The subject says what was done and why, briefly, in the person's language.

## Checking the program itself

```
runtime\python.exe -m pytest -q -p no:cacheprovider tests      the engine, the console command, every canon entry on the lab
hub_cli.cmd canon --docs                                        after a change of the canon: the tables of the documents
install\Build-App.cmd                                           the window and its self-check
install\verify_portable_env.cmd                                 environment, console command, Start.exe, window
```

A new Git operation is a new entry of `system_core\core\git_canon.py` with its words in both languages and its undo, a
check in `tests\test_git_canon.py` on the lab, then `canon --docs` — not code in the window.
