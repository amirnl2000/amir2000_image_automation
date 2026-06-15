from __future__ import annotations

# AMIR_FORCE_LOGS_DIR_IMPORT_START
from pathlib import Path as _amir_force_logs_pathlib_path
import sys as _amir_force_logs_sys

_amir_force_logs_root = _amir_force_logs_pathlib_path(__file__).resolve().parent

while not (_amir_force_logs_root / "utils").exists() and _amir_force_logs_root.parent != _amir_force_logs_root:
    _amir_force_logs_root = _amir_force_logs_root.parent

if str(_amir_force_logs_root) not in _amir_force_logs_sys.path:
    _amir_force_logs_sys.path.insert(0, str(_amir_force_logs_root))

from utils.force_logs_dir import install as _amir_force_logs_install
_amir_force_logs_install()
# AMIR_FORCE_LOGS_DIR_IMPORT_END

import argparse
import json
import re
import sqlite3
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def clean_text(value: Any) -> str:
    if value is None:
        return ""

    text = str(value)
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def safe_table_name(value: str) -> str:
    table = clean_text(value)

    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
        raise SystemExit(f"[ERROR] Unsafe table name: {table}")

    return table


def load_router_results(json_path: Path) -> list[dict[str, Any]]:
    if not json_path.exists():
        raise SystemExit(f"[ERROR] Router JSON not found: {json_path}")

    data = json.loads(json_path.read_text(encoding="utf-8"))

    rows = data.get("results", [])

    if not isinstance(rows, list):
        raise SystemExit("[ERROR] Router JSON does not contain a results list.")

    return [
        row
        for row in rows
        if isinstance(row, dict)
    ]


def get_table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {
        row[1]
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }


def update_identifier_rows(
    conn: sqlite3.Connection,
    table: str,
    rows: list[dict[str, Any]],
    dry_run: bool,
) -> tuple[int, int]:
    columns = get_table_columns(conn, table)

    required = {
        "File_Name",
        "Original_File_Name",
        "identifier_route",
        "identifier_category",
        "identifier_subject",
        "identifier_confidence",
        "subject_seed",
        "subject_seed_mode",
        "subject_seed_confidence",
        "subject_seed_reason",
        "identifier_raw_json",
    }

    missing = sorted(required - columns)

    if missing:
        raise SystemExit(f"[ERROR] Missing DB columns: {', '.join(missing)}")

    updated = 0
    missed = 0

    for row in rows:
        image_name = clean_text(row.get("image_name"))

        if not image_name:
            missed += 1
            print("[MISS] Router row has no image_name.")
            continue

        values = {
            "identifier_route": clean_text(row.get("route")),
            "identifier_category": clean_text(row.get("category")),
            "identifier_subject": clean_text(row.get("subject")),
            "identifier_confidence": int(row.get("confidence") or 0),
            "subject_seed": clean_text(row.get("subject_seed")),
            "subject_seed_mode": clean_text(row.get("subject_seed_mode")),
            "subject_seed_confidence": int(row.get("subject_seed_confidence") or row.get("confidence") or 0),
            "subject_seed_reason": clean_text(row.get("subject_seed_reason")),
            "identifier_raw_json": json.dumps(row, ensure_ascii=False),
        }

        existing = conn.execute(
            f"""
            SELECT id
            FROM {table}
            WHERE File_Name = ?
               OR Original_File_Name = ?
            LIMIT 1
            """,
            (image_name, image_name),
        ).fetchone()

        if not existing:
            missed += 1
            print(f"[MISS] Not found in DB: {image_name}")
            continue

        print(
            f"[UPDATE] {image_name} | "
            f"{values['identifier_subject']} | "
            f"{values['subject_seed_mode']} | "
            f"{values['identifier_confidence']}"
        )

        if not dry_run:
            conn.execute(
                f"""
                UPDATE {table}
                SET
                    identifier_route = ?,
                    identifier_category = ?,
                    identifier_subject = ?,
                    identifier_confidence = ?,
                    subject_seed = ?,
                    subject_seed_mode = ?,
                    subject_seed_confidence = ?,
                    subject_seed_reason = ?,
                    identifier_raw_json = ?
                WHERE id = ?
                """,
                (
                    values["identifier_route"],
                    values["identifier_category"],
                    values["identifier_subject"],
                    values["identifier_confidence"],
                    values["subject_seed"],
                    values["subject_seed_mode"],
                    values["subject_seed_confidence"],
                    values["subject_seed_reason"],
                    values["identifier_raw_json"],
                    int(existing[0]),
                ),
            )

        updated += 1

    if not dry_run:
        conn.commit()

    return updated, missed


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()

    parser.add_argument("--db", default=str(PROJECT_ROOT / "data" / "review.db"))
    parser.add_argument("--table", default="review_queue")
    parser.add_argument("--json", default=str(PROJECT_ROOT / "data" / "identifier_router_last.json"))
    parser.add_argument("--dry-run", action="store_true")

    return parser


def main() -> None:
    args = build_arg_parser().parse_args()

    db_path = Path(args.db)
    json_path = Path(args.json)
    table = safe_table_name(args.table)

    if not db_path.exists():
        raise SystemExit(f"[ERROR] DB not found: {db_path}")

    rows = load_router_results(json_path)

    print("== Apply identifier router result to DB ==")
    print(f"DB:     {db_path}")
    print(f"Table:  {table}")
    print(f"JSON:   {json_path}")
    print(f"Rows:   {len(rows)}")
    print(f"DryRun: {args.dry_run}")
    print("")

    with sqlite3.connect(db_path) as conn:
        updated, missed = update_identifier_rows(
            conn=conn,
            table=table,
            rows=rows,
            dry_run=args.dry_run,
        )

    print("")
    print(f"[DONE] Updated: {updated}")
    print(f"[DONE] Missed:  {missed}")


if __name__ == "__main__":
    main()
