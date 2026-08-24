from __future__ import annotations

from pathlib import Path

from system_core.core.file_tree_model import build_lazy_tree, build_search_tree, build_tree, changed_tree


def test_build_tree_uses_status_dot_fields_without_status_suffix(tmp_path: Path) -> None:
    root = tmp_path / "project"
    source_dir = root / "system_core"
    source_dir.mkdir(parents=True)
    (source_dir / "main.py").write_text("print('ok')\n", encoding="utf-8")

    nodes = build_tree(root, status_map={"system_core/main.py": "modified"})
    system_node = nodes[0]["children"][0]
    file_node = system_node["children"][0]

    assert system_node["status"] == "modified"
    assert system_node["kindIcon"] == "folder"
    assert system_node["icon"] == "circle"
    assert system_node["iconColor"]
    assert system_node["statusCounts"] == {"modified": 1}
    assert system_node["statusSummary"] == "M1"
    assert file_node["label"] == "main.py"
    assert "[modified]" not in file_node["label"]


def test_changed_tree_keeps_status_as_dot_metadata() -> None:
    nodes = changed_tree({"README.md": "staged"})
    file_node = nodes[0]["children"][0]

    assert file_node["label"] == "README.md"
    assert file_node["status"] == "staged"
    assert file_node["editorPreview"] is True
    assert file_node["diffPreview"] is True
    assert file_node["icon"] == "circle"
    assert file_node["iconColor"]


def test_changed_tree_groups_changed_files_by_folder() -> None:
    nodes = changed_tree({"system_core/app/main.py": "modified", "README.md": "staged"})
    root_children = nodes[0]["children"]
    system_node = root_children[0]
    readme_node = root_children[1]
    app_node = system_node["children"][0]
    file_node = app_node["children"][0]

    assert nodes[0]["statusCounts"] == {"staged": 1, "modified": 1}
    assert nodes[0]["statusSummary"] == "S1 M1"
    assert system_node["label"] == "system_core"
    assert system_node["status"] == "modified"
    assert system_node["kindIcon"] == "folder"
    assert system_node["statusCounts"] == {"modified": 1}
    assert system_node["statusSummary"] == "M1"
    assert app_node["label"] == "app"
    assert file_node["label"] == "main.py"
    assert file_node["path"] == "system_core/app/main.py"
    assert readme_node["label"] == "README.md"
    assert readme_node["status"] == "staged"


def test_build_lazy_tree_loads_folder_children_only_when_expanded(tmp_path: Path) -> None:
    root = tmp_path / "project"
    nested = root / "system_core" / "app"
    nested.mkdir(parents=True)
    (nested / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (root / "README.md").write_text("# demo\n", encoding="utf-8")

    collapsed = build_lazy_tree(root)
    system_node = next(node for node in collapsed[0]["children"] if node["label"] == "system_core")
    readme_node = next(node for node in collapsed[0]["children"] if node["label"] == "README.md")

    assert system_node["kind"] == "dir"
    assert system_node["isLazy"] is True
    assert system_node["children"][0]["kind"] == "placeholder"
    assert system_node["children"][0]["label"] == "..."
    assert readme_node["kind"] == "file"
    assert readme_node["editorPreview"] is True

    expanded = build_lazy_tree(root, expanded={"system_core"})
    system_node = next(node for node in expanded[0]["children"] if node["label"] == "system_core")

    assert "children" in system_node
    assert system_node["children"][0]["label"] == "app"
    assert system_node["children"][0]["isLazy"] is True


def test_build_lazy_tree_marks_editor_and_diff_preview_nodes(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "README.md").write_text("# demo\n", encoding="utf-8")
    (root / "app.py").write_text("print('ok')\n", encoding="utf-8")

    nodes = build_lazy_tree(root, status_map={"README.md": "modified", "app.py": "modified"})
    children = {node["label"]: node for node in nodes[0]["children"]}

    assert children["README.md"]["editorPreview"] is True
    assert children["README.md"]["diffPreview"] is True
    assert "editorPreview" not in children["app.py"]
    assert children["app.py"]["diffPreview"] is True


def test_build_lazy_tree_keeps_status_metadata_for_unloaded_folders(tmp_path: Path) -> None:
    root = tmp_path / "project"
    nested = root / "system_core" / "app"
    nested.mkdir(parents=True)
    (nested / "main.py").write_text("print('ok')\n", encoding="utf-8")

    nodes = build_lazy_tree(root, status_map={"system_core/app/main.py": "modified"})
    system_node = nodes[0]["children"][0]

    assert system_node["status"] == "modified"
    assert system_node["icon"] == "circle"
    assert system_node["iconColor"]
    assert system_node["statusSummary"] == "M1"
    assert system_node["isLazy"] is True
    assert system_node["children"][0]["kind"] == "placeholder"


def test_build_search_tree_finds_matches_below_collapsed_lazy_level(tmp_path: Path) -> None:
    root = tmp_path / "project"
    nested = root / "docs" / "manual"
    nested.mkdir(parents=True)
    (nested / "README.md").write_text("# demo\n", encoding="utf-8")
    (root / "main.py").write_text("print('ok')\n", encoding="utf-8")

    nodes = build_search_tree(root, query="readme")
    docs_node = nodes[0]["children"][0]
    manual_node = docs_node["children"][0]
    readme_node = manual_node["children"][0]

    assert docs_node["label"] == "docs"
    assert manual_node["label"] == "manual"
    assert readme_node["label"] == "README.md"
    assert readme_node["path"] == "docs/manual/README.md"
