from __future__ import annotations

from pathlib import Path

import pytest

from system_core.core.json_utils import load_json_safe
from system_core.core.project_registry import load_project_registry
from system_core.core.projection_engine import ProjectionProfile, apply_projection_plan


def test_load_json_safe_never_raises_on_broken_content(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text('{ "projects": [ , ] }', encoding="utf-8")

    payload, error = load_json_safe(broken, default={"projects": []})

    assert payload == {"projects": []}
    assert "broken.json" in error


def test_load_json_safe_reports_nothing_for_a_missing_file(tmp_path: Path) -> None:
    payload, error = load_json_safe(tmp_path / "absent.json", default={"a": 1})
    assert (payload, error) == ({"a": 1}, "")


def test_registry_survives_a_broken_file_and_still_yields_a_project(tmp_path: Path) -> None:
    # A stray comma used to abort startup with a traceback before the window opened.
    config = tmp_path / "projects.json"
    config.write_text('{ "projects": [ , ] }', encoding="utf-8")

    registry = load_project_registry(config)

    assert registry.projects == []
    assert registry.load_error
    assert registry.active_project().id == "unconfigured"


def test_registry_skips_one_broken_record_but_keeps_the_others(tmp_path: Path) -> None:
    config = tmp_path / "projects.json"
    config.write_text(
        '{"active_project_id": "good", "projects": [{"id": "good", "source_path": "."}, "not a record"]}',
        encoding="utf-8",
    )

    registry = load_project_registry(config)

    assert [project.id for project in registry.projects] == ["good"]
    assert registry.active_project().id == "good"


def test_apply_refuses_a_plan_whose_roots_overlap(tmp_path: Path) -> None:
    # Plans are JSON and can be stale or edited; deleting under a nested root
    # would take out the source itself.
    source = tmp_path / "source"
    projection = source / "inside"
    source.mkdir()
    projection.mkdir()
    profile = ProjectionProfile(id="test", include_globs=["**/*.py"])

    plan = {
        "source_root": str(source),
        "projection_root": str(projection),
        "profile": profile.to_json(),
        "source_dirs": [],
        "items": [],
    }

    with pytest.raises(ValueError, match="Refusing"):
        apply_projection_plan(plan, dry_run=False)


def test_delete_phase_is_skipped_after_errors_even_when_the_profile_allows_deleting(tmp_path: Path) -> None:
    source = tmp_path / "source"
    projection = tmp_path / "projection"
    source.mkdir()
    projection.mkdir()
    (projection / "stale.py").write_text("x = 1\n", encoding="utf-8")
    profile = ProjectionProfile(id="test", include_globs=["**/*.py"], delete_after_successful_copy=False)

    plan = {
        "source_root": str(source),
        "projection_root": str(projection),
        "profile": profile.to_json(),
        "source_dirs": [],
        "items": [
            {"action": "error", "rel_path": "broken.py", "reason": "hash_failed"},
            {"action": "delete", "rel_path": "stale.py", "target": {"abs_path": str(projection / "stale.py")}},
        ],
    }

    result = apply_projection_plan(plan, dry_run=False)

    assert (projection / "stale.py").exists()
    assert result["summary"]["delete_phase_skipped"] is True
    assert result["summary"]["deleted"] == 0
