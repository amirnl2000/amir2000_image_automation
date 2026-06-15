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

import os
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_ROOT = PROJECT_ROOT / "data" / "models"

MODEL_REPOS = [
    "microsoft/Florence-2-base",
    "imageomics/bioclip-2",
]


def main() -> None:
    try:
        from huggingface_hub import snapshot_download
    except Exception as exc:
        raise SystemExit(
            "Missing huggingface_hub. Run installer with -InstallPackages first. "
            f"Original error: {type(exc).__name__}: {exc}"
        )

    MODEL_ROOT.mkdir(parents=True, exist_ok=True)

    os.environ["HF_HOME"] = str(MODEL_ROOT / "huggingface_cache")
    os.environ["TRANSFORMERS_CACHE"] = str(MODEL_ROOT / "transformers_cache")
    os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

    print("== Download identifier models, safe serial resume mode ==")
    print(f"Model root: {MODEL_ROOT}")
    print("")

    for repo_id in MODEL_REPOS:
        local_dir = MODEL_ROOT / repo_id.replace("/", "__")
        print(f"[DOWNLOAD] {repo_id}")
        print(f"[TARGET]   {local_dir}")

        last_error = None

        for attempt in range(1, 6):
            try:
                print(f"[TRY] attempt {attempt}/5")

                path = snapshot_download(
                    repo_id=repo_id,
                    local_dir=str(local_dir),
                    max_workers=1,
                    etag_timeout=60,
                    force_download=False,
                )

                print(f"[OK] {repo_id} -> {path}")
                last_error = None
                break

            except Exception as exc:
                last_error = exc
                print(f"[WARN] {repo_id} attempt {attempt} failed: {type(exc).__name__}: {exc}")

                if attempt < 5:
                    wait_seconds = attempt * 10
                    print(f"[WAIT] {wait_seconds}s before retry")
                    time.sleep(wait_seconds)

        if last_error is not None:
            raise SystemExit(f"Failed to download {repo_id}: {type(last_error).__name__}: {last_error}")

    print("")
    print("[DONE] Identifier model download complete.")


if __name__ == "__main__":
    main()
