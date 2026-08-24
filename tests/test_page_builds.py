"""The smoke has to notice a page that cannot be built."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from system_core.ui_nicegui import app as gui


def test_the_smoke_builds_the_page() -> None:
    report = gui.smoke_check()

    assert report["ok"] is True
    assert report["widgets"] > 100, report
    assert report["stylesheet_bytes"] > 1000, report


def test_a_page_that_cannot_be_built_fails_the_smoke(monkeypatch) -> None:
    """This app reads config and themes in its smoke; nothing built the page.

    Two apps in this fleet shipped a build function that raised on its first
    statement because their smoke never called it.
    """
    def broken() -> None:
        raise RuntimeError("panel is missing")

    monkeypatch.setattr(gui, "_build_ui", broken)
    report = gui.smoke_check()

    assert report["ok"] is False
    assert "panel is missing" in report["error"]
