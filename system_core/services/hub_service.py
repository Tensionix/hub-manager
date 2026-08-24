from __future__ import annotations

from system_core.core.project_registry import load_project_registry
from system_core.core.projection_engine import apply_projection_plan, plan_projection_from_project


def preview_active_project() -> dict:
    registry = load_project_registry()
    return plan_projection_from_project(registry.active_project())


def apply_active_project() -> dict:
    plan = preview_active_project()
    return apply_projection_plan(plan, dry_run=False)
