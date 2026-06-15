from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
INIT = DATA / "init"

REVIEW_DB = DATA / "review.db"
REVAMP_DB = DATA / "photos_info_revamp.db"

def apply_sql(db_path: Path, sql_path: Path) -> None:
    sql = sql_path.read_text(encoding="utf-8")
    con = sqlite3.connect(str(db_path))
    try:
        con.executescript(sql)
        con.commit()
    finally:
        con.close()

def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)

    review_sql = INIT / "review_queue.sql"
    revamp_sql = INIT / "photos_info_revamp.sql"
    metadata_quality_sql = INIT / "metadata_quality.sql"

    if not review_sql.exists():
        raise SystemExit(f"Missing {review_sql}")
    if not revamp_sql.exists():
        raise SystemExit(f"Missing {revamp_sql}")

    apply_sql(REVIEW_DB, review_sql)
    apply_sql(REVAMP_DB, revamp_sql)

    if metadata_quality_sql.exists():
        apply_sql(REVIEW_DB, metadata_quality_sql)

    print("OK: created data/review.db and data/photos_info_revamp.db from init SQL")

if __name__ == "__main__":
    main()
