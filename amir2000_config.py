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
    "DESKTOP_ROOT": CFG("DESKTOP_ROOT", r".\\export"),
    "ARCHIVE_ROOT": CFG("ARCHIVE_ROOT", r".\\archive"),

    "LOCAL_SITE_IMAGES_BASE": CFG("LOCAL_SITE_IMAGES_BASE", r".\\site_images"),

    # Metadata quality / ML support. Keep all DBs under DATA_DIR.
    "REVAMP_KNOWLEDGE_DB_PATH": CFG(
        "REVAMP_KNOWLEDGE_DB_PATH",
        str(Path(CFG("DATA_DIR", r".\\data")) / "revamp_knowledge.db"),
    ),
    "METADATA_QUALITY_SCRIPT": CFG(
        "METADATA_QUALITY_SCRIPT",
        str(ROOT / "scripts" / "metadata_quality_production.py"),
    ),
    "LEGACY_BASE_PICK_DIR": CFG(
        "LEGACY_BASE_PICK_DIR",
        r"YOUR_PATH_HERE to be uploaded",
    ),
}

PATHS["REJECTED_DIR"] = CFG(
    "REJECTED_DIR",
    str(Path(PATHS["BASE_PICK_DIR"]) / "rejected"),
)

# Derived DB paths
PATHS["REVIEW_DB_PATH"] = str(Path(PATHS["DATA_DIR"]) / "review.db")
PATHS["PHOTOS_INFO_DB_PATH"] = str(Path(PATHS["DATA_DIR"]) / "photos_info_revamp.db")

# ---------- publish paths ----------
PUBLISH = {
    "REMOTE_BASE": CFG("REMOTE_BASE", "public_html/pic/images/new"),
    "PUBLIC_URL_BASE": CFG("PUBLIC_URL_BASE", "https://YOUR_SITE/pic/images/new"),
    "MYSQL_MIRROR_TABLE": CFG("MYSQL_MIRROR_TABLE", "photos_info_revamp"),
    "REVIEW_QUEUE_TABLE": CFG("REVIEW_QUEUE_TABLE", "review_queue"),
    "METADATA_QUALITY_TABLE": CFG("METADATA_QUALITY_TABLE", "metadata_quality"),
    "METADATA_QUALITY_SYNC_AFTER_UPLOAD": CFG("METADATA_QUALITY_SYNC_AFTER_UPLOAD", "1"),
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
    "model": "qwen2.5vl:7b",
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

# BEGIN AMIR2000 SUBJECT IDENTIFIER CONFIG
SUBJECT_IDENTIFIER = {
    "ENABLE": CFG("SUBJECT_IDENTIFIER_ENABLE", "1") == "1",
    "MODEL": CFG("SUBJECT_IDENTIFIER_MODEL", "qwen2.5vl:7b"),
    "FALLBACK_MODEL": CFG("SUBJECT_IDENTIFIER_FALLBACK_MODEL", "llama3.2-vision:latest"),
    "MAX_SAMPLE_IMAGES": int(CFG("SUBJECT_IDENTIFIER_MAX_SAMPLE_IMAGES", "12")),
    "MIN_CONFIDENCE": int(CFG("SUBJECT_IDENTIFIER_MIN_CONFIDENCE", "72")),
    "MIN_SPECIES_CONFIDENCE": int(CFG("SUBJECT_IDENTIFIER_MIN_SPECIES_CONFIDENCE", "78")),
    "IMAGE_MAX_SIDE": int(CFG("SUBJECT_IDENTIFIER_IMAGE_MAX_SIDE", "1400")),
    "JPEG_QUALITY": int(CFG("SUBJECT_IDENTIFIER_JPEG_QUALITY", "88")),
    "TIMEOUT_SEC": int(CFG("SUBJECT_IDENTIFIER_TIMEOUT_SEC", "150")),
}

PATHS["REVAMP_KNOWLEDGE_DB_PATH"] = CFG(
    "REVAMP_KNOWLEDGE_DB_PATH",
    str(Path(PATHS["DATA_DIR"]) / "revamp_knowledge.db"),
)
PATHS["SUBJECT_IDENTIFIER_LOG_DB"] = CFG(
    "SUBJECT_IDENTIFIER_LOG_DB",
    str(Path(PATHS["DATA_DIR"]) / "review.db"),
)
# END AMIR2000 SUBJECT IDENTIFIER CONFIG
