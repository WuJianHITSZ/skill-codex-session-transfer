#!/usr/bin/env python3
"""Package, install, inspect, and roll back a session skill package.

Default workflow:
  1. packup
  2. install (dry-run first, then --execute)
  3. list-transactions
  4. rollback --latest or rollback --transaction-id <id>
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_cwd(path: str) -> str:
    if path.startswith("\\\\?\\"):
        return path[4:]
    return path


def localize_windows_documents_path(path: str, remote_home: str) -> str:
    normalized = normalize_cwd(path)
    marker = "\\Documents\\"
    idx = normalized.find(marker)
    if idx == -1:
        return normalized
    return str(Path(remote_home) / normalized[idx + 1 :].replace("\\", "/"))


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    path.write_text(text, encoding="utf-8")


def load_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_manifest(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_index(path: Path) -> dict[str, dict]:
    rows = {}
    if not path.exists():
        return rows
    for row in read_jsonl(path):
        rows[row["id"]] = row
    return rows


def iso_utc_from_epoch(seconds: int) -> str:
    return datetime.fromtimestamp(seconds, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def target_rollout_path(codex_home: Path, original_rollout_path: str) -> Path:
    normalized = original_rollout_path.replace("/", "\\")
    marker = "\\sessions\\"
    idx = normalized.lower().find(marker)
    if idx == -1:
        return codex_home / "sessions" / "imported" / Path(original_rollout_path).name
    suffix = normalized[idx + len(marker) :].replace("\\", "/")
    return codex_home / "sessions" / Path(suffix)


def merge_tree(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            merge_tree(item, target)
        else:
            shutil.copy2(item, target)


def replace_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def update_rollout_text(text: str, target_cwd: str) -> str:
    lines = text.splitlines()
    updated = []
    for line in lines:
        obj = json.loads(line)
        payload = obj.get("payload")
        if obj.get("type") == "session_meta" and isinstance(payload, dict):
            payload["cwd"] = target_cwd
        if obj.get("type") == "turn_context" and isinstance(payload, dict):
            payload["cwd"] = target_cwd
            sandbox = payload.get("sandbox_policy")
            if isinstance(sandbox, dict):
                sandbox["writable_roots"] = [target_cwd]
        if (
            obj.get("type") == "response_item"
            and isinstance(payload, dict)
            and payload.get("type") == "message"
            and payload.get("role") == "user"
        ):
            for item in payload.get("content", []):
                text_value = item.get("text")
                if isinstance(text_value, str) and "<cwd>" in text_value and "</cwd>" in text_value:
                    start = text_value.find("<cwd>") + len("<cwd>")
                    end = text_value.find("</cwd>")
                    if end > start:
                        item["text"] = text_value[:start] + target_cwd + text_value[end:]
        updated.append(json.dumps(obj, ensure_ascii=False))
    return "\n".join(updated) + "\n"


def ensure_threads_schema(con: sqlite3.Connection) -> None:
    cur = con.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS threads (
            id TEXT PRIMARY KEY,
            rollout_path TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            source TEXT NOT NULL,
            model_provider TEXT NOT NULL,
            cwd TEXT NOT NULL,
            title TEXT NOT NULL,
            sandbox_policy TEXT NOT NULL,
            approval_mode TEXT NOT NULL,
            tokens_used INTEGER NOT NULL DEFAULT 0,
            has_user_event INTEGER NOT NULL DEFAULT 0,
            archived INTEGER NOT NULL DEFAULT 0,
            archived_at INTEGER,
            git_sha TEXT,
            git_branch TEXT,
            git_origin_url TEXT,
            cli_version TEXT NOT NULL DEFAULT '',
            first_user_message TEXT NOT NULL DEFAULT '',
            agent_nickname TEXT,
            agent_role TEXT,
            memory_mode TEXT NOT NULL DEFAULT 'enabled',
            model TEXT,
            reasoning_effort TEXT,
            agent_path TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS thread_dynamic_tools (
            thread_id TEXT NOT NULL,
            position INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            input_schema TEXT NOT NULL,
            defer_loading INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (thread_id, position)
        )
        """
    )
    con.commit()


