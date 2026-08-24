from __future__ import annotations

from pathlib import Path
from typing import Any

from system_core.core.config import load_yaml_or_json
from system_core.core.paths import get_project_paths
from system_core.core.ui_settings import load_ui_settings, save_ui_settings
from system_core.core.ui_theme_catalog import DEFAULT_THEME_ID, normalize_theme_id


def _legacy_gui_settings() -> dict[str, Any]:
    paths = get_project_paths()
    data = load_yaml_or_json(paths.config / "gui_settings.json")
    return data.get("gui", data) if isinstance(data, dict) else {}


def load_gui_settings() -> dict[str, Any]:
    paths = get_project_paths()
    legacy = _legacy_gui_settings()
    ui_settings = load_ui_settings(paths.config / "gui_settings.yaml")
    settings = dict(legacy)
    settings.update(
        {
            "language": ui_settings.language,
            "theme": ui_settings.theme,
            "emoji": ui_settings.emoji,
            "allow_runtime_switching": ui_settings.allow_runtime_switching,
            "advanced_open": ui_settings.advanced_open,
            "header_status_mode": ui_settings.header_status_mode,
        }
    )
    return settings


def save_gui_settings(settings: dict[str, Any]) -> None:
    paths = get_project_paths()
    current = load_ui_settings(paths.config / "gui_settings.yaml")
    current.language = str(settings.get("language", current.language))
    current.theme = normalize_theme_id(settings.get("theme", current.theme))
    current.emoji = bool(settings.get("emoji", current.emoji))
    current.allow_runtime_switching = bool(settings.get("allow_runtime_switching", current.allow_runtime_switching))
    current.advanced_open = bool(settings.get("advanced_open", current.advanced_open))
    current.header_status_mode = str(settings.get("header_status_mode", current.header_status_mode))
    save_ui_settings(paths.config / "gui_settings.yaml", current)


