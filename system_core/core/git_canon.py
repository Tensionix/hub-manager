"""The Git canon of Audion Hub Manager: every Git operation the program offers, in one table.

One entry is one operation: the exact command (argv with {places}), how risky it is, where the
window shows it, whether it runs at once, asks first or goes to the command line to be finished,
and what it does and how to undo it in plain words, Russian and English. The window reads the
table through `hub_cli canon`, the tests run every entry on the lab repositories (lab.py), the
documents quote it. Nothing else names a Git command of the program.

Risk:
  read    changes nothing
  local   changes this repository only
  net     talks to a server
  danger  can lose work or rewrite history: the window asks before it runs

Mode:
  run       runs at once
  ask       runs after a question that shows the command and what it costs
  template  goes to the command line with its places marked; the person finishes it
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re

PLACE_RE = re.compile(r"\{([a-z_]+)\}")

# Windows starts a program with a command line of at most 32767 characters; the first commit of a big project passes it.
ARGV_LIMIT = 24000


def fit(argv: list[str]) -> tuple[list[str], str | None]:
    """A git command whose paths after `--` would not fit into one command line: the same command reading them from
    its input (`--pathspec-from-file=- --pathspec-file-nul`), and that input. A command that fits comes back as it is,
    with no input - the lesson is the command as typed."""
    if not argv or argv[0] != "git" or "--" not in argv or sum(len(arg) + 3 for arg in argv) <= ARGV_LIMIT:
        return argv, None
    cut = argv.index("--")
    return [*argv[:cut], "--pathspec-from-file=-", "--pathspec-file-nul"], "\0".join(argv[cut + 1:]) + "\0"


@dataclass(frozen=True)
class CanonEntry:
    id: str
    args: tuple[str, ...]
    risk: str
    mode: str
    section: str
    ru: tuple[str, str]
    en: tuple[str, str]
    old: str = ""
    tags: tuple[str, ...] = field(default=())

    @property
    def places(self) -> tuple[str, ...]:
        found: list[str] = []
        for arg in self.args:
            for name in PLACE_RE.findall(arg):
                if name not in found:
                    found.append(name)
        return tuple(found)

    def argv(self, **values: str | list[str]) -> list[str]:
        """The command with its places filled. A list value spreads into several arguments
        when the place stands alone ({paths}); a missing value is an error, not a guess."""
        out: list[str] = []
        for arg in self.args:
            names = PLACE_RE.findall(arg)
            if len(names) == 1 and arg == "{" + names[0] + "}" and isinstance(values.get(names[0]), list):
                out.extend(str(item) for item in values[names[0]])  # type: ignore[union-attr]
                continue
            for name in names:
                if name not in values:
                    raise KeyError(f"{self.id}: no value for {{{name}}}")
            out.append(PLACE_RE.sub(lambda m: str(values[m.group(1)]), arg))
        return out

    def argv_fit(self, **values: str | list[str]) -> tuple[list[str], str | None]:
        """argv(), made to fit one command line: see fit()."""
        return fit(self.argv(**values))

    @property
    def short(self) -> str:
        """The command as a person types it, without its places and quiet flags: "git restore --staged",
        "git switch -c", "git log --graph --all". The caption of a button: what to type in a terminal."""
        if self.id in SHORT:
            return SHORT[self.id]
        args = [a for a in self.args if "{" not in a]
        words = args[:2]
        if len(args) > 2 and not args[2].startswith("-") and args[2] != "--":
            words.append(args[2])
        words += [a for a in args[2:] if a in MEANINGFUL_FLAGS and a not in words]
        return " ".join(words)

    def display(self) -> str:
        """The command as the window prints it, places shown as ‹place›."""
        return " ".join(_quote_for_display(PLACE_RE.sub(lambda m: f"‹{m.group(1)}›", arg)) for arg in self.args)


def _quote_for_display(arg: str) -> str:
    return f'"{arg}"' if " " in arg and not arg.startswith("‹") else arg


def _e(id: str, args: str, risk: str, mode: str, section: str, ru: tuple[str, str], en: tuple[str, str], old: str = "", tags: tuple[str, ...] = ()) -> CanonEntry:
    return CanonEntry(id, tuple(_split(args)), risk, mode, section, ru, en, old, tags)


def _split(text: str) -> list[str]:
    """Split on spaces, keeping "quoted parts" whole (the quotes are not part of the argument)."""
    parts: list[str] = []
    for match in re.finditer(r'"([^"]*)"|(\S+)', text):
        parts.append(match.group(1) if match.group(1) is not None else match.group(2))
    return parts


# The flags a caption keeps: they change what a command does. The others (--short, --decorate, -20, -m) say how.
MEANINGFUL_FLAGS = {
    "--staged", "--cached", "--hard", "--soft", "--abort", "--amend", "--only", "-c", "-u", "-i", "--no-ff", "--all",
    "--graph", "--ff-only", "--full", "-nd", "-vv", "-v", "-d", "-", "-n", "--list", "--add", "--push",
    "--show-toplevel", "--get-regexp",
}
# The programs that are not git: their captions are said whole.
SHORT = {
    "ssh_github": "ssh -T git@github.com", "ssh_gitlab": "ssh -T git@gitlab.com",
    "gh_runs": "gh run list", "gh_watch": "gh run watch", "glab_ci": "glab ci status",
}

NOTHING_RU = "Ничего не меняет."
NOTHING_EN = "Changes nothing."

CANON: tuple[CanonEntry, ...] = (
    # --- changes: status, differences, the index, the commit ---
    _e("status", "git status --short --branch", "read", "run", "changes",
       ("Что изменено, что в индексе и насколько ветка впереди или позади remote.", NOTHING_RU),
       ("What changed, what is in the index and how far the branch is ahead of or behind its remote.", NOTHING_EN),
       old="Quick → git status"),
    _e("diff", "git diff -- {path}", "read", "run", "changes",
       ("Чем файл в рабочей папке отличается от индекса: что ещё не подготовлено к коммиту.", NOTHING_RU),
       ("How the file in the working folder differs from the index: what is not yet prepared for the commit.", NOTHING_EN),
       old="Quick → git diff --; Diff → Unstaged"),
    _e("diff_cached", "git diff --cached -- {path}", "read", "run", "changes",
       ("Что из файла уже лежит в индексе и войдёт в следующий коммит.", NOTHING_RU),
       ("What of the file is already in the index and goes into the next commit.", NOTHING_EN),
       old="Quick → git diff --cached --; Diff → Staged"),
    _e("diff_head", "git diff HEAD -- {path}", "read", "run", "changes",
       ("Все изменения файла против последнего коммита — и в индексе, и нет.", NOTHING_RU),
       ("Every change of the file against the last commit, in the index or not.", NOTHING_EN),
       old="Diff → HEAD"),
    _e("blame", "git blame -- {path}", "read", "run", "changes",
       ("Кто и в каком коммите написал каждую строку файла.", NOTHING_RU),
       ("Who wrote each line of the file and in which commit.", NOTHING_EN),
       old="Quick → git blame --"),
    _e("add", "git add -- {paths}", "local", "run", "changes",
       ("Кладёт файлы в индекс — «на стол перед коммитом». Следующий коммит возьмёт именно то, что в индексе.",
        "Отменить: git restore --staged -- ‹файлы›"),
       ("Puts the files into the index, \"on the table before the commit\". The next commit takes exactly what the index holds.",
        "Undo: git restore --staged -- ‹files›"),
       old="Quick → git add --; Basket → git add -- basket"),
    _e("add_profile", "git add -- {paths}", "local", "run", "changes",
       ("Кладёт в индекс все изменения слоя, но только файлы, которые разрешает профиль проекта: логи, сборки и секреты не попадут.",
        "Отменить: git restore --staged -- ."),
       ("Puts every change of the layer into the index, but only the files the project profile allows: logs, builds and secrets stay out.",
        "Undo: git restore --staged -- ."),
       old="Quick/Basket → add active project", tags=("profile",)),
    _e("unstage", "git restore --staged -- {paths}", "local", "run", "changes",
       ("Снимает файлы со стола: они остаются изменёнными в рабочей папке, но в коммит не войдут.",
        "Отменить: git add -- ‹файлы›"),
       ("Takes the files off the table: they stay changed in the working folder but leave the commit.",
        "Undo: git add -- ‹files›"),
       old="Quick → git restore --staged --; Basket → git restore --staged -- basket"),
    # Before the first commit there is no HEAD for restore --staged to take the files back to; git itself advises rm --cached.
    _e("unstage_new", "git rm --cached -- {paths}", "local", "run", "changes",
       ("Снимает файлы со стола, пока в репозитории нет ни одного коммита: из индекса они уходят, в рабочей папке остаются.",
        "Отменить: git add -- ‹файлы›"),
       ("Takes the files off the table while the repository has no commit yet: they leave the index and stay in the "
        "working folder.",
        "Undo: git add -- ‹files›"),
       tags=("first_commit",)),
    _e("restore", "git restore -- {paths}", "danger", "ask", "changes",
       ("Возвращает файлы в рабочей папке к виду из индекса. Незакоммиченные правки этих файлов пропадут.",
        "Отменить нельзя: этих правок нет ни в одном коммите."),
       ("Returns the files in the working folder to what the index holds. Their uncommitted edits are lost.",
        "Cannot be undone: those edits are in no commit."),
       old="Quick → git restore --"),
    _e("commit", 'git commit -m "{message}"', "local", "run", "changes",
       ("Записывает в историю всё, что лежит в индексе, одним снимком с сообщением.",
        "Отменить последний: git reset --soft HEAD~1 (файлы вернутся в индекс)."),
       ("Writes everything in the index into the history as one snapshot with a message.",
        "Undo the last one: git reset --soft HEAD~1 (the files go back to the index)."),
       old="Basket → git commit -m", tags=("profile",)),
    _e("commit_only", 'git commit --only -m "{message}" -- {paths}', "local", "run", "changes",
       ("Коммит только отмеченных файлов, что бы ни лежало в индексе.",
        "Отменить: git reset --soft HEAD~1"),
       ("A commit of the marked files only, whatever else the index holds.",
        "Undo: git reset --soft HEAD~1"),
       old="Basket → git commit --only -- basket", tags=("profile",)),
    _e("amend", 'git commit --amend -m "{message}"', "danger", "ask", "changes",
       ("Переписывает последний коммит: новое сообщение и всё, что сейчас в индексе. Если коммит уже отправлен — история разойдётся с remote.",
        "Отменить: git reset --soft HEAD@{1}"),
       ("Rewrites the last commit: a new message and whatever the index holds now. If the commit was pushed, the history parts from the remote.",
        "Undo: git reset --soft HEAD@{1}"),
       tags=("new",)),
    _e("tag", 'git tag -a {tag} -m "{message}"', "local", "run", "changes",
       ("Ставит именную метку версии на текущий коммит. Push с --follow-tags отправит её вместе с веткой.",
        "Отменить: git tag -d ‹тег›"),
       ("Puts a named version mark on the current commit. A push with --follow-tags sends it with the branch.",
        "Undo: git tag -d ‹tag›"),
       old="Basket → git tag HEAD; Branch → git tag version"),

    # --- history ---
    _e("log", "git log --oneline --decorate -20", "read", "run", "history",
       ("Последние 20 коммитов по одной строке.", NOTHING_RU),
       ("The last 20 commits, one line each.", NOTHING_EN),
       old="Quick → git log --oneline"),
    _e("graph", "git log --graph --oneline --decorate --all -50", "read", "run", "history",
       ("Граф всех веток: где разошлись и где сошлись.", NOTHING_RU),
       ("The graph of every branch: where they parted and where they met.", NOTHING_EN),
       old="Branch → git log --graph; History → Graph"),
    _e("log_file", "git log --date=short --pretty=format:%h%x09%ad%x09%an%x09%s -40 -- {path}", "read", "run", "history",
       ("История одного файла: какие коммиты его меняли.", NOTHING_RU),
       ("The history of one file: which commits changed it.", NOTHING_EN),
       old="History → Selected path"),
    _e("reflog", "git reflog --date=local -20", "read", "run", "history",
       ("Журнал перемещений HEAD — спасательный круг: здесь видны даже «потерянные» коммиты.", NOTHING_RU),
       ("The journal of HEAD moves, the life buoy: even \"lost\" commits show here.", NOTHING_EN),
       old="Quick → git reflog"),
    _e("show", "git show --stat {commit}", "read", "run", "history",
       ("Что изменил коммит: сообщение, автор, файлы.", NOTHING_RU),
       ("What a commit changed: message, author, files.", NOTHING_EN),
       old="Quick → git show --stat"),
    _e("tags", "git tag -n --sort=-creatordate", "read", "run", "history",
       ("Все теги с подписями, новые сверху.", NOTHING_RU),
       ("Every tag with its note, newest first.", NOTHING_EN),
       old="Branch → git tag -n; History → Tags"),
    _e("tag_at", 'git tag -a {tag} {commit} -m "{message}"', "local", "run", "history",
       ("Ставит метку версии на выбранный коммит.", "Отменить: git tag -d ‹тег›"),
       ("Puts a version mark on the chosen commit.", "Undo: git tag -d ‹tag›"),
       tags=("new",)),
    _e("branch_at", "git switch -c {new_branch} {commit}", "local", "run", "history",
       ("Создаёт ветку на выбранном коммите и переходит на неё — так спасают «потерянный» коммит из reflog.",
        "Удалить: git branch -d ‹ветка›"),
       ("Makes a branch at the chosen commit and moves to it: the way to rescue a \"lost\" commit from the reflog.",
        "Delete: git branch -d ‹branch›"),
       tags=("new",)),
    _e("revert", "git revert --no-edit {commit}", "local", "run", "history",
       ("Делает НОВЫЙ коммит, который отменяет изменения выбранного. История не переписывается — годится и для отправленных коммитов.",
        "Отменить: git revert ‹новый коммит›"),
       ("Makes a NEW commit that undoes the chosen one. History is not rewritten, so it suits pushed commits too.",
        "Undo: git revert ‹the new commit›"),
       old="Branch → git revert"),
    _e("cherry_pick", "git cherry-pick {commit}", "local", "run", "history",
       ("Копирует изменения выбранного коммита в текущую ветку новым коммитом.",
        "При конфликте: git cherry-pick --abort"),
       ("Copies the changes of the chosen commit onto the current branch as a new commit.",
        "On a conflict: git cherry-pick --abort"),
       old="Branch → git cherry-pick"),
    _e("reset_soft", "git reset --soft HEAD~1", "danger", "ask", "history",
       ("Убирает последний коммит, а его файлы оставляет в индексе: можно переписать сообщение или разбить коммит.",
        "Отменить: git reset --soft HEAD@{1}"),
       ("Removes the last commit and leaves its files in the index: rewrite the message or split the commit.",
        "Undo: git reset --soft HEAD@{1}"),
       old="Quick → git reset --soft HEAD~1"),
    _e("reset_hard", "git reset --hard {commit}", "danger", "ask", "history",
       ("Переносит ветку на выбранный коммит и стирает ВСЕ незакоммиченные изменения рабочей папки и индекса.",
        "Коммиты найдутся в reflog; незакоммиченное пропадёт навсегда."),
       ("Moves the branch to the chosen commit and wipes EVERY uncommitted change of the working folder and the index.",
        "The commits stay in the reflog; uncommitted work is gone for good."),
       old="Quick → git reset --hard (template, blocked by the danger filter)", tags=("typed",)),

    # --- branches ---
    _e("branches", "git branch -vv", "read", "run", "branches",
       ("Ветки, их пары на сервере и насколько они впереди или позади.", NOTHING_RU),
       ("The branches, their partners on the server and how far ahead or behind they are.", NOTHING_EN),
       old="Branch → git branch -vv"),
    _e("switch", "git switch {branch}", "local", "run", "branches",
       ("Переключает рабочую папку на другую ветку. Незакоммиченные правки Git перенесёт или откажется, если они мешают.",
        "Вернуться: git switch -"),
       ("Switches the working folder to another branch. Uncommitted edits travel along, or Git refuses if they are in the way.",
        "Go back: git switch -"),
       old="Branch → git switch"),
    _e("switch_new", "git switch -c {new_branch}", "local", "run", "branches",
       ("Создаёт ветку от текущего коммита и переходит на неё.", "Удалить: git branch -d ‹ветка›"),
       ("Makes a branch at the current commit and moves to it.", "Delete: git branch -d ‹branch›"),
       old="Branch → git switch -c"),
    _e("switch_back", "git switch -", "local", "run", "branches",
       ("Возвращает на предыдущую ветку.", "Ещё раз — обратно."),
       ("Goes back to the previous branch.", "Once more goes back again."),
       tags=("new",)),
    _e("compare", "git log --left-right --graph --cherry-pick --oneline HEAD...{branch}", "read", "run", "branches",
       ("Какие коммиты есть только в текущей ветке (<) и только в выбранной (>).", NOTHING_RU),
       ("Which commits only the current branch has (<) and which only the chosen one has (>).", NOTHING_EN),
       old="Branch → compare"),
    _e("merge", "git merge --no-ff --no-edit {branch}", "local", "run", "branches",
       ("Сливает выбранную ветку в текущую отдельным коммитом слияния — в графе видно, откуда пришла работа.",
        "При конфликте: git merge --abort"),
       ("Merges the chosen branch into the current one with a merge commit of its own, so the graph shows where the work came from.",
        "On a conflict: git merge --abort"),
       old="Branch → git merge --no-ff"),
    _e("branch_delete", "git branch -d {branch}", "local", "run", "branches",
       ("Удаляет слитую ветку. Неслитую Git удалить не даст.",
        "Вернуть: git switch -c ‹ветка› ‹хэш из reflog›"),
       ("Deletes a merged branch. Git refuses an unmerged one.",
        "Bring back: git switch -c ‹branch› ‹hash from the reflog›"),
       tags=("new",)),
    _e("stash_push", 'git stash push -u -m "{message}"', "local", "run", "branches",
       ("Откладывает все незакоммиченные правки и новые файлы в «ящик» и очищает рабочую папку.",
        "Вернуть: git stash pop"),
       ("Puts every uncommitted edit and new file into the \"drawer\" and leaves the working folder clean.",
        "Bring back: git stash pop"),
       old="Branch → git stash push -u -m"),
    _e("stash_pop", "git stash pop", "local", "run", "branches",
       ("Достаёт последние отложенные правки обратно в рабочую папку.", "Отложить снова: git stash push"),
       ("Takes the last put-aside edits back into the working folder.", "Put aside again: git stash push"),
       old="Branch → git stash pop"),
    _e("stash_list", "git stash list", "read", "run", "branches",
       ("Что лежит в ящике отложенного.", NOTHING_RU),
       ("What lies in the drawer.", NOTHING_EN),
       old="Branch → git stash list"),
    _e("rebase", "git rebase -i {range}", "danger", "template", "branches",
       ("Переписывает цепочку коммитов: склеить, переставить, переименовать. Только для неотправленных коммитов.",
        "Во время: git rebase --abort; после: через reflog."),
       ("Rewrites a chain of commits: squash, reorder, reword. Only for commits not yet pushed.",
        "During it: git rebase --abort; after it: through the reflog."),
       old="Branch → git rebase -i"),
    _e("merge_abort", "git merge --abort", "local", "run", "branches",
       ("Прерывает слияние с конфликтами и возвращает всё как было до него.", "—"),
       ("Stops a merge with conflicts and puts everything back as it was before it.", "—"),
       old="Branch → git merge --abort"),
    _e("cherry_pick_abort", "git cherry-pick --abort", "local", "run", "branches",
       ("Прерывает перенос коммита с конфликтами и возвращает всё как было до него.", "—"),
       ("Stops a cherry-pick with conflicts and puts everything back as it was before it.", "—"),
       old="Branch → git cherry-pick --abort"),

    # --- sync ---
    _e("fetch", "git fetch --all --prune", "net", "run", "sync",
       ("Скачивает новости со всех remote, не трогая ваши ветки и файлы. Самая безопасная сетевая команда.",
        "Ничего вашего не меняет."),
       ("Downloads the news of every remote without touching your branches and files. The safest network command.",
        "Changes nothing of yours."),
       old="Branch/Remote → git fetch --all --prune"),
    _e("fetch_remote", "git fetch --prune {remote}", "net", "run", "sync",
       ("Узнаёт, что нового на одном сервере, не трогая ваши ветки и файлы.",
        "Ничего вашего не меняет."),
       ("Learns what is new on one server without touching your branches and files.",
        "Changes nothing of yours."),
       tags=("each_remote",)),
    _e("pull", "git pull --ff-only {remote} {branch}", "net", "run", "sync",
       ("Забирает новые коммиты с сервера, только если их можно просто дописать сверху, без слияния.",
        "Откажет, если ветки разошлись: тогда — ВЕТКИ, слияние."),
       ("Takes new commits from the server only when they can simply be added on top, without a merge.",
        "Refuses when the branches have parted: then BRANCHES, merge."),
       old="Remote → git pull --ff-only"),
    _e("push", "git push --follow-tags {remote} {branch}", "net", "run", "sync",
       ("Отправляет коммиты текущей ветки и теги на сервер, в её пару. Если имена разные, команда называет обе: "
        "‹ветка›:‹пара›.",
        "Отправленное отменяют новым коммитом (revert), а не переписыванием."),
       ("Sends the commits of the current branch and the tags to the server, into its pair. When the names differ, the "
        "command names both: ‹branch›:‹pair›.",
        "What was pushed is undone by a new commit (revert), not by rewriting."),
       old="Remote → git push origin"),
    _e("push_upstream", "git push -u {remote} {branch}", "net", "run", "sync",
       ("Отправляет новую ветку и связывает её с парой на сервере: дальше push и pull без имён.",
        "Удалить на сервере: git push ‹remote› --delete ‹ветка›"),
       ("Sends a new branch and ties it to its partner on the server: push and pull need no names after that.",
        "Delete on the server: git push ‹remote› --delete ‹branch›"),
       tags=("new",)),
    _e("push_all", "git push --follow-tags {remote} {branch}", "net", "run", "sync",
       ("Отправляет ветку и теги по очереди во все remote репозитория.", "—"),
       ("Sends the branch and tags to every remote of the repository, one after another.", "—"),
       old="Remote → git push all remotes", tags=("each_remote",)),
    _e("remotes", "git remote -v", "read", "run", "sync",
       ("Куда репозиторий умеет отправлять и откуда забирать.", NOTHING_RU),
       ("Where the repository can push to and fetch from.", NOTHING_EN),
       old="Remote → git remote -v"),
    _e("remote_add", "git remote add {remote} {url}", "local", "run", "sync",
       ("Прописывает в репозиторий remote из сохранённого списка.", "Убрать: git remote remove ‹имя›"),
       ("Writes a remote of the saved list into the repository.", "Remove: git remote remove ‹name›"),
       old="Remote → apply remotes.json", tags=("remotes_json",)),
    _e("remote_set_url", "git remote set-url {remote} {url}", "local", "run", "sync",
       ("Меняет адрес remote, который уже есть в репозитории.", "Вернуть: git remote set-url ‹имя› ‹прежний адрес›"),
       ("Changes the address of a remote the repository already has.", "Back: git remote set-url ‹name› ‹old address›"),
       old="Remote → apply remotes.json", tags=("remotes_json",)),
    _e("origin_push_url", "git remote set-url --add --push {remote} {url}", "local", "run", "sync",
       ("Один remote, несколько адресов отправки: забирать из одного, отправлять в несколько зеркал.",
        "Убрать: git remote set-url --delete --push ‹remote› ‹адрес›"),
       ("One remote, several push addresses: fetch from one, push to several mirrors.",
        "Remove: git remote set-url --delete --push ‹remote› ‹address›"),
       old="Remote → origin push URLs"),
    _e("clone", "git clone {url} {dest}", "net", "run", "projects",
       ("Скачивает репозиторий целиком в новую папку.", "Удалить папку."),
       ("Downloads a repository whole into a new folder.", "Delete the folder."),
       old="SOURCE ACTIONS → Clone Source; Remote → clone"),
    _e("ssh_github", "ssh -T -o BatchMode=yes git@github.com", "net", "run", "sync",
       ("Проверяет, пускает ли GitHub по вашему SSH-ключу.", NOTHING_RU),
       ("Checks whether GitHub lets you in by your SSH key.", NOTHING_EN),
       old="Remote → ssh -T GitHub"),
    _e("ssh_gitlab", "ssh -T -o BatchMode=yes git@gitlab.com", "net", "run", "sync",
       ("Проверяет, пускает ли GitLab по вашему SSH-ключу.", NOTHING_RU),
       ("Checks whether GitLab lets you in by your SSH key.", NOTHING_EN),
       old="Remote → ssh -T GitLab"),
    _e("gh_runs", "gh run list --limit 15", "net", "run", "sync",
       ("Последние прогоны GitHub Actions.", NOTHING_RU),
       ("The last runs of GitHub Actions.", NOTHING_EN),
       old="Quick → gh run list"),
    _e("gh_watch", "gh run watch", "net", "run", "sync",
       ("Следит за идущим прогоном GitHub Actions до конца.", NOTHING_RU),
       ("Follows the running GitHub Actions run to its end.", NOTHING_EN),
       old="Quick → gh run watch"),
    _e("glab_ci", "glab ci status", "net", "run", "sync",
       ("Состояние конвейера GitLab CI.", NOTHING_RU),
       ("The state of the GitLab CI pipeline.", NOTHING_EN),
       old="Quick → glab ci status"),

    # --- service ---
    _e("init", "git init -b {branch}", "local", "run", "service",
       ("Создаёт пустой репозиторий (папку .git) в выбранном слое; первая ветка — ветка проекта из реестра, обычно main.",
        "Удалить папку .git."),
       ("Makes an empty repository (the .git folder) in the chosen layer; its first branch is the project's branch of the "
        "registry, main as a rule.", "Delete the .git folder."),
       old="Quick → git init"),
    _e("root", "git rev-parse --show-toplevel", "read", "run", "service",
       ("Корень репозитория, в котором идут команды.", NOTHING_RU),
       ("The root of the repository the commands run in.", NOTHING_EN),
       old="Quick → git root"),
    _e("bundle", "git bundle create {bundle} {branch} --tags", "local", "run", "service",
       ("Вся история ветки и теги одним файлом — резерв без сервера. Поднимается командой git clone ‹файл›.",
        "Удалить файл."),
       ("The whole history of the branch and its tags in one file: a backup without a server. Restored by git clone ‹file›.",
        "Delete the file."),
       old="Quick → git bundle create"),
    _e("clean_preview", "git clean -nd", "read", "run", "service",
       ("Показывает, какие неотслеживаемые файлы удалил бы git clean. Сам ничего не удаляет.", NOTHING_RU),
       ("Shows which untracked files git clean would delete. Deletes nothing itself.", NOTHING_EN),
       old="Quick → git clean preview"),
    _e("gc", "git gc", "local", "run", "service",
       ("Уплотняет базу репозитория. Безопасно.", "—"),
       ("Packs the repository database. Safe.", "—"),
       old="Quick → git gc"),
    _e("fsck", "git fsck --full", "read", "run", "service",
       ("Проверяет целостность базы репозитория.", NOTHING_RU),
       ("Checks the integrity of the repository database.", NOTHING_EN),
       old="Quick → git fsck"),
    _e("config_list", "git config --list --show-origin", "read", "run", "service",
       ("Все настройки Git и из какого файла каждая.", NOTHING_RU),
       ("Every Git setting and the file each one comes from.", NOTHING_EN),
       old="Quick → git config list"),
    _e("config_user", "git config --show-origin --get-regexp user\\.", "read", "run", "service",
       ("Под каким именем и почтой будут подписаны коммиты.", NOTHING_RU),
       ("The name and mail your commits will carry.", NOTHING_EN),
       old="Remote → git config user"),
)

BY_ID: dict[str, CanonEntry] = {entry.id: entry for entry in CANON}

RISKS = ("read", "local", "net", "danger")
MODES = ("run", "ask", "template")
SECTIONS = ("changes", "history", "branches", "sync", "projects", "service")


def entry(canon_id: str) -> CanonEntry:
    return BY_ID[canon_id]


def as_json() -> list[dict[str, object]]:
    """The table for the window (`hub_cli canon`)."""
    return [
        {
            "id": item.id,
            "args": list(item.args),
            "display": item.display(),
            "short": item.short,
            "places": list(item.places),
            "risk": item.risk,
            "mode": item.mode,
            "section": item.section,
            "ru": {"what": item.ru[0], "undo": item.ru[1]},
            "en": {"what": item.en[0], "undo": item.en[1]},
            "old": item.old,
            "tags": list(item.tags),
        }
        for item in CANON
    ]
