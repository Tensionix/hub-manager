"""The English of the window: every Russian text it shows has its pair (Source\\Tools\\check_i18n.py), and so do the
titles the program writes into the registry itself - the lessons of the lab, shown through the dictionary."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from system_core.core.hub_ops import LAB_TITLES

ROOT = Path(__file__).resolve().parents[1]


def _watchman():
    spec = importlib.util.spec_from_file_location("check_i18n", ROOT / "Source" / "Tools" / "check_i18n.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_russian_text_of_the_window_has_its_english_pair() -> None:
    assert _watchman().problems() == []


def test_the_lessons_of_the_lab_are_named_in_english_too() -> None:
    pairs = json.loads((ROOT / "Source" / "config" / "i18n.json").read_text(encoding="utf-8-sig"))
    missing = [title for title in LAB_TITLES.values() if not pairs.get(title, {}).get("en")]
    assert missing == []
