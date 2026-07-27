import argparse
import json
import sqlite3
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from .config import DB_PATH
from .db import get_conn
from .migrations import MigrationError, apply_migrations, migration_status


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect or upgrade the local SQLite application schema."
    )
    parser.add_argument("command", choices=("status", "backup", "upgrade"))
    parser.add_argument(
        "--output",
        type=Path,
        help="Backup destination; only valid with the backup command.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Print compact JSON instead of indented JSON.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.output and args.command != "backup":
        build_parser().error("--output is only valid with the backup command")
    if args.command == "backup":
        return _backup_database(args.output, compact=args.compact)
    try:
        with get_conn() as conn:
            if args.command == "upgrade":
                status = apply_migrations(conn)
            else:
                status = migration_status(conn)
    except MigrationError as exc:
        _print_json(
            {"status": "failed", "error": str(exc)},
            compact=args.compact,
        )
        return 1

    _print_json(status.public_dict(include_history=True), compact=args.compact)
    return 0 if status.ready else 2


def _backup_database(output: Path | None, *, compact: bool) -> int:
    if not DB_PATH.exists():
        _print_json({"status": "failed", "error": "database does not exist"}, compact=compact)
        return 2
    destination = output or DB_PATH.with_name(
        f"{DB_PATH.stem}.backup-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.db"
    )
    destination = destination.expanduser().resolve()
    if destination == DB_PATH.resolve():
        _print_json({"status": "failed", "error": "backup must use a different path"}, compact=compact)
        return 2
    if destination.exists():
        _print_json({"status": "failed", "error": "backup destination already exists"}, compact=compact)
        return 2
    destination.parent.mkdir(parents=True, exist_ok=True)

    try:
        with get_conn() as source, sqlite3.connect(destination) as target:
            source.backup(target)
            integrity = target.execute("PRAGMA integrity_check").fetchone()[0]
    except sqlite3.Error as exc:
        _print_json({"status": "failed", "error": f"backup failed: {exc}"}, compact=compact)
        return 1
    if integrity != "ok":
        _print_json(
            {"status": "failed", "error": "backup integrity check failed"},
            compact=compact,
        )
        return 1
    _print_json(
        {
            "status": "backup_created",
            "output": str(destination),
            "integrity_check": integrity,
        },
        compact=compact,
    )
    return 0


def _print_json(payload: dict, *, compact: bool) -> None:
    if compact:
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
