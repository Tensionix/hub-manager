from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import argparse
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nicegui import ui  # type: ignore

from system_core.core.file_tree_model import build_lazy_tree, build_search_tree, changed_tree
from system_core.core.git_engine import (
    apply_remotes_from_config as git_apply_remotes_from_config,
    build_version_tag,
    configure_origin_push_urls_from_config as git_configure_origin_push_urls_from_config,
    commit as git_commit,
    commit_paths as git_commit_paths,
    create_annotated_tag as git_create_annotated_tag,
    diff as git_diff,
    fetch_all as git_fetch_all,
    format_semver,
    git as git_run,
    remotes as git_remotes,
    next_version_for_series as git_next_version_for_series,
    parse_semver,
    push_all_remotes as git_push_all_remotes,
    stage as git_stage,
    status as git_status,
    unstage as git_unstage,
    clone as git_clone,
    create_bundle as git_create_bundle,
    directory_name_from_url as git_directory_name_from_url,
    pull_ff_only as git_pull_ff_only,
    validate_remote_url as git_validate_remote_url,
)
from system_core.core.copy_engine import hash_file_blake3
from system_core.core.json_utils import load_json, load_json_safe, save_json
from system_core.core.mask_engine import include_file, norm_rel
from system_core.core.project_importer import merge_project_import, scan_project_folder
from system_core.core.project_registry import ProjectEntry, load_project_registry
from system_core.core.projection_engine import (
    apply_projection_plan,
    get_projection_profile,
    plan_projection,
    verify_projection_mirror,
    write_report,
)
from system_core.core.paths import get_project_paths
from system_core.core.auth_doctor import (
    has_embedded_credentials as auth_doctor_has_embedded_credentials,
    run_auth_doctor as run_auth_doctor_core,
)
from system_core.core import forgejo_api, forgejo_service
from system_core.core.safety import scan_safety
from system_core.core.storage_layout import storage_layout_status
from system_core.core.terminal_render import iter_process_output_lines, terminal_html, terminal_lines_html
from system_core.core import external_apps
from system_core.core.safety import is_dangerous_command
from system_core.ui_nicegui.i18n import t
from system_core.ui_nicegui.theme import (
    css_from_tokens,
    load_gui_settings,
    load_theme_tokens,
    save_gui_settings,
    theme_mode,
    theme_options,
)


# Platforms whose server address is fixed, versus instances the user hosts.
CLOUD_PLATFORM_HOSTS = {"github": "github.com", "gitlab": "gitlab.com", "codeberg": "codeberg.org"}
SELF_HOSTED_PLATFORMS = {"forgejo", "gitea", "custom"}
PLATFORM_TITLES = {"github": "GitHub", "gitlab": "GitLab", "codeberg": "Codeberg", "forgejo": "Forgejo", "gitea": "Gitea"}


class UIState:
    def __init__(self) -> None:
        self.paths = get_project_paths()
        self.settings = load_gui_settings()
        self.lang = str(self.settings.get("language", "ru"))
        self.theme = str(self.settings.get("theme", "code_dark"))
        self.header_status_mode = str(self.settings.get("header_status_mode", "labeled"))
        self.registry = load_project_registry()
        self.project: ProjectEntry = self.registry.active_project()
        self.current_plan: dict[str, Any] | None = None
        self.git_status_map: dict[str, str] = {}
        self.git_status_root: Path | None = None
        self.selected_path: str = ""
        self.commit_basket: set[str] = set()
        self.commit_basket_root: Path | None = None
        self.tree_scope: str = "project"
        self.current_tree_root: Path = self.project.source_path
        self.tree_expanded: set[str] = {"."}
        self.location_overrides: dict[str, Path] = {}
        self.editor_path: Path | None = None
        self.diff_text: str = ""
        self.history_text: str = ""
        self.metadata_payload: dict[str, Any] = {}
        self.safety_payload: dict[str, Any] = {}
        self.storage_payload: dict[str, Any] = {}
        self.log_lines: list[str] = []
        self.status: str = ""
        self.source_tree_status: str = ""

    def log(self, line: str) -> None:
        self.log_lines.append(str(line))
        if len(self.log_lines) > 2000:
            self.log_lines = self.log_lines[-2000:]


state = UIState()

PRIMARY_HEADER_STATUS = [
    ("staged", "check_circle", "#1D9E75"),
    ("modified", "edit", "#EF9F27"),
    ("untracked", "fiber_new", "#85B7EB"),
    ("conflict", "warning", "#E24B4A"),
]
FALLBACK_HEADER_STATUS = ("changed", "change_circle", "#888780")
STATUS_LETTERS = {"staged": "S", "modified": "M", "untracked": "U", "conflict": "C", "changed": "G"}
STATUS_MODE_CYCLE = ["labeled", "icons", "letters"]


def tr(key: str, **kwargs: Any) -> str:
    return t(state.lang, key, **kwargs)


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _set_theme(theme_id: Any) -> None:
    selected = str(theme_id or "").strip()
    if not selected:
        return
    state.theme = selected
    state.settings["theme"] = selected
    save_gui_settings(state.settings)
    ui.notify(tr("theme_saved"), type="positive")
    ui.run_javascript("window.location.reload()")


def _toggle_language() -> None:
    state.lang = "en" if state.lang == "ru" else "ru"
    state.settings["language"] = state.lang
    save_gui_settings(state.settings)
    ui.run_javascript("window.location.reload()")


def _powershell_executable() -> str:
    portable = state.paths.system_core / "powershell" / "pwsh.exe"
    if portable.exists():
        return str(portable)
    for name in ("pwsh.exe", "powershell.exe"):
        found = shutil.which(name)
        if found:
            return found
    return "powershell.exe"


def _ps_quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _picker_dpi_prelude() -> list[str]:
    return [
        "Add-Type -AssemblyName System.Windows.Forms",
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8",
        r"""Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

public static class AudionPickerDpi {
    [DllImport("user32.dll")]
    public static extern bool SetProcessDpiAwarenessContext(IntPtr value);

    [DllImport("shcore.dll")]
    public static extern int SetProcessDpiAwareness(int value);

    [DllImport("user32.dll")]
    public static extern bool SetProcessDPIAware();
}
"@""",
        "$dpiSet = $false",
        "try {",
        "  $method = [System.Windows.Forms.Application].GetMethod('SetHighDpiMode')",
        "  $modeType = [System.Windows.Forms.Application].Assembly.GetType('System.Windows.Forms.HighDpiMode')",
        "  if ($method -and $modeType) {",
        "    $mode = [Enum]::Parse($modeType, 'PerMonitorV2')",
        "    $dpiSet = [bool]$method.Invoke($null, @($mode))",
        "  }",
        "} catch {}",
        "if (-not $dpiSet) {",
        "  try { $dpiSet = [AudionPickerDpi]::SetProcessDpiAwarenessContext([IntPtr](-4)) } catch {}",
        "}",
        "if (-not $dpiSet) {",
        "  try { $dpiSet = ([AudionPickerDpi]::SetProcessDpiAwareness(2) -eq 0) } catch {}",
        "}",
        "if (-not $dpiSet) {",
        "  try { $dpiSet = [AudionPickerDpi]::SetProcessDPIAware() } catch {}",
        "}",
        "[System.Windows.Forms.Application]::EnableVisualStyles()",
        "[System.Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)",
    ]


