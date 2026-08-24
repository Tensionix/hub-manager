from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


STATUS_DOT_COLORS = {
    "modified": "#e0a05f",
    "untracked": "#7aa2f7",
    "staged": "#92c36e",
    "conflict": "#ef6f6c",
}
STATUS_COUNT_LABELS = {
    "conflict": "C",
    "staged": "S",
    "modified": "M",
    "untracked": "U",
}
EDITOR_PREVIEW_EXTENSIONS = {".md", ".markdown", ".txt", ".rst"}


@dataclass
class TreeNode:
    id: str
    label: str
    path: str
    kind: str
    status: str = "clean"
    children: list["TreeNode"] = field(default_factory=list)
    lazy: bool = False
    status_counts: dict[str, int] = field(default_factory=dict)

    def to_nicegui(self) -> dict:
        item = {"id": self.id, "label": self.label, "path": self.path, "kind": self.kind, "status": self.status}
        if self.kind == "file" and Path(self.label).suffix.lower() in EDITOR_PREVIEW_EXTENSIONS:
            item["editorPreview"] = True
        if self.status != "clean":
            item["diffPreview"] = True
        if self.kind == "dir":
            item["kindIcon"] = "folder"
        if self.status_counts:
            item["statusCounts"] = self.status_counts
            item["statusSummary"] = " ".join(
                f"{label}{self.status_counts[status]}"
                for status, label in STATUS_COUNT_LABELS.items()
                if self.status_counts.get(status, 0) > 0
            )
        if self.lazy:
            item["isLazy"] = True
        if self.status in STATUS_DOT_COLORS:
            item["icon"] = "circle"
            item["iconColor"] = STATUS_DOT_COLORS[self.status]
        if self.children:
            item["children"] = [child.to_nicegui() for child in self.children]
        return item


def _status_for_path(rel: str, status_map: dict[str, str]) -> str:
    if rel in status_map:
        return status_map[rel]
    prefix = rel.rstrip("/") + "/" if rel else ""
    child_statuses = {status for path, status in status_map.items() if path.startswith(prefix)}
    if "conflict" in child_statuses:
        return "conflict"
    if "staged" in child_statuses:
        return "staged"
    if "modified" in child_statuses:
        return "modified"
    if "untracked" in child_statuses:
        return "untracked"
    return "clean"


def _status_counts_for_path(rel: str, status_map: dict[str, str]) -> dict[str, int]:
    prefix = rel.rstrip("/") + "/" if rel else ""
    counts = {status: 0 for status in STATUS_COUNT_LABELS}
    for path, status in status_map.items():
        if rel and path != rel and not path.startswith(prefix):
            continue
        if status in counts:
            counts[status] += 1
    return {status: count for status, count in counts.items() if count > 0}


def _visible_entries(path: Path, *, show_hidden: bool) -> list[Path]:
    try:
        entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError:
        return []
    if show_hidden:
        return entries
    allowed_hidden_files = {".gitignore", ".gitattributes", ".editorconfig"}
    return [
        entry
        for entry in entries
        if not entry.name.startswith(".") or (entry.is_file() and entry.name in allowed_hidden_files)
    ]


def build_tree(root: Path, *, status_map: dict[str, str] | None = None, max_depth: int = 2, show_hidden: bool = False) -> list[dict]:
    root = root.expanduser()
    status_map = status_map or {}
    if not root.exists() or not root.is_dir():
        return []

    def visit(path: Path, depth: int) -> TreeNode:
        rel = "" if path == root else path.relative_to(root).as_posix()
        status = _status_for_path(rel, status_map)
        node = TreeNode(
            id=rel or ".",
            label=path.name or str(root),
            path=rel,
            kind="dir",
            status=status,
            status_counts=_status_counts_for_path(rel, status_map),
        )
        if depth >= max_depth:
            return node
        for entry in _visible_entries(path, show_hidden=show_hidden):
            child_rel = entry.relative_to(root).as_posix()
            child_status = _status_for_path(child_rel, status_map)
            if entry.is_dir():
                node.children.append(visit(entry, depth + 1))
            else:
                node.children.append(TreeNode(id=child_rel, label=entry.name, path=child_rel, kind="file", status=child_status))
        return node

    return [visit(root, 0).to_nicegui()]