def build_packup(output_dir: Path, codex_home: Path, cwd_filter: str) -> dict:
    cwd_filter = normalize_cwd(cwd_filter)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    (output_dir / "metadata").mkdir(parents=True, exist_ok=True)
    (output_dir / "sessions").mkdir(parents=True, exist_ok=True)
    (output_dir / "skills").mkdir(parents=True, exist_ok=True)
    (output_dir / "skeleton").mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(codex_home / "state_5.sqlite")
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("SELECT * FROM threads")
    threads = [dict(row) for row in cur.fetchall() if normalize_cwd(row["cwd"]) == cwd_filter]
    thread_ids = {row["id"] for row in threads}
    cur.execute("SELECT * FROM thread_dynamic_tools")
    tool_rows = [dict(row) for row in cur.fetchall() if row["thread_id"] in thread_ids]
    con.close()

    index = read_index(codex_home / "session_index.jsonl")
    index_rows = []
    for row in threads:
        existing = index.get(row["id"])
        if existing is not None:
            index_rows.append(existing)
        else:
            index_rows.append(
                {
                    "id": row["id"],
                    "thread_name": row["title"],
                    "updated_at": iso_utc_from_epoch(int(row["updated_at"])),
                }
            )

    for row in threads:
        src = Path(row["rollout_path"])
        shutil.copy2(src, output_dir / "sessions" / src.name)

    for skill_dir in sorted((codex_home / "skills").iterdir()):
        if skill_dir.name.startswith(".") or not skill_dir.is_dir():
            continue
        shutil.copytree(skill_dir, output_dir / "skills" / skill_dir.name)

    required_dirs = sorted({normalize_cwd(row["cwd"]) for row in threads})
    manifest = {
        "format_version": 1,
        "package_kind": "session-skill-package",
        "minimum_working_set_only": True,
        "cwd_filter": cwd_filter,
        "thread_ids": sorted(thread_ids),
        "skills_included": sorted(p.name for p in (output_dir / "skills").iterdir() if p.is_dir()),
        "deferred_components": [
            "logs_1.sqlite",
            "state_5.sqlite.logs",
            "state_5.sqlite.stage1_outputs",
            ".codex-global-state.json",
        ],
        "preferred_installer_skill": "codex-session-transfer",
    }
    save_manifest(output_dir / "package_manifest.json", manifest)
    write_jsonl(output_dir / "metadata" / "threads.jsonl", threads)
    write_jsonl(output_dir / "metadata" / "session_index.jsonl", index_rows)
    write_jsonl(output_dir / "metadata" / "thread_dynamic_tools.jsonl", tool_rows)
    (output_dir / "metadata" / "path_localization.json").write_text(
        json.dumps(
            {
                "rule": "replace path prefix before \\\\Documents with your local home path on the machine performing the install",
                "examples": required_dirs,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (output_dir / "skeleton" / "required-directories.json").write_text(json.dumps(required_dirs, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "README.md").write_text(
        "# Session Skill Package\n\n"
        "This package contains the first-phase minimum working set for selected Codex sessions and all user-defined skills.\n",
        encoding="utf-8",
    )
    (output_dir / "INSTALL_REMOTE.md").write_text(
        "# Install This Package on Your Machine\n\n"
        "You are the Codex agent that should install this package on your own machine. Treat this document as the primary execution guide.\n\n"
        "## Goal\n\n"
        "Install this first-phase session skill package into your local Codex Desktop environment with path localization, transaction logging, and rollback support.\n\n"
        "## What You Should Locate First\n\n"
        "Before running anything, determine:\n\n"
        "- the package root directory that contains this `INSTALL_REMOTE.md`\n"
        "- your local user home directory\n"
        "- your local Codex home directory, usually `<your-local-user-home>/.codex`\n"
        "- your local skill directory, usually `<your-local-codex-home>/skills`\n\n"
        "## Required Skill\n\n"
        "This package includes `skills/codex-session-transfer`. If your local Codex environment does not already have that skill, copy the packaged `codex-session-transfer` skill into your local skill directory first.\n\n"
        "## Install Workflow\n\n"
        "1. Confirm the package root directory.\n"
        "2. Confirm your local user home directory.\n"
        "3. Confirm your local Codex home directory.\n"
        "4. Ensure `codex-session-transfer` is installed in your local skill directory.\n"
        "5. Run the installer in dry-run mode first.\n"
        "6. Inspect the planned localized working directories, rollout destinations, and skill copy targets.\n"
        "7. If the dry-run plan looks correct, rerun with `--execute`.\n"
        "8. Record the returned transaction id.\n"
        "9. Restart Codex Desktop and verify the imported sessions.\n\n"
        "## Dry-Run Command Template\n\n"
        "```text\n"
        "python scripts/install_session_skill_package.py install <package-root> --codex-home <your-local-codex-home> --remote-home <your-local-user-home>\n"
        "```\n\n"
        "## Execute Command Template\n\n"
        "```text\n"
        "python scripts/install_session_skill_package.py install <package-root> --codex-home <your-local-codex-home> --remote-home <your-local-user-home> --execute\n"
        "```\n\n"
        "## Path Localization Rule\n\n"
        "For Windows paths, this package expects localization by preserving the suffix starting at `\\\\Documents\\\\` and replacing the leading prefix with your local user home.\n\n"
        "Example:\n\n"
        "- source path: `C:\\\\Users\\\\jian\\\\Documents\\\\R\\\\example-project`\n"
        "- your local home: `C:\\\\Users\\\\jianw`\n"
        "- localized path on your machine: `C:\\\\Users\\\\jianw\\\\Documents\\\\R\\\\example-project`\n\n"
        "If a path does not contain `\\\\Documents\\\\`, leave it unchanged unless the operator provides an explicit mapping.\n\n"
        "## Validation After Install\n\n"
        "After execute completes, verify:\n\n"
        "- the transaction status is recorded\n"
        "- the imported sessions appear under the localized project in Codex Desktop\n"
        "- the imported threads open successfully\n"
        "- the localized working-directory skeleton exists on disk\n\n"
        "## Recovery\n\n"
        "To inspect rollback candidates:\n\n"
        "```text\n"
        "python scripts/install_session_skill_package.py list-transactions --codex-home <your-local-codex-home>\n"
        "```\n\n"
        "To dry-run rollback of the most recent completed migration:\n\n"
        "```text\n"
        "python scripts/install_session_skill_package.py rollback --codex-home <your-local-codex-home> --latest\n"
        "```\n\n"
        "To execute rollback of the most recent completed migration:\n\n"
        "```text\n"
        "python scripts/install_session_skill_package.py rollback --codex-home <your-local-codex-home> --latest --execute\n"
        "```\n",
        encoding="utf-8",
    )
    return {"mode": "packup", "threads": len(threads), "dynamic_tools": len(tool_rows), "skills": len(manifest["skills_included"]), "output_dir": str(output_dir)}


def insert_or_replace_rows(con: sqlite3.Connection, table: str, rows: list[dict], columns: list[str]) -> None:
    if not rows:
        return
    placeholders = ",".join("?" for _ in columns)
    sql = f"INSERT OR REPLACE INTO {table} ({','.join(columns)}) VALUES ({placeholders})"
    data = [[row.get(col) for col in columns] for row in rows]
    con.executemany(sql, data)
    con.commit()


def journal_dir(codex_home: Path) -> Path:
    return codex_home / "transfer-journal"


def copy_if_exists(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def missing_parent_dirs(target: Path, stop_at: Path | None = None) -> list[Path]:
    missing = []
    current = target
    while True:
        if current.exists():
            break
        if stop_at is not None and current == stop_at:
            break
        missing.append(current)
        parent = current.parent
        if parent == current:
            break
        current = parent
    missing.reverse()
    return missing


def build_install_plan(package_root: Path, codex_home: Path, remote_home: str) -> tuple[dict, list[dict], list[dict], list[dict]]:
    manifest = load_manifest(package_root / "package_manifest.json")
    threads = read_jsonl(package_root / "metadata" / "threads.jsonl")
    index_rows = read_jsonl(package_root / "metadata" / "session_index.jsonl")
    tool_rows = read_jsonl(package_root / "metadata" / "thread_dynamic_tools.jsonl")
    required_dirs = json.loads((package_root / "skeleton" / "required-directories.json").read_text(encoding="utf-8"))

    plan = {"sessions": [], "skills": [], "directories": []}
    localized_threads = []
    for row in threads:
        target_cwd = localize_windows_documents_path(row["cwd"], remote_home)
        target_rollout = target_rollout_path(codex_home, row["rollout_path"])
        copied = dict(row)
        copied["cwd"] = target_cwd
        copied["rollout_path"] = str(target_rollout)
        sandbox = json.loads(copied["sandbox_policy"])
        sandbox["writable_roots"] = [target_cwd]
        copied["sandbox_policy"] = json.dumps(sandbox, ensure_ascii=False, separators=(",", ":"))
        localized_threads.append(copied)
        plan["sessions"].append(
            {
                "id": row["id"],
                "source_rollout": str(package_root / "sessions" / Path(row["rollout_path"]).name),
                "rollout": str(target_rollout),
                "cwd": target_cwd,
            }
        )

    for skill_dir in sorted((package_root / "skills").glob("*")):
        if skill_dir.is_dir():
            plan["skills"].append({"name": skill_dir.name, "source": str(skill_dir), "target": str(codex_home / "skills" / skill_dir.name)})

    for src_dir in required_dirs:
        plan["directories"].append(localize_windows_documents_path(src_dir, remote_home))

    return manifest, plan, localized_threads, index_rows, tool_rows


def build_transaction(codex_home: Path, package_root: Path, remote_home: str, plan: dict) -> tuple[Path, dict, list[dict]]:
    tx_id = str(uuid.uuid7())
    tx_dir = journal_dir(codex_home) / tx_id
    backups_dir = tx_dir / "backups"
    backups_dir.mkdir(parents=True, exist_ok=False)
    operations = []
    registered_created_dirs = set()

    def add_restore_or_remove_file(target: Path, backup_rel: str) -> None:
        backup_path = backups_dir / backup_rel
        if target.exists():
            copy_if_exists(target, backup_path)
            operations.append({"op": "restore_file", "target": str(target), "backup": str(backup_path)})
        else:
            operations.append({"op": "remove_created_file", "target": str(target)})

    def add_restore_or_remove_tree(target: Path, backup_rel: str) -> None:
        backup_path = backups_dir / backup_rel
        if target.exists():
            shutil.copytree(target, backup_path)
            operations.append({"op": "restore_tree", "target": str(target), "backup": str(backup_path)})
        else:
            operations.append({"op": "remove_created_dir", "target": str(target)})

    def register_created_parent_dirs(target: Path, stop_at: Path | None = None) -> None:
        for path in missing_parent_dirs(target, stop_at=stop_at):
            text = str(path)
            if text not in registered_created_dirs:
                operations.append({"op": "remove_created_dir", "target": text})
                registered_created_dirs.add(text)

    add_restore_or_remove_file(codex_home / "state_5.sqlite", "codex-home/state_5.sqlite")
    add_restore_or_remove_file(codex_home / "state_5.sqlite-wal", "codex-home/state_5.sqlite-wal")
    add_restore_or_remove_file(codex_home / "state_5.sqlite-shm", "codex-home/state_5.sqlite-shm")
    add_restore_or_remove_file(codex_home / "session_index.jsonl", "codex-home/session_index.jsonl")
    register_created_parent_dirs(codex_home / "sessions", stop_at=codex_home)
    register_created_parent_dirs(codex_home / "skills", stop_at=codex_home)

    for item in plan["sessions"]:
        rollout_target = Path(item["rollout"])
        add_restore_or_remove_file(rollout_target, f"sessions/{Path(item['rollout']).name}")
        register_created_parent_dirs(rollout_target.parent, stop_at=codex_home)
    for skill in plan["skills"]:
        skill_target = Path(skill["target"])
        add_restore_or_remove_tree(skill_target, f"skills/{skill['name']}")
        register_created_parent_dirs(skill_target.parent, stop_at=codex_home)
    for directory in plan["directories"]:
        dir_path = Path(directory)
        if not dir_path.exists():
            operations.append({"op": "remove_created_dir", "target": directory})
        register_created_parent_dirs(dir_path.parent, stop_at=Path(remote_home))

    transaction = {
        "transaction_id": tx_id,
        "created_at": now_utc(),
        "status": "prepared",
        "package_root": str(package_root),
        "codex_home": str(codex_home),
        "remote_home": remote_home,
        "plan_summary": {
            "sessions": len(plan["sessions"]),
            "skills": len(plan["skills"]),
            "directories": len(plan["directories"]),
        },
    }
    save_manifest(tx_dir / "manifest.json", transaction)
    write_jsonl(tx_dir / "operations.jsonl", operations)
    return tx_dir, transaction, operations


def execute_install(package_root: Path, codex_home: Path, plan: dict, localized_threads: list[dict], index_rows: list[dict], tool_rows: list[dict], tx_dir: Path, transaction: dict) -> dict:
    (codex_home / "skills").mkdir(parents=True, exist_ok=True)
    (codex_home / "sessions").mkdir(parents=True, exist_ok=True)
    journal_dir(codex_home).mkdir(parents=True, exist_ok=True)

    for dst in plan["directories"]:
        Path(dst).mkdir(parents=True, exist_ok=True)

    for skill in plan["skills"]:
        src = Path(skill["source"])
        dst = Path(skill["target"])
        merge_tree(src, dst)

    for item in plan["sessions"]:
        src = Path(item["source_rollout"])
        dst = Path(item["rollout"])
        dst.parent.mkdir(parents=True, exist_ok=True)
        text = src.read_text(encoding="utf-8")
        dst.write_text(update_rollout_text(text, item["cwd"]), encoding="utf-8")

    state_db = codex_home / "state_5.sqlite"
    con = sqlite3.connect(state_db)
    ensure_threads_schema(con)
    thread_columns = [
        "id",
        "rollout_path",
        "created_at",
        "updated_at",
        "source",
        "model_provider",
        "cwd",
        "title",
        "sandbox_policy",
        "approval_mode",
        "tokens_used",
        "has_user_event",
        "archived",
        "archived_at",
        "git_sha",
        "git_branch",
        "git_origin_url",
        "cli_version",
        "first_user_message",
        "agent_nickname",
        "agent_role",
        "memory_mode",
        "model",
        "reasoning_effort",
        "agent_path",
    ]
    insert_or_replace_rows(con, "threads", localized_threads, thread_columns)
    tool_columns = ["thread_id", "position", "name", "description", "input_schema", "defer_loading"]
    insert_or_replace_rows(con, "thread_dynamic_tools", tool_rows, tool_columns)
    con.close()

    target_index = codex_home / "session_index.jsonl"
    existing = {}
    for row in read_jsonl(target_index):
        existing[row["id"]] = row
    for row in index_rows:
        existing[row["id"]] = row
    write_jsonl(target_index, list(existing.values()))

    transaction["status"] = "completed"
    transaction["completed_at"] = now_utc()
    save_manifest(tx_dir / "manifest.json", transaction)
    return {"mode": "execute", "transaction_id": transaction["transaction_id"], "installed_sessions": len(plan["sessions"]), "installed_skills": len(plan["skills"])}


def list_transactions(codex_home: Path) -> dict:
    rows = []
    root = journal_dir(codex_home)
    if root.exists():
        for tx in sorted(root.iterdir()):
            manifest_path = tx / "manifest.json"
            if manifest_path.exists():
                rows.append(load_manifest(manifest_path))
    rows.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return {"transactions": rows}


def select_transaction(codex_home: Path, transaction_id: str | None, latest: bool) -> tuple[Path, dict]:
    root = journal_dir(codex_home)
    if not root.exists():
        raise SystemExit("No transfer-journal directory found.")
    if transaction_id:
        tx_dir = root / transaction_id
        manifest_path = tx_dir / "manifest.json"
        if not manifest_path.exists():
            raise SystemExit(f"Transaction not found: {transaction_id}")
        return tx_dir, load_manifest(manifest_path)
    if latest:
        candidates = []
        for tx in root.iterdir():
            manifest_path = tx / "manifest.json"
            if manifest_path.exists():
                manifest = load_manifest(manifest_path)
                if manifest.get("status") == "completed":
                    candidates.append((manifest.get("completed_at") or manifest.get("created_at") or "", tx, manifest))
        if not candidates:
            raise SystemExit("No completed transactions available for rollback.")
        candidates.sort(key=lambda item: item[0], reverse=True)
        _, tx_dir, manifest = candidates[0]
        return tx_dir, manifest
    raise SystemExit("Provide --transaction-id or --latest.")


def rollback_transaction(codex_home: Path, tx_dir: Path, transaction: dict, execute: bool) -> dict:
    operations = read_jsonl(tx_dir / "operations.jsonl")
    plan = {
        "transaction_id": transaction["transaction_id"],
        "status": transaction.get("status"),
        "rollback_operations": len(operations),
        "targets": [row["target"] for row in operations],
    }
    if not execute:
        return {"mode": "dry-run-rollback", "plan": plan}

    for row in reversed(operations):
        op = row["op"]
        target = Path(row["target"])
        if op == "restore_file":
            backup = Path(row["backup"])
            target.parent.mkdir(parents=True, exist_ok=True)
            if backup.exists():
                shutil.copy2(backup, target)
        elif op == "remove_created_file":
            if target.exists():
                target.unlink()
        elif op == "restore_tree":
            backup = Path(row["backup"])
            if backup.exists():
                replace_tree(backup, target)
        elif op == "remove_created_dir":
            if target.exists():
                shutil.rmtree(target)

    transaction["status"] = "rolled_back"
    transaction["rolled_back_at"] = now_utc()
    save_manifest(tx_dir / "manifest.json", transaction)
    return {"mode": "rollback", "transaction_id": transaction["transaction_id"], "rolled_back_operations": len(operations)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    packup = sub.add_parser("packup")
    packup.add_argument("--codex-home", required=True)
    packup.add_argument("--cwd-filter", required=True)
    packup.add_argument("--output-dir", required=True)

    install = sub.add_parser("install")
    install.add_argument("package_root")
    install.add_argument("--codex-home", required=True)
    install.add_argument("--remote-home", required=True)
    install.add_argument("--execute", action="store_true")

    list_tx = sub.add_parser("list-transactions")
    list_tx.add_argument("--codex-home", required=True)

    rollback = sub.add_parser("rollback")
    rollback.add_argument("--codex-home", required=True)
    rollback.add_argument("--transaction-id")
    rollback.add_argument("--latest", action="store_true")
    rollback.add_argument("--execute", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.command == "packup":
        codex_home = Path(args.codex_home).resolve()
        output_dir = Path(args.output_dir).resolve()
        result = build_packup(output_dir, codex_home, args.cwd_filter)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "install":
        package_root = Path(args.package_root).resolve()
        codex_home = Path(args.codex_home).resolve()
        remote_home = str(Path(args.remote_home).resolve())
        manifest, plan, localized_threads, index_rows, tool_rows = build_install_plan(package_root, codex_home, remote_home)
        if not args.execute:
            print(json.dumps({"mode": "dry-run", "manifest": manifest, "plan": plan}, ensure_ascii=False, indent=2))
            return 0
        tx_dir, transaction, _ = build_transaction(codex_home, package_root, remote_home, plan)
        result = execute_install(package_root, codex_home, plan, localized_threads, index_rows, tool_rows, tx_dir, transaction)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "list-transactions":
        codex_home = Path(args.codex_home).resolve()
        print(json.dumps(list_transactions(codex_home), ensure_ascii=False, indent=2))
        return 0

    if args.command == "rollback":
        codex_home = Path(args.codex_home).resolve()
        tx_dir, transaction = select_transaction(codex_home, args.transaction_id, args.latest)
        result = rollback_transaction(codex_home, tx_dir, transaction, execute=args.execute)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    raise SystemExit("Unsupported command.")


if __name__ == "__main__":
    raise SystemExit(main())