def _pick_directory(initial: Path, title: str) -> Path | None:
    initial = initial.expanduser()
    script = "\n".join(
        _picker_dpi_prelude()
        + [
            "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog",
            f"$dialog.Description = {_ps_quote(title)}",
            "$dialog.ShowNewFolderButton = $true",
            f"$initial = {_ps_quote(str(initial))}",
            "if (Test-Path -LiteralPath $initial) { $dialog.SelectedPath = (Resolve-Path -LiteralPath $initial).Path }",
            "$result = $dialog.ShowDialog()",
            "if ($result -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $dialog.SelectedPath }",
        ]
    )
    result = subprocess.run(
        [_powershell_executable(), "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=None,
        check=False,
    )
    selected = result.stdout.strip().splitlines()
    if result.returncode != 0 or not selected:
        return None
    return Path(selected[-1]).expanduser()


def _pick_file(initial: Path, title: str, filter_text: str = "Executable files (*.exe)|*.exe|All files (*.*)|*.*") -> Path | None:
    initial = initial.expanduser()
    script = "\n".join(
        _picker_dpi_prelude()
        + [
            "$dialog = New-Object System.Windows.Forms.OpenFileDialog",
            f"$dialog.Title = {_ps_quote(title)}",
            f"$dialog.Filter = {_ps_quote(filter_text)}",
            "$dialog.CheckFileExists = $true",
            f"$initial = {_ps_quote(str(initial))}",
            "if (Test-Path -LiteralPath $initial -PathType Leaf) {",
            "  $item = Get-Item -LiteralPath $initial",
            "  $dialog.InitialDirectory = $item.DirectoryName",
            "  $dialog.FileName = $item.Name",
            "} elseif (Test-Path -LiteralPath $initial -PathType Container) {",
            "  $dialog.InitialDirectory = (Resolve-Path -LiteralPath $initial).Path",
            "}",
            "$result = $dialog.ShowDialog()",
            "if ($result -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $dialog.FileName }",
        ]
    )
    result = subprocess.run(
        [_powershell_executable(), "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=None,
        check=False,
    )
    selected = result.stdout.strip().splitlines()
    if result.returncode != 0 or not selected:
        return None
    return Path(selected[-1]).expanduser()


def _splitter_javascript() -> str:
    return """
    (() => {
      if (window.__ahmSplitterCleanup) window.__ahmSplitterCleanup();

      const root = document.querySelector('.ahm-root');
      const main = document.querySelector('.ahm-main');
      if (!root || !main) return;

      const storage = {
        left: 'ahm.left.width.v3',
        right: 'ahm.right.width.v3',
        terminal: 'ahm.terminal.height.v2',
      };
      const min = {
        left: 260,
        middle: 300,
        right: 420,
        main: 330,
        terminal: 180,
      };
      const ratio = { left: 25, middle: 30, right: 45 };
      const splittersWidth = 16;
      const horizontalSplitterHeight = 8;
      const controller = new AbortController();
      const signal = controller.signal;

      const clamp = (value, lower, upper) => Math.max(lower, Math.min(upper, value));
      const storedNumber = (key) => {
        const value = Number.parseFloat(localStorage.getItem(key) || '');
        return Number.isFinite(value) ? value : null;
      };
      const cssNumber = (name, fallback) => {
        const raw = getComputedStyle(root).getPropertyValue(name).trim();
        const value = Number.parseFloat(raw);
        if (Number.isFinite(value) && raw.endsWith('%')) {
          return main.getBoundingClientRect().width * value / 100;
        }
        if (Number.isFinite(value) && raw.endsWith('vw')) {
          return window.innerWidth * value / 100;
        }
        return Number.isFinite(value) ? value : fallback;
      };
      const leftWidth = () => cssNumber('--ahm-left-width', 640);
      const rightWidth = () => cssNumber('--ahm-right-width', 640);
      const terminalHeight = () => cssNumber('--ahm-terminal-height', 228);
      const defaultPanelWidths = () => {
        const mainWidth = main.getBoundingClientRect().width;
        const available = Math.max(min.left + min.middle + min.right, mainWidth - splittersWidth);
        const total = ratio.left + ratio.middle + ratio.right;
        return {
          left: Math.round(available * ratio.left / total),
          right: Math.round(available * ratio.right / total),
        };
      };
      const setPanelPair = (leftValue, rightValue, persist = true) => {
        const mainWidth = main.getBoundingClientRect().width;
        const available = Math.max(min.left + min.middle + min.right, mainWidth - splittersWidth);
        const maxLeft = Math.max(min.left, available - min.middle - min.right);
        const nextLeft = Math.round(clamp(leftValue, min.left, maxLeft));
        const maxRight = Math.max(min.right, available - min.middle - nextLeft);
        const nextRight = Math.round(clamp(rightValue, min.right, maxRight));
        root.style.setProperty('--ahm-left-width', `${nextLeft}px`);
        root.style.setProperty('--ahm-right-width', `${nextRight}px`);
        if (persist) {
          localStorage.setItem(storage.left, String(nextLeft));
          localStorage.setItem(storage.right, String(nextRight));
        }
      };

      const setLeft = (value, persist = true) => {
        const mainWidth = main.getBoundingClientRect().width;
        const max = Math.max(min.left, mainWidth - splittersWidth - rightWidth() - min.middle);
        const next = Math.round(clamp(value, min.left, max));
        root.style.setProperty('--ahm-left-width', `${next}px`);
        if (persist) localStorage.setItem(storage.left, String(next));
      };
      const setRight = (value, persist = true) => {
        const mainWidth = main.getBoundingClientRect().width;
        const max = Math.max(min.right, mainWidth - splittersWidth - leftWidth() - min.middle);
        const next = Math.round(clamp(value, min.right, max));
        root.style.setProperty('--ahm-right-width', `${next}px`);
        if (persist) localStorage.setItem(storage.right, String(next));
      };
      const setTerminal = (value, persist = true) => {
        const rootHeight = root.getBoundingClientRect().height;
        const max = Math.max(min.terminal, rootHeight - horizontalSplitterHeight - min.main);
        const next = Math.round(clamp(value, min.terminal, max));
        root.style.setProperty('--ahm-terminal-height', `${next}px`);
        if (persist) localStorage.setItem(storage.terminal, String(next));
      };
      const applyStoredSizes = () => {
        const defaults = defaultPanelWidths();
        setPanelPair(storedNumber(storage.left) ?? defaults.left, storedNumber(storage.right) ?? defaults.right, false);
        setTerminal(storedNumber(storage.terminal) ?? terminalHeight(), false);
      };
      const startDrag = (kind, event) => {
        event.preventDefault();
        const startX = event.clientX;
        const startY = event.clientY;
        const startLeft = leftWidth();
        const startRight = rightWidth();
        const startTerminal = terminalHeight();
        document.body.classList.add('ahm-resizing');

        const onMove = (moveEvent) => {
          const dx = moveEvent.clientX - startX;
          const dy = moveEvent.clientY - startY;
          if (kind === 'left') setLeft(startLeft + dx);
          if (kind === 'right') setRight(startRight - dx);
          if (kind === 'terminal') setTerminal(startTerminal - dy);
        };
        const onUp = () => {
          document.body.classList.remove('ahm-resizing');
          window.removeEventListener('pointermove', onMove);
          window.removeEventListener('pointerup', onUp);
          window.removeEventListener('pointercancel', onUp);
        };
        window.addEventListener('pointermove', onMove);
        window.addEventListener('pointerup', onUp);
        window.addEventListener('pointercancel', onUp);
      };

      document.querySelector('.ahm-splitter-left')?.addEventListener('pointerdown', (event) => startDrag('left', event), { signal });
      document.querySelector('.ahm-splitter-right')?.addEventListener('pointerdown', (event) => startDrag('right', event), { signal });
      document.querySelector('.ahm-splitter-terminal')?.addEventListener('pointerdown', (event) => startDrag('terminal', event), { signal });
      window.addEventListener('resize', applyStoredSizes, { signal });
      window.__ahmSplitterCleanup = () => controller.abort();
      applyStoredSizes();
    })();
    """


def _build_ui() -> None:
    tokens = load_theme_tokens(state.theme)
    ui.add_head_html(css_from_tokens(tokens))
    ui.page_title(tr("title"))
    if theme_mode(state.theme) == "dark":
        ui.dark_mode().enable()
    else:
        ui.dark_mode().disable()

    project_options = {project.id: project.title for project in state.registry.projects}
    scope_buttons: dict[str, Any] = {}
    # The Remote pane uses button rows instead of dropdowns; these hold the current choice.
    remote_platform_buttons: dict[str, Any] = {}
    remote_url_type_buttons: dict[str, Any] = {}
    forgejo_visibility_buttons: dict[str, Any] = {}
    remote_choice = {"platform": "github", "url_type": "ssh", "visibility": "private"}
    forgejo_stored_state: dict[str, Any] = {"checked": False, "present": False, "login": ""}
    # Hand-edited config must never keep the window from opening; collect the
    # problems and report them in the terminal dock once the UI exists.
    config_errors: list[str] = []
    if state.registry.load_error:
        config_errors.append(state.registry.load_error)
    command_cache, command_cache_error = load_json_safe(state.paths.config / "command_cache.json", {"history": [], "pinned": []})
    if command_cache_error:
        config_errors.append(command_cache_error)
    if not isinstance(command_cache, dict):
        command_cache = {"history": [], "pinned": []}
    remote_field_cache_defaults: dict[str, list[str]] = {"names": [], "owners": [], "repos": [], "urls": [], "hosts": []}
    remote_field_cache, remote_cache_error = load_json_safe(state.paths.config / "remote_field_cache.json", dict(remote_field_cache_defaults))
    if remote_cache_error:
        config_errors.append(remote_cache_error)
    if not isinstance(remote_field_cache, dict):
        remote_field_cache = dict(remote_field_cache_defaults)

    def command_tone(command: str) -> str:
        lowered = command.lower()
        if "reset --hard" in lowered or "rebase -i" in lowered or "push --all" in lowered or "restore -- <path>" in lowered:
            return "danger"
        if "reset --soft" in lowered or "clean" in lowered or "gc" in lowered or "fsck" in lowered or "cherry-pick" in lowered or "stash pop" in lowered:
            return "caution"
        if any(token in lowered for token in ("status", "diff", "log", "show", "blame", "remote -v", "branch -vv")):
            return "read"
        return "safe"

    branch_compare_command = "git log --left-right --graph --cherry-pick --oneline HEAD..."

    def command_display_label(command: str) -> str:
        if command == branch_compare_command:
            return "git log\n--left-right --graph --cherry-pick --oneline HEAD..."
        return command

    def delayed_tooltip(text: str) -> Any:
        return ui.tooltip(text).props("delay=1200 hide-delay=80 transition-show=fade transition-hide=fade transition-duration=80")

    def attach_tooltip(element: Any, tooltip_key: str) -> Any:
        with element:
            delayed_tooltip(tr(tooltip_key))
        return element

    def tooltipped_button(
        label: str | None = None,
        *,
        icon: str | None = None,
        on_click: Any,
        tooltip_key: str,
        props: str = "dense flat no-wrap",
        classes: str = "audion-action rounded-lg",
    ) -> Any:
        button = ui.button(label, icon=icon, on_click=on_click) if label is not None else ui.button(icon=icon, on_click=on_click)
        button.props(props).classes(classes)
        return attach_tooltip(button, tooltip_key)

    def inspector_tab(label_key: str, icon: str, tooltip_key: str) -> Any:
        tab = ui.tab(tr(label_key), label=tr(label_key), icon=icon).props("inline-label")
        return attach_tooltip(tab, tooltip_key)

    def command_button(icon: str, command: str, on_click: Any, tooltip_key: str, *, primary: bool = False) -> Any:
        classes = f"audion-action ahm-op-button ahm-command-button ahm-command-{command_tone(command)} rounded-lg"
        wrap_flags = command == branch_compare_command
        if wrap_flags:
            classes = f"{classes} ahm-command-button-wrap-flags"
        if primary:
            classes = f"{classes} audion-primary-action"
        props = "dense flat" if wrap_flags else "dense flat no-wrap"
        button = ui.button(command_display_label(command), icon=icon, on_click=on_click).props(props).classes(classes)
        return attach_tooltip(button, tooltip_key)

    def command_value_controls(
        icon: str,
        command: str,
        tooltip_key: str,
        *,
        value_name: str,
        placeholder: str,
        default: str = "",
        empty_value: str | None = None,
        quote_value: bool = False,
        primary: bool = False,
        wide: bool = False,
        separator: str = " ",
    ) -> Any:
        value_input = None

        def _queue_from_value() -> None:
            value = str(value_input.value if value_input is not None else "").strip()
            if not value:
                if empty_value is not None:
                    value = empty_value
                else:
                    append_terminal(tr("command_value_required", value=value_name, command=command))
                    set_status(tr("status_blocked"), "blocked")
                    try:
                        value_input.run_method("focus")
                    except Exception:
                        pass
                    return
            if quote_value:
                value = quote_git_path(value)
            queue_git_command(f"{command}{separator}{value}")

        button = command_button(icon, command, _queue_from_value, tooltip_key, primary=primary)
        value_input = ui.input(value=default, placeholder=placeholder).props("dense outlined").classes("audion-input ahm-command-value-input")
        if wide:
            button.classes(add="ahm-command-value-wide-button")
            value_input.classes(add="ahm-command-value-wide-input")
        return value_input

    def cache_icon_button(icon: str, on_click: Any, tooltip_key: str) -> Any:
        button = ui.button(icon=icon, on_click=on_click).props("dense flat").classes("audion-action ahm-cache-icon-button rounded-lg")
        return attach_tooltip(button, tooltip_key)

    def pane_icon_button(icon: str, on_click: Any, tooltip_key: str, extra_class: str = "") -> Any:
        classes = f"audion-action ahm-pane-icon-button {extra_class}".strip()
        button = ui.button(icon=icon, on_click=on_click).props("dense flat round").classes(classes)
        return attach_tooltip(button, tooltip_key)

    def header_status_counts() -> dict[str, int]:
        counts = Counter(state.git_status_map.values())
        return {
            "staged": counts.get("staged", 0),
            "modified": counts.get("modified", 0),
            "untracked": counts.get("untracked", 0),
            "conflict": counts.get("conflict", 0),
            "changed": counts.get("changed", 0),
        }

    def normalized_header_status_mode() -> str:
        mode = str(getattr(state, "header_status_mode", "labeled") or "labeled").strip().lower()
        return mode if mode in STATUS_MODE_CYCLE else "labeled"

    def build_header_status_indicator(container: Any) -> None:
        counts = header_status_counts()
        mode = normalized_header_status_mode()
        container.clear()
        with container:
            with ui.row().classes(f"ahm-header-status-indicator ahm-status-mode-{mode} items-center justify-center"):
                items = list(PRIMARY_HEADER_STATUS)
                if counts.get("changed", 0) > 0:
                    items.append(FALLBACK_HEADER_STATUS)
                for label_key, icon_name, color in items:
                    n = counts.get(label_key, 0)
                    with ui.row().classes("ahm-status-cell items-center"):
                        dot = ui.element("span").classes("ahm-status-dot")
                        dot.style(f"background:{color};" + ("" if n else "opacity:.35;"))
                        if mode == "letters":
                            ui.label(STATUS_LETTERS[label_key]).classes("ahm-status-letter ahm-mono")
                        else:
                            ui.icon(icon_name).classes("ahm-status-icon")
                            if mode == "labeled":
                                ui.label(tr(f"status_word_{label_key}")).classes("ahm-status-word")
                        count_label = ui.label(str(n)).classes("ahm-status-count ahm-mono")
                        if not n:
                            count_label.classes(add="ahm-status-count-zero")
                        delayed_tooltip(tr(f"status_{label_key}"))

    def cycle_header_status_mode() -> None:
        current = normalized_header_status_mode()
        state.header_status_mode = STATUS_MODE_CYCLE[(STATUS_MODE_CYCLE.index(current) + 1) % len(STATUS_MODE_CYCLE)]
        state.settings["header_status_mode"] = state.header_status_mode
        save_gui_settings(state.settings)
        build_header_status_indicator(header_status_slot)
        ui.notify(tr("status_mode_saved", mode=state.header_status_mode), type="positive")

    def expand_button(selector: str) -> Any:
        script = f"""
        (() => {{
          const target = document.querySelector({json.dumps(selector)});
          if (!target) return;
          if (!window.__ahmCloseExpandedPanels) {{
            window.__ahmCloseExpandedPanels = () => {{
              document.querySelectorAll('.ahm-expanded-panel').forEach((panel) => {{
                panel.classList.remove('ahm-expanded-panel');
                const panelIcon = panel.querySelector('.ahm-expand-button .q-icon');
                if (panelIcon) panelIcon.textContent = 'open_in_full';
              }});
              document.body.classList.remove('ahm-has-expanded-panel');
            }};
            window.addEventListener('keydown', (event) => {{
              if (event.key === 'Escape') window.__ahmCloseExpandedPanels();
            }});
          }}
          const shouldExpand = !target.classList.contains('ahm-expanded-panel');
          window.__ahmCloseExpandedPanels();
          if (shouldExpand) target.classList.add('ahm-expanded-panel');
          const anyExpanded = !!document.querySelector('.ahm-expanded-panel');
          document.body.classList.toggle('ahm-has-expanded-panel', anyExpanded);
          const icon = target.querySelector('.ahm-expand-button .q-icon');
          if (icon) icon.textContent = shouldExpand ? 'close_fullscreen' : 'open_in_full';
          setTimeout(() => {{
            const terminal = target.querySelector('#ahm-terminal-output');
            if (terminal) terminal.scrollTop = terminal.scrollHeight;
          }}, 0);
        }})();
        """
        button = ui.button(icon="open_in_full", on_click=lambda: ui.run_javascript(script)).props("dense flat round").classes("audion-action ahm-expand-button")
        return attach_tooltip(button, "tip_expand_panel")

    def pane_control_button(icon: str, label: str, on_click: Any, tooltip_key: str, extra_class: str = "") -> Any:
        classes = f"audion-action ahm-pane-control-button {extra_class}".strip()
        button = ui.button(label, icon=icon, on_click=on_click).props("dense flat no-wrap").classes(classes)
        return attach_tooltip(button, tooltip_key)

    def command_cache_path() -> Path:
        return state.paths.config / "command_cache.json"

    def normalize_command_cache() -> None:
        history = command_cache.get("history", []) if isinstance(command_cache, dict) else []
        pinned = command_cache.get("pinned", []) if isinstance(command_cache, dict) else []
        normalized_history: list[str] = []
        seen_history: set[str] = set()
        for item in history if isinstance(history, list) else []:
            command = str(item.get("command", "") if isinstance(item, dict) else item).strip()
            if command and command not in seen_history:
                normalized_history.append(command)
                seen_history.add(command)
            if len(normalized_history) >= 200:
                break
        normalized_pinned: list[dict[str, str]] = []
        seen_pinned: set[str] = set()
        for item in pinned if isinstance(pinned, list) else []:
            if isinstance(item, dict):
                command = str(item.get("command", "")).strip()
                title = str(item.get("title", "")).strip()
            else:
                command = str(item).strip()
                title = ""
            if command and command not in seen_pinned:
                normalized_pinned.append({"title": title or command, "command": command})
                seen_pinned.add(command)
        command_cache.clear()
        command_cache.update({"history": normalized_history, "pinned": normalized_pinned})

    def save_command_cache() -> None:
        normalize_command_cache()
        save_json(command_cache_path(), command_cache)

    def command_title(command: str) -> str:
        text = command.strip()
        return text if len(text) <= 42 else f"{text[:39]}..."

    def command_history() -> list[str]:
        normalize_command_cache()
        return list(command_cache["history"])

    def pinned_commands() -> list[dict[str, str]]:
        normalize_command_cache()
        return list(command_cache["pinned"])

    def pinned_options() -> dict[str, str]:
        return {item["command"]: f"{item['title']}  ·  {item['command']}" for item in pinned_commands()}

    normalize_command_cache()

    def remote_field_cache_path() -> Path:
        return state.paths.config / "remote_field_cache.json"

    def normalize_remote_field_cache() -> None:
        for key in remote_field_cache_defaults:
            values = remote_field_cache.get(key, []) if isinstance(remote_field_cache, dict) else []
            normalized: list[str] = []
            seen: set[str] = set()
            for item in values if isinstance(values, list) else []:
                value = str(item).strip()
                if value and value not in seen:
                    normalized.append(value)
                    seen.add(value)
                if len(normalized) >= 20:
                    break
            remote_field_cache[key] = normalized

    def save_remote_field_cache() -> None:
        normalize_remote_field_cache()
        save_json(remote_field_cache_path(), remote_field_cache)

    def remote_cache_options(key: str) -> list[str]:
        normalize_remote_field_cache()
        return list(remote_field_cache.get(key, []))

    def refresh_remote_cache_selects() -> None:
        for key, select in (
            ("names", remote_name_cache_select),
            ("owners", remote_owner_cache_select),
            ("repos", remote_repo_cache_select),
            ("urls", remote_url_cache_select),
            ("hosts", remote_host_cache_select),
        ):
            select.options = remote_cache_options(key)
            if select.value and select.value not in select.options:
                select.value = None
            select.update()

    def remember_remote_field_value(key: str, value: str) -> None:
        value = str(value or "").strip()
        if not value:
            return
        values = [item for item in remote_cache_options(key) if item != value]
        remote_field_cache[key] = [value, *values][:20]

    def remember_remote_form_values() -> None:
        remember_remote_field_value("names", str(remote_name_input.value or ""))
        remember_remote_field_value("owners", str(remote_owner_input.value or ""))
        remember_remote_field_value("repos", str(remote_repo_input.value or ""))
        remember_remote_field_value("urls", str(remote_url_input.value or ""))
        remember_remote_field_value("hosts", str(remote_server_input.value or ""))
        save_remote_field_cache()
        refresh_remote_cache_selects()

    def apply_remote_cache_value(key: str, target: Any, select: Any) -> None:
        value = str(select.value or "").strip()
        if not value:
            append_terminal(tr("remote_cache_value_required"))
            set_status(tr("status_blocked"), "blocked")
            return
        target.value = value
        target.update()
        append_terminal(tr("remote_cache_applied", value=value))
        set_status(tr("status_remote_form_ok"), "success")

    normalize_remote_field_cache()

    with ui.header().classes("ahm-header"):
        ui.label(tr("title")).classes("ahm-header-title text-lg font-bold")
        header_status_slot = ui.element("div").classes("ahm-header-status-slot")
        build_header_status_indicator(header_status_slot)
        header_status_label = ui.label(state.status or tr("idle")).classes("ahm-status ahm-status-idle ahm-header-status")
        with ui.row().classes("ahm-header-controls items-center gap-2"):
            status_mode_button = ui.button(icon="monitor_heart", on_click=cycle_header_status_mode).props("dense flat round").classes("audion-action ahm-header-icon-button")
            attach_tooltip(status_mode_button, "status_mode_toggle")
            ui.icon("palette").classes("text-lg")
            ui.select(
                options=theme_options(state.lang),
                value=state.theme,
                on_change=lambda event: _set_theme(event.value),
            ).props("dense outlined options-dense popup-content-class=audion-select-popup").classes("audion-select audion-theme-select")
            tooltipped_button(tr("lang_switch"), on_click=_toggle_language, tooltip_key="tip_lang_switch", props="dense flat", classes="audion-action rounded-lg")

    with ui.element("div").classes("ahm-root"):
        with ui.element("div").classes("ahm-main"):
            with ui.element("div").classes("ahm-panel ahm-left-panel"):
                ui.label(tr("control")).classes("ahm-title")
                with ui.element("section").classes("ahm-block ahm-block-first"):
                    ui.label(tr("block_project")).classes("ahm-section-title")
                    project_select = ui.select(project_options, value=state.project.id, label=tr("project")).props("dense outlined options-dense popup-content-class=audion-select-popup").classes("audion-select w-full")
                    ui.label(tr("flow_label")).classes("ahm-muted")

                with ui.element("section").classes("ahm-block"):
                    ui.label(tr("block_open")).classes("ahm-section-title")
                    with ui.element("div").classes("ahm-button-grid ahm-button-grid-three ahm-open-layer-grid"):
                        tooltipped_button(tr("open_source_folder"), on_click=lambda: open_folder(source_root()), tooltip_key="tip_open_source_folder", classes="audion-action ahm-op-button rounded-lg")
                        tooltipped_button(tr("open_mirror_folder"), on_click=lambda: open_folder(mirror_root()), tooltip_key="tip_open_mirror_folder", classes="audion-action ahm-op-button rounded-lg")
                        tooltipped_button(tr("open_docs_app"), on_click=lambda: open_docs_app(), tooltip_key="tip_open_docs_app", classes="audion-action ahm-op-button rounded-lg")
                    with ui.element("div").classes("ahm-button-grid ahm-button-grid-three ahm-open-tool-grid"):
                        tooltipped_button(tr("open_vscode"), on_click=lambda: open_project_vscode(), tooltip_key="tip_open_vscode", classes="audion-action ahm-op-button rounded-lg")
                        tooltipped_button(tr("open_terminal"), on_click=lambda: open_project_terminal(), tooltip_key="tip_open_terminal", classes="audion-action ahm-op-button rounded-lg")
                        tooltipped_button(tr("open_git"), on_click=lambda: open_project_git(), tooltip_key="tip_open_git", classes="audion-action ahm-op-button rounded-lg")

                with ui.element("section").classes("ahm-block"):
                    ui.label(tr("block_mirror")).classes("ahm-section-title")
                    with ui.element("div").classes("ahm-check-grid"):
                        dry_run = ui.checkbox(tr("dry_run"), value=True).props("dense")
                        exact_mirror = ui.checkbox(tr("exact_mirror"), value=True).props("dense")
                        preserve_empty = ui.checkbox(tr("preserve_empty_dirs"), value=True).props("dense")
                        hash_compare = ui.checkbox(tr("hash_compare"), value=True).props("dense")
                    with ui.element("div").classes("ahm-button-grid ahm-button-grid-primary"):
                        tooltipped_button(tr("preview_mirror"), on_click=lambda: preview_mirror(), tooltip_key="tip_preview_mirror", classes="audion-action audion-primary-action ahm-op-button rounded-lg")
                        tooltipped_button(tr("apply_mirror"), on_click=lambda: apply_mirror(), tooltip_key="tip_apply_mirror", classes="audion-action audion-primary-action ahm-op-button rounded-lg")
                        tooltipped_button(tr("refresh"), on_click=lambda: refresh_all(), tooltip_key="tip_refresh_all", classes="audion-action ahm-op-button rounded-lg")

                with ui.element("section").classes("ahm-block"):
                    ui.label(tr("source_actions")).classes("ahm-section-title")
                    source_tree_badge = ui.label(state.source_tree_status or tr("project_tree_status_idle")).classes("ahm-source-tree-badge")
                    with ui.element("div").classes("ahm-button-grid ahm-source-action-grid"):
                        command_button("travel_explore", tr("rebuild_project_dropdown"), lambda: scan_projects_panel(), "tip_rebuild_project_dropdown")
                        command_button("download", tr("clone_into_source"), lambda: queue_clone_into_source(), "tip_clone_into_source")
                        command_button("fact_check", tr("batch_preview_mirror"), lambda: batch_preview_mirror_all(), "tip_batch_preview_mirror")
                        command_button("shield", tr("batch_safety_scan"), lambda: batch_safety_scan_all(), "tip_batch_safety_scan")
                        command_button("verified", tr("batch_verify_mirror"), lambda: batch_verify_mirror_all(), "tip_batch_verify_mirror")
                        command_button("query_stats", tr("batch_git_status"), lambda: batch_git_status_all(), "tip_batch_git_status")
                        command_button("workspaces", tr("combined_workspace"), lambda: generate_combined_workspace_file(), "tip_combined_workspace")

                with ui.element("section").classes("ahm-block"):
                    ui.label(tr("project_actions")).classes("ahm-section-title")
                    with ui.element("div").classes("ahm-button-grid ahm-project-action-grid"):
                        command_button("refresh", tr("refresh_tree_action"), lambda: refresh_tree(), "tip_refresh_tree_action")
                        command_button("edit_note", tr("load_selected_editor"), lambda: load_selected_into_editor(), "tip_load_selected_editor")
                        command_button("open_in_new", tr("open_selected_vscode"), lambda: open_selected_vscode(), "tip_open_selected_vscode")
                        command_button("content_copy", tr("copy_relative_path"), lambda: copy_selected_relative_path(), "tip_copy_relative_path")
                        command_button("file_copy", tr("copy_full_path"), lambda: copy_selected_full_path(), "tip_copy_full_path")

                with ui.element("section").classes("ahm-block"):
                    ui.label(tr("git_support_commands")).classes("ahm-section-title")
                    with ui.element("div").classes("ahm-button-grid ahm-support-grid"):
                        command_button("medical_services", tr("auth_doctor"), lambda: run_auth_doctor_panel(), "tip_auth_doctor")
                        command_button("fingerprint", "BLAKE3", lambda: run_blake3_check_panel(), "tip_blake3_check")
                        command_button("verified", "Verify Mirror", lambda: verify_mirror_panel(), "tip_verify_mirror")
                        command_button("account_tree", "Storage", lambda: run_storage_layout_panel(), "tip_storage_layout")
                        command_button("shield", "Safety Scan", lambda: run_safety_scan_panel(), "tip_safety_scan")
                        command_button("cleaning_services", tr("clean_projects_config"), lambda: clean_projects_config_panel(), "tip_clean_projects_config")

            ui.element("div").classes("ahm-splitter ahm-v-splitter ahm-splitter-left")

            with ui.element("div").classes("ahm-panel ahm-tree-panel"):
                with ui.element("div").classes("ahm-panel-head ahm-tree-panel-head"):
                    ui.label(tr("tree")).classes("ahm-title")
                    location_label = ui.label("").classes("ahm-source-tree-badge ahm-tree-location-badge")
                with ui.element("section").classes("ahm-block ahm-block-first"):
                    with ui.element("div").classes("ahm-location-strip"):
                        for scope, label_key in (
                            ("project", "tree_scope_project"),
                            ("hub", "tree_scope_hub"),
                            ("docs", "tree_scope_docs"),
                        ):
                            with ui.element("div").classes("ahm-location-pair"):
                                scope_buttons[scope] = ui.button(
                                    tr(label_key),
                                    on_click=lambda s=scope: set_tree_scope(s),
                                ).props("dense flat no-wrap").classes("audion-action ahm-scope-button rounded-lg")
                                attach_tooltip(scope_buttons[scope], f"tip_tree_scope_{scope}")
                                pick_button = ui.button(
                                    icon="folder_open",
                                    on_click=lambda s=scope: pick_location(s),
                                ).props("dense flat round color=grey-7").classes("ahm-location-pick")
                                attach_tooltip(pick_button, "pick_location")
                        ui.element("div").classes("ahm-location-spacer")
                        clear_locations_button = ui.button(
                            icon="clear_all",
                            on_click=lambda: clear_location_overrides(),
                        ).props("dense flat round color=grey-7").classes("ahm-location-clear")
                        attach_tooltip(clear_locations_button, "clear_locations")
                    ui.label(tr("block_filters")).classes("ahm-section-title")
                    with ui.element("div").classes("ahm-tree-toolbar"):
                        view_select = ui.select(["Full Tree", "Changed Only", "Staged", "Untracked", "Conflicts"], value="Full Tree", label=tr("view")).props("dense outlined options-dense popup-content-class=audion-select-popup").classes("audion-select")
                        search = ui.input(tr("search"), placeholder="README, AGENTS, system_core...").props("dense outlined").classes("audion-input")
                    with ui.element("div").classes("ahm-check-row"):
                        hide_clean = ui.checkbox(tr("hide_clean"), value=False).props("dense")
                        show_hidden = ui.checkbox(tr("show_hidden"), value=False).props("dense")
                        top_level_search = ui.checkbox(tr("top_level_search"), value=True).props("dense")
                tree_holder = ui.column().classes("ahm-tree-holder w-full")

            ui.element("div").classes("ahm-splitter ahm-v-splitter ahm-splitter-right")

            with ui.element("div").classes("ahm-panel ahm-inspector-panel"):
                with ui.element("div").classes("ahm-panel-head"):
                    ui.label(tr("inspector")).classes("ahm-title")
                    selected_label = ui.label(f"{tr('selected')}: {tr('not_selected')}").classes("ahm-muted")
                with ui.tabs().classes("w-full ahm-tab-toggle-pairs") as tabs:
                    tab_actions = inspector_tab("tab_actions", "flash_on", "tip_tab_quick")
                    tab_branch = inspector_tab("tab_branch", "account_tree", "tip_tab_branch")
                    tab_editor = inspector_tab("tab_editor", "edit_note", "tip_tab_editor")
                    tab_diff = inspector_tab("tab_diff", "difference", "tip_tab_diff")
                    tab_storage = inspector_tab("tab_storage", "storage", "tip_tab_storage")
                    tab_remote = inspector_tab("tab_remote", "cloud_sync", "tip_tab_remote")
                    tab_basket = inspector_tab("tab_basket", "inventory_2", "tip_tab_basket")
                    tab_preview = inspector_tab("tab_preview", "menu_book", "tip_tab_reader")
                    tab_history = inspector_tab("tab_history", "history", "tip_tab_history")
                    tab_meta = inspector_tab("tab_metadata", "info", "tip_tab_details")
                tab_panels = ui.tab_panels(tabs, value=tab_actions).classes("w-full ahm-tab-panels")
                tab_panels.on_value_change(lambda e: refresh_editor_layout())
                with tab_panels:
                    with ui.tab_panel(tab_actions):
                        with ui.element("div").classes("ahm-actions-panel"):
                            with ui.element("div").classes("ahm-actions-command-pane"):
                                with ui.element("section").classes("ahm-action-section"):
                                    ui.label(tr("git_local_commands")).classes("ahm-subsection-title")
                                    with ui.element("div").classes("ahm-command-grid"):
                                        command_button("create_new_folder", "git init", lambda: queue_git_command("git init"), "tip_git_init")
                                        command_button("search", "git status", lambda: refresh_git(), "tip_git_status")
                                        command_button("home", "git root", lambda: queue_git_command("git rev-parse --show-toplevel"), "tip_git_root")
                                        command_button("history", "git log --oneline", lambda: queue_git_command("git log --oneline --decorate -20"), "tip_git_queue")
                                        command_button("restore", "git reflog", lambda: queue_git_command("git reflog --date=local -20"), "tip_git_reflog")

                                with ui.element("section").classes("ahm-action-section"):
                                    ui.label(tr("git_inspect_commands")).classes("ahm-subsection-title")
                                    with ui.element("div").classes("ahm-command-value-grid"):
                                        command_value_controls("difference", "git diff --", "tip_git_diff_path", value_name="path", placeholder=tr("placeholder_path"), default=state.selected_path or "", quote_value=True)
                                        command_value_controls("fact_check", "git diff --cached --", "tip_git_diff_cached_path", value_name="path", placeholder=tr("placeholder_path"), default=state.selected_path or "", quote_value=True)
                                        command_value_controls("manage_search", "git blame --", "tip_git_queue", value_name="path", placeholder=tr("placeholder_path"), default=state.selected_path or "", quote_value=True)
                                        command_value_controls("plagiarism", "git show --stat", "tip_git_queue", value_name="commit", placeholder="HEAD", default="HEAD")

                                with ui.element("section").classes("ahm-action-section"):
                                    ui.label(tr("git_file_commands")).classes("ahm-subsection-title")
                                    with ui.element("div").classes("ahm-command-value-grid"):
                                        command_value_controls("add", "git add --", "tip_git_add_path", value_name="path", placeholder=tr("placeholder_path"), default=state.selected_path or "", quote_value=True)
                                        command_value_controls("undo", "git restore --staged --", "tip_git_restore_staged_path", value_name="path", placeholder=tr("placeholder_path"), default=state.selected_path or "", quote_value=True)
                                        command_value_controls("restore_page", "git restore --", "tip_git_queue", value_name="path", placeholder=tr("placeholder_path"), default=state.selected_path or "", quote_value=True)
                                    with ui.element("div").classes("ahm-command-grid"):
                                        command_button("inventory", "add active project", lambda: stage_active_project(), "tip_git_add_active_project", primary=True)
                                        command_button("playlist_add", "basket + selected", lambda: add_selected_to_basket(), "tip_basket_add")
                                        copy_button = ui.button(tr("copy_relative_path"), icon="content_copy", on_click=lambda: ui.clipboard.write(state.selected_path)).props("dense flat no-wrap").classes("audion-action ahm-op-button ahm-command-button rounded-lg")
                                        attach_tooltip(copy_button, "tip_copy_path")

                                with ui.element("section").classes("ahm-action-section"):
                                    ui.label(tr("git_backup_commands")).classes("ahm-subsection-title")
                                    with ui.element("div").classes("ahm-command-grid"):
                                        command_button("inventory_2", "git bundle create", lambda: create_checkpoint_bundle(), "tip_git_queue")
                                        command_button("cleaning_services", "git clean preview", lambda: queue_git_command("git clean -nd"), "tip_git_queue")
                                        command_button("compress", "git gc", lambda: queue_git_command("git gc"), "tip_git_queue")
                                        command_button("health_and_safety", "git fsck", lambda: queue_git_command("git fsck --full"), "tip_git_queue")
                                        command_button("list_alt", "git config list", lambda: queue_git_command("git config --list --show-origin"), "tip_git_config_list")

                                ui.element("div").classes("ahm-command-divider")

                                with ui.element("section").classes("ahm-action-section ahm-action-section-danger"):
                                    ui.label(tr("git_advanced_commands")).classes("ahm-subsection-title ahm-subsection-danger")
                                    with ui.element("div").classes("ahm-command-value-grid"):
                                        command_value_controls("restart_alt", "git reset --hard", "tip_git_queue", value_name="commit", placeholder="HEAD~1")
                                    with ui.element("div").classes("ahm-command-grid"):
                                        command_button("history_toggle_off", "git reset --soft HEAD~1", lambda: queue_git_command("git reset --soft HEAD~1"), "tip_git_queue")

                                with ui.element("section").classes("ahm-action-section"):
                                    ui.label(tr("cicd_observe_commands")).classes("ahm-subsection-title")
                                    with ui.element("div").classes("ahm-command-grid"):
                                        if shutil.which("gh"):
                                            command_button("list_alt", "gh run list", lambda: queue_git_command("gh run list --limit 15"), "tip_git_queue")
                                            command_button("visibility", "gh run watch", lambda: queue_git_command("gh run watch"), "tip_git_queue")
                                        if shutil.which("glab"):
                                            command_button("list_alt", "glab ci status", lambda: queue_git_command("glab ci status"), "tip_git_queue")

                            with ui.element("div").classes("ahm-action-cache-panel"):
                                with ui.element("div").classes("ahm-command-cache-tools-row"):
                                    pinned_command_select = ui.select(
                                        pinned_options(),
                                        label=tr("pinned_commands"),
                                        on_change=lambda e: set_action_command(str(e.value or "")),
                                    ).props("dense outlined options-dense popup-content-class=audion-select-popup").classes("audion-select ahm-pinned-command-select")
                                    command_cache_select = ui.select(
                                        command_history(),
                                        label=tr("command_cache"),
                                        on_change=lambda e: set_action_command(str(e.value or "")),
                                    ).props("dense outlined options-dense popup-content-class=audion-select-popup").classes("audion-select ahm-command-cache-select")
                                    cache_icon_button("push_pin", lambda: pin_action_command(), "tip_pin_command")
                                    cache_icon_button("push_pin", lambda: unpin_selected_command(), "tip_unpin_command")
                                    cache_icon_button("delete", lambda: delete_selected_command_history(), "tip_delete_command_cache_item")
                                    cache_icon_button("delete_sweep", lambda: clear_command_history(), "tip_clear_command_cache")
                                with ui.element("div").classes("ahm-custom-command-row"):
                                    action_command_input = ui.textarea(tr("command"), placeholder="git log --oneline --decorate -20").props("dense outlined no-resize autogrow rows=2 input-style='min-height: 40px;'").classes("audion-input ahm-action-command-input")
                                    action_command_input.on("keydown.enter", lambda e: run_action_command())
                                    command_button("play_arrow", tr("run"), lambda: run_action_command(), "tip_run_command")
                    with ui.tab_panel(tab_basket):
                        with ui.element("div").classes("ahm-commit-pane"):
                            ui.label(tr("git_commit_basket")).classes("ahm-subsection-title")
                            basket_box = ui.textarea(value=tr("basket_empty"), placeholder=tr("basket_paths")).props("readonly autogrow dense outlined no-resize").classes("audion-terminal-field ahm-basket-box w-full ahm-mono")

                            with ui.element("div").classes("ahm-commit-grid"):
                                commit_type = ui.select(["docs", "code", "fix", "ui", "test", "chore", "audit"], value="docs").props("dense outlined options-dense popup-content-class=audion-select-popup").classes("audion-select ahm-basket-compact-field")
                                commit_scope = ui.input(placeholder=tr("commit_scope")).props("dense outlined").classes("audion-input ahm-basket-compact-field")
                                commit_subject = ui.input(placeholder=tr("commit_subject")).props("dense outlined").classes("audion-input ahm-commit-wide ahm-basket-compact-field")
                                version_series = ui.input(value="projection", placeholder=tr("version_series")).props("dense outlined").classes("audion-input ahm-commit-wide ahm-basket-compact-field")
                                version_value = ui.input(value="v0.1.0", placeholder=tr("version_value")).props("dense outlined").classes("audion-input ahm-basket-compact-field")
                            with ui.element("div").classes("ahm-basket-command-layout"):
                                with ui.element("div").classes("ahm-basket-param-column"):
                                    with ui.element("div").classes("ahm-basket-command-pair"):
                                        command_button("upgrade", "next version", lambda: update_next_version(), "tip_next_version")
                                        version_bump_command = ui.select(["patch", "minor", "major"], value="patch").props("dense outlined options-dense popup-content-class=audion-select-popup").classes("audion-select ahm-command-value-input ahm-basket-command-value")
                                    with ui.element("div").classes("ahm-basket-command-pair"):
                                        command_button("new_label", "git tag HEAD", lambda: tag_head_version(), "tip_tag_head")
                                        tag_head_field = ui.input(value="", placeholder="v0.1.0").props("readonly dense outlined").classes("audion-input ahm-command-value-input ahm-basket-command-value")
                                    with ui.element("div").classes("ahm-basket-command-pair"):
                                        command_button("edit_note", tr("build_commit_message"), lambda: update_commit_message(), "tip_build_commit_message")
                                        commit_message = ui.input(placeholder=tr("commit_message")).props("dense outlined").classes("audion-input ahm-command-value-input ahm-basket-command-value")
                                with ui.element("div").classes("ahm-basket-action-column"):
                                    command_button("delete_sweep", "basket clear", lambda: clear_commit_basket(), "tip_basket_clear")
                                    command_button("inventory", "add active project", lambda: stage_active_project(), "tip_git_add_active_project", primary=True)
                                    command_button("playlist_add_check", "git add -- basket", lambda: stage_basket(), "tip_git_add_basket")
                                with ui.element("div").classes("ahm-basket-action-column ahm-basket-git-column"):
                                    command_button("playlist_remove", "git restore --staged -- basket", lambda: unstage_basket(), "tip_git_restore_basket")
                                    command_button("check_circle", "git commit --only -- basket", lambda: commit_basket(), "tip_git_commit_basket", primary=True)
                                    command_button("inventory_2", "git commit -m", lambda: commit_staged(), "tip_git_commit_staged")
                    with ui.tab_panel(tab_branch):
                        with ui.element("div").classes("ahm-branch-pane"):
                            ui.label(tr("branch_viewer")).classes("ahm-subsection-title")
                            with ui.element("section").classes("ahm-action-section"):
                                ui.label(tr("branch_status_commands")).classes("ahm-subsection-title")
                                with ui.element("div").classes("ahm-command-grid"):
                                    command_button("search", "git status", lambda: refresh_git(), "tip_git_status", primary=True)
                                    command_button("account_tree", "git branch -vv", lambda: queue_git_command("git branch -vv"), "tip_git_queue")
                                    command_button("history", "git log --graph", lambda: queue_git_command("git log --graph --oneline --decorate --all -30"), "tip_history_graph")
                                    command_button("cloud_sync", "git fetch --all --prune", lambda: fetch_all_remotes(), "tip_git_fetch_all")
                            with ui.element("section").classes("ahm-action-section"):
                                ui.label(tr("git_branch_tag_commands")).classes("ahm-subsection-title")
                                with ui.element("div").classes("ahm-command-value-grid"):
                                    command_value_controls("alt_route", "git switch", "tip_git_queue", value_name="branch", placeholder="main")
                                    command_value_controls("alt_route", "git switch -c", "tip_git_queue", value_name="new branch", placeholder="feature/name")
                                    command_button("new_label", "git tag version", lambda: queue_version_tag_command(), "tip_git_queue")
                                    command_button("sell", "git tag -n", lambda: queue_git_command("git tag -n --sort=-creatordate"), "tip_git_queue")
                            with ui.element("section").classes("ahm-action-section"):
                                ui.label(tr("git_integrate_commands")).classes("ahm-subsection-title")
                                with ui.element("div").classes("ahm-command-value-grid"):
                                    command_value_controls("compare_arrows", "git log --left-right --graph --cherry-pick --oneline HEAD...", "tip_git_queue", value_name="branch", placeholder="feature/name", separator="")
                                    command_value_controls("undo", "git revert", "tip_git_queue", value_name="commit", placeholder="a1b2c3d")
                                    command_value_controls("call_merge", "git merge --no-ff", "tip_git_queue", value_name="branch", placeholder="feature/name")
                                    command_value_controls("content_paste_go", "git cherry-pick", "tip_git_queue", value_name="commit", placeholder="a1b2c3d")
                            with ui.element("section").classes("ahm-action-section"):
                                ui.label(tr("git_stash_commands")).classes("ahm-subsection-title")
                                with ui.element("div").classes("ahm-command-value-grid"):
                                    command_value_controls("archive", "git stash push -u -m", "tip_git_queue", value_name="stash message", placeholder="wip", default="wip", quote_value=True, wide=True)
                                    command_button("unarchive", "git stash pop", lambda: queue_git_command("git stash pop"), "tip_git_queue")
                                    command_button("inventory", "git stash list", lambda: queue_git_command("git stash list"), "tip_git_queue")
                            with ui.element("section").classes("ahm-action-section ahm-action-section-danger"):
                                ui.label(tr("branch_danger_commands")).classes("ahm-subsection-title ahm-subsection-danger")
                                with ui.element("div").classes("ahm-command-value-grid"):
                                    command_value_controls("edit_note", "git rebase -i", "tip_git_queue", value_name="revision range", placeholder="HEAD~3", default="HEAD~3")
                                    command_button("merge_type", "git merge --abort", lambda: queue_git_command("git merge --abort"), "tip_git_queue")
                                    command_button("playlist_remove", "git cherry-pick --abort", lambda: queue_git_command("git cherry-pick --abort"), "tip_git_queue")
                    with ui.tab_panel(tab_remote):
                        with ui.element("div").classes("ahm-auth-pane"):
                            ui.label(tr("git_remote_commands")).classes("ahm-subsection-title")
                            with ui.element("div").classes("ahm-remote-toggle-strip"):
                                with ui.element("div").classes("ahm-remote-toggle-group"):
                                    ui.label(tr("remote_platform")).classes("ahm-remote-toggle-caption")
                                    for platform_key, platform_label in (
                                        ("github", "GitHub"),
                                        ("gitlab", "GitLab"),
                                        ("codeberg", "Codeberg"),
                                        ("forgejo", "Forgejo"),
                                        ("gitea", "Gitea"),
                                        ("custom", tr("remote_platform_custom")),
                                    ):
                                        remote_platform_buttons[platform_key] = ui.button(
                                            platform_label,
                                            on_click=lambda key=platform_key: set_remote_platform(key),
                                        ).props("dense flat no-wrap").classes("audion-action ahm-remote-toggle rounded-lg")
                                        attach_tooltip(remote_platform_buttons[platform_key], "tip_remote_platform")
                                with ui.element("div").classes("ahm-remote-toggle-group"):
                                    ui.label(tr("remote_url_type")).classes("ahm-remote-toggle-caption")
                                    for url_type_key, url_type_label_key in (("ssh", "remote_url_type_ssh"), ("https", "remote_url_type_https")):
                                        remote_url_type_buttons[url_type_key] = ui.button(
                                            tr(url_type_label_key),
                                            on_click=lambda key=url_type_key: set_remote_url_type(key),
                                        ).props("dense flat no-wrap").classes("audion-action ahm-remote-toggle rounded-lg")
                                        attach_tooltip(remote_url_type_buttons[url_type_key], "tip_remote_url_type")
                            with ui.element("div").classes("ahm-remote-config-grid"):
                                remote_server_input = ui.input(tr("remote_server_url"), value="", placeholder="https://git.example.org").props("dense outlined stack-label").classes("audion-input ahm-basket-field ahm-remote-input-field")
                                with ui.element("div").classes("ahm-remote-cache-row") as remote_server_cache_row:
                                    remote_host_cache_select = ui.select(remote_cache_options("hosts"), label=tr("recent_remote_server")).props("dense outlined stack-label options-dense popup-content-class=audion-select-popup").classes("audion-select ahm-basket-field ahm-remote-cache-select")
                                    cache_icon_button("keyboard_return", lambda: apply_remote_cache_value("hosts", remote_server_input, remote_host_cache_select), "tip_remote_cache_use")
                                remote_ssh_port_input = ui.input(tr("remote_ssh_port"), value="22", placeholder="22").props("dense outlined stack-label").classes("audion-input ahm-basket-field ahm-remote-input-field")
                                remote_selfhosted_spacer = ui.element("div").classes("ahm-remote-grid-spacer")
                                remote_selfhosted_elements = [remote_server_input, remote_server_cache_row, remote_ssh_port_input, remote_selfhosted_spacer]
                                remote_name_input = ui.input(tr("remote_name"), value="", placeholder="hidden_github").props("dense outlined stack-label").classes("audion-input ahm-basket-field ahm-remote-input-field")
                                with ui.element("div").classes("ahm-remote-cache-row"):
                                    remote_name_cache_select = ui.select(remote_cache_options("names"), label=tr("recent_remote_name")).props("dense outlined stack-label options-dense popup-content-class=audion-select-popup").classes("audion-select ahm-basket-field ahm-remote-cache-select")
                                    cache_icon_button("keyboard_return", lambda: apply_remote_cache_value("names", remote_name_input, remote_name_cache_select), "tip_remote_cache_use")
                                remote_owner_input = ui.input(tr("remote_owner"), value="", placeholder="audion or group/subgroup").props("dense outlined stack-label").classes("audion-input ahm-basket-field ahm-remote-input-field")
                                with ui.element("div").classes("ahm-remote-cache-row"):
                                    remote_owner_cache_select = ui.select(remote_cache_options("owners"), label=tr("recent_remote_owner")).props("dense outlined stack-label options-dense popup-content-class=audion-select-popup").classes("audion-select ahm-basket-field ahm-remote-cache-select")
                                    cache_icon_button("keyboard_return", lambda: apply_remote_cache_value("owners", remote_owner_input, remote_owner_cache_select), "tip_remote_cache_use")
                                remote_repo_input = ui.input(tr("remote_repo"), value="", placeholder="Audion_Hub_Private").props("dense outlined stack-label").classes("audion-input ahm-basket-field ahm-remote-input-field")
                                with ui.element("div").classes("ahm-remote-cache-row"):
                                    remote_repo_cache_select = ui.select(remote_cache_options("repos"), label=tr("recent_remote_repo")).props("dense outlined stack-label options-dense popup-content-class=audion-select-popup").classes("audion-select ahm-basket-field ahm-remote-cache-select")
                                    cache_icon_button("keyboard_return", lambda: apply_remote_cache_value("repos", remote_repo_input, remote_repo_cache_select), "tip_remote_cache_use")
                                remote_url_input = ui.input(tr("remote_url"), value="", placeholder="git@github.com:audion/Audion_Hub_Private.git").props("dense outlined stack-label").classes("audion-input ahm-basket-field ahm-remote-input-field")
                                with ui.element("div").classes("ahm-remote-cache-row"):
                                    remote_url_cache_select = ui.select(remote_cache_options("urls"), label=tr("recent_remote_url")).props("dense outlined stack-label options-dense popup-content-class=audion-select-popup").classes("audion-select ahm-basket-field ahm-remote-cache-select")
                                    cache_icon_button("keyboard_return", lambda: apply_remote_cache_value("urls", remote_url_input, remote_url_cache_select), "tip_remote_cache_use")
                            with ui.element("div").classes("ahm-command-grid ahm-auth-command-grid"):
                                command_button("upload", "git push origin", lambda: queue_git_command(f"git push --follow-tags origin {state.project.default_branch}"), "tip_git_push_follow_tags")
                                command_button("download", "git pull --ff-only", lambda: pull_ff_only_from_origin(), "tip_git_queue")
                                command_button("cloud_sync", "git fetch --all --prune", lambda: fetch_all_remotes(), "tip_git_fetch_all")
                                command_button("hub", "git remote -v", lambda: show_remotes(), "tip_git_remote")
                                command_button("backup_table", "git push all remotes", lambda: push_all_remotes(), "tip_git_push_all_remotes")
                                command_button("settings_input_component", "git apply remotes.json", lambda: apply_configured_remotes(), "tip_git_apply_remotes")
                                command_button("multiple_stop", "git origin push URLs", lambda: configure_origin_push_urls(), "tip_git_origin_push_urls")
                                command_button("link", tr("build_remote_url"), lambda: build_remote_url_into_field(), "tip_build_remote_url")
                                command_button("content_copy", tr("clone_repository"), lambda: clone_remote_repository(), "tip_clone_repository")
                                command_button("save", tr("save_remote_config"), lambda: save_remote_config_from_fields(), "tip_save_remote_config", primary=True)
                            ui.label(tr("forgejo_section")).classes("ahm-subsection-title")
                            ui.label(tr("forgejo_token_hint")).classes("ahm-muted")
                            with ui.element("div").classes("ahm-remote-toggle-strip"):
                                with ui.element("div").classes("ahm-remote-toggle-group"):
                                    ui.label(tr("forgejo_visibility")).classes("ahm-remote-toggle-caption")
                                    for visibility_key in ("private", "public"):
                                        forgejo_visibility_buttons[visibility_key] = ui.button(
                                            tr(f"forgejo_visibility_{visibility_key}"),
                                            on_click=lambda key=visibility_key: set_forgejo_visibility(key),
                                        ).props("dense flat no-wrap").classes("audion-action ahm-remote-toggle rounded-lg")
                                        attach_tooltip(forgejo_visibility_buttons[visibility_key], "tip_forgejo_visibility")
                            with ui.element("div").classes("ahm-remote-config-grid"):
                                forgejo_login_input = ui.input(tr("forgejo_login"), value="", placeholder="audion").props("dense outlined stack-label").classes("audion-input ahm-basket-field ahm-remote-input-field")
                                with ui.element("div").classes("ahm-remote-cache-row"):
                                    forgejo_token_input = ui.input(tr("forgejo_token"), value="", password=True, password_toggle_button=True).props("dense outlined stack-label autocomplete=off").classes("audion-input ahm-basket-field ahm-remote-input-field")
                                    cache_icon_button("key_off", lambda: forget_forgejo_token(), "tip_forgejo_forget_token")
                                forgejo_repo_select = ui.select([], label=tr("forgejo_repositories")).props("dense outlined stack-label options-dense popup-content-class=audion-select-popup").classes("audion-select ahm-basket-field ahm-remote-input-field ahm-remote-url-field")
                            with ui.element("div").classes("ahm-command-grid ahm-auth-command-grid"):
                                command_button("dns", tr("forgejo_check_server"), lambda: check_forgejo_server(), "tip_forgejo_check_server")
                                command_button("vpn_key", tr("forgejo_remember_token"), lambda: save_forgejo_token(), "tip_forgejo_save_token", primary=True)
                                command_button("badge", tr("forgejo_whoami"), lambda: show_forgejo_identity(), "tip_forgejo_whoami")
                                command_button("inventory", tr("forgejo_list_repos"), lambda: load_forgejo_repositories(), "tip_forgejo_list_repos")
                                command_button("input", tr("forgejo_use_repo"), lambda: apply_forgejo_repository(), "tip_forgejo_use_repo")
                                command_button("create_new_folder", tr("forgejo_create_repo"), lambda: create_forgejo_repository(), "tip_forgejo_create_repo")
                                command_button("open_in_new", tr("forgejo_open_tokens_page"), lambda: open_forgejo_token_page(), "tip_forgejo_open_tokens_page")
                            forgejo_status_label = ui.label(tr("forgejo_not_signed_in")).classes("ahm-muted")
                            ui.label(tr("remote_auth_actions")).classes("ahm-subsection-title")
                            with ui.element("div").classes("ahm-command-grid ahm-auth-command-grid"):
                                command_button("fact_check", tr("check_auth"), lambda: run_auth_doctor_panel(), "tip_auth_doctor", primary=True)
                                command_button("badge", "git config user", lambda: queue_git_command("git config --show-origin --get-regexp user\\."), "tip_git_user_config")
                                command_button("key", "ssh -T GitHub", lambda: run_ssh_auth_probe("github.com"), "tip_ssh_github")
                                command_button("key", "ssh -T GitLab", lambda: run_ssh_auth_probe("gitlab.com"), "tip_ssh_gitlab")
                                command_button("key", tr("ssh_probe_forgejo"), lambda: run_forgejo_ssh_probe(), "tip_ssh_forgejo")
                                command_button("login", "gh auth login", lambda: open_auth_terminal("gh auth login"), "tip_gh_auth_login")
                                command_button("login", "glab auth login", lambda: open_auth_terminal("glab auth login"), "tip_glab_auth_login")
                                command_button("admin_panel_settings", tr("open_windows_credentials"), lambda: open_windows_credentials(), "tip_windows_credentials")
                                command_button("folder_open", tr("open_gitkraken_folder"), lambda: open_gitkraken_folder(), "tip_gitkraken_folder")
                                command_button("code", tr("open_vscode"), lambda: open_project_vscode(), "tip_open_vscode")
                            ui.label(tr("auth_no_secrets")).classes("ahm-muted")
                            auth_box = ui.textarea(value="", label=tr("auth_doctor")).props("readonly autogrow dense outlined").classes("audion-terminal-field w-full ahm-mono")
                    with ui.tab_panel(tab_editor):
                        with ui.element("div").classes("ahm-editor-pane"):
                            with ui.element("div").classes("ahm-pane-head"):
                                ui.label(tr("markdown_editor")).classes("ahm-subsection-title")
                                with ui.element("div").classes("ahm-window-controls ahm-editor-window-controls"):
                                    pane_icon_button("file_open", lambda: load_selected_into_editor(), "tip_editor_load")
                                    pane_icon_button("save", lambda: save_editor_file(), "tip_editor_save")
                                    pane_icon_button("content_paste", lambda: paste_editor_text(), "tip_editor_paste")
                                    pane_icon_button("content_copy", lambda: copy_editor_text(), "tip_editor_copy")
                                    pane_icon_button("backspace", lambda: clear_editor_text(), "tip_editor_clear")
                                    pane_icon_button("open_in_new", lambda: open_editor_file_vscode(), "tip_editor_open_vscode", "ahm-pane-vscode-button")
                                    expand_button(".ahm-editor-pane")
                            editor_path_label = ui.label(tr("editor_no_file")).classes("ahm-muted ahm-editor-path")
                            try:
                                markdown_editor = ui.codemirror(
                                    value="",
                                    language="Markdown",
                                    theme="vscodeDark" if theme_mode(state.theme) == "dark" else "vscodeLight",
                                    indent="  ",
                                    line_wrapping=True,
                                    highlight_whitespace=False,
                                ).classes("w-full ahm-markdown-editor")
                            except Exception:
                                markdown_editor = ui.textarea(value="", label=tr("markdown_editor")).props("dense outlined").classes("audion-terminal-field ahm-markdown-editor-fallback w-full ahm-mono")
                    with ui.tab_panel(tab_preview):
                        preview_text = ui.markdown(tr("preview_placeholder"))
                    with ui.tab_panel(tab_diff):
                        with ui.element("div").classes("ahm-diff-pane"):
                            with ui.element("div").classes("ahm-pane-head"):
                                ui.label(tr("diff_viewer")).classes("ahm-subsection-title")
                                expand_button(".ahm-diff-pane")
                            diff_path_label = ui.label(tr("diff_no_path")).classes("ahm-muted ahm-editor-path")
                            with ui.element("div").classes("ahm-command-grid ahm-diff-command-grid"):
                                command_button("difference", "Unstaged", lambda: show_selected_diff("unstaged"), "tip_diff_unstaged", primary=True)
                                command_button("fact_check", "Staged", lambda: show_selected_diff("staged"), "tip_diff_staged")
                                command_button("history", "HEAD", lambda: show_selected_diff("head"), "tip_diff_head")
                                command_button("content_copy", "Copy patch", lambda: copy_diff_patch(), "tip_diff_copy")
                            diff_stats_label = ui.label("").classes("ahm-muted")
                            diff_box = ui.html("").classes("ahm-diff-box ahm-redline-box")
                    with ui.tab_panel(tab_history):
                        with ui.element("div").classes("ahm-history-pane"):
                            ui.label(tr("history_viewer")).classes("ahm-subsection-title")
                            history_path_label = ui.label(tr("history_no_path")).classes("ahm-muted ahm-editor-path")
                            with ui.element("div").classes("ahm-command-grid ahm-history-command-grid"):
                                command_button("manage_history", tr("history_selected"), lambda: show_history("selected"), "tip_history_selected", primary=True)
                                command_button("history", tr("history_repo"), lambda: show_history("repo"), "tip_history_repo")
                                command_button("account_tree", tr("history_graph"), lambda: show_history("graph"), "tip_history_graph")
                                command_button("new_label", tr("history_tags"), lambda: show_history("tags"), "tip_history_tags")
                                command_button("content_copy", tr("history_copy"), lambda: copy_history_text(), "tip_history_copy")
                            history_stats_label = ui.label("").classes("ahm-muted")
                            history_box = ui.html("").classes("ahm-history-box")
                    with ui.tab_panel(tab_meta):
                        with ui.element("div").classes("ahm-meta-pane"):
                            ui.label(tr("metadata_viewer")).classes("ahm-subsection-title")
                            with ui.element("div").classes("ahm-command-grid ahm-meta-command-grid"):
                                command_button("refresh", tr("metadata_refresh"), lambda: refresh_metadata_panel(), "tip_metadata_refresh", primary=True)
                                command_button("content_copy", tr("metadata_copy_json"), lambda: copy_metadata_json(), "tip_metadata_copy")
                                command_button("open_in_new", tr("metadata_open_vscode"), lambda: open_selected_vscode(), "tip_open_selected_vscode")
                            meta_summary = ui.html("").classes("ahm-meta-summary")
                            meta_box = ui.textarea(value="{}", label="metadata").props("readonly autogrow dense outlined").classes("audion-terminal-field ahm-meta-json w-full ahm-mono")
                    with ui.tab_panel(tab_storage):
                        with ui.element("div").classes("ahm-storage-pane"):
                            ui.label(tr("storage_viewer")).classes("ahm-subsection-title")
                            with ui.element("div").classes("ahm-command-grid ahm-storage-command-grid"):
                                command_button("account_tree", tr("storage_check"), lambda: run_storage_layout_panel(), "tip_storage_layout", primary=True)
                                command_button("travel_explore", tr("scan_projects"), lambda: scan_projects_panel(), "tip_scan_projects")
                                command_button("data_object", tr("generate_workspace"), lambda: generate_workspace_file(), "tip_generate_workspace")
                                command_button("content_copy", tr("storage_copy_json"), lambda: copy_storage_json(), "tip_storage_copy")
                                command_button("open_in_new", tr("storage_open_workspace"), lambda: open_generated_workspace(), "tip_storage_open_workspace")
                            storage_summary_box = ui.html("").classes("ahm-meta-summary")
                            storage_box = ui.textarea(value="", label=tr("storage_layout")).props("readonly autogrow dense outlined").classes("audion-terminal-field ahm-meta-json w-full ahm-mono")
                            ui.label(tr("safety_viewer")).classes("ahm-subsection-title")
                            with ui.element("div").classes("ahm-command-grid ahm-safety-command-grid"):
                                command_button("shield", tr("safety_scan_current"), lambda: run_safety_scan_panel(), "tip_safety_scan", primary=True)
                                command_button("content_copy", tr("safety_copy_json"), lambda: copy_safety_json(), "tip_safety_copy")
                            safety_summary_box = ui.html("").classes("ahm-meta-summary")
                            safety_box = ui.textarea(value="", label=tr("safety_scan")).props("readonly autogrow dense outlined").classes("audion-terminal-field ahm-meta-json w-full ahm-mono")
                            ui.label(tr("external_tools")).classes("ahm-subsection-title")
                            with ui.element("div").classes("ahm-service-row"):
                                vscode_command_input = ui.input(tr("vscode_executable"), placeholder="Code.exe").props("dense outlined").classes("audion-input")
                                command_button("folder_open", tr("pick_file"), lambda: pick_vscode_executable(), "tip_pick_vscode")
                                command_button("save", tr("save"), lambda: save_vscode_executable(), "tip_save_vscode", primary=True)
                                command_button("play_arrow", tr("test_vscode"), lambda: test_vscode_executable(), "tip_test_vscode")
                            vscode_resolved_label = ui.label("").classes("ahm-muted ahm-editor-path")

        ui.element("div").classes("ahm-splitter ahm-h-splitter ahm-splitter-terminal")

        with ui.element("div").classes("ahm-terminal"):
            with ui.element("div").classes("ahm-terminal-head"):
                with ui.element("div").classes("ahm-terminal-title-group"):
                    ui.label(tr("terminal")).classes("ahm-title")
                    ui.label(tr("operations_log")).classes("ahm-muted ahm-terminal-log-label")
                with ui.row().classes("items-center gap-2"):
                    status_label = ui.label(state.status or tr("idle")).classes("ahm-status ahm-status-idle")
                    pane_icon_button("delete_sweep", lambda: clear_terminal(), "tip_terminal_clear")
                    expand_button(".ahm-terminal")
            terminal = ui.html(f'<div id="ahm-terminal-output">{terminal_html([])}</div>').classes("ahm-terminal-output w-full")
            with ui.element("div").classes("ahm-command-row"):
                cmd_input = ui.input(tr("command"), placeholder="git status --porcelain=v1 -b").props("dense outlined").classes("audion-input")
                tooltipped_button(tr("run"), on_click=lambda: run_terminal_command(), tooltip_key="tip_run_command")
                tooltipped_button(tr("clear"), on_click=lambda: clear_terminal(), tooltip_key="tip_terminal_clear")

    def scope_title(scope: str) -> str:
        if scope == "hub":
            return tr("tree_scope_hub")
        if scope == "docs":
            return tr("tree_scope_docs")
        return tr("tree_scope_project")

    def project_field_for_scope(scope: str) -> str:
        if scope == "hub":
            return "projection_path"
        if scope == "docs":
            return "docs_path"
        return "source_path"

    def projects_config_path() -> Path:
        return state.paths.config / "projects.json"

    def projects_payload() -> dict[str, Any]:
        payload = load_json(projects_config_path(), default={"active_project_id": "", "projects": []})
        return payload if isinstance(payload, dict) else {"active_project_id": "", "projects": []}

    def current_project_item(payload: dict[str, Any]) -> dict[str, Any] | None:
        projects = payload.get("projects", [])
        if not isinstance(projects, list):
            return None
        for item in projects:
            if isinstance(item, dict) and str(item.get("id", "")).strip() == state.project.id:
                return item
        return None

    def configured_location(scope: str) -> Path | None:
        item = current_project_item(projects_payload())
        if not item:
            return None
        value = str(item.get(project_field_for_scope(scope), "")).strip()
        if not value:
            return None
        path = Path(value).expanduser()
        return path if path.is_absolute() else (state.paths.root / path).resolve(strict=False)

    def portable_existing_path(path: Path) -> Path:
        path = path.expanduser()
        if not path.is_absolute():
            return (state.paths.root / path).resolve(strict=False)
        if path.exists():
            return path
        current_drive = state.paths.root.drive
        if path.drive and current_drive and path.drive.lower() != current_drive.lower():
            candidate = Path(current_drive + "\\", *path.parts[1:])
            if candidate.exists():
                return candidate
        return path

    def project_config_path_value(path: Path) -> str:
        try:
            root = state.paths.root.resolve()
            target = path.expanduser().resolve(strict=False)
            relative = target.relative_to(root)
            return "." if str(relative) == "." else relative.as_posix()
        except (OSError, ValueError):
            return str(path.expanduser())

    def normalize_project_entry_paths(entry: dict[str, str]) -> dict[str, str]:
        normalized = dict(entry)
        for field in ("source_path", "projection_path", "docs_path"):
            value = str(normalized.get(field, "")).strip()
            if value:
                normalized[field] = project_config_path_value(Path(value))
        return normalized

    def project_model_location(scope: str) -> Path:
        if scope == "hub":
            return state.project.projection_path
        if scope == "docs":
            if state.project.docs_path is None:
                raise ValueError(f"Project '{state.project.id}' has no docs_path configured in projects.json")
            return state.project.docs_path
        return state.project.source_path

    def default_location(scope: str) -> Path:
        return portable_existing_path(configured_location(scope) or project_model_location(scope))

    def effective_location(scope: str) -> Path:
        return default_location(scope).expanduser()

    def source_root() -> Path:
        return effective_location("project")

    def mirror_root() -> Path:
        return effective_location("hub")

    def same_root(left: Path | None, right: Path) -> bool:
        if left is None:
            return False
        try:
            return left.resolve() == right.resolve()
        except OSError:
            return left.absolute() == right.absolute()

    def current_git_root() -> Path:
        return current_tree_root()

    def update_scope_buttons() -> None:
        for scope, button in scope_buttons.items():
            active_class = " ahm-scope-button-active" if scope == state.tree_scope else ""
            button.classes(replace=f"audion-action ahm-scope-button{active_class} rounded-lg")
            button.update()

    def update_location_label() -> None:
        root = effective_location(state.tree_scope)
        location_label.text = f"{scope_title(state.tree_scope)}: {root}"
        location_label.update()

    def update_location_ui() -> None:
        update_scope_buttons()
        update_location_label()

    def update_vscode_tool_ui() -> None:
        configured = external_apps.configured_vscode_command()
        resolved = external_apps.resolved_vscode_command(folder=True)
        vscode_command_input.value = configured
        vscode_command_input.update()
        vscode_resolved_label.text = tr("vscode_resolved", path=resolved)
        vscode_resolved_label.update()

    def update_project_select_options() -> None:
        project_options.clear()
        project_options.update({project.id: project.title for project in state.registry.projects})
        project_select.options = project_options
        project_select.value = state.project.id
        project_select.update()

    def set_tree_scope(scope: str) -> None:
        state.tree_scope = scope
        state.selected_path = ""
        state.tree_expanded = {"."}
        selected_label.text = f"{tr('selected')}: {tr('not_selected')}"
        selected_label.update()
        update_location_ui()
        refresh_tree()

    def clear_location_overrides() -> None:
        payload = projects_payload()
        item = current_project_item(payload)
        if item is not None:
            for field in ("source_path", "projection_path", "docs_path", "obsidian" + "_path"):
                item.pop(field, None)
            save_json(projects_config_path(), payload)
            state.registry = load_project_registry()
            state.project = state.registry.by_id(str(project_select.value or state.project.id))
        state.location_overrides.clear()
        state.current_plan = None
        state.tree_expanded = {"."}
        append_terminal(tr("locations_cleared"))
        update_location_ui()
        refresh_tree()

    def pick_location(scope: str) -> None:
        try:
            selected = _pick_directory(effective_location(scope), tr("pick_location_title", scope=scope_title(scope)))
        except Exception as exc:
            append_terminal(tr("pick_location_failed", error=exc))
            set_status(tr("status_error"), "error")
            return
        if selected is None:
            return
        payload = projects_payload()
        item = current_project_item(payload)
        if item is None:
            append_terminal(tr("project_config_missing", project=state.project.id))
            set_status(tr("status_error"), "error")
            return
        item[project_field_for_scope(scope)] = project_config_path_value(selected)
        save_json(projects_config_path(), payload)
        state.registry = load_project_registry()
        state.project = state.registry.by_id(state.project.id)
        state.location_overrides.clear()
        state.current_plan = None
        state.tree_scope = scope
        state.tree_expanded = {"."}
        append_terminal(tr("location_saved", scope=scope_title(scope), path=selected))
        update_location_ui()
        refresh_tree()

    def pick_vscode_executable() -> None:
        current = str(vscode_command_input.value or "").strip() or external_apps.resolved_vscode_command(folder=True)
        try:
            selected = _pick_file(Path(current), tr("pick_vscode_title"))
        except Exception as exc:
            append_terminal(tr("pick_vscode_failed", error=exc))
            set_status(tr("status_error"), "error")
            return
        if selected is None:
            return
        vscode_command_input.value = str(selected)
        vscode_command_input.update()

    def save_vscode_executable() -> None:
        command = str(vscode_command_input.value or "").strip()
        if not command:
            append_terminal(tr("vscode_path_required"))
            set_status(tr("status_blocked"), "blocked")
            return
        config_path = external_apps.save_local_vscode_command(command)
        update_vscode_tool_ui()
        append_terminal(tr("vscode_saved", path=command, config=config_path))
        set_status(tr("status_storage_ok"), "success")

    def test_vscode_executable() -> None:
        try:
            resolved = external_apps.resolved_vscode_command(folder=True)
            append_terminal(tr("vscode_resolved", path=resolved))
            external_apps.open_folder_in_vscode(source_root())
            append_terminal(tr("opened_vscode", target=source_root()))
            set_status(tr("status_storage_ok"), "success")
        except Exception as exc:
            append_terminal(tr("open_vscode_failed", error=exc))
            set_status(tr("status_error"), "error")

    def set_project(project_id: str) -> None:
        state.project = state.registry.by_id(project_id)
        state.current_plan = None
        state.tree_expanded = {"."}
        append_terminal(tr("selected_project", title=state.project.title))
        update_location_ui()
        refresh_tree()

    def terminal_update_html(lines: list[str], *, reset: bool = False) -> None:
        if reset:
            terminal.content = f'<div id="ahm-terminal-output">{terminal_html(lines[-500:])}</div>'
            terminal.update()
            return
        fragment = terminal_lines_html(lines, leading_newline=len(state.log_lines) > len(lines))
        payload = json.dumps(fragment)
        ui.run_javascript(
            f"""
            setTimeout(() => {{
              const box = document.getElementById('ahm-terminal-output');
              const pre = box?.querySelector('.audion-terminal-pre');
              if (!pre) return;
              pre.insertAdjacentHTML('beforeend', {payload});
              const lines = pre.querySelectorAll('.audion-terminal-line');
              const extra = lines.length - 500;
              for (let index = 0; index < extra; index += 1) lines[index]?.remove();
              box.scrollTop = box.scrollHeight;
            }}, 0);
            """
        )

    def append_terminal(line: str) -> None:
        text = str(line)
        lines = text.splitlines() or [""]
        for item in lines:
            state.log(item)
        terminal_update_html(lines)

    def set_status(text: str, kind: str = "idle") -> None:
        state.status = text
        header_status_label.text = text
        header_status_label.classes(replace=f"ahm-status ahm-status-{kind} ahm-header-status")
        header_status_label.update()
        status_label.text = text
        status_label.classes(replace=f"ahm-status ahm-status-{kind}")
        status_label.update()

    def log_command_result(result: Any) -> None:
        append_terminal(f"$ {result.joined_command()}  [cwd={result.cwd}]")
        if result.stdout.strip():
            append_terminal(result.stdout.strip())
        if result.stderr.strip():
            append_terminal(result.stderr.strip())
        append_terminal(tr("exit_code", code=result.returncode))

    def set_command_status(result: Any, ok_key: str = "status_command_ok") -> None:
        set_status(tr(ok_key) if result.ok else tr("status_error"), "success" if result.ok else "error")

    def refresh_command_cache_ui() -> None:
        pinned_command_select.options = pinned_options()
        if pinned_command_select.value and pinned_command_select.value not in pinned_command_select.options:
            pinned_command_select.value = None
        pinned_command_select.update()
        command_cache_select.options = command_history()
        if command_cache_select.value and command_cache_select.value not in command_cache_select.options:
            command_cache_select.value = None
        command_cache_select.update()

    def add_command_history(command: str) -> None:
        command = command.strip()
        if not command:
            return
        history = [item for item in command_history() if item != command]
        command_cache["history"] = [command, *history][:200]
        save_command_cache()
        refresh_command_cache_ui()

    def set_action_command(command: str) -> None:
        command = command.strip()
        if not command:
            return
        action_command_input.value = command
        action_command_input.update()
        cmd_input.value = command
        cmd_input.update()

    def queue_git_command(command: str) -> None:
        command = command.strip()
        if not command:
            return
        set_action_command(command)
        add_command_history(command)
        append_terminal(tr("command_queued", command=command))
        if is_dangerous_command(command):
            append_terminal(tr("dangerous_command_queued", command=command))
            ui.notify(tr("dangerous_command_queued", command=command), type="warning")
        set_status(tr("status_command_cache_ok"), "success")

    def queue_clone_into_source() -> None:
        source_parent = source_root().parent if source_root().exists() else state.paths.root.parent
        script = f"Set-Location -LiteralPath {_ps_quote(str(source_parent))}; git clone REMOTE_URL_HERE"
        command = f'powershell -NoProfile -ExecutionPolicy Bypass -Command "{script}"'
        queue_git_command(command)

    def quote_git_path(path: str) -> str:
        return '"' + path.replace('"', '\\"') + '"'

    def queue_selected_git_command(template: str) -> None:
        if not state.selected_path:
            append_terminal(tr("no_selected_path_for_stage"))
            set_status(tr("status_blocked"), "blocked")
            return
        queue_git_command(template.format(path=quote_git_path(state.selected_path)))

    def selected_action_command() -> str:
        return str(action_command_input.value or cmd_input.value or "").strip()

    def pin_action_command() -> None:
        command = selected_action_command()
        if not command:
            append_terminal(tr("custom_command_required"))
            set_status(tr("status_blocked"), "blocked")
            return
        normalize_command_cache()
        if command not in {item["command"] for item in command_cache["pinned"]}:
            command_cache["pinned"].append({"title": command_title(command), "command": command})
        add_command_history(command)
        save_command_cache()
        refresh_command_cache_ui()
        append_terminal(tr("command_pinned", command=command))
        set_status(tr("status_command_cache_ok"), "success")

    def unpin_selected_command() -> None:
        command = str(pinned_command_select.value or "").strip()
        if not command:
            append_terminal(tr("pinned_command_required"))
            set_status(tr("status_blocked"), "blocked")
            return
        command_cache["pinned"] = [item for item in pinned_commands() if item["command"] != command]
        save_command_cache()
        refresh_command_cache_ui()
        append_terminal(tr("command_unpinned", command=command))
        set_status(tr("status_command_cache_ok"), "success")

    def clear_command_history() -> None:
        command_cache["history"] = []
        save_command_cache()
        refresh_command_cache_ui()
        append_terminal(tr("command_cache_cleared"))
        set_status(tr("status_command_cache_ok"), "success")

    def delete_selected_command_history() -> None:
        command = str(command_cache_select.value or "").strip()
        if not command:
            append_terminal(tr("command_cache_item_required"))
            set_status(tr("status_blocked"), "blocked")
            return
        command_cache["history"] = [item for item in command_history() if item != command]
        save_command_cache()
        command_cache_select.value = None
        refresh_command_cache_ui()
        append_terminal(tr("command_cache_item_deleted", command=command))
        set_status(tr("status_command_cache_ok"), "success")

    def run_shell_command(command: str) -> None:
        command = command.strip()
        if not command:
            return
        if is_dangerous_command(command):
            append_terminal(f"BLOCKED dangerous command: {command}")
            set_status(tr("status_blocked"), "blocked")
            ui.notify(tr("dangerous_command_blocked"), type="warning")
            return
        add_command_history(command)
        root = current_git_root()
        if not root.exists():
            root = state.paths.root
        append_terminal(f"> {command}")
        try:
            set_status(tr("status_running"), "running")
            process = subprocess.Popen(
                command,
                cwd=str(root),
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
            )
            assert process.stdout is not None
            for output_line in iter_process_output_lines(process.stdout):
                append_terminal(output_line)
            returncode = int(process.wait() or 0)
            append_terminal(tr("exit_code", code=returncode))
            set_status(tr("status_command_ok") if returncode == 0 else tr("status_error"), "success" if returncode == 0 else "error")
        except Exception as exc:
            append_terminal(tr("command_failed", kind=exc.__class__.__name__, error=exc))
            set_status(tr("status_error"), "error")

    def run_action_command() -> None:
        command = selected_action_command()
        if command:
            set_action_command(command)
        run_shell_command(command)

    def sorted_commit_basket() -> list[str]:
        return sorted((item for item in state.commit_basket if item), key=str.casefold)

    def basket_paths_summary() -> str:
        paths = sorted_commit_basket()
        if not paths:
            return ""
        if len(paths) == 1:
            return paths[0]
        return f"{len(paths)} paths"

    def update_basket_command_fields() -> None:
        tag_head_field.value = version_tag_text()
        tag_head_field.update()

    def update_basket_box() -> None:
        paths = sorted_commit_basket()
        basket_box.value = "\n".join(paths) if paths else tr("basket_empty")
        basket_box.update()
        update_basket_command_fields()

    def clear_commit_basket(*, quiet: bool = False) -> None:
        state.commit_basket.clear()
        state.commit_basket_root = None
        update_basket_box()
        if not quiet:
            append_terminal(tr("basket_cleared"))
            set_status(tr("status_basket_ok"), "success")

    def ensure_commit_basket_root() -> Path:
        root = current_git_root()
        if state.commit_basket_root is None:
            state.commit_basket_root = root
        elif not same_root(state.commit_basket_root, root):
            state.commit_basket.clear()
            state.commit_basket_root = root
            append_terminal(tr("basket_root_changed", root=root))
        update_basket_box()
        return root

    def basket_paths_or_block() -> tuple[Path, list[str]] | None:
        root = ensure_commit_basket_root()
        paths = sorted_commit_basket()
        if not paths:
            append_terminal(tr("basket_empty_for_git"))
            set_status(tr("status_blocked"), "blocked")
            return None
        if commit_paths_blocked_by_hub_profile(root, paths):
            return None
        return root, paths

    def commit_profile_violations(root: Path, paths: list[str]) -> list[str]:
        profile = get_projection_profile(state.project.profile)
        marker_file = str(getattr(profile, "marker_file", ".gitkeep") or ".gitkeep")
        violations: list[str] = []
        for raw_path in paths:
            rel = norm_rel(raw_path)
            if not rel:
                continue
            target = root / rel
            if target.exists() and target.is_dir():
                candidates = [item for item in target.rglob("*") if item.is_file()]
            else:
                candidates = [target]
            for candidate in candidates:
                try:
                    candidate_rel = norm_rel(candidate.relative_to(root))
                except ValueError:
                    candidate_rel = rel
                if Path(candidate_rel).name == marker_file:
                    continue
                size = candidate.stat().st_size if candidate.exists() and candidate.is_file() else 0
                allowed, reason = include_file(candidate_rel, size, profile)
                if not allowed:
                    violations.append(f"{candidate_rel} ({reason})")
        return sorted(set(violations), key=str.casefold)

    def commit_paths_blocked_by_hub_profile(root: Path, paths: list[str]) -> bool:
        violations = commit_profile_violations(root, paths)
        if not violations:
            return False
        shown = ", ".join(violations[:8])
        if len(violations) > 8:
            shown += f", +{len(violations) - 8}"
        append_terminal(tr("commit_paths_outside_hub_profile", paths=shown))
        set_status(tr("status_blocked"), "blocked")
        return True

    def active_project_stage_target() -> Path | None:
        projection = mirror_root()
        if not projection.exists():
            append_terminal(tr("active_project_projection_missing", path=projection))
            set_status(tr("status_blocked"), "blocked")
            return None
        return projection

    def stage_active_project() -> None:
        root = active_project_stage_target()
        if root is None:
            return
        if commit_paths_blocked_by_hub_profile(root, ["."]):
            return
        result = git_stage(root, ["."])
        log_command_result(result)
        if result.ok:
            append_terminal(tr("active_project_staged", path=".", root=root))
        set_command_status(result, "status_stage_ok")
        refresh_git()

    def add_selected_to_basket() -> None:
        if not state.selected_path:
            append_terminal(tr("no_selected_path_for_basket"))
            set_status(tr("status_blocked"), "blocked")
            return
        ensure_commit_basket_root()
        state.commit_basket.add(state.selected_path)
        update_basket_box()
        append_terminal(tr("basket_added", path=state.selected_path))
        set_status(tr("status_basket_ok"), "success")

    def stage_basket() -> None:
        target = basket_paths_or_block()
        if target is None:
            return
        root, paths = target
        result = git_stage(root, paths)
        log_command_result(result)
        set_command_status(result, "status_stage_ok")
        refresh_git()

    def unstage_basket() -> None:
        target = basket_paths_or_block()
        if target is None:
            return
        root, paths = target
        result = git_unstage(root, paths)
        log_command_result(result)
        set_command_status(result, "status_unstage_ok")
        refresh_git()

    def commit_basket() -> None:
        target = basket_paths_or_block()
        if target is None:
            return
        message = update_commit_message()
        if not message:
            append_terminal(tr("commit_message_required"))
            set_status(tr("status_blocked"), "blocked")
            return
        root, paths = target
        result = git_commit_paths(root, message, paths)
        log_command_result(result)
        set_command_status(result, "status_commit_ok")
        if result.ok:
            clear_commit_basket(quiet=True)
        refresh_git()

    def show_remotes() -> None:
        result = git_remotes(current_git_root())
        log_command_result(result)
        preview_text.content = f"```text\n{result.stdout or result.stderr}\n```"
        preview_text.update()
        set_command_status(result, "status_remotes_ok")

    def fetch_all_remotes() -> None:
        result = git_fetch_all(current_git_root())
        log_command_result(result)
        preview_text.content = f"```text\n{result.stdout or result.stderr}\n```"
        preview_text.update()
        set_command_status(result, "status_fetch_ok")
        refresh_git()

    def log_git_result_batch(results: list[Any], ok_key: str) -> bool:
        output_parts: list[str] = []
        for result in results:
            log_command_result(result)
            text = (result.stdout or result.stderr).strip()
            if text:
                output_parts.append(text)
        preview_text.content = f"```text\n{chr(10).join(output_parts)}\n```"
        preview_text.update()
        ok = bool(results) and all(result.ok for result in results)
        set_status(tr(ok_key) if ok else tr("status_error"), "success" if ok else "error")
        return ok

    def remotes_config_path() -> Path:
        return state.paths.config / "remotes.json"

    def remember_remote_choice() -> None:
        """Persist the button-row selection so the pane opens where it was left."""
        remote_field_cache["platform"] = remote_choice["platform"]
        remote_field_cache["url_type"] = remote_choice["url_type"]
        save_remote_field_cache()

    def restore_remote_choice() -> None:
        platform = str(remote_field_cache.get("platform", "")).strip().lower()
        if platform in remote_platform_buttons:
            remote_choice["platform"] = platform
        url_type = str(remote_field_cache.get("url_type", "")).strip().lower()
        if url_type in remote_url_type_buttons:
            remote_choice["url_type"] = url_type

    def update_remote_toggle_buttons() -> None:
        for buttons, chosen in (
            (remote_platform_buttons, remote_choice["platform"]),
            (remote_url_type_buttons, remote_choice["url_type"]),
            (forgejo_visibility_buttons, remote_choice["visibility"]),
        ):
            for key, button in buttons.items():
                active = " ahm-remote-toggle-active" if key == chosen else ""
                button.classes(replace=f"audion-action ahm-remote-toggle{active} rounded-lg")
                button.update()

    def set_remote_platform(platform: str) -> None:
        remote_choice["platform"] = platform
        update_remote_toggle_buttons()
        update_remote_platform_ui()
        remember_remote_choice()

    def set_remote_url_type(url_type: str) -> None:
        remote_choice["url_type"] = url_type
        update_remote_toggle_buttons()
        remember_remote_choice()

    def set_forgejo_visibility(visibility: str) -> None:
        remote_choice["visibility"] = visibility
        update_remote_toggle_buttons()

    def remote_form_field_values() -> tuple[str, str, str, str]:
        platform = str(remote_choice["platform"] or "github").strip().lower()
        owner = str(remote_owner_input.value or "").strip().strip("/")
        repo = str(remote_repo_input.value or "").strip().strip("/")
        if repo.endswith(".git"):
            repo = repo[:-4]
        remote_name = str(remote_name_input.value or "").strip()
        return platform, owner, repo, remote_name

    def remote_url_type_value() -> str:
        return str(remote_choice["url_type"] or "ssh").strip().lower()

    def remote_ssh_port_value() -> int | None:
        """Parsed SSH port, or None when the field holds something unusable.

        Falling back to 22 would build a URL that looks right and fails at push
        time with an error pointing at the wrong thing.
        """
        raw = str(remote_ssh_port_input.value or "").strip()
        if not raw:
            return 22
        try:
            port = int(raw)
        except ValueError:
            return None
        return port if 1 <= port <= 65535 else None

    def is_self_hosted_platform(platform: str = "") -> bool:
        return (platform or str(remote_choice["platform"])).strip().lower() in SELF_HOSTED_PLATFORMS

    def update_remote_platform_ui() -> None:
        """Self-hosted platforms need a server address; the cloud ones do not."""
        self_hosted = is_self_hosted_platform()
        for element in remote_selfhosted_elements:
            element.set_visibility(self_hosted)
        if self_hosted and not str(remote_server_input.value or "").strip():
            host = forgejo_service.active_host(state.paths.config)
            if host:
                remote_server_input.value = host.base_url
                remote_ssh_port_input.value = str(host.ssh_port)
                remote_choice["url_type"] = host.preferred_url_type or "ssh"
                if host.login and not str(forgejo_login_input.value or "").strip():
                    forgejo_login_input.value = host.login
                for element in (remote_server_input, remote_ssh_port_input, forgejo_login_input):
                    element.update()
                update_remote_toggle_buttons()
        update_forgejo_status_label()

    def forgejo_host_from_form(*, quiet: bool = False) -> forgejo_api.ForgejoHost | None:
        """Build a host record from the form, falling back to the configured one."""
        server = str(remote_server_input.value or "").strip()
        if not server:
            host = forgejo_service.active_host(state.paths.config)
            if host is None and not quiet:
                append_terminal(tr("forgejo_server_required"))
                set_status(tr("status_blocked"), "blocked")
            return host
        try:
            base_url = forgejo_api.normalize_base_url(server)
        except ValueError as exc:
            if not quiet:
                append_terminal(tr("forgejo_server_invalid", error=exc))
                set_status(tr("status_blocked"), "blocked")
            return None
        port = remote_ssh_port_value()
        if port is None:
            if not quiet:
                append_terminal(tr("remote_ssh_port_invalid", value=str(remote_ssh_port_input.value or "").strip()))
                set_status(tr("status_blocked"), "blocked")
            return None
        hostname = urlparse(base_url).hostname or ""
        configured = next((item for item in forgejo_service.load_hosts(state.paths.config) if item.hostname == hostname), None)
        platform = str(remote_choice["platform"]).strip().lower()
        title = configured.title if configured else f"{platform.title() or 'Forgejo'} {hostname}"
        try:
            return forgejo_api.ForgejoHost(
                id=configured.id if configured else (hostname or "forgejo"),
                title=title,
                url=base_url,
                ssh_port=port,
                ssh_user=configured.ssh_user if configured else "git",
                preferred_url_type=remote_url_type_value(),
                login=str(forgejo_login_input.value or "").strip() or (configured.login if configured else ""),
            )
        except ValueError as exc:
            if not quiet:
                append_terminal(tr("forgejo_server_invalid", error=exc))
                set_status(tr("status_blocked"), "blocked")
            return None

    def remote_url_from_identity_fields() -> str:
        platform, owner, repo, _remote_name = remote_form_field_values()
        if not owner or not repo:
            return ""
        if is_self_hosted_platform(platform):
            host = forgejo_host_from_form()
            if host is None:
                return ""
            return forgejo_api.build_remote_url(host, owner, repo, remote_url_type_value())
        hostname = CLOUD_PLATFORM_HOSTS.get(platform, "github.com")
        if remote_url_type_value() == "https":
            return f"https://{hostname}/{owner}/{repo}.git"
        return f"git@{hostname}:{owner}/{repo}.git"

    def remote_url_from_form() -> str:
        explicit_url = str(remote_url_input.value or "").strip()
        if explicit_url:
            return explicit_url
        return remote_url_from_identity_fields()

    def build_remote_url_into_field() -> None:
        url = remote_url_from_identity_fields()
        if not url:
            append_terminal(tr("remote_fields_required"))
            set_status(tr("status_blocked"), "blocked")
            return
        remote_url_input.value = url
        remote_url_input.update()
        append_terminal(tr("remote_url_built", url=url))
        set_status(tr("status_remote_form_ok"), "success")

    def save_remote_config_from_fields() -> None:
        platform, owner, repo, remote_name = remote_form_field_values()
        if not remote_name:
            remote_name = f"hidden_{platform}"
            remote_name_input.value = remote_name
            remote_name_input.update()
        if not re.match(r"^[A-Za-z0-9._-]+$", remote_name):
            append_terminal(tr("remote_name_invalid", name=remote_name))
            set_status(tr("status_blocked"), "blocked")
            return
        url = remote_url_from_form()
        if not url:
            append_terminal(tr("remote_fields_required"))
            set_status(tr("status_blocked"), "blocked")
            return
        # config/remotes.json is a committed file. A pasted https://user:TOKEN@host
        # URL would publish the secret with the next commit.
        if auth_doctor_has_embedded_credentials(url):
            append_terminal(tr("remote_url_has_credentials"))
            set_status(tr("status_blocked"), "blocked")
            return
        try:
            git_validate_remote_url(url)
        except ValueError as exc:
            append_terminal(tr("remote_url_unsafe", error=exc))
            set_status(tr("status_blocked"), "blocked")
            return

        config_path = remotes_config_path()
        payload = load_json(config_path, {"global_remotes": []})
        if not isinstance(payload, dict):
            payload = {"global_remotes": []}
        items = payload.get("global_remotes")
        if not isinstance(items, list):
            items = []
            payload["global_remotes"] = items
        title_platform = PLATFORM_TITLES.get(platform, platform.title())
        entry = {
            "name": remote_name,
            "title": f"{title_platform} {repo or remote_name}",
            "enabled": True,
            "url": url,
        }
        for index, item in enumerate(items):
            if isinstance(item, dict) and str(item.get("name", "")).strip() == remote_name:
                items[index] = {**item, **entry}
                break
        else:
            items.append(entry)
        save_json(config_path, payload)
        remote_url_input.value = url
        remote_url_input.update()
        remember_remote_form_values()
        append_terminal(tr("remote_config_saved", name=remote_name, url=url, path=config_path))
        set_status(tr("status_remote_form_ok"), "success")

    def create_checkpoint_bundle() -> None:
        """Run git bundle through the engine, not as a shell string.

        The destination path is interpolated into the command otherwise, so a
        folder name containing `&` or a quote breaks or mangles it.
        """
        target = state.paths.backup / "checkpoint.bundle"
        set_status(tr("status_running"), "running")
        try:
            result = git_create_bundle(current_git_root(), target, state.project.default_branch)
        except Exception as exc:
            append_terminal(tr("command_failed", kind=exc.__class__.__name__, error=exc))
            set_status(tr("status_error"), "error")
            return
        log_command_result(result)
        set_command_status(result)

    def pull_ff_only_from_origin() -> None:
        set_status(tr("status_running"), "running")
        result = git_pull_ff_only(current_git_root(), "origin", state.project.default_branch)
        log_command_result(result)
        set_command_status(result)
        if result.ok:
            refresh_git()

    def log_api_result(result: forgejo_api.ApiResult) -> None:
        append_terminal(f"$ {result.joined_command()}")
        if result.status is not None:
            append_terminal(tr("forgejo_http_status", status=result.status))
        if result.error:
            append_terminal(result.error)

    def report_forgejo_api_failure(result: forgejo_api.ApiResult, host_url: str, fallback_key: str) -> None:
        """Say what actually went wrong: bad token, missing scope, or the call itself."""
        if result.forbidden or result.unauthorized:
            append_terminal(
                tr(
                    forgejo_service.token_failure_message_key(result),
                    error=forgejo_service.token_failure_detail(result),
                    host=host_url,
                )
            )
            if result.forbidden:
                append_terminal(tr("forgejo_scope_hint"))
        else:
            append_terminal(tr(fallback_key, error=result.error))
        set_status(tr("status_error"), "error")

    def forgejo_token_in_field() -> str:
        return str(forgejo_token_input.value or "").strip()

    def refresh_forgejo_stored_state() -> None:
        """Ask the credential store whether a token is remembered for this host.

        The field is cleared after saving, so without this the pane looks exactly
        the same whether a token was remembered or not.
        """
        host = forgejo_host_from_form(quiet=True)
        if host is None:
            forgejo_stored_state.update({"checked": True, "present": False, "login": ""})
            return
        login = str(forgejo_login_input.value or "").strip() or host.login
        token, _probe = forgejo_service.stored_token(host, login, cwd=current_git_root())
        forgejo_stored_state.update({"checked": True, "present": bool(token), "login": login})

    def set_forgejo_stored_state(present: bool, login: str = "") -> None:
        """Record what we just did, so the label updates without another probe."""
        forgejo_stored_state.update({"checked": True, "present": present, "login": login})

    def log_credential_probe(credential: Any) -> None:
        """Only meaningful when the token came from the store rather than the field."""
        if credential is not None:
            append_terminal(f"$ {credential.joined_command()}")

    def update_forgejo_status_label() -> None:
        host = forgejo_host_from_form(quiet=True)
        if host is None:
            forgejo_status_label.text = tr("forgejo_no_host")
        else:
            login = str(forgejo_login_input.value or "").strip() or host.login
            base = (
                tr("forgejo_status_known", host=host.base_url, login=login)
                if login
                else tr("forgejo_status_unknown", host=host.base_url)
            )
            if forgejo_token_in_field():
                # The typed token wins over anything remembered.
                source = tr("forgejo_token_source_field")
            elif not forgejo_stored_state["checked"]:
                source = tr("forgejo_token_unchecked")
            elif forgejo_stored_state["present"]:
                source = tr("forgejo_token_remembered", login=forgejo_stored_state["login"] or login)
            else:
                source = tr("forgejo_token_not_remembered")
            forgejo_status_label.text = f"{base} · {source}"
        forgejo_status_label.update()

    def check_forgejo_server() -> None:
        host = forgejo_host_from_form()
        if host is None:
            return
        set_status(tr("status_running"), "running")
        result = forgejo_api.server_version(host.base_url)
        log_api_result(result)
        if result.ok and isinstance(result.data, dict):
            version = str(result.data.get("version", "")).strip()
            append_terminal(tr("forgejo_server_ok", host=host.base_url, version=version))
            remember_remote_field_value("hosts", host.base_url)
            save_remote_field_cache()
            refresh_remote_cache_selects()
            set_status(tr("status_auth_ok"), "success")
        else:
            append_terminal(tr("forgejo_server_failed", host=host.base_url, error=result.error))
            set_status(tr("status_error"), "error")

    def save_forgejo_token() -> None:
        """Verify the token first, then hand it to the Git credential helper."""
        host = forgejo_host_from_form()
        if host is None:
            return
        token = str(forgejo_token_input.value or "").strip()
        if not token:
            append_terminal(tr("forgejo_token_required"))
            set_status(tr("status_blocked"), "blocked")
            return
        if host.base_url.lower().startswith("http://"):
            # Plain HTTP is legitimate for a LAN instance, but the token crosses
            # the wire in the clear, so say it out loud rather than assume.
            append_terminal(tr("forgejo_insecure_transport", host=host.base_url))
        set_status(tr("status_running"), "running")
        outcome = forgejo_service.sign_in(
            state.paths.config,
            host,
            str(forgejo_login_input.value or "").strip(),
            token,
            cwd=current_git_root(),
        )
        if outcome.api is not None:
            log_api_result(outcome.api)
        if outcome.credential is not None:
            append_terminal(f"$ {outcome.credential.joined_command()}")
        if not outcome.ok:
            append_terminal(tr(outcome.message_key, error=outcome.detail, host=host.base_url))
            if outcome.api is not None and outcome.api.forbidden:
                append_terminal(tr("forgejo_scope_hint"))
            set_status(tr("status_error"), "error")
            return
        # The secret is now in the OS credential store; drop it from the form.
        forgejo_token_input.value = ""
        forgejo_token_input.update()
        forgejo_login_input.value = outcome.login
        forgejo_login_input.update()
        if not str(remote_owner_input.value or "").strip():
            remote_owner_input.value = outcome.login
            remote_owner_input.update()
        remember_remote_field_value("hosts", host.base_url)
        save_remote_field_cache()
        refresh_remote_cache_selects()
        append_terminal(tr("forgejo_signed_in", login=outcome.login, host=host.base_url))
        set_forgejo_stored_state(True, outcome.login)
        update_forgejo_status_label()
        set_status(tr("status_auth_ok"), "success")

    def show_forgejo_identity() -> None:
        host = forgejo_host_from_form()
        if host is None:
            return
        set_status(tr("status_running"), "running")
        result, credential = forgejo_service.whoami(
            host,
            str(forgejo_login_input.value or "").strip(),
            cwd=current_git_root(),
            token=forgejo_token_in_field(),
        )
        log_credential_probe(credential)
        if result is None:
            append_terminal(tr("forgejo_no_token_anywhere", host=host.base_url))
            set_status(tr("status_blocked"), "blocked")
            return
        log_api_result(result)
        if not result.ok:
            report_forgejo_api_failure(result, host.base_url, "forgejo_token_rejected")
            return
        user = forgejo_api.user_summary(result.data)
        forgejo_login_input.value = user.get("login", "")
        forgejo_login_input.update()
        forgejo_service.remember_login(state.paths.config, host, user.get("login", ""))
        append_terminal(tr("forgejo_identity", login=user.get("login", ""), name=user.get("full_name", ""), email=user.get("email", "")))
        update_forgejo_status_label()
        set_status(tr("status_auth_ok"), "success")

    def load_forgejo_repositories() -> None:
        host = forgejo_host_from_form()
        if host is None:
            return
        set_status(tr("status_running"), "running")
        result, credential = forgejo_service.list_repos(
            host,
            str(forgejo_login_input.value or "").strip(),
            cwd=current_git_root(),
            token=forgejo_token_in_field(),
        )
        log_credential_probe(credential)
        if result is None:
            append_terminal(tr("forgejo_no_token_anywhere", host=host.base_url))
            set_status(tr("status_blocked"), "blocked")
            return
        log_api_result(result)
        if not result.ok:
            report_forgejo_api_failure(result, host.base_url, "forgejo_repos_failed")
            return
        summaries = [forgejo_api.repo_summary(item) for item in (result.data or []) if isinstance(item, dict)]
        options = {
            item["full_name"]: f"{item['full_name']}  ·  {tr('forgejo_visibility_private') if item['private'] else tr('forgejo_visibility_public')}"
            for item in summaries
            if item["full_name"]
        }
        forgejo_repo_select.options = options
        forgejo_repo_select.value = None
        forgejo_repo_select.update()
        append_terminal(tr("forgejo_repos_loaded", count=len(options), host=host.base_url))
        if result.truncated:
            append_terminal(tr("forgejo_repos_truncated", count=len(options)))
        set_status(tr("status_auth_ok"), "success")

    def clone_remote_repository() -> None:
        """Clone the repository from the Remote URL field next to the active project."""
        url = remote_url_from_form()
        if not url:
            append_terminal(tr("remote_fields_required"))
            set_status(tr("status_blocked"), "blocked")
            return
        try:
            git_validate_remote_url(url)
        except ValueError as exc:
            append_terminal(tr("remote_url_unsafe", error=exc))
            set_status(tr("status_blocked"), "blocked")
            return
        parent = source_root().parent
        directory = git_directory_name_from_url(url)
        if not directory:
            append_terminal(tr("clone_target_unknown", url=url))
            set_status(tr("status_blocked"), "blocked")
            return
        target = parent / directory
        if target.exists():
            # Cloning onto an existing folder is how work gets lost.
            append_terminal(tr("clone_target_exists", target=target))
            set_status(tr("status_blocked"), "blocked")
            return
        # Git reads its own credential from the store; a token sitting only in
        # the form field is invisible to it.
        if url.lower().startswith("https://") and forgejo_token_in_field():
            host = forgejo_host_from_form(quiet=True)
            if host is not None:
                stored, _probe = forgejo_service.stored_token(host, str(forgejo_login_input.value or "").strip(), cwd=current_git_root())
                if not stored:
                    append_terminal(tr("clone_needs_remembered_token"))
        append_terminal(tr("clone_started", url=url, target=target))
        set_status(tr("status_running"), "running")
        try:
            result = git_clone(parent, url)
        except Exception as exc:
            append_terminal(tr("command_failed", kind=exc.__class__.__name__, error=exc))
            set_status(tr("status_error"), "error")
            return
        log_command_result(result)
        if not result.ok:
            set_status(tr("status_error"), "error")
            return
        append_terminal(tr("clone_finished", target=target))
        set_command_status(result, "status_command_ok")

    def apply_forgejo_repository() -> None:
        full_name = str(forgejo_repo_select.value or "").strip()
        if not full_name or "/" not in full_name:
            append_terminal(tr("forgejo_repo_selection_required"))
            set_status(tr("status_blocked"), "blocked")
            return
        owner, repo = full_name.split("/", 1)
        remote_owner_input.value = owner
        remote_repo_input.value = repo
        remote_owner_input.update()
        remote_repo_input.update()
        build_remote_url_into_field()

    def create_forgejo_repository() -> None:
        host = forgejo_host_from_form()
        if host is None:
            return
        _platform, _owner, repo, _remote_name = remote_form_field_values()
        if not repo:
            append_terminal(tr("forgejo_repo_name_required"))
            set_status(tr("status_blocked"), "blocked")
            return
        private = str(remote_choice["visibility"]).strip().lower() != "public"
        set_status(tr("status_running"), "running")
        result, credential = forgejo_service.create_repo(
            host,
            repo,
            login=str(forgejo_login_input.value or "").strip(),
            private=private,
            default_branch=state.project.default_branch,
            cwd=current_git_root(),
            token=forgejo_token_in_field(),
        )
        log_credential_probe(credential)
        if result is None:
            append_terminal(tr("forgejo_no_token_anywhere", host=host.base_url))
            set_status(tr("status_blocked"), "blocked")
            return
        log_api_result(result)
        if not result.ok:
            report_forgejo_api_failure(result, host.base_url, "forgejo_repo_create_failed")
            return
        created = forgejo_api.repo_summary(result.data if isinstance(result.data, dict) else {})
        if created.get("owner"):
            remote_owner_input.value = created["owner"]
            remote_owner_input.update()
        append_terminal(
            tr(
                "forgejo_repo_created",
                name=created.get("full_name", repo),
                visibility=tr("forgejo_visibility_private") if private else tr("forgejo_visibility_public"),
            )
        )
        build_remote_url_into_field()
        set_status(tr("status_auth_ok"), "success")

    def open_forgejo_token_page() -> None:
        host = forgejo_host_from_form()
        if host is None:
            return
        url = f"{host.base_url}/user/settings/applications"
        try:
            external_apps.open_web_url(url)
        except Exception as exc:
            append_terminal(tr("command_failed", kind=exc.__class__.__name__, error=exc))
            set_status(tr("status_error"), "error")
            return
        append_terminal(tr("forgejo_tokens_page_opened", url=url))
        set_status(tr("status_auth_ok"), "success")

    def clear_forgejo_token_field() -> bool:
        """Wipe the typed token out of the form. Returns whether there was one."""
        had_token = bool(forgejo_token_in_field())
        forgejo_token_input.value = ""
        forgejo_token_input.update()
        return had_token

    def forget_forgejo_token() -> None:
        """Drop the token from both places it can live: the field and the store."""
        cleared_field = clear_forgejo_token_field()
        if cleared_field:
            append_terminal(tr("forgejo_token_field_cleared"))
        host = forgejo_host_from_form()
        if host is None:
            return
        login = str(forgejo_login_input.value or "").strip() or host.login
        if not login:
            # Helpers key credentials by host *and* username; without one the
            # erase silently matches nothing and looks like it succeeded.
            append_terminal(tr("forgejo_forget_needs_login"))
            set_status(tr("status_blocked") if not cleared_field else tr("status_auth_ok"), "blocked" if not cleared_field else "success")
            return
        result = forgejo_service.sign_out(host, login, cwd=current_git_root())
        append_terminal(f"$ {result.joined_command()}")
        if not result.ok:
            append_terminal(tr("forgejo_forget_failed", error=result.stderr or result.notes))
            set_status(tr("status_error"), "error")
            return
        append_terminal(tr("forgejo_forgotten", host=host.base_url))
        forgejo_repo_select.options = {}
        forgejo_repo_select.value = None
        forgejo_repo_select.update()
        set_forgejo_stored_state(False, "")
        update_forgejo_status_label()
        set_status(tr("status_auth_ok"), "success")

    def apply_configured_remotes() -> None:
        try:
            results = git_apply_remotes_from_config(current_git_root(), remotes_config_path())
        except Exception as exc:
            append_terminal(tr("command_failed", kind=exc.__class__.__name__, error=exc))
            set_status(tr("status_error"), "error")
            return
        log_git_result_batch(results, "status_remotes_apply_ok")
        show_remotes()

    def configure_origin_push_urls() -> None:
        try:
            results = git_configure_origin_push_urls_from_config(current_git_root(), remotes_config_path(), "origin")
        except Exception as exc:
            append_terminal(tr("command_failed", kind=exc.__class__.__name__, error=exc))
            set_status(tr("status_error"), "error")
            return
        log_git_result_batch(results, "status_origin_push_urls_ok")
        show_remotes()

    def push_all_remotes() -> None:
        results = git_push_all_remotes(current_git_root(), state.project.default_branch, follow_tags=True)
        ok = log_git_result_batch(results, "status_push_all_ok")
        if ok:
            refresh_git()

    def version_series_text() -> str:
        return str(version_series.value or "projection").strip()

    def normalized_version_text() -> str:
        parsed = parse_semver(str(version_value.value or "").strip())
        return format_semver(parsed or (0, 1, 0))

    def version_tag_text() -> str:
        return build_version_tag(version_series_text(), normalized_version_text())

    def update_next_version() -> str:
        version, result = git_next_version_for_series(current_git_root(), version_series_text(), str(version_bump_command.value or "patch"))
        log_command_result(result)
        if not result.ok:
            set_status(tr("status_error"), "error")
            return update_commit_message()
        version_value.value = version
        version_value.update()
        message = update_commit_message()
        update_basket_command_fields()
        append_terminal(tr("version_next", version=version, tag=version_tag_text()))
        set_status(tr("status_version_ok"), "success")
        return message

    def version_marker() -> str:
        return f"{version_series_text()} {normalized_version_text()}"

    def build_commit_message() -> str:
        kind = str(commit_type.value or "").strip()
        scope = str(commit_scope.value or "").strip()
        subject = str(commit_subject.value or "").strip()
        if not subject:
            return str(commit_message.value or "").strip()
        prefix = kind or "docs"
        if scope:
            prefix = f"{prefix}({scope})"
        return f"{prefix}: {version_marker()} - {subject}"

    def update_commit_message() -> str:
        message = build_commit_message()
        if message:
            commit_message.value = message
            commit_message.update()
        update_basket_command_fields()
        return message

    def queue_version_tag_command() -> None:
        tag = version_tag_text()
        message = update_commit_message() or f"{version_marker()}"
        queue_git_command(f'git tag -a "{tag}" -m "{message.replace(chr(34), chr(39))}"')

    def tag_head_version() -> None:
        tag = version_tag_text()
        message = update_commit_message() or f"{version_marker()}"
        result = git_create_annotated_tag(current_git_root(), tag, message)
        log_command_result(result)
        set_command_status(result, "status_tag_ok")

    def run_auth_doctor_panel() -> None:
        try:
            set_status(tr("status_running"), "running")
            append_terminal(tr("auth_doctor_started"))
            payload = run_auth_doctor_core(state.paths.root, repo_root=mirror_root())
            auth_box.value = json.dumps(payload, ensure_ascii=False, indent=2)
            auth_box.update()
            for probe in payload.get("probes", []):
                command = " ".join(str(part) for part in probe.get("command", []))
                append_terminal(f"$ {command}")
                output = "\n".join(str(probe.get(key, "")).strip() for key in ("stdout", "stderr") if str(probe.get(key, "")).strip())
                if output:
                    append_terminal(output)
                if probe.get("skipped"):
                    append_terminal(f"skipped: {probe.get('notes', '')}")
                append_terminal(tr("exit_code", code=probe.get("returncode")))
            preview_text.content = tr("auth_summary", probes=len(payload.get("probes", [])), remotes=len(payload.get("remotes", [])))
            preview_text.update()
            set_status(tr("status_auth_ok"), "success")
        except Exception as exc:
            append_terminal(f"ERROR auth doctor: {exc.__class__.__name__}: {exc}")
            set_status(tr("status_error"), "error")

    def run_blake3_check_panel() -> None:
        probe = state.paths.logs / ".tmp" / "blake3_probe.bin"
        try:
            set_status(tr("status_running"), "running")
            append_terminal(tr("blake3_check_started"))
            probe.parent.mkdir(parents=True, exist_ok=True)
            probe.write_bytes(b"Audion Hub Manager BLAKE3 GUI probe\n")
            digest = hash_file_blake3(probe)
            algorithm, _, value = digest.partition(":")
            payload = {
                "ok": algorithm == "blake3" and bool(value),
                "algorithm": algorithm,
                "digest": digest,
                "project_id": state.project.id,
                "probe_root": str(probe.parent),
            }
            report = write_report("blake3_check", payload, project_id=state.project.id)
            append_terminal(tr("blake3_summary", algo=algorithm, digest=digest))
            append_terminal(f"report: {report}")
            preview_text.content = tr("blake3_summary", algo=algorithm, digest=digest)
            preview_text.update()
            set_status(tr("status_blake3_ok") if payload["ok"] else tr("status_blake3_warning"), "success" if payload["ok"] else "blocked")
        except Exception as exc:
            append_terminal(f"ERROR BLAKE3 check: {exc.__class__.__name__}: {exc}")
            set_status(tr("status_error"), "error")
        finally:
            try:
                probe.unlink()
            except OSError:
                pass

    def verify_mirror_panel() -> None:
        try:
            set_status(tr("status_running"), "running")
            append_terminal(tr("mirror_verify_started", source=source_root(), target=mirror_root()))
            result = verify_projection_mirror(source_root(), mirror_root(), current_projection_profile())
            report = write_report("mirror_verify", result, project_id=state.project.id)
            summary = result["summary"]
            preview_text.content = f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2)}\n```"
            preview_text.update()
            append_terminal(
                tr(
                    "mirror_verify_summary",
                    same=summary.get("same", 0),
                    changed=summary.get("changed", 0),
                    missing=summary.get("missing", 0),
                    extra=summary.get("extra", 0),
                    errors=summary.get("errors", 0),
                )
            )
            append_terminal(tr("report", path=report))
            ok = int(summary.get("exit_code", 1)) == 0
            set_status(tr("status_mirror_verify_ok") if ok else tr("status_mirror_verify_warning"), "success" if ok else "blocked")
        except Exception as exc:
            append_terminal(f"ERROR mirror verify: {exc.__class__.__name__}: {exc}")
            set_status(tr("status_error"), "error")

    def render_small_summary(rows: list[tuple[str, Any]]) -> str:
        items = "\n".join(
            f'<div class="ahm-meta-row"><span>{escape(str(label))}</span><strong>{escape(str(value))}</strong></div>'
            for label, value in rows
        )
        return f'<div class="ahm-meta-grid">{items}</div>'

    def run_storage_layout_panel() -> None:
        try:
            set_status(tr("status_running"), "running")
            payload = storage_layout_status(state.paths.root, state.registry.projects)
            state.storage_payload = payload
            storage_box.value = json.dumps(payload, ensure_ascii=False, indent=2)
            storage_box.update()
            storage_summary_box.content = render_small_summary(
                [
                    (tr("storage_ok"), payload.get("ok")),
                    (tr("storage_projects"), len(payload.get("projects", []))),
                    (tr("storage_root"), state.paths.root),
                    (tr("storage_workspace"), state.paths.workspace),
                ]
            )
            storage_summary_box.update()
            preview_text.content = tr("storage_summary", ok=payload.get("ok"), projects=len(payload.get("projects", [])))
            preview_text.update()
            append_terminal(tr("storage_doctor_ok", ok=payload.get("ok")))
            set_status(tr("status_storage_ok") if payload.get("ok") else tr("status_blocked"), "success" if payload.get("ok") else "blocked")
        except Exception as exc:
            append_terminal(f"ERROR storage layout: {exc.__class__.__name__}: {exc}")
            set_status(tr("status_error"), "error")

    def scan_projects_panel() -> None:
        try:
            try:
                default_source_parent = source_root().parent
            except Exception:
                default_source_parent = state.paths.root.parent
            selected = _pick_directory(default_source_parent, tr("scan_projects_title"))
        except Exception as exc:
            append_terminal(tr("scan_projects_failed", error=exc))
            set_status(tr("status_error"), "error")
            return
        if selected is None:
            return
        try:
            set_status(tr("status_running"), "running")
            payload = projects_payload()
            docs_root = effective_location("docs").parent if state.project.docs_path is not None else None
            entries = scan_project_folder(
                selected,
                mirror_root().parent,
                docs_root=docs_root,
            )
            portable_entries = [normalize_project_entry_paths(entry) for entry in entries]
            updated, added, skipped = merge_project_import(payload, portable_entries)
            save_json(projects_config_path(), updated)
            previous_project_id = state.project.id
            state.registry = load_project_registry()
            try:
                state.project = state.registry.by_id(previous_project_id)
            except KeyError:
                state.project = state.registry.active_project()
            update_project_select_options()
            result = {
                "scan_root": str(selected),
                "hub_root": str(mirror_root().parent),
                "docs_root": str(docs_root or ""),
                "summary": {
                    "candidates": len(entries),
                    "imported": added,
                    "skipped": skipped,
                },
                "candidates": entries,
            }
            state.storage_payload = result
            report = write_report("project_scan", result, project_id=state.project.id)
            storage_box.value = json.dumps(result, ensure_ascii=False, indent=2)
            storage_box.update()
            storage_summary_box.content = render_small_summary(
                [
                    (tr("scan_projects_candidates"), len(entries)),
                    (tr("scan_projects_imported"), added),
                    (tr("scan_projects_skipped"), skipped),
                    (tr("storage_root"), selected),
                ]
            )
            storage_summary_box.update()
            append_terminal(tr("projects_scan_imported", added=added, skipped=skipped, candidates=len(entries)))
            append_terminal(tr("report", path=report))
            set_status(tr("status_storage_ok"), "success")
        except Exception as exc:
            append_terminal(f"ERROR project scan: {exc.__class__.__name__}: {exc}")
            set_status(tr("status_error"), "error")

    def clean_projects_config_panel() -> None:
        try:
            set_status(tr("status_running"), "running")
            payload = projects_payload()
            cleaned: list[dict[str, Any]] = []
            removed: list[dict[str, str]] = []
            seen_ids: set[str] = set()
            seen_sources: set[str] = set()
            for item in payload.get("projects", []):
                if not isinstance(item, dict):
                    removed.append({"id": "", "title": "", "reason": "invalid record"})
                    continue
                project = ProjectEntry.from_dict(item)
                source_key = str(project.source_path).lower()
                if not project.source_path.is_dir():
                    removed.append({"id": project.id, "title": project.title, "reason": f"missing source: {project.source_path}"})
                    continue
                if project.id in seen_ids:
                    removed.append({"id": project.id, "title": project.title, "reason": "duplicate id"})
                    continue
                if source_key in seen_sources:
                    removed.append({"id": project.id, "title": project.title, "reason": f"duplicate source: {project.source_path}"})
                    continue
                seen_ids.add(project.id)
                seen_sources.add(source_key)
                cleaned.append(item)
            payload["projects"] = cleaned
            active_id = str(payload.get("active_project_id", "")).strip()
            clean_ids = {str(item.get("id", "")).strip() for item in cleaned if isinstance(item, dict)}
            if active_id not in clean_ids:
                payload["active_project_id"] = str(cleaned[0].get("id", "")) if cleaned else ""
            save_json(projects_config_path(), payload)
            previous_project_id = state.project.id
            state.registry = load_project_registry()
            if state.registry.projects:
                try:
                    state.project = state.registry.by_id(previous_project_id)
                except KeyError:
                    state.project = state.registry.active_project()
            update_project_select_options()
            state.current_plan = None
            set_source_tree_badge(tr("project_tree_status_idle"))
            result = {
                "config": str(projects_config_path()),
                "summary": {
                    "kept": len(cleaned),
                    "removed": len(removed),
                    "active_project_id": payload.get("active_project_id", ""),
                },
                "removed": removed,
            }
            state.storage_payload = result
            report = write_report("projects_config_clean", result, project_id=state.project.id if state.registry.projects else "none")
            storage_box.value = json.dumps(result, ensure_ascii=False, indent=2)
            storage_box.update()
            storage_summary_box.content = render_small_summary(
                [
                    (tr("projects_config_kept"), len(cleaned)),
                    (tr("projects_config_removed"), len(removed)),
                    (tr("project"), payload.get("active_project_id", "")),
                    (tr("storage_ok"), True),
                ]
            )
            storage_summary_box.update()
            append_terminal(tr("projects_config_cleaned", kept=len(cleaned), removed=len(removed)))
            append_terminal(tr("report", path=report))
            set_status(tr("status_storage_ok"), "success")
            refresh_tree()
        except Exception as exc:
            append_terminal(f"ERROR projects config clean: {exc.__class__.__name__}: {exc}")
            set_status(tr("status_error"), "error")

    def copy_storage_json() -> None:
        payload = state.storage_payload or storage_layout_status(state.paths.root, state.registry.projects)
        ui.clipboard.write(json.dumps(payload, ensure_ascii=False, indent=2))
        append_terminal(tr("storage_copied"))
        set_status(tr("status_storage_ok"), "success")

    def run_safety_scan_panel() -> None:
        try:
            set_status(tr("status_running"), "running")
            root = current_tree_root()
            append_terminal(tr("safety_scan_started", root=root))
            payload = scan_safety(root)
            payload["project_id"] = state.project.id
            payload["root_role"] = state.tree_scope
            report = write_report("safety_scan", payload, project_id=state.project.id)
            state.safety_payload = payload
            safety_box.value = json.dumps(payload, ensure_ascii=False, indent=2)
            safety_box.update()
            summary = payload.get("summary", {})
            safety_summary_box.content = render_small_summary(
                [
                    (tr("safety_findings"), summary.get("findings", 0)),
                    (tr("safety_blockers"), summary.get("blockers", 0)),
                    (tr("safety_warnings"), summary.get("warnings", 0)),
                    (tr("safety_root"), root),
                ]
            )
            safety_summary_box.update()
            preview_text.content = tr(
                "safety_summary",
                findings=summary.get("findings", 0),
                blockers=summary.get("blockers", 0),
                warnings=summary.get("warnings", 0),
            )
            preview_text.update()
            append_terminal(
                tr(
                    "safety_summary",
                    findings=summary.get("findings", 0),
                    blockers=summary.get("blockers", 0),
                    warnings=summary.get("warnings", 0),
                )
            )
            append_terminal(tr("report", path=report))
            if summary.get("blockers", 0):
                set_status(tr("status_safety_blocked"), "blocked")
            elif summary.get("warnings", 0) or summary.get("errors", 0):
                set_status(tr("status_safety_warning"), "error")
            else:
                set_status(tr("status_safety_ok"), "success")
        except Exception as exc:
            append_terminal(f"ERROR safety scan: {exc.__class__.__name__}: {exc}")
            set_status(tr("status_error"), "error")

    def copy_safety_json() -> None:
        payload = state.safety_payload or {"summary": {}, "findings": []}
        ui.clipboard.write(json.dumps(payload, ensure_ascii=False, indent=2))
        append_terminal(tr("safety_copied"))
        set_status(tr("status_safety_ok"), "success")

    def generate_workspace_file() -> None:
        folders = [
            {"name": "Audion Hub Manager", "path": str(state.paths.root)},
            {"name": f"{state.project.title} Source", "path": str(source_root())},
            {"name": f"{state.project.title} Hub", "path": str(mirror_root())},
        ]
        if state.project.docs_path is not None:
            folders.append({"name": f"{state.project.title} Docs", "path": str(effective_location("docs"))})
        payload = {
            "folders": folders,
            "settings": {
                "files.exclude": {
                    "**/.git": False,
                }
            },
        }
        target = state.paths.workspace / "audion_hub_layers.code-workspace"
        save_json(target, payload)
        append_terminal(tr("workspace_generated", path=target))
        state.storage_payload = {"workspace": str(target), **payload}
        storage_box.value = json.dumps(state.storage_payload, ensure_ascii=False, indent=2)
        storage_box.update()
        storage_summary_box.content = render_small_summary(
            [
                (tr("storage_workspace"), target),
                (tr("storage_folders"), len(payload["folders"])),
                (tr("storage_ok"), True),
                (tr("storage_root"), state.paths.root),
            ]
        )
        storage_summary_box.update()
        set_status(tr("status_command_ok"), "success")

    def open_generated_workspace() -> None:
        target = state.paths.workspace / "audion_hub_layers.code-workspace"
        if not target.exists():
            generate_workspace_file()
        external_apps.open_default(target)
        append_terminal(tr("workspace_opened", path=target))
        set_status(tr("status_storage_ok"), "success")

    def dedupe_workspace_folders(folders: list[dict[str, str]]) -> list[dict[str, str]]:
        seen: set[str] = set()
        unique: list[dict[str, str]] = []
        for folder in folders:
            path = str(folder.get("path", "")).strip()
            if not path:
                continue
            key = str(Path(path)).lower()
            if key in seen:
                continue
            seen.add(key)
            unique.append(folder)
        return unique

    def generate_combined_workspace_file() -> None:
        folders: list[dict[str, str]] = [{"name": "Audion Hub Manager", "path": str(state.paths.root)}]
        for project in state.registry.projects:
            folders.extend(
                [
                    {"name": f"{project.title} Source", "path": str(project.source_path)},
                    {"name": f"{project.title} Hub", "path": str(project.projection_path)},
                ]
            )
            if project.docs_path is not None:
                folders.append({"name": f"{project.title} Docs", "path": str(project.docs_path)})
        payload = {
            "folders": dedupe_workspace_folders(folders),
            "settings": {"files.exclude": {"**/.git": False}},
        }
        target = state.paths.workspace / "audion_hub_all_projects.code-workspace"
        save_json(target, payload)
        append_terminal(tr("combined_workspace_generated", path=target, folders=len(payload["folders"])))
        state.storage_payload = {"workspace": str(target), **payload}
        storage_box.value = json.dumps(state.storage_payload, ensure_ascii=False, indent=2)
        storage_box.update()
        storage_summary_box.content = render_small_summary(
            [
                (tr("storage_workspace"), target),
                (tr("storage_folders"), len(payload["folders"])),
                (tr("storage_projects"), len(state.registry.projects)),
                (tr("storage_ok"), True),
            ]
        )
        storage_summary_box.update()
        set_status(tr("status_storage_ok"), "success")

    EDITOR_EXTENSIONS = {".md", ".markdown", ".txt", ".rst"}

    def editor_supported(path: Path) -> bool:
        return path.is_file() and path.suffix.lower() in EDITOR_EXTENSIONS

    def editor_value() -> str:
        return str(getattr(markdown_editor, "value", "") or "")

    def set_editor_value(text: str) -> None:
        markdown_editor.value = text
        markdown_editor.update()
        refresh_editor_layout()

    def refresh_editor_layout() -> None:
        ui.run_javascript(
            "setTimeout(() => { window.dispatchEvent(new Event('resize')); "
            "document.querySelectorAll('.cm-editor').forEach(e => e.dispatchEvent(new Event('resize'))); }, 80);"
        )

    def update_editor_path_label() -> None:
        editor_path_label.text = str(state.editor_path) if state.editor_path else tr("editor_no_file")
        editor_path_label.update()

    def load_path_into_editor(path: Path, *, quiet: bool = False) -> None:
        if not editor_supported(path):
            return
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            append_terminal(tr("editor_load_failed", error=exc))
            set_status(tr("status_error"), "error")
            return
        state.editor_path = path
        set_editor_value(text)
        update_editor_path_label()
        if not quiet:
            append_terminal(tr("editor_loaded", path=path))
            set_status(tr("status_editor_ok"), "success")

    def load_selected_into_editor() -> None:
        if not state.selected_path:
            append_terminal(tr("editor_no_selected_file"))
            set_status(tr("status_blocked"), "blocked")
            return
        path = current_tree_root() / state.selected_path
        if not editor_supported(path):
            append_terminal(tr("editor_unsupported_file", path=path))
            set_status(tr("status_blocked"), "blocked")
            return
        load_path_into_editor(path)

    def save_editor_file() -> None:
        if state.editor_path is None:
            append_terminal(tr("editor_no_file"))
            set_status(tr("status_blocked"), "blocked")
            return
        try:
            state.editor_path.write_text(editor_value(), encoding="utf-8", newline="")
        except OSError as exc:
            append_terminal(tr("editor_save_failed", error=exc))
            set_status(tr("status_error"), "error")
            return
        append_terminal(tr("editor_saved", path=state.editor_path))
        set_status(tr("status_editor_ok"), "success")
        refresh_tree()

    def copy_editor_text() -> None:
        ui.clipboard.write(editor_value())
        append_terminal(tr("editor_copied"))
        set_status(tr("status_editor_ok"), "success")

    def paste_editor_text() -> None:
        commands = (
            ["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
            ["pwsh", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
        )
        last_error = ""
        for command in commands:
            try:
                result = subprocess.run(command, capture_output=True, text=True, timeout=5)
            except Exception as exc:
                last_error = str(exc)
                continue
            if result.returncode == 0:
                text = result.stdout
                if not text:
                    append_terminal(tr("editor_clipboard_empty"))
                    set_status(tr("status_blocked"), "blocked")
                    return
                set_editor_value(f"{editor_value()}{text}")
                append_terminal(tr("editor_pasted"))
                set_status(tr("status_editor_ok"), "success")
                return
            last_error = result.stderr.strip()
        append_terminal(tr("editor_paste_failed", error=last_error or "clipboard unavailable"))
        set_status(tr("status_error"), "error")

    def clear_editor_text() -> None:
        set_editor_value("")
        append_terminal(tr("editor_cleared"))
        set_status(tr("status_editor_ok"), "success")

    def open_editor_file_vscode() -> None:
        if state.editor_path is None:
            append_terminal(tr("editor_no_file"))
            set_status(tr("status_blocked"), "blocked")
            return
        try:
            external_apps.open_in_vscode(state.editor_path)
            append_terminal(tr("opened_selected_vscode", target=state.editor_path))
            set_status(tr("status_editor_ok"), "success")
        except Exception as exc:
            append_terminal(tr("open_selected_failed", error=exc))
            set_status(tr("status_error"), "error")

    def projection_profile_for_project(project: ProjectEntry):
        profile = get_projection_profile(project.profile)
        return replace(
            profile,
            mirror=bool(exact_mirror.value),
            preserve_empty_dirs=bool(preserve_empty.value),
            compare_mode="strict_blake3" if bool(hash_compare.value) else "quick",
        )

    def current_projection_profile():
        return projection_profile_for_project(state.project)

    def set_source_tree_badge(text: str) -> None:
        value = str(text or "").upper()
        state.source_tree_status = value
        source_tree_badge.text = value
        source_tree_badge.update()

    def show_batch_payload(kind: str, payload: dict[str, Any]) -> None:
        state.storage_payload = payload
        report = write_report(kind, payload, project_id=state.project.id)
        storage_box.value = json.dumps(payload, ensure_ascii=False, indent=2)
        storage_box.update()
        summary = payload.get("summary", {})
        storage_summary_box.content = render_small_summary(
            [
                (tr("storage_projects"), summary.get("projects", len(payload.get("results", [])))),
                (tr("batch_errors"), summary.get("errors", 0)),
                (tr("batch_operation"), payload.get("operation", kind)),
                (tr("storage_ok"), int(summary.get("errors", 0)) == 0),
            ]
        )
        storage_summary_box.update()
        preview_text.content = f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2)}\n```"
        preview_text.update()
        append_terminal(tr("batch_complete", operation=payload.get("operation", kind), projects=summary.get("projects", 0), errors=summary.get("errors", 0)))
        append_terminal(tr("report", path=report))
        set_status(tr("status_storage_ok") if int(summary.get("errors", 0)) == 0 else tr("status_blocked"), "success" if int(summary.get("errors", 0)) == 0 else "blocked")

    def batch_preview_mirror_all() -> None:
        set_status(tr("status_running"), "running")
        results: list[dict[str, Any]] = []
        totals = {"projects": 0, "copy": 0, "delete": 0, "touch": 0, "same": 0, "errors": 0}
        for project in state.registry.projects:
            item: dict[str, Any] = {
                "project_id": project.id,
                "title": project.title,
                "source": str(project.source_path),
                "hub": str(project.projection_path),
            }
            try:
                plan = plan_projection(project.source_path, project.projection_path, projection_profile_for_project(project))
                summary = plan.get("summary", {})
                item["summary"] = summary
                for key in ("copy", "delete", "touch", "same"):
                    totals[key] += int(summary.get(key, 0))
            except Exception as exc:
                totals["errors"] += 1
                item["error"] = f"{exc.__class__.__name__}: {exc}"
            results.append(item)
        totals["projects"] = len(results)
        show_batch_payload("batch_projection_plan", {"operation": "Batch Preview MIRROR", "summary": totals, "results": results})

    def batch_safety_scan_all() -> None:
        set_status(tr("status_running"), "running")
        results: list[dict[str, Any]] = []
        totals = {"projects": 0, "findings": 0, "blockers": 0, "warnings": 0, "errors": 0}
        for project in state.registry.projects:
            item: dict[str, Any] = {"project_id": project.id, "title": project.title, "source": str(project.source_path)}
            try:
                payload = scan_safety(project.source_path)
                summary = payload.get("summary", {})
                item["summary"] = summary
                for key in ("findings", "blockers", "warnings", "errors"):
                    totals[key] += int(summary.get(key, 0))
            except Exception as exc:
                totals["errors"] += 1
                item["error"] = f"{exc.__class__.__name__}: {exc}"
            results.append(item)
        totals["projects"] = len(results)
        show_batch_payload("batch_safety_scan", {"operation": "Batch Safety Scan", "root_role": "source", "summary": totals, "results": results})

    def batch_verify_mirror_all() -> None:
        set_status(tr("status_running"), "running")
        results: list[dict[str, Any]] = []
        totals = {"projects": 0, "same": 0, "changed": 0, "missing": 0, "extra": 0, "errors": 0}
        for project in state.registry.projects:
            item: dict[str, Any] = {
                "project_id": project.id,
                "title": project.title,
                "source": str(project.source_path),
                "hub": str(project.projection_path),
            }
            try:
                result = verify_projection_mirror(project.source_path, project.projection_path, projection_profile_for_project(project))
                summary = result.get("summary", {})
                item["summary"] = summary
                for key in ("same", "changed", "missing", "extra", "errors"):
                    totals[key] += int(summary.get(key, 0))
            except Exception as exc:
                totals["errors"] += 1
                item["error"] = f"{exc.__class__.__name__}: {exc}"
            results.append(item)
        totals["projects"] = len(results)
        show_batch_payload("batch_mirror_verify", {"operation": "Batch Verify Mirror", "summary": totals, "results": results})

    def batch_git_status_all() -> None:
        set_status(tr("status_running"), "running")
        results: list[dict[str, Any]] = []
        totals = {"projects": 0, "clean": 0, "dirty": 0, "errors": 0}
        for project in state.registry.projects:
            item: dict[str, Any] = {"project_id": project.id, "title": project.title, "source": str(project.source_path)}
            try:
                stat, command = git_status(project.source_path)
                item.update(
                    {
                        "ok": command.ok,
                        "branch": stat.branch,
                        "ahead": stat.ahead,
                        "behind": stat.behind,
                        "files": len(stat.files),
                        "stderr": command.stderr.strip(),
                    }
                )
                if command.ok and not stat.files:
                    totals["clean"] += 1
                elif command.ok:
                    totals["dirty"] += 1
                else:
                    totals["errors"] += 1
            except Exception as exc:
                totals["errors"] += 1
                item["error"] = f"{exc.__class__.__name__}: {exc}"
            results.append(item)
        totals["projects"] = len(results)
        set_source_tree_badge(
            tr(
                "project_tree_status_summary",
                projects=totals["projects"],
                clean=totals["clean"],
                dirty=totals["dirty"],
                errors=totals["errors"],
            )
        )
        show_batch_payload("batch_git_status", {"operation": "Batch Git status", "root_role": "source", "summary": totals, "results": results})

    def filter_tree(nodes: list[dict]) -> list[dict]:
        query = str(search.value or "").strip().lower()
        hide_clean_enabled = bool(hide_clean.value)

        def keep(node: dict) -> dict | None:
            children = [item for child in node.get("children", []) if (item := keep(child))]
            label = str(node.get("label", ""))
            path = str(node.get("path", node.get("id", "")))
            status = str(node.get("status", "clean"))
            matches_query = not query or query in label.lower() or query in path.lower()
            matches_status = not hide_clean_enabled or status != "clean" or bool(children)
            if (matches_query and matches_status) or children:
                clone = dict(node)
                if children:
                    clone["children"] = children
                else:
                    clone.pop("children", None)
                return clone
            return None

        return [item for node in nodes if (item := keep(node))]

    def refresh_git_status_cache(root: Path) -> None:
        try:
            stat, command = git_status(root)
        except Exception as exc:
            state.git_status_map = {}
            state.git_status_root = root
            set_status(tr("status_error"), "error")
            append_terminal(f"ERROR git status: {exc.__class__.__name__}: {exc}")
            return
        state.git_status_map = stat.status_map() if command.ok else {}
        state.git_status_root = root
        build_header_status_indicator(header_status_slot)
        if not command.ok:
            set_status(tr("status_error"), "error")

    def current_tree_root() -> Path:
        return effective_location(state.tree_scope)

    def update_tree_expanded(expanded: list[str]) -> None:
        next_expanded = {str(item) for item in expanded if str(item).strip()}
        next_expanded.add(".")
        if next_expanded != state.tree_expanded:
            state.tree_expanded = next_expanded
            refresh_tree()

    def refresh_tree(*, log: bool = True) -> None:
        tree_holder.clear()
        root = current_tree_root()
        if not same_root(state.current_tree_root, root):
            state.tree_expanded = {"."}
        state.current_tree_root = root
        view = str(view_select.value or "Full Tree")
        status_filters = {
            "Staged": {"staged"},
            "Untracked": {"untracked"},
            "Conflicts": {"conflict"},
        }
        status_views = {"Changed Only", *status_filters.keys()}
        if view in status_views:
            refresh_git_status_cache(root)
        tree_status_map = state.git_status_map if same_root(state.git_status_root, root) else {}
        if view == "Changed Only":
            nodes = changed_tree(tree_status_map) if tree_status_map else []
            nodes = nodes[0].get("children", []) if nodes else []
        elif view in status_filters:
            wanted = status_filters[view]
            filtered = {path: status for path, status in tree_status_map.items() if status in wanted}
            nodes = changed_tree(filtered) if filtered else []
            nodes = nodes[0].get("children", []) if nodes else []
        elif str(search.value or "").strip() and not bool(top_level_search.value):
            nodes = build_search_tree(
                root,
                query=str(search.value or ""),
                status_map=tree_status_map,
                show_hidden=bool(show_hidden.value),
                hide_clean=bool(hide_clean.value),
            )
        else:
            nodes = build_lazy_tree(root, expanded=state.tree_expanded, status_map=tree_status_map, show_hidden=bool(show_hidden.value))
        nodes = filter_tree(nodes)
        with tree_holder:
            if not nodes:
                message = tr("no_tree_matches") if root.exists() and root.is_dir() else tr("no_tree_missing", root=root)
                ui.label(message).classes("ahm-muted")
            else:
                tree = ui.tree(
                    nodes,
                    label_key="label",
                    node_key="id",
                    on_select=lambda e: select_path(str(e.value or "")),
                    on_expand=lambda e: update_tree_expanded(list(e.value or [])),
                ).props("dense no-selection-unset")
                tree.add_slot(
                    "default-header",
                    """
                    <div
                      :data-path="props.node.id"
                      :class="[
                        'ahm-tree-node-header',
                        'ahm-tree-node-' + (props.node.kind || 'node'),
                        props.node.editorPreview ? 'ahm-tree-node-editor' : '',
                        props.node.diffPreview ? 'ahm-tree-node-diff' : '',
                        props.node.status ? 'ahm-tree-status-' + props.node.status : ''
                      ]"
                    >
                      <q-icon
                        v-if="props.node.icon"
                        :name="props.node.icon"
                        class="ahm-git-status-dot"
                        :style="{ color: props.node.iconColor }"
                      />
                      <q-icon
                        v-if="props.node.kindIcon"
                        :name="props.node.kindIcon"
                        class="ahm-tree-kind-icon"
                      />
                      <span class="ahm-tree-node-label">{{ props.node.label }}</span>
                      <span
                        v-if="props.node.statusSummary"
                        class="ahm-tree-status-summary"
                      >{{ props.node.statusSummary }}</span>
                      <q-icon
                        v-if="props.node.editorPreview"
                        name="edit_note"
                        class="ahm-tree-hover-hint ahm-tree-hover-editor"
                      />
                      <q-icon
                        v-if="props.node.diffPreview"
                        name="difference"
                        class="ahm-tree-hover-hint ahm-tree-hover-diff"
                      />
                      <q-btn
                        dense
                        flat
                        round
                        size="xs"
                        icon="open_in_new"
                        class="ahm-tree-open-vscode"
                        title="Open in VS Code"
                      />
                    </div>
                    """,
                )
                tree.expand(sorted(state.tree_expanded))
                if state.selected_path:
                    tree.select(state.selected_path)
                tree.on("select-node", lambda e: select_path(tree_event_path(e.args)))
                tree.on("open-editor", lambda e: open_tree_node_editor(e.args))
                tree.on("open-vscode", lambda e: open_tree_node_vscode(e.args))
                tree.on(
                    "click.capture",
                    lambda e: select_path(tree_event_path(e.args)),
                    js_handler="""
                    (event) => {
                      if (event.target.closest('.ahm-tree-open-vscode')) return;
                      const header = event.target.closest('.ahm-tree-node-header[data-path]');
                      if (!header) return;
                      emit(header.dataset.path || '');
                    }
                    """,
                )
                tree.on(
                    "dblclick.capture",
                    lambda e: open_tree_node_editor(e.args),
                    js_handler="""
                    (event) => {
                      const header = event.target.closest('.ahm-tree-node-header[data-path]');
                      if (!header) return;
                      event.preventDefault();
                      event.stopPropagation();
                      emit(header.dataset.path || '');
                    }
                    """,
                )
                tree.on(
                    "click.capture",
                    lambda e: open_tree_node_vscode(e.args),
                    js_handler="""
                    (event) => {
                      const button = event.target.closest('.ahm-tree-open-vscode');
                      if (!button) return;
                      event.preventDefault();
                      event.stopPropagation();
                      const header = button.closest('.ahm-tree-node-header[data-path]');
                      emit(header?.dataset.path || '');
                    }
                    """,
                )
        if log:
            append_terminal(tr("tree_refreshed", root=root))
        set_status(tr("status_ready"), "idle")

    def format_file_size(size: int | None) -> str:
        if size is None:
            return tr("metadata_empty_value")
        value = float(size)
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024 or unit == "GB":
                return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
            value /= 1024
        return f"{int(size)} B"

    def selected_full_path() -> Path:
        return state.current_tree_root / state.selected_path if state.selected_path else state.current_tree_root

    def copy_selected_relative_path() -> None:
        if not state.selected_path:
            append_terminal(tr("no_selected_path"))
            set_status(tr("status_blocked"), "blocked")
            return
        ui.clipboard.write(state.selected_path)
        append_terminal(tr("path_copied", path=state.selected_path))
        set_status(tr("status_command_ok"), "success")

    def copy_selected_full_path() -> None:
        target = selected_full_path()
        ui.clipboard.write(str(target))
        append_terminal(tr("path_copied", path=target))
        set_status(tr("status_command_ok"), "success")

    def metadata_for_selection() -> dict[str, Any]:
        root = state.current_tree_root
        rel_path = state.selected_path
        full = selected_full_path()
        payload: dict[str, Any] = {
            "project_id": state.project.id,
            "project_title": state.project.title,
            "tree_scope": state.tree_scope,
            "root": str(root),
            "relative_path": rel_path or ".",
            "absolute_path": str(full),
            "exists": full.exists(),
            "git_status": state.git_status_map.get(rel_path, "clean" if rel_path else "root"),
            "git_root": str(current_git_root()),
            "editor_supported": editor_supported(full) if full.exists() else False,
        }
        if full.exists():
            try:
                stat = full.stat()
                payload.update(
                    {
                        "is_file": full.is_file(),
                        "is_dir": full.is_dir(),
                        "suffix": full.suffix,
                        "size": stat.st_size,
                        "size_human": format_file_size(stat.st_size),
                        "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                    }
                )
            except OSError as exc:
                payload["stat_error"] = str(exc)
        if rel_path and full.is_file() and same_root(state.git_status_root, current_git_root()):
            result = git_run(current_git_root(), "hash-object", "--", rel_path)
            if result.ok:
                payload["git_blob"] = result.stdout.strip()
        return payload

    def render_metadata_summary(payload: dict[str, Any]) -> str:
        rows = [
            (tr("metadata_project"), str(payload.get("project_title", ""))),
            (tr("metadata_scope"), str(payload.get("tree_scope", ""))),
            (tr("metadata_path"), str(payload.get("relative_path", ""))),
            (tr("metadata_status"), str(payload.get("git_status", ""))),
            (tr("metadata_type"), tr("metadata_type_dir") if payload.get("is_dir") else tr("metadata_type_file") if payload.get("is_file") else tr("metadata_type_missing")),
            (tr("metadata_size"), str(payload.get("size_human") or tr("metadata_empty_value"))),
            (tr("metadata_modified"), str(payload.get("mtime") or tr("metadata_empty_value"))),
            (tr("metadata_git_blob"), str(payload.get("git_blob") or tr("metadata_empty_value"))),
        ]
        items = "\n".join(
            f'<div class="ahm-meta-row"><span>{escape(label)}</span><strong>{escape(value)}</strong></div>'
            for label, value in rows
        )
        return f'<div class="ahm-meta-grid">{items}</div>'

    def set_metadata_payload(payload: dict[str, Any]) -> None:
        state.metadata_payload = payload
        meta_summary.content = render_metadata_summary(payload)
        meta_summary.update()
        meta_box.value = json.dumps(payload, ensure_ascii=False, indent=2)
        meta_box.update()

    def refresh_metadata_panel() -> None:
        payload = metadata_for_selection()
        set_metadata_payload(payload)
        append_terminal(tr("metadata_refreshed", path=payload.get("relative_path", ".")))
        set_status(tr("status_metadata_ok"), "success")

    def copy_metadata_json() -> None:
        ui.clipboard.write(json.dumps(state.metadata_payload or metadata_for_selection(), ensure_ascii=False, indent=2))
        append_terminal(tr("metadata_copied"))
        set_status(tr("status_metadata_ok"), "success")

    def render_history_html(text: str, mode: str) -> str:
        lines = str(text or "").splitlines()
        if not lines:
            lines = [tr("history_empty")]
        rendered = ['<pre class="ahm-history-pre">']
        for line in lines:
            css = "ahm-history-line"
            if mode == "graph":
                css += " ahm-history-graph-line"
            parts = line.split("\t", 3)
            if mode in {"selected", "repo"} and len(parts) == 4:
                rendered.append(
                    '<span class="ahm-history-commit">'
                    f'<span class="ahm-history-hash">{escape(parts[0])}</span>'
                    f'<span class="ahm-history-date">{escape(parts[1])}</span>'
                    f'<span class="ahm-history-author">{escape(parts[2])}</span>'
                    f'<span class="ahm-history-subject">{escape(parts[3])}</span>'
                    "</span>"
                )
            else:
                rendered.append(f'<span class="{css}">{escape(line)}</span>')
        rendered.append("</pre>")
        return "".join(rendered)

    def set_history_text(text: str, mode: str) -> None:
        state.history_text = text or tr("history_empty")
        history_box.content = render_history_html(state.history_text, mode)
        history_box.update()
        count = len([line for line in state.history_text.splitlines() if line.strip()])
        history_stats_label.text = tr("history_stats", mode=mode, count=count)
        history_stats_label.update()

    def show_history(mode: str) -> None:
        root = current_git_root()
        path = state.selected_path
        if mode == "selected" and not path:
            append_terminal(tr("history_no_path"))
            set_status(tr("status_blocked"), "blocked")
            return
        if mode == "selected":
            result = git_run(root, "log", "--date=short", "--pretty=format:%h%x09%ad%x09%an%x09%s", "-40", "--", path)
            history_path_label.text = tr("history_path_label", mode=mode, path=path)
        elif mode == "graph":
            result = git_run(root, "log", "--graph", "--oneline", "--decorate", "--all", "-50")
            history_path_label.text = tr("history_path_label", mode=mode, path=".")
        elif mode == "tags":
            result = git_run(root, "tag", "-n", "--sort=-creatordate")
            history_path_label.text = tr("history_path_label", mode=mode, path="tags")
        else:
            result = git_run(root, "log", "--date=short", "--pretty=format:%h%x09%ad%x09%an%x09%s", "-50")
            history_path_label.text = tr("history_path_label", mode="repo", path=".")
        history_path_label.update()
        log_command_result(result)
        set_history_text(result.stdout or result.stderr, mode)
        set_command_status(result, "status_history_ok")

    def copy_history_text() -> None:
        ui.clipboard.write(state.history_text)
        append_terminal(tr("history_copied"))
        set_status(tr("status_history_ok"), "success")

    def selection_status(rel_path: str) -> str:
        if not rel_path:
            return "clean"
        if rel_path in state.git_status_map:
            return state.git_status_map[rel_path]
        prefix = rel_path.rstrip("/") + "/"
        child_statuses = {status for path, status in state.git_status_map.items() if path.startswith(prefix)}
        for status in ("conflict", "staged", "modified", "untracked", "changed"):
            if status in child_statuses:
                return status
        return "clean"

    def activate_inspector_tab(target: Any) -> None:
        tab_panels.value = target
        tab_panels.update()
        refresh_editor_layout()

    def select_path(rel_path: str) -> None:
        rel_path = rel_path.strip("'\"")
        if not rel_path:
            return
        if rel_path == ".__lazy__" or rel_path.endswith("/.__lazy__"):
            return
        state.selected_path = rel_path if rel_path != "." else ""
        selected_label.text = f"{tr('selected')}: {state.selected_path or '.'}"
        selected_label.update()
        payload = metadata_for_selection()
        set_metadata_payload(payload)
        history_path_label.text = tr("history_path_label", mode="selected", path=state.selected_path or ".")
        history_path_label.update()
        refresh_selected_diff_preview()

    def open_tree_node_editor(value: Any) -> None:
        rel_path = tree_event_path(value)
        if rel_path in {"", "."} or rel_path == ".__lazy__" or rel_path.endswith("/.__lazy__"):
            return
        select_path(rel_path)
        path = current_tree_root() / state.selected_path
        if editor_supported(path):
            load_path_into_editor(path)
            activate_inspector_tab(tab_editor)
            return
        if path.is_file():
            open_tree_node_vscode(rel_path)

    def preview_mirror() -> None:
        try:
            set_status(tr("status_running"), "running")
            append_terminal(f"PLAN MIRROR: {source_root()} -> {mirror_root()}")
            plan = plan_projection(source_root(), mirror_root(), current_projection_profile())
            state.current_plan = plan
            report = write_report("projection_plan", plan, project_id=state.project.id)
            preview_text.content = f"```json\n{json.dumps(plan['summary'], ensure_ascii=False, indent=2)}\n```"
            preview_text.update()
            append_terminal(tr("plan_ok", copy=plan["summary"]["copy"], delete=plan["summary"]["delete"], touch=plan["summary"]["touch"], same=plan["summary"]["same"]))
            append_terminal(tr("report", path=report))
            set_status(tr("status_plan_ok"), "success")
        except Exception as exc:
            append_terminal(f"ERROR plan MIRROR: {exc.__class__.__name__}: {exc}")
            set_status(tr("status_error"), "error")
            ui.notify(str(exc), type="negative")

    def apply_mirror() -> None:
        try:
            set_status(tr("status_running"), "running")
            if state.current_plan is None:
                preview_mirror()
            if state.current_plan is None:
                return
            append_terminal(tr("apply_started"))
            result = apply_projection_plan(state.current_plan, dry_run=bool(dry_run.value))
            report = write_report("projection_apply", result, project_id=state.project.id)
            preview_text.content = f"```json\n{json.dumps(result['summary'], ensure_ascii=False, indent=2)}\n```"
            preview_text.update()
            append_terminal(tr("apply_ok", summary=json.dumps(result["summary"], ensure_ascii=False)))
            append_terminal(tr("report", path=report))
            refresh_tree()
            set_status(tr("status_apply_ok"), "success")
        except Exception as exc:
            append_terminal(f"ERROR apply MIRROR: {exc.__class__.__name__}: {exc}")
            set_status(tr("status_error"), "error")
            ui.notify(str(exc), type="negative")

    def refresh_git() -> None:
        try:
            set_status(tr("status_running"), "running")
            root = current_git_root()
            stat, command = git_status(root)
            state.git_status_map = stat.status_map()
            state.git_status_root = root
            build_header_status_indicator(header_status_slot)
            log_command_result(command)
            if not command.ok:
                preview_text.content = command.stderr.strip() or tr("git_command_failed")
                preview_text.update()
                refresh_tree()
                set_status(tr("status_error"), "error")
                return
            if not command.stdout.strip():
                append_terminal("clean")
            preview_text.content = tr("branch_summary", branch=stat.branch, ahead=stat.ahead, behind=stat.behind, files=len(stat.files))
            preview_text.update()
            refresh_tree()
            set_status(tr("status_git_ok"), "success")
        except Exception as exc:
            append_terminal(f"ERROR git status: {exc.__class__.__name__}: {exc}")
            set_status(tr("status_error"), "error")

    def refresh_all() -> None:
        refresh_git()
        refresh_tree()

    def selected_diff_path() -> str:
        return str(state.selected_path or "").strip()

    def update_diff_path_label(mode: str) -> None:
        path = selected_diff_path()
        diff_path_label.text = tr("diff_path_label", mode=mode, path=path or ".")
        diff_path_label.update()

    def render_diff_html(text: str) -> str:
        lines = str(text or "").splitlines()
        if not lines:
            return f'<pre class="ahm-redline-pre"><span class="ahm-diff-muted">{escape(tr("diff_placeholder"))}</span></pre>'
        rendered: list[str] = ['<pre class="ahm-redline-pre">']
        for index, line in enumerate(lines, 1):
            css = "ahm-diff-context"
            marker = " "
            if line.startswith("@@"):
                css = "ahm-diff-hunk"
                marker = "@"
            elif line.startswith("+++") or line.startswith("---") or line.startswith("diff --git") or line.startswith("index "):
                css = "ahm-diff-meta"
                marker = "i"
            elif line.startswith("+"):
                css = "ahm-diff-added"
                marker = "+"
            elif line.startswith("-"):
                css = "ahm-diff-removed"
                marker = "-"
            elif line.startswith("\\"):
                css = "ahm-diff-muted"
                marker = "!"
            rendered.append(
                f'<span class="ahm-diff-line {css}">'
                f'<span class="ahm-diff-gutter">{index:>4}</span>'
                f'<span class="ahm-diff-marker">{escape(marker)}</span>'
                f'<span class="ahm-diff-code-text">{escape(line)}</span>'
                "</span>"
            )
        rendered.append("</pre>")
        return "".join(rendered)

    def update_diff_stats(text: str, mode: str) -> None:
        added = removed = hunks = 0
        for line in str(text or "").splitlines():
            if line.startswith("@@"):
                hunks += 1
            elif line.startswith("+") and not line.startswith("+++"):
                added += 1
            elif line.startswith("-") and not line.startswith("---"):
                removed += 1
        diff_stats_label.text = tr("diff_stats", added=added, removed=removed, hunks=hunks, mode=mode)
        diff_stats_label.update()

    def set_diff_text(text: str, mode: str) -> None:
        state.diff_text = text or tr("diff_empty", mode=mode)
        diff_box.content = render_diff_html(state.diff_text)
        diff_box.update()
        update_diff_stats(text, mode)
        ui.run_javascript(
            "setTimeout(() => { const el = document.querySelector('.ahm-redline-box'); if (el) el.scrollTop = 0; }, 0)"
        )

    def show_selected_diff(mode: str = "unstaged", *, quiet: bool = False) -> None:
        if not state.selected_path:
            append_terminal(tr("no_selected_path_for_diff"))
            set_status(tr("status_blocked"), "blocked")
            return
        cached = mode == "staged"
        path = selected_diff_path()
        if mode == "head":
            result = git_run(current_git_root(), "diff", "HEAD", "--", path)
        else:
            result = git_diff(current_git_root(), path, cached=cached)
        if not quiet:
            log_command_result(result)
        update_diff_path_label(mode)
        set_diff_text(result.stdout or result.stderr, mode)
        if not quiet:
            set_command_status(result, "status_diff_ok")

    def refresh_selected_diff_preview() -> None:
        if not state.selected_path:
            diff_path_label.text = tr("diff_no_path")
            diff_path_label.update()
            return
        status = state.git_status_map.get(state.selected_path, "")
        if status in {"modified", "staged", "untracked", "conflict", "changed"}:
            show_selected_diff("staged" if status == "staged" else "unstaged", quiet=True)

    def copy_diff_patch() -> None:
        ui.clipboard.write(state.diff_text)
        append_terminal(tr("diff_copied"))
        set_status(tr("status_diff_ok"), "success")

    def diff_selected(cached: bool = False) -> None:
        show_selected_diff("staged" if cached else "unstaged")

    diff_box.content = render_diff_html(tr("diff_placeholder"))
    diff_box.update()
    diff_stats_label.text = tr("diff_stats", added=0, removed=0, hunks=0, mode="idle")
    diff_stats_label.update()
    set_history_text(tr("history_placeholder"), "idle")
    history_path_label.text = tr("history_no_path")
    history_path_label.update()
    set_metadata_payload(metadata_for_selection())
    safety_summary_box.content = render_small_summary(
        [
            (tr("safety_findings"), 0),
            (tr("safety_blockers"), 0),
            (tr("safety_warnings"), 0),
            (tr("safety_root"), current_tree_root()),
        ]
    )
    safety_summary_box.update()
    storage_summary_box.content = render_small_summary(
        [
            (tr("storage_ok"), tr("metadata_empty_value")),
            (tr("storage_projects"), len(state.registry.projects)),
            (tr("storage_root"), state.paths.root),
            (tr("storage_workspace"), state.paths.workspace),
        ]
    )
    storage_summary_box.update()

    def stage_selected() -> None:
        if not state.selected_path:
            append_terminal(tr("no_selected_path_for_stage"))
            set_status(tr("status_blocked"), "blocked")
            return
        if commit_paths_blocked_by_hub_profile(current_git_root(), [state.selected_path]):
            return
        result = git_stage(current_git_root(), [state.selected_path])
        log_command_result(result)
        set_command_status(result, "status_stage_ok")
        refresh_git()

    def unstage_selected() -> None:
        if not state.selected_path:
            append_terminal(tr("no_selected_path_for_stage"))
            set_status(tr("status_blocked"), "blocked")
            return
        result = git_unstage(current_git_root(), [state.selected_path])
        log_command_result(result)
        set_command_status(result, "status_unstage_ok")
        refresh_git()

    def commit_staged() -> None:
        message = update_commit_message()
        if not message:
            append_terminal(tr("commit_message_required"))
            set_status(tr("status_blocked"), "blocked")
            return
        staged_status, status_result = git_status(current_git_root())
        if not status_result.ok:
            log_command_result(status_result)
            set_status(tr("status_error"), "error")
            return
        staged_paths = [item.path for item in staged_status.files if item.index.strip() and item.index != "?"]
        if commit_paths_blocked_by_hub_profile(current_git_root(), staged_paths):
            return
        result = git_commit(current_git_root(), message)
        log_command_result(result)
        set_command_status(result, "status_commit_ok")
        refresh_git()

    def open_folder(target: Path) -> None:
        try:
            external_apps.open_default(target)
            append_terminal(tr("opened_folder", target=target))
        except Exception as exc:
            append_terminal(tr("open_folder_failed", error=exc))
            set_status(tr("status_error"), "error")

    def open_project_vscode() -> None:
        try:
            target = Path(state.project.vscode_workspace) if state.project.vscode_workspace else source_root()
            external_apps.open_folder_in_vscode(target)
            append_terminal(tr("opened_vscode", target=target))
        except Exception as exc:
            append_terminal(tr("open_vscode_failed", error=exc))

    def tree_event_path(value: Any) -> str:
        if isinstance(value, list) and value:
            value = value[0]
        text = str(value or "").strip().strip("'\"")
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text.replace("'", '"'))
                if isinstance(parsed, list) and parsed:
                    text = str(parsed[0])
            except Exception:
                pass
        return text.strip().strip("'\"")

    def open_tree_node_vscode(value: Any) -> None:
        rel_path = tree_event_path(value)
        if rel_path == ".__lazy__" or rel_path.endswith("/.__lazy__"):
            return
        target = current_tree_root() if rel_path in {"", "."} else current_tree_root() / rel_path
        try:
            if target.is_dir():
                external_apps.open_folder_in_vscode(target)
            else:
                external_apps.open_in_vscode(target)
            select_path(rel_path)
            append_terminal(tr("opened_selected_vscode", target=target))
        except Exception as exc:
            append_terminal(tr("open_selected_failed", error=exc))
            set_status(tr("status_error"), "error")

    def open_selected_vscode() -> None:
        root = current_tree_root()
        target = root / state.selected_path if state.selected_path else root
        try:
            if target.is_dir():
                external_apps.open_folder_in_vscode(target)
            else:
                external_apps.open_in_vscode(target)
            append_terminal(tr("opened_selected_vscode", target=target))
        except Exception as exc:
            append_terminal(tr("open_selected_failed", error=exc))

    def open_auth_terminal(command: str) -> None:
        try:
            external_apps.open_terminal_command(command, cwd=current_git_root())
            append_terminal(tr("auth_terminal_opened", command=command))
            set_status(tr("status_auth_ok"), "success")
        except Exception as exc:
            append_terminal(tr("auth_terminal_failed", error=exc))
            set_status(tr("status_error"), "error")

    def run_ssh_auth_probe(host: str) -> None:
        run_shell_command(f"ssh -o BatchMode=yes -o ConnectTimeout=8 -T git@{host}")

    def run_forgejo_ssh_probe() -> None:
        host = forgejo_host_from_form()
        if host is None:
            return
        port = f"-p {host.ssh_port} " if host.ssh_port != 22 else ""
        run_shell_command(f"ssh -o BatchMode=yes -o ConnectTimeout=8 {port}-T {host.ssh_user}@{host.hostname}")

    def open_windows_credentials() -> None:
        try:
            external_apps.open_windows_credential_manager()
            append_terminal(tr("opened_windows_credentials"))
            set_status(tr("status_auth_ok"), "success")
        except Exception as exc:
            append_terminal(tr("open_windows_credentials_failed", error=exc))
            set_status(tr("status_error"), "error")

    def open_gitkraken_folder() -> None:
        open_folder(current_git_root())

    def open_project_terminal() -> None:
        try:
            external_apps.open_terminal_command("git status --short", cwd=source_root())
            append_terminal(tr("project_terminal_opened", target=source_root()))
            set_status(tr("status_command_ok"), "success")
        except Exception as exc:
            append_terminal(tr("project_terminal_failed", error=exc))
            set_status(tr("status_error"), "error")

    def open_project_git() -> None:
        try:
            target = current_git_root()
            external_apps.open_terminal_command("git status --short", cwd=target)
            append_terminal(tr("project_git_opened", target=target))
            set_status(tr("status_command_ok"), "success")
        except Exception as exc:
            append_terminal(tr("project_git_failed", error=exc))
            set_status(tr("status_error"), "error")

    def open_docs_app() -> None:
        try:
            target = effective_location("docs")
            external_apps.open_default(target)
            append_terminal(tr("opened_docs_app", target=target))
        except Exception as exc:
            append_terminal(tr("open_docs_app_failed", error=exc))

    def run_terminal_command() -> None:
        command = str(cmd_input.value or "").strip()
        run_shell_command(command)

    def clear_terminal() -> None:
        state.log_lines.clear()
        terminal_update_html([], reset=True)
        set_status(tr("idle"), "idle")

    project_select.on_value_change(lambda e: set_project(str(e.value)))
    view_select.on_value_change(lambda e: refresh_tree(log=False))
    search.on_value_change(lambda e: refresh_tree(log=False))
    hide_clean.on_value_change(lambda e: refresh_tree(log=False))
    show_hidden.on_value_change(lambda e: refresh_tree(log=False))
    top_level_search.on_value_change(lambda e: refresh_tree(log=False))
    commit_type.on_value_change(lambda e: update_commit_message())
    commit_scope.on_value_change(lambda e: update_commit_message())
    commit_subject.on_value_change(lambda e: update_commit_message())
    version_series.on_value_change(lambda e: update_basket_command_fields())
    version_value.on_value_change(lambda e: update_basket_command_fields())
    version_bump_command.on_value_change(lambda e: update_basket_command_fields())
    commit_message.on_value_change(lambda e: update_basket_command_fields())
    def invalidate_forgejo_stored_state() -> None:
        # A different server or login means the previous answer no longer applies.
        forgejo_stored_state.update({"checked": False, "present": False, "login": ""})
        update_forgejo_status_label()

    remote_server_input.on_value_change(lambda e: invalidate_forgejo_stored_state())
    forgejo_login_input.on_value_change(lambda e: invalidate_forgejo_stored_state())
    forgejo_token_input.on_value_change(lambda e: update_forgejo_status_label())
    # Probing the credential store spawns git, so keep it off the first paint.
    ui.timer(0.6, lambda: (refresh_forgejo_stored_state(), update_forgejo_status_label()), once=True)
    update_location_ui()
    update_vscode_tool_ui()
    restore_remote_choice()
    update_remote_toggle_buttons()
    update_remote_platform_ui()
    refresh_command_cache_ui()
    update_basket_command_fields()
    refresh_tree()
    append_terminal(tr("skeleton_loaded"))
    for problem in config_errors:
        append_terminal(tr("config_load_failed", error=problem))
    if config_errors:
        set_status(tr("status_config_problem"), "blocked")
    ui.run_javascript(f"setTimeout(() => {{{_splitter_javascript()}}}, 0)")

