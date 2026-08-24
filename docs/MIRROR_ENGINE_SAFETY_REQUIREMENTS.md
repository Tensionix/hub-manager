# MIRROR engine safety requirements

This document freezes the Disk Auditor hardening lessons that must be carried into Audion Hub Manager.

## Source of truth

- Full Project is the only source of truth.
- Hub Projection is a derived, filtered mirror.
- MIRROR may delete and rebuild managed projection files.
- MIRROR must never modify the Full Project source directory.
- Source may still be a normal Git working tree for agents and IDEs. MIRROR must
  not care whether Source has `.git`; it should only read profile-allowed files.
- Hub Projection may also be a normal Git working tree and must protect `.git/**`
  from scan, delete and `.gitkeep` maintenance.

Separate from MIRROR, the Markdown Editor may read selected source files. It may
write only when the user explicitly presses Save for that selected file.
Automated MIRROR tests and GUI smoke checks must not modify Source.

## Apply semantics

### `dry_run_default`

Profiles may define:

```json
"dry_run_default": true
```

CLI must not ignore it. A real write must require explicit intent:

```text
--mirror-apply PROJECT_ID           -> dry-run if profile dry_run_default=true
--mirror-apply PROJECT_ID --apply   -> real apply
--mirror-apply PROJECT_ID --dry-run -> forced dry-run
```

### Mask/profile safety

A filtered profile must never silently become a full copy because no mask was selected.

Required profile fields:

```json
"require_include_filter": true,
"min_include_globs": 1
```

If the profile requires filters and `include_globs` is empty, planning must fail.

Even a future `"mirror_scope": "full"` profile must not be allowed to become an
unfiltered copy by accident. If `mirror=true` and both `include_globs` and
`small_include_globs` are empty, planning must fail unless the profile explicitly
sets:

```json
"allow_unfiltered_full": true
```

No shipped profile should set this flag.

### Phased mirror apply

Real apply must be phased:

```text
Phase 1: create allowed directories
Phase 2: copy/update files
Phase 3: touch mtimes
Phase 4: if copy/touch/errors/conflicts == clean -> delete projection-only files
Phase 5: delete obsolete empty dirs
Phase 6: ensure .gitkeep in preserved empty incoming dirs
```

Deletion must not happen before copy/update succeeds. If a copy/touch phase fails, deletion is skipped and the report must expose:

```json
"delete_phase_skipped": true
```

### Compare modes

Hub Manager keeps three semantics:

```text
quick  = size + mtime
safe   = size + mtime fast path; BLAKE3 only on same-size/different-mtime
strict = BLAKE3 for same-size files, even if mtime also matches
```

`safe` is fast and compatible with Disk Auditor behavior, but it intentionally does not catch the case:

```text
same size + same mtime + different content
```

Use `strict_blake3` for important checkpoints.

The code-level default compare mode is `metadata_then_blake3`, which aliases to
strict same-size hashing while preserving older configuration names. Shipped Hub
profiles should keep their explicit `strict_blake3` setting so checkpoint
mirrors catch same-size/same-mtime content drift.

Hash digests stored or reported by core code must be algorithm-tagged, for
example `blake3:<hex>` or `sha256:<hex>`. SHA-256 is a correctness fallback for
minimal test/portable environments, not a BLAKE3-compatible digest.

### Conflicts and exit code

Any real apply with errors or conflicts is not success:

```json
"exit_code": 1
```

Future two-way sync must return non-zero when conflicts exist.

### Mirror scope

Every profile must explicitly state scope:

```json
"mirror_scope": "filtered"
```

`filtered` means target is made to match source only for selected filters. Out-of-scope target files are ignored by scan/plan unless they are inside managed projection paths that the profile includes.

Future possible value:

```json
"mirror_scope": "full"
```

Do not use `full` for project Hub projections without a separate review.

### Timestamp uniqueness

Report and temp filenames must use microseconds:

```text
YYYYMMDD_HHMMSS_microseconds
```

This prevents overwrites from fast CLI/GUI automation.

### .gitkeep post-processing

After MIRROR, run `.gitkeep` maintenance over the projection root:

- create `.gitkeep` in every empty directory that belongs to the mirrored incoming structure;
- remove `.gitkeep` from folders that contain real files or real subdirectories;
- do not create `.gitkeep` in hidden technical junk directories;
- treat `.gitkeep` as generated projection metadata.

## Tests that must stay green

Minimum safety tests:

- `test_profile_requires_include_masks`
- `test_strict_mode_detects_same_size_same_mtime_different_content`
- `test_safe_mode_keeps_disk_auditor_fast_path_same_size_same_mtime`
- `test_delete_phase_is_skipped_when_copy_phase_fails`
- `test_projection_mirror_preserves_empty_service_dirs`
- `test_projection_preserves_empty_dirs_with_gitkeep`

## BLAKE3 Verification Scope

Mirror verification is Source <-> Hub Data only. Documentation app folders such
as Docs, Obsidian, LogSeq or a VS Code docs folder are not checksum targets:
they are readable projections/consumers, while Hub Data is the canonical
technical mirror. Verification manifests and reports must be written only to
manager logs such as `logs/<project_id>/`.

## Not implemented here

The following Disk Auditor hardening items belong to Disk Auditor itself or future Hub modules:

- two-way `sync2` conflict handling;
- custom checksum manifest self-exclusion;
- release-clean policy for placeholder configs;
- Windows batch cleanup rewrite around delayed expansion.

If these features are imported later, preserve these safety notes.
