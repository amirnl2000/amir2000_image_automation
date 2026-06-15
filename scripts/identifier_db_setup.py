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

import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
RESULTS_DB = DATA_DIR / "identifier_results.db"
LABEL_BANK_DB = DATA_DIR / "identifier_label_bank.db"


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(path)


def create_results_db() -> None:
    with connect(RESULTS_DB) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS identifier_image_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                set_key TEXT,
                image_path TEXT,
                file_name TEXT,
                detected_domain TEXT,
                model_used TEXT,
                top_candidates_json TEXT,
                raw_result_json TEXT,
                chosen_subject TEXT,
                confidence REAL,
                rank_used TEXT,
                needs_manual INTEGER DEFAULT 0,
                notes TEXT
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_identifier_image_results_set_key
            ON identifier_image_results(set_key)
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS identifier_set_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                set_key TEXT UNIQUE,
                image_count INTEGER,
                sampled_count INTEGER,
                subject_hint TEXT,
                location_hint TEXT,
                folder_hint TEXT,
                detected_domain TEXT,
                final_subject_suggestion TEXT,
                confidence REAL,
                rank_used TEXT,
                needs_manual INTEGER DEFAULT 0,
                top_candidates_json TEXT,
                source_models_json TEXT,
                notes TEXT
            )
            """
        )


def create_label_bank_db() -> None:
    with connect(LABEL_BANK_DB) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS identifier_labels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                domain TEXT NOT NULL,
                label TEXT NOT NULL,
                latin_name TEXT,
                parent_label TEXT,
                label_rank TEXT,
                allowed_for_filename INTEGER DEFAULT 1,
                notes TEXT,
                UNIQUE(domain, label)
            )
            """
        )

        seed_rows = [
            ("bird", "Gull", "", "Bird", "common_group", 1, "Safe group for gulls when exact species is uncertain"),
            ("bird", "Herring Gull", "Larus argentatus", "Gull", "species", 1, "Use only when visually supported"),
            ("bird", "Black headed Gull", "Chroicocephalus ridibundus", "Gull", "species", 1, "Use only when visually supported"),
            ("bird", "Lesser Black backed Gull", "Larus fuscus", "Gull", "species", 1, "Use only when visually supported"),
            ("bird", "Egyptian Goose", "Alopochen aegyptiaca", "Goose", "species", 1, "Common in Netherlands"),
            ("bird", "Greylag Goose", "Anser anser", "Goose", "species", 1, "Use only when visually supported"),
            ("mammal", "Horse", "Equus caballus", "Mammal", "species_common", 1, "Common name enough for upload subject"),
            ("flower", "Prunus Blossoms", "Prunus", "Spring Blossoms", "genus", 1, "Use when Prunus is visually plausible"),
            ("flower", "White Spring Blossoms on Branches", "", "Spring Blossoms", "safe_descriptive", 1, "Safe if exact genus is uncertain"),
            ("aircraft", "Passenger Jet", "", "Aircraft", "safe_group", 1, "Use when exact type is uncertain"),
            ("aircraft", "Commercial Aircraft", "", "Aircraft", "safe_group", 1, "Use when aircraft type is uncertain"),
            ("aircraft", "Boeing 737", "", "Passenger Jet", "family", 1, "Use only when supported"),
            ("aircraft", "Airbus A320", "", "Passenger Jet", "family", 1, "Use only when supported"),
            ("airline", "KLM Passenger Jet", "", "Passenger Jet", "operator_visible", 1, "Use only when livery or text is visible"),
            ("airline", "EasyJet Passenger Jet", "", "Passenger Jet", "operator_visible", 1, "Use only when livery or text is visible"),
            ("boat", "Fishing Boat", "", "Boat", "object", 1, "Use when trawler or fishing vessel is visible"),
            ("vehicle", "Classic Car", "", "Car", "safe_group", 1, "Use when exact make/model is uncertain"),
            ("vehicle", "Motorcycle", "", "Vehicle", "safe_group", 1, "Use when motorcycle is visible"),
        ]

        conn.executemany(
            """
            INSERT OR IGNORE INTO identifier_labels (
                domain,
                label,
                latin_name,
                parent_label,
                label_rank,
                allowed_for_filename,
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            seed_rows,
        )


def main() -> None:
    create_results_db()
    create_label_bank_db()

    print("== Identifier DB setup ==")
    print(f"[OK] Results DB:   {RESULTS_DB}")
    print(f"[OK] Label bank DB: {LABEL_BANK_DB}")


if __name__ == "__main__":
    main()
