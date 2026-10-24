"""The Git lab: ten small repositories in known states, built the same way on any machine.

Each repository is a lesson and a test bench at once. A person breaks it while learning and
builds it again with one button; the tests run every operation of the Git canon (git_canon.py)
on a fresh copy and check what came of it. The authors, the dates and the bytes of every file
are fixed, so the commit hashes are the same on every machine and in every run.

Layout of the lab folder (examples/lab by default):

    01-first-commit      files, no repository yet
    02-index             changed, new, deleted, renamed, half in the index
    03-branch-merge      a feature branch behind main, a merged fix branch
    04-conflict          a merge stopped on a conflict
    05-behind-remote     a clone whose server moved on while it did too
    06-stash             edits that stand in the way of a switch, one stash already
    07-tags              a series of version tags, one commit after the last
    08-lost-commit       a commit reset away, found only in the reflog
    09-revert-reset      a straight history with one bad commit
    10-source-mirror     a full project and its clean Git copy, apart
    _servers/            bare repositories: the "server" of 05
    LAB.md               what each one teaches
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os
import shutil
import subprocess

LAB_DIR_NAME = "lab"
AUTHOR = ("Lab", "lab@example.invalid")
# 19 October 2026, 22:00 UTC+6: the first commit of the lab; every next one is an hour later.
EPOCH = 1792425600
OFFSET = "+0600"

REPOS = (
    "01-first-commit", "02-index", "03-branch-merge", "04-conflict", "05-behind-remote",
    "06-stash", "07-tags", "08-lost-commit", "09-revert-reset", "10-source-mirror",
)


class LabError(RuntimeError):
    pass


@dataclass
class Clock:
    """Hands out the dates of commits: fixed, one hour apart."""
    tick: int = 0

    def next(self) -> str:
        stamp = f"{EPOCH + self.tick * 3600} {OFFSET}"
        self.tick += 1
        return stamp


@dataclass
class Repo:
    path: Path
    clock: Clock
    git_exe: str = "git"
    log: list[str] = field(default_factory=list)

    def env(self, date: str | None = None) -> dict[str, str]:
        env = dict(os.environ)
        # The lab must not depend on the person's Git settings: no global or system config, no hooks.
        env["GIT_CONFIG_NOSYSTEM"] = "1"
        env["GIT_CONFIG_GLOBAL"] = os.devnull
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GIT_AUTHOR_NAME"], env["GIT_AUTHOR_EMAIL"] = AUTHOR
        env["GIT_COMMITTER_NAME"], env["GIT_COMMITTER_EMAIL"] = AUTHOR
        if date:
            env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
        return env

    def git(self, *args: str, date: str | None = None, ok: bool = True) -> subprocess.CompletedProcess[str]:
        done = subprocess.run(
            [self.git_exe, *args], cwd=self.path, env=self.env(date), capture_output=True,
            text=True, encoding="utf-8", errors="replace",
        )
        self.log.append(f"{self.path.name}$ git {' '.join(args)} -> {done.returncode}")
        if ok and done.returncode != 0:
            raise LabError(f"git {' '.join(args)} in {self.path}: {done.stderr.strip() or done.stdout.strip()}")
        return done

    def write(self, rel: str, text: str) -> None:
        target = self.path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))

    def write_bytes(self, rel: str, data: bytes) -> None:
        target = self.path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def init(self, branch: str = "main") -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        self.git("init", "-q", "-b", branch)
        self.configure()

    def configure(self) -> None:
        # Kept in the repository itself, so a person can commit in the lab even with no Git identity of their own.
        for key, value in (("user.name", AUTHOR[0]), ("user.email", AUTHOR[1]), ("core.autocrlf", "false"),
                           ("commit.gpgsign", "false"), ("tag.gpgsign", "false"), ("core.quotepath", "false")):
            self.git("config", key, value)

    def commit(self, message: str, *paths: str) -> None:
        self.git("add", "-A", "--", *(paths or (".",)))
        self.git("commit", "-q", "-m", message, date=self.clock.next())

    def tag(self, name: str, message: str, target: str = "HEAD") -> None:
        self.git("tag", "-a", name, target, "-m", message, date=self.clock.next())

    def head(self) -> str:
        return self.git("rev-parse", "HEAD").stdout.strip()


# --- the ten lessons ---

def _first_commit(repo: Repo) -> None:
    repo.path.mkdir(parents=True, exist_ok=True)
    repo.write("README.md", "# Hello lab\n\nThis folder has no repository yet. Make one: git init.\n")
    repo.write("src/hello.py", 'print("hello, lab")\n')
    repo.write(".gitignore", "output/\n")


def _index(repo: Repo) -> None:
    repo.init()
    repo.write("README.md", "# Index lab\n\nThree places of Git: the working folder, the index, the history.\n")
    repo.write("config/app.json", '{\n  "name": "lab",\n  "level": 1\n}\n')
    repo.write("old.txt", "an old file that goes away\n")
    repo.write("src/app.py", 'def main():\n    print("lab")\n')
    repo.write(".gitignore", "output/\n")
    repo.commit("docs: first draft")
    repo.write("src/app.py", 'def main():\n    print("lab", 2)\n')
    repo.commit("code(app): print the level")
    # Staged: a new guide, a rename, one change of config/app.json.
    repo.write("docs/guide.md", "# Guide\n\nStage a file, then commit it.\n")
    repo.git("add", "--", "docs/guide.md")
    repo.git("mv", "src/app.py", "src/main.py")
    repo.write("config/app.json", '{\n  "name": "lab",\n  "level": 2\n}\n')
    repo.git("add", "--", "config/app.json")
    # Not staged: a second change of the same file, a changed README, a deleted file.
    repo.write("config/app.json", '{\n  "name": "lab",\n  "level": 2,\n  "colour": "teal"\n}\n')
    repo.write("README.md", "# Index lab\n\nThree places of Git: the working folder, the index, the history.\nA file can live in two of them at once.\n")
    (repo.path / "old.txt").unlink()
    # New and unknown to Git; the PDF is outside every projection profile.
    repo.write("NOTES.md", "notes nobody added yet\n")
    repo.write_bytes("output/report.pdf", b"%PDF-1.7\n% lab\n")
    repo.write_bytes("report.pdf", b"%PDF-1.7\n% a build result beside the code\n")


def _branch_merge(repo: Repo) -> None:
    repo.init()
    repo.write("README.md", "# Branch lab\n")
    repo.write("app/login.py", "def login():\n    return None\n")
    repo.commit("docs: first draft")
    repo.write("app/core.py", "VERSION = 1\n")
    repo.commit("code(core): version 1")
    repo.git("switch", "-q", "-c", "feature/login")
    repo.write("app/login.py", "def login(user):\n    return user\n")
    repo.commit("code(login): take a user")
    repo.write("app/login.py", "def login(user, password):\n    return user if password else None\n")
    repo.commit("code(login): check the password")
    repo.git("switch", "-q", "main")
    repo.write("app/core.py", "VERSION = 2\n")
    repo.commit("code(core): version 2")
    repo.git("switch", "-q", "-c", "fix/typo")
    repo.write("README.md", "# Branch lab\n\nTwo branches, one merged.\n")
    repo.commit("fix(readme): typo")
    repo.git("switch", "-q", "main")
    repo.git("merge", "--no-ff", "--no-edit", "-q", "fix/typo", date=repo.clock.next())


def _conflict(repo: Repo) -> None:
    repo.init()
    repo.write("style.css", "body {\n  color: blue;\n}\n")
    repo.write("README.md", "# Conflict lab\n")
    repo.commit("ui: blue text")
    repo.git("switch", "-q", "-c", "feature/colors")
    repo.write("style.css", "body {\n  color: green;\n}\n")
    repo.commit("ui(colors): green text")
    repo.git("switch", "-q", "main")
    repo.write("style.css", "body {\n  color: red;\n}\n")
    repo.commit("ui: red text")
    # Stops on the conflict and stays there: the lesson is the merge in progress.
    done = repo.git("merge", "--no-ff", "--no-edit", "feature/colors", date=repo.clock.next(), ok=False)
    if done.returncode == 0:
        raise LabError("04-conflict: the merge did not stop on a conflict")


def _behind_remote(repo: Repo, servers: Path) -> None:
    origin = servers / "demo.git"
    mirror = servers / "mirror.git"
    for bare in (origin, mirror):
        bare.mkdir(parents=True, exist_ok=True)
        Repo(bare, repo.clock, repo.git_exe).git("init", "-q", "--bare", "-b", "main")
    repo.init()
    # Relative addresses: the lab moves with the program and still finds its server.
    repo.git("remote", "add", "origin", "../_servers/demo.git")
    repo.git("remote", "add", "mirror", "../_servers/mirror.git")
    repo.write("README.md", "# Remote lab\n")
    repo.commit("docs: first draft")
    repo.write("docs/notes.md", "# Notes\n")
    repo.commit("docs(notes): start")
    repo.git("switch", "-q", "-c", "docs")
    repo.write("docs/notes.md", "# Notes\n\nOn the docs branch.\n")
    repo.commit("docs(notes): a line")
    repo.git("push", "-q", "-u", "origin", "docs")
    repo.git("switch", "-q", "main")
    repo.git("push", "-q", "-u", "origin", "main")
    # Someone else moves the server on: one commit on main, one on docs.
    other = Repo(repo.path.parent / "_servers" / "_other", repo.clock, repo.git_exe)
    subprocess.run([repo.git_exe, "clone", "-q", str(origin), str(other.path)], env=repo.env(), check=True, capture_output=True)
    other.configure()
    other.write("CHANGELOG.md", "# Changelog\n\n- written on the server side\n")
    other.commit("docs(changelog): from a colleague")
    other.git("push", "-q", "origin", "main")
    other.git("switch", "-q", "docs")
    other.write("docs/notes.md", "# Notes\n\nOn the docs branch.\nAnd one more from a colleague.\n")
    other.commit("docs(notes): from a colleague")
    other.git("push", "-q", "origin", "docs")
    shutil.rmtree(other.path, onerror=_writable_and_retry)
    # Meanwhile two commits here, not pushed: main is ahead 2 and, after a fetch, behind 1.
    repo.write("app.py", 'print("remote lab")\n')
    repo.commit("code(app): first line")
    repo.write("app.py", 'print("remote lab", 2)\n')
    repo.commit("code(app): second line")


def _stash(repo: Repo) -> None:
    repo.init()
    repo.write("notes.txt", "line one\n")
    repo.write("README.md", "# Stash lab\n")
    repo.commit("docs: first draft")
    repo.git("switch", "-q", "-c", "other")
    repo.write("notes.txt", "line one\nfrom the other branch\n")
    repo.commit("docs(notes): other branch")
    repo.git("switch", "-q", "main")
    repo.write("README.md", "# Stash lab\n\nA draft put aside.\n")
    repo.git("stash", "push", "-q", "-m", "draft README", date=repo.clock.next())
    # This edit stands in the way: git switch other refuses until it is put aside.
    repo.write("notes.txt", "line one\nan edit of my own\n")


def _tags(repo: Repo) -> None:
    repo.init()
    repo.write("README.md", "# Tags lab\n")
    repo.commit("docs: first draft")
    repo.tag("projection-v0.1.0", "projection v0.1.0")
    repo.write("app.py", "VERSION = (0, 1, 1)\n")
    repo.commit("code(app): projection v0.1.1 - the version")
    repo.write("CHANGELOG.md", "# Changelog\n\n## 0.1.1\n")
    repo.commit("docs(changelog): projection v0.1.1 - notes")
    repo.tag("projection-v0.1.1", "projection v0.1.1")
    repo.write("app.py", "VERSION = (0, 1, 2)\n")
    repo.commit("code(app): the next step, not tagged yet")


def _lost_commit(repo: Repo) -> None:
    repo.init()
    repo.write("README.md", "# Lost commit lab\n")
    repo.commit("docs: first draft")
    repo.write("plan.md", "# Plan\n\n- step one\n")
    repo.commit("docs(plan): step one")
    repo.write("plan.md", "# Plan\n\n- step one\n- step two, the important one\n")
    repo.commit("docs(plan): step two - the one that gets lost")
    repo.git("reset", "-q", "--hard", "HEAD~1")


def _revert_reset(repo: Repo) -> None:
    repo.init()
    repo.write("calc.py", "def total(a, b):\n    return a + b\n")
    repo.commit("code(calc): add")
    repo.write("README.md", "# Revert lab\n")
    repo.commit("docs: readme")
    repo.write("calc.py", "def total(a, b):\n    return a - b\n")
    repo.commit("code(calc): bad - broke the sum")
    repo.write("README.md", "# Revert lab\n\nThe third commit is the bad one.\n")
    repo.commit("docs: point at the bad commit")
    repo.write("tests.py", "from calc import total\nassert total(2, 2) == 4\n")
    repo.commit("test(calc): the sum")


def _source_mirror(repo: Repo) -> None:
    source = Repo(repo.path / "source", repo.clock, repo.git_exe)
    mirror = Repo(repo.path / "git-copy", repo.clock, repo.git_exe)
    source.init()
    source.write("README.md", "# Mirror lab\n\nThe full project.\n")
    source.write("AGENTS.md", "# Agents\n")
    source.write("system_core/app.py", 'print("mirror lab")\n')
    source.write("config/app.json", '{\n  "name": "mirror lab"\n}\n')
    source.write("docs/GUIDE.md", "# Guide\n")
    source.write(".gitignore", "runtime/\nlogs/\noutput/\n.env\n*.local.json\n")
    source.commit("docs: first draft")
    source.write("system_core/app.py", 'print("mirror lab", 2)\n')
    source.write("system_core/new_module.py", "VALUE = 1\n")
    source.commit("code: second step")
    # What a live project carries and the Git copy must never take.
    source.write_bytes("runtime/python.exe", b"MZ lab runtime stand-in\n")
    source.write("logs/run.log", "a log line\n")
    source.write_bytes("output/report.pdf", b"%PDF-1.7\n% lab\n")
    source.write(".env", "TOKEN=not-a-real-token\n")
    source.write("config/machine.local.json", '{\n  "path": "C:/here"\n}\n')
    # The Git copy, made a step ago: it lacks the new module and keeps a file the project dropped.
    mirror.init()
    mirror.write("README.md", "# Mirror lab\n\nThe full project.\n")
    mirror.write("AGENTS.md", "# Agents\n")
    mirror.write("system_core/app.py", 'print("mirror lab")\n')
    mirror.write("config/app.json", '{\n  "name": "mirror lab"\n}\n')
    mirror.write("docs/GUIDE.md", "# Guide\n")
    mirror.write("docs/old_notes.md", "# Old notes\n\nThe project dropped this file.\n")
    mirror.commit("mirror: first projection")


LESSONS = {
    "01-first-commit": _first_commit,
    "02-index": _index,
    "03-branch-merge": _branch_merge,
    "04-conflict": _conflict,
    "06-stash": _stash,
    "07-tags": _tags,
    "08-lost-commit": _lost_commit,
    "09-revert-reset": _revert_reset,
    "10-source-mirror": _source_mirror,
}

LAB_MD = """# Git lab / Учебная лаборатория Git

