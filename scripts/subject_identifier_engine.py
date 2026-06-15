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
import sqlite3
import time
from pathlib import Path
from typing import Any

from .identifier_biology_bioclip import identify_image_biology
from .identifier_consensus import build_subject_consensus
from .identifier_general_vision import identify_image_general
from .identifier_vehicle_aircraft import refine_vehicle_aircraft


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = PROJECT_ROOT / "data"
RESULTS_DB = DATA_ROOT / "identifier_results.db"

SOURCE_NAME = "subject_identifier_engine_v1"


def choose_samples(image_paths: list[str | Path], *, max_samples: int = 12) -> list[Path]:
    paths = [Path(path) for path in image_paths if Path(path).exists()]

    if len(paths) <= max_samples:
        return paths

    if max_samples <= 1:
        return [paths[0]]

    indexes = []
    last = len(paths) - 1

    for slot in range(max_samples):
        index = round(slot * last / (max_samples - 1))
        indexes.append(index)

    seen = set()
    samples = []

    for index in indexes:
        if index not in seen:
            samples.append(paths[index])
            seen.add(index)

    return samples


def identify_subject_set(
    image_paths: list[str | Path],
    *,
    user_subject: str = "",
    location: str = "",
    folder: str = "",
    max_samples: int = 12,
    print_progress: bool = True,
) -> dict[str, Any]:
    started = time.time()
    samples = choose_samples(image_paths, max_samples=max_samples)

    if print_progress:
        print(
            f"[IDENTIFIER] start | selected={len(image_paths)} | samples={len(samples)} | "
            f"biology=BioCLIP2 | general=Ollama"
        )

    candidates: list[dict[str, Any]] = []

    for index, image_path in enumerate(samples, start=1):
        sample_started = time.time()

        if print_progress:
            print(f"[IDENTIFIER] analyzing sample {index}/{len(samples)}: {image_path.name}")

        general = identify_image_general(
            image_path,
            user_subject=user_subject,
            location=location,
            folder=folder,
        )
        general = refine_vehicle_aircraft(
            general,
            user_subject=user_subject,
            folder=folder,
        )

        candidates.append(general)

        should_run_biology = _should_run_biology(general, user_subject=user_subject, folder=folder)

        if should_run_biology:
            try:
                biology = identify_image_biology(image_path)
            except Exception as exc:
                biology = {
                    "ok": False,
                    "source": "bioclip2_zero_shot_v1",
                    "image_path": str(image_path),
                    "subject": "",
                    "category": "unknown",
                    "confidence": 0,
                    "error": f"{type(exc).__name__}: {exc}",
                }
                if print_progress:
                    print(f"[IDENTIFIER] biology model unavailable; continuing with vision result: {biology['error']}")

            candidates.append(biology)

        elapsed_total = max(0.01, time.time() - started)
        done = index
        per_item = elapsed_total / done
        remaining = max(0, int(round(per_item * (len(samples) - done))))

        if print_progress:
            sample_elapsed = int(round(time.time() - sample_started))
            print(
                f"[IDENTIFIER] sample {index}/{len(samples)} done | "
                f"sample_elapsed {sample_elapsed}s | elapsed {int(elapsed_total)}s | ETA {remaining}s"
            )

    result = build_subject_consensus(
        candidates,
        user_subject=user_subject,
        location=location,
        folder=folder,
    )

    result["source"] = SOURCE_NAME
    result["sample_count"] = len(samples)
    result["selected_count"] = len(image_paths)
    result["elapsed_seconds"] = round(time.time() - started, 2)
    result["user_subject_hint"] = user_subject
    result["location_hint"] = location
    result["folder_hint"] = folder

    _write_result_to_db(result, samples)

    if print_progress:
        subject = result.get("subject") or "(none)"
        confidence = result.get("confidence", 0)
        mode = result.get("mode", "")
        print(f"[IDENTIFIER] result | subject={subject} | confidence={confidence} | mode={mode}")

    return result


def _should_run_biology(candidate: dict[str, Any], *, user_subject: str = "", folder: str = "") -> bool:
    text = " ".join(
        [
            str(candidate.get("category", "")),
            str(candidate.get("subject", "")),
            str(candidate.get("label", "")),
            user_subject,
            folder,
        ]
    ).lower()

    return any(
        token in text
        for token in [
            "bird",
            "gull",
            "goose",
            "duck",
            "swan",
            "animal",
            "mammal",
            "horse",
            "insect",
            "bee",
            "fly",
            "butterfly",
            "flower",
            "blossom",
            "plant",
            "fungi",
            "mushroom",
            "nature",
        ]
    )


def _write_result_to_db(result: dict[str, Any], samples: list[Path]) -> None:
    try:
        DATA_ROOT.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(RESULTS_DB) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS identifier_set_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    source TEXT,
                    subject TEXT,
                    confidence INTEGER,
                    category TEXT,
                    mode TEXT,
                    selected_count INTEGER,
                    sample_count INTEGER,
                    location_hint TEXT,
                    folder_hint TEXT,
                    user_subject_hint TEXT,
                    sample_paths_json TEXT,
                    result_json TEXT
                )
                """
            )

            conn.execute(
                """
                INSERT INTO identifier_set_results (
                    source,
                    subject,
                    confidence,
                    category,
                    mode,
                    selected_count,
                    sample_count,
                    location_hint,
                    folder_hint,
                    user_subject_hint,
                    sample_paths_json,
                    result_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    SOURCE_NAME,
                    str(result.get("subject", "")),
                    int(result.get("confidence", 0) or 0),
                    str(result.get("category", "")),
                    str(result.get("mode", "")),
                    int(result.get("selected_count", 0) or 0),
                    int(result.get("sample_count", 0) or 0),
                    str(result.get("location_hint", "")),
                    str(result.get("folder_hint", "")),
                    str(result.get("user_subject_hint", "")),
                    json.dumps([str(path) for path in samples], ensure_ascii=True),
                    json.dumps(result, ensure_ascii=True, default=str),
                ),
            )
    except Exception as exc:
        result["db_error"] = f"{type(exc).__name__}: {exc}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("images", nargs="+")
    parser.add_argument("--subject-hint", default="")
    parser.add_argument("--location", default="")
    parser.add_argument("--folder", default="")
    parser.add_argument("--max-samples", type=int, default=12)
    parser.add_argument("--json", action="store_true")

    args = parser.parse_args()

    result = identify_subject_set(
        args.images,
        user_subject=args.subject_hint,
        location=args.location,
        folder=args.folder,
        max_samples=args.max_samples,
        print_progress=not args.json,
    )

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=True, default=str))


if __name__ == "__main__":
    main()
