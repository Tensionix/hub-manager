from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        if default is not None:
            return default
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def load_json_safe(path: Path, default: Any) -> tuple[Any, str]:
    """Read JSON without ever raising. Returns (payload, error_text).

    Config files are hand-edited, and a single stray comma used to take the
    whole application down before the window even opened. Callers that run at
    startup use this and surface the error instead of dying.
    """
    if not path.exists():
        return default, ""
    try:
        return json.loads(path.read_text(encoding="utf-8")), ""
    except (ValueError, OSError) as exc:
        return default, f"{path.name}: {exc.__class__.__name__}: {exc}"


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
