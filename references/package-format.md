# Session Skill Package Format

## Goal

Represent the minimum working set needed to re-home Codex Desktop sessions and user-defined skills onto another machine.

## Root Layout

```text
session-skill-package/
  package_manifest.json
  README.md
  INSTALL_REMOTE.md
  metadata/
    threads.jsonl
    session_index.jsonl
    thread_dynamic_tools.jsonl
    path_localization.json
  sessions/
    ...copied rollout jsonl files...
  skills/
    ...user-defined skill directories...
  skeleton/
    required-directories.json
```

`packup` produces this as a plain directory tree by default. Compression is out of scope unless an operator adds a separate packaging step.

## Minimal Working Set

- `sessions/`
  Required rollout transcript files.
- `metadata/threads.jsonl`
  Required per-thread rows exported from `state_5.sqlite`.
- `metadata/session_index.jsonl`
  Required sidebar index entries.
- `metadata/thread_dynamic_tools.jsonl`
  Required when target threads depend on dynamic tools.
- `skills/`
  Required user-defined skills, including `codex-session-transfer`.
- `skeleton/required-directories.json`
  Directory tree to create on the target host so imported sessions have valid working directories.
- `INSTALL_REMOTE.md`
  The default agent handoff document. A Codex agent reading this file on its own machine should be able to carry out the first-phase install workflow with minimal extra guidance.

## Agent Handoff Requirements

`INSTALL_REMOTE.md` should explicitly instruct the Codex agent reading the package to:

- identify the package root it is operating on
- locate its local user home and local `~/.codex`
- install `skills/codex-session-transfer` from the package into its local skill directory if needed
- run `install` in dry-run mode first
- inspect localized `cwd` targets and rollout destinations
- rerun with `--execute` only after the dry-run looks correct
- restart Codex Desktop after install
- use `list-transactions` and `rollback` if recovery is required

## Deferred for Later Phases

- `logs_1.sqlite`
- `state_5.sqlite.logs`
- `state_5.sqlite.stage1_outputs`
- `.codex-global-state.json`

## Path Localization Rule

For Windows paths, first try to preserve the suffix starting at `\\Documents\\`.

Example:

- Source: `C:\\Users\\jian\\Documents\\R\\MSI_SRT_mPD_LL`
- Target user home: `C:\\Users\\jianw`
- Localized: `C:\\Users\\jianw\\Documents\\R\\MSI_SRT_mPD_LL`

If a path does not contain `\\Documents\\`, keep it unchanged unless the operator provides an explicit mapping.
