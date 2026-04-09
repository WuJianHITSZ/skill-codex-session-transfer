# codex-session-transfer

`codex-session-transfer` is a Codex skill for packaging, installing, re-homing, and rolling back local Codex Desktop session migrations.

This repository-stage copy is prepared for public GitHub publication. The installable skill content remains at the repository root so the folder can still be copied directly into `~/.codex/skills/codex-session-transfer/`.

## What This Skill Does

- Packages the first-phase minimum working set for selected Codex sessions
- Installs a session skill package onto another Codex Desktop environment
- Localizes working-directory paths for the destination machine
- Records transaction logs and backups for safe rollback
- Lists migration transactions and rolls them back when needed

## Repository Layout

```text
codex-session-transfer/
  SKILL.md
  agents/
    openai.yaml
  references/
    package-format.md
  scripts/
    install_session_skill_package.py
  README.md
  PUBLISHING.md
  LICENSE-DECISION.md
  .gitignore
```

## Installation Into Codex

Copy this directory into your local Codex skills directory as:

```text
~/.codex/skills/codex-session-transfer/
```

The required skill entrypoint is [SKILL.md](./SKILL.md).

## Primary Workflow

The skill exposes one lifecycle with four actions:

- `packup`
- `install`
- `list-transactions`
- `rollback`

The main implementation lives in [scripts/install_session_skill_package.py](./scripts/install_session_skill_package.py).

## Scope

This version focuses on the first-phase minimum working set:

- rollout `jsonl` files
- `threads`
- `session_index`
- `thread_dynamic_tools`
- user-defined skills
- required empty directory skeletons

It intentionally does not yet migrate:

- `logs_1.sqlite`
- `state_5.sqlite.logs`
- `state_5.sqlite.stage1_outputs`
- `.codex-global-state.json`

## Publishing Notes

This copy is prepared for GitHub publication, but one important repository decision is still intentionally left to the maintainer: choose a public license before publishing. See [LICENSE-DECISION.md](./LICENSE-DECISION.md).