Ten small repositories in known states. Break them freely: Hub Manager builds them again with one
button (PROJECTS → GIT LAB), the same commits with the same hashes on any machine.

Десять маленьких репозиториев в известных состояниях. Ломайте смело: Hub Manager строит их заново
одной кнопкой (ПРОЕКТЫ → УЧЕБНАЯ ЛАБОРАТОРИЯ), те же коммиты с теми же хэшами на любой машине.

| | Репозиторий | Что в нём | Что попробовать |
|---|---|---|---|
| 01 | first-commit | файлы, репозитория ещё нет | git init, add, commit |
| 02 | index | изменены, новые, удалён, переименован, файл наполовину в индексе | status, три вида diff, add, restore --staged, restore, коммит части файлов |
| 03 | branch-merge | ветка feature/login позади main, fix/typo уже слита | switch, switch -c, switch -, сравнить, merge --no-ff, branch -d |
| 04 | conflict | слияние остановилось на конфликте в style.css | разобрать конфликт или merge --abort |
| 05 | behind-remote | свой «сервер» в _servers; у вас 2 неотправленных коммита, на сервере 1 новый | fetch, pull --ff-only (на main откажет, на docs пройдёт), push, push -u |
| 06 | stash | правка notes.txt мешает перейти на ветку other; один stash уже лежит | stash push, switch, stash list, stash pop |
| 07 | tags | теги projection-v0.1.0 и v0.1.1, после них ещё коммит | следующая версия, tag -a, tag -n |
| 08 | lost-commit | коммит «step two» стёрт reset'ом | reflog, ветка от потерянного коммита |
| 09 | revert-reset | третий коммит сломал расчёт | revert, reset --soft, reset --hard |
| 10 | source-mirror | проект (source) и его GIT-КОПИЯ (git-copy) разошлись | план зеркала, применить, сверить, коммит GIT-КОПИИ |
"""


def build_lab(target: Path, *, git_exe: str = "git") -> dict[str, object]:
    """Build the lab into `target`, which must not exist yet. Returns what was built."""
    target = Path(target)
    if target.exists():
        raise LabError(f"{target} exists: move it away first (the window sends it to the Recycle Bin)")
    target.mkdir(parents=True)
    clock = Clock()
    built: dict[str, str] = {}
    log: list[str] = []
    servers = target / "_servers"
    for name in REPOS:
        repo = Repo(target / name, clock, git_exe, log)
        if name == "05-behind-remote":
            _behind_remote(repo, servers)
        else:
            LESSONS[name](repo)
        if name == "10-source-mirror":
            built[name] = Repo(repo.path / "source", clock, git_exe).head()
        elif (repo.path / ".git").exists():
            built[name] = repo.head()
        else:
            built[name] = ""
    (target / "LAB.md").write_bytes(LAB_MD.encode("utf-8"))
    return {"lab": str(target), "repos": built, "steps": len(log)}


def default_lab_dir(app_root: Path) -> Path:
    return Path(app_root) / "examples" / LAB_DIR_NAME


def _writable_and_retry(func, path, _info) -> None:  # noqa: ANN001
    # Git keeps its objects read-only; a scratch clone of the builder itself is removed this way.
    os.chmod(path, 0o666)
    func(path)
