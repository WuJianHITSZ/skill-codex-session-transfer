---
name: codex-session-transfer
description: Transfer, clone, re-home, or repair Codex Desktop local session histories by editing ~/.codex transcript files, session indexes, and local SQLite thread metadata. Use when a session jsonl came from another device, when a thread should appear under a different local project, when Codex App sidebar visibility is wrong, or when a copied session must be made openable without damaging the source session. Also use when a session skill package must be installed onto a target Codex home with path localization and minimum-workset metadata fusion.
---

# Codex Session Transfer

## Overview

Use this skill to manage the full first-phase session migration lifecycle: package local sessions, install a session skill package into a target Codex Desktop environment, list migration transactions, and roll a migration back later if needed.

Prefer dry-run first. Treat the rollout transcript, `threads` row, `session_index` entry, and `thread_dynamic_tools` rows as one coherent set.

Read [package-format.md](references/package-format.md) before changing the package schema.

## Workflow

### 0. Use one skill for the whole lifecycle

Use this single skill for:

- `packup`
- `install`
- `list-transactions`
- `rollback`

Do not split packaging and transfer into separate primary skills.

### Packup

Use `packup` to export a first-phase session skill package from a local Codex environment.

The exporter collects:

- rollout `jsonl` files
- matching `threads` rows
- matching `session_index` rows
- matching `thread_dynamic_tools` rows
- all user-defined skills under `~/.codex/skills`, excluding `.system`
- required working-directory skeletons

Use working directory as the main selector in phase 1.

### Packup Output Contract

`packup` writes an uncompressed package directory by default. Do not assume an archive step exists unless the operator explicitly adds one later.

Every future package must include a root-level `INSTALL_REMOTE.md`. Treat that file as the primary handoff document for the Codex agent reading the package on its own machine.

That handoff document should be actionable, not just descriptive. It should tell that agent:

- how to locate its local user home
- how to locate its local `~/.codex`
- that `codex-session-transfer` is the required installer skill
- which command to run for install dry-run
- which command to run for install execute
- how path localization works
- how to verify the install afterward
- how to list transactions and roll back if needed

### 1. Inspect the target Codex home

Before writing anything, confirm:

- target `~/.codex`
- target `~/.codex/sessions`
- target `~/.codex/skills`
- target `state_5.sqlite`

If the target database is missing, initialize only the minimum tables required for first-phase install.

### 2. Read the package manifest

Use `scripts/install_session_skill_package.py` to load:

- `package_manifest.json`
- `metadata/threads.jsonl`
- `metadata/session_index.jsonl`
- `metadata/thread_dynamic_tools.jsonl`
- `skeleton/required-directories.json`

### 3. Localize paths

For Windows paths, preserve the suffix starting at `\\Documents\\` and replace the leading user-home prefix with the local home path on the machine performing the install.

If a path has no `\\Documents\\` segment, leave it unchanged unless the operator gives an explicit mapping.

### 4. Dry-run first

Run the installer without `--execute` first. Review:

- target rollout file paths
- target working directories
- skill copy targets
- thread count and dynamic tool count

### 5. Execute only after validation

When the dry-run looks correct, rerun with `--execute`.

The script copies:

- package skills into `~/.codex/skills`
- rollout transcripts into `~/.codex/sessions`
- thread metadata into `state_5.sqlite`
- sidebar index entries into `session_index.jsonl`
- empty working-directory skeletons into the target filesystem

The script also creates a transaction journal under:

```text
~/.codex/transfer-journal/<transaction-id>/
```

That directory stores:

- `manifest.json`
- `operations.jsonl`
- `backups/`

### 6. Restart Codex Desktop

After install, ask the user to restart the app and verify:

- sessions appear under localized projects
- imported threads open correctly
- follow-up work can resolve the localized working directory

## Agent Handoff Document

When maintaining this skill, keep `INSTALL_REMOTE.md` aligned with the actual installer behavior.

The agent-facing document should present this flow:

1. Confirm the package root on the current machine.
2. Find the local home directory and local `~/.codex`.
3. Ensure `skills/codex-session-transfer` from the package is installed into the local `~/.codex/skills/`.
4. Run `install` without `--execute`.
5. Inspect localized target paths, session count, skill count, and directory skeleton creation.
6. Run `install --execute`.
7. Restart Codex Desktop and validate imported sessions.
8. If needed, run `list-transactions` and `rollback`.

Write it for a second-person Codex agent audience, so the document can be fed directly to the target agent with minimal extra explanation.

## Rollback

Keep rollback inside this same skill. Natural triggers include:

- "Use $codex-session-transfer to roll back the last migration."
- "Use $codex-session-transfer to list rollback transactions."
- "Use $codex-session-transfer to roll back transaction `<id>`."

### Rollback workflow

1. List transactions if the target transaction is not known yet.
2. Prefer `--latest` for the most recent completed migration.
3. Run rollback in dry-run mode first.
4. If the rollback plan looks correct, rerun with `--execute`.

Rollback restores backed-up files and directories and removes objects that were newly created by the migration.

## Commands

Packup:

```text
python scripts/install_session_skill_package.py packup --codex-home <local-codex-home> --cwd-filter <project-root> --output-dir <package-dir>
```

Install dry-run:

```text
python scripts/install_session_skill_package.py install <package-root> --codex-home <your-local-codex-home> --remote-home <your-local-user-home>
```

Install execute:

```text
python scripts/install_session_skill_package.py install <package-root> --codex-home <your-local-codex-home> --remote-home <your-local-user-home> --execute
```

List transactions:

```text
python scripts/install_session_skill_package.py list-transactions --codex-home <your-local-codex-home>
```

Rollback dry-run for latest:

```text
python scripts/install_session_skill_package.py rollback --codex-home <your-local-codex-home> --latest
```

Rollback execute for latest:

```text
python scripts/install_session_skill_package.py rollback --codex-home <your-local-codex-home> --latest --execute
```

Rollback a specific transaction:

```text
python scripts/install_session_skill_package.py rollback --codex-home <your-local-codex-home> --transaction-id <transaction-id> --execute
```

## Safety Rules

- Always dry-run before execute.
- Keep source sessions untouched.
- Reuse original session ids unless they conflict locally.
- Do not claim phase-2 memory migration is complete in phase 1.
- Treat rollback as part of the same skill, not a separate workflow.
