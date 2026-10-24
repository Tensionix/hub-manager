from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import Path
import json
import random

from system_core.core.mask_engine import matches_any

ROOT = Path(__file__).resolve().parents[1]


def _reference(rel: str, name: str, patterns: list[str]) -> bool:
    """The masks one by one, as fnmatch reads them: what the fast matcher must answer."""
    rel, name = rel.lower(), name.lower()
    for pattern in patterns:
        p = pattern.strip().lower()
        if not p:
            continue
        if p.endswith("/**") and rel == p[:-3]:
            return True
        if fnmatchcase(rel, p) or fnmatchcase(name, p):
            return True
    return False


def test_the_fast_matcher_answers_as_every_mask_one_by_one() -> None:
    profiles = json.loads((ROOT / "config" / "projection_profiles.json").read_text(encoding="utf-8"))["profiles"]
    lists = [p.get(key, []) for p in profiles.values() for key in ("include_globs", "exclude_globs", "small_include_globs")]
    lists = [items for items in lists if items] + [["*", "LICENSE*", "docs/**", "a?b.txt", "[ab].md", "", "*.min.js"]]
    words = ["src", "docs", "App", "licenses", "node_modules", "Source", "Assets", ".github", "config", "a", "lib"]
    names = ["main.py", "README.md", "app.min.js", "LICENSE", "license.txt", "x.deps.json", "a1b.txt", "b.md", ".env",
             ".env.example", "Makefile", "style.css", "photo.PNG", "font.ttf", "core.obj", "yarn.lock", "id_rsa", "x"]
    rng = random.Random(7)
    checked = 0
    for patterns in lists:
        for _ in range(400):
            folders = [rng.choice(words) for _ in range(rng.randint(0, 3))]
            name = rng.choice(names)
            rel = "/".join(folders + [name])
            assert matches_any(rel, name, patterns) == _reference(rel, name, patterns), (rel, patterns[:5])
            # A folder written as `folder/**` matches the folder itself.
            assert matches_any("/".join(folders), folders[-1] if folders else "", patterns) == _reference(
                "/".join(folders), folders[-1] if folders else "", patterns)
            checked += 1
    assert checked >= 400 * len(lists)
