from __future__ import annotations

from system_core.ui_nicegui.theme import css_from_tokens


def test_command_accent_layer_is_interaction_only() -> None:
    css = css_from_tokens({})

    assert "--ahm-button-label:" in css
    assert "--ahm-button-label-hover:" in css
    assert "--ahm-button-label: #E8E6DC;" in css
    assert "body.body--light" in css
    assert "--ahm-button-label: #444444;" in css
    assert "--ahm-command-chip:" in css
    assert "--ahm-command-chip-pressed:" in css
    assert "--ahm-command-chip: color-mix(in srgb, var(--ahm-bg3) 86%, var(--ahm-bg) 14%);" in css
    assert "--ahm-command-chip-pressed: color-mix(in srgb, var(--ahm-command-chip) 88%, #000 12%);" in css
    assert "--ahm-command-safe-ring:" in css
    assert "--ahm-command-danger-ring:" in css
    assert ".q-btn.ahm-command-button {" in css
    assert "background: var(--ahm-command-chip) !important;" in css
    assert "background: var(--ahm-command-chip-pressed) !important;" in css
    assert ".ahm-check-grid .q-checkbox" in css
    assert ".ahm-check-row .q-checkbox" in css
    generic_checkbox_label = css.find("\n    .q-checkbox__label {")
    chip_checkbox_label = css.find("\n    .ahm-check-grid .q-checkbox .q-checkbox__label", generic_checkbox_label)
    assert generic_checkbox_label >= 0
    assert chip_checkbox_label > generic_checkbox_label
    assert ".ahm-open-layer-grid .q-btn.ahm-op-button" in css
    assert ".ahm-open-tool-grid .q-btn.ahm-op-button" in css
    assert ".q-btn.ahm-scope-button" in css
    assert ".q-btn.ahm-location-pick" in css
    assert "border: 0 !important;" in css
    assert ".ahm-command-safe, .ahm-command-read" in css
    assert ".ahm-command-caution, .ahm-command-danger" in css
    assert ":is(:hover, :focus-visible)" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
