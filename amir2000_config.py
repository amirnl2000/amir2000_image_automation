# amir2000_config.py
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def CFG(env_key: str, hardcoded: str) -> str:
    """Env override wins. Otherwise use the hardcoded value in this file."""
    v = os.environ.get(env_key)
    if v is not None and str(v).strip() != "":
        return str(v).strip()
    return hardcoded

def CFG_INT(env_key: str, hardcoded: int) -> int:
    v = os.environ.get(env_key)
    if v is None or str(v).strip() == "":
        return int(hardcoded)
    return int(str(v).strip())

# ---------- local paths ----------
PATHS = {
    "DATA_DIR": CFG("DATA_DIR", r".\\data"),
    "INCOMING_DIR": CFG("INCOMING_DIR", r".\\incoming"),

    "BASE_PICK_DIR": CFG("BASE_PICK_DIR", r".\\incoming"),
    "STAGED_DIR": CFG("STAGED_DIR", r".\\incoming\\staged"),

    "REJECTED_DIR": CFG("REJECTED_DIR", r".\\rejected"),
    "DESKTOP_ROOT": CFG("DESKTOP_ROOT", r".\\export"),
    "ARCHIVE_ROOT": CFG("ARCHIVE_ROOT", r".\\archive"),

    "LOCAL_SITE_IMAGES_BASE": CFG("LOCAL_SITE_IMAGES_BASE", r".\\site_images"),
}

# Derived DB paths
PATHS["REVIEW_DB_PATH"] = str(Path(PATHS["DATA_DIR"]) / "review.db")
PATHS["PHOTOS_INFO_DB_PATH"] = str(Path(PATHS["DATA_DIR"]) / "photos_info_revamp.db")

# ---------- publish paths ----------
PUBLISH = {
    "REMOTE_BASE": CFG("REMOTE_BASE", "public_html/pic/images/new"),
    "PUBLIC_URL_BASE": CFG("PUBLIC_URL_BASE", "https://YOUR_SITE/pic/images/new"),
    "MYSQL_MIRROR_TABLE": CFG("MYSQL_MIRROR_TABLE", "photos_info_revamp"),
    "REVIEW_QUEUE_TABLE": CFG("REVIEW_QUEUE_TABLE", "review_queue"),
    "UPLOAD_LOG_FILE": CFG("UPLOAD_LOG_FILE", r".\\logs\\upload_errors.log"),  # supports ~
}

# ---------- credentials ----------
MYSQL = {
    "host": CFG("MYSQL_HOST", "YOUR_MYSQL_HOST"),
    "user": CFG("MYSQL_USER", "YOUR_MYSQL_USER"),
    "password": CFG("MYSQL_PASS", "YOUR_SECRET_HERE"),
    "database": CFG("MYSQL_DB", "YOUR_MYSQL_DB"),
    "charset": "utf8mb4",
    "use_unicode": True,
    "autocommit": False,
}

FTP_CONFIG = {
    "host": CFG("FTP_HOST", "YOUR_FTP_HOST"),
    "port": CFG_INT("FTP_PORT", 21),
    "user": CFG("FTP_USER", "YOUR_FTP_USER"),
    "passwd": CFG("FTP_PASS", "YOUR_SECRET_HERE"),
}

# --------------------------
# Ollama
# --------------------------
OLLAMA = {
    "host": "127.0.0.1",
    "port": 11434,
    "model": "qwen2.5vl:32b",
    "timeout_sec": 1800,     # slow model, go big
    "max_retries": 4,
    "options": {
        "temperature": 0.2,
        "top_p": 0.9,
        "top_k": 40,
        "repeat_penalty": 1.08,
        "num_predict": 220,
    },
}

# --------------------------
# Website V2 path mapping
# --------------------------
WEBSITE_V2 = {
    "resized_root": r"YOUR_PATH_HERE",
    "orig_root": r"YOUR_PATH_HERE",
    "base_url": "https://YOUR_SITE/REDACTED",
}

