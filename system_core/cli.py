"""The console command of Audion Hub Manager: hub_cli.cmd.

Hub Manager's own operations - the registry, the mirror, the checks, the batches, the lab, Forgejo -
run here, and the window runs them through this command and nothing else. Git itself the window
calls directly, because the command a button runs is the lesson; the table of those commands is
`canon`.

  hub_cli.cmd version
  hub_cli.cmd canon [--docs]
  hub_cli.cmd projects list | active ID | set ID --source P --mirror P --docs P --profile X --branch B
  hub_cli.cmd projects scan FOLDER [--import] [--hub-root P] [--docs-root P] [--depth N] [--dry-run]
  hub_cli.cmd projects remove ID [--dry-run]
  hub_cli.cmd projects clean [--dry-run]
  hub_cli.cmd profile ID
  hub_cli.cmd check-paths ID --layer source|mirror PATH... | --stdin
  hub_cli.cmd mirror plan|apply|verify ID [--apply | --dry-run]
  hub_cli.cmd docs plan|apply ID
  hub_cli.cmd safety ID [--layer source|mirror]
  hub_cli.cmd storage
  hub_cli.cmd blake3
  hub_cli.cmd tools
  hub_cli.cmd auth [--repo P] [--no-mirrors]
  hub_cli.cmd batch status|mirror-plan|safety|verify
  hub_cli.cmd workspace [ID]
  hub_cli.cmd lab create [--dir P] [--replace] [--register]
  hub_cli.cmd next-version --repo P [--series S] [--bump patch|minor|major]
  hub_cli.cmd remote url --platform X --owner O --repo R [--type ssh|https] [--server S] [--ssh-port N]
  hub_cli.cmd remote list | save --name N --url U [--platform X] [--repo R] [--disabled]
  hub_cli.cmd forgejo doctor [--offline] | check --url U | whoami --url U [--login L] | repos --url U [--login L]
  hub_cli.cmd forgejo sign-in --url U [--login L] [--ssh-port N] [--type ssh|https]   (the token comes on stdin)
  hub_cli.cmd forgejo sign-out --url U [--login L]
  hub_cli.cmd forgejo create --url U --name N [--login L] [--public] [--description D] [--branch B]

Every command prints one JSON document. Exit codes: 0 done; 1 done with a bad result (the mirror differs,
a check failed) or failed; 2 a wrong call (unknown project, missing argument) - nothing was changed.
Reports of the mirror, the checks and the batches are written into logs\\<project> as before.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from system_core.core import git_canon, hub_ops  # noqa: E402
from system_core.core.json_utils import load_json, save_json  # noqa: E402
from system_core.core.project_registry import load_project_registry  # noqa: E402

EXIT_OK, EXIT_BAD, EXIT_USAGE = 0, 1, 2


class Usage(Exception):
    """A wrong call: reported with exit 2, nothing changed."""


def out(payload: dict[str, Any], code: int = EXIT_OK) -> int:
    payload = {"ok": code == EXIT_OK, **payload}
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n")
    sys.stdout.flush()
    return code


def project(project_id: str):  # noqa: ANN201
    try:
        return load_project_registry().by_id(project_id)
    except KeyError:
        raise Usage(f"no project {project_id!r} in the registry") from None


def report(kind: str, payload: dict[str, Any], project_id: str) -> str:
    from system_core.core.projection_engine import write_report

    return str(write_report(kind, payload, project_id=project_id))


# --- commands ---

def cmd_version(_args) -> int:  # noqa: ANN001
    version = load_json(ROOT / "config" / "version.json", default={}).get("version", "")
    return out({"version": version, "root": str(ROOT)})


def cmd_canon(args) -> int:  # noqa: ANN001
    if args.docs:
        from system_core.core.canon_docs import write_docs

        return out(write_docs(ROOT))
    return out({"canon": git_canon.as_json()})


def cmd_projects(args) -> int:  # noqa: ANN001
    if args.action == "list":
        return out(hub_ops.list_projects(with_repo_state=not args.fast))
    if args.action == "active":
        try:
            return out(hub_ops.set_active_project(args.id))
        except KeyError as exc:
            raise Usage(exc.args[0] if exc.args else str(exc)) from None
    if args.action == "set":
        try:
            return out(hub_ops.set_project_fields(args.id, title=args.title, source_path=args.source, projection_path=args.mirror,
                                                  docs_path=args.docs, profile=args.profile, default_branch=args.branch,
                                                  vscode_workspace=args.workspace, notes=args.notes))
        except KeyError as exc:
            raise Usage(exc.args[0] if exc.args else str(exc)) from None
    if args.action == "remove":
        try:
            result = hub_ops.remove_project(args.id, dry_run=args.dry_run)
        except KeyError as exc:
            raise Usage(exc.args[0] if exc.args else str(exc)) from None
        result["report"] = report("projects_config_remove", result, "registry")
        return out(result)
    if args.action == "clean":
        result = hub_ops.clean_registry(dry_run=args.dry_run)
        result["report"] = report("projects_config_clean", result, "registry")
        return out(result)
    if args.action in ("export", "import"):
        if not args.id:
            raise Usage(f"projects {args.action}: name the file")
        try:
            if args.action == "export":
                return out(hub_ops.export_registry(Path(args.id)))
            return out(hub_ops.import_registry(Path(args.id), replace=args.replace, dry_run=args.dry_run))
        except ValueError as exc:
            raise Usage(str(exc)) from None
    if args.action == "scan":
        from system_core.core.project_importer import merge_project_import, scan_project_folder

        folder = Path(args.id).expanduser()
        if not folder.is_dir():
            raise Usage(f"not a folder: {folder}")
        hub_root = Path(args.hub_root).expanduser() if args.hub_root else ROOT.parent / "Hub Data"
        docs_root = Path(args.docs_root).expanduser() if args.docs_root else None
        entries = scan_project_folder(folder, hub_root, docs_root=docs_root, max_depth=max(0, args.depth))
        entries = [{**entry, **{key: hub_ops.config_path_value(Path(entry[key])) for key in ("source_path", "projection_path", "docs_path")
                                if str(entry.get(key, "")).strip()}} for entry in entries]
        result: dict[str, Any] = {"scan_root": str(folder), "hub_root": str(hub_root), "docs_root": str(docs_root or ""),
                                  "candidates": entries, "summary": {"candidates": len(entries), "imported": 0, "skipped": 0}}
        if args.do_import:
            path = hub_ops.projects_config_path()
            updated, added, skipped = merge_project_import(load_json(path, default={"active_project_id": "", "projects": []}), entries)
            if not args.dry_run:
                save_json(path, updated)
            result["summary"].update({"imported": added, "skipped": skipped})
            result["dry_run"] = bool(args.dry_run)
        result["report"] = report("project_scan", result, "registry")
        return out(result)
    raise Usage(f"unknown action: {args.action}")


def cmd_profile(args) -> int:  # noqa: ANN001
    return out({"profile": hub_ops.describe_profile(project(args.id).profile)})


def cmd_check_paths(args) -> int:  # noqa: ANN001
    entry = project(args.id)
    root = hub_ops.layer_path(entry, args.layer)
    if root is None or not root.is_dir():
        raise Usage(f"the {args.layer} layer of {args.id} is not a folder: {root}")
    # Thousands of paths do not fit one command line: --stdin reads them a line each.
    paths = [*args.paths, *(line for line in sys.stdin.read().splitlines() if line.strip())] if args.stdin else args.paths
    if not paths:
        raise Usage("check-paths: no paths - give them as arguments or a line each with --stdin")
    result = hub_ops.check_paths(root, entry.profile, paths)
    return out(result, EXIT_OK if not result["blocked"] else EXIT_BAD)


def cmd_mirror(args) -> int:  # noqa: ANN001
    from system_core.core.projection_engine import apply_projection_plan, plan_projection_from_project, verify_projection_mirror_from_project

    entry = project(args.id)
    if args.action == "verify":
        result = verify_projection_mirror_from_project(entry)
        code = int(result.get("summary", {}).get("exit_code", 1))
        return out({"report": report("mirror_verify", result, entry.id), "result": result}, EXIT_OK if code == 0 else EXIT_BAD)
    plan = plan_projection_from_project(entry)
    if args.action == "plan":
        return out({"report": report("projection_plan", plan, entry.id), "result": plan})
    if args.dry_run and args.apply:
        raise Usage("--dry-run and --apply together")
    profile_dry = bool(plan.get("profile", {}).get("dry_run_default", True))
    dry_run = bool(args.dry_run or (profile_dry and not args.apply))
    result = apply_projection_plan(plan, dry_run=dry_run)
    result.setdefault("runtime", {}).update({"profile_dry_run_default": profile_dry, "effective_dry_run": dry_run})
    errors = int(result.get("summary", {}).get("errors", 0) or 0)
    return out({"report": report("projection_apply", result, entry.id), "result": result}, EXIT_OK if not errors else EXIT_BAD)


def cmd_docs(args) -> int:  # noqa: ANN001
    from system_core.core.docs_view import plan_docs_view
    from system_core.core.projection_engine import apply_projection_plan

    entry = project(args.id)
    plan = plan_docs_view(ROOT, entry)
    if args.action == "plan":
        return out({"report": report("docs_plan", plan, entry.id), "result": plan})
    result = apply_projection_plan(plan, dry_run=bool(args.dry_run))
    # As the mirror: a copy that failed is no success.
    code = EXIT_OK if int(result.get("summary", {}).get("exit_code", 0) or 0) == 0 else EXIT_BAD
    return out({"report": report("docs_apply", result, entry.id), "result": result}, code)


def cmd_safety(args) -> int:  # noqa: ANN001
    from system_core.core.safety import scan_safety

    entry = project(args.id)
    root = hub_ops.layer_path(entry, args.layer)
    if root is None or not root.is_dir():
        raise Usage(f"the {args.layer} layer of {args.id} is not a folder: {root}")
    result = scan_safety(root)
    result.update({"project_id": entry.id, "root_role": args.layer})
    summary = result.get("summary", {})
    # A blocker, or a file that could not be read - either way the layer is not known to be clean.
    bad = int(summary.get("blockers", 0) or 0) or int(summary.get("errors", 0) or 0)
    return out({"report": report("safety_scan", result, entry.id), "result": result}, EXIT_OK if not bad else EXIT_BAD)


def cmd_storage(args) -> int:  # noqa: ANN001
    from system_core.core.storage_layout import set_projects_root, storage_layout_status

    if args.projects_root is not None or args.reset_projects_root:
        try:
            set_projects_root(ROOT, None if args.reset_projects_root else args.projects_root)
        except ValueError as exc:
            raise Usage(str(exc)) from exc
        # The root is written - what was asked is done; the layout of its projects is told in result.ok and off_layout.
        return out({"result": storage_layout_status(ROOT, load_project_registry().projects)}, EXIT_OK)
    result = storage_layout_status(ROOT, load_project_registry().projects)
    return out({"result": result}, EXIT_OK if result.get("ok") else EXIT_BAD)


def cmd_blake3(_args) -> int:  # noqa: ANN001
    result = hub_ops.blake3_probe()
    return out({"result": result}, EXIT_OK if result["ok"] else EXIT_BAD)


def cmd_tools(_args) -> int:  # noqa: ANN001
    return out(hub_ops.machine_tools())


def cmd_auth(args) -> int:  # noqa: ANN001
    from system_core.core.auth_doctor import run_auth_doctor

    repo = Path(args.repo).expanduser() if args.repo else None
    return out({"result": run_auth_doctor(ROOT, repo_root=repo, check_mirrors=not args.no_mirrors)})


def cmd_batch(args) -> int:  # noqa: ANN001
    run = {"status": hub_ops.batch_status, "mirror-plan": hub_ops.batch_mirror_plan,
           "safety": hub_ops.batch_safety, "verify": hub_ops.batch_verify}[args.action]
    result = run()
    result["report"] = report(f"batch_{args.action.replace('-', '_')}", result, "registry")
    # Code 1 as each command alone would give it: any error; for secrets a blocker; for the check of copies a difference.
    s = result["summary"]
    bad = s.get("errors") or (args.action == "safety" and s.get("blockers")) \
        or (args.action == "verify" and (s.get("changed") or s.get("missing") or s.get("extra")))
    return out(result, EXIT_BAD if bad else EXIT_OK)


def cmd_workspace(args) -> int:  # noqa: ANN001
    if args.id:
        project(args.id)
    return out(hub_ops.write_workspace(args.id))


def cmd_lab(args) -> int:  # noqa: ANN001
    from system_core.core.lab import build_lab, default_lab_dir

    target = Path(args.dir).expanduser() if args.dir else default_lab_dir(ROOT)
    if target.exists():
        if not args.replace:
            raise Usage(f"{target} exists: --replace sends it to the Recycle Bin first")
        hub_ops.send_to_recycle_bin(target)
    result = build_lab(target)
    if args.register:
        result["registry"] = hub_ops.register_lab(target)
    return out(result)


def cmd_next_version(args) -> int:  # noqa: ANN001
    from system_core.core.git_engine import build_version_tag, next_version_for_series

    version, command = next_version_for_series(Path(args.repo).expanduser(), args.series, args.bump)
    return out({"series": args.series, "version": version, "tag": build_version_tag(args.series, version),
                "command": command.joined_command()})


def cmd_remote(args) -> int:  # noqa: ANN001
    if args.action == "url":
        try:
            url = hub_ops.remote_url(args.platform, args.owner, args.repo, url_type=args.type, server=args.server, ssh_port=args.ssh_port)
        except ValueError as exc:
            raise Usage(str(exc)) from None
        return out({"url": url})
    if args.action == "list":
        return out(hub_ops.list_saved_remotes())
    try:
        return out(hub_ops.save_remote(args.name, args.url, platform=args.platform, repo=args.repo, enabled=not args.disabled))
    except ValueError as exc:
        raise Usage(str(exc)) from None


def _forgejo_host(args):  # noqa: ANN001, ANN202
    from system_core.core import forgejo_api, forgejo_service

    try:
        base = forgejo_api.normalize_base_url(args.url)
    except ValueError as exc:
        raise Usage(str(exc)) from None
    from urllib.parse import urlparse

    hostname = urlparse(base).hostname or "forgejo"
    known = next((item for item in forgejo_service.load_hosts(ROOT / "config") if item.base_url == base), None)
    return forgejo_api.ForgejoHost(
        id=known.id if known else hostname, title=known.title if known else f"Forgejo {hostname}", url=base,
        ssh_port=int(getattr(args, "ssh_port", 0) or (known.ssh_port if known else 22)),
        ssh_user=known.ssh_user if known else "git",
        preferred_url_type=(getattr(args, "type", "") or (known.preferred_url_type if known else "https")),
        login=(getattr(args, "login", "") or (known.login if known else "")))


def cmd_forgejo(args) -> int:  # noqa: ANN001
    from system_core.core import forgejo_api, forgejo_service

    if args.action == "doctor":
        return out({"result": forgejo_service.forgejo_doctor(ROOT / "config", check_server=not args.offline)})
    host = _forgejo_host(args)
    if args.action == "check":
        result = forgejo_api.server_version(host.base_url)
        return out({"server": host.base_url, "api": result.to_dict(), "version": (result.data or {}).get("version", "") if isinstance(result.data, dict) else ""},
                   EXIT_OK if result.ok else EXIT_BAD)
    if args.action == "sign-in":
        token = sys.stdin.readline().strip()
        if not token:
            raise Usage("the token is read from stdin, and stdin was empty")
        outcome = forgejo_service.sign_in(ROOT / "config", host, args.login, token)
        return out({"server": host.base_url, "login": outcome.login, "message": outcome.message_key, "detail": outcome.detail,
                    "user": outcome.user or {}}, EXIT_OK if outcome.ok else EXIT_BAD)
    if args.action == "sign-out":
        result = forgejo_service.sign_out(host, args.login)
        return out({"server": host.base_url, "credential": result.to_dict()}, EXIT_OK if result.ok else EXIT_BAD)
    if args.action in {"whoami", "repos", "create"}:
        if args.action == "whoami":
            api, credential = forgejo_service.whoami(host, args.login)
        elif args.action == "repos":
            api, credential = forgejo_service.list_repos(host, args.login)
        else:
            api, credential = forgejo_service.create_repo(host, args.name, login=args.login, private=not args.public,
                                                          description=args.description, default_branch=args.branch)
        if api is None:
            return out({"server": host.base_url, "message": "forgejo_token_missing",
                        "credential": credential.to_dict() if credential else {}}, EXIT_BAD)
        data: Any = api.data
        if args.action == "whoami" and api.ok:
            data = forgejo_api.user_summary(api.data)
        elif args.action == "repos" and api.ok and isinstance(api.data, list):
            data = [forgejo_api.repo_summary(item) for item in api.data if isinstance(item, dict)]
        elif args.action == "create" and api.ok and isinstance(api.data, dict):
            data = forgejo_api.repo_summary(api.data)
        return out({"server": host.base_url, "api": api.to_dict(), "data": data}, EXIT_OK if api.ok else EXIT_BAD)
    raise Usage(f"unknown action: {args.action}")


class Parser(argparse.ArgumentParser):
    """argparse that does not print its usage to stderr and leave: a wrong call - a missing id, an unknown command - is
    answered with one JSON like every other (kind "usage", code 2). The subcommands are made of the same class."""

    def error(self, message: str):  # noqa: ANN201
        raise Usage(f"{self.prog}: {message}")


def parser() -> argparse.ArgumentParser:
    p = Parser(prog="hub_cli", description="Audion Hub Manager: the console command")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("version").set_defaults(run=cmd_version)
    s = sub.add_parser("canon")
    s.add_argument("--docs", action="store_true", help="write the canon tables of docs\\*.md and SKILL.md")
    s.set_defaults(run=cmd_canon)

    s = sub.add_parser("projects")
    s.add_argument("action", choices=["list", "active", "set", "scan", "remove", "clean", "export", "import"])
    s.add_argument("id", nargs="?", default="", help="the project; for scan the folder, for export and import the file")
    s.add_argument("--replace", action="store_true", help="import: the file's list instead of the registry's")
    s.add_argument("--fast", action="store_true", help="list: skip the repository state of each layer")
    for flag in ("title", "source", "mirror", "docs", "profile", "branch", "workspace", "notes", "hub-root", "docs-root"):
        s.add_argument(f"--{flag}", default=None)
    s.add_argument("--import", dest="do_import", action="store_true")
    s.add_argument("--depth", type=int, default=3)
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(run=cmd_projects)

    s = sub.add_parser("profile")
    s.add_argument("id")
    s.set_defaults(run=cmd_profile)

    s = sub.add_parser("check-paths")
    s.add_argument("id")
    s.add_argument("--layer", choices=["source", "mirror"], default="source")
    s.add_argument("--stdin", action="store_true", help="read the paths from the input, a line each")
    s.add_argument("paths", nargs="*")
    s.set_defaults(run=cmd_check_paths)

    s = sub.add_parser("mirror")
    s.add_argument("action", choices=["plan", "apply", "verify"])
    s.add_argument("id")
    s.add_argument("--apply", action="store_true")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(run=cmd_mirror)

    s = sub.add_parser("docs")
    s.add_argument("action", choices=["plan", "apply"])
    s.add_argument("id")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(run=cmd_docs)

    s = sub.add_parser("safety")
    s.add_argument("id")
    s.add_argument("--layer", choices=["source", "mirror"], default="source")
    s.set_defaults(run=cmd_safety)

    s = sub.add_parser("storage")
    root_choice = s.add_mutually_exclusive_group()
    root_choice.add_argument("--projects-root", metavar="FOLDER", help="make FOLDER the root of the live projects of this machine")
    root_choice.add_argument("--reset-projects-root", action="store_true", help="give the shipped root back (the folder beside the program)")
    s.set_defaults(run=cmd_storage)
    sub.add_parser("blake3").set_defaults(run=cmd_blake3)
    sub.add_parser("tools").set_defaults(run=cmd_tools)

    s = sub.add_parser("auth")
    s.add_argument("--repo", default="")
    s.add_argument("--no-mirrors", action="store_true")
    s.set_defaults(run=cmd_auth)

    s = sub.add_parser("batch")
    s.add_argument("action", choices=["status", "mirror-plan", "safety", "verify"])
    s.set_defaults(run=cmd_batch)

    s = sub.add_parser("workspace")
    s.add_argument("id", nargs="?", default="")
    s.set_defaults(run=cmd_workspace)

    s = sub.add_parser("lab")
    s.add_argument("action", choices=["create"])
    s.add_argument("--dir", default="")
    s.add_argument("--replace", action="store_true")
    s.add_argument("--register", action="store_true", help="put the ten repositories into the registry")
    s.set_defaults(run=cmd_lab)

    s = sub.add_parser("next-version")
    s.add_argument("--repo", required=True)
    s.add_argument("--series", default="projection")
    s.add_argument("--bump", choices=["patch", "minor", "major"], default="patch")
    s.set_defaults(run=cmd_next_version)

    s = sub.add_parser("remote")
    s.add_argument("action", choices=["url", "list", "save"])
    s.add_argument("--platform", default="github")
    s.add_argument("--owner", default="")
    s.add_argument("--repo", default="")
    s.add_argument("--type", default="ssh")
    s.add_argument("--server", default="")
    s.add_argument("--ssh-port", type=int, default=22)
    s.add_argument("--name", default="")
    s.add_argument("--url", default="")
    s.add_argument("--disabled", action="store_true")
    s.set_defaults(run=cmd_remote)

    s = sub.add_parser("forgejo")
    s.add_argument("action", choices=["doctor", "check", "sign-in", "sign-out", "whoami", "repos", "create"])
    s.add_argument("--url", default="")
    s.add_argument("--login", default="")
    s.add_argument("--ssh-port", type=int, default=0)
    s.add_argument("--type", default="")
    s.add_argument("--name", default="")
    s.add_argument("--public", action="store_true")
    s.add_argument("--description", default="")
    s.add_argument("--branch", default="main")
    s.add_argument("--offline", action="store_true")
    s.set_defaults(run=cmd_forgejo)
    return p


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    try:
        args = parser().parse_args(argv)
    except Usage as exc:
        return out({"error": str(exc), "kind": "usage"}, EXIT_USAGE)
    except SystemExit as exc:  # --help: its text is the answer
        return EXIT_USAGE if exc.code else EXIT_OK
    try:
        return args.run(args)
    except Usage as exc:
        return out({"error": str(exc), "kind": "usage"}, EXIT_USAGE)
    except Exception as exc:  # the caller reads JSON, not a traceback
        return out({"error": f"{exc.__class__.__name__}: {exc}", "kind": "failed"}, EXIT_BAD)


if __name__ == "__main__":
    raise SystemExit(main())
