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

import json
import os
import random
import piexif
from PIL import Image
from utils.file_namer import get_exif_data, get_camera_model, get_exif_year
from datetime import datetime

def format_exposure(value):
    try:
        if isinstance(value, tuple) and len(value) == 2 and value[1] != 0:
            val = value[0] / value[1]
        elif isinstance(value, (float, int)):
            val = value
        elif isinstance(value, str):
            val = float(value.lower().replace("s", "").strip())
        else:
            return ""
        return f"{round(val)} sec" if val >= 1 else f"1/{round(1 / val)} sec"
    except:
        return ""

def format_datetime(exif_dict):
    dt = exif_dict.get("DateTimeOriginal") or exif_dict.get("DateTime") or ""
    try:
        return datetime.strptime(dt, "%Y:%m:%d %H:%M:%S").strftime("%Y-%m-%d %H:%M:%S")
    except:
        return ""

def build_metadata(image_path, web_img_path, file_name, folder, year, location, subject):
    exif = get_exif_data(image_path)
    camera = get_camera_model(exif)

    # Validate all required fields exist and are not None/empty
    required_fields = ["FNumber", "FocalLength", "ISOSpeedRatings", "LensModel"]
    missing = [k for k in required_fields if k not in exif or not exif[k]]
    if missing:
        raise ValueError(f"❌ Missing critical EXIF fields in {image_path}: {', '.join(missing)}")

    aperture = f"F{round(float(exif['FNumber']), 1)}"
    focal    = int(float(exif["FocalLength"]))
    iso      = int(exif["ISOSpeedRatings"])
    lens     = exif["LensModel"]
    formatted_datetime = format_datetime(exif)

    # Use local file for dimensions; fall back if not found
    img_size_path = image_path if image_path and os.path.exists(image_path) else web_img_path
    with Image.open(img_size_path) as im:
        width, height = im.size

    # If not yet approved, these will be empty (filled at approval)
    thumb_img_path = ""
    path = ""

    # If file has already been approved/moved (web_img_path is set), fill in paths for DB/website
    if web_img_path and not web_img_path.startswith("http"):
        # Compose your final URL and thumb URL here if needed
        thumb_img_path = web_img_path.replace("/images/new/", "/images/new/thumbs/")
        path = web_img_path

    # Try to get exposure
    try:
        piexif_data = piexif.load(image_path)
        raw_exposure = piexif_data["Exif"].get(piexif.ExifIFD.ExposureTime)
    except:
        raw_exposure = None

    exposure = format_exposure(raw_exposure)

    # Normalize folder key for caption lookup
    with open("data/folder_map.json", "r", encoding="utf-8") as f:
        folder_map = json.load(f)
    reverse_map = {v: k for k, v in folder_map.items()}
    folder_key = reverse_map.get(folder, folder.replace(" ", "_"))

    # Load caption/keyword templates
    with open("data/caption_templates.json", "r", encoding="utf-8") as f:
        templates = json.load(f)
    template_list = templates.get(folder_key, {}).get("captions", [])
    keywords_list = templates.get(folder_key, {}).get("keywords", [])

    # Caption generation
    if template_list:
        caption_template = random.choice(template_list)
        final_caption = caption_template.format(
            subject=subject.replace("_", " "),
            location=location.replace("_", " "),
            folder=folder.replace("_", " "),
            camera=camera
        )
    else:
        final_caption = (
            f"A breathtaking capture of {location.replace('_', ' ')} in {folder.replace('_', ' ')}, "
            "photographed by Amir Darzi. Photography by YOUR_HOST, a Dutch photographer."
        )

    keywords_string = ", ".join(keywords_list)

    return {
        "Folder": folder,
        "File_Name": file_name,
        "Path": path,                 # filled on approve, empty on initial review
        "Thumb_Path": thumb_img_path, # filled on approve, empty on initial review
        "DateTime": formatted_datetime,
        "Camera": camera,
        "Lens_model": lens,
        "Width": width,
        "Height": height,
        "Exposure": exposure,
        "Aperture": aperture,
        "ISO": iso,
        "Focal_length": focal,
        "Keywords": keywords_string,
        "Caption": final_caption,
        "Location": location,
        "Subject": subject,
        "QR": None,
        "QC_Status": "NA"
    }