def build_lazy_tree(
    root: Path,
    *,
    expanded: set[str] | None = None,
    status_map: dict[str, str] | None = None,
    show_hidden: bool = False,
) -> list[dict]:
    root = root.expanduser()
    expanded = expanded or set()
    status_map = status_map or {}
    if not root.exists() or not root.is_dir():
        return []

    def visit_dir(path: Path, *, force_load: bool) -> TreeNode:
        rel = "" if path == root else path.relative_to(root).as_posix()
        entries = _visible_entries(path, show_hidden=show_hidden)
        node = TreeNode(
            id=rel or ".",
            label=path.name or str(root),
            path=rel,
            kind="dir",
            status=_status_for_path(rel, status_map),
            status_counts=_status_counts_for_path(rel, status_map),
            lazy=bool(entries) and not force_load,
        )
        if not force_load:
            if entries:
                placeholder_id = f"{rel}/.__lazy__" if rel else ".__lazy__"
                node.children.append(TreeNode(id=placeholder_id, label="...", path=rel, kind="placeholder"))
            return node
        for entry in entries:
            child_rel = entry.relative_to(root).as_posix()
            child_status = _status_for_path(child_rel, status_map)
            if entry.is_dir():
                node.children.append(visit_dir(entry, force_load=child_rel in expanded))
            else:
                node.children.append(TreeNode(id=child_rel, label=entry.name, path=child_rel, kind="file", status=child_status))
        return node

    return [visit_dir(root, force_load=True).to_nicegui()]


def build_search_tree(
    root: Path,
    *,
    query: str,
    status_map: dict[str, str] | None = None,
    show_hidden: bool = False,
    hide_clean: bool = False,
) -> list[dict]:
    root = root.expanduser()
    query_normalized = query.strip().lower()
    status_map = status_map or {}
    if not query_normalized or not root.exists() or not root.is_dir():
        return []

    def matches_text(label: str, rel: str) -> bool:
        return query_normalized in label.lower() or query_normalized in rel.lower()

    def visit_file(path: Path) -> TreeNode | None:
        rel = path.relative_to(root).as_posix()
        status = _status_for_path(rel, status_map)
        if hide_clean and status == "clean":
            return None
        if not matches_text(path.name, rel):
            return None
        return TreeNode(id=rel, label=path.name, path=rel, kind="file", status=status)

    def visit_dir(path: Path) -> TreeNode | None:
        rel = "" if path == root else path.relative_to(root).as_posix()
        children: list[TreeNode] = []
        for entry in _visible_entries(path, show_hidden=show_hidden):
            child = visit_dir(entry) if entry.is_dir() else visit_file(entry)
            if child:
                children.append(child)
        status = _status_for_path(rel, status_map)
        has_match = matches_text(path.name or str(root), rel)
        matches_status = not hide_clean or status != "clean" or bool(children)
        if not children and not (has_match and matches_status):
            return None
        return TreeNode(
            id=rel or ".",
            label=path.name or str(root),
            path=rel,
            kind="dir",
            status=status,
            children=children,
            status_counts=_status_counts_for_path(rel, status_map),
        )

    node = visit_dir(root)
    return [node.to_nicegui()] if node else []


def _sort_children(node: TreeNode) -> None:
    node.children.sort(key=lambda child: (child.kind != "dir", child.label.lower()))
    for child in node.children:
        _sort_children(child)


def changed_tree(status_map: dict[str, str]) -> list[dict]:
    root = TreeNode(
        id=".",
        label="Changed",
        path="",
        kind="dir",
        status=_status_for_path("", status_map),
        status_counts=_status_counts_for_path("", status_map),
    )
    directories: dict[str, TreeNode] = {"": root}

    for path, status in sorted(status_map.items()):
        parts = [part for part in path.replace("\\", "/").split("/") if part]
        if not parts:
            continue
        parent_rel = ""
        for index, part in enumerate(parts[:-1]):
            dir_rel = "/".join(parts[: index + 1])
            if dir_rel not in directories:
                parent = directories[parent_rel]
                directory = TreeNode(
                    id=dir_rel,
                    label=part,
                    path=dir_rel,
                    kind="dir",
                    status=_status_for_path(dir_rel, status_map),
                    status_counts=_status_counts_for_path(dir_rel, status_map),
                )
                parent.children.append(directory)
                directories[dir_rel] = directory
            parent_rel = dir_rel
        parent = directories[parent_rel]
        parent.children.append(TreeNode(id=path, label=parts[-1], path=path, kind="file", status=status))

    _sort_children(root)
    return [root.to_nicegui()]