def run() -> None:
    settings = state.settings
    ui.run(
        root=_build_ui,
        title=tr("title"),
        host=str(os.environ.get("AHM_GUI_HOST", settings.get("host", "127.0.0.1"))),
        port=int(os.environ.get("AHM_GUI_PORT", settings.get("port", 8080))),
        native=bool(settings.get("native", False)),
        reload=bool(settings.get("reload", False)),
        show=_env_bool("AHM_OPEN_BROWSER", bool(settings.get("open_browser", True))),
    )


def build_ui_once() -> dict[str, int]:
    """Build the whole page once, headlessly, and report what came of it.

    The rest of the smoke reads config and themes; nothing built the page, so a
    _build_ui that raised on its first statement would have shipped. Two apps in
    this fleet did exactly that before their pages were built here.

    No browser and no HTTP request, so whatever the page defers until a client
    attaches is skipped, but every widget is constructed.
    """
    import asyncio
    import logging

    from nicegui import core
    from nicegui.client import Client
    from nicegui.page import page as page_definition

    async def build() -> tuple[int, int]:
        core.loop = asyncio.get_running_loop()
        # Work deferred to a connected browser fails here and says nothing about
        # the build. An exception raised by _build_ui itself still propagates.
        core.loop.set_exception_handler(lambda _loop, _context: None)
        logging.getLogger("nicegui").setLevel(logging.CRITICAL)
        client = Client(page_definition("/__smoke__"))
        with client:
            _build_ui()
        report = len(client.elements), len(client.shared_head_html + client.head_html)
        # The page starts work that waits for a browser to attach. Nothing will
        # attach, so stop it deliberately instead of letting the loop close on it.
        pending = asyncio.all_tasks(core.loop) - {asyncio.current_task()}
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        return report

    widgets, stylesheet = asyncio.run(build())
    if widgets < 2:
        raise RuntimeError("_build_ui produced no widgets")
    return {"widgets": widgets, "stylesheet_bytes": stylesheet}


def smoke_check() -> dict[str, Any]:
    tokens = load_theme_tokens(state.theme)
    try:
        page = build_ui_once()
    except Exception as error:  # noqa: BLE001
        return {"ok": False, "error": f"{type(error).__name__}: {error}"}
    return {
        "ok": True,
        **page,
        "project": state.project.id,
        "projects": len(state.registry.projects),
        "theme": state.theme,
        "theme_tokens": len(tokens),
        "nicegui_app": str(Path(__file__).resolve()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audion Hub Manager NiceGUI app")
    parser.add_argument("--smoke", action="store_true", help="Import and config smoke check without starting the server")
    parser.add_argument("--no-browser", action="store_true", help="Start server without opening a browser")
    parser.add_argument("--host", help="Override GUI host")
    parser.add_argument("--port", type=int, help="Override GUI port")
    args = parser.parse_args(argv)

    if args.smoke:
        print(json.dumps(smoke_check(), ensure_ascii=False, indent=2))
        return 0
    if args.no_browser:
        os.environ["AHM_OPEN_BROWSER"] = "0"
    if args.host:
        os.environ["AHM_GUI_HOST"] = str(args.host)
    if args.port:
        os.environ["AHM_GUI_PORT"] = str(args.port)
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
