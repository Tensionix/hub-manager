"""Every operation of the Git canon, run on the lab and checked by what it left behind.

The lab (system_core/core/lab.py) is built once per run; each test works on its own copy.
Commands come from the canon table (git_canon.py) and nowhere else, so a wrong command in the
table fails here. Five operations need a real server or a CLI login (ssh -T, gh, glab): they
are checked for their shape only.
"""
from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess
import sys

import pytest

from system_core.core import git_canon
from system_core.core.git_engine import next_version_for_series
from system_core.core.lab import build_lab

NETWORK_ONLY = {"ssh_github", "ssh_gitlab", "gh_runs", "gh_watch", "glab_ci"}


def _env(**extra: str) -> dict[str, str]:
    env = dict(os.environ)
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0",
                "GIT_EDITOR": "true", "GIT_SEQUENCE_EDITOR": "true", "LC_ALL": "C"})
    env.update(extra)
    return env


@pytest.fixture(scope="session")
def lab_master(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return Path(build_lab(tmp_path_factory.mktemp("lab-master") / "lab")["lab"])


@pytest.fixture()
def lab(lab_master: Path, tmp_path: Path) -> Path:
    target = tmp_path / "lab"
    shutil.copytree(lab_master, target)
    return target


def canon(repo: Path, canon_id: str, *, ok: bool = True, **values) -> subprocess.CompletedProcess[str]:
    argv = git_canon.entry(canon_id).argv(**values)
    done = subprocess.run(argv, cwd=repo, env=_env(), capture_output=True, text=True, encoding="utf-8", errors="replace")
    if ok:
        assert done.returncode == 0, f"{' '.join(argv)}\n{done.stdout}\n{done.stderr}"
    return done


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=repo, env=_env(), capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert done.returncode == 0, f"git {' '.join(args)}: {done.stderr}"
    return done.stdout


def porcelain(repo: Path) -> list[str]:
    return [line for line in git(repo, "status", "--porcelain=v1", "--untracked-files=all").splitlines() if line]


def head_message(repo: Path) -> str:
    return git(repo, "log", "-1", "--format=%s").strip()


def branch(repo: Path) -> str:
    return git(repo, "branch", "--show-current").strip()


# --- the table itself ---

def test_every_entry_has_a_test() -> None:
    tests = {name[len("test_canon_"):] for name in dir(sys.modules[__name__]) if name.startswith("test_canon_")}
    assert tests == set(git_canon.BY_ID), sorted(set(git_canon.BY_ID) ^ tests)


def test_entries_are_well_formed() -> None:
    assert len(git_canon.BY_ID) == len(git_canon.CANON)
    for item in git_canon.CANON:
        assert item.risk in git_canon.RISKS and item.mode in git_canon.MODES and item.section in git_canon.SECTIONS, item.id
        assert item.ru[0] and item.ru[1] and item.en[0] and item.en[1], item.id
        # The caption of a button is the command as typed: its program first, no place left in it.
        assert item.short.split()[0] == item.args[0] and "{" not in item.short, item.id
        if item.risk == "danger":
            assert item.mode in {"ask", "template"}, f"{item.id}: a dangerous command must not run without a question"


def test_lab_is_the_same_every_time(tmp_path: Path, lab_master: Path) -> None:
    again = build_lab(tmp_path / "again")
    for name, commit in again["repos"].items():
        if commit:
            repo = lab_master / name / ("source" if name == "10-source-mirror" else "")
            assert git(repo, "rev-parse", "HEAD").strip() == commit, name


# --- changes ---

def test_canon_status(lab: Path) -> None:
    out = canon(lab / "02-index", "status").stdout
    assert out.startswith("## main")
    for line in (" M README.md", "MM config/app.json", "A  docs/guide.md", " D old.txt", "R  src/app.py -> src/main.py", "?? NOTES.md"):
        assert line in out, line


def test_canon_diff(lab: Path) -> None:
    out = canon(lab / "02-index", "diff", path="config/app.json").stdout
    assert '+  "colour": "teal"' in out and '"level": 1' not in out


def test_canon_diff_cached(lab: Path) -> None:
    out = canon(lab / "02-index", "diff_cached", path="config/app.json").stdout
    assert '+  "level": 2' in out and "colour" not in out


def test_canon_diff_head(lab: Path) -> None:
    out = canon(lab / "02-index", "diff_head", path="config/app.json").stdout
    assert '-  "level": 1' in out and "colour" in out


def test_canon_blame(lab: Path) -> None:
    assert "Lab" in canon(lab / "03-branch-merge", "blame", path="README.md").stdout


def test_canon_add(lab: Path) -> None:
    repo = lab / "02-index"
    canon(repo, "add", paths=["README.md", "NOTES.md"])
    assert {"M  README.md", "A  NOTES.md"} <= set(porcelain(repo))


def test_canon_add_profile(lab: Path) -> None:
    # The window passes only what the profile allows; report.pdf is not among them and stays out.
    repo = lab / "02-index"
    canon(repo, "add_profile", paths=["README.md", "NOTES.md", "config/app.json", "old.txt"])
    state = set(porcelain(repo))
    assert {"M  README.md", "A  NOTES.md", "M  config/app.json", "D  old.txt", "?? report.pdf"} <= state


def test_canon_unstage(lab: Path) -> None:
    repo = lab / "02-index"
    canon(repo, "unstage", paths=["docs/guide.md"])
    assert "?? docs/guide.md" in porcelain(repo)


def test_canon_unstage_new(lab: Path) -> None:
    # Before the first commit there is no HEAD: restore --staged fails, rm --cached takes the file off the index.
    repo = lab / "01-first-commit"
    canon(repo, "init", branch="main")
    canon(repo, "add", paths=["README.md"])
    assert canon(repo, "unstage", ok=False, paths=["README.md"]).returncode != 0
    canon(repo, "unstage_new", paths=["README.md"])
    assert "?? README.md" in porcelain(repo) and (repo / "README.md").is_file()


def test_canon_restore(lab: Path) -> None:
    repo = lab / "02-index"
    canon(repo, "restore", paths=["README.md"])
    assert not any(line.endswith(" README.md") for line in porcelain(repo))
    assert "A file can live" not in (repo / "README.md").read_text(encoding="utf-8")


def test_canon_commit(lab: Path) -> None:
    repo = lab / "02-index"
    canon(repo, "commit", message="docs(guide): projection v0.1.0 - a guide")
    assert head_message(repo) == "docs(guide): projection v0.1.0 - a guide"
    state = porcelain(repo)
    assert " M README.md" in state and " M config/app.json" in state and not any(line.startswith("A ") for line in state)


def test_canon_commit_only(lab: Path) -> None:
    repo = lab / "02-index"
    canon(repo, "commit_only", message="docs: only the readme", paths=["README.md"])
    assert git(repo, "show", "--name-only", "--format=", "HEAD").split() == ["README.md"]
    assert "A  docs/guide.md" in porcelain(repo)


def test_a_long_list_of_paths_goes_through_the_input(lab: Path) -> None:
    # The first commit of a big project: its paths do not fit one command line of Windows (32767 characters).
    repo = lab / "02-index"
    names = [f"bulk/{'a_rather_long_folder_name_' * 2}{index:04d}.txt" for index in range(1200)] + ["bulk/документ.txt"]
    for name in names:
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text("x\n", encoding="utf-8")

    def run(canon_id: str, **values) -> None:
        argv, feed = git_canon.entry(canon_id).argv_fit(**values)
        assert feed is not None and "--pathspec-from-file=-" in argv and len(" ".join(argv)) < git_canon.ARGV_LIMIT
        done = subprocess.run(argv, cwd=repo, env=_env(), input=feed, capture_output=True, text=True, encoding="utf-8", errors="replace")
        assert done.returncode == 0, done.stderr

    run("add", paths=names)
    assert sum(1 for line in porcelain(repo) if line.startswith("A  bulk/")) == len(names)
    run("unstage", paths=names)
    assert sum(1 for line in porcelain(repo) if line.startswith("?? bulk/")) == len(names)
    run("add", paths=names)
    run("commit_only", message="code: many files", paths=names)
    assert len(git(repo, "show", "--name-only", "--format=", "HEAD").split()) == len(names)
    # A short list stays the command as typed.
    assert git_canon.entry("add").argv_fit(paths=["README.md"]) == (["git", "add", "--", "README.md"], None)


def test_canon_amend(lab: Path) -> None:
    repo = lab / "07-tags"
    parent = git(repo, "rev-parse", "HEAD~1").strip()
    canon(repo, "amend", message="code(app): projection v0.1.2 - the version")
    assert head_message(repo) == "code(app): projection v0.1.2 - the version"
    assert git(repo, "rev-parse", "HEAD~1").strip() == parent


def test_canon_tag(lab: Path) -> None:
    repo = lab / "07-tags"
    version, _ = next_version_for_series(repo, "projection")
    assert version == "v0.1.2"
    canon(repo, "tag", tag=f"projection-{version}", message=f"projection {version}")
    assert git(repo, "cat-file", "-t", "projection-v0.1.2").strip() == "tag"


# --- history ---

def test_canon_log(lab: Path) -> None:
    assert len(canon(lab / "07-tags", "log").stdout.splitlines()) == 4


def test_canon_graph(lab: Path) -> None:
    out = canon(lab / "03-branch-merge", "graph").stdout
    assert "feature/login" in out and "|\\" in out


def test_canon_log_file(lab: Path) -> None:
    out = canon(lab / "03-branch-merge", "log_file", path="README.md").stdout
    assert "fix(readme): typo" in out and "docs: first draft" in out


def test_canon_reflog(lab: Path) -> None:
    assert "step two" in canon(lab / "08-lost-commit", "reflog").stdout


def test_canon_show(lab: Path) -> None:
    assert "calc.py" in canon(lab / "09-revert-reset", "show", commit="HEAD~2").stdout


def test_canon_tags(lab: Path) -> None:
    lines = canon(lab / "07-tags", "tags").stdout.splitlines()
    assert [line.split()[0] for line in lines] == ["projection-v0.1.1", "projection-v0.1.0"]


def test_canon_tag_at(lab: Path) -> None:
    repo = lab / "07-tags"
    canon(repo, "tag_at", tag="checkpoint-v0.0.1", commit="HEAD~3", message="the very start")
    assert git(repo, "rev-list", "-n", "1", "checkpoint-v0.0.1").strip() == git(repo, "rev-parse", "HEAD~3").strip()


def test_canon_branch_at(lab: Path) -> None:
    repo = lab / "08-lost-commit"
    lost = git(repo, "rev-parse", "HEAD@{1}").strip()
    canon(repo, "branch_at", new_branch="rescue", commit=lost)
    assert branch(repo) == "rescue" and "step two" in (repo / "plan.md").read_text(encoding="utf-8")


def test_canon_revert(lab: Path) -> None:
    repo = lab / "09-revert-reset"
    canon(repo, "revert", commit="HEAD~2")
    assert "a + b" in (repo / "calc.py").read_text(encoding="utf-8")
    assert head_message(repo).startswith('Revert "code(calc): bad')


def test_canon_cherry_pick(lab: Path) -> None:
    repo = lab / "03-branch-merge"
    canon(repo, "cherry_pick", commit="feature/login~1")
    assert (repo / "app/login.py").read_text(encoding="utf-8") == "def login(user):\n    return user\n"


def test_canon_reset_soft(lab: Path) -> None:
    repo = lab / "09-revert-reset"
    canon(repo, "reset_soft")
    assert head_message(repo) == "docs: point at the bad commit" and porcelain(repo) == ["A  tests.py"]


def test_canon_reset_hard(lab: Path) -> None:
    repo = lab / "06-stash"
    canon(repo, "reset_hard", commit="HEAD")
    assert porcelain(repo) == []


# --- branches ---

def test_canon_branches(lab: Path) -> None:
    assert "[origin/main: ahead 2]" in canon(lab / "05-behind-remote", "branches").stdout


def test_canon_switch(lab: Path) -> None:
    repo = lab / "03-branch-merge"
    canon(repo, "switch", branch="feature/login")
    assert branch(repo) == "feature/login"


def test_canon_switch_new(lab: Path) -> None:
    repo = lab / "03-branch-merge"
    canon(repo, "switch_new", new_branch="feature/report")
    assert branch(repo) == "feature/report"


def test_canon_switch_back(lab: Path) -> None:
    repo = lab / "03-branch-merge"
    canon(repo, "switch", branch="feature/login")
    canon(repo, "switch_back")
    assert branch(repo) == "main"


def test_canon_compare(lab: Path) -> None:
    out = canon(lab / "03-branch-merge", "compare", branch="feature/login").stdout
    assert "< " in out and "> " in out


def test_canon_merge(lab: Path) -> None:
    repo = lab / "03-branch-merge"
    canon(repo, "merge", branch="feature/login")
    assert len(git(repo, "rev-list", "--parents", "-n", "1", "HEAD").split()) == 3
    assert "password" in (repo / "app/login.py").read_text(encoding="utf-8")


def test_canon_branch_delete(lab: Path) -> None:
    repo = lab / "03-branch-merge"
    canon(repo, "branch_delete", branch="fix/typo")
    assert canon(repo, "branch_delete", ok=False, branch="feature/login").returncode != 0, "an unmerged branch must be refused"
    assert "fix/typo" not in git(repo, "branch")


def test_canon_stash_push(lab: Path) -> None:
    repo = lab / "06-stash"
    assert subprocess.run(["git", "switch", "other"], cwd=repo, env=_env(), capture_output=True).returncode != 0
    canon(repo, "stash_push", message="my edit")
    assert porcelain(repo) == [] and len(git(repo, "stash", "list").splitlines()) == 2
    git(repo, "switch", "other")


def test_canon_stash_pop(lab: Path) -> None:
    repo = lab / "06-stash"
    canon(repo, "stash_pop")
    assert {" M README.md", " M notes.txt"} <= set(porcelain(repo)) and git(repo, "stash", "list") == ""


def test_canon_stash_list(lab: Path) -> None:
    assert "draft README" in canon(lab / "06-stash", "stash_list").stdout


def test_canon_rebase(lab: Path) -> None:
    # Interactive in the window; here the sequence editor accepts the plan as it is.
    repo = lab / "09-revert-reset"
    before = git(repo, "rev-parse", "HEAD").strip()
    canon(repo, "rebase", range="HEAD~2")
    assert git(repo, "rev-parse", "HEAD").strip() == before


def test_canon_merge_abort(lab: Path) -> None:
    repo = lab / "04-conflict"
    assert "UU style.css" in porcelain(repo)
    canon(repo, "merge_abort")
    assert porcelain(repo) == [] and "red" in (repo / "style.css").read_text(encoding="utf-8")


def test_canon_cherry_pick_abort(lab: Path) -> None:
    repo = lab / "04-conflict"
    canon(repo, "merge_abort")
    assert canon(repo, "cherry_pick", ok=False, commit="feature/colors").returncode != 0
    canon(repo, "cherry_pick_abort")
    assert porcelain(repo) == []


# --- sync ---

def test_canon_fetch(lab: Path) -> None:
    repo = lab / "05-behind-remote"
    canon(repo, "fetch")
    assert "[origin/main: ahead 2, behind 1]" in git(repo, "branch", "-vv")


def test_canon_fetch_remote(lab: Path) -> None:
    repo = lab / "05-behind-remote"
    canon(repo, "fetch_remote", remote="origin")
    assert "[origin/main: ahead 2, behind 1]" in git(repo, "branch", "-vv")


def test_push_names_both_branches_when_their_names_differ(lab: Path) -> None:
    # topic follows origin/docs: "git push origin docs" would send the LOCAL docs, and topic's commit would stay here.
    repo = lab / "05-behind-remote"
    git(repo, "switch", "docs")
    git(repo, "pull", "--ff-only", "origin", "docs")
    git(repo, "switch", "-c", "topic", "--track", "origin/docs")
    (repo / "docs/topic.md").write_text("topic\n", encoding="utf-8")
    git(repo, "add", "--", "docs/topic.md")
    git(repo, "commit", "-q", "-m", "docs: topic")
    canon(repo, "push", remote="origin", branch="topic:docs")
    assert git(repo, "rev-parse", "topic").strip() in git(repo, "ls-remote", "origin", "refs/heads/docs")


def test_canon_pull(lab: Path) -> None:
    repo = lab / "05-behind-remote"
    refused = canon(repo, "pull", ok=False, remote="origin", branch="main")
    assert refused.returncode != 0, "main has parted from the server: --ff-only must refuse"
    git(repo, "switch", "docs")
    canon(repo, "pull", remote="origin", branch="docs")
    assert "from a colleague" in (repo / "docs/notes.md").read_text(encoding="utf-8")


def test_canon_push(lab: Path) -> None:
    repo = lab / "05-behind-remote"
    assert canon(repo, "push", ok=False, remote="origin", branch="main").returncode != 0, "a push over newer server commits is refused"
    git(repo, "switch", "docs")
    git(repo, "pull", "--ff-only", "origin", "docs")
    (repo / "docs/more.md").write_text("more\n", encoding="utf-8")
    git(repo, "add", "--", "docs/more.md")
    git(repo, "commit", "-q", "-m", "docs: more")
    canon(repo, "push", remote="origin", branch="docs")
    assert git(repo, "rev-parse", "HEAD").strip() in git(repo, "ls-remote", "origin", "refs/heads/docs")


def test_canon_push_upstream(lab: Path) -> None:
    repo = lab / "05-behind-remote"
    git(repo, "switch", "-c", "feature/x")
    canon(repo, "push_upstream", remote="origin", branch="feature/x")
    assert git(repo, "rev-parse", "--abbrev-ref", "feature/x@{upstream}").strip() == "origin/feature/x"


def test_canon_push_all(lab: Path) -> None:
    repo = lab / "05-behind-remote"
    git(repo, "switch", "docs")
    git(repo, "pull", "--ff-only", "origin", "docs")
    for remote in git(repo, "remote").split():
        canon(repo, "push_all", remote=remote, branch="docs")
    assert git(repo, "ls-remote", "mirror", "refs/heads/docs").strip()


def test_canon_remotes(lab: Path) -> None:
    out = canon(lab / "05-behind-remote", "remotes").stdout
    assert "origin\t../_servers/demo.git (fetch)" in out and "mirror" in out


def test_canon_remote_add(lab: Path) -> None:
    repo = lab / "03-branch-merge"
    canon(repo, "remote_add", remote="origin", url="../_servers/demo.git")
    assert git(repo, "remote", "get-url", "origin").strip() == "../_servers/demo.git"


def test_canon_remote_set_url(lab: Path) -> None:
    repo = lab / "05-behind-remote"
    canon(repo, "remote_set_url", remote="mirror", url="../_servers/demo.git")
    assert git(repo, "remote", "get-url", "mirror").strip() == "../_servers/demo.git"


def test_canon_origin_push_url(lab: Path) -> None:
    repo = lab / "05-behind-remote"
    git(repo, "remote", "set-url", "--add", "--push", "origin", "../_servers/demo.git")
    canon(repo, "origin_push_url", remote="origin", url="../_servers/mirror.git")
    assert git(repo, "remote", "get-url", "--push", "--all", "origin").split() == ["../_servers/demo.git", "../_servers/mirror.git"]


def test_canon_clone(lab: Path) -> None:
    canon(lab, "clone", url="_servers/demo.git", dest="clone-of-demo")
    assert (lab / "clone-of-demo" / "README.md").exists()


@pytest.mark.parametrize("canon_id", sorted(NETWORK_ONLY))
def test_network_entries_have_their_tool_first(canon_id: str) -> None:
    item = git_canon.entry(canon_id)
    assert item.risk == "net" and item.args[0] in {"ssh", "gh", "glab"} and not item.places


def test_canon_ssh_github() -> None:
    assert git_canon.entry("ssh_github").args[-1] == "git@github.com"


def test_canon_ssh_gitlab() -> None:
    assert git_canon.entry("ssh_gitlab").args[-1] == "git@gitlab.com"


def test_canon_gh_runs() -> None:
    assert git_canon.entry("gh_runs").args[:3] == ("gh", "run", "list")


def test_canon_gh_watch() -> None:
    assert git_canon.entry("gh_watch").args == ("gh", "run", "watch")


def test_canon_glab_ci() -> None:
    assert git_canon.entry("glab_ci").args == ("glab", "ci", "status")


# --- service ---

def test_canon_init(lab: Path) -> None:
    repo = lab / "01-first-commit"
    canon(repo, "init", branch="main")
    assert (repo / ".git").is_dir()
    # The first branch is the one asked for, whatever init.defaultBranch of the machine says.
    assert git(repo, "symbolic-ref", "HEAD").strip() == "refs/heads/main"


def test_canon_root(lab: Path) -> None:
    repo = lab / "02-index"
    assert Path(canon(repo, "root").stdout.strip()).resolve() == repo.resolve()


def test_canon_bundle(lab: Path) -> None:
    repo = lab / "07-tags"
    canon(repo, "bundle", bundle="checkpoint.bundle", branch="main")
    assert "is okay" in subprocess.run(["git", "bundle", "verify", "checkpoint.bundle"], cwd=repo, env=_env(),
                                       capture_output=True, text=True).stderr


def test_canon_clean_preview(lab: Path) -> None:
    repo = lab / "02-index"
    out = canon(repo, "clean_preview").stdout
    assert "Would remove NOTES.md" in out and (repo / "NOTES.md").exists()


def test_canon_gc(lab: Path) -> None:
    canon(lab / "07-tags", "gc")


def test_canon_fsck(lab: Path) -> None:
    canon(lab / "07-tags", "fsck")


def test_canon_config_list(lab: Path) -> None:
    assert "user.name=Lab" in canon(lab / "02-index", "config_list").stdout


def test_canon_config_user(lab: Path) -> None:
    assert "user.name Lab" in canon(lab / "02-index", "config_user").stdout
