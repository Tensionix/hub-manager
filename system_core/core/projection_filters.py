from __future__ import annotations

# Compatibility module for earlier Hub Manager drafts.
# The canonical ProjectionProfile lives in projection_engine.py in this skeleton.

from .projection_engine import DEFAULT_COMPARE_MODE, ProjectionProfile as _ProjectionProfile


class ProjectionProfile(_ProjectionProfile):
    def __init__(
        self,
        id: str = "inline",
        title: str = "",
        description: str = "",
        compare_mode: str = DEFAULT_COMPARE_MODE,
        mirror: bool = True,
        preserve_empty_dirs: bool = True,
        marker_file: str = ".gitkeep",
        max_file_bytes: int | None = 10 * 1024 * 1024,
        include_globs: list[str] | None = None,
        exclude_globs: list[str] | None = None,
        small_include_globs: list[str] | None = None,
        small_include_max_file_bytes: int | None = None,
        hide_dirs: list[str] | None = None,
        exclude_dir_contents: list[str] | None = None,
        forbidden_dirs: list[str] | None = None,
        protected_target_globs: list[str] | None = None,
    ) -> None:
        super().__init__(
            id=id,
            title=title,
            description=description,
            compare_mode=compare_mode,
            mirror=mirror,
            preserve_empty_dirs=preserve_empty_dirs,
            marker_file=marker_file,
            max_file_bytes=max_file_bytes,
            include_globs=include_globs or ["*.md", "*.txt", "*.py", "*.json", "*.yaml", "*.yml", "*.cmd", "*.ps1"],
            exclude_globs=exclude_globs or ["*.log", "*.tmp", "*.zip", "*.exe", "*.dll", "*.whl"],
            small_include_globs=small_include_globs or [],
            small_include_max_file_bytes=small_include_max_file_bytes,
            hide_dirs=hide_dirs or [".git", "__pycache__", ".venv", "venv", "node_modules"],
            exclude_dir_contents=exclude_dir_contents or ["logs", "output", "runtime", "wheelhouse", "backup", "temp", "tmp"],
            forbidden_dirs=forbidden_dirs or ["_pwsh_tmp"],
            protected_target_globs=protected_target_globs or [".git/**", ".hub_cache/**", ".obsidian/**", ".logseq/**"],
        )
