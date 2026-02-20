import os
import shutil
from datetime import datetime


def copy_and_rename_original(src_path, new_name, folder_key):
    try:
        # Extract date (fallback: current year)
        try:
            mtime = os.path.getmtime(src_path)
            year = datetime.fromtimestamp(mtime).strftime("%Y")
        except Exception:
            year = datetime.now().strftime("%Y")

        # Construct destination folder (set AMIR_IMAGE_ARCHIVE_ROOT in your environment)
        archive_root = os.environ.get("AMIR_IMAGE_ARCHIVE_ROOT", "YOUR_PATH_HERE")
        dest_folder = os.path.join(archive_root, year, folder_key)
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
