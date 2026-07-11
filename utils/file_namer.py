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
import re
import json
import time
import glob
import shutil
import tempfile
import warnings
from datetime import datetime

from PIL import Image
from PIL.ExifTags import TAGS


# -------------------------
# Helpers
# -------------------------

def _used_json_path() -> str:
    # main_set.py and review_editor.py set this to the canonical absolute path
    p = os.environ.get("AMIR_USED_FILENAMES_JSON")
    if p:
        return p

    # Fallback: ../data/used_filenames.json (works when this file lives in utils/)
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.abspath(os.path.join(here, os.pardir)) if os.path.basename(here).lower() == "utils" else here
    return os.path.join(root, "data", "used_filenames.json")


def _ensure_used_file(path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump([], f, indent=2)


def load_used_filenames(path: str | None = None) -> set[str]:
    path = path or _used_json_path()
    _ensure_used_file(path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return set(str(x) for x in data if x)
        if isinstance(data, dict):
            return set(str(k) for k in data.keys())
    except Exception:
        pass
    return set()


def save_used_filenames(used: set[str], path: str | None = None):
    path = path or _used_json_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    used = set(used)

    def _prune_backups(keep: int = 20):
        try:
            pattern = f"{path}.bak_*"
            files = [p for p in glob.glob(pattern) if os.path.isfile(p)]
            files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
            for old in files[max(1, int(keep)):]:
                try:
                    os.remove(old)
                except Exception:
                    pass
        except Exception:
            pass

    # backup (best effort)
    try:
        if os.path.exists(path):
            shutil.copy2(path, f"{path}.bak_{int(time.time())}")
            _prune_backups(keep=20)
    except Exception:
        pass

    # atomic write
    fd, tmp = tempfile.mkstemp(prefix="used_", suffix=".json", dir=os.path.dirname(path) or None)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(sorted(used), f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


_AIRCRAFT_HYPHEN_TOKEN_RE = re.compile(
    r"(?<![A-Z0-9])(?:ATR[-\s]+(?:72|42)-[0-9A-Z]{2,5}|Fokker[-\s]+[0-9]{2,3}|[A-Z]{1,3}-[A-Z0-9]{2,5}|[0-9][A-Z]-[A-Z0-9]{2,5}|[A-Z]?\d{3,4}[A-Z]?-[0-9A-Z]{2,5}|7\d{2}[A-Z]?-[0-9A-Z]{2,5})(?![A-Z0-9])",
    re.IGNORECASE,
)
_AIRCRAFT_HYPHEN_MARKER = "AMIRKEEPHYPHEN"


def _protect_aircraft_hyphen_tokens(text: str) -> str:
    return _AIRCRAFT_HYPHEN_TOKEN_RE.sub(
        lambda match: match.group(0).replace("-", _AIRCRAFT_HYPHEN_MARKER),
        text or "",
    )


def _restore_aircraft_hyphen_tokens(text: str) -> str:
    return re.sub(_AIRCRAFT_HYPHEN_MARKER, "-", text or "", flags=re.IGNORECASE)


def slugify(text: str) -> str:
    if text is None:
        return ""
    s = _protect_aircraft_hyphen_tokens(str(text).strip())

    # keep case, just sanitize
    s = s.replace("&", "and")
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)   # punctuation -> space
    s = re.sub(r"\s+", " ", s).strip()                 # collapse spaces
    s = s.replace(" ", "_")
    s = re.sub(r"_+", "_", s).strip("_")
    return _restore_aircraft_hyphen_tokens(s)


def _title_case_token(t: str) -> str:
    t = (t or "").strip()
    if not t:
        return ""
    if t.isupper():
        return t
    if t[:1].islower():
        return t[:1].upper() + t[1:]
    return t


def _title_case_slug_tokens(s: str) -> str:
    parts = [p for p in (s or "").split("_") if p]
    if not parts:
        return ""
    return "_".join(_title_case_token(p) for p in parts)


# -------------------------
# EXIF helpers (used by main_set)
# -------------------------

def get_exif_data(image_path: str) -> dict:
    if not image_path or not os.path.exists(image_path):
        return {}
    try:
        # Read EXIF via context manager so file handles are always released.
        with warnings.catch_warnings():
            try:
                warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            except Exception:
                pass

            with Image.open(image_path) as img:
                exif = {}

                def _collect(raw):
                    if not raw:
                        return
                    try:
                        items = raw.items() if hasattr(raw, "items") else raw
                        for tag_id, value in items:
                            tag = TAGS.get(tag_id, tag_id)
                            # Keep richer values already discovered (often from _getexif).
                            if tag not in exif or exif.get(tag) in (None, ""):
                                exif[tag] = value
                    except Exception:
                        pass

                # Prefer _getexif first; on many JPEGs this includes ExifIFD tags
                # (LensModel, ISO, FNumber, FocalLength, dimensions) that getexif()
                # can omit when only top-level tags are exposed.
                try:
                    _collect(getattr(img, "_getexif", lambda: None)())
                except Exception:
                    pass

                try:
                    _collect(img.getexif())
                except Exception:
                    pass

                return exif
    except Exception:
        return {}


def get_camera_model(exif: dict) -> str:
    make = (exif.get("Make") or "").strip()
    model = (exif.get("Model") or "").strip()

    # Normalize whitespace/underscores
    make_norm = re.sub(r"[_\s]+", " ", make).strip()
    model_norm = re.sub(r"[_\s]+", " ", model).strip()

    # Collapse duplicate tokens in Make, ex: "Canon Canon" -> "Canon"
    toks = make_norm.split()
    dedup = []
    for t in toks:
        if not dedup or dedup[-1].lower() != t.lower():
            dedup.append(t)
    make_norm = " ".join(dedup)

    # Avoid repeating Make if Model already starts with it
    if make_norm and model_norm and model_norm.lower().startswith(make_norm.lower()):
        full = model_norm
    elif make_norm and model_norm:
        full = f"{make_norm} {model_norm}"
    else:
        full = model_norm or make_norm

    # Canon R5 Mark II canonicalization (covers EOS R5m2, R5m2, R5 Mark II variants)
    compact = re.sub(r"[^a-z0-9]+", "", full.lower())
    if ("r5m2" in compact) or ("r5markii" in compact) or ("r5mark2" in compact):
        return "Canon_EOS_R5_Mark_II"

    camera = slugify(full)
    return camera if camera else "Canon_EOS_R5_Mark_II"



def get_exif_year(exif: dict) -> str:
    dt = exif.get("DateTimeOriginal") or exif.get("DateTime") or ""
    try:
        # usually "YYYY:MM:DD HH:MM:SS"
        y = str(dt)[:4]
        if y.isdigit():
            return y
    except Exception:
        pass
    return str(datetime.now().year)


# -------------------------
# Filename generator
# -------------------------

def generate_unique_filename(subject, location, folder, camera, year):
    used_path = _used_json_path()
    used = load_used_filenames(used_path)
    used_ci = {str(u).casefold() for u in used if isinstance(u, str)}

    subject_s = slugify(subject)
    location_s = _title_case_slug_tokens(slugify(location))
    camera_s = slugify(camera) or "Canon_EOS_R5_Mark_II"

    # Defensive canonicalization (in case a raw camera string bypassed get_camera_model)
    cam_compact = camera_s.lower().replace("_", "")
    if ("r5m2" in cam_compact) or ("r5markii" in cam_compact) or ("r5mark2" in cam_compact):
        camera_s = "Canon_EOS_R5_Mark_II"
    if camera_s.lower().startswith("canon_canon_"):
        camera_s = "Canon_" + camera_s[len("canon_canon_"):]

    year_s = str(year) if str(year).isdigit() else str(datetime.now().year)

    # normalize folder token (but preserve case from input)
    folder_clean = _title_case_slug_tokens(slugify(folder))
    if folder_clean and not folder_clean.lower().endswith("photography"):
        folder_clean = f"{folder_clean}_Photography"

    # Key idea:
    # If the ONLY difference is folder casing (Cities vs cities),
    # continue from the max existing index, and reuse the existing folder token casing.
    prefix = f"{subject_s}_{location_s}_"
    suffix = f"_{camera_s}_{year_s}_"
    prefix_cf = prefix.casefold()
    suffix_cf = suffix.casefold()

    max_idx = 0
    canonical_folder = None

    for fn in used:
        if not isinstance(fn, str):
            continue
        fn = fn.strip()
        fn_cf = fn.casefold()
        if not fn_cf.endswith(".jpg"):
            continue
        if not fn_cf.startswith(prefix_cf):
            continue

        # split once from the right by suffix (case-insensitive)
        pos = fn_cf.rfind(suffix_cf)
        if pos < 0:
            continue
        pre = fn[:pos]
        rest = fn[pos + len(suffix):]

        if not rest.casefold().endswith(".jpg"):
            continue
        idx_str = rest[:-4]  # remove .JPG
        if len(idx_str) != 3 or not idx_str.isdigit():
            continue

        folder_part = pre[len(prefix):]  # between prefix and suffix
        if folder_part.casefold() == folder_clean.casefold():
            idx_val = int(idx_str)
            if idx_val > max_idx:
                max_idx = idx_val
                canonical_folder = folder_part

    if canonical_folder:
        folder_clean = canonical_folder

    # Preserve caller casing; uniqueness checks are case-insensitive.
    base = "_".join([subject_s, location_s, folder_clean, camera_s, year_s])
    start = (max_idx + 1) if max_idx > 0 else 1

    for i in range(start, 1000):
        filename = f"{base}_{i:03d}.JPG"
        if filename.casefold() not in used_ci:
            used.add(filename)
            used_ci.add(filename.casefold())
            save_used_filenames(used, used_path)
            return filename

    raise Exception("Too many similar filenames; could not find a unique one.")
