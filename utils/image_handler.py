
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
import shutil
from datetime import datetime

def copy_and_rename_original(src_path, new_name, folder_key):
    try:
        # Extract date (fallback: current year)
        try:
            mtime = os.path.getmtime(src_path)
            year = datetime.fromtimestamp(mtime).strftime("%Y")
        except:
            year = datetime.now().strftime("%Y")

        # Construct destination folder
        output_root = os.environ.get(
            "AMIR2000_PHOTO_OUTPUT_ROOT",
            os.path.join(os.getcwd(), "output", "photos", "new"),
        )
        dest_folder = os.path.join(
            output_root, year, folder_key
        )
        os.makedirs(dest_folder, exist_ok=True)

        # Full destination path
        dest_path = os.path.join(dest_folder, new_name)

        # Copy file
        shutil.copy2(src_path, dest_path)
        print(f"Copied to: {dest_path}")
        return dest_path
    except Exception as e:
        print(f"Error copying {src_path}: {e}")
        return None
