from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from system_core.core.project_registry import load_project_registry
from system_core.core.project_importer import merge_project_import, scan_project_folder
from system_core.core.projection_engine import (
    apply_projection_plan,
    plan_projection_from_project,
    verify_projection_mirror_from_project,
    write_report,
)
from system_core.core.safety import scan_safety
from system_core.core.storage_layout import storage_layout_status
from system_core.core.docs_view import plan_docs_view
from system_core.core.json_utils import load_json, save_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Audion Hub Manager")
    parser.add_argument("--doctor", action="store_true", help="Run a lightweight project/config doctor")
    parser.add_argument("--storage-doctor", action="store_true", help="Run storage root and project path checks")
    parser.add_argument("--auth-doctor", action="store_true", help="Run non-interactive Git/GitHub/GitLab auth probes")
    parser.add_argument("--scan-projects", metavar="ROOT", help="Scan a folder with projects and nested project roots")
    parser.add_argument("--hub-root", metavar="PATH", help="Hub Data root used by --scan-projects")
    parser.add_argument("--docs-root", metavar="PATH", help="Docs root used by --scan-projects")
    parser.add_argument("--import-projects", action="store_true", help="Append --scan-projects results to config/projects.json")
    parser.add_argument("--scan-depth", type=int, default=3, help="Nested scan depth for --scan-projects")
    parser.add_argument("--mirror-preview", metavar="PROJECT_ID", help="Build projection plan for project id")
    parser.add_argument("--mirror-apply", metavar="PROJECT_ID", help="Apply projection mirror for project id")
    parser.add_argument("--verify-mirror", metavar="PROJECT_ID", help="Build BLAKE3 Source/Hub verification report for project id")
    parser.add_argument("--docs-preview", metavar="PROJECT_ID", help="Build docs-only plan for project id")
    parser.add_argument("--docs-apply", metavar="PROJECT_ID", help="Apply docs-only mirror for project id")
    parser.add_argument("--safety-scan", metavar="PROJECT_ID", help="Scan a project root for secret and heavy-file candidates")
    parser.add_argument("--safety-root", choices=["source", "projection"], default="source", help="Root to scan for --safety-scan")
    parser.add_argument("--dry-run", action="store_true", help="For --mirror-apply, force dry-run")
    parser.add_argument("--apply", action="store_true", help="For --mirror-apply, explicitly perform real writes even if profile dry_run_default is true")
    parser.add_argument("--json", action="store_true", help="Print JSON result")
    args = parser.parse_args()

    if args.doctor:
        registry = load_project_registry()
        payload = {
            "project_root": str(ROOT),
            "config_dir": str(ROOT / "config"),
            "projects": [project.to_dict() for project in registry.projects],
            "active_project_id": registry.active_project_id,
            "storage": storage_layout_status(ROOT, registry.projects),
            "ok": True,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.storage_doctor:
        registry = load_project_registry()
        payload = storage_layout_status(ROOT, registry.projects)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.auth_doctor:
        from system_core.core.auth_doctor import run_auth_doctor
        payload = run_auth_doctor(ROOT)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.scan_projects:
        config_path = ROOT / "config" / "projects.json"
        payload = load_json(config_path, default={"active_project_id": "", "projects": []})
        hub_root = Path(args.hub_root).expanduser() if args.hub_root else ROOT.parent / "Hub Data"
        docs_root = Path(args.docs_root).expanduser() if args.docs_root else None
        entries = scan_project_folder(
            Path(args.scan_projects),
            hub_root,
            docs_root=docs_root,
            max_depth=max(0, args.scan_depth),
        )
        result = {
            "scan_root": str(Path(args.scan_projects).expanduser()),
            "hub_root": str(hub_root),
            "docs_root": str(docs_root or ""),
            "candidates": entries,
            "summary": {
                "candidates": len(entries),
                "imported": 0,
                "skipped": 0,
            },
        }
        if args.import_projects:
            updated, added, skipped = merge_project_import(payload, entries)
            save_json(config_path, updated)
            result["summary"].update({"imported": added, "skipped": skipped})
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.verify_mirror:
        registry = load_project_registry()
        project = registry.by_id(args.verify_mirror)
        result = verify_projection_mirror_from_project(project)
        report = write_report("mirror_verify", result, project_id=project.id)
        if args.json:
            print(json.dumps({"report": str(report), "result": result}, ensure_ascii=False, indent=2))
        else:
            print(f"Report: {report}")
            print(json.dumps(result.get("summary", {}), ensure_ascii=False, indent=2))
        return int(result.get("summary", {}).get("exit_code", 1))

    if args.safety_scan:
        registry = load_project_registry()
        project = registry.by_id(args.safety_scan)
        root = project.projection_path if args.safety_root == "projection" else project.source_path
        result = scan_safety(root)
        result["project_id"] = project.id
        result["root_role"] = args.safety_root
        report = write_report("safety_scan", result, project_id=project.id)
        if args.json:
            print(json.dumps({"report": str(report), "result": result}, ensure_ascii=False, indent=2))
        else:
            print(f"Report: {report}")
            print(json.dumps(result.get("summary", {}), ensure_ascii=False, indent=2))
        return 0

    docs_preview = args.docs_preview
    docs_apply = args.docs_apply
    if args.mirror_preview or args.mirror_apply or docs_preview or docs_apply:
        if args.dry_run and args.apply:
            parser.error("--dry-run and --apply are mutually exclusive")
        registry = load_project_registry()
        project_id = args.mirror_preview or args.mirror_apply or docs_preview or docs_apply
        project = registry.by_id(project_id)
        plan = plan_docs_view(ROOT, project) if (docs_preview or docs_apply) else plan_projection_from_project(project)
        if args.mirror_preview or docs_preview:
            result = plan
            report = write_report("docs_plan" if docs_preview else "projection_plan", result, project_id=project.id)
        else:
            profile_payload = plan.get("profile", {}) if isinstance(plan, dict) else {}
            profile_dry_default = bool(profile_payload.get("dry_run_default", True))
            effective_dry_run = bool(args.dry_run or (profile_dry_default and not args.apply))
            result = apply_projection_plan(plan, dry_run=effective_dry_run)
            result.setdefault("runtime", {})
            result["runtime"].update({
                "profile_dry_run_default": profile_dry_default,
                "cli_apply": bool(args.apply),
                "cli_dry_run": bool(args.dry_run),
                "effective_dry_run": effective_dry_run,
            })
            report = write_report("docs_apply" if docs_apply else "projection_apply", result, project_id=project.id)
        if args.json:
            print(json.dumps({"report": str(report), "result": result}, ensure_ascii=False, indent=2))
        else:
            print(f"Report: {report}")
            print(json.dumps(result.get("summary", {}), ensure_ascii=False, indent=2))
        return 0

    from system_core.ui_nicegui.app import run
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