def _string_map(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _normalize_theme(theme_id: str, theme_data: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": theme_id,
        "label": str(theme_data.get("label") or theme_id).strip(),
        "label_ru": str(theme_data.get("label_ru") or theme_data.get("label") or theme_id).strip(),
        "mode": "dark" if str(theme_data.get("mode", "dark")).lower() == "dark" else "light",
        "tokens": _string_map(theme_data.get("tokens", {})),
    }


def load_ui_colors(path: Path | None = None) -> dict[str, Any]:
    paths = get_project_paths()
    data = load_yaml_or_json(path or paths.config / "ui_colors.yaml")
    ramps = data.get("ramps", {}) if isinstance(data, dict) else {}
    themes_raw = data.get("themes", {}) if isinstance(data, dict) else {}
    themes: dict[str, dict[str, Any]] = {}
    if isinstance(themes_raw, dict):
        for theme_id, theme_data in themes_raw.items():
            if isinstance(theme_data, dict):
                normalized_id = normalize_theme_id(theme_id, default="")
                if normalized_id:
                    themes[normalized_id] = _normalize_theme(normalized_id, theme_data)
    if DEFAULT_THEME_ID not in themes:
        themes[DEFAULT_THEME_ID] = _normalize_theme(
            DEFAULT_THEME_ID,
            {
                "label": "Code Dark",
                "label_ru": "Code Темная",
                "mode": "dark",
                "tokens": {
                    "color-background-primary": "#141413",
                    "color-background-secondary": "#1f1e1a",
                    "color-background-tertiary": "#0f0f0e",
                    "color-text-primary": "#faf9f5",
                    "color-text-tertiary": "#b0aea5",
                    "color-border-tertiary": "rgba(250, 249, 245, 0.15)",
                    "color-accent-primary": "#d97757",
                },
            },
        )
    return {
        "ramps": ramps if isinstance(ramps, dict) else {},
        "tokens": _string_map(data.get("tokens", {}) if isinstance(data, dict) else {}),
        "themes": themes,
    }


def theme_options(language: str = "ru") -> dict[str, str]:
    colors = load_ui_colors()
    label_key = "label_ru" if language == "ru" else "label"
    return {
        theme_id: str(theme_data.get(label_key) or theme_data.get("label") or theme_id)
        for theme_id, theme_data in colors["themes"].items()
    }


def theme_mode(theme_id: str) -> str:
    colors = load_ui_colors()
    normalized = normalize_theme_id(theme_id)
    theme = colors["themes"].get(normalized) or colors["themes"].get(DEFAULT_THEME_ID) or {}
    return str(theme.get("mode", "dark"))


def load_theme_tokens(theme_id: str) -> dict[str, str]:
    colors = load_ui_colors()
    themes = colors["themes"]
    normalized = normalize_theme_id(theme_id)
    theme = themes.get(normalized, themes.get(DEFAULT_THEME_ID, {}))
    tokens = dict(colors["tokens"])
    if isinstance(theme, dict):
        tokens.update(_string_map(theme.get("tokens", {})))
    return tokens


def css_from_tokens(tokens: dict[str, str]) -> str:
    def val(name: str, default: str) -> str:
        return tokens.get(name, default)
    return f"""
    <style>
    :root {{
      --ahm-bg: {val('color-background-primary', '#141413')};
      --ahm-bg2: {val('color-background-secondary', '#1f1e1a')};
      --ahm-bg3: {val('color-background-tertiary', '#0f0f0e')};
      --ahm-text: {val('color-text-primary', '#faf9f5')};
      --ahm-text2: {val('color-text-secondary', '#e8e6dc')};
      --ahm-muted: {val('color-text-tertiary', '#b0aea5')};
      --ahm-border: {val('color-border-tertiary', 'rgba(250,249,245,.15)')};
      --ahm-border2: {val('color-border-secondary', 'rgba(250,249,245,.3)')};
      --ahm-accent: {val('color-accent-primary', '#d97757')};
      --ahm-accent2: {val('color-accent-secondary', '#6a9bcc')};
      --ahm-button-label: #E8E6DC;
      --ahm-button-label-hover: #FAF9F5;
      --ahm-command-chip: color-mix(in srgb, var(--ahm-bg3) 86%, var(--ahm-bg) 14%);
      --ahm-command-chip-pressed: color-mix(in srgb, var(--ahm-command-chip) 88%, #000 12%);
      --ahm-command-safe-ring: {val('color-border-info', '#378ADD')};
      --ahm-command-danger-ring: {val('color-border-warning', '#BA7517')};
      --ahm-font: {val('font-sans', 'Segoe UI, Arial, sans-serif')};
      --ahm-mono: {val('font-mono', 'Cascadia Mono, Consolas, monospace')};
      --ahm-radius: {val('border-radius-md', '8px')};
    }}
    body.body--light {{
      --ahm-button-label: #444444;
      --ahm-button-label-hover: #202020;
      --ahm-command-chip: color-mix(in srgb, var(--ahm-bg3) 86%, var(--ahm-bg) 14%);
      --ahm-command-chip-pressed: color-mix(in srgb, var(--ahm-command-chip) 88%, #000 12%);
    }}
    html,
    body {{
      width: 100%;
      height: 100%;
      overflow: hidden;
    }}
    body, .nicegui-content, .q-layout, .q-page {{
      background: var(--ahm-bg);
      color: var(--ahm-text);
      font-family: var(--ahm-font);
    }}
    .nicegui-content {{
      padding: 0 !important;
      height: 100vh;
      overflow: hidden;
    }}
    .q-layout,
    .q-page {{
      min-height: 0 !important;
      height: 100%;
      overflow: hidden;
    }}
    .q-textarea textarea {{ min-height: 0 !important; }}
    .ahm-header {{
      display: grid !important;
      grid-template-columns: minmax(190px, auto) minmax(0, 1fr) minmax(120px, auto) minmax(260px, auto);
      align-items: center !important;
      min-height: 42px !important;
      height: 42px !important;
      padding: 0 16px !important;
      background: var(--ahm-bg2) !important;
      border-bottom: 1px solid var(--ahm-border);
      color: var(--ahm-text);
    }}
    .ahm-header-title,
    .ahm-header-status-slot,
    .ahm-header-status,
    .ahm-header-controls {{
      transform: translateY(2px);
    }}
    .ahm-header-title {{
      color: var(--ahm-text);
      letter-spacing: 0;
      justify-self: start;
      white-space: nowrap;
    }}
    .ahm-header-status-slot {{
      justify-self: center;
      min-width: 0;
      max-width: 100%;
    }}
    .ahm-header-status {{
      justify-self: end;
      max-width: min(260px, 20vw);
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .ahm-header-controls {{
      justify-self: end;
      align-items: center !important;
      min-width: 0;
    }}
    .ahm-header-icon-button {{
      width: 24px !important;
      min-width: 24px !important;
      height: 24px !important;
      min-height: 24px !important;
      padding: 0 !important;
    }}
    .ahm-header-status-indicator {{
      gap: 14px;
      flex-wrap: nowrap;
      min-width: 0;
    }}
    .ahm-status-cell {{
      gap: 5px;
      min-width: 0;
      white-space: nowrap;
    }}
    .ahm-status-dot {{
      width: 8px;
      height: 8px;
      border-radius: 50%;
      border: none;
      display: inline-block;
      flex: 0 0 auto;
    }}
    .ahm-status-icon {{
      color: var(--ahm-text2);
      font-size: 15px !important;
    }}
    .ahm-status-count {{
      font-size: 12px;
      color: var(--ahm-text);
      min-width: 9px;
    }}
    .ahm-status-count-zero {{
      color: var(--ahm-muted);
    }}
    .ahm-status-word {{
      font-size: 11px;
      color: var(--ahm-text2);
      white-space: nowrap;
    }}
    .ahm-status-letter {{
      font-size: 12px;
      font-weight: 600;
      color: var(--ahm-text2);
      min-width: 10px;
      text-align: center;
    }}
    .ahm-root {{
      --ahm-left-width: 25%;
      --ahm-right-width: 45%;
      --ahm-terminal-height: 228px;
      width: 100%;
      height: calc(100vh - 42px);
      display: grid;
      grid-template-rows: minmax(330px, 1fr) 8px var(--ahm-terminal-height);
      gap: 0;
      padding: 8px;
      box-sizing: border-box;
      overflow: hidden;
    }}
    .ahm-main {{
      display: grid;
      grid-template-columns: var(--ahm-left-width) 8px minmax(300px, 1fr) 8px var(--ahm-right-width);
      gap: 0;
      min-height: 0;
      height: 100%;
    }}
    .ahm-panel {{
      background: var(--ahm-bg2);
      border: 1px solid var(--ahm-border);
      border-radius: var(--ahm-radius);
      padding: 14px 18px;
      overflow: auto;
      scrollbar-gutter: stable;
      min-height: 0;
      min-width: 0;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }}
    .ahm-tree-panel,
    .ahm-inspector-panel {{
      padding: 14px 18px;
      gap: 8px;
    }}
    .ahm-inspector-panel {{
      overflow: hidden;
    }}
    .ahm-inspector-panel .q-tab-panels,
    .ahm-tab-panels {{
      flex: 1 1 auto;
      min-width: 0;
      min-height: 0;
      width: 100%;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }}
    .ahm-inspector-panel .q-panel,
    .ahm-inspector-panel .q-tab-panel {{
      width: 100%;
      min-width: 0;
      height: 100%;
      min-height: 0;
      overflow: hidden;
    }}
    .ahm-tab-panels > .q-panel,
    .ahm-tab-panels .q-panel.scroll {{
      flex: 1 1 auto;
      width: 100%;
      min-width: 0;
      min-height: 0;
      overflow: hidden;
    }}
    .ahm-tab-panels .q-tab-panel {{
      display: flex;
      flex-direction: column;
      align-items: stretch;
      overflow-x: hidden;
      overflow-y: auto;
      scrollbar-gutter: stable;
    }}
    .ahm-tree-panel {{
      overflow: hidden;
    }}
    .ahm-tree-holder {{
      flex: 1 1 auto;
      min-height: 0;
      overflow: auto;
      scrollbar-gutter: stable;
      padding-right: 4px;
    }}
    .ahm-terminal {{
      display: flex;
      flex-direction: column;
      gap: 8px;
      background: var(--ahm-bg2);
      border: 1px solid var(--ahm-border);
      border-radius: var(--ahm-radius);
      padding: 12px 18px;
      overflow: hidden;
      min-height: 0;
      min-width: 0;
    }}
    .ahm-splitter {{
      min-width: 0;
      min-height: 0;
      position: relative;
      touch-action: none;
      user-select: none;
      background: transparent;
    }}
    .ahm-v-splitter {{
      cursor: col-resize;
    }}
    .ahm-h-splitter {{
      cursor: row-resize;
    }}
    .ahm-v-splitter::before,
    .ahm-h-splitter::before {{
      content: "";
      position: absolute;
      border-radius: 999px;
      background: color-mix(in srgb, var(--ahm-border2) 52%, transparent 48%);
      transition: background-color 120ms ease, opacity 120ms ease;
      opacity: 0.72;
    }}
    .ahm-v-splitter::before {{
      top: 10px;
      bottom: 10px;
      left: 3px;
      width: 2px;
    }}
    .ahm-h-splitter::before {{
      left: 10px;
      right: 10px;
      top: 3px;
      height: 2px;
    }}
    .ahm-splitter:hover::before,
    body.ahm-resizing .ahm-splitter::before {{
      background: var(--ahm-accent2);
      opacity: 1;
    }}
    body.ahm-resizing,
    body.ahm-resizing * {{
      user-select: none !important;
    }}
    .ahm-panel-head,
    .ahm-terminal-head,
    .ahm-pane-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      min-height: 20px;
      flex: 0 0 auto;
    }}
    .ahm-pane-head {{
      width: 100%;
    }}
    .ahm-tree-panel-head {{
      justify-content: flex-start;
      gap: 10px;
    }}
    .ahm-tree-panel-head .ahm-title {{
      flex: 0 0 auto;
    }}
    .ahm-tree-location-badge {{
      flex: 1 1 auto;
      min-width: 0;
      max-width: min(72%, 520px);
      justify-content: flex-start !important;
      text-align: left !important;
    }}
    .ahm-window-controls {{
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 3px;
      flex: 0 0 auto;
      margin-left: auto;
    }}
    .ahm-editor-window-controls {{
      gap: 13px;
    }}
    .ahm-editor-window-controls .ahm-expand-button {{
      margin-left: 16px;
    }}
    .ahm-title {{ color: var(--ahm-accent); font-weight: 700; letter-spacing: 0; line-height: 1.15; }}
    .ahm-muted {{ color: var(--ahm-muted); font-size: 12px; line-height: 1.25; }}
    .ahm-mono textarea, .ahm-mono pre, .ahm-terminal textarea, .audion-terminal-pre {{
      font-family: var(--ahm-mono);
    }}
    .ahm-terminal-title-group {{
      display: flex;
      align-items: baseline;
      gap: 10px;
      min-width: 0;
    }}
    .ahm-terminal-log-label {{
      white-space: nowrap;
    }}
    .ahm-block {{
      border-top: 1px solid var(--ahm-border);
      padding-top: 7px;
      display: flex;
      flex-direction: column;
      gap: 6px;
      min-width: 0;
    }}
    .ahm-block-first {{ border-top: 0; padding-top: 0; }}
    .ahm-section-title {{
      color: var(--ahm-muted);
      font-size: 11px;
      font-weight: 800;
      line-height: 1;
      text-transform: uppercase;
    }}
    .ahm-subsection-title {{
      color: color-mix(in srgb, var(--ahm-muted) 82%, var(--ahm-accent2) 18%);
      font-size: 10px;
      font-weight: 800;
      line-height: 1;
      margin-top: 0;
      text-transform: uppercase;
    }}
    .ahm-check-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      column-gap: 10px;
      row-gap: 2px;
      min-width: 0;
      align-items: start;
    }}
    .ahm-check-grid .q-checkbox {{
      padding-left: 8px !important;
    }}
    .ahm-check-row {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 2px 12px;
      min-height: 22px;
    }}
    .ahm-button-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 6px;
      min-width: 0;
    }}
    .ahm-button-grid-primary {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    .ahm-button-grid-primary .audion-action:last-child {{ grid-column: 1 / -1; }}
    .ahm-button-grid-three {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
    .ahm-source-main-button {{
      width: 100% !important;
      margin-top: 4px;
      min-height: 34px !important;
      justify-content: center !important;
    }}
    .ahm-source-action-grid,
    .ahm-project-action-grid {{
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }}
    .ahm-source-tree-badge {{
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 21px;
      padding: 3px 8px;
      border: 1px solid color-mix(in srgb, var(--ahm-accent2) 20%, var(--ahm-border) 80%);
      border-radius: var(--ahm-radius);
      background: color-mix(in srgb, var(--ahm-accent2) 5%, var(--ahm-bg3) 95%);
      color: color-mix(in srgb, var(--ahm-text2) 78%, var(--ahm-accent2) 22%);
      font-size: 10.5px;
      font-weight: 800;
      line-height: 1.15;
      text-align: center;
      text-transform: uppercase;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .ahm-open-tool-grid {{
      padding-top: 6px;
      border-top: 1px solid color-mix(in srgb, var(--ahm-border) 68%, transparent 32%);
    }}
    .ahm-actions-stack {{ grid-template-columns: minmax(0, 1fr); }}
    .ahm-actions-panel {{
      display: grid;
      grid-template-rows: minmax(0, 1fr) auto;
      gap: 12px;
      min-width: 0;
      height: 100%;
      min-height: 0;
      overflow: hidden;
    }}
    .ahm-actions-command-pane {{
      display: flex;
      flex-direction: column;
      gap: 7px;
      min-width: 0;
      min-height: 0;
      overflow: auto;
      padding-right: 6px;
      scrollbar-gutter: stable;
    }}
    .ahm-action-section {{
      display: flex;
      flex-direction: column;
      gap: 7px;
      min-width: 0;
      padding: 8px 9px 9px;
      border: 1px solid color-mix(in srgb, var(--ahm-border) 74%, transparent 26%);
      border-radius: var(--ahm-radius);
      background: color-mix(in srgb, var(--ahm-bg3) 24%, transparent 76%);
    }}
    .ahm-action-section .ahm-subsection-title {{
      display: grid;
      grid-template-columns: minmax(24px, 1fr) auto minmax(24px, 1fr);
      align-items: center;
      gap: 8px;
      width: 100%;
      text-align: center;
      letter-spacing: 0;
      color: var(--ahm-text2);
    }}
    .ahm-action-section .ahm-subsection-title::before,
    .ahm-action-section .ahm-subsection-title::after {{
      content: "";
      height: 1px;
      background: color-mix(in srgb, var(--ahm-border2) 54%, transparent 46%);
    }}
    .ahm-commit-pane {{
      display: flex;
      flex-direction: column;
      gap: 10px;
      min-width: 0;
      container-type: inline-size;
      padding: 12px;
      border-left: 1px solid color-mix(in srgb, var(--ahm-accent2) 24%, transparent 76%);
      background: color-mix(in srgb, var(--ahm-bg3) 34%, transparent 66%);
      border-radius: var(--ahm-radius);
    }}
    .ahm-editor-pane {{
      display: flex;
      flex-direction: column;
      gap: 10px;
      width: 100%;
      min-width: 0;
      min-height: 0;
      height: 100%;
      overflow: hidden;
      padding: 12px;
      border-left: 1px solid color-mix(in srgb, var(--ahm-accent) 22%, transparent 78%);
      background: color-mix(in srgb, var(--ahm-bg3) 28%, transparent 72%);
      border-radius: var(--ahm-radius);
    }}
    .ahm-auth-pane,
    .ahm-branch-pane {{
      display: flex;
      flex-direction: column;
      gap: 10px;
      min-width: 0;
      container-type: inline-size;
      padding: 12px;
      border-left: 1px solid color-mix(in srgb, var(--ahm-accent2) 24%, transparent 76%);
      background: color-mix(in srgb, var(--ahm-bg3) 30%, transparent 70%);
      border-radius: var(--ahm-radius);
    }}
    .ahm-diff-pane {{
      display: flex;
      flex-direction: column;
      gap: 10px;
      min-width: 0;
      min-height: 0;
      height: 100%;
      padding: 12px;
      border-left: 1px solid color-mix(in srgb, var(--ahm-accent) 22%, transparent 78%);
      background: color-mix(in srgb, var(--ahm-bg3) 28%, transparent 72%);
      border-radius: var(--ahm-radius);
    }}
    .ahm-history-pane,
    .ahm-meta-pane,
    .ahm-safety-pane,
    .ahm-storage-pane {{
      display: flex;
      flex-direction: column;
      gap: 10px;
      min-width: 0;
      min-height: 0;
      height: 100%;
      padding: 12px;
      border-left: 1px solid color-mix(in srgb, var(--ahm-accent2) 24%, transparent 76%);
      background: color-mix(in srgb, var(--ahm-bg3) 30%, transparent 70%);
      border-radius: var(--ahm-radius);
    }}
    .ahm-storage-pane {{
      flex: 1 1 auto;
      overflow-y: auto;
      overflow-x: hidden;
      scrollbar-gutter: stable;
      padding-right: 14px;
    }}
    .ahm-storage-pane .ahm-meta-json {{
      flex: 0 0 auto;
      min-height: 0 !important;
      max-height: 210px !important;
      overflow: hidden !important;
    }}
    .ahm-storage-pane .ahm-meta-json textarea {{
      min-height: 118px !important;
      max-height: 184px !important;
      overflow: auto !important;
    }}
    .ahm-editor-path {{
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      max-width: 100%;
    }}
    .ahm-action-cache-panel {{
      display: flex;
      flex-direction: column;
      gap: 8px;
      min-width: 0;
      padding-top: 10px;
      border-top: 1px solid color-mix(in srgb, var(--ahm-border2) 40%, transparent 60%);
      background: var(--ahm-bg2);
      flex: 0 0 auto;
      z-index: 1;
    }}
    .ahm-pinned-command-row {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(92px, auto);
      gap: 10px;
      min-width: 0;
      align-items: start;
    }}
    .ahm-command-cache-tools-row {{
      display: grid;
      grid-template-columns: minmax(190px, 1fr) minmax(190px, 1fr) repeat(4, 34px);
      gap: 8px;
      min-width: 0;
      align-items: start;
    }}
    .ahm-custom-command-row {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(76px, auto);
      gap: 10px;
      min-width: 0;
      align-items: start;
    }}
    .ahm-pinned-command-select,
    .ahm-command-cache-select,
    .ahm-action-command-input {{
      min-width: 0;
    }}
    .ahm-action-command-input textarea {{
      font-family: var(--ahm-mono);
      font-size: 13px !important;
      line-height: 1.35 !important;
      min-height: 40px !important;
    }}
    .ahm-command-cache-tools-row .audion-action,
    .ahm-custom-command-row .audion-action {{
      width: 100% !important;
      min-width: 0 !important;
      min-height: 38px !important;
      height: 38px !important;
      justify-content: center !important;
      color: var(--ahm-accent) !important;
      background: color-mix(in srgb, var(--ahm-bg3) 74%, var(--ahm-bg) 26%) !important;
      border: 1px solid color-mix(in srgb, var(--ahm-border) 82%, transparent 18%) !important;
      border-radius: var(--ahm-radius) !important;
      box-sizing: border-box !important;
    }}
    .ahm-command-cache-tools-row .audion-action:hover,
    .ahm-custom-command-row .audion-action:hover {{
      color: var(--ahm-text) !important;
      background: color-mix(in srgb, var(--ahm-accent2) 8%, var(--ahm-bg3) 92%) !important;
      border-color: color-mix(in srgb, var(--ahm-accent2) 34%, var(--ahm-border2) 66%) !important;
    }}
    .ahm-command-cache-tools-row .ahm-cache-icon-button {{
      width: 34px !important;
      min-width: 34px !important;
      max-width: 34px !important;
      height: 34px !important;
      min-height: 34px !important;
      padding: 0 !important;
      background: transparent !important;
      border: 0 !important;
      border-radius: 6px !important;
    }}
    .ahm-command-cache-tools-row .ahm-cache-icon-button:hover {{
      background: color-mix(in srgb, var(--ahm-accent2) 10%, transparent 90%) !important;
      border: 0 !important;
    }}
    .ahm-cache-icon-button .q-btn__content {{
      width: 100%;
      justify-content: center !important;
      gap: 0 !important;
    }}
    .ahm-cache-icon-button .q-icon {{
      margin: 0 !important;
      font-size: 18px !important;
    }}
    .ahm-action-command-input .q-field__control,
    .ahm-action-command-input .q-field__control-container {{
      min-height: 48px !important;
    }}
    .ahm-command-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 6px 10px;
      min-width: 0;
    }}
    .ahm-command-value-grid {{
      display: grid;
      grid-template-columns: minmax(150px, 0.9fr) minmax(120px, 1.1fr) minmax(150px, 0.9fr) minmax(120px, 1.1fr);
      gap: 7px 10px;
      min-width: 0;
      align-items: center;
    }}
    .ahm-command-value-grid .audion-action {{
      width: 100% !important;
      min-width: 0 !important;
      min-height: 30px !important;
      height: 30px !important;
      padding-left: 5px !important;
      padding-right: 5px !important;
      padding-top: 1px !important;
      padding-bottom: 2px !important;
      justify-content: flex-start !important;
      color: var(--ahm-accent) !important;
      background: transparent !important;
      border: 0 !important;
      border-radius: 6px !important;
      box-sizing: border-box !important;
    }}
    .ahm-command-value-grid .audion-action:hover {{
      color: var(--ahm-text) !important;
      background: color-mix(in srgb, var(--ahm-accent2) 10%, transparent 90%) !important;
      border-color: transparent !important;
    }}
    .ahm-command-value-grid .audion-action .q-btn__content {{
      display: grid !important;
      grid-template-columns: 22px minmax(0, 1fr);
      align-items: center;
      column-gap: 8px;
      font-family: var(--ahm-font) !important;
      font-size: 12px;
      font-weight: 600;
      line-height: 1.25 !important;
      width: 100%;
      min-width: 0;
      justify-content: stretch;
      overflow: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
      padding-bottom: 1px;
    }}
    .ahm-command-value-grid .audion-action .q-icon {{
      grid-column: 1;
      font-size: 18px !important;
      width: 18px !important;
      min-width: 18px !important;
      margin: 0 !important;
      justify-self: center;
    }}
    .ahm-command-value-grid .audion-action .q-btn__content > .block {{
      grid-column: 2;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      line-height: 1.25 !important;
      justify-self: start;
    }}
    .ahm-command-value-grid .ahm-command-button-wrap-flags .q-btn__content {{
      align-items: center;
      column-gap: 7px;
    }}
    .ahm-command-value-grid .ahm-command-button-wrap-flags .q-btn__content > .block {{
      white-space: pre-line;
      line-height: 1.25 !important;
      font-size: 10.5px;
      letter-spacing: 0;
      text-align: left !important;
      width: 100%;
      max-height: 28px;
    }}
    .ahm-command-value-input {{
      min-width: 0;
      width: 100%;
    }}
    .ahm-command-value-input .q-field__control,
    .ahm-command-value-input .q-field__control-container {{
      min-height: 28px !important;
      height: 28px !important;
    }}
    .ahm-command-value-input .q-field__native,
    .ahm-command-value-input input {{
      min-height: 26px !important;
      height: 26px !important;
      line-height: 26px !important;
      padding-top: 0 !important;
      padding-bottom: 1px !important;
      font-size: 12px !important;
    }}
    .ahm-command-value-input input::placeholder {{
      color: color-mix(in srgb, var(--ahm-muted) 72%, transparent 28%) !important;
      opacity: 1 !important;
    }}
    .ahm-command-value-wide-button {{
      grid-column: 1;
    }}
    .ahm-command-value-wide-input {{
      grid-column: 2 / -1;
    }}
    .ahm-command-grid .audion-action {{
      width: 100% !important;
      min-width: 0 !important;
      min-height: 30px !important;
      height: 30px !important;
      padding-left: 5px !important;
      padding-right: 5px !important;
      padding-top: 1px !important;
      padding-bottom: 2px !important;
      justify-content: flex-start !important;
      color: var(--ahm-accent) !important;
      background: transparent !important;
      border: 0 !important;
      border-radius: 6px !important;
      box-sizing: border-box !important;
    }}
    .ahm-command-read {{
      color: var(--ahm-accent2) !important;
      background: transparent !important;
      border-color: transparent !important;
    }}
    .ahm-command-safe {{
      color: color-mix(in srgb, var(--ahm-accent2) 92%, #1D9E75 8%) !important;
      background: transparent !important;
      border-color: transparent !important;
    }}
    .ahm-command-caution {{
      color: color-mix(in srgb, #EF9F27 74%, var(--ahm-accent2) 26%) !important;
      background: transparent !important;
      border-color: transparent !important;
    }}
    .ahm-command-danger {{
      color: color-mix(in srgb, var(--ahm-accent) 78%, var(--ahm-accent2) 22%) !important;
      background: transparent !important;
      border-color: transparent !important;
    }}
    .ahm-command-grid .audion-action:hover {{
      color: var(--ahm-text) !important;
      background: color-mix(in srgb, var(--ahm-accent2) 10%, transparent 90%) !important;
      border-color: transparent !important;
    }}
    .ahm-command-grid .audion-action .q-btn__content {{
      display: grid !important;
      grid-template-columns: 22px minmax(0, 1fr);
      align-items: center;
      column-gap: 8px;
      font-family: var(--ahm-font) !important;
      font-size: 12px;
      font-weight: 600;
      line-height: 1.25 !important;
      width: 100%;
      min-width: 0;
      justify-content: stretch;
      overflow: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
      padding-bottom: 1px;
    }}
    .ahm-command-grid .audion-action .q-icon {{
      grid-column: 1;
      font-size: 18px !important;
      width: 18px !important;
      min-width: 18px !important;
      margin: 0 !important;
      justify-self: center;
    }}
    .ahm-command-grid .audion-action .q-btn__content > .block {{
      grid-column: 2;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      line-height: 1.25 !important;
      justify-self: start;
    }}
    .ahm-command-divider {{
      border-top: 1px solid color-mix(in srgb, var(--ahm-accent) 18%, var(--ahm-border) 82%);
      margin: 0 0 1px;
    }}
    .ahm-action-section-danger {{
      border-color: color-mix(in srgb, var(--ahm-accent) 20%, var(--ahm-border) 80%);
      background: color-mix(in srgb, var(--ahm-accent) 4%, var(--ahm-bg3) 96%);
    }}
    .ahm-action-section-danger .ahm-subsection-danger {{
      color: color-mix(in srgb, var(--ahm-accent) 62%, var(--ahm-text2) 38%) !important;
    }}
    .ahm-support-grid {{
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }}
    .ahm-basket-command-layout {{
      display: grid;
      grid-template-columns: minmax(236px, 1.12fr) minmax(104px, 0.5fr) minmax(118px, 0.58fr);
      gap: 7px 8px;
      min-width: 0;
      align-items: start;
      justify-content: start;
    }}
    .ahm-basket-param-column,
    .ahm-basket-action-column {{
      display: grid;
      gap: 7px;
      min-width: 0;
      align-content: start;
    }}
    .ahm-basket-command-pair {{
      display: grid;
      grid-template-columns: minmax(104px, 0.92fr) minmax(112px, 1.08fr);
      gap: 5px;
      min-width: 0;
      align-items: center;
    }}
    .ahm-basket-command-layout .audion-action {{
      width: 100% !important;
      min-width: 0 !important;
      padding-left: 4px !important;
      padding-right: 4px !important;
    }}
    .ahm-basket-command-layout .audion-action .q-btn__content {{
      font-size: 11.5px !important;
      gap: 6px !important;
      justify-content: stretch !important;
    }}
    .ahm-basket-git-column .audion-action .q-btn__content {{
      font-size: 11px !important;
      gap: 5px !important;
    }}
    .ahm-basket-command-layout .audion-primary-action .q-btn__content {{
      justify-content: stretch !important;
    }}
    .ahm-branch-pane .ahm-command-grid {{
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 6px 8px;
    }}
    .ahm-branch-pane .ahm-command-value-grid {{
      grid-template-columns: repeat(4, minmax(118px, 1fr));
      gap: 7px 8px;
    }}
    @container (max-width: 720px) {{
      .ahm-branch-pane .ahm-command-value-grid {{
        grid-template-columns: minmax(132px, 0.95fr) minmax(0, 1.05fr);
      }}
    }}
    @container (max-width: 500px) {{
      .ahm-branch-pane .ahm-command-grid,
      .ahm-branch-pane .ahm-command-value-grid {{
        grid-template-columns: minmax(0, 1fr);
      }}
      .ahm-command-value-wide-input {{
        grid-column: auto;
      }}
    }}
    .ahm-editor-command-grid {{
      grid-template-columns: repeat(3, minmax(132px, 1fr));
    }}
    .ahm-auth-command-grid {{
      grid-template-columns: repeat(2, minmax(190px, 1fr));
    }}
    .ahm-diff-command-grid {{
      grid-template-columns: repeat(4, minmax(120px, 1fr));
    }}
    .ahm-history-command-grid {{
      grid-template-columns: repeat(5, minmax(112px, 1fr));
    }}
    .ahm-meta-command-grid {{
      grid-template-columns: repeat(3, minmax(130px, 1fr));
    }}
    .ahm-safety-command-grid {{
      grid-template-columns: repeat(2, minmax(150px, 1fr));
    }}
    .ahm-storage-command-grid {{
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 6px 4px;
    }}
    .ahm-storage-command-grid .audion-action {{
      padding-left: 1px !important;
      padding-right: 1px !important;
    }}
    .ahm-storage-command-grid .audion-action .q-btn__content {{
      font-size: 11.5px;
      gap: 6px;
    }}
    .ahm-service-row {{
      display: grid;
      grid-template-columns: minmax(240px, 1fr) repeat(3, minmax(92px, auto));
      gap: 10px;
      min-width: 0;
      align-items: start;
    }}
    .ahm-commit-grid {{
      display: grid;
      grid-template-columns: minmax(180px, 0.28fr) minmax(320px, 0.72fr);
      gap: 7px 10px;
      min-width: 0;
    }}
    .ahm-remote-config-grid {{
      display: grid;
      grid-template-columns: minmax(240px, 1fr) minmax(240px, 1fr);
      gap: 8px 10px;
      min-width: 0;
      margin-bottom: 8px;
    }}
    .ahm-remote-toggle-strip {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      column-gap: 14px;
      row-gap: 6px;
      min-width: 0;
      margin-bottom: 8px;
    }}
    .ahm-remote-toggle-group {{
      display: inline-flex;
      flex-wrap: wrap;
      align-items: center;
      column-gap: 6px;
      row-gap: 6px;
      min-width: 0;
    }}
    .ahm-remote-toggle-caption {{
      font-size: 0.68rem;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: var(--ahm-muted);
      white-space: nowrap;
      margin-right: 2px;
    }}
    .audion-action.ahm-remote-toggle {{
      flex: 0 0 auto !important;
      width: auto !important;
      max-width: none !important;
      min-width: 0;
      min-height: 1.75rem !important;
      height: 1.75rem !important;
      padding: 0 0.6rem !important;
      color: var(--ahm-accent2) !important;
      background: color-mix(in srgb, var(--ahm-accent2) 7%, transparent 93%) !important;
      border: 1px solid color-mix(in srgb, var(--ahm-accent2) 22%, transparent 78%) !important;
      border-radius: var(--ahm-radius) !important;
      box-shadow: none !important;
      box-sizing: border-box !important;
    }}
    .audion-action.ahm-remote-toggle:hover {{
      color: var(--ahm-accent2) !important;
      background: color-mix(in srgb, var(--ahm-accent2) 12%, transparent 88%) !important;
      border-color: color-mix(in srgb, var(--ahm-accent2) 34%, transparent 66%) !important;
    }}
    .q-btn.audion-action.ahm-remote-toggle-active {{
      color: var(--ahm-text) !important;
      background: color-mix(in srgb, var(--ahm-accent2) 22%, transparent 78%) !important;
      border-color: color-mix(in srgb, var(--ahm-accent2) 44%, transparent 56%) !important;
      font-weight: 650 !important;
    }}
    .q-btn.audion-action.ahm-remote-toggle-active:hover {{
      color: var(--ahm-text) !important;
      background: color-mix(in srgb, var(--ahm-accent2) 28%, transparent 72%) !important;
    }}
    .q-btn.audion-action.ahm-remote-toggle .q-btn__content {{
      min-width: 0;
      white-space: nowrap;
      font-size: 0.72rem;
      text-transform: uppercase;
      line-height: 1;
      justify-content: center !important;
    }}
    .ahm-remote-grid-spacer {{
      min-width: 0;
    }}
    .ahm-remote-cache-row {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) 36px;
      gap: 6px;
      min-width: 0;
      align-items: start;
    }}
    .ahm-remote-cache-row .ahm-cache-icon-button {{
      width: 34px !important;
      height: 34px !important;
      min-height: 34px !important;
      margin-top: 7px;
    }}
    .ahm-remote-input-field,
    .ahm-remote-cache-select,
    .ahm-remote-input-field .q-field__inner,
    .ahm-remote-cache-select .q-field__inner,
    .ahm-remote-input-field .q-field__control,
    .ahm-remote-cache-select .q-field__control,
    .ahm-remote-input-field .q-field__control-container,
    .ahm-remote-cache-select .q-field__control-container {{
      min-width: 0 !important;
      max-width: 100% !important;
      overflow: hidden !important;
      box-sizing: border-box !important;
    }}
    .ahm-remote-input-field .q-field__native,
    .ahm-remote-input-field .q-field__input,
    .ahm-remote-cache-select .q-field__native,
    .ahm-remote-cache-select .q-field__input {{
      min-width: 0 !important;
      max-width: 100% !important;
      overflow: hidden !important;
      text-overflow: ellipsis !important;
      white-space: nowrap !important;
    }}
    .ahm-remote-cache-row .q-field__append {{
      min-width: 28px !important;
      flex: 0 0 auto !important;
    }}
    .ahm-remote-url-field {{
      grid-column: 1 / -1;
    }}
    .ahm-commit-wide {{
      grid-column: 1 / -1;
    }}
    .ahm-basket-field,
    .ahm-commit-message {{
      min-height: 58px !important;
      height: 58px !important;
    }}
    .ahm-basket-field .q-field__inner,
    .ahm-commit-message .q-field__inner {{
      min-height: 58px !important;
      height: 58px !important;
      padding-bottom: 0 !important;
    }}
    .ahm-basket-box .q-field__label,
    .ahm-basket-field .q-field__label,
    .ahm-commit-message .q-field__label {{
      top: 9px !important;
      font-size: 11px !important;
      line-height: 1 !important;
      color: var(--ahm-muted) !important;
    }}
    .ahm-basket-field .q-field__control,
    .ahm-commit-message .q-field__control {{
      min-height: 58px !important;
      height: 58px !important;
      align-items: stretch !important;
      padding-top: 0 !important;
      padding-bottom: 0 !important;
    }}
    .ahm-basket-field .q-field__control-container,
    .ahm-commit-message .q-field__control-container {{
      display: flex !important;
      align-items: flex-start !important;
      min-height: 58px !important;
      padding-top: 24px !important;
      padding-bottom: 0 !important;
    }}
    .ahm-basket-field .q-field__native,
    .ahm-basket-field .q-field__input,
    .ahm-commit-message .q-field__native,
    .ahm-commit-message .q-field__input,
    .ahm-basket-field input,
    .ahm-commit-message input {{
      min-height: 26px !important;
      height: 26px !important;
      line-height: 26px !important;
      padding-top: 0 !important;
      padding-bottom: 0 !important;
    }}
    .ahm-basket-field .q-field__marginal,
    .ahm-basket-field .q-field__append {{
      min-height: 58px !important;
      height: 58px !important;
      align-items: center !important;
      padding-top: 7px !important;
    }}
    .ahm-basket-box textarea {{
      min-height: 54px !important;
      max-height: 96px !important;
      padding-top: 14px !important;
      overflow: auto !important;
    }}
    .ahm-basket-field,
    .ahm-basket-field .q-field__inner,
    .ahm-basket-field .q-field__control {{
      min-height: 48px !important;
      height: 48px !important;
    }}
    .ahm-basket-field .q-field__control-container {{
      min-height: 48px !important;
      padding-top: 19px !important;
    }}
    .ahm-basket-field .q-field__native,
    .ahm-basket-field .q-field__input,
    .ahm-basket-field input {{
      min-height: 24px !important;
      height: 24px !important;
      line-height: 24px !important;
      font-size: 13px !important;
    }}
    .ahm-basket-field .q-field__marginal,
    .ahm-basket-field .q-field__append {{
      min-height: 48px !important;
      height: 48px !important;
      padding-top: 5px !important;
    }}
    .ahm-commit-message,
    .ahm-commit-message .q-field__inner,
    .ahm-commit-message .q-field__control {{
      min-height: 64px !important;
      height: 64px !important;
    }}
    .ahm-commit-message .q-field__control-container {{
      min-height: 64px !important;
      padding-top: 27px !important;
    }}
    .ahm-commit-message .q-field__native,
    .ahm-commit-message .q-field__input,
    .ahm-commit-message input {{
      min-height: 30px !important;
      height: 30px !important;
      line-height: 30px !important;
      font-size: 13px !important;
    }}
    .ahm-basket-compact-field,
    .ahm-basket-commit-message {{
      min-height: 30px !important;
      height: 30px !important;
      min-width: 0 !important;
    }}
    .ahm-basket-compact-field .q-field__inner,
    .ahm-basket-compact-field .q-field__control,
    .ahm-basket-compact-field .q-field__control-container,
    .ahm-basket-commit-message .q-field__inner,
    .ahm-basket-commit-message .q-field__control,
    .ahm-basket-commit-message .q-field__control-container {{
      min-height: 30px !important;
      height: 30px !important;
    }}
    .ahm-basket-compact-field .q-field__control,
    .ahm-basket-commit-message .q-field__control {{
      padding: 0 8px !important;
    }}
    .ahm-basket-compact-field .q-field__native,
    .ahm-basket-compact-field .q-field__input,
    .ahm-basket-compact-field input,
    .ahm-basket-commit-message .q-field__native,
    .ahm-basket-commit-message .q-field__input,
    .ahm-basket-commit-message input {{
      min-height: 28px !important;
      height: 28px !important;
      line-height: 28px !important;
      padding-top: 0 !important;
      padding-bottom: 1px !important;
      font-size: 12px !important;
      color: var(--ahm-text2) !important;
    }}
    .ahm-basket-compact-field input::placeholder,
    .ahm-basket-commit-message input::placeholder {{
      color: color-mix(in srgb, var(--ahm-muted) 76%, transparent 24%) !important;
      opacity: 1 !important;
    }}
    .ahm-basket-compact-field .q-field__marginal,
    .ahm-basket-compact-field .q-field__append {{
      min-height: 30px !important;
      height: 30px !important;
      padding-top: 0 !important;
      align-items: center !important;
    }}
    .ahm-basket-box .q-field__control {{
      min-height: 44px !important;
      padding: 0 8px !important;
    }}
    .ahm-basket-box textarea {{
      min-height: 42px !important;
      max-height: 74px !important;
      padding-top: 8px !important;
      padding-bottom: 7px !important;
      overflow: auto !important;
      font-size: 12px !important;
      line-height: 1.35 !important;
    }}
    .ahm-redline-box {{
      flex: 1 1 auto;
      min-height: 320px;
      overflow: auto;
      border: 1px solid var(--ahm-border);
      border-radius: var(--ahm-radius);
      background: color-mix(in srgb, var(--ahm-bg) 88%, black 12%);
      box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--ahm-bg3) 72%, transparent 28%);
    }}
    .ahm-redline-pre {{
      margin: 0;
      padding: 8px 0;
      min-width: max-content;
      font-family: var(--ahm-mono);
      font-size: 10px;
      line-height: 1.35;
      color: var(--ahm-text2);
      tab-size: 2;
    }}
    .ahm-diff-line {{
      display: grid;
      grid-template-columns: 42px 18px minmax(0, 1fr);
      min-height: 15px;
      white-space: pre;
    }}
    .ahm-diff-gutter {{
      color: color-mix(in srgb, var(--ahm-muted) 68%, transparent 32%);
      text-align: right;
      padding-right: 8px;
      user-select: none;
      border-right: 1px solid color-mix(in srgb, var(--ahm-border) 62%, transparent 38%);
      background: color-mix(in srgb, var(--ahm-bg3) 34%, transparent 66%);
    }}
    .ahm-diff-marker {{
      text-align: center;
      user-select: none;
      font-weight: 800;
    }}
    .ahm-diff-code-text {{
      padding: 0 12px 0 4px;
    }}
    .ahm-diff-added {{
      color: #d3f8df;
      background: color-mix(in srgb, #1f8f4d 24%, transparent 76%);
    }}
    .ahm-diff-added .ahm-diff-marker {{
      color: #60d394;
    }}
    .ahm-diff-removed {{
      color: #ffd6d6;
      background: color-mix(in srgb, #b13a3a 26%, transparent 74%);
    }}
    .ahm-diff-removed .ahm-diff-marker {{
      color: #ff7d7d;
    }}
    .ahm-diff-hunk {{
      color: #c9ddff;
      background: color-mix(in srgb, var(--ahm-accent2) 24%, transparent 76%);
    }}
    .ahm-diff-meta {{
      color: color-mix(in srgb, var(--ahm-muted) 88%, var(--ahm-text) 12%);
      background: color-mix(in srgb, var(--ahm-bg3) 42%, transparent 58%);
    }}
    .ahm-diff-muted {{
      color: var(--ahm-muted);
    }}
    .ahm-history-box {{
      flex: 1 1 auto;
      min-height: 320px;
      overflow: auto;
      border: 1px solid var(--ahm-border);
      border-radius: var(--ahm-radius);
      background: color-mix(in srgb, var(--ahm-bg) 88%, black 12%);
      box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--ahm-bg3) 72%, transparent 28%);
    }}
    .ahm-history-pre {{
      margin: 0;
      padding: 8px 0;
      min-width: max-content;
      font-family: var(--ahm-mono);
      font-size: 10.5px;
      line-height: 1.45;
      color: var(--ahm-text2);
    }}
    .ahm-history-line,
    .ahm-history-commit {{
      display: grid;
      grid-template-columns: 78px 82px minmax(118px, 0.22fr) minmax(320px, 1fr);
      min-height: 17px;
      padding: 0 10px;
      gap: 10px;
      white-space: pre;
      border-bottom: 1px solid color-mix(in srgb, var(--ahm-border) 24%, transparent 76%);
    }}
    .ahm-history-line {{
      display: block;
      white-space: pre;
    }}
    .ahm-history-graph-line {{
      color: color-mix(in srgb, var(--ahm-text2) 92%, var(--ahm-accent2) 8%);
    }}
    .ahm-history-hash {{
      color: var(--ahm-accent2);
      font-weight: 700;
    }}
    .ahm-history-date {{
      color: var(--ahm-muted);
    }}
    .ahm-history-author {{
      color: color-mix(in srgb, var(--ahm-text2) 80%, var(--ahm-muted) 20%);
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .ahm-history-subject {{
      color: var(--ahm-text);
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .ahm-meta-summary {{
      flex: 0 0 auto;
      min-width: 0;
    }}
    .ahm-meta-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }}
    .ahm-meta-row {{
      min-width: 0;
      border: 1px solid var(--ahm-border);
      border-radius: 7px;
      background: color-mix(in srgb, var(--ahm-bg3) 72%, transparent 28%);
      padding: 8px 10px;
    }}
    .ahm-meta-row span {{
      display: block;
      color: var(--ahm-muted);
      font-size: 10px;
      line-height: 1.2;
      text-transform: uppercase;
    }}
    .ahm-meta-row strong {{
      display: block;
      min-width: 0;
      margin-top: 3px;
      color: var(--ahm-text2);
      font-family: var(--ahm-mono);
      font-size: 11px;
      font-weight: 600;
      line-height: 1.25;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .ahm-meta-json textarea {{
      min-height: 185px !important;
      max-height: 320px !important;
      overflow: auto !important;
      font-size: 10px !important;
      line-height: 1.35 !important;
    }}
    .ahm-markdown-editor {{
      width: 100%;
      flex: 1 1 auto;
      height: auto;
      min-height: 220px;
      border: 1px solid var(--ahm-border);
      border-radius: var(--ahm-radius);
      overflow: hidden;
      background: var(--ahm-bg);
    }}
    .ahm-markdown-editor .cm-editor {{
      height: 100%;
      background: var(--ahm-bg) !important;
      color: var(--ahm-text2) !important;
      font-family: var(--ahm-mono);
      font-size: 13.5px;
      line-height: 1.45;
    }}
    .ahm-markdown-editor .cm-editor.cm-focused {{
      outline: 1px solid color-mix(in srgb, var(--ahm-accent) 50%, transparent 50%);
    }}
    .ahm-markdown-editor .cm-scroller {{
      overflow: auto;
      font-family: var(--ahm-mono) !important;
    }}
    .ahm-markdown-editor .cm-content {{
      padding: 10px 12px;
    }}
    .ahm-markdown-editor .cm-gutters {{
      background: color-mix(in srgb, var(--ahm-bg2) 70%, transparent 30%) !important;
      color: var(--ahm-muted) !important;
      border-right: 1px solid var(--ahm-border) !important;
    }}
    .ahm-markdown-editor-fallback textarea {{
      min-height: 360px !important;
      max-height: 520px !important;
      overflow: auto !important;
      font-family: var(--ahm-mono) !important;
      font-size: 13.5px !important;
      white-space: pre;
    }}
    .ahm-command-button .q-btn__content {{
      gap: 9px;
    }}
    .ahm-location-strip {{
      display: flex;
      align-items: center;
      align-content: flex-start;
      column-gap: 14px;
      row-gap: 6px;
      flex-wrap: wrap;
      min-width: 0;
      width: 100%;
      overflow: visible;
    }}
    .ahm-location-pair {{
      display: inline-flex !important;
      align-items: center;
      gap: 0.15rem;
      flex: 0 0 auto;
      min-height: 1.75rem !important;
      min-width: 0;
      max-width: none;
    }}
    .ahm-location-pair + .ahm-location-pair {{
      margin-left: 0;
    }}
    .ahm-location-spacer {{
      flex: 1 1 8px;
      min-width: 0;
    }}
    .audion-action.ahm-scope-button {{
      flex: 0 0 4.2rem !important;
      min-width: 0;
      width: 4.2rem !important;
      max-width: 4.2rem !important;
      min-height: 1.75rem !important;
      height: 1.75rem !important;
      padding: 0 0.45rem !important;
      color: var(--ahm-accent2) !important;
      background: color-mix(in srgb, var(--ahm-accent2) 7%, transparent 93%) !important;
      border: 1px solid color-mix(in srgb, var(--ahm-accent2) 22%, transparent 78%) !important;
      border-radius: var(--ahm-radius) !important;
      text-transform: uppercase !important;
      box-shadow: none !important;
      box-sizing: border-box !important;
    }}
    .audion-action.ahm-scope-button:hover {{
      color: var(--ahm-accent2) !important;
      background: color-mix(in srgb, var(--ahm-accent2) 12%, transparent 88%) !important;
      border-color: color-mix(in srgb, var(--ahm-accent2) 34%, transparent 66%) !important;
    }}
    .q-btn.audion-action.ahm-scope-button-active {{
      color: var(--ahm-text) !important;
      background: color-mix(in srgb, var(--ahm-accent2) 22%, transparent 78%) !important;
      border-color: color-mix(in srgb, var(--ahm-accent2) 44%, transparent 56%) !important;
      font-weight: 650 !important;
    }}
    .q-btn.audion-action.ahm-scope-button-active:hover {{
      color: var(--ahm-text) !important;
      background: color-mix(in srgb, var(--ahm-accent2) 28%, transparent 72%) !important;
    }}
    .q-btn.audion-action.ahm-scope-button-active .q-btn__content {{
      color: var(--ahm-text) !important;
    }}
    .q-btn.audion-action.ahm-scope-button .q-btn__content,
    .ahm-scope-button .q-btn__content {{
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 0.72rem;
      text-transform: uppercase;
      line-height: 1;
      justify-content: center !important;
      text-align: center !important;
    }}
    .ahm-location-pick,
    .ahm-location-clear {{
      width: 1.75rem !important;
      min-width: 1.75rem !important;
      height: 1.75rem !important;
      min-height: 1.75rem !important;
      padding: 0 !important;
      box-sizing: border-box !important;
    }}
    .ahm-location-pick .q-btn__content,
    .ahm-location-clear .q-btn__content {{
      justify-content: center;
      line-height: 1;
    }}
    .ahm-location-label {{
      display: none;
    }}
    .ahm-tree-toolbar {{
      display: grid;
      grid-template-columns: minmax(138px, 0.34fr) minmax(180px, 1fr);
      gap: 8px;
      min-width: 0;
    }}
    .ahm-command-row {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) 88px 88px;
      gap: 8px;
      align-items: start;
      min-width: 0;
      flex: 0 0 auto;
    }}
    .ahm-status {{
      border-radius: 999px;
      color: var(--ahm-muted);
      font-size: 11px;
      line-height: 1;
      padding: 5px 9px;
      white-space: nowrap;
      background: color-mix(in srgb, var(--ahm-bg2) 82%, var(--ahm-muted) 18%);
    }}
    .ahm-status-running {{ color: {val('color-text-info', '#B5D4F4')}; background: {val('color-background-info', '#042C53')}; }}
    .ahm-status-success {{ color: {val('color-text-success', '#C0DD97')}; background: {val('color-background-success', '#173404')}; }}
    .ahm-status-error {{ color: {val('color-text-danger', '#F7C1C1')}; background: {val('color-background-danger', '#501313')}; }}
    .ahm-status-blocked {{ color: {val('color-text-warning', '#FAC775')}; background: {val('color-background-warning', '#412402')}; }}
    .audion-action {{
      color: var(--ahm-accent) !important;
      background: transparent !important;
      border: 0 !important;
      min-height: 28px !important;
      height: 28px !important;
      padding-left: 8px !important;
      padding-right: 8px !important;
      text-transform: none !important;
      box-shadow: none !important;
    }}
    .audion-action:hover {{
      background: var(--ahm-bg) !important;
    }}
    .ahm-expand-button {{
      width: 20px !important;
      min-width: 20px !important;
      height: 20px !important;
      min-height: 20px !important;
      padding: 0 !important;
      color: var(--ahm-accent2) !important;
      border: 0 !important;
      background: transparent !important;
      border-radius: var(--ahm-radius) !important;
      opacity: 0.82;
    }}
    .ahm-expand-button:hover {{
      color: var(--ahm-text) !important;
      background: color-mix(in srgb, var(--ahm-accent2) 12%, transparent 88%) !important;
      opacity: 1;
    }}
    .ahm-expand-button .q-btn__content {{
      justify-content: center !important;
      font-size: 13px !important;
    }}
    .ahm-pane-icon-button {{
      width: 28px !important;
      min-width: 28px !important;
      height: 24px !important;
      min-height: 24px !important;
      padding: 0 !important;
      color: var(--ahm-accent2) !important;
      border: 0 !important;
      background: transparent !important;
      border-radius: var(--ahm-radius) !important;
      opacity: 0.82;
    }}
    .ahm-pane-icon-button:hover {{
      color: var(--ahm-text) !important;
      background: color-mix(in srgb, var(--ahm-accent2) 12%, transparent 88%) !important;
      opacity: 1;
    }}
    .ahm-pane-icon-button .q-btn__content {{
      justify-content: center !important;
      font-size: 14px !important;
    }}
    .ahm-pane-icon-button .q-icon {{
      font-size: 22px !important;
    }}
    .ahm-pane-control-button {{
      min-width: 74px !important;
      height: 24px !important;
      min-height: 24px !important;
      padding: 0 9px !important;
      color: var(--ahm-accent2) !important;
      border: 0 !important;
      background: transparent !important;
      border-radius: var(--ahm-radius) !important;
      opacity: 0.9;
      text-transform: none !important;
    }}
    .ahm-pane-control-button:hover {{
      color: var(--ahm-text) !important;
      background: color-mix(in srgb, var(--ahm-accent2) 12%, transparent 88%) !important;
      opacity: 1;
    }}
    .ahm-pane-control-button .q-btn__content {{
      justify-content: flex-start !important;
      gap: 7px !important;
      font-size: 12px !important;
      line-height: 1 !important;
      width: auto !important;
    }}
    .ahm-pane-control-button .q-icon {{
      font-size: 17px !important;
    }}
    .ahm-pane-vscode-button {{
      color: var(--ahm-accent) !important;
    }}
    .audion-action .q-btn__content {{
      width: 100%;
      justify-content: flex-start;
      overflow: visible;
      white-space: nowrap;
      flex-wrap: nowrap !important;
      font-size: 12px;
      line-height: 1;
    }}
    .audion-primary-action {{
      color: var(--ahm-accent2) !important;
      background: color-mix(in srgb, var(--ahm-accent2) 10%, transparent 90%) !important;
      border: 1px solid color-mix(in srgb, var(--ahm-accent2) 30%, transparent 70%) !important;
      border-radius: var(--ahm-radius) !important;
      font-weight: 650 !important;
    }}
    .audion-primary-action:hover {{
      background: color-mix(in srgb, var(--ahm-accent2) 16%, var(--ahm-bg) 84%) !important;
      border-color: color-mix(in srgb, var(--ahm-accent2) 44%, transparent 56%) !important;
    }}
    .audion-primary-action .q-btn__content {{
      justify-content: center;
    }}
    .ahm-command-button.audion-primary-action {{
      color: var(--ahm-accent2) !important;
      background: transparent !important;
      border: 0 !important;
      box-shadow: none !important;
    }}
    .ahm-command-button.audion-primary-action:hover {{
      color: var(--ahm-text) !important;
      background: color-mix(in srgb, var(--ahm-accent2) 10%, transparent 90%) !important;
      border: 0 !important;
    }}
    /* Command chips: dark at rest, semantic outlines appear only on interaction. */
    .q-btn.audion-action:not(.ahm-pane-vscode-button) {{
      --q-primary: var(--ahm-button-label);
      color: var(--ahm-button-label) !important;
    }}
    .q-btn.audion-action:not(.ahm-pane-vscode-button) .q-btn__content,
    .q-btn.audion-action:not(.ahm-pane-vscode-button) .q-btn__content > .block,
    .q-btn.audion-action:not(.ahm-pane-vscode-button) .q-icon {{
      color: inherit !important;
    }}
    .q-btn.ahm-command-button {{
      background: var(--ahm-command-chip) !important;
      border: 0 !important;
      box-shadow: none !important;
      transition:
        color 150ms ease,
        background-color 150ms ease,
        box-shadow 150ms ease !important;
    }}
    .q-btn.ahm-command-button:is(.ahm-command-safe, .ahm-command-read):is(:hover, :focus-visible) {{
      color: var(--ahm-button-label-hover) !important;
      background: color-mix(in srgb, var(--ahm-command-safe-ring) 10%, var(--ahm-command-chip) 90%) !important;
      box-shadow:
        inset 0 0 0 1px color-mix(in srgb, var(--ahm-command-safe-ring) 78%, transparent 22%),
        0 0 12px color-mix(in srgb, var(--ahm-command-safe-ring) 18%, transparent 82%) !important;
    }}
    .q-btn.ahm-command-button:is(.ahm-command-caution, .ahm-command-danger):is(:hover, :focus-visible) {{
      color: var(--ahm-button-label-hover) !important;
      background: color-mix(in srgb, var(--ahm-command-danger-ring) 11%, var(--ahm-command-chip) 89%) !important;
      box-shadow:
        inset 0 0 0 1px color-mix(in srgb, var(--ahm-command-danger-ring) 82%, transparent 18%),
        0 0 12px color-mix(in srgb, var(--ahm-command-danger-ring) 20%, transparent 80%) !important;
    }}
    .q-btn.ahm-command-button:is(.ahm-command-safe, .ahm-command-read):active {{
      background: var(--ahm-command-chip-pressed) !important;
      box-shadow:
        inset 0 0 0 1px var(--ahm-command-safe-ring),
        0 0 16px color-mix(in srgb, var(--ahm-command-safe-ring) 28%, transparent 72%) !important;
    }}
    .q-btn.ahm-command-button:is(.ahm-command-caution, .ahm-command-danger):active {{
      background: var(--ahm-command-chip-pressed) !important;
      box-shadow:
        inset 0 0 0 1px var(--ahm-command-danger-ring),
        0 0 16px color-mix(in srgb, var(--ahm-command-danger-ring) 30%, transparent 70%) !important;
    }}
    .ahm-check-grid .q-checkbox,
    .ahm-check-row .q-checkbox,
    .ahm-open-layer-grid .q-btn.ahm-op-button,
    .ahm-open-tool-grid .q-btn.ahm-op-button,
    .q-btn.ahm-scope-button,
    .q-btn.ahm-location-pick,
    .q-btn.ahm-location-clear {{
      background: var(--ahm-command-chip) !important;
      border: 0 !important;
      border-radius: 6px !important;
      box-shadow: none !important;
      transition:
        color 150ms ease,
        background-color 150ms ease,
        box-shadow 150ms ease !important;
    }}
    .ahm-check-grid .q-checkbox,
    .ahm-check-row .q-checkbox {{
      min-height: 28px !important;
      padding: 0 8px !important;
    }}
    .ahm-check-grid .q-checkbox .q-checkbox__label,
    .ahm-check-row .q-checkbox .q-checkbox__label {{
      color: var(--ahm-button-label) !important;
    }}
    .ahm-open-layer-grid .q-btn.ahm-op-button,
    .ahm-open-tool-grid .q-btn.ahm-op-button,
    .q-btn.ahm-scope-button,
    .q-btn.ahm-location-pick,
    .q-btn.ahm-location-clear {{
      --q-primary: var(--ahm-button-label);
      color: var(--ahm-button-label) !important;
    }}
    .q-btn.ahm-scope-button-active {{
      color: var(--ahm-button-label-hover) !important;
      background: color-mix(in srgb, var(--ahm-command-safe-ring) 12%, var(--ahm-command-chip) 88%) !important;
      border: 0 !important;
      box-shadow: none !important;
    }}
    .ahm-check-grid .q-checkbox:is(:hover, :focus-within),
    .ahm-check-row .q-checkbox:is(:hover, :focus-within),
    .ahm-open-layer-grid .q-btn.ahm-op-button:is(:hover, :focus-visible),
    .ahm-open-tool-grid .q-btn.ahm-op-button:is(:hover, :focus-visible),
    .q-btn.ahm-scope-button:is(:hover, :focus-visible),
    .q-btn.ahm-location-pick:is(:hover, :focus-visible),
    .q-btn.ahm-location-clear:is(:hover, :focus-visible) {{
      color: var(--ahm-button-label-hover) !important;
      background: color-mix(in srgb, var(--ahm-command-safe-ring) 10%, var(--ahm-command-chip) 90%) !important;
      box-shadow:
        inset 0 0 0 1px color-mix(in srgb, var(--ahm-command-safe-ring) 78%, transparent 22%),
        0 0 12px color-mix(in srgb, var(--ahm-command-safe-ring) 18%, transparent 82%) !important;
    }}
    .ahm-check-grid .q-checkbox:active,
    .ahm-check-row .q-checkbox:active,
    .ahm-open-layer-grid .q-btn.ahm-op-button:active,
    .ahm-open-tool-grid .q-btn.ahm-op-button:active,
    .q-btn.ahm-scope-button:active,
    .q-btn.ahm-location-pick:active,
    .q-btn.ahm-location-clear:active {{
      background: var(--ahm-command-chip-pressed) !important;
    }}
    @media (prefers-reduced-motion: reduce) {{
      .q-btn.ahm-command-button,
      .ahm-check-grid .q-checkbox,
      .ahm-check-row .q-checkbox,
      .ahm-open-layer-grid .q-btn.ahm-op-button,
      .ahm-open-tool-grid .q-btn.ahm-op-button,
      .q-btn.ahm-scope-button,
      .q-btn.ahm-location-pick,
      .q-btn.ahm-location-clear {{ transition: none !important; }}
    }}
    .audion-select .q-field__control,
    .audion-input .q-field__control,
    .audion-terminal-field .q-field__control {{
      background: var(--ahm-bg3) !important;
      color: var(--ahm-text) !important;
      min-height: 34px !important;
    }}
    .audion-select .q-field__control:before,
    .audion-input .q-field__control:before,
    .audion-terminal-field .q-field__control:before {{
      border-color: var(--ahm-border) !important;
    }}
    .audion-select.q-field--outlined:hover .q-field__control:before,
    .audion-input.q-field--outlined:hover .q-field__control:before,
    .audion-terminal-field.q-field--outlined:hover .q-field__control:before {{
      border-color: var(--ahm-border2) !important;
    }}
    .audion-select .q-field__native,
    .audion-select .q-field__input,
    .audion-input .q-field__native,
    .audion-input .q-field__input,
    .audion-terminal-field textarea,
    .q-checkbox__label {{
      font-family: var(--ahm-font) !important;
      font-size: 13px !important;
      color: var(--ahm-text2) !important;
    }}
    .audion-select .q-field__bottom,
    .audion-input .q-field__bottom,
    .audion-terminal-field .q-field__bottom {{ display: none !important; }}
    .audion-input.ahm-command-value-input .q-field__inner,
    .audion-input.ahm-command-value-input .q-field__control,
    .audion-input.ahm-command-value-input .q-field__control-container {{
      min-height: 28px !important;
      height: 28px !important;
    }}
    .audion-input.ahm-command-value-input .q-field__control {{
      padding: 0 8px !important;
    }}
    .audion-input.ahm-command-value-input .q-field__native,
    .audion-input.ahm-command-value-input .q-field__input,
    .audion-input.ahm-command-value-input input {{
      min-height: 26px !important;
      height: 26px !important;
      line-height: 26px !important;
      padding-top: 0 !important;
      padding-bottom: 1px !important;
      font-size: 12px !important;
      color: var(--ahm-text2) !important;
    }}
    .audion-input.ahm-command-value-input input::placeholder {{
      color: color-mix(in srgb, var(--ahm-muted) 72%, transparent 28%) !important;
      opacity: 1 !important;
    }}
    .audion-theme-select {{
      width: 176px;
      min-height: 32px !important;
      height: 32px !important;
    }}
    .audion-theme-select.q-field,
    .audion-theme-select .q-field__inner {{
      min-height: 32px !important;
      height: 32px !important;
      padding-bottom: 0 !important;
    }}
    .audion-theme-select .q-field__control {{
      min-height: 32px !important;
      height: 32px !important;
      background: transparent !important;
      padding: 0 8px 0 14px !important;
    }}
    .audion-theme-select .q-field__marginal,
    .audion-theme-select .q-field__native,
    .audion-theme-select .q-field__append {{
      min-height: 32px !important;
      height: 32px !important;
      font-size: 13px !important;
    }}
    .audion-theme-select .q-field__native {{
      align-items: center !important;
      line-height: 32px !important;
      padding: 0 0 1px 0 !important;
    }}
    .ahm-terminal-output {{
      flex: 1 1 auto;
      min-height: 0;
      height: auto !important;
      overflow: hidden;
      border: 1px solid var(--ahm-border2);
      border-radius: 7px;
      background: var(--ahm-bg3);
    }}
    #ahm-terminal-output {{
      height: 100% !important;
      min-height: 0;
      max-height: 100%;
      overflow-x: hidden;
      overflow-y: auto;
      scrollbar-gutter: stable;
    }}
    .audion-terminal-pre {{
      box-sizing: border-box;
      display: block;
      width: 100%;
      height: 100% !important;
      margin: 0;
      min-height: 0 !important;
      font-family: "Cascadia Mono", "Cascadia Code", Consolas, monospace !important;
      font-size: 9.5pt !important;
      font-weight: 400 !important;
      line-height: 1.35 !important;
      padding: 8px 10px !important;
      white-space: pre-wrap !important;
      overflow-wrap: anywhere !important;
      word-break: break-word !important;
      overflow: visible;
      color: var(--ahm-text);
    }}
    .audion-terminal-line {{
      min-height: 1.35em;
    }}
    body.ahm-has-expanded-panel {{
      overflow: hidden !important;
    }}
    .ahm-expanded-panel {{
      position: fixed !important;
      inset: 48px 14px 14px 14px !important;
      z-index: 7000 !important;
      width: auto !important;
      max-width: none !important;
      height: auto !important;
      min-height: 0 !important;
      border: 1px solid color-mix(in srgb, var(--ahm-accent2) 48%, var(--ahm-border2) 52%) !important;
      box-shadow: 0 22px 80px rgba(0, 0, 0, 0.55), 0 0 0 9999px rgba(0, 0, 0, 0.38) !important;
      background: color-mix(in srgb, var(--ahm-bg2) 96%, black 4%) !important;
    }}
    .ahm-expanded-panel.ahm-editor-pane .ahm-markdown-editor {{
      flex: 1 1 auto;
      height: auto !important;
      min-height: 0 !important;
    }}
    .ahm-expanded-panel.ahm-editor-pane .ahm-markdown-editor-fallback textarea {{
      min-height: 0 !important;
      max-height: none !important;
      height: calc(100vh - 220px) !important;
    }}
    .ahm-expanded-panel.ahm-diff-pane .ahm-diff-box,
    .ahm-expanded-panel.ahm-terminal .ahm-terminal-output {{
      flex: 1 1 auto;
      min-height: 0 !important;
      height: auto !important;
    }}
    .ahm-expanded-panel.ahm-terminal {{
      display: flex;
      flex-direction: column;
    }}
    .q-checkbox {{
      min-height: 21px !important;
      align-items: center !important;
    }}
    .q-checkbox__inner {{
      font-size: 32px !important;
      flex: 0 0 auto;
    }}
    .q-checkbox__label {{
      color: var(--ahm-text2) !important;
      font-size: 12px;
      line-height: 1.2;
      min-width: 0;
      white-space: nowrap;
    }}
    .ahm-check-grid .q-checkbox .q-checkbox__label,
    .ahm-check-row .q-checkbox .q-checkbox__label {{
      color: var(--ahm-button-label) !important;
    }}
    .q-tab {{
      color: var(--ahm-muted);
      text-transform: uppercase;
      min-height: 28px;
      padding: 0 8px;
      justify-content: center !important;
      text-align: center !important;
    }}
    .q-tab .q-focus-helper,
    .q-tab .q-tab__content {{
      justify-content: center !important;
      text-align: center !important;
      width: 100%;
    }}
    .q-tab .q-tab__label {{
      width: 100%;
      text-align: center !important;
    }}
    .q-tab--active {{ color: var(--ahm-accent) !important; }}
    .q-tabs {{ min-height: 28px; }}
    .ahm-tab-toggle-pairs {{
      min-height: 56px !important;
    }}
    .ahm-tab-toggle-pairs .q-tabs__content {{
      display: grid !important;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      grid-auto-rows: 28px;
      align-items: stretch;
      width: 100%;
      min-width: 0;
      overflow: hidden;
    }}
    .ahm-tab-toggle-pairs .q-tab {{
      width: 100%;
      min-width: 0;
      min-height: 28px !important;
      height: 28px !important;
      padding: 0 4px !important;
    }}
    .ahm-tab-toggle-pairs .q-tab .q-tab__content {{
      display: grid !important;
      grid-template-columns: 18px minmax(0, auto);
      column-gap: 6px;
      align-items: center !important;
      justify-content: center !important;
      justify-items: start !important;
      text-align: left !important;
      width: 100%;
      min-width: 0;
    }}
    .ahm-tab-toggle-pairs .q-tab .q-icon {{
      justify-self: center;
      font-size: 17px !important;
      line-height: 1 !important;
    }}
    .ahm-tab-toggle-pairs .q-tab__label {{
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 11px;
      line-height: 1;
      text-align: left !important;
    }}
    .q-tree, .q-tab-panels, .q-tab-panel {{ background: transparent !important; color: var(--ahm-text); }}
    .ahm-tree-holder .q-tree {{
      color: color-mix(in srgb, var(--ahm-text2) 50%, transparent 50%) !important;
      font-size: 10.5px !important;
      line-height: 1.1 !important;
      font-family: var(--ahm-mono);
      min-width: max-content;
    }}
    .ahm-tree-holder .q-tree__node:after,
    .ahm-tree-holder .q-tree__node-header:before,
    .ahm-tree-holder .q-tree__node-body:after {{
      border-color: color-mix(in srgb, var(--ahm-accent) 38%, transparent 62%) !important;
    }}
    .ahm-tree-holder .q-tree__node-header {{
      min-height: 18px !important;
      padding: 1px 2px 1px 0 !important;
      border-radius: 6px;
      transition: background-color 100ms ease, box-shadow 100ms ease;
    }}
    .ahm-tree-holder .q-tree__node-header:hover {{
      background: color-mix(in srgb, var(--ahm-accent2) 12%, transparent 88%) !important;
      box-shadow: inset 2px 0 0 color-mix(in srgb, var(--ahm-accent2) 72%, transparent 28%);
    }}
    .ahm-tree-holder .q-tree__node-header:hover .ahm-tree-node-label {{
      color: var(--ahm-text) !important;
    }}
    .ahm-tree-holder .q-tree__children {{
      padding-left: 28px !important;
      margin-left: 0 !important;
    }}
    .ahm-tree-holder .q-tree__node-header-content {{
      min-width: 0;
    }}
    .ahm-tree-holder .q-tree__node-header-content .q-tree__node-label {{
      color: var(--ahm-text2) !important;
      white-space: nowrap;
    }}
    .ahm-tree-node-header {{
      display: inline-flex;
      align-items: center;
      gap: 4px;
      min-width: 0;
      white-space: nowrap;
    }}
    .ahm-tree-node-editor .ahm-tree-node-label {{
      color: color-mix(in srgb, var(--ahm-text2) 82%, var(--ahm-accent2) 18%) !important;
    }}
    .ahm-tree-node-diff .ahm-tree-node-label {{
      color: color-mix(in srgb, var(--ahm-text2) 80%, var(--ahm-accent) 20%) !important;
    }}
    .ahm-tree-open-vscode {{
      color: var(--ahm-accent) !important;
      opacity: 0;
      margin-left: 4px;
      transition: opacity 100ms ease;
    }}
    .ahm-tree-holder .q-tree__node-header:hover .ahm-tree-open-vscode {{
      opacity: 1;
    }}
    .ahm-tree-hover-hint {{
      width: 14px;
      min-width: 14px;
      font-size: 13px !important;
      line-height: 1 !important;
      opacity: 0;
      transition: opacity 100ms ease;
    }}
    .ahm-tree-hover-editor {{
      color: var(--ahm-accent2) !important;
    }}
    .ahm-tree-hover-diff {{
      color: var(--ahm-accent) !important;
    }}
    .ahm-tree-holder .q-tree__node-header:hover .ahm-tree-hover-hint {{
      opacity: 0.92;
    }}
    .ahm-git-status-dot {{
      width: 10px;
      min-width: 10px;
      font-size: 8px !important;
      line-height: 1 !important;
    }}
    .ahm-tree-kind-icon {{
      width: 14px;
      min-width: 14px;
      color: color-mix(in srgb, var(--ahm-accent2) 78%, var(--ahm-muted) 22%) !important;
      font-size: 14px !important;
      line-height: 1 !important;
    }}
    .ahm-tree-node-label {{
      color: var(--ahm-text2) !important;
      white-space: nowrap;
    }}
    .ahm-tree-status-summary {{
      color: var(--ahm-muted);
      font-size: 9px;
      font-weight: 700;
      line-height: 1;
      margin-left: 4px;
      opacity: 0.84;
      white-space: nowrap;
    }}
    .ahm-tree-holder .q-tree__arrow,
    .ahm-tree-holder .q-tree__tickbox,
    .ahm-tree-holder .q-tree__spinner,
    .ahm-tree-holder .q-tree__icon,
    .ahm-tree-holder .q-tree__node-header-content .q-icon:not(.ahm-git-status-dot):not(.ahm-tree-kind-icon) {{
      color: color-mix(in srgb, var(--ahm-text2) 50%, transparent 50%) !important;
      font-size: 14px !important;
    }}
    .ahm-tree-holder .q-tree__node-body {{
      padding: 0 0 0 18px !important;
    }}
    .q-tab-panel {{ padding: 5px 0 0 !important; }}
    @media (max-width: 1500px) {{
      .ahm-command-grid {{
        grid-template-columns: repeat(3, minmax(0, 1fr));
      }}
      .ahm-command-cache-tools-row {{
        grid-template-columns: repeat(2, minmax(0, 1fr)) repeat(4, 34px);
      }}
      .ahm-custom-command-row {{
        grid-template-columns: minmax(0, 1fr) minmax(76px, auto);
      }}
    }}
    @media (max-width: 900px) {{
      html, body {{ overflow: auto; }}
      .nicegui-content {{ height: auto; overflow: visible; }}
      .ahm-root {{ display: flex; flex-direction: column; height: auto; overflow: visible; }}
      .ahm-main {{ grid-template-columns: minmax(0, 1fr); }}
      .ahm-basket-command-layout,
      .ahm-basket-param-grid,
      .ahm-basket-action-grid {{
        grid-template-columns: minmax(0, 1fr);
      }}
      .ahm-command-grid,
      .ahm-editor-command-grid,
      .ahm-auth-command-grid,
      .ahm-diff-command-grid,
      .ahm-history-command-grid,
      .ahm-meta-command-grid,
      .ahm-safety-command-grid,
      .ahm-storage-command-grid {{ grid-template-columns: minmax(0, 1fr); }}
      .ahm-remote-config-grid {{ grid-template-columns: minmax(0, 1fr); }}
      .ahm-remote-grid-spacer {{ display: none; }}
      .ahm-meta-grid {{ grid-template-columns: minmax(0, 1fr); }}
      .ahm-pinned-command-row,
      .ahm-command-cache-tools-row,
      .ahm-custom-command-row {{ grid-template-columns: minmax(0, 1fr); }}
      .ahm-splitter {{ display: none; }}
      .ahm-button-grid-three {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .ahm-tree-toolbar {{ grid-template-columns: minmax(0, 1fr); }}
      .ahm-tab-toggle-pairs .q-tabs__content {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
        grid-auto-rows: 28px;
      }}
      .ahm-tab-toggle-pairs {{
        min-height: 140px !important;
      }}
    }}
    </style>
    """
