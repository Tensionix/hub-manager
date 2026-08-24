# STORAGE_LAYOUT_DECISION — Manager, Hub Data and Docs separation

## Decision

Do **not** put everything into one giant documentation folder.

Audion Hub Manager should manage three separate layers:

```text
1. Audion_Hub_Manager        independent portable app / codebase
2. Audion_Hub_Data           Git-backed technical Hub / projections / mirrors
3. Audion_Docs                neutral Markdown/text docs folder / docs view / inbox
```

The layers can live under one parent folder, but they should remain conceptually separate.

## Why separate them

### Hub Manager is a tool

It is an independent portable Python/NiceGUI project. It can be versioned and mirrored like any other project, but it must not depend on the Hub that it manages.

### Hub Data is technical

Hub Data contains filtered project projections:

```text
projects/<project_id>/
  README_RU.md / README_EN.md
  TECH_SPEC_RU.md / TECH_SPEC_EN.md
  AGENTS_RU.md / AGENTS_EN.md
  docs/
  prompts/
  reports/
  system_core/
  config/
  launcher.cmd
  logs/.gitkeep
  output/.gitkeep
```

This is primarily for VS Code, Git, diff, commit, mirror, Codex and code reuse.

### Docs is a neutral folder

Docs should not scan thousands of source files and scripts. The docs layer should contain Markdown-oriented material, indexes, project docs views, daily/inbox notes and links.

Docs can be opened or synced by whichever tool the user prefers: VS Code, a file manager, Obsidian, LogSeq, Syncthing, Git, a cloud drive, or nothing at all. Hub Data remains Git-backed and does not need to be synced to the phone.

## Recommended physical layout

```text
S:/Audion_System/
  00_Manager/
    Audion_Hub_Manager/

  10_Hub_Data/
    Audion_Hub/
      projects/
      manifests/
      indexes/
      bundles/
      .git/

  20_Docs/
    Audion_Docs/
      00_Inbox/
      Projects/
      30_Prompts_View/
      90_Indexes/
      .obsidian/        optional app metadata, only when the user wants it
```

VS Code can open all layers together through a `.code-workspace` file.
The current Storage pane can show the configured roots, run a layout check and
generate/open the workspace helper.

The Project dropdown is a selector for records in `config/projects.json`, not a
second Source picker. When one Source container holds many real projects, use
`SOURCE ACTIONS -> Rebuild dropdown` to discover nested project roots and merge
them into the registry. The active dropdown entry is then mirrored, scanned,
verified and committed as one project.

`Clean projects.json` is a maintenance action for the registry only: it removes
records with missing source paths and duplicate ids/source paths. It must never
delete Source, Hub Data or Docs folders.

## Project source of truth

```text
Full Project = source of truth
Hub Data     = filtered technical mirror
Docs         = neutral human-readable view, not canonical project source
```

Project documentation belongs in the full project first. If it is useful in Docs, it is copied or indexed from the project/Hub projection.

## Git placement

Git should stay transparent. Use normal visible `.git` directories that live
with the working tree they describe.

Recommended model:

```text
Full Project Source/
  .git/              optional, for agents, VS Code and full project work
  runtime/
  wheelhouse/
  system_core/
  docs/

Hub Data/<project>/
  .git/              reference mirror history for the filtered projection
  system_core/
  docs/
```

Avoid sidecar Git directories for normal Hub Manager workflows. They make
ownership unclear after project moves or rebuilds and reduce transparency for
agents. The price of a normal `.git` in Hub is acceptable because MIRROR protects
`.git/**`, and release cleanup should be run against release/source trees, not
against Hub Data reference mirrors.

The Source tree may contain dependencies and runtime payloads while still using
Git, as long as Hub Manager-created stage/commit flows obey the active Hub
projection profile. In other words, both Source Git and Hub Git should commit the
same curated pathset when Hub Manager is doing the committing.

## Docs view

The Docs view can receive a docs-only projection for the Docs layer:

```text
Full Project / Hub Projection
  -> allowed Markdown/docs/assets only
  -> Audion_Docs/Projects/<project_id>/
```

This keeps the Docs layer useful without making it the canonical project store.

Allowed docs-view material:

```text
*.md
*.txt
small images used by docs
README / TECH_SPEC / AGENTS / CHANGELOG / audit reports / prompts
```

Excluded from Docs view:

```text
*.py, *.ps1, *.cmd, *.json, runtime, wheelhouse, output, logs, backup, node_modules
```

Exception: specific code snippets can be exported into Markdown code capsules later, but these are generated/copy-reviewed artifacts, not the full codebase.

## Editing policy

Default policy:

```text
Edit project docs in Full Project / VS Code.
MIRROR updates Hub Data.
Docs projection updates Docs view.
```

Hub Manager now also provides a lightweight Markdown Editor pane for selected
Markdown/text files. It is an explicit editor, not an automatic sync engine:

```text
Open/load selected file -> edit -> explicit Save
```

MIRROR and background refresh operations remain read-only with respect to Full
Project Source.

Mobile Docs edits should go into `00_Inbox/` unless a future explicit **Sync Docs Back** workflow is implemented with diff review.

This prevents two competing documentation sources.

## One parent, not one monolith

It is acceptable to keep everything under one root folder for convenience. It is not acceptable to blur roles.

```text
Good:
  Audion_System contains Manager + Hub Data + Docs as siblings.

Risky:
  One giant Docs folder contains all code projections, scripts, generated files and notes.
```

## Git repositories

Recommended:

```text
Audion_Hub_Manager   own repo
Audion_Hub_Data      own repo with GitHub/GitLab/local mirrors
Audion_Docs          optional own repo OR external sync only
Full Projects        own repos where appropriate
```

This prevents recursion and keeps the tool, the projection database and the human-readable docs layer independently recoverable.

Hub Data commits should be made from the Hub projection root, not from Full
Project Source. The commit pathset must match the active Hub projection profile:
same allowed extensions/masks as MIRROR, plus marker files such as `.gitkeep`.
Do not use broad `git add .` commands that can collect generated binaries,
PDFs, logs or runtime payloads outside the Hub allowlist.

When committing Source through Hub Manager, use the same rule: no broad
`git add .`; stage only paths accepted by the active Hub projection profile.
