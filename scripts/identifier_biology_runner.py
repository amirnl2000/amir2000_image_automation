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
import importlib
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def smoke_only() -> int:
    print("== Real identifier smoke test ==")

    modules = [
        "scripts.identifier_biology_bioclip",
        "scripts.identifier_general_vision",
        "scripts.identifier_vehicle_aircraft",
        "scripts.identifier_consensus",
        "scripts.subject_identifier_engine",
    ]

    ok = True

    for module_name in modules:
        try:
            importlib.import_module(module_name)
            print(f"[OK] {module_name}")
        except Exception as exc:
            print(f"[FAIL] {module_name}: {type(exc).__name__}: {exc}")
            ok = False

    print("")

    if ok:
        print("[READY] Real identifier modules import correctly.")
        return 0

    print("[NOT READY] Import failed.")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-only", action="store_true")
    parser.add_argument("--folder", default="")
    parser.add_argument("--subject-hint", default="")
    parser.add_argument("--location", default="")
    parser.add_argument("--max-samples", type=int, default=4)

    args = parser.parse_args()

    if args.smoke_only:
        return smoke_only()

    if not args.folder:
        print("[ERROR] Provide --folder with test images.")
        return 2

    from scripts.subject_identifier_engine import identify_subject_set

    folder = Path(args.folder)

    images = []
    for pattern in ["*.jpg", "*.jpeg", "*.png", "*.webp", "*.JPG", "*.JPEG", "*.PNG", "*.WEBP"]:
        images.extend(folder.glob(pattern))

    images = sorted(set(images))

    if not images:
        print(f"[ERROR] No images found in {folder}")
        return 2

    result = identify_subject_set(
        images,
        user_subject=args.subject_hint,
        location=args.location,
        folder=args.folder,
        max_samples=args.max_samples,
        print_progress=True,
    )

    print("")
    print("== JSON result ==")
    print(json.dumps(result, indent=2, ensure_ascii=True, default=str))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
