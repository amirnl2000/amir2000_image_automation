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

# AMIR_VISIBLE_TEXT_HARD_BLOCK_START
# Hard final-subject guard.
# OCR / visible text / text DB can be context only.
# It must never become the selected upload subject.

def _amir_hard_subject_norm_v2(value: object) -> str:
    import re

    text = str(value or "").replace("_", " ").replace("-", " ").lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _amir_hard_subject_row_ok_v2(row: object) -> bool:
    if not isinstance(row, dict):
        return True

    source = _amir_hard_subject_norm_v2(row.get("source", ""))
    subject = _amir_hard_subject_norm_v2(row.get("subject", ""))

    if not subject:
        return False

    bad_source_bits = {
        "visible text db",
        "visible text",
        "ocr",
        "ocr text",
        "text db",
        "readable text",
        "text context",
        "untrusted",
    }

    if any(bit in source for bit in bad_source_bits):
        return False

    bad_subjects = {
        "text",
        "visible text",
        "ocr text",
        "written text",
        "writing",
        "letter",
        "letters",
        "word",
        "words",
        "label",
        "labels",
        "caption",
        "object",
        "thing",
        "scene",
        "view",
        "detail",
        "details",
        "background",
        "foreground",
        "unknown",
        "blossom",
        "flower",
        "flowers",
        "plant",
        "plants",
        "bird",
        "birds",
        "animal",
        "animals",
        "boat",
        "person",
        "man",
        "woman",
        "building",
        "vehicle",
    }

    if subject in bad_subjects:
        return False

    return True


def _amir_filter_subject_rows_v2(rows: object) -> list:
    kept = []

    for row in rows or []:
        if _amir_hard_subject_row_ok_v2(row):
            kept.append(row)

    return kept


def _amir_log_untrusted_subject_row_v2(row: object) -> None:
    if not isinstance(row, dict):
        return

    try:
        print(
            "[SUBJECT AI] rejected | untrusted subject source | "
            f"subject={row.get('subject', '')} | source={row.get('source', '')}"
        )
    except Exception:
        pass
# AMIR_VISIBLE_TEXT_HARD_BLOCK_END

# AMIR_HARD_VISIBLE_TEXT_VOTE_FILTER_START
# Final subject voting safety filter.
# OCR / visible text may be context, but it must never become the subject.
# Generic. Not per topic. Not per subject.

def _amir_subject_vote_row_is_valid(row: dict) -> bool:
    import re

    source = str(row.get("source", "") or "").lower().replace("-", "_")
    subject = str(row.get("subject", "") or "").strip()

    norm = subject.lower().replace("_", " ").replace("-", " ")
    norm = re.sub(r"[^a-z0-9\s]", " ", norm)
    norm = re.sub(r"\s+", " ", norm).strip()

    if not norm:
        return False

    bad_sources = {
        "visible_text_untrusted_context",
        "visible_text",
        "ocr",
        "ocr_text",
        "text_db",
        "readable_text",
    }

    if any(bad in source for bad in bad_sources):
        return False

    meta_labels = {
        "text",
        "visible text",
        "ocr text",
        "written text",
        "writing",
        "letters",
        "lettering",
        "word",
        "words",
        "label",
        "labels",
        "caption",
        "object",
        "thing",
        "scene",
        "view",
        "detail",
        "details",
        "background",
        "foreground",
        "unknown",
    }

    if norm in meta_labels:
        return False

    tokens = norm.split()

    if len(tokens) == 1 and tokens[0] in {
        "flower",
        "flowers",
        "bird",
        "birds",
        "animal",
        "animals",
        "plant",
        "plants",
        "tree",
        "trees",
        "boat",
        "person",
        "man",
        "woman",
        "building",
        "vehicle",
    }:
        return False

    return True


def _amir_filter_subject_vote_rows(rows):
    kept = []

    for row in rows or []:
        try:
            if _amir_subject_vote_row_is_valid(row):
                kept.append(row)
        except Exception:
            continue

    return kept
# AMIR_HARD_VISIBLE_TEXT_VOTE_FILTER_END

# AMIR_TRUSTED_SUBJECT_SOURCE_FIX_START
# Generic subject source trust filter.
# OCR / visible_text_untrusted_context may be useful context, but it is NOT visual subject evidence.
# Not topic-specific. Not subject-specific.

def _amir_subject_source_is_trusted(row: dict) -> bool:
    import re

    source = str(row.get("source", "") or "").lower().replace("-", "_")
    subject = str(row.get("subject", "") or "").strip()

    normalized = subject.lower().replace("_", " ").replace("-", " ")
    normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()

    if not normalized:
        return False

    # OCR/text sources are never trusted as the main subject.
    # A sign can be keyword/context later, but not the upload subject.
    untrusted_sources = {
        "visible_text_untrusted_context",
        "ocr",
        "ocr_text",
        "text_db",
        "visible_text",
    }

    if any(src in source for src in untrusted_sources):
        return False

    hard_meta_labels = {
        "text",
        "visible text",
        "ocr text",
        "written text",
        "writing",
        "letters",
        "lettering",
        "word",
        "words",
        "label",
        "labels",
        "caption",
        "object",
        "thing",
        "scene",
        "view",
        "detail",
        "background",
        "foreground",
    }

    if normalized in hard_meta_labels:
        return False

    tokens = normalized.split()

    if len(tokens) == 1 and tokens[0] in {
        "flower",
        "flowers",
        "bird",
        "birds",
        "animal",
        "animals",
        "plant",
        "plants",
        "tree",
        "trees",
        "boat",
        "person",
        "man",
        "woman",
        "building",
        "vehicle",
    }:
        # One-word broad labels are too weak as final subject.
        return False

    return True
# AMIR_TRUSTED_SUBJECT_SOURCE_FIX_END

# AMIR_SUBJECT_META_LABEL_OUTLIER_FIX_START
# Generic subject resolver guard.
# Prevents OCR/meta labels like "Text" from becoming a real subject.
# Not topic-specific. Not subject-specific.

def _amir_subject_normalize_for_vote(value: object) -> str:
    import re

    text = str(value or "").replace("_", " ").replace("-", " ").lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _amir_subject_meta_label_leak(subject: object, source: object = "") -> bool:
    text = _amir_subject_normalize_for_vote(subject)
    src = _amir_subject_normalize_for_vote(source)

    if not text:
        return True

    tokens = text.split()

    hard_meta_labels = {
        "text",
        "visible text",
        "ocr text",
        "written text",
        "writing",
        "letters",
        "lettering",
        "words",
        "word",
        "caption",
        "label",
        "labels",
        "unknown text",
        "readable text",
    }

    if text in hard_meta_labels:
        return True

    if ("visible text" in src or "ocr" in src or "text db" in src) and len(tokens) <= 2:
        meta_tokens = {
            "text",
            "word",
            "words",
            "letter",
            "letters",
            "writing",
            "label",
            "labels",
            "caption",
        }

        if all(token in meta_tokens for token in tokens):
            return True

    weak_roots = {
        "object",
        "thing",
        "scene",
        "view",
        "detail",
        "details",
        "background",
        "foreground",
        "closeup",
        "close",
    }

    if len(tokens) == 1 and tokens[0] in weak_roots:
        return True

    return False


def _amir_subject_vote_key(value: object) -> str:
    text = _amir_subject_normalize_for_vote(value)

    singulars = []

    for token in text.split():
        if len(token) > 4 and token.endswith("ies"):
            singulars.append(token[:-3] + "y")
        elif len(token) > 3 and token.endswith("s"):
            singulars.append(token[:-1])
        else:
            singulars.append(token)

    return " ".join(singulars).strip()


def _amir_subject_majority_fallback(existing: object, rows: list[dict], subjects: list[str]) -> str:
    from collections import Counter
    import math

    current = str(existing or "").strip()

    if current:
        return current

    vote_counts = Counter()
    display_by_key: dict[str, str] = {}

    for row in rows or []:
        try:
            subject = row.get("subject")
            source = row.get("source", "")
        except Exception:
            continue

        if _amir_subject_meta_label_leak(subject, source):
            continue

        clean_subject = str(subject or "").strip()
        key = _amir_subject_vote_key(clean_subject)

        if not key:
            continue

        vote_counts[key] += 1
        display_by_key.setdefault(key, clean_subject)

    if not vote_counts:
        for subject in subjects or []:
            if _amir_subject_meta_label_leak(subject, ""):
                continue

            key = _amir_subject_vote_key(subject)

            if not key:
                continue

            vote_counts[key] += 1
            display_by_key.setdefault(key, str(subject).strip())

    if not vote_counts:
        return ""

    top_key, top_count = vote_counts.most_common(1)[0]
    total = sum(vote_counts.values())
    needed = max(2, math.ceil(total * 0.60))

    if top_count >= needed:
        return display_by_key.get(top_key, "").strip()

    return ""
# AMIR_SUBJECT_META_LABEL_OUTLIER_FIX_END

import argparse
import base64
import hashlib
import io
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}

def _amir_project_root_is_valid(path: Path) -> bool:
    return (
        (path / "main_set.py").exists()
        or (path / "data" / "review.db").exists()
        or (path / "data" / "location_list.json").exists()
    )


def _find_project_root() -> Path:
    here = Path(__file__).resolve()
    candidates: list[Path] = []

    for env_name in ["AMIR_PROJECT_ROOT", "PROJECT_ROOT"]:
        value = os.getenv(env_name, "").strip()

        if value:
            candidates.append(Path(value))

    data_dir = os.getenv("DATA_DIR", "").strip()

    if data_dir:
        candidates.append(Path(data_dir).parent)

    try:
        import amir2000_config as cfg  # type: ignore

        paths = getattr(cfg, "PATHS", {})

        if isinstance(paths, dict):
            cfg_data = str(paths.get("DATA_DIR") or "").strip()

            if cfg_data:
                candidates.append(Path(cfg_data).parent)
    except Exception:
        pass

    try:
        exe_dir = Path(sys.executable).resolve().parent
        candidates.extend([exe_dir, exe_dir.parent])
    except Exception:
        pass

    try:
        cwd = Path.cwd().resolve()
        candidates.extend([cwd, cwd.parent])
    except Exception:
        pass

    for candidate in candidates:
        try:
            if _amir_project_root_is_valid(candidate):
                return candidate.resolve()
        except Exception:
            continue

    for parent in [here.parent, *here.parents]:
        if _amir_project_root_is_valid(parent):
            return parent

    return here.parents[1]


PROJECT_ROOT = _find_project_root()
DATA_DIR = PROJECT_ROOT / "data"
RESULTS_DB = DATA_DIR / "identifier_results.db"
LABEL_BANK_DB = DATA_DIR / "identifier_label_bank.db"
REVAMP_KNOWLEDGE_DB = DATA_DIR / "revamp_knowledge.db"
PHOTOS_INFO_DB = DATA_DIR / "photos_info_revamp.db"

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
PRIMARY_MODEL = os.getenv("OLLAMA_MODEL_SUBJECT", "qwen2.5vl:7b").strip()
FALLBACK_MODEL = os.getenv("OLLAMA_MODEL_SUBJECT_FALLBACK", "llama3.2-vision:latest").strip()
EXTRA_MODELS_ENV = os.getenv(
    "SUBJECT_IDENTIFIER_EXTRA_MODELS",
    "llama3.2-vision:11b,qwen2.5vl:32b,llava:34b,minicpm-v:latest",
)
MAX_IMAGES = max(1, int(os.getenv("SUBJECT_IDENTIFIER_MAX_IMAGES", "12")))
MAX_SIDE = max(768, int(os.getenv("SUBJECT_IDENTIFIER_MAX_SIDE", "1280")))
JPEG_QUALITY = max(70, min(95, int(os.getenv("SUBJECT_IDENTIFIER_JPEG_QUALITY", "88"))))
TIMEOUT = max(60, int(os.getenv("SUBJECT_IDENTIFIER_TIMEOUT", "240")))
MIN_ACCEPT_SCORE = max(35, min(95, int(os.getenv("SUBJECT_IDENTIFIER_MIN_SCORE", "62"))))
KEEP_GOING_SCORE = max(MIN_ACCEPT_SCORE, min(100, int(os.getenv("SUBJECT_IDENTIFIER_KEEP_GOING_SCORE", "82"))))
MAX_MODEL_ATTEMPTS_PER_IMAGE = max(1, int(os.getenv("SUBJECT_IDENTIFIER_MAX_MODEL_ATTEMPTS", "6")))
SAVE_RESULTS = os.getenv("SUBJECT_IDENTIFIER_SAVE_RESULTS", "1") == "1"


GENERIC_EXACT = {
    "",
    "unknown",
    "none",
    "other",
    "object",
    "subject",
    "scene",
    "photo",
    "image",
    "picture",
    "photograph",
    "photography",
    "nature",
    "wildlife",
    "animal",
    "animals",
    "mammal",
    "mammals",
    "bird",
    "birds",
    "waterfowl",
    "plant",
    "plants",
    "flower",
    "flowers",
    "tree",
    "trees",
    "insect",
    "insects",
    "bug",
    "bugs",
    "vehicle",
    "vehicles",
    "car",
    "truck",
    "boat",
    "ship",
    "aircraft",
    "airplane",
    "plane",
    "building",
    "architecture",
    "landscape",
    "cityscape",
    "street scene",
    "urban scene",
    "outdoor scene",
    "natural landscape",
    "canal scene",
    "water scene",
}

# Broad roots are not rejected automatically. They are rejected only when the
# output is a lazy category or color plus category, for example Dark Horse.
BROAD_ROOTS = {
    "animal",
    "mammal",
    "bird",
    "waterfowl",
    "plant",
    "flower",
    "tree",
    "insect",
    "vehicle",
    "car",
    "truck",
    "boat",
    "ship",
    "aircraft",
    "airplane",
    "plane",
    "building",
    "architecture",
    "landscape",
    "cityscape",
    "person",
    "people",
    "dog",
    "cat",
    "horse",
}

COLOR_WORDS = {
    "black",
    "white",
    "brown",
    "grey",
    "gray",
    "red",
    "orange",
    "chestnut",
    "rufous",
    "russet",
    "yellow",
    "green",
    "blue",
    "purple",
    "pink",
    "dark",
    "light",
    "pale",
    "cream",
    "tan",
    "beige",
    "golden",
    "silver",
}

QUANTITY_WORDS = {
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "pair",
    "group",
    "several",
    "many",
}

ACTION_WORDS = {
    "landing",
    "flying",
    "perched",
    "grazing",
    "feeding",
    "swimming",
    "floating",
    "resting",
    "standing",
    "walking",
    "running",
    "sitting",
    "blooming",
    "approaching",
    "takeoff",
    "taxiing",
    "parked",
    "moored",
    "reflected",
    "reflection",
    "silhouette",
    "sunset",
    "dawn",
    "night",
}

LOCATION_NOISE = {
    "amsterdam",
    "netherlands",
    "nederland",
    "holland",
    "noord",
    "zuid",
    "israel",
    "usa",
    "united",
    "states",
    "arizona",
    "colorado",
    "california",
    "scotland",
    "england",
    "london",
    "zandvoort",
    "tel",
    "aviv",
}

GEAR_NOISE = {
    "canon",
    "eos",
    "r5",
    "r5m2",
    "mark",
    "ii",
    "iii",
    "rf",
    "ef",
    "lens",
    "iso",
    "aperture",
}

SUBJECT_NOISE_PHRASES = {
    "close up",
    "close-up",
    "close view",
    "wide view",
    "side view",
    "front view",
    "rear view",
    "view of",
    "visible subject",
    "answer answer",
    "main subject",
    "photographic subject",
    "outdoor scene",
    "natural scene",
    "nature scene",
    "urban scene",
    "water scene",
}

SCHEMA_ARTIFACT_PHRASES = {
    "subject text",
    "subject type",
    "specific name",
    "descriptive subject",
    "primary focus reason",
    "visible traits",
    "visible text",
    "keywords seed",
    "open label",
    "not restricted",
    "type specific",
    "type animal",
    "type bird",
    "type flower",
    "type vehicle",
    "type aircraft",
    "type building",
    "type landscape",
    "type scene",
}

_SCHEMA_KEY_ALIASES = {
    "subjecttext": "subject_text",
    "subject": "subject_text",
    "bestsubject": "best_subject",
    "primarysubject": "primary_subject",
    "mainsubject": "main_subject",
    "subjecttype": "subject_type",
    "specificname": "specific_name",
    "specific": "specific_name",
    "descriptivesubject": "descriptive_subject",
    "descriptive": "descriptive_subject",
    "primaryfocusreason": "primary_focus_reason",
    "evidence": "primary_focus_reason",
    "visibletraits": "visible_traits",
    "actionorstate": "action_or_state",
    "actionstate": "action_or_state",
    "setting": "setting",
    "visibletext": "visible_text",
    "confidence": "confidence",
    "alternatives": "alternatives",
    "keywordsseed": "keywords_seed",
    "keywords": "keywords_seed",
    "name": "name",
    "why": "why",
    "model": "_model",
    "phase": "_phase",
}

_DB_CACHE: dict[str, dict[str, Any]] = {}


@dataclass
class Candidate:
    label: str
    score: float
    source: str
    model: str
    image_name: str
    confidence: int = 0
    subject_type: str = ""
    evidence: str = ""
    db_match: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class SubjectSuggestion:
    subject: str = ""
    confidence: int = 0
    category: str = ""
    error: str = ""
    details: dict[str, Any] | None = None


def log(message: str) -> None:
    print(message, flush=True)


def clean_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\u00a0", " ").replace("_", " ")
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().strip('"').strip("'").strip(" ,.;:")


def raw_response_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\u00a0", " ")
    return text.strip()


def schema_key(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9]+", "", text).lower()
    return text


def normalize_model_json(value: Any) -> Any:
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}

        for raw_key, raw_value in value.items():
            key = _SCHEMA_KEY_ALIASES.get(schema_key(raw_key), str(raw_key))
            normalized[key] = normalize_model_json(raw_value)

        return normalized

    if isinstance(value, list):
        return [normalize_model_json(item) for item in value]

    return value


def has_schema_artifact(value: Any) -> bool:
    key = norm_key(value)

    if not key:
        return False

    if re.search(r"\btext\b.+\btype\b", key):
        return True

    if re.search(r"\btype\b.+\bspecific\b", key):
        return True

    if re.search(r"\btype\b.+\bname\b", key):
        return True

    return any(phrase in key for phrase in SCHEMA_ARTIFACT_PHRASES)


def ascii_text(value: str) -> str:
    text = clean_text(value)
    text = text.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", text).strip()


def norm_key(value: Any) -> str:
    text = ascii_text(clean_text(value)).lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def word_tokens(value: Any) -> list[str]:
    return re.findall(r"[a-z0-9]+", norm_key(value))


def smart_title(value: str) -> str:
    text = ascii_text(value)

    if not text:
        return ""

    keep_upper = {
        "KLM",
        "NASA",
        "USA",
        "UK",
        "EU",
        "TUI",
        "SAS",
        "LOT",
        "ANA",
        "JAL",
        "UPS",
        "DHL",
        "ATC",
        "RAF",
    }

    small_words = {"and", "or", "of", "on", "in", "at", "with", "to", "for", "the"}
    words: list[str] = []

    for index, raw in enumerate(text.split()):
        token = raw.strip()

        if not token:
            continue

        upper = token.upper()
        lower = token.lower()

        if upper in keep_upper:
            words.append(upper)
            continue

        if re.fullmatch(r"[A-Z]{1,3}-?[A-Z0-9]{2,6}", upper) and any(ch.isdigit() for ch in upper):
            words.append(upper)
            continue

        if re.fullmatch(r"A\d{3}|B\d{3}|\d{3}|\d{3}-\d", upper):
            words.append(upper)
            continue

        if index > 0 and lower in small_words:
            words.append(lower)
            continue

        parts = token.split("-")
        title_parts = []

        for part in parts:
            if not part:
                continue
            part_upper = part.upper()
            part_lower = part.lower()

            if part_upper in keep_upper:
                title_parts.append(part_upper)
            elif re.fullmatch(r"[A-Z]{1,3}\d{2,4}|\d{2,4}[A-Z]?", part_upper):
                title_parts.append(part_upper)
            elif part_lower in small_words and title_parts:
                title_parts.append(part_lower)
            else:
                title_parts.append(part[:1].upper() + part[1:].lower())

        words.append("-".join(title_parts))

    return re.sub(r"\s+", " ", " ".join(words)).strip()


def strip_subject_noise(value: str) -> str:
    text = ascii_text(value)
    text = re.sub(r"\b(?:photo|image|picture|photograph|photography|subject|object)\b", " ", text, flags=re.I)

    for phrase in sorted(SUBJECT_NOISE_PHRASES, key=len, reverse=True):
        text = re.sub(rf"\b{re.escape(phrase)}\b", " ", text, flags=re.I)

    text = re.sub(r"\b(?:visible|main|primary|likely|possible|probably|maybe|unknown)\b", " ", text, flags=re.I)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" ,.;:")


def is_exact_generic(value: str) -> bool:
    key = norm_key(value)

    if key in GENERIC_EXACT:
        return True

    if key.endswith(" scene") and len(key.split()) <= 2:
        return True

    if key.startswith("unknown "):
        return True

    return False


def is_color_only_broad(value: str) -> bool:
    tokens = word_tokens(value)

    if len(tokens) < 2 or len(tokens) > 4:
        return False

    roots = [token for token in tokens if token in BROAD_ROOTS]

    if not roots:
        return False

    useful = [token for token in tokens if token not in COLOR_WORDS and token not in BROAD_ROOTS]

    return not useful


def has_specific_signal(value: str) -> bool:
    text = ascii_text(value)
    tokens = word_tokens(text)

    if not tokens:
        return False

    if any(token in ACTION_WORDS for token in tokens):
        return True

    if any(any(ch.isdigit() for ch in token) for token in text.split()):
        return True

    if len(tokens) >= 3:
        useful = [
            token
            for token in tokens
            if token not in COLOR_WORDS
            and token not in BROAD_ROOTS
        ]
        return len(useful) >= 1

    if len(tokens) == 2:
        useful = [
            token
            for token in tokens
            if token not in BROAD_ROOTS
            and token not in COLOR_WORDS
            and token not in ACTION_WORDS
            and token not in QUANTITY_WORDS
            and token not in LOCATION_NOISE
            and token not in GEAR_NOISE
        ]
        return bool(useful)

    if len(tokens) == 1 and tokens[0] not in BROAD_ROOTS:
        return True

    return False

def candidate_is_usable(value: str) -> tuple[bool, str]:
    text = strip_subject_noise(value)
    key = norm_key(text)

    if not key:
        return False, "empty"

    if len(key) < 3:
        return False, "too_short"

    tokens = key.split()

    if all(token in LOCATION_NOISE or token in GEAR_NOISE for token in tokens):
        return False, "noise_only"

    if all(token in QUANTITY_WORDS for token in tokens):
        return False, "quantity_only"

    if all(token in ACTION_WORDS for token in tokens):
        return False, "action_only"

    if is_exact_generic(key):
        return False, "generic_exact"

    if is_color_only_broad(key):
        return False, "color_only_broad"

    if len(tokens) == 1 and tokens[0] in BROAD_ROOTS:
        return False, "single_broad_root"

    if len(tokens) == 1 and tokens[0] in QUANTITY_WORDS:
        return False, "single_quantity"

    if not has_specific_signal(key):
        return False, "not_specific_enough"

    return True, "ok"



ERROR_LEAK_WORDS = {
    "abort",
    "aborted",
    "cannot",
    "empty",
    "error",
    "exception",
    "failed",
    "failure",
    "httperror",
    "http",
    "invalid",
    "missing",
    "model",
    "notfound",
    "request",
    "retry",
    "stderr",
    "traceback",
    "unable",
    "unsupported",
}


def subject_has_error_leak(value: Any) -> bool:
    raw = clean_text(value)

    if not raw:
        return False

    key = norm_key(raw)
    compact = key.replace(" ", "")

    if not key:
        return False

    phrases = [
        "http error",
        "model not found",
        "not found",
        "only supports one image",
        "more than one image",
        "ggml assert",
        "primary model failed",
        "fallback failed",
    ]

    if any(phrase in key for phrase in phrases):
        return True

    if any(word in compact for word in ["httperror", "traceback", "notfound"]):
        return True

    tokens = set(key.split())

    if tokens & ERROR_LEAK_WORDS:
        return True

    return False

def clean_subject_label(value: str, max_words: int = 8, max_chars: int = 70) -> str:
    if subject_has_error_leak(value):
        return ""

    text = strip_subject_noise(value)

    if subject_has_error_leak(text):
        return ""

    text = re.sub(r"\bbg\b", "background", text, flags=re.I)
    text = re.sub(r"\banswer\b", " ", text, flags=re.I)
    text = re.sub(r"[^A-Za-z0-9 '&/\-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" ,.;:")

    if not text:
        return ""

    words = text.split()

    if len(words) > max_words:
        words = words[:max_words]

    text = " ".join(words)

    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0].strip()

    return smart_title(text)



# Amir generic detail evidence upgrade.
# This is not a topic or subject patch. It gives the model crop evidence so
# small signs, markings, petals, insects, birds, vehicles, aircraft and labels
# have a fair chance before the subject resolver decides.
def identifier_detail_crop_paths(path: Path) -> list[Path]:
    from PIL import Image

    try:
        with Image.open(path) as image:
            image = image.convert("RGB")
            width, height = image.size

            if width < 900 or height < 700:
                return []

            digest = hashlib.sha1(str(path.resolve()).encode("utf-8", errors="replace")).hexdigest()[:16]
            crop_dir = DATA_DIR / "identifier_detail_tmp" / digest
            crop_dir.mkdir(parents=True, exist_ok=True)

            boxes: list[tuple[str, tuple[int, int, int, int]]] = []

            def add_box(name: str, left: float, top: float, right: float, bottom: float) -> None:
                l = max(0, min(width - 1, int(width * left)))
                t = max(0, min(height - 1, int(height * top)))
                r = max(l + 1, min(width, int(width * right)))
                b = max(t + 1, min(height, int(height * bottom)))

                if (r - l) >= 400 and (b - t) >= 300:
                    boxes.append((name, (l, t, r, b)))

            add_box("center", 0.18, 0.18, 0.82, 0.82)
            add_box("top", 0.00, 0.00, 1.00, 0.55)
            add_box("bottom", 0.00, 0.45, 1.00, 1.00)
            add_box("left", 0.00, 0.12, 0.58, 0.88)
            add_box("right", 0.42, 0.12, 1.00, 0.88)

            out: list[Path] = []

            for name, box in boxes:
                dst = crop_dir / f"{name}.jpg"
                crop = image.crop(box)
                crop.thumbnail((MAX_SIDE, MAX_SIDE))
                crop.save(dst, format="JPEG", quality=JPEG_QUALITY, optimize=True)
                out.append(dst)

            return out[:4]
    except Exception:
        return []


def image_payloads(path: Path) -> list[str]:
    payloads = [image_to_base64(path)]

    for crop_path in identifier_detail_crop_paths(path):
        try:
            payloads.append(image_to_base64(crop_path))
        except Exception:
            continue

    return payloads


_VISIBLE_TEXT_WORD_BLOCK = {
    "amsterdam",
    "netherlands",
    "nederland",
    "holland",
    "canon",
    "eos",
    "r5",
    "mark",
    "ii",
    "photo",
    "image",
    "picture",
    "photography",
    "visible",
    "text",
    "unknown",
    "none",
}


def visible_text_subject_candidate(visible_text: str) -> str:
    text = clean_text(visible_text)

    if not text:
        return ""

    chunks = re.split(r"[,;|/\\]+", text)
    candidates: list[str] = []

    for chunk in chunks:
        chunk = re.sub(r"[^A-Za-z0-9 '&-]+", " ", chunk)
        chunk = re.sub(r"\s+", " ", chunk).strip(" -_'\"")

        if not chunk:
            continue

        tokens = word_tokens(chunk)
        useful = [
            token
            for token in tokens
            if token not in _VISIBLE_TEXT_WORD_BLOCK
            and token not in LOCATION_NOISE
            and token not in GEAR_NOISE
        ]

        if len(useful) < 2:
            continue

        if len(useful) > 6:
            continue

        if all(token.isdigit() for token in useful):
            continue

        label = clean_subject_label(" ".join(useful), max_words=6, max_chars=55)

        if label:
            candidates.append(label)

    if not candidates:
        return ""

    candidates.sort(key=lambda item: (len(word_tokens(item)), len(item)), reverse=True)
    return candidates[0]


def identifier_analysis_image_paths(image_path: Path) -> list[tuple[str, Path]]:
    crop_limit = max(0, min(5, int(os.getenv("SUBJECT_IDENTIFIER_DETAIL_CROPS", "2"))))

    items: list[tuple[str, Path]] = [("full", image_path)]

    for crop_path in identifier_detail_crop_paths(image_path)[:crop_limit]:
        if crop_path.exists():
            items.append((crop_path.stem, crop_path))

    seen: set[str] = set()
    unique: list[tuple[str, Path]] = []

    for label, item_path in items:
        key = str(item_path.resolve()).lower()

        if key in seen:
            continue

        seen.add(key)
        unique.append((label, item_path))

    return unique

def image_to_base64(path: Path) -> str:
    from PIL import Image

    with Image.open(path) as image:
        image = image.convert("RGB")
        image.thumbnail((MAX_SIDE, MAX_SIDE))

        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)

    return base64.b64encode(buffer.getvalue()).decode("ascii")


def parse_json_from_text(text: str) -> dict[str, Any]:
    raw = raw_response_text(text)

    if not raw:
        return {}

    raw = re.sub(r"^```json\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"^```\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    raw = raw.strip()

    try:
        value = json.loads(raw)
        return normalize_model_json(value) if isinstance(value, dict) else {}
    except Exception:
        pass

    first = raw.find("{")
    last = raw.rfind("}")

    if first == -1 or last == -1 or last <= first:
        return {}

    try:
        value = json.loads(raw[first:last + 1])
        return normalize_model_json(value) if isinstance(value, dict) else {}
    except Exception:
        return {}


def normalize_confidence(value: Any, default: int = 0) -> int:
    try:
        confidence = float(value)
    except Exception:
        confidence = default

    if 0 < confidence <= 1:
        confidence *= 100

    return max(0, min(100, int(round(confidence))))


def _ollama_tags_url() -> str:
    if OLLAMA_URL.endswith("/api/generate"):
        return OLLAMA_URL[: -len("/api/generate")] + "/api/tags"

    return "http://127.0.0.1:11434/api/tags"


def installed_ollama_model_names() -> set[str]:
    try:
        request = urllib.request.Request(
            _ollama_tags_url(),
            headers={"Content-Type": "application/json"},
            method="GET",
        )

        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))

        models = payload.get("models", [])

        if not isinstance(models, list):
            return set()

        names: set[str] = set()

        for item in models:
            if not isinstance(item, dict):
                continue

            name = clean_text(item.get("name"))

            if name:
                names.add(name)

        return names
    except Exception as exc:
        log(f"[SUBJECT AI] warning | could not read ollama model list: {type(exc).__name__}: {exc}")
        return set()


def make_model_list():
    import os

    forced_model = os.getenv("AMIR_SUBJECT_FORCE_MODEL", "").strip()
    normal_model = os.getenv("AMIR_SUBJECT_NORMAL_MODEL", "qwen2.5vl:3b").strip()
    mode = os.getenv("AMIR_SUBJECT_MODEL_MODE", "").strip().lower()

    if forced_model:
        # Regenerate route.
        # This must win over every normal/default model path.
        requested = [
            forced_model,
            normal_model,
        ]
    elif mode == "regenerate_alt":
        requested = [
            "gemma3:4b",
            normal_model,
        ]
    else:
        requested = [
            normal_model,
        ]

    # Safety: 7b stays blocked unless manually enabled.
    if os.getenv("AMIR_ALLOW_QWEN_7B_SUBJECT", "").strip() == "1":
        requested.append("qwen2.5vl:7b")

    cleaned = []
    seen = set()

    for model in requested:
        model = str(model or "").strip()

        if not model or model in seen:
            continue

        seen.add(model)
        cleaned.append(model)

    return cleaned


def build_prompt(
    *,
    subject_hint: str,
    location_hint: str,
    folder_hint: str,
    phase: str,
    rejected: str = "",
    previous_traits: str = "",
) -> str:
    hint_block = f"""
Optional hints. Use them only as context. Never copy a hint as the answer unless the image supports it.
subject_hint: {subject_hint}
location_hint: {location_hint}
folder_hint: {folder_hint}
""".strip()

    reject_block = ""

    if rejected or previous_traits:
        reject_block = f"""
Previous weak answer was rejected: {rejected}
Visible evidence already mentioned: {previous_traits}
Now refine from the image itself. Do not return a broad fallback.
""".strip()

    return f"""
Return strict JSON only. No markdown. No explanation outside JSON.

You are an open world visual identifier for a photography upload workflow.
This is NOT a category classifier. Identify the best visible subject for a file name and upload subject.

{hint_block}

{reject_block}

Task:
1. Look at the full image and all detail crops.
2. Use crop evidence to read small signs, markings, labels, numbers, petals, insects, birds, vehicles, aircraft, architecture details and object details.
3. Decide the primary visible subject, not a background object.
3. Give the most specific safe subject supported by the image.
4. For species, breed, aircraft type, vehicle model, building type, flower, mushroom, insect, object, scene, or celestial subject, be as specific as the image supports.
4b. For birds, flowers, plants, insects, and animals, use visible traits such as bill color, wing shape, leg color, body pattern, petals, flower shape, insect markings, and habitat to choose the safest common species or common group name.
5. If exact species or model is uncertain, do NOT fall back to a bare category. Use a useful descriptive subject with visible action, setting, or trait.
6. Confidence should be lower when uncertain, but the subject must still be useful.
7. Do not invent unreadable text, location, species, model, or brand.
8. Return alternatives when several specific options are plausible.

Lazy answers that are not useful: animal, bird, waterfowl, dog, cat, horse, plant, flower, vehicle, aircraft, boat, building, landscape, scene, object.
Useful answers look like: Greylag Goose, Gull Landing On Wet Sand, Light Colored Horse Grazing, Fishing Boat At Sunset, Canal Boats With Reflections, Air Canada Boeing 787 Dreamliner, Gothic Church Tower, White Blossom Branches, Orange Mushroom On Wood, Moon In Night Sky.

JSON schema:
{{
  "subject_text": "best specific visible subject, including useful action or setting when it matters",
  "subject_type": "open label, not restricted",
  "visible_count": 1,
  "specific_name": "species, breed, model, object type, building type, flower or mushroom name if supported",
  "descriptive_subject": "safe descriptive subject including count, action, setting, or trait when useful",
  "group_subject": "plural or grouped subject when more than one main subject is visible",
  "primary_focus_reason": "why this is the main subject, not background",
  "visible_traits": ["short visible trait", "short visible trait", "short visible trait"],
  "action_or_state": "visible action or state",
  "setting": "short visible setting",
  "visible_text": "only text actually readable in the image",
  "confidence": 0,
  "alternatives": [
    {{"name":"specific alternative", "confidence":0, "why":"short visual reason"}},
    {{"name":"specific alternative", "confidence":0, "why":"short visual reason"}},
    {{"name":"specific alternative", "confidence":0, "why":"short visual reason"}}
  ],
  "keywords_seed": ["visual keyword", "visual keyword", "visual keyword"]
}}

phase: {phase}
""".strip()


def build_free_text_prompt(
    *,
    subject_hint: str,
    location_hint: str,
    folder_hint: str,
    rejected: str = "",
) -> str:
    return f"""
You are an open world visual identifier for a photography upload workflow.
Look at the image and return useful subject candidates.
Do not return a lazy category like bird, animal, flower, plane, boat, landscape, scene, object.
If exact species/model is uncertain, return a useful descriptive subject instead.
For birds, flowers, plants, insects, and animals, prefer the safest common species or common group name supported by visible traits.
Use optional hints only as context, never as the answer unless visible.
subject_hint: {subject_hint}
location_hint: {location_hint}
folder_hint: {folder_hint}
Rejected weak answer: {rejected}

Return plain text only in this exact format:
BEST: <best useful subject>
SPECIFIC: <species, breed, model, object type, building type, plant/mushroom/insect name if supported>
DESCRIPTIVE: <safe descriptive subject with visible action, setting, or trait>
VISIBLE_TEXT: <readable text in the image, empty if none>
TRAITS: <short visual traits separated by comma>
ALTERNATIVES: <up to three useful alternatives separated by semicolon>
""".strip()


def call_ollama_text(
    *,
    image_path: Path,
    model: str,
    subject_hint: str,
    location_hint: str,
    folder_hint: str,
    rejected: str = "",
) -> dict[str, Any]:
    prompt = build_free_text_prompt(
        subject_hint=subject_hint,
        location_hint=location_hint,
        folder_hint=folder_hint,
        rejected=rejected,
    )

    payload = {
        "model": model,
        "prompt": prompt,
        "images": [image_to_base64(image_path)],
        "stream": False,
        "options": {
            "temperature": 0.12,
            "num_ctx": 4096,
            "num_predict": 360,
            "top_p": 0.9,
            "repeat_penalty": 1.08,
        },
    }

    request = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        data = json.loads(response.read().decode("utf-8", errors="replace"))

    return {
        "_raw_response": data.get("response", ""),
        "_model": model,
        "_phase": "text_fallback",
    }


def call_ollama(
    *,
    image_path: Path,
    model: str,
    subject_hint: str,
    location_hint: str,
    folder_hint: str,
    phase: str,
    rejected: str = "",
    previous_traits: str = "",
) -> dict[str, Any]:
    prompt = build_prompt(
        subject_hint=subject_hint,
        location_hint=location_hint,
        folder_hint=folder_hint,
        phase=phase,
        rejected=rejected,
        previous_traits=previous_traits,
    )

    payload = {
        "model": model,
        "prompt": prompt,
        "images": [image_to_base64(image_path)],
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0.05 if phase == "normal" else 0.15,
            "num_ctx": 4096,
            "num_predict": 520,
            "top_p": 0.9,
            "repeat_penalty": 1.08,
        },
    }

    request = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        data = json.loads(response.read().decode("utf-8", errors="replace"))

    parsed = parse_json_from_text(data.get("response", ""))
    parsed["_raw_response"] = data.get("response", "")
    parsed["_model"] = model
    parsed["_phase"] = phase
    return parsed


def sqlite_rows(db_path: Path, sql: str, params: tuple[Any, ...]) -> list[sqlite3.Row]:
    if not db_path.exists():
        return []

    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            return list(conn.execute(sql, params).fetchall())
    except Exception:
        return []


def db_lookup_exact(label: str) -> dict[str, Any]:
    key = norm_key(label)

    if not key:
        return {}

    if key in _DB_CACHE:
        return dict(_DB_CACHE[key])

    checks: list[tuple[Path, str, tuple[Any, ...], str]] = [
        (
            LABEL_BANK_DB,
            """
            SELECT label AS display_term, domain AS kind, label_rank AS rank, 'identifier_label_bank' AS source
            FROM identifier_labels
            WHERE allowed_for_filename = 1 AND (LOWER(label) = ? OR LOWER(latin_name) = ?)
            LIMIT 1
            """,
            (key, key),
            "identifier_label_bank",
        ),
        (
            REVAMP_KNOWLEDGE_DB,
            """
            SELECT term AS display_term, kind, notes AS rank, source
            FROM revamp_visual_terms
            WHERE normalized = ?
            ORDER BY weight DESC
            LIMIT 1
            """,
            (key,),
            "revamp_visual_terms",
        ),
        (
            REVAMP_KNOWLEDGE_DB,
            """
            SELECT display_term, best_kind AS kind, best_source AS source, score AS rank
            FROM revamp_candidate_terms
            WHERE normalized = ?
            ORDER BY score DESC
            LIMIT 1
            """,
            (key,),
            "revamp_candidate_terms",
        ),
        (
            REVAMP_KNOWLEDGE_DB,
            """
            SELECT term AS display_term, kind, source_table AS source, weight AS rank
            FROM mysql_terms
            WHERE normalized = ?
            ORDER BY weight DESC
            LIMIT 1
            """,
            (key,),
            "mysql_terms",
        ),
    ]

    for db_path, sql, params, source_name in checks:
        rows = sqlite_rows(db_path, sql, params)

        if not rows:
            continue

        row = rows[0]
        display = clean_subject_label(str(row["display_term"] or label))

        if not display:
            continue

        result = {
            "display": display,
            "kind": clean_text(row["kind"] if "kind" in row.keys() else ""),
            "rank": clean_text(row["rank"] if "rank" in row.keys() else ""),
            "source": clean_text(row["source"] if "source" in row.keys() else source_name),
        }
        _DB_CACHE[key] = result
        return dict(result)

    _DB_CACHE[key] = {}
    return {}


def db_lookup_from_visible_text(visible_text: str) -> list[dict[str, Any]]:
    text = norm_key(visible_text)

    if not text or len(text) < 3:
        return []

    hits: list[dict[str, Any]] = []

    # Exact visible operator/object words from your vocab, not a per-subject rule.
    for token_count in range(5, 0, -1):
        tokens = text.split()

        for start in range(0, max(0, len(tokens) - token_count + 1)):
            phrase = " ".join(tokens[start:start + token_count])
            match = db_lookup_exact(phrase)

            if match:
                hits.append(match)

        if hits:
            break

    seen = set()
    out = []

    for hit in hits:
        display = hit.get("display", "")

        if display and display.lower() not in seen:
            seen.add(display.lower())
            out.append(hit)

    return out[:5]


def db_lookup_phrase_hits(label: str) -> list[dict[str, Any]]:
    tokens = word_tokens(label)

    if not tokens:
        return []

    hits: list[dict[str, Any]] = []
    max_window = min(5, len(tokens))

    for token_count in range(max_window, 0, -1):
        for start in range(0, len(tokens) - token_count + 1):
            phrase = " ".join(tokens[start:start + token_count])

            phrase_tokens = phrase.split()

            if phrase in GENERIC_EXACT or phrase in LOCATION_NOISE or phrase in GEAR_NOISE:
                continue

            if all(token in QUANTITY_WORDS for token in phrase_tokens):
                continue

            if all(token in ACTION_WORDS for token in phrase_tokens):
                continue

            if all(token in {"a", "an", "and", "the", "in", "on", "of", "with", "at", "to", "for"} for token in phrase_tokens):
                continue

            match = db_lookup_exact(phrase)

            if match:
                hit = dict(match)
                hit["phrase"] = phrase
                hits.append(hit)

    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    for hit in hits:
        key = norm_key(hit.get("display") or hit.get("phrase"))

        if not key or key in seen:
            continue

        seen.add(key)
        out.append(hit)

    return out[:8]


def combine_parts(*parts: str) -> str:
    words: list[str] = []
    seen: set[str] = set()

    for part in parts:
        for word in clean_text(part).split():
            key = word.lower()

            if key in seen:
                continue

            seen.add(key)
            words.append(word)

    return " ".join(words)


def singular_token(token: str) -> str:
    token = norm_key(token)

    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"

    if token.endswith("ses") and len(token) > 4:
        return token[:-2]

    if token.endswith("s") and len(token) > 3:
        return token[:-1]

    return token


def token_root_set(value: str) -> set[str]:
    roots: set[str] = set()

    for token in word_tokens(value):
        roots.add(token)
        roots.add(singular_token(token))

    return {root for root in roots if root}


def specific_head_roots(value: str) -> set[str]:
    tokens = [token for token in word_tokens(value) if token not in COLOR_WORDS and token not in QUANTITY_WORDS]

    if not tokens:
        return set()

    head = tokens[-1]
    roots = {head, singular_token(head)}

    if len(tokens) >= 2:
        phrase = " ".join(tokens[-2:])
        roots.add(phrase)

    return {root for root in roots if root}


def label_matches_specific(label: str, specific: str) -> bool:
    label_roots = token_root_set(label)
    specific_roots = specific_head_roots(specific)

    if not label_roots or not specific_roots:
        return False

    if norm_key(specific) in norm_key(label):
        return True

    return bool(label_roots & specific_roots)


def label_has_action_or_quantity(label: str) -> bool:
    tokens = word_tokens(label)

    return any(token in ACTION_WORDS or token in QUANTITY_WORDS for token in tokens)


def contextual_specific_strength(label: str, raw: dict[str, Any]) -> int:
    specific = clean_text(raw.get("specific_name"))

    if not specific or not label_matches_specific(label, specific):
        return 0

    if label_has_action_or_quantity(label):
        return 2

    if norm_key(label) == norm_key(specific):
        return 1

    return 0


COUNT_WORDS = {
    1: "One",
    2: "Two",
    3: "Three",
    4: "Four",
    5: "Five",
    6: "Six",
    7: "Seven",
    8: "Eight",
    9: "Nine",
    10: "Ten",
}

WORD_COUNTS = {value.lower(): key for key, value in COUNT_WORDS.items()}
WORD_COUNTS.update({"pair": 2})

IRREGULAR_PLURALS = {
    "goose": "geese",
    "deer": "deer",
    "sheep": "sheep",
    "aircraft": "aircraft",
    "fish": "fish",
    "person": "people",
    "man": "men",
    "woman": "women",
    "mouse": "mice",
}


def parse_visible_count(value: Any) -> int:
    if value is None:
        return 0

    if isinstance(value, (int, float)):
        number = int(value)
        return number if 1 <= number <= 10 else 0

    text = norm_key(str(value))

    if text.isdigit():
        number = int(text)
        return number if 1 <= number <= 10 else 0

    for token in word_tokens(text):
        if token in WORD_COUNTS:
            return WORD_COUNTS[token]

    return 0


def infer_count_from_text(*values: str) -> int:
    for value in values:
        tokens = word_tokens(value)

        for token in tokens[:2]:
            if token in WORD_COUNTS:
                return WORD_COUNTS[token]

    return 0


def pluralize_last_word(value: str) -> str:
    words = clean_text(value).split()

    if not words:
        return ""

    last = words[-1]
    key = norm_key(last)

    if key in IRREGULAR_PLURALS:
        words[-1] = smart_title(IRREGULAR_PLURALS[key])
        return " ".join(words)

    if key.endswith("s"):
        return " ".join(words)

    if key.endswith("y") and len(key) > 2 and key[-2] not in "aeiou":
        words[-1] = last[:-1] + "ies"
    elif key.endswith(("ch", "sh", "x", "z")):
        words[-1] = last + "es"
    else:
        words[-1] = last + "s"

    return " ".join(words)


def action_phrase(action: str) -> str:
    action_key = norm_key(action)

    if not action_key:
        return ""

    if action_key in {"flying", "flight"}:
        return "in Flight"

    return smart_title(action)


def compose_context_subject(data: dict[str, Any]) -> str:
    specific = clean_subject_label(data.get("specific_name") or "")
    subject_text = clean_subject_label(data.get("subject_text") or "")
    descriptive = clean_subject_label(data.get("descriptive_subject") or "")
    group_subject = clean_subject_label(data.get("group_subject") or "")
    action = clean_text(data.get("action_or_state"))

    if not specific:
        return ""

    count = parse_visible_count(data.get("visible_count"))

    if not count:
        count = infer_count_from_text(group_subject, descriptive, subject_text)

    base = specific

    if count > 1:
        base = f"{COUNT_WORDS.get(count, str(count))} {pluralize_last_word(specific)}"

    phrase = action_phrase(action)

    if phrase and norm_key(phrase) not in norm_key(base):
        return clean_subject_label(f"{base} {phrase}", max_words=10, max_chars=80)

    if count > 1:
        return clean_subject_label(base, max_words=10, max_chars=80)

    return ""


def raw_response_candidate_texts(data: dict[str, Any]) -> list[tuple[str, str, int, str]]:
    raw = raw_response_text(data.get("_raw_response", ""))

    if not raw:
        return []

    confidence = normalize_confidence(data.get("confidence"), default=55)
    items: list[tuple[str, str, int, str]] = []

    # Mine JSON-like fragments only by explicit keys. Never turn the whole JSON
    # scaffold into a candidate subject.
    for key_name in ["subject_text", "specific_name", "descriptive_subject", "group_subject", "best_subject", "primary_subject", "main_subject", "name"]:
        for match in re.finditer(rf'"{key_name}"\s*:\s*"([^"]{{3,120}})"', raw, flags=re.I):
            value = clean_subject_label(match.group(1))

            if value and not has_schema_artifact(value):
                items.append((value, f"raw_{key_name}", confidence, "parsed from broken json"))

    # Plain text fallback has labelled lines. Use only labelled lines, not random prose.
    lines = [line.strip() for line in re.split(r"[\r\n]+", raw) if line.strip()]

    for line in lines:
        line = re.sub(r"^[-*•\s]*", "", line).strip()
        line = re.sub(r"^\d+[.)]\s*", "", line).strip()

        match = re.match(
            r"^(?:BEST|SUBJECT|SPECIFIC|DESCRIPTIVE|PRIMARY|MAIN|ALTERNATIVES)\s*[:=]\s*(.+)$",
            line,
            flags=re.I,
        )

        if not match:
            continue

        for value in re.split(r"\s*[;|]\s*", match.group(1)):
            value = clean_subject_label(value)

            if value and not has_schema_artifact(value):
                items.append((value, "raw_text", confidence, "parsed from labelled plain text response"))

    unique: list[tuple[str, str, int, str]] = []
    seen: set[str] = set()

    for label, source, conf, evidence in items:
        key = norm_key(label)

        if not key or key in seen:
            continue

        seen.add(key)
        unique.append((label, source, conf, evidence))

    return unique[:12]


def candidate_texts_from_json(data: dict[str, Any]) -> list[tuple[str, str, int, str]]:
    data = normalize_model_json(data)

    if norm_key(data.get("subject_type")) == "error":
        return []

    if subject_has_error_leak(data.get("subject_text")):
        data["subject_text"] = ""

    if subject_has_error_leak(data.get("specific_name")):
        data["specific_name"] = ""

    if subject_has_error_leak(data.get("descriptive_subject")):
        data["descriptive_subject"] = ""

    if subject_has_error_leak(data.get("group_subject")):
        data["group_subject"] = ""

    confidence = normalize_confidence(data.get("confidence"), default=50)
    evidence = clean_text(data.get("primary_focus_reason") or data.get("evidence"))

    raw_items: list[tuple[str, str, int, str]] = []

    context_subject = compose_context_subject(data)

    if context_subject:
        raw_items.append((context_subject, "specific_context", confidence, evidence))

    # Structured model fields first. These must beat raw-text mining.
    for key_name in ["subject_text", "specific_name", "descriptive_subject", "group_subject", "best_subject", "primary_subject", "main_subject"]:
        value = clean_text(data.get(key_name))

        if value:
            raw_items.append((value, key_name, confidence, evidence))

    specific_name = clean_text(data.get("specific_name"))
    action = clean_text(data.get("action_or_state"))
    setting = clean_text(data.get("setting"))
    descriptive = clean_text(data.get("descriptive_subject"))
    subject_text = clean_text(data.get("subject_text"))

    for base in [specific_name, subject_text, descriptive]:
        if base and action and len(word_tokens(base)) <= 5:
            raw_items.append((combine_parts(base, action), "base_plus_action", confidence, evidence))

        if base and setting and len(word_tokens(base)) <= 4:
            raw_items.append((combine_parts(base, setting), "base_plus_setting", confidence, evidence))

    alternatives = data.get("alternatives")

    if isinstance(alternatives, list):
        for item in alternatives:
            if not isinstance(item, dict):
                continue

            item = normalize_model_json(item)
            name = clean_text(item.get("name"))
            alt_conf = normalize_confidence(item.get("confidence"), default=max(35, confidence - 10))
            why = clean_text(item.get("why"))

            if name:
                raw_items.append((name, "alternative", alt_conf, why))

    visible_text = clean_text(data.get("visible_text"))

    visible_label = visible_text_subject_candidate(visible_text)

    if visible_label:
        raw_items.append((visible_label, "visible_text_label", max(confidence, 74), "readable visible text or object marking"))

    for hit in db_lookup_from_visible_text(visible_text):
        display = clean_text(hit.get("display"))

        if display:
            raw_items.append((display, "visible_text_untrusted_context", max(confidence, 72), "visible text matched local vocabulary"))

    # Only mine the raw response when structured fields produced nothing, or when
    # this is the explicit plain-text fallback call.
    structured_sources = {
        "subject_text",
        "specific_name",
        "specific_context",
        "descriptive_subject",
        "best_subject",
        "primary_subject",
        "main_subject",
        "base_plus_action",
        "base_plus_setting",
        "alternative",
        "visible_text_untrusted_context",
        "visible_text_label",
    }
    has_structured = any(source in structured_sources for _label, source, _conf, _why in raw_items)

    if not has_structured or clean_text(data.get("_phase")) == "text_fallback":
        raw_items.extend(raw_response_candidate_texts(data))

    unique: list[tuple[str, str, int, str]] = []
    seen: set[str] = set()

    for label, source, conf, why in raw_items:
        clean = clean_subject_label(label)
        key = norm_key(clean)

        if not clean or key in seen or has_schema_artifact(clean) or subject_has_error_leak(clean):
            continue

        seen.add(key)
        unique.append((clean, source, conf, why))

    return unique


def score_candidate(
    *,
    label: str,
    source: str,
    confidence: int,
    model: str,
    image_name: str,
    subject_type: str,
    evidence: str,
    raw: dict[str, Any],
) -> Candidate | None:
    if has_schema_artifact(label) or subject_has_error_leak(label):
        return None

    clean = clean_subject_label(label)

    if not clean or has_schema_artifact(clean) or subject_has_error_leak(clean):
        return None

    key = norm_key(clean)
    tokens = word_tokens(clean)

    if not tokens:
        return None

    # Never accept scaffold leftovers or empty quantity/action fragments.
    if all(token in QUANTITY_WORDS for token in tokens):
        return None

    if all(token in ACTION_WORDS for token in tokens):
        return None

    if key in GENERIC_EXACT:
        return None

    db_match = db_lookup_exact(clean)
    db_hits = db_lookup_phrase_hits(clean)

    usable, reason = candidate_is_usable(clean)

    # One-word species/object names are valid when they come from the structured
    # specific field or match the local knowledge bank. This prevents Jackdaw,
    # Pigeon, Daffodil, Scania, Cessna, etc. from being thrown away just because
    # they are one token.
    if not usable:
        allow_single_specific = (
            reason == "not_specific_enough"
            and len(tokens) == 1
            and tokens[0] not in BROAD_ROOTS
            and tokens[0] not in COLOR_WORDS
            and tokens[0] not in ACTION_WORDS
            and tokens[0] not in QUANTITY_WORDS
            and (source == "specific_name" or bool(db_match) or bool(db_hits))
        )

        if not allow_single_specific:
            return None

    # Models often return confidence=0 or confidence=1. The confidence normalizer
    # already converts 0.8/1.0 to 80/100, so the score can trust specific fields.
    score = float(confidence)

    if confidence <= 0 and (has_specific_signal(clean) or db_match or source == "specific_name"):
        score = 52.0
    elif confidence < 35 and (has_specific_signal(clean) or db_match or source == "specific_name"):
        score = max(score, 48.0)

    if db_match:
        clean = clean_subject_label(db_match.get("display") or clean)
        score += 18

        rank = norm_key(db_match.get("rank", ""))
        kind = norm_key(db_match.get("kind", ""))

        if any(word in rank for word in ["species", "family", "genus", "object", "operator", "visual"]):
            score += 8

        if kind:
            score += 4

    if db_hits:
        score += min(24, 8 * len(db_hits))

        # Do not replace a good multi-word candidate with a noisy one-word
        # keyword-bank fragment like Two, Flying, Water, or In. Only normalize
        # when the DB hit is the same phrase, not a substring.
        if not db_match:
            best_hit_display = clean_subject_label(db_hits[0].get("display") or "")

            if best_hit_display and norm_key(best_hit_display) == norm_key(clean):
                clean = best_hit_display

    tokens = word_tokens(clean)

    if len(tokens) >= 2:
        score += 5

    if len(tokens) >= 3:
        score += 6

    if len(tokens) >= 4:
        score += 4

    if any(token in ACTION_WORDS for token in tokens):
        score += 10

    if any(any(ch.isdigit() for ch in token) for token in clean.split()):
        score += 10

    if source == "specific_context":
        score += 22
    elif source == "specific_name":
        score += 18
    elif source in {"visible_text_label"}:
        score += 16
    elif source in {"subject_text", "best_subject", "primary_subject", "main_subject", "visible_text_untrusted_context"}:
        score += 10
    elif source == "descriptive_subject":
        score += 6
    elif source.startswith("raw_"):
        score += 2

    if source == "raw_text":
        score -= 10

    if source == "alternative":
        score -= 1

    if is_color_only_broad(clean):
        return None

    if norm_key(clean) in GENERIC_EXACT:
        return None

    return Candidate(
        label=clean,
        score=max(0, min(100, score)),
        source=source,
        model=model,
        image_name=image_name,
        confidence=confidence,
        subject_type=subject_type,
        evidence=evidence,
        db_match=json.dumps(db_match, ensure_ascii=False) if db_match else "",
        raw=raw,
    )

def best_candidate_from_json(data: dict[str, Any], image_path: Path, model: str) -> Candidate | None:
    subject_type = clean_text(data.get("subject_type"))
    candidates: list[Candidate] = []

    for label, source, confidence, evidence in candidate_texts_from_json(data):
        candidate = score_candidate(
            label=label,
            source=source,
            confidence=confidence,
            model=model,
            image_name=image_path.name,
            subject_type=subject_type,
            evidence=evidence,
            raw=data,
        )

        if candidate is not None:
            candidates.append(candidate)

    if not candidates:
        return None

    source_priority = {
        "specific_context": 95,
        "specific_name": 90,
        "visible_text_untrusted_context": 86,
        "visible_text_label": 84,
        "subject_text": 70,
        "best_subject": 70,
        "primary_subject": 70,
        "main_subject": 70,
        "descriptive_subject": 60,
        "base_plus_action": 50,
        "base_plus_setting": 45,
        "alternative": 25,
        "raw_text": 10,
    }

    candidates.sort(
        key=lambda item: (
            item.score,
            contextual_specific_strength(item.label, item.raw),
            source_priority.get(item.source, 20),
            1 if item.db_match else 0,
            item.confidence,
            len(word_tokens(item.label)),
        ),
        reverse=True,
    )
    return candidates[0]


def describe_rejected_json(data: dict[str, Any]) -> tuple[str, str]:
    fields = []

    for key_name in ["subject_text", "specific_name", "descriptive_subject", "group_subject", "subject_type"]:
        value = clean_text(data.get(key_name))

        if value:
            fields.append(value)

    traits = data.get("visible_traits")

    if isinstance(traits, list):
        fields.extend(clean_text(item) for item in traits[:6] if clean_text(item))

    keywords = data.get("keywords_seed")

    if isinstance(keywords, list):
        fields.extend(clean_text(item) for item in keywords[:6] if clean_text(item))

    rejected = "; ".join(fields[:8])
    previous_traits = "; ".join(fields[2:10])
    return rejected, previous_traits


def analyze_one_image(
    image_path: Path,
    subject_hint: str,
    location_hint: str,
    folder_hint: str,
):
    """
    Robust subject analysis.

    Recovery ladder:
    1. qwen2.5vl:7b
    2. if runner crashes, stop model and retry qwen2.5vl:7b once
    3. qwen2.5vl:3b
    4. if runner crashes, stop model and retry qwen2.5vl:3b once

    No llama/minicpm final subject.
    No OCR / visible text final subject.
    """

    import re
    import subprocess
    import time

    def _norm(value):
        value = str(value or "").replace("_", " ").replace("-", " ").lower()
        value = re.sub(r"[^a-z0-9\s]", " ", value)
        value = re.sub(r"\s+", " ", value).strip()
        return value

    def _runner_dead(raw):
        reason = _norm(raw.get("primary_focus_reason", ""))

        dead_bits = [
            "http error 500",
            "httperror 500",
            "model runner has unexpectedly stopped",
            "resource limitation",
            "runner stopped",
            "server error",
        ]

        return any(bit in reason for bit in dead_bits)

    def _recover_model(model):
        try:
            log(f"[SUBJECT AI] recovery | stopping dead model runner: {model}")
        except Exception:
            pass

        try:
            subprocess.run(
                [
                    "ollama",
                    "stop",
                    model,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=20,
            )
        except Exception:
            pass

        time.sleep(2.0)

    def _candidate_is_safe(candidate):
        if candidate is None:
            return False

        label = _norm(getattr(candidate, "label", ""))
        source = _norm(getattr(candidate, "source", ""))

        if not label:
            return False

        blocked_source_bits = [
            "visible text",
            "ocr",
            "readable text",
            "text db",
            "text context",
            "untrusted context",
            "raw text",
        ]

        if any(bit in source for bit in blocked_source_bits):
            return False

        blocked_exact_labels = {
            "text",
            "visible text",
            "ocr text",
            "written text",
            "writing",
            "letter",
            "letters",
            "word",
            "words",
            "label",
            "labels",
            "caption",
            "object",
            "thing",
            "scene",
            "view",
            "detail",
            "details",
            "background",
            "foreground",
            "unknown",
            "blossom",
            "flower",
            "flowers",
            "plant",
            "plants",
            "bird",
            "birds",
            "animal",
            "animals",
            "boat",
            "person",
            "man",
            "woman",
            "building",
            "vehicle",
        }

        if label in blocked_exact_labels:
            return False

        useful_tokens = [
            token
            for token in label.split()
            if token not in {
                "in",
                "on",
                "of",
                "with",
                "and",
                "the",
                "a",
                "an",
            }
        ]

        if len(useful_tokens) < 2:
            return False

        return True

    def _call_subject_model(model, variant_label, analysis_path, retry_after_recovery=False):
        phase = "normal"

        log(
            "[SUBJECT AI] analyzing "
            f"{image_path.name} variant={variant_label} with {model} phase={phase}"
        )

        try:
            raw = call_ollama(
                image_path=analysis_path,
                model=model,
                subject_hint=subject_hint,
                location_hint=location_hint,
                folder_hint=folder_hint,
                phase=phase,
                rejected="",
                previous_traits="",
            )
        except Exception as exc:
            raw = {
                "subject_text": "",
                "subject_type": "error",
                "confidence": 0,
                "primary_focus_reason": f"{type(exc).__name__}: {exc}",
                "_raw_response": "",
                "_model": model,
                "_phase": phase,
            }

        raw["_variant"] = variant_label
        raw["_analysis_image"] = str(analysis_path)
        raw["_original_image"] = str(image_path)

        attempts.append(raw)

        if _runner_dead(raw):
            if not retry_after_recovery:
                _recover_model(model)

                return _call_subject_model(
                    model=model,
                    variant_label=variant_label,
                    analysis_path=analysis_path,
                    retry_after_recovery=True,
                )

            log(
                "[SUBJECT AI] rejected | qwen runner still failed after recovery | "
                f"{image_path.name} | model={model}"
            )
            return None

        candidate = best_candidate_from_json(raw, image_path, model)

        if candidate is None:
            reason = clean_text(raw.get("primary_focus_reason"))

            if len(reason) > 120:
                reason = reason[:120] + "..."

            log(
                "[SUBJECT AI] rejected | "
                f"{image_path.name} | variant={variant_label} | model={model} | phase={phase} | "
                f"subject={clean_text(raw.get('subject_text'))} | "
                f"specific={clean_text(raw.get('specific_name'))} | "
                f"descriptive={clean_text(raw.get('descriptive_subject'))} | "
                f"reason={reason}"
            )
            return None

        if not _candidate_is_safe(candidate):
            log(
                "[SUBJECT AI] rejected | unsafe subject candidate | "
                f"{image_path.name} | variant={variant_label} | {candidate.label} | "
                f"source={candidate.source} | model={model}"
            )
            return None

        log(
            "[SUBJECT AI] candidate | "
            f"{image_path.name} | variant={variant_label} | {candidate.label} | "
            f"score={candidate.score:.0f} | confidence={candidate.confidence} | "
            f"source={candidate.source} | model={model} | phase={phase}"
        )

        return candidate

    models = make_model_list()
    attempts = []

    if not models:
        return {
            "image": str(image_path),
            "image_name": image_path.name,
            "accepted": False,
            "subject": "",
            "category": "",
            "confidence": 0,
            "score": 0,
            "model": "",
            "source": "",
            "attempts": attempts,
            "notes": "No trusted Qwen subject model available.",
        }

    try:
        raw_variants = identifier_analysis_image_paths(image_path)
    except Exception:
        raw_variants = [
            (
                "full",
                image_path,
            )
        ]

    variants = []

    for variant_label, analysis_path in raw_variants:
        if variant_label in {
            "full",
            "center",
        }:
            variants.append(
                (
                    variant_label,
                    analysis_path,
                )
            )

    if not variants:
        variants = raw_variants[:1]

    variants = variants[:2]

    best = None

    for model in models:
        if not str(model).startswith("qwen2.5vl:"):
            continue

        for variant_label, analysis_path in variants:
            candidate = _call_subject_model(
                model=model,
                variant_label=variant_label,
                analysis_path=analysis_path,
            )

            if candidate is None:
                continue

            if best is None or candidate.score > best.score:
                best = candidate

            if candidate.score >= KEEP_GOING_SCORE:
                break

        if best is not None and best.score >= KEEP_GOING_SCORE:
            break

    if best is None or best.score < MIN_ACCEPT_SCORE:
        return {
            "image": str(image_path),
            "image_name": image_path.name,
            "accepted": False,
            "subject": "",
            "category": "",
            "confidence": 0,
            "score": 0,
            "model": "",
            "source": "",
            "attempts": attempts,
            "notes": "No safe visual subject after Qwen recovery ladder.",
        }

    log(
        f"[SUBJECT AI] accepted | {image_path.name} | {best.label} | "
        f"score={best.score:.0f} | confidence={best.confidence} | "
        f"source={best.source} | model={best.model}"
    )

    return {
        "image": str(image_path),
        "image_name": image_path.name,
        "accepted": True,
        "subject": best.label,
        "category": best.subject_type,
        "confidence": best.confidence,
        "score": int(round(best.score)),
        "model": best.model,
        "source": best.source,
        "evidence": best.evidence,
        "db_match": best.db_match,
        "attempts": attempts,
    }

def collect_images_from_folder(folder: Path) -> list[Path]:
    if not folder.exists():
        raise SystemExit(f"Folder does not exist: {folder}")

    return sorted(
        [
            path
            for path in folder.iterdir()
            if path.is_file() and path.suffix.lower() in IMAGE_EXTS
        ],
        key=lambda path: path.name.lower(),
    )


def choose_samples(paths: list[Path], max_images: int) -> list[Path]:
    if max_images <= 0 or len(paths) <= max_images:
        return paths

    if max_images == 1:
        return [paths[0]]

    last_index = len(paths) - 1
    indexes = {
        round(index * last_index / (max_images - 1))
        for index in range(max_images)
    }

    return [paths[index] for index in sorted(indexes)]


SET_RESOLVER_STOPWORDS = {
    "a",
    "an",
    "and",
    "the",
    "of",
    "on",
    "in",
    "at",
    "to",
    "for",
    "with",
    "by",
    "from",
    "near",
    "over",
    "under",
    "into",
    "is",
    "are",
    "was",
    "were",
    "be",
    "being",
    "been",
    "this",
    "that",
    "these",
    "those",
}

SET_RESOLVER_WEAK_WORDS = {
    "static",
    "still",
    "open",
    "closed",
    "background",
    "foreground",
    "blurred",
    "soft",
    "sharp",
    "close",
    "macro",
    "detail",
    "details",
    "outdoor",
    "indoors",
    "outside",
    "inside",
    "view",
    "scene",
    "scenery",
    "blooming",
    "blossoming",
}

SET_RESOLVER_HUMAN_BROAD_WORDS = {
    "man",
    "men",
    "woman",
    "women",
    "person",
    "people",
    "child",
    "children",
    "boy",
    "girl",
    "male",
    "female",
}



SET_RESOLVER_MASS_CONTEXT_WORDS = {
    "water",
    "sea",
    "ocean",
    "sky",
    "snow",
    "ice",
    "sand",
    "grass",
    "sunlight",
    "mist",
    "fog",
    "rain",
    "cloud",
    "clouds",
}


def is_human_scene_subject(label: str) -> bool:
    tokens = word_tokens(label)

    if not tokens:
        return False

    has_human = any(singular_token(token) in SET_RESOLVER_HUMAN_BROAD_WORDS for token in tokens)
    has_action = any(singular_token(token) in ACTION_WORDS for token in tokens)

    return has_human and has_action


def is_usable_set_subject(label: str) -> bool:
    if subject_core_root_list(label):
        return True

    if is_human_scene_subject(label):
        return True

    return False


def set_context_label(context_root: str) -> str:
    root = singular_token(context_root)

    if not root:
        return ""

    if root in SET_RESOLVER_MASS_CONTEXT_WORDS:
        return smart_title(root)

    return pluralize_last_word(smart_title(root))


def set_context_preposition(subject: str) -> str:
    if is_human_scene_subject(subject):
        return "By"

    return "On"

def set_resolver_skip_token(token: str) -> bool:
    root = singular_token(token)

    if not root:
        return True

    if root in SET_RESOLVER_STOPWORDS:
        return True

    if root in SET_RESOLVER_WEAK_WORDS:
        return True

    if root in COLOR_WORDS or root in QUANTITY_WORDS:
        return True

    if root in ACTION_WORDS:
        return True

    if root in BROAD_ROOTS or root in SET_RESOLVER_HUMAN_BROAD_WORDS:
        return True

    if root in LOCATION_NOISE or root in GEAR_NOISE:
        return True

    if root in GENERIC_EXACT:
        return True

    if root.endswith("ing") and len(root) > 5:
        return True

    return False


def subject_core_root_list(label: str) -> list[str]:
    roots: list[str] = []
    seen: set[str] = set()

    for token in word_tokens(label):
        root = singular_token(token)

        if set_resolver_skip_token(root):
            continue

        if root in seen:
            continue

        seen.add(root)
        roots.append(root)

    return roots


def subject_core_roots(label: str) -> set[str]:
    return set(subject_core_root_list(label))


def label_family_key(label: str) -> str:
    if is_human_scene_subject(label):
        for token in word_tokens(label):
            root = singular_token(token)

            if root in ACTION_WORDS:
                return root

        return "human_scene"

    roots = subject_core_root_list(label)

    if roots:
        return roots[-1]

    return ""

def subject_set_quality_score(label: str) -> tuple[int, int, int, int]:
    tokens = word_tokens(label)
    core_roots = subject_core_root_list(label)
    color_count = sum(1 for token in tokens if token in COLOR_WORDS)
    broad_count = sum(1 for token in tokens if token in BROAD_ROOTS)

    return (
        len(core_roots),
        color_count,
        len(tokens) - broad_count,
        len(clean_text(label)),
    )


def pluralize_set_subject(label: str, image_count: int) -> str:
    clean = clean_subject_label(label, max_words=10, max_chars=80)

    if image_count <= 1:
        return clean

    tokens = word_tokens(clean)

    if not tokens:
        return clean

    if any(token in QUANTITY_WORDS for token in tokens):
        return clean

    if tokens[-1].endswith("s"):
        return clean

    return clean_subject_label(pluralize_last_word(clean), max_words=10, max_chars=80)


def row_attempt_text_values(row: dict[str, Any]) -> list[str]:
    values: list[str] = []

    for attempt in row.get("attempts", []) or []:
        if not isinstance(attempt, dict):
            continue

        for key_name in [
            "subject_text",
            "specific_name",
            "descriptive_subject",
            "group_subject",
            "action_or_state",
            "setting",
            "primary_focus_reason",
        ]:
            value = clean_text(attempt.get(key_name))

            if value:
                values.append(value)

        for key_name in ["visible_traits", "keywords_seed"]:
            items = attempt.get(key_name)

            if isinstance(items, list):
                values.extend(clean_text(item) for item in items if clean_text(item))

    return values


def shared_context_root(rows: list[dict[str, Any]], subject: str) -> str:
    if not rows:
        return ""

    subject_roots = subject_core_roots(subject)
    support: Counter[str] = Counter()

    for row in rows:
        row_roots: set[str] = set()

        for value in row_attempt_text_values(row):
            for token in word_tokens(value):
                root = singular_token(token)

                if set_resolver_skip_token(root):
                    continue

                if root in subject_roots:
                    continue

                row_roots.add(root)

        support.update(row_roots)

    if not support:
        return ""

    needed = max(2, round(len(rows) * 0.50))

    for root, count in support.most_common(8):
        if count >= needed:
            return root

    return ""


def enhance_set_subject_with_context(subject: str, rows: list[dict[str, Any]]) -> str:
    clean = clean_subject_label(subject, max_words=10, max_chars=80)

    if not clean or not rows:
        return clean

    if any(token in {"on", "in", "at", "with", "near", "by"} for token in word_tokens(clean)):
        return clean

    context_root = shared_context_root(rows, clean)

    if not context_root:
        return clean

    context_label = set_context_label(context_root)

    if not context_label:
        return clean

    preposition = set_context_preposition(clean)
    candidate = clean_subject_label(f"{clean} {preposition} {context_label}", max_words=10, max_chars=80)

    if len(word_tokens(candidate)) <= 10:
        return candidate

    return clean

def compress_set_subject(subjects: list[str], rows: list[dict[str, Any]] | None = None) -> str:
    if not subjects:
        return ""

    rows = rows or []
    cleaned: list[str] = []
    seen: set[str] = set()

    for subject in subjects:
        clean = clean_subject_label(subject, max_words=10, max_chars=80)
        key = norm_key(clean)

        if not clean or not key or key in seen:
            continue

        seen.add(key)
        cleaned.append(clean)

    if not cleaned:
        return ""

    if len(cleaned) == 1:
        if not is_usable_set_subject(cleaned[0]):
            return ""

        subject = pluralize_set_subject(cleaned[0], len(subjects))
        return enhance_set_subject_with_context(subject, rows)

    specific_subjects = [item for item in cleaned if subject_core_root_list(item)]

    if not specific_subjects:
        return ""

    root_counts = Counter(label_family_key(item) for item in specific_subjects if label_family_key(item))

    if not root_counts:
        return ""

    root, support = root_counts.most_common(1)[0]
    matching = [item for item in specific_subjects if label_family_key(item) == root]
    incompatible_specific = [item for item in specific_subjects if label_family_key(item) != root]

    generic_compatible_count = len(cleaned) - len(specific_subjects)
    compatible_count = support + generic_compatible_count
    compatible_ratio = compatible_count / max(1, len(cleaned))
    direct_ratio = support / max(1, len(cleaned))

    if incompatible_specific and direct_ratio < 0.60:
        return ""

    if compatible_ratio < 0.55 and direct_ratio < 0.50:
        return ""

    best = max(matching, key=subject_set_quality_score)
    subject = pluralize_set_subject(best, len(subjects))
    return enhance_set_subject_with_context(subject, rows)


def combine_subjects(rows: list[dict[str, Any]]) -> SubjectSuggestion:
    accepted = [row for row in rows if row.get("accepted") and row.get("subject")]

    if not accepted:
        attempted = []

        for row in rows:
            for attempt in row.get("attempts", []) or []:
                for key_name in ["subject_text", "specific_name", "descriptive_subject", "group_subject", "subject_type"]:
                    value = clean_text(attempt.get(key_name))

                    if value:
                        attempted.append(value)

        attempted_counts = Counter(norm_key(item) for item in attempted if norm_key(item))
        error = "No reliable useful subject found after model retries."

        if attempted_counts:
            error += f" Rejected: {dict(attempted_counts.most_common(6))}"

        return SubjectSuggestion(
            subject="",
            confidence=0,
            category="",
            error=error,
            details={"rows": rows},
        )

    subject_counts = Counter(clean_text(row.get("subject")) for row in accepted)
    best_subject, best_count = subject_counts.most_common(1)[0]
    same_ratio = best_count / max(1, len(accepted))
    best_subject_clean = clean_subject_label(best_subject, max_words=10, max_chars=80)

    if same_ratio >= 0.55:
        best_rows = [row for row in accepted if clean_text(row.get("subject")).lower() == best_subject.lower()]
        confidence = max(int(row.get("confidence") or 0) for row in best_rows)
        score = max(int(row.get("score") or 0) for row in best_rows)
        category = clean_text(best_rows[0].get("category"))
        subject = pluralize_set_subject(best_subject_clean, len(accepted))
        subject = enhance_set_subject_with_context(subject, best_rows)

        return SubjectSuggestion(
            subject=subject,
            confidence=max(confidence, score),
            category=category,
            error="",
            details={"rows": rows, "mode": "exact_consensus"},
        )

    accepted = [
        row
        for row in accepted
        if not _amir_subject_meta_label_leak(row.get("subject"), row.get("source", ""))
    ]

    accepted = [
        row
        for row in accepted
        if _amir_subject_source_is_trusted(row)
    ]

    accepted = _amir_filter_subject_vote_rows(accepted)

    accepted = _amir_filter_subject_rows_v2(accepted)

    scored_subjects = sorted(
        accepted,
        key=lambda row: (int(row.get("score") or 0), int(row.get("confidence") or 0)),
        reverse=True,
    )
    scored_subjects = _amir_filter_subject_vote_rows(scored_subjects)
    subjects = [clean_text(row.get("subject")) for row in scored_subjects if clean_text(row.get("subject"))]
    scored_subjects = _amir_filter_subject_rows_v2(scored_subjects)
    subjects = [clean_text(row.get("subject")) for row in scored_subjects if clean_text(row.get("subject"))]
    compressed = compress_set_subject(subjects, rows=scored_subjects)
    compressed = _amir_subject_majority_fallback(compressed, scored_subjects, subjects)

    if compressed:
        confidence = max(int(row.get("score") or 0) for row in accepted)
        category_counts = Counter(clean_text(row.get("category")) for row in accepted if clean_text(row.get("category")))
        category = category_counts.most_common(1)[0][0] if category_counts else "mixed"

        return SubjectSuggestion(
            subject=compressed,
            confidence=confidence,
            category=category,
            error="",
            details={"rows": rows, "mode": "compatible_specific_consensus"},
        )

    return SubjectSuggestion(
        subject="",
        confidence=0,
        category="mixed_specific",
        error="Specific subjects conflict across selected images. Split the set or type the shared subject manually.",
        details={"rows": rows},
    )

def make_set_key(image_paths: list[str]) -> str:
    joined = "\n".join(sorted(str(Path(path).resolve()).lower() for path in image_paths))
    return hashlib.sha256(joined.encode("utf-8", errors="replace")).hexdigest()[:24]


def ensure_results_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(RESULTS_DB) as conn:
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


def save_results(
    *,
    set_key: str,
    all_paths: list[Path],
    sampled_paths: list[Path],
    rows: list[dict[str, Any]],
    result: SubjectSuggestion,
    subject_hint: str,
    location_hint: str,
    folder_hint: str,
) -> None:
    if not SAVE_RESULTS:
        return

    ensure_results_db()

    with sqlite3.connect(RESULTS_DB) as conn:
        for path, row in zip(sampled_paths, rows):
            conn.execute(
                """
                INSERT INTO identifier_image_results (
                    set_key,
                    image_path,
                    file_name,
                    detected_domain,
                    model_used,
                    top_candidates_json,
                    raw_result_json,
                    chosen_subject,
                    confidence,
                    rank_used,
                    needs_manual,
                    notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    set_key,
                    str(path),
                    path.name,
                    clean_text(row.get("category")),
                    clean_text(row.get("model")),
                    json.dumps([row.get("subject")], ensure_ascii=False),
                    json.dumps(row.get("attempts", []), ensure_ascii=False),
                    clean_text(row.get("subject")),
                    float(row.get("confidence") or 0),
                    clean_text(row.get("source")),
                    0 if row.get("accepted") else 1,
                    clean_text(row.get("notes")),
                ),
            )

        conn.execute(
            """
            INSERT INTO identifier_set_results (
                set_key,
                image_count,
                sampled_count,
                subject_hint,
                location_hint,
                folder_hint,
                detected_domain,
                final_subject_suggestion,
                confidence,
                rank_used,
                needs_manual,
                top_candidates_json,
                source_models_json,
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(set_key) DO UPDATE SET
                created_at = CURRENT_TIMESTAMP,
                image_count = excluded.image_count,
                sampled_count = excluded.sampled_count,
                subject_hint = excluded.subject_hint,
                location_hint = excluded.location_hint,
                folder_hint = excluded.folder_hint,
                detected_domain = excluded.detected_domain,
                final_subject_suggestion = excluded.final_subject_suggestion,
                confidence = excluded.confidence,
                rank_used = excluded.rank_used,
                needs_manual = excluded.needs_manual,
                top_candidates_json = excluded.top_candidates_json,
                source_models_json = excluded.source_models_json,
                notes = excluded.notes
            """,
            (
                set_key,
                len(all_paths),
                len(sampled_paths),
                subject_hint,
                location_hint,
                folder_hint,
                result.category,
                result.subject,
                float(result.confidence or 0),
                clean_text((result.details or {}).get("mode", "")),
                0 if result.subject else 1,
                json.dumps(result.details or {}, ensure_ascii=False),
                json.dumps(sorted({clean_text(row.get("model")) for row in rows if row.get("model")}), ensure_ascii=False),
                result.error,
            ),
        )


def _amir_identifier_reference_visual_text(rows, result, subject_hint="", folder_hint=""):
    parts = [
        subject_hint,
        folder_hint,
        str(getattr(result, "subject", "") or ""),
        str(getattr(result, "category", "") or ""),
        str(getattr(result, "error", "") or ""),
    ]

    details = getattr(result, "details", {}) or {}

    if isinstance(details, dict):
        for key in ("original_subject", "mode", "category"):
            value = details.get(key)
            if value:
                parts.append(str(value))

    for row in rows or []:
        if not isinstance(row, dict):
            continue

        for key in (
            "subject",
            "specific",
            "descriptive",
            "category",
            "evidence",
            "reason",
            "raw",
            "raw_response",
            "cleaned",
        ):
            value = row.get(key)

            if not value:
                continue

            if isinstance(value, (dict, list, tuple)):
                try:
                    value = json.dumps(value, ensure_ascii=True)
                except Exception:
                    value = str(value)

            parts.append(str(value))

    return clean_text(" ".join(part for part in parts if part))[:4000]


def _amir_identifier_reference_context_is_biological(rows, result) -> bool:
    parts = [
        str(getattr(result, "subject", "") or ""),
        str(getattr(result, "category", "") or ""),
        str(getattr(result, "error", "") or ""),
    ]

    for row in rows or []:
        if not isinstance(row, dict):
            continue

        for key in [
            "subject",
            "specific",
            "descriptive",
            "category",
            "evidence",
            "reason",
            "notes",
        ]:
            value = row.get(key)

            if value:
                parts.append(str(value))

    tokens = set(re.findall(r"[a-z0-9]+", clean_text(" ".join(parts)).lower()))
    biological_triggers = {
        "animal",
        "animals",
        "bird",
        "birds",
        "flower",
        "flowers",
        "fungi",
        "fungus",
        "insect",
        "insects",
        "leaf",
        "leaves",
        "mammal",
        "mammals",
        "mushroom",
        "mushrooms",
        "plant",
        "plants",
        "spike",
        "stalk",
        "stalks",
        "stem",
        "stems",
        "tree",
        "trees",
        "wildflower",
        "wildflowers",
    }

    return bool(tokens & biological_triggers)


def _amir_identifier_reference_needed(rows, result):
    if not _amir_subject_identifier_mode():
        return False

    subject = str(getattr(result, "subject", "") or "")
    category = str(getattr(result, "category", "") or "")
    error = str(getattr(result, "error", "") or "")

    if not subject or error or category in {"underidentified_taxon", "identify_insufficient_set_support"}:
        return True

    # Strict Identify is the slow, high-confidence path. Always let the
    # reference verifier inspect the final set answer; it cheaply exits when
    # the set is not biological, and prevents set-group synthesis from
    # becoming the final taxon without evidence.
    return True

    if _amir_identifier_reference_context_is_biological(rows, result):
        return True

    checks = (
        "_amir_subject_underidentified_taxon",
        "_amir_taxon_is_group_label",
        "_amir_taxon_is_broad",
    )

    for name in checks:
        try:
            checker = globals().get(name)
            if checker and checker(subject):
                return True
        except Exception:
            continue

    accepted = [
        row
        for row in rows or []
        if isinstance(row, dict) and row.get("accepted") and clean_text(row.get("subject"))
    ]

    if len(accepted) >= 2:
        specific_hits = 0

        for row in accepted:
            row_subject = clean_text(row.get("subject"))
            try:
                if not _amir_subject_underidentified_taxon(row_subject):
                    specific_hits += 1
            except Exception:
                pass

        if specific_hits <= 0:
            return True

    return False


def _amir_identifier_reference_subject(paths, rows, result, *, subject_hint="", location_hint="", folder_hint=""):
    if not _amir_identifier_reference_needed(rows, result):
        return None

    try:
        from scripts.identifier_biology_inaturalist import identify_biology_reference_set
    except Exception as exc:
        try:
            log(f"[SUBJECT AI IDENTIFY] reference unavailable | error={exc}")
        except Exception:
            pass
        return None

    visual_text = _amir_identifier_reference_visual_text(
        rows,
        result,
        subject_hint=subject_hint,
        folder_hint=folder_hint,
    )

    try:
        reference = identify_biology_reference_set(
            [str(path) for path in paths],
            location=location_hint,
            folder=folder_hint,
            subject_hint=subject_hint,
            visual_text=visual_text,
            max_samples=min(6, max(1, len(paths or []))),
        )
    except Exception as exc:
        try:
            log(f"[SUBJECT AI IDENTIFY] reference failed | error={exc}")
        except Exception:
            pass
        return None

    if not isinstance(reference, dict) or not reference.get("ok"):
        try:
            error_text = str((reference or {}).get("error", "")) if isinstance(reference, dict) else "invalid result"
            log(
                "[SUBJECT AI IDENTIFY] reference no decision "
                f"| current={str(getattr(result, 'subject', '') or '')!r} | error={error_text} "
                f"| mode={str((reference or {}).get('mode', '')) if isinstance(reference, dict) else ''} "
                f"| month={str((reference or {}).get('month', '')) if isinstance(reference, dict) else ''} "
                f"| recovered={str((reference or {}).get('recovered_original_count', '')) if isinstance(reference, dict) else ''}"
            )
        except Exception:
            pass
        return None

    confidence = int(reference.get("confidence") or 0)
    accept_confidence = int(os.getenv("AMIR_IDENTIFIER_INAT_ACCEPT_CONFIDENCE", "70") or "70")

    if confidence < accept_confidence:
        try:
            log(
                "[SUBJECT AI IDENTIFY] reference below confidence "
                f"| subject={str(reference.get('subject') or '')!r} | confidence={confidence}"
            )
        except Exception:
            pass
        return None

    subject = clean_text(reference.get("subject"))

    if not subject:
        return None

    try:
        log(
            "[SUBJECT AI IDENTIFY] reference accepted "
            f"| subject={subject!r} | confidence={confidence} "
            f"| scientific={str(reference.get('scientific') or '')!r} "
            f"| avg={float(reference.get('average_similarity') or 0.0):.3f} "
            f"| min={float(reference.get('minimum_similarity') or 0.0):.3f} "
            f"| margin={float(reference.get('margin') or 0.0):.3f} "
            f"| mode={str(reference.get('mode') or '')} "
            f"| month={str(reference.get('month') or '')} "
            f"| recovered={str(reference.get('recovered_original_count') or 0)} "
            f"| delegated={str(reference.get('delegated_to_venv') or False)}"
        )
    except Exception:
        pass

    details = getattr(result, "details", {}) or {}
    if not isinstance(details, dict):
        details = {}

    details = dict(details)
    details.update(
        {
            "rows": rows,
            "mode": "identify_biology_reference",
            "original_subject": str(getattr(result, "subject", "") or ""),
            "reference": reference,
        }
    )

    return SubjectSuggestion(
        subject=subject,
        confidence=confidence,
        category=str(reference.get("category") or "biology_reference"),
        error="",
        details=details,
    )


def suggest_subject_multi(
    image_paths: list[str],
    *,
    location_hint: str = "",
    folder_hint: str = "",
    subject_hint: str = "",
) -> SubjectSuggestion:
    paths = [
        Path(path)
        for path in image_paths or []
        if path and Path(path).is_file() and Path(path).suffix.lower() in IMAGE_EXTS
    ]

    if not paths:
        return SubjectSuggestion(
            subject="",
            confidence=0,
            category="",
            error="No valid image files selected.",
            details={"rows": []},
        )

    sample_paths = choose_samples(paths, MAX_IMAGES)
    models = make_model_list()

    log(
        f"[SUBJECT AI] start | selected={len(paths)} | samples={len(sample_paths)} | "
        f"models={', '.join(models)} | source=subject_identifier_production_v17_context_subject_identifier_json_db_identifier"
    )
    log(
        f"[SUBJECT AI] db | results={RESULTS_DB.exists()} | label_bank={LABEL_BANK_DB.exists()} | "
        f"knowledge={REVAMP_KNOWLEDGE_DB.exists()}"
    )

    start_time = time.time()
    rows: list[dict[str, Any]] = []

    for index, path in enumerate(sample_paths, start=1):
        elapsed = int(time.time() - start_time)
        log(f"[SUBJECT AI] sample {index}/{len(sample_paths)} | elapsed={elapsed}s | {path.name}")

        row = analyze_one_image(
            image_path=path,
            subject_hint=subject_hint,
            location_hint=location_hint,
            folder_hint=folder_hint,
        )
        rows.append(row)

    result = combine_subjects(rows)
    set_key = make_set_key([str(path) for path in paths])

    try:
        save_results(
            set_key=set_key,
            all_paths=paths,
            sampled_paths=sample_paths,
            rows=rows,
            result=result,
            subject_hint=subject_hint,
            location_hint=location_hint,
            folder_hint=folder_hint,
        )
    except Exception as exc:
        log(f"[SUBJECT AI] warn | could not save identifier_results.db | {type(exc).__name__}: {exc}")

    if result.subject:
        log(
            f"[SUBJECT AI] result | subject={result.subject} | "
            f"confidence={result.confidence} | category={result.category}"
        )
    else:
        log(f"[SUBJECT AI] result | needs_manual | {result.error}")

    return result


# AMIR_EVIDENCE_SUBJECT_RESOLVER_HOOK_START
# Generic evidence subject resolver.
# No per subject rules. No per topic rules. It only repairs voting and consensus.
try:
    _amir_original_combine_subjects_evidence = combine_subjects

    def combine_subjects(rows):
        original = _amir_original_combine_subjects_evidence(rows)

        try:
            from scripts.evidence_subject_pipeline import resolve_subject_from_rows

            resolved = resolve_subject_from_rows(rows, original)

            if resolved and resolved.get("subject"):
                return SubjectSuggestion(
                    subject=resolved.get("subject", ""),
                    confidence=int(resolved.get("confidence", 0) or 0),
                    category=resolved.get("category", "evidence_consensus"),
                    error="",
                    details={
                        "rows": rows,
                        "mode": resolved.get("mode", "evidence_consensus"),
                        "original": getattr(original, "details", None),
                    },
                )
        except Exception as _amir_subject_resolver_error:
            try:
                log(f"[SUBJECT AI] warn | evidence subject resolver failed | {_amir_subject_resolver_error}")
            except Exception:
                pass

        return original
except NameError:
    pass
# AMIR_EVIDENCE_SUBJECT_RESOLVER_HOOK_END

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", default="")
    parser.add_argument("--images", nargs="*", default=[])
    parser.add_argument("--subject-hint", default="")
    parser.add_argument("--location-hint", default="")
    parser.add_argument("--folder-hint", default="")
    parser.add_argument("--print-json", action="store_true")

    args = parser.parse_args()

    image_paths: list[Path] = []

    if args.folder:
        image_paths.extend(collect_images_from_folder(Path(args.folder)))

    for raw_path in args.images:
        path = Path(raw_path)

        if path.is_file() and path.suffix.lower() in IMAGE_EXTS:
            image_paths.append(path)

    result = suggest_subject_multi(
        [str(path) for path in image_paths],
        subject_hint=args.subject_hint,
        location_hint=args.location_hint,
        folder_hint=args.folder_hint,
    )

    print("")
    print("== Subject identifier result ==")
    print(f"subject:    {result.subject}")
    print(f"confidence: {result.confidence}")
    print(f"category:   {result.category}")
    print(f"error:      {result.error}")

    if args.print_json:
        print("")
        print(json.dumps(result.details or {}, indent=2, ensure_ascii=False))


# AMIR_RUNTIME_SUBJECT_GUARD_START
# Generic runtime guard.
# Blocks prompt/error/meta leaks and lazy broad subjects.
# No topic patching. No subject patching.

META_LEAK_WORDS = {
    "plural",
    "plurals",
    "singular",
    "singulars",
    "label",
    "labels",
    "candidate",
    "candidates",
    "category",
    "categories",
    "subject",
    "subjects",
    "specific",
    "descriptive",
    "generic",
    "taxonomy",
    "schema",
    "json",
    "field",
    "fields",
    "prompt",
    "instruction",
    "instructions",
    "failed",
    "failure",
    "error",
    "httperror",
    "traceback",
    "unknown",
}

LAZY_BROAD_SUBJECT_ROOTS = {
    "animal",
    "bird",
    "boat",
    "building",
    "car",
    "flower",
    "insect",
    "landscape",
    "man",
    "object",
    "person",
    "plant",
    "scene",
    "structure",
    "vehicle",
    "woman",
}

WEAK_DESCRIPTOR_ROOTS = {
    "bloom",
    "blooming",
    "blossom",
    "blossoming",
    "standing",
    "sitting",
    "static",
    "showing",
    "visible",
    "close",
    "closeup",
    "detail",
    "view",
}


def _amir_subject_has_meta_leak(value: Any) -> bool:
    raw = clean_text(value)

    if not raw:
        return False

    key = norm_key(raw)
    tokens = set(key.split())

    if tokens & META_LEAK_WORDS:
        return True

    bad_phrases = [
        "on plural",
        "on plurals",
        "in plural",
        "as plural",
        "subject label",
        "specific subject",
        "descriptive subject",
        "model failed",
        "http error",
        "not found",
        "only supports one image",
        "more than one image",
    ]

    return any(phrase in key for phrase in bad_phrases)


def _amir_subject_is_lazy_generic(value: str) -> bool:
    clean = clean_text(value)

    if not clean:
        return True

    tokens = [singular_token(token) for token in word_tokens(clean)]
    tokens = [token for token in tokens if token]

    if not tokens:
        return True

    if any(token in META_LEAK_WORDS for token in tokens):
        return True

    useful = [
        token
        for token in tokens
        if token not in LAZY_BROAD_SUBJECT_ROOTS
        and token not in WEAK_DESCRIPTOR_ROOTS
        and token not in COLOR_WORDS
        and token not in QUANTITY_WORDS
        and token not in ACTION_WORDS
        and token not in LOCATION_NOISE
        and token not in GEAR_NOISE
    ]

    has_broad = any(token in LAZY_BROAD_SUBJECT_ROOTS for token in tokens)

    if has_broad and not useful:
        return True

    if len(tokens) <= 2 and has_broad and len(useful) == 0:
        return True

    return False


_AMIR_ORIGINAL_CLEAN_SUBJECT_LABEL = clean_subject_label


def clean_subject_label(value: str, max_words: int = 8, max_chars: int = 70) -> str:
    if subject_has_error_leak(value) or _amir_subject_has_meta_leak(value):
        return ""

    cleaned = _AMIR_ORIGINAL_CLEAN_SUBJECT_LABEL(value, max_words=max_words, max_chars=max_chars)

    if subject_has_error_leak(cleaned) or _amir_subject_has_meta_leak(cleaned):
        return ""

    if _amir_subject_is_lazy_generic(cleaned):
        return ""

    return cleaned


def has_specific_signal(value: str) -> bool:
    text = ascii_text(value)

    if subject_has_error_leak(text) or _amir_subject_has_meta_leak(text) or _amir_subject_is_lazy_generic(text):
        return False

    tokens = word_tokens(text)

    if not tokens:
        return False

    useful = [
        singular_token(token)
        for token in tokens
        if singular_token(token)
        and singular_token(token) not in LAZY_BROAD_SUBJECT_ROOTS
        and singular_token(token) not in WEAK_DESCRIPTOR_ROOTS
        and singular_token(token) not in COLOR_WORDS
        and singular_token(token) not in QUANTITY_WORDS
        and singular_token(token) not in ACTION_WORDS
        and singular_token(token) not in LOCATION_NOISE
        and singular_token(token) not in GEAR_NOISE
        and singular_token(token) not in META_LEAK_WORDS
    ]

    if any(any(ch.isdigit() for ch in token) for token in text.split()):
        return True

    if len(useful) >= 1 and len(tokens) >= 2:
        return True

    if len(useful) >= 2:
        return True

    return False

# AMIR_RUNTIME_SUBJECT_GUARD_END

# AMIR_TAIL_META_CLEANER_START
# Generic tail leak cleaner.
# Removes prompt/schema words when they appear as trailing garbage:
# "On Mains", "On Plurals", "As Subject", etc.
# Does not patch any specific topic.

TAIL_META_WORDS = {
    "main",
    "mains",
    "plural",
    "plurals",
    "singular",
    "singulars",
    "label",
    "labels",
    "subject",
    "subjects",
    "candidate",
    "candidates",
    "category",
    "categories",
    "specific",
    "descriptive",
    "generic",
    "schema",
    "json",
    "field",
    "fields",
    "prompt",
    "instruction",
    "instructions",
}


def _amir_strip_tail_meta_words(value: str) -> str:
    text = clean_text(value)

    if not text:
        return ""

    text = re.sub(r"[_-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" ,.;:-")

    for _ in range(5):
        new_text = re.sub(
            r"\b(?:on|in|at|by|with|for|as|of|the)\s+(?:main|mains|plural|plurals|singular|singulars|label|labels|subject|subjects|candidate|candidates|category|categories|specific|descriptive|generic|schema|json|field|fields|prompt|instruction|instructions)\s*$",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip(" ,.;:-")

        new_text = re.sub(
            r"\b(?:main|mains|plural|plurals|singular|singulars|label|labels|subject|subjects|candidate|candidates|category|categories|specific|descriptive|generic|schema|json|field|fields|prompt|instruction|instructions)\s*$",
            "",
            new_text,
            flags=re.IGNORECASE,
        ).strip(" ,.;:-")

        if new_text == text:
            break

        text = new_text

    return text


_PREVIOUS_CLEAN_SUBJECT_LABEL = clean_subject_label


def clean_subject_label(value: str, max_words: int = 8, max_chars: int = 70) -> str:
    cleaned_input = _amir_strip_tail_meta_words(value)

    if not cleaned_input:
        return ""

    cleaned = _PREVIOUS_CLEAN_SUBJECT_LABEL(cleaned_input, max_words=max_words, max_chars=max_chars)
    cleaned = _amir_strip_tail_meta_words(cleaned)

    if not cleaned:
        return ""

    if subject_has_error_leak(cleaned):
        return ""

    if "_amir_subject_has_meta_leak" in globals():
        if _amir_subject_has_meta_leak(cleaned):
            return ""

    if "_amir_subject_is_lazy_generic" in globals():
        if _amir_subject_is_lazy_generic(cleaned):
            return ""

    return cleaned
# AMIR_TAIL_META_CLEANER_END

# AMIR_DUPLICATE_TAIL_CLEANER_START
# Generic duplicate tail cleaner.
# Example:
# "White Blossom Branches On Branches" -> "White Blossom Branches"
# No topic patching. No subject patching.

def _amir_strip_duplicate_subject_tail(value: str) -> str:
    text = clean_text(value)

    if not text:
        return ""

    text = re.sub(r"[_-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" ,.;:-")

    for _ in range(4):
        match = re.search(
            r"^(?P<head>.+?)\s+(?P<prep>on|in|at|by|with|near|of)\s+(?P<tail>[A-Za-z][A-Za-z ]{1,40})$",
            text,
            flags=re.IGNORECASE,
        )

        if not match:
            break

        head = match.group("head").strip(" ,.;:-")
        tail = match.group("tail").strip(" ,.;:-")

        head_roots = {
            singular_token(token)
            for token in word_tokens(head)
            if singular_token(token)
        }

        tail_roots = [
            singular_token(token)
            for token in word_tokens(tail)
            if singular_token(token)
        ]

        if not tail_roots:
            break

        useful_tail_roots = [
            root
            for root in tail_roots
            if root not in COLOR_WORDS
            and root not in QUANTITY_WORDS
            and root not in ACTION_WORDS
            and root not in LOCATION_NOISE
            and root not in GEAR_NOISE
        ]

        if useful_tail_roots and all(root in head_roots for root in useful_tail_roots):
            text = head
            continue

        break

    return text


_DUPLICATE_TAIL_PREVIOUS_CLEAN_SUBJECT_LABEL = clean_subject_label


def clean_subject_label(value: str, max_words: int = 8, max_chars: int = 70) -> str:
    cleaned = _DUPLICATE_TAIL_PREVIOUS_CLEAN_SUBJECT_LABEL(
        value,
        max_words=max_words,
        max_chars=max_chars,
    )

    cleaned = _amir_strip_duplicate_subject_tail(cleaned)

    if not cleaned:
        return ""

    return cleaned
# AMIR_DUPLICATE_TAIL_CLEANER_END

# AMIR_UNSUPPORTED_IDENTITY_DOWNGRADE_START
# Generic unsupported identity downgrade.
# This is not a church patch.
# It removes unsupported building/function identity words when the model only has weak visual evidence.
# Example:
# "Church Steeple Standing" -> "Pointed Rooftop Detail"
# "Building Steeple Standing" -> "Pointed Rooftop Detail"

_AMIR_FUNCTION_IDENTITY_WORDS = {
    "church",
    "cathedral",
    "chapel",
    "mosque",
    "synagogue",
    "temple",
    "castle",
    "palace",
    "museum",
    "station",
    "school",
    "hospital",
    "hotel",
    "restaurant",
    "shop",
    "store",
    "office",
    "factory",
    "warehouse",
    "house",
    "apartment",
    "courthouse",
    "townhall",
    "monument",
}

_AMIR_BROAD_STRUCTURE_WORDS = {
    "building",
    "structure",
    "architecture",
    "architectural",
}

_AMIR_WEAK_STATIC_WORDS = {
    "standing",
    "showing",
    "visible",
    "seen",
    "appearing",
    "static",
    "view",
    "detail",
}

_AMIR_VISUAL_ROOF_WORDS = {
    "steeple",
    "spire",
    "turret",
    "tower",
    "roof",
    "rooftop",
    "dome",
    "cupola",
    "conical",
    "pointed",
}


def _amir_title_from_roots(roots):
    words = []

    for root in roots:
        if not root:
            continue

        words.append(root.capitalize())

    return " ".join(words).strip()


def _amir_downgrade_unsupported_identity(value: str) -> str:
    text = clean_text(value)

    if not text:
        return ""

    original_tokens = word_tokens(text)
    roots = [singular_token(token) for token in original_tokens if singular_token(token)]

    if not roots:
        return ""

    has_function_identity = any(root in _AMIR_FUNCTION_IDENTITY_WORDS for root in roots)
    has_broad_structure = any(root in _AMIR_BROAD_STRUCTURE_WORDS for root in roots)
    has_weak_static = any(root in _AMIR_WEAK_STATIC_WORDS for root in roots)
    has_visual_roof = any(root in _AMIR_VISUAL_ROOF_WORDS for root in roots)

    if not (has_function_identity or has_broad_structure or has_weak_static):
        return text

    cleaned_roots = [
        root
        for root in roots
        if root not in _AMIR_FUNCTION_IDENTITY_WORDS
        and root not in _AMIR_BROAD_STRUCTURE_WORDS
        and root not in _AMIR_WEAK_STATIC_WORDS
    ]

    if has_visual_roof:
        if "conical" in roots:
            return "Conical Rooftop Detail"

        if "dome" in roots or "cupola" in roots:
            return "Rooftop Dome Detail"

        if "tower" in roots and not ("steeple" in roots or "spire" in roots):
            return "Architectural Tower Detail"

        return "Pointed Rooftop Detail"

    if cleaned_roots:
        return _amir_title_from_roots(cleaned_roots)

    return ""


_AMIR_PREVIOUS_CLEAN_SUBJECT_LABEL_FOR_IDENTITY = clean_subject_label


def clean_subject_label(value: str, max_words: int = 8, max_chars: int = 70) -> str:
    cleaned = _AMIR_PREVIOUS_CLEAN_SUBJECT_LABEL_FOR_IDENTITY(
        value,
        max_words=max_words,
        max_chars=max_chars,
    )

    cleaned = _amir_downgrade_unsupported_identity(cleaned)

    if not cleaned:
        return ""

    if subject_has_error_leak(cleaned):
        return ""

    if "_amir_subject_has_meta_leak" in globals() and _amir_subject_has_meta_leak(cleaned):
        return ""

    if "_amir_subject_is_lazy_generic" in globals() and _amir_subject_is_lazy_generic(cleaned):
        return ""

    return cleaned
# AMIR_UNSUPPORTED_IDENTITY_DOWNGRADE_END

# AMIR_ADAPTIVE_SUBJECT_SAMPLING_V2_START
# Generic adaptive subject sampling.
# No per topic rules. No per subject rules.
# qwen2.5vl:3b first. qwen2.5vl:7b only if 3b is weak or rejected.

import json as _amir_subj_json
import re as _amir_subj_re
import time as _amir_subj_time
from pathlib import Path as _amir_subj_Path


def make_model_list():
    mode = os.getenv("AMIR_SUBJECT_MODEL_MODE", "").strip().lower()

    if mode == "regenerate_alt":
        # Safe regenerate mode.
        # Do NOT load qwen2.5vl:7b by default.
        # On 12 GB VRAM it can fall back to CPU/RAM and crash Windows.
        requested = [
            "qwen2.5vl:3b",
        ]
    else:
        # Safe normal mode.
        # Keep 7b disabled by default to avoid CPU fallback and MEMORY_MANAGEMENT crashes.
        requested = [
            "qwen2.5vl:3b",
        ]

    if os.getenv("AMIR_ALLOW_QWEN_7B_SUBJECT", "").strip() == "1":
        requested.append("qwen2.5vl:7b")

    try:
        installed = installed_ollama_model_names()
    except Exception:
        installed = set()

    if installed:
        models = [model for model in requested if model in installed]
    else:
        models = requested[:]

    if not models:
        try:
            log("[SUBJECT AI] warning | no trusted qwen subject model installed")
        except Exception:
            pass

    return models


def _amir_subj_norm(value):
    text = str(value or "").replace("_", " ").replace("-", " ").lower()
    text = _amir_subj_re.sub(r"[^a-z0-9\s]", " ", text)
    text = _amir_subj_re.sub(r"\s+", " ", text).strip()
    return text


def _amir_subj_tokens(value):
    return [token for token in _amir_subj_norm(value).split() if len(token) >= 3]


def _amir_subj_stem(token):
    token = str(token or "").lower()

    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"

    if len(token) > 4 and token.endswith("es"):
        return token[:-2]

    if len(token) > 3 and token.endswith("s"):
        return token[:-1]

    return token


def _amir_subj_stems(value):
    return {_amir_subj_stem(token) for token in _amir_subj_tokens(value)}


def _amir_subj_similarity(left, right):
    a = _amir_subj_stems(left)
    b = _amir_subj_stems(right)

    if not a or not b:
        return 0.0

    return len(a & b) / max(1, len(a | b))


def _amir_subj_unique_paths(paths):
    seen = set()
    result = []

    for path in paths:
        key = str(path)

        if key in seen:
            continue

        seen.add(key)
        result.append(path)

    return result


def _amir_subj_initial_samples(paths):
    if len(paths) <= 2:
        return paths[:]

    return _amir_subj_unique_paths([paths[0], paths[-1]])


def _amir_subj_extra_samples(paths):
    if len(paths) <= 2:
        return []

    last = len(paths) - 1
    candidates = [
        paths[round(last * 0.16)],
        paths[round(last * 0.33)],
        paths[round(last * 0.67)],
        paths[round(last * 0.50)],
        paths[round(last * 0.25)],
        paths[round(last * 0.75)],
    ]

    if len(paths) >= 31:
        candidates.extend([paths[1], paths[-2]])
    elif len(paths) >= 7:
        candidates.append(paths[round(last * 0.33)])

    max_total = min(max(2, int(MAX_IMAGES)), 6, len(paths))
    already = set(str(path) for path in _amir_subj_initial_samples(paths))
    result = []

    for path in _amir_subj_unique_paths(candidates):
        if str(path) in already:
            continue

        result.append(path)

        if len(result) + len(already) >= max_total:
            break

    return result


def choose_samples(paths: list[_amir_subj_Path], max_images: int) -> list[_amir_subj_Path]:
    if not paths:
        return []

    initial = _amir_subj_initial_samples(paths)
    extra = _amir_subj_extra_samples(paths)
    target_count = min(max(1, int(max_images or 1)), 6, len(paths))

    return _amir_subj_unique_paths(initial + extra)[:target_count]


def _amir_subj_rows_agree(rows, result):
    if not getattr(result, "subject", ""):
        return False

    if int(getattr(result, "confidence", 0) or 0) < 85:
        return False

    accepted_subjects = [
        str(row.get("subject") or "")
        for row in rows or []
        if isinstance(row, dict) and row.get("accepted") and row.get("subject")
    ]

    if len(accepted_subjects) < 2:
        return False

    base = str(getattr(result, "subject", "") or accepted_subjects[0])
    similar = [
        subject
        for subject in accepted_subjects
        if _amir_subj_similarity(base, subject) >= 0.50
    ]

    return len(similar) >= max(2, int(round(len(accepted_subjects) * 0.67)))


def suggest_subject_multi(
    image_paths: list[str],
    *,
    location_hint: str = "",
    folder_hint: str = "",
    subject_hint: str = "",
) -> SubjectSuggestion:
    paths = [
        _amir_subj_Path(path)
        for path in image_paths or []
        if path and _amir_subj_Path(path).is_file() and _amir_subj_Path(path).suffix.lower() in IMAGE_EXTS
    ]

    if not paths:
        return SubjectSuggestion(
            subject="",
            confidence=0,
            category="",
            error="No valid image files selected.",
            details={"rows": []},
        )

    initial_paths = _amir_subj_initial_samples(paths)
    extra_paths = _amir_subj_extra_samples(paths)
    models = make_model_list()
    max_total = min(max(2, int(MAX_IMAGES)), 6, len(paths))

    log(
        f"[SUBJECT AI] start | selected={len(paths)} | samples=adaptive:{len(initial_paths)}-to-{max_total} | "
        f"models={', '.join(models)} | source=subject_identifier_production_v17_context_subject_identifier_json_db_identifier"
    )
    log(
        f"[SUBJECT AI] db | results={RESULTS_DB.exists()} | label_bank={LABEL_BANK_DB.exists()} | "
        f"knowledge={REVAMP_KNOWLEDGE_DB.exists()}"
    )

    start_time = _amir_subj_time.time()
    rows: list[dict[str, Any]] = []
    sampled_paths = []

    def analyze_path(path, index, total_label):
        elapsed = int(_amir_subj_time.time() - start_time)
        log(f"[SUBJECT AI] sample {index}/{total_label} | elapsed={elapsed}s | {path.name}")

        row = analyze_one_image(
            image_path=path,
            subject_hint=subject_hint,
            location_hint=location_hint,
            folder_hint=folder_hint,
        )

        rows.append(row)
        sampled_paths.append(path)
        return row

    for index, path in enumerate(initial_paths, start=1):
        analyze_path(path, index, f"adaptive initial {len(initial_paths)}")

    result = combine_subjects(rows)

    if _amir_subj_rows_agree(rows, result):
        log("[SUBJECT AI] adaptive stop | first samples agree")
    else:
        for path in extra_paths:
            if len(sampled_paths) >= max_total:
                break

            analyze_path(path, len(sampled_paths) + 1, f"adaptive max {max_total}")
            result = combine_subjects(rows)

            if _amir_subj_rows_agree(rows, result):
                log("[SUBJECT AI] adaptive stop | subject agreement reached")
                break

    reference_result = _amir_identifier_reference_subject(
        paths,
        rows,
        result,
        subject_hint=subject_hint,
        location_hint=location_hint,
        folder_hint=folder_hint,
    )

    if reference_result is not None:
        result = reference_result

    set_key = make_set_key([str(path) for path in paths])

    try:
        save_results(
            set_key=set_key,
            all_paths=paths,
            sampled_paths=sampled_paths,
            rows=rows,
            result=result,
            subject_hint=subject_hint,
            location_hint=location_hint,
            folder_hint=folder_hint,
        )
    except Exception as exc:
        log(f"[SUBJECT AI] warn | could not save identifier_results.db | {type(exc).__name__}: {exc}")

    if result.subject:
        log(
            f"[SUBJECT AI] result | subject={result.subject} | "
            f"confidence={result.confidence} | category={result.category}"
        )
    else:
        log(f"[SUBJECT AI] result | needs_manual | {result.error}")

    return result
# AMIR_ADAPTIVE_SUBJECT_SAMPLING_V2_END

# AMIR_HINT_KEYWORDS_SUBJECT_SOFT_EVIDENCE_V1_START
# Optional hint keywords for subject detection.
# Positive hints are added as soft context.
# Negative hints like "no people" reject matching hallucinated candidates.

import os as _amir_subj_hint_os
import re as _amir_subj_hint_re


_AMIR_SUBJ_HINT_HIGH_RISK_EQUIV = {
    "person": {"person", "people", "human", "man", "woman", "boy", "girl", "pedestrian", "worker", "workers"},
    "people": {"person", "people", "human", "man", "woman", "boy", "girl", "pedestrian", "worker", "workers"},
    "human": {"person", "people", "human", "man", "woman", "boy", "girl", "pedestrian", "worker", "workers"},
}


def _amir_subj_hint_norm(value):
    text = str(value or "")
    text = text.replace("_", " ").replace("-", " ").lower()
    text = _amir_subj_hint_re.sub(r"[^a-z0-9,\s]", " ", text)
    text = _amir_subj_hint_re.sub(r"\s+", " ", text).strip()
    return text


def _amir_subj_hint_tokens(value):
    return [
        token
        for token in _amir_subj_hint_re.findall(r"[a-z0-9]+", _amir_subj_hint_norm(value))
        if len(token) >= 2
    ]


def _amir_subj_hint_get():
    return str(_amir_subj_hint_os.environ.get("AMIR_CURRENT_HINT_KEYWORDS") or "").strip()


def _amir_subj_hint_parse(value):
    raw = str(value or "")
    parts = [
        item.strip()
        for item in _amir_subj_hint_re.split(r"[,;|]", raw)
        if item.strip()
    ]

    positive = []
    negative = []

    for part in parts:
        low = _amir_subj_hint_norm(part)

        if not low:
            continue

        is_negative = False

        for prefix in ["no ", "not ", "without ", "exclude ", "avoid "]:
            if low.startswith(prefix):
                is_negative = True
                low = low[len(prefix):].strip()
                break

        if is_negative:
            negative.append(low)
        else:
            positive.append(low)

    return positive, negative


def _amir_subj_hint_violates_negative(subject, negative_terms):
    subject_tokens = set(_amir_subj_hint_tokens(subject))

    if not subject_tokens:
        return False

    for term in negative_terms:
        term_tokens = set(_amir_subj_hint_tokens(term))

        if not term_tokens:
            continue

        expanded = set(term_tokens)

        for token in list(term_tokens):
            expanded.update(_AMIR_SUBJ_HINT_HIGH_RISK_EQUIV.get(token, set()))

        if subject_tokens & expanded:
            return True

    return False


try:
    _amir_original_analyze_one_image_with_hints
except NameError:
    _amir_original_analyze_one_image_with_hints = analyze_one_image


def analyze_one_image(*args, **kwargs):
    hints = _amir_subj_hint_get()
    positive, negative = _amir_subj_hint_parse(hints)

    if positive:
        current_hint = str(kwargs.get("subject_hint") or "").strip()
        soft_hint = "Optional visual hint keywords, use only if visible: " + ", ".join(positive)

        if current_hint:
            kwargs["subject_hint"] = current_hint + ". " + soft_hint
        else:
            kwargs["subject_hint"] = soft_hint

    row = _amir_original_analyze_one_image_with_hints(*args, **kwargs)

    try:
        if negative and isinstance(row, dict):
            subject = str(row.get("subject") or "")

            if subject and _amir_subj_hint_violates_negative(subject, negative):
                row = dict(row)
                row["accepted"] = False
                row["confidence"] = 0
                row["reason"] = "Rejected by negative hint keywords."
                row["notes"] = "Rejected by optional negative hint keywords."
                log(f"[SUBJECT AI] rejected by hint | subject={subject} | hints={hints}")
    except Exception as exc:
        try:
            log(f"[SUBJECT AI] hint gate warning | {type(exc).__name__}: {exc}")
        except Exception:
            pass

    return row


try:
    _amir_original_combine_subjects_with_hints
except NameError:
    _amir_original_combine_subjects_with_hints = combine_subjects


def combine_subjects(rows):
    result = _amir_original_combine_subjects_with_hints(rows)

    try:
        hints = _amir_subj_hint_get()
        _positive, negative = _amir_subj_hint_parse(hints)
        subject = str(getattr(result, "subject", "") or "")

        if subject and negative and _amir_subj_hint_violates_negative(subject, negative):
            return SubjectSuggestion(
                subject="",
                confidence=0,
                category="",
                error="Rejected by optional negative hint keywords.",
                details={
                    "rows": rows,
                    "hint_keywords": hints,
                },
            )
    except Exception as exc:
        try:
            log(f"[SUBJECT AI] hint combine warning | {type(exc).__name__}: {exc}")
        except Exception:
            pass

    return result
# AMIR_HINT_KEYWORDS_SUBJECT_SOFT_EVIDENCE_V1_END

# AMIR_FINAL_SUBJECT_MODEL_SELECTOR_V1_START
# Final model selector override.
# This must sit immediately before the __main__ guard so it wins over older patched selectors.
def make_model_list():
    import os

    forced_model = os.getenv("AMIR_SUBJECT_FORCE_MODEL", "").strip()
    normal_model = os.getenv("AMIR_SUBJECT_NORMAL_MODEL", "qwen3-vl:4b,qwen2.5vl:3b").strip()
    regenerate_model = os.getenv("AMIR_SUBJECT_REGENERATE_MODEL", "qwen3-vl:4b").strip()
    identify_model = os.getenv("AMIR_SUBJECT_IDENTIFY_MODEL", "qwen3-vl:4b").strip()
    mode = os.getenv("AMIR_SUBJECT_MODEL_MODE", "").strip().lower()

    if forced_model:
        # Regenerate must use ONLY the forced alternate model.
        # Do not include qwen2.5vl:3b here, because the internal selector can pick it again.
        requested = [
            forced_model,
        ]
    elif mode == "regenerate_alt":
        # Regenerate must be a real second opinion.
        requested = [
            regenerate_model,
        ]
    elif mode == "identify":
        # Dedicated identifier mode is allowed to be stricter/slower, but only
        # for the explicit Identify workflow.
        requested = _amir_subject_split_models(identify_model) if "_amir_subject_split_models" in globals() else [identify_model]
    else:
        # Normal AI suggest stays stable and fast.
        requested = _amir_subject_split_models(normal_model) if "_amir_subject_split_models" in globals() else [normal_model]

    if os.getenv("AMIR_ALLOW_QWEN_7B_SUBJECT", "").strip() == "1":
        requested.append("qwen2.5vl:7b")

    cleaned = []
    seen = set()

    for model in requested:
        model = str(model or "").strip()

        if not model:
            continue

        if model in seen:
            continue

        seen.add(model)
        cleaned.append(model)

    return cleaned
# AMIR_FINAL_SUBJECT_MODEL_SELECTOR_V1_END





# AMIR_SUBJECT_PROPER_MODEL_REGENERATE_V2_START
# Worker-level model subject system.
# Reads regenerate context from data/subject_regenerate_context.json when env does not cross process.
# Hints are soft evidence only. No copy/paste.

import base64 as _amir_subject_b64
import json as _amir_subject_json
import os as _amir_subject_os
import re as _amir_subject_re
import time as _amir_subject_time
import urllib.request as _amir_subject_urlreq
from pathlib import Path as _amir_subject_Path


_AMIR_SUBJECT_BAD = {
    "",
    "image",
    "photo",
    "picture",
    "photograph",
    "scene",
    "view",
    "object",
    "subject",
    "unknown",
    "landscape",
    "cityscape",
    "outdoor scene",
    "urban scene",
    "nature scene",
}

_AMIR_SUBJECT_DROP = {
    "a",
    "an",
    "the",
    "this",
    "that",
    "image",
    "photo",
    "picture",
    "photograph",
    "shows",
    "showing",
    "depicts",
    "featuring",
    "contains",
    "visible",
    "main",
    "subject",
    "appears",
    "there",
    "is",
    "are",
    "of",
}


def _amir_subject_context_path():
    env_path = _amir_subject_os.getenv("AMIR_SUBJECT_CONTEXT_FILE", "").strip()

    candidates = []

    if env_path:
        candidates.append(_amir_subject_Path(env_path))

    candidates.append(_amir_subject_Path.cwd() / "data" / "subject_regenerate_context.json")
    candidates.append(_amir_subject_Path(__file__).resolve().parent.parent / "data" / "subject_regenerate_context.json")

    for path in candidates:
        if path.exists():
            return path

    return candidates[0] if candidates else None


def _amir_subject_read_context():
    path = _amir_subject_context_path()

    if path is None or not path.exists():
        return {
            "active": False,
            "hints": "",
            "current_subject": "",
        }

    try:
        data = _amir_subject_json.loads(path.read_text(encoding="utf-8", errors="replace"))
        active = bool(data.get("active"))

        if active:
            created_at = float(data.get("created_at") or 0.0)
            ttl = int(_amir_subject_os.getenv("AMIR_SUBJECT_CONTEXT_TTL_SEC", "1200") or "1200")

            if created_at and ttl > 0 and (_amir_subject_time.time() - created_at) > ttl:
                active = False

        return {
            "active": active,
            "hints": str(data.get("hints") or "").strip() if active else "",
            "current_subject": str(data.get("current_subject") or "").strip() if active else "",
        }
    except Exception:
        return {
            "active": False,
            "hints": "",
            "current_subject": "",
        }


def _amir_subject_is_garbage(value):
    text = str(value or "").strip()

    if not text:
        return True

    tokens = _amir_subject_re.findall(r"[A-Za-z0-9]+", text)

    if not tokens:
        return True

    hexish = 0
    tiny = 0
    has_normal_word = False

    for token in tokens:
        low = token.lower()

        if len(token) <= 1:
            tiny += 1

        if _amir_subject_re.fullmatch(r"[0-9a-fA-F]{2,}", token):
            hexish += 1

        if len(token) >= 3 and _amir_subject_re.search(r"[aeiou]", low) and not _amir_subject_re.fullmatch(r"[0-9a-fA-F]+", token):
            has_normal_word = True

    if len(tokens) >= 4 and (hexish + tiny) / len(tokens) >= 0.55:
        return True

    if not has_normal_word:
        return True

    return False


def _amir_subject_norm(value):
    return _amir_subject_re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


_AMIR_SUBJECT_REGEN_DETAIL_WORDS = {
    "wearing",
    "sunglasses",
    "glasses",
    "cap",
    "hat",
    "shirt",
    "jacket",
    "coat",
    "clothing",
    "clothes",
}


def _amir_subject_same_regen_frame(candidate, current):
    cand_tokens = set(_amir_subject_re.findall(r"[a-z0-9]+", str(candidate or "").lower()))
    curr_tokens = set(_amir_subject_re.findall(r"[a-z0-9]+", str(current or "").lower()))

    if not cand_tokens or not curr_tokens:
        return False

    if _amir_subject_norm(candidate) == _amir_subject_norm(current):
        return True

    shared = cand_tokens & curr_tokens
    smaller = max(1, min(len(cand_tokens), len(curr_tokens)))
    overlap = len(shared) / smaller

    if overlap >= 0.7 and len(cand_tokens - curr_tokens) <= 1:
        return True

    if (
        "wearing" in cand_tokens
        and "wearing" in curr_tokens
        and cand_tokens & _AMIR_SUBJECT_REGEN_DETAIL_WORDS
        and curr_tokens & _AMIR_SUBJECT_REGEN_DETAIL_WORDS
    ):
        return True

    return False


def _amir_subject_broaden_unprompted_specific(subject, hints="", current_subject=""):
    text = str(subject or "").strip()

    if not text or not str(hints or "").strip():
        return text

    support_tokens = set(
        _amir_subject_re.findall(
            r"[a-z0-9]+",
            f"{hints or ''} {current_subject or ''}".lower(),
        )
    )
    subject_tokens = set(_amir_subject_re.findall(r"[a-z0-9]+", text.lower()))

    match = _amir_subject_re.match(
        r"^(.+?)\s+(on|with|near|beside|by|at|inside|under)\s+(?:a|an|the\s+)?([a-z0-9][a-z0-9\s]{1,30})$",
        text,
        flags=_amir_subject_re.IGNORECASE,
    )

    if not match:
        return text

    head = match.group(1).strip()
    tail = match.group(3).strip()
    head_tokens = set(_amir_subject_re.findall(r"[a-z0-9]+", head.lower()))
    tail_tokens = set(_amir_subject_re.findall(r"[a-z0-9]+", tail.lower()))

    if not head_tokens or not tail_tokens:
        return text

    if tail_tokens & support_tokens:
        return text

    role_or_action = bool(head_tokens & _AMIR_SUBJECT_WEAK_REGEN_WORDS)

    if not role_or_action:
        return text

    trimmed = head

    if len(trimmed.split()) >= 2:
        return trimmed

    return text


_AMIR_SUBJECT_WEAK_REGEN_WORDS = {
    "man",
    "men",
    "woman",
    "women",
    "person",
    "people",
    "worker",
    "workers",
    "working",
    "sitting",
    "standing",
    "walking",
    "looking",
}


def _amir_subject_is_weak_regen_subject(subject, hints=""):
    if _amir_subject_identifier_mode():
        try:
            if (
                "_amir_subject_should_run_taxon_identifier" in globals()
                and _amir_subject_should_run_taxon_identifier(subject, "")
                and (
                    (
                        "_amir_subject_underidentified_taxon" in globals()
                        and _amir_subject_underidentified_taxon(subject)
                    )
                    or (
                        "_amir_taxon_is_group_label" in globals()
                        and _amir_taxon_is_group_label(subject)
                    )
                    or (
                        "_amir_taxon_is_broad" in globals()
                        and _amir_taxon_is_broad(subject)
                    )
                )
            ):
                return True
        except Exception:
            pass

    if not str(hints or "").strip():
        return False

    tokens = _amir_subject_re.findall(r"[a-z0-9]+", str(subject or "").lower())

    if not tokens:
        return True

    if len(tokens) <= 3 and set(tokens) <= _AMIR_SUBJECT_WEAK_REGEN_WORDS:
        return True

    return False


def _amir_subject_clean(value):
    text = str(value or "").strip()

    try:
        data = _amir_subject_json.loads(text)

        if isinstance(data, dict):
            text = str(data.get("subject") or "")
    except Exception:
        match = _amir_subject_re.search(r"\{[\s\S]*?\"subject\"[\s\S]*?\}", text)

        if match:
            try:
                data = _amir_subject_json.loads(match.group(0))

                if isinstance(data, dict):
                    text = str(data.get("subject") or "")
            except Exception:
                pass

    text = text.replace("_", " ").replace("-", " ")
    text = _amir_subject_re.sub(r"```[\s\S]*?```", " ", text)
    text = _amir_subject_re.sub(r"[^A-Za-z0-9\s]", " ", text)
    text = _amir_subject_re.sub(r"\s+", " ", text).strip()

    if _amir_subject_is_garbage(text):
        return ""

    words = []

    for word in text.split():
        low = word.lower()

        if low in _AMIR_SUBJECT_DROP:
            continue

        words.append(word[:1].upper() + word[1:].lower())

    subject = " ".join(words[:8]).strip()
    subject = _amir_subject_re.sub(r"\b([A-Za-z0-9]{2,}) S ([A-Za-z0-9]{2,})\b", r"\1 \2", subject)
    subject = _amir_subject_re.sub(r"\s+", " ", subject).strip()

    if subject.lower() in _AMIR_SUBJECT_BAD:
        return ""

    if _amir_subject_is_garbage(subject):
        return ""

    if len(subject) < 4:
        return ""

    return subject


def _amir_subject_find_image_path(args, kwargs):
    candidates = []

    for item in args:
        candidates.append(item)

    for item in kwargs.values():
        candidates.append(item)

    for item in candidates:
        try:
            path = _amir_subject_Path(str(item))

            if path.exists() and path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                return path
        except Exception:
            pass

    return None


def _amir_subject_call_model(
    image_path,
    prompt,
    model,
    temperature,
    num_predict=None,
    json_mode=False,
):
    try:
        image_b64 = image_to_base64(image_path)
    except Exception:
        image_b64 = _amir_subject_b64.b64encode(image_path.read_bytes()).decode("ascii")

    model_name = str(model or "").strip().lower()
    qwen3_vl = model_name.startswith("qwen3-vl:")

    predict = int(num_predict) if num_predict is not None else (384 if qwen3_vl else 96)

    payload = {
        "model": model,
        "prompt": prompt,
        "images": [image_b64],
        "stream": False,
        "keep_alive": "10m",
        "options": {
            "temperature": temperature,
            "num_predict": predict,
            "num_ctx": 4096 if qwen3_vl else 2048,
        },
    }

    if json_mode:
        payload["format"] = "json"

        if qwen3_vl:
            payload["think"] = False

    request = _amir_subject_urlreq.Request(
        "http://127.0.0.1:11434/api/generate",
        data=_amir_subject_json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with _amir_subject_urlreq.urlopen(request, timeout=240) as response:
        raw = _amir_subject_json.loads(response.read().decode("utf-8", errors="replace"))

    response = str(raw.get("response") or "").strip()

    if response:
        return response

    thinking = str(raw.get("thinking") or "").strip()

    if '"subject"' in thinking:
        return thinking

    return response


def _amir_subject_split_models(value):
    return [
        item.strip()
        for item in _amir_subject_re.split(r"[,;|]+", str(value or ""))
        if item.strip()
    ]


def _amir_subject_direct_model_candidates(force_regenerate=False):
    try:
        installed = installed_ollama_model_names()
    except Exception:
        installed = set()

    forced = _amir_subject_os.getenv("AMIR_SUBJECT_FORCE_MODEL", "").strip()
    identify_model = _amir_subject_os.getenv("AMIR_SUBJECT_IDENTIFY_MODEL", "qwen3-vl:4b").strip()

    if _amir_subject_identifier_mode():
        requested = [forced] if forced else _amir_subject_split_models(identify_model or "qwen3-vl:4b")
        cleaned = []
        seen = set()

        for model in requested:
            model = str(model or "").strip()

            if not model or model in seen:
                continue

            if installed and model not in installed:
                continue

            seen.add(model)
            cleaned.append(model)

        return cleaned or [identify_model or "qwen3-vl:4b"]

    regenerate = _amir_subject_os.getenv("AMIR_SUBJECT_REGENERATE_MODEL", "qwen3-vl:4b").strip()
    requested = []

    if forced:
        requested.append(forced)
    elif force_regenerate and regenerate:
        requested.append(regenerate)

    if force_regenerate:
        fallback = _amir_subject_os.getenv(
            "AMIR_SUBJECT_REGENERATE_FALLBACK_MODELS",
            "qwen3-vl:4b,qwen2.5vl:3b,minicpm-v:latest",
        )
    else:
        fallback = _amir_subject_os.getenv(
            "AMIR_SUBJECT_NORMAL_DIRECT_MODELS",
            "qwen3-vl:4b,qwen2.5vl:3b,minicpm-v:latest",
        )

    requested.extend(_amir_subject_split_models(fallback))

    if _amir_subject_os.getenv("AMIR_ALLOW_QWEN_7B_SUBJECT", "").strip() == "1":
        requested.append("qwen2.5vl:7b")

    cleaned = []
    seen = set()

    for model in requested:
        model = str(model or "").strip()

        if not model or model in seen:
            continue

        if installed and model not in installed:
            continue

        seen.add(model)
        cleaned.append(model)

    return cleaned or ["qwen2.5vl:3b"]


# AMIR_TAXONOMIC_SUBJECT_SUPPORT_V1_START
# Generic local taxonomic support for nature subjects.
# This is not a per-folder or per-current-batch patch. It gives birds, flowers,
# plants, insects, and animals a chance to resolve to a safe common name when
# the vision model returns only a broad phrase such as "birds in flight".

_AMIR_TAXON_BROAD_LABELS = {
    "animal",
    "animals",
    "bird",
    "birds",
    "goose",
    "geese",
    "duck",
    "ducks",
    "gull",
    "gulls",
    "pigeon",
    "pigeons",
    "heron",
    "herons",
    "cormorant",
    "cormorants",
    "swan",
    "swans",
    "coot",
    "coots",
    "moorhen",
    "moorhens",
    "raptor",
    "raptors",
    "deer",
    "fox",
    "foxes",
    "rabbit",
    "rabbits",
    "hare",
    "hares",
    "squirrel",
    "squirrels",
    "horse",
    "horses",
    "cow",
    "cows",
    "sheep",
    "dog",
    "dogs",
    "cat",
    "cats",
    "wildlife",
    "flower",
    "flowers",
    "plant",
    "plants",
    "tree",
    "trees",
    "insect",
    "insects",
}

_AMIR_TAXON_GROUP_LABELS = {
    "waterfowl",
    "wading birds",
    "shorebirds",
    "songbirds",
    "raptor",
    "wildflowers",
}

_AMIR_TAXON_WEAK_CONTEXT_WORDS = {
    "and",
    "or",
    "formation",
    "flying",
    "flight",
    "floating",
    "swimming",
    "swim",
    "grazing",
    "standing",
    "walking",
    "running",
    "resting",
    "lying",
    "flock",
    "in",
    "on",
    "at",
    "of",
    "the",
    "with",
    "group",
    "groups",
    "line",
    "lines",
    "sequence",
    "sequences",
    "calm",
    "over",
    "above",
    "open",
    "sky",
    "water",
    "waters",
    "pond",
    "ponds",
    "lake",
    "lakes",
    "river",
    "rivers",
    "canal",
    "canals",
    "stream",
    "streams",
    "sea",
    "wetland",
    "wetlands",
    "wading",
    "shallow",
    "shore",
    "bank",
    "banks",
    "reed",
    "reeds",
    "field",
    "fields",
    "grass",
    "pasture",
    "meadow",
    "habitat",
    "scene",
    "view",
    "closeup",
    "closeups",
    "close",
    "up",
    "macro",
    "detail",
    "leaf",
    "leaves",
    "head",
    "headed",
    "neck",
    "body",
    "back",
    "breast",
    "belly",
    "side",
    "sides",
    "bill",
    "bills",
    "beak",
    "beaks",
    "wing",
    "wings",
    "tail",
    "legs",
    "leg",
    "feet",
    "foot",
    "fur",
    "plumage",
    "marking",
    "markings",
    "pattern",
    "patterns",
    "petal",
    "petals",
    "stem",
    "stems",
    "branch",
    "branches",
}

_AMIR_TAXON_VISUAL_ONLY_DESCRIPTOR_ROOTS = {
    "background",
    "bloom",
    "blooms",
    "blossom",
    "blossoms",
    "cluster",
    "clusters",
    "clustered",
    "dark",
    "dry",
    "form",
    "forming",
    "flowering",
    "foreground",
    "ground",
    "growth",
    "large",
    "light",
    "low",
    "moss",
    "mossy",
    "patch",
    "patches",
    "spike",
    "spikes",
    "spiky",
    "shape",
    "shaped",
    "stalk",
    "stalks",
    "slender",
    "small",
    "spray",
    "sprays",
    "tall",
    "tuft",
    "tufts",
    "upright",
    "wet",
}

_AMIR_TAXON_NAME_QUALIFIER_WORDS = {
    "common",
    "eastern",
    "eurasian",
    "european",
    "great",
    "greater",
    "lesser",
    "little",
    "northern",
    "southern",
    "western",
}

_AMIR_TAXON_IDENTIFIER_TRIGGER_WORDS = {
    "animal",
    "animals",
    "wildlife",
    "bird",
    "birds",
    "waterfowl",
    "shorebird",
    "shorebirds",
    "wader",
    "waders",
    "goose",
    "geese",
    "duck",
    "ducks",
    "gull",
    "gulls",
    "pigeon",
    "pigeons",
    "lapwing",
    "lapwings",
    "oystercatcher",
    "oystercatchers",
    "heron",
    "herons",
    "cormorant",
    "cormorants",
    "swan",
    "swans",
    "coot",
    "coots",
    "moorhen",
    "moorhens",
    "raptor",
    "raptors",
    "deer",
    "fox",
    "foxes",
    "rabbit",
    "rabbits",
    "hare",
    "hares",
    "squirrel",
    "squirrels",
    "horse",
    "horses",
    "cow",
    "cows",
    "sheep",
    "dog",
    "dogs",
    "cat",
    "cats",
    "flower",
    "flowers",
    "plant",
    "plants",
    "tree",
    "trees",
    "leaf",
    "leaves",
    "petal",
    "petals",
    "stamen",
    "stamens",
    "insect",
    "insects",
    "butterfly",
    "butterflies",
    "moth",
    "moths",
    "bee",
    "bees",
    "beetle",
    "beetles",
    "dragonfly",
    "dragonflies",
    "damselfly",
    "damselflies",
    "fly",
    "flies",
    "wasp",
    "wasps",
    "spider",
    "spiders",
    "macro",
    "closeup",
    "closeups",
    "plumage",
    "bill",
    "bills",
    "beak",
    "beaks",
    "wing",
    "wings",
    "marking",
    "markings",
}

_AMIR_TAXON_LABELS = [
    # Birds and common wetland/urban wildlife
    "eurasian oystercatcher",
    "northern lapwing",
    "black-tailed godwit",
    "bar-tailed godwit",
    "common redshank",
    "eurasian curlew",
    "common snipe",
    "pied avocet",
    "mallard duck",
    "eurasian wigeon",
    "tufted duck",
    "common teal",
    "greylag goose",
    "canada goose",
    "mute swan",
    "eurasian coot",
    "common moorhen",
    "grey heron",
    "great cormorant",
    "black-headed gull",
    "herring gull",
    "common buzzard",
    "common kestrel",
    "feral pigeon",
    "wood pigeon",
    "european robin",
    "great tit",
    "house sparrow",
    "eurasian magpie",
    "carrion crow",
    "shorebirds",
    "wading birds",
    "waterfowl",
    "bird",
    "birds",
    # Flowers, plants, fungi, and botanical subjects
    "purple crocus",
    "crocus flowers",
    "tulip flowers",
    "daffodil flowers",
    "rose flowers",
    "sunflower",
    "orchid flowers",
    "daisy flowers",
    "poppy flowers",
    "iris flowers",
    "lavender flowers",
    "hydrangea flowers",
    "cherry blossom",
    "white blossom",
    "wildflowers",
    "mushroom",
    "fern fronds",
    "reeds",
    "seed heads",
    "flowers",
    "plants",
    # Insects and animals
    "red admiral butterfly",
    "butterfly",
    "moth",
    "honey bee",
    "bumblebee",
    "hoverfly",
    "dragonfly",
    "damselfly",
    "ladybird beetle",
    "beetle",
    "spider",
    "wasp",
    "fly insect",
    "red fox",
    "roe deer",
    "rabbit",
    "hare",
    "squirrel",
    "horse",
    "cow",
    "sheep",
    "dog",
    "cat",
    "animal",
]

_AMIR_TAXON_PIPE = None


def _amir_subject_identifier_mode():
    return _amir_subject_os.getenv("AMIR_SUBJECT_IDENTIFY_MODE", "").strip() == "1"


def _amir_identifier_int_env(name, default, minimum, maximum):
    try:
        value = int(float(_amir_subject_os.getenv(name, str(default)) or default))
    except Exception:
        value = default

    return max(minimum, min(maximum, value))


def _amir_identifier_target_confidence():
    return _amir_identifier_int_env("AMIR_SUBJECT_IDENTIFY_ACCEPT_CONFIDENCE", 80, 50, 99)


def _amir_identifier_grid_boxes(width, height, cols, rows, overlap=0.10):
    boxes = []
    cell_w = width / max(1, cols)
    cell_h = height / max(1, rows)
    pad_w = cell_w * overlap
    pad_h = cell_h * overlap

    for row in range(rows):
        for col in range(cols):
            left = max(0, int((col * cell_w) - pad_w))
            top = max(0, int((row * cell_h) - pad_h))
            right = min(width, int(((col + 1) * cell_w) + pad_w))
            bottom = min(height, int(((row + 1) * cell_h) + pad_h))

            if right - left >= 80 and bottom - top >= 80:
                boxes.append((left, top, right, bottom))

    return boxes


def _amir_identifier_salient_boxes(image):
    try:
        work = image.copy()
        work.thumbnail((640, 640))
        width, height = work.size
        pixels = list(work.convert("RGB").getdata())
    except Exception:
        return []

    if width < 80 or height < 80:
        return []

    mask = bytearray(width * height)

    for index, (red, green, blue) in enumerate(pixels):
        lum = (red * 299 + green * 587 + blue * 114) // 1000
        chroma = max(red, green, blue) - min(red, green, blue)

        if lum < 72 or (lum < 135 and chroma > 28) or (chroma > 78 and lum < 235):
            mask[index] = 1

    visited = bytearray(width * height)
    components = []
    total_area = width * height

    for start, active in enumerate(mask):
        if not active or visited[start]:
            continue

        stack = [start]
        visited[start] = 1
        area = 0
        min_x = max_x = start % width
        min_y = max_y = start // width

        while stack:
            current = stack.pop()
            x = current % width
            y = current // width
            area += 1
            min_x = min(min_x, x)
            max_x = max(max_x, x)
            min_y = min(min_y, y)
            max_y = max(max_y, y)

            if x > 0:
                nxt = current - 1
                if mask[nxt] and not visited[nxt]:
                    visited[nxt] = 1
                    stack.append(nxt)

            if x + 1 < width:
                nxt = current + 1
                if mask[nxt] and not visited[nxt]:
                    visited[nxt] = 1
                    stack.append(nxt)

            if y > 0:
                nxt = current - width
                if mask[nxt] and not visited[nxt]:
                    visited[nxt] = 1
                    stack.append(nxt)

            if y + 1 < height:
                nxt = current + width
                if mask[nxt] and not visited[nxt]:
                    visited[nxt] = 1
                    stack.append(nxt)

        box_w = max_x - min_x + 1
        box_h = max_y - min_y + 1

        if area < 5:
            continue

        if area > total_area * 0.08:
            continue

        if box_w > width * 0.45 or box_h > height * 0.45:
            continue

        aspect = box_w / max(1, box_h)

        if aspect < 0.12 or aspect > 8.0:
            continue

        components.append((area, min_x, min_y, max_x + 1, max_y + 1))

    if not components:
        return []

    components.sort(reverse=True)
    scale_x = image.size[0] / width
    scale_y = image.size[1] / height
    out = []
    min_crop_side = _amir_identifier_int_env("AMIR_SUBJECT_IDENTIFY_MIN_CROP_SIDE", 360, 140, 900)

    for _area, left, top, right, bottom in components[:24]:
        orig_left = int(left * scale_x)
        orig_top = int(top * scale_y)
        orig_right = int(right * scale_x)
        orig_bottom = int(bottom * scale_y)
        cx = (orig_left + orig_right) // 2
        cy = (orig_top + orig_bottom) // 2
        box_w = max(min_crop_side, orig_right - orig_left)
        box_h = max(min_crop_side, orig_bottom - orig_top)
        side = max(box_w, box_h)
        crop_left = max(0, cx - side // 2)
        crop_top = max(0, cy - side // 2)
        crop_right = min(image.size[0], crop_left + side)
        crop_bottom = min(image.size[1], crop_top + side)
        crop_left = max(0, crop_right - side)
        crop_top = max(0, crop_bottom - side)

        candidate = (crop_left, crop_top, crop_right, crop_bottom)
        duplicate = False

        for prev in out:
            prev_cx = (prev[0] + prev[2]) // 2
            prev_cy = (prev[1] + prev[3]) // 2

            if abs(prev_cx - cx) < side * 0.35 and abs(prev_cy - cy) < side * 0.35:
                duplicate = True
                break

        if duplicate:
            continue

        out.append(candidate)

        if len(out) >= _amir_identifier_int_env("AMIR_SUBJECT_IDENTIFY_MAX_SALIENT_CROPS", 9, 3, 16):
            break

    return out


def _amir_identifier_make_sheet(image, boxes, out_path, tile_size=(300, 220), cols=4):
    try:
        from PIL import Image, ImageOps
    except Exception:
        return False

    tiles = []

    for box in boxes:
        try:
            crop = image.crop(box)
            crop = ImageOps.exif_transpose(crop).convert("RGB")
            crop.thumbnail(tile_size)
            tile = Image.new("RGB", tile_size, (245, 245, 245))
            x = max(0, (tile_size[0] - crop.width) // 2)
            y = max(0, (tile_size[1] - crop.height) // 2)
            tile.paste(crop, (x, y))
            tiles.append(tile)
        except Exception:
            continue

    if not tiles:
        return False

    cols = max(1, min(cols, len(tiles)))
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tile_size[0], rows * tile_size[1]), (245, 245, 245))

    for index, tile in enumerate(tiles):
        sheet.paste(tile, ((index % cols) * tile_size[0], (index // cols) * tile_size[1]))

    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(out_path, format="JPEG", quality=90, optimize=True)
        return True
    except Exception:
        return False


def _amir_identifier_zoom_sheet_paths(image_path):
    if not _amir_subject_identifier_mode():
        return []

    if _amir_subject_os.getenv("AMIR_SUBJECT_IDENTIFY_ZOOM", "1").strip() == "0":
        return []

    try:
        from PIL import Image, ImageOps

        with Image.open(image_path) as raw_image:
            image = ImageOps.exif_transpose(raw_image).convert("RGB")
    except Exception:
        return []

    width, height = image.size

    if width < 300 or height < 300:
        return []

    max_levels = _amir_identifier_int_env("AMIR_SUBJECT_IDENTIFY_ZOOM_LEVELS", 2, 0, 3)
    if max_levels <= 0:
        return []

    digest = hashlib.sha1(str(_amir_subject_Path(image_path).resolve()).encode("utf-8", errors="replace")).hexdigest()[:16]
    out_dir = _amir_subject_Path(__file__).resolve().parent.parent / "data" / "identifier_zoom_tmp" / digest
    created = []

    if max_levels >= 1:
        boxes = _amir_identifier_grid_boxes(width, height, 3, 2, overlap=0.08)
        out_path = out_dir / "zoom_1_grid.jpg"

        if _amir_identifier_make_sheet(image, boxes, out_path, tile_size=(360, 260), cols=3):
            created.append(out_path)

    if max_levels >= 2:
        salient = _amir_identifier_salient_boxes(image)
        grid = _amir_identifier_grid_boxes(width, height, 4, 3, overlap=0.06)
        boxes = []

        for box in salient + grid:
            if box not in boxes:
                boxes.append(box)

            if len(boxes) >= 12:
                break

        out_path = out_dir / "zoom_2_detail.jpg"

        if _amir_identifier_make_sheet(image, boxes, out_path, tile_size=(300, 220), cols=4):
            created.append(out_path)

    if max_levels >= 3:
        boxes = _amir_identifier_grid_boxes(width, height, 5, 4, overlap=0.04)[:16]
        out_path = out_dir / "zoom_3_tight_grid.jpg"

        if _amir_identifier_make_sheet(image, boxes, out_path, tile_size=(260, 200), cols=4):
            created.append(out_path)

    try:
        log(
            "[SUBJECT AI IDENTIFY] zoom sheets "
            f"| image={_amir_subject_Path(image_path).name} | count={len(created)}"
        )
    except Exception:
        pass

    return created


def _amir_taxon_env_labels():
    raw = _amir_subject_os.getenv("AMIR_TAXON_SUBJECT_EXTRA_LABELS", "").strip()

    if not raw:
        return []

    return [
        item.strip().lower()
        for item in _amir_subject_re.split(r"[,;|]+", raw)
        if item.strip()
    ]


def _amir_taxon_labels():
    labels = []
    seen = set()

    for label in list(_AMIR_TAXON_LABELS) + _amir_taxon_env_labels():
        clean = _amir_subject_norm(label)

        if not clean or clean in seen:
            continue

        seen.add(clean)
        labels.append(clean)

    return labels


def _amir_taxon_load_pipe():
    global _AMIR_TAXON_PIPE

    if _AMIR_TAXON_PIPE is not None:
        return _AMIR_TAXON_PIPE

    if _amir_subject_os.getenv("AMIR_TAXON_SUBJECT_ENABLE", "1").strip() == "0":
        return None

    try:
        from transformers import pipeline
    except Exception:
        return None

    model = _amir_subject_os.getenv("AMIR_TAXON_SUBJECT_MODEL", "openai/clip-vit-large-patch14").strip()

    try:
        _AMIR_TAXON_PIPE = pipeline("zero-shot-image-classification", model=model, device=-1)
    except Exception:
        _AMIR_TAXON_PIPE = None

    return _AMIR_TAXON_PIPE


def _amir_taxon_is_broad(label):
    key = _amir_subject_norm(label)

    if key in _AMIR_TAXON_BROAD_LABELS:
        return True

    tokens = set(_amir_subject_re.findall(r"[a-z0-9]+", key))

    return bool(tokens) and tokens <= (
        _AMIR_TAXON_BROAD_LABELS
        | _AMIR_TAXON_WEAK_CONTEXT_WORDS
        | _AMIR_TAXON_VISUAL_ONLY_DESCRIPTOR_ROOTS
        | _AMIR_TAXON_NAME_QUALIFIER_WORDS
    )


def _amir_taxon_is_group_label(label):
    return _amir_subject_norm(label) in _AMIR_TAXON_GROUP_LABELS


def _amir_taxon_is_specific_label(label):
    key = _amir_subject_norm(label)
    return bool(key) and not _amir_taxon_is_broad(key) and not _amir_taxon_is_group_label(key)


def _amir_subject_should_run_taxon_identifier(subject, evidence=""):
    text = f"{subject or ''} {evidence or ''}"
    tokens = set(_amir_subject_re.findall(r"[a-z0-9]+", _amir_subject_norm(text)))

    if not tokens:
        return False

    return bool(tokens & _AMIR_TAXON_IDENTIFIER_TRIGGER_WORDS)


def _amir_subject_mentions_taxon(subject):
    return _amir_subject_should_run_taxon_identifier(subject)


def _amir_subject_underidentified_taxon(subject):
    key = _amir_subject_norm(subject)

    if not key:
        return False

    tokens = set(_amir_subject_re.findall(r"[a-z0-9]+", key))

    if not tokens:
        return False

    broad_roots = {
        "animal",
        "animals",
        "bird",
        "birds",
        "goose",
        "geese",
        "duck",
        "ducks",
        "gull",
        "gulls",
        "pigeon",
        "pigeons",
        "heron",
        "herons",
        "cormorant",
        "cormorants",
        "swan",
        "swans",
        "coot",
        "coots",
        "moorhen",
        "moorhens",
        "raptor",
        "raptors",
        "deer",
        "fox",
        "foxes",
        "rabbit",
        "rabbits",
        "hare",
        "hares",
        "squirrel",
        "squirrels",
        "horse",
        "horses",
        "cow",
        "cows",
        "sheep",
        "dog",
        "dogs",
        "cat",
        "cats",
        "flower",
        "flowers",
        "plant",
        "plants",
        "insect",
        "insects",
        "wildlife",
        "waterfowl",
        "shorebird",
        "shorebirds",
        "wader",
        "waders",
        "butterfly",
        "butterflies",
        "moth",
        "moths",
        "bee",
        "bees",
        "beetle",
        "beetles",
        "dragonfly",
        "dragonflies",
        "damselfly",
        "damselflies",
        "fly",
        "flies",
        "wasp",
        "wasps",
        "spider",
        "spiders",
        "tree",
        "trees",
    }

    if not (tokens & broad_roots):
        return False

    useful = [
        token
        for token in tokens
        if token not in broad_roots
        and token not in _AMIR_TAXON_WEAK_CONTEXT_WORDS
        and token not in _AMIR_TAXON_VISUAL_ONLY_DESCRIPTOR_ROOTS
        and token not in _AMIR_TAXON_NAME_QUALIFIER_WORDS
        and token not in COLOR_WORDS
        and token not in QUANTITY_WORDS
        and token not in ACTION_WORDS
        and token not in LOCATION_NOISE
        and token not in GEAR_NOISE
    ]

    return len(useful) == 0


def _amir_taxon_title(label):
    words = []

    for word in _amir_subject_norm(label).split():
        if word in {"and", "of", "in", "on", "with"}:
            words.append(word.capitalize())
        else:
            words.append(word[:1].upper() + word[1:])

    return " ".join(words).strip()


def _amir_taxon_subject_candidate(image_path):
    pipe = _amir_taxon_load_pipe()

    if pipe is None:
        return "", 0.0, ""

    labels = _amir_taxon_labels()

    if not labels:
        return "", 0.0, ""

    try:
        from PIL import Image, ImageOps

        with Image.open(image_path) as raw_image:
            image = ImageOps.exif_transpose(raw_image).convert("RGB")
    except Exception:
        return "", 0.0, ""

    try:
        preds = pipe(image, candidate_labels=labels)
    except Exception:
        return "", 0.0, ""

    if isinstance(preds, dict) and "labels" in preds and "scores" in preds:
        preds = [
            {"label": label, "score": score}
            for label, score in zip(preds.get("labels") or [], preds.get("scores") or [])
        ]

    preds = list(preds) if isinstance(preds, list) else []
    preds = [
        item
        for item in preds
        if isinstance(item, dict) and str(item.get("label") or "").strip()
    ]

    if not preds:
        return "", 0.0, ""

    preds.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)

    top_label = _amir_subject_norm(preds[0].get("label"))
    top_score = float(preds[0].get("score") or 0.0)
    second_score = float(preds[1].get("score") or 0.0) if len(preds) > 1 else 0.0

    if not top_label or _amir_taxon_is_broad(top_label) or _amir_taxon_is_group_label(top_label):
        return "", top_score, top_label

    min_score = float(_amir_subject_os.getenv("AMIR_TAXON_SUBJECT_MIN_SCORE", "0.16") or "0.16")
    min_margin = float(_amir_subject_os.getenv("AMIR_TAXON_SUBJECT_MIN_MARGIN", "1.08") or "1.08")

    if top_score < min_score:
        return "", top_score, top_label

    if second_score > 0 and top_score < (second_score * min_margin):
        return "", top_score, top_label

    return _amir_taxon_title(top_label), top_score, top_label


def _amir_taxon_evidence_from_raw(raw_text):
    text = str(raw_text or "").strip()

    if not text:
        return ""

    try:
        data = _amir_subject_json.loads(text)

        if isinstance(data, dict):
            parts = []

            for key in ["evidence", "visible_traits", "traits", "reason", "subject"]:
                value = data.get(key)

                if isinstance(value, list):
                    parts.extend(str(item) for item in value if str(item).strip())
                elif value:
                    parts.append(str(value))

            if parts:
                return "; ".join(parts)
    except Exception:
        pass

    return text


def _amir_identifier_data_from_raw(raw_text):
    text = str(raw_text or "").strip()

    if not text:
        return {}

    try:
        data = _amir_subject_json.loads(text)
    except Exception:
        match = _amir_subject_re.search(r"\{[\s\S]*\}", text)

        if not match:
            return {}

        try:
            data = _amir_subject_json.loads(match.group(0))
        except Exception:
            return {}

    return data if isinstance(data, dict) else {}


def _amir_identifier_subject_is_specific_enough(subject, evidence=""):
    subject = _amir_subject_clean(subject)

    if not subject:
        return False

    if _amir_subject_is_garbage(subject):
        return False

    try:
        if "_amir_subject_is_lazy_generic" in globals() and _amir_subject_is_lazy_generic(subject):
            return False
    except Exception:
        pass

    if _amir_taxon_is_group_label(subject) or _amir_taxon_is_broad(subject):
        return False

    if _amir_subject_underidentified_taxon(subject):
        return False

    if not _amir_subject_should_run_taxon_identifier(subject, evidence):
        return True

    broad_roots = set(_AMIR_TAXON_BROAD_LABELS) | {
        "shorebird",
        "shorebirds",
        "wader",
        "waders",
    }
    useful = []

    for token in _amir_subject_re.findall(r"[a-z0-9]+", _amir_subject_norm(subject)):
        root = singular_token(token)

        if not root:
            continue

        if root in broad_roots:
            continue

        if root in _AMIR_TAXON_WEAK_CONTEXT_WORDS:
            continue

        if root in _AMIR_TAXON_VISUAL_ONLY_DESCRIPTOR_ROOTS:
            continue

        if root in _AMIR_TAXON_NAME_QUALIFIER_WORDS:
            continue

        if root in COLOR_WORDS or root in QUANTITY_WORDS or root in ACTION_WORDS:
            continue

        if root in LOCATION_NOISE or root in GEAR_NOISE:
            continue

        useful.append(root)

    return bool(useful)


def _amir_identifier_direct_subject_from_raw(raw_text, original_subject=""):
    data = _amir_identifier_data_from_raw(raw_text)

    if not data:
        return "", 0

    subject = _amir_subject_clean(data.get("subject") or "")
    evidence = _amir_taxon_evidence_from_raw(raw_text)
    confidence = normalize_confidence(data.get("confidence"), default=0)

    if 0 < confidence <= 1:
        confidence = int(round(confidence * 100))

    if subject and _amir_subject_norm(subject) == _amir_subject_norm(original_subject):
        return "", confidence

    if not confidence and subject:
        confidence = int(_amir_subject_os.getenv("AMIR_SUBJECT_IDENTIFY_DIRECT_DEFAULT_CONFIDENCE", "76") or "76")

    min_confidence = int(_amir_subject_os.getenv("AMIR_SUBJECT_IDENTIFY_DIRECT_MIN_CONFIDENCE", "65") or "65")

    if confidence < min_confidence:
        return "", confidence

    if not _amir_identifier_subject_is_specific_enough(subject, evidence):
        return "", confidence

    return subject, confidence


def _amir_taxon_label_keys():
    return {_amir_subject_norm(label) for label in _amir_taxon_labels()}


_AMIR_TAXON_TRAIT_SIGNATURES = {
    "greylag goose": [
        {"goose", "geese", "bird", "birds"},
        {"orange", "pink"},
        {"bill", "bills", "beak", "beaks"},
        {"grey", "gray", "brown"},
        {"barred", "striped", "streaked", "pattern", "patterns"},
    ],
    "canada goose": [
        {"goose", "geese", "bird", "birds"},
        {"black"},
        {"neck", "head"},
        {"white"},
        {"chin", "cheek", "face", "patch"},
    ],
    "roe deer": [
        {"deer", "animal", "wildlife"},
        {"slender", "small", "brown", "tan", "reddish", "grey", "gray"},
        {"ears", "head", "body", "legs", "antlers", "rump"},
    ],
    "red fox": [
        {"fox", "animal", "wildlife"},
        {"red", "orange", "russet", "brown"},
        {"tail", "bushy", "ears", "muzzle"},
    ],
    "rabbit": [
        {"rabbit", "animal", "wildlife"},
        {"ears", "long"},
        {"small", "brown", "grey", "gray", "grass", "field"},
    ],
    "squirrel": [
        {"squirrel", "animal", "wildlife"},
        {"tail", "bushy"},
        {"tree", "branch", "ground", "brown", "grey", "gray", "red"},
    ],
    "horse": [
        {"horse", "horses", "animal"},
        {"mane", "tail", "legs", "grazing", "standing", "field"},
    ],
    "eurasian oystercatcher": [
        {"bird", "birds"},
        {"black"},
        {"white"},
        {"orange", "red"},
        {"bill", "bills", "beak", "beaks"},
    ],
    "purple crocus": [
        {"purple", "violet"},
        {"crocus", "petal", "petals", "flower", "flowers"},
        {"orange", "yellow", "stamen", "stamens"},
    ],
    "red admiral butterfly": [
        {"butterfly"},
        {"black", "dark"},
        {"red", "orange"},
        {"white"},
        {"wing", "wings"},
    ],
    "ladybird beetle": [
        {"ladybird", "ladybug", "beetle"},
        {"red", "orange"},
        {"black"},
        {"spots", "spotted"},
    ],
}


def _amir_taxon_signature_from_evidence(evidence):
    text = _amir_subject_norm(evidence)

    if not text:
        return ""

    tokens = set(_amir_subject_re.findall(r"[a-z0-9]+", text))

    if not tokens:
        return ""

    for label, groups in _AMIR_TAXON_TRAIT_SIGNATURES.items():
        ok = True

        for group in groups:
            if not (tokens & group):
                ok = False
                break

        if ok:
            return _amir_taxon_title(label)

    return ""


def _amir_taxon_refine_from_evidence(subject, raw_text):
    evidence = _amir_taxon_evidence_from_raw(raw_text)

    if not evidence:
        return "", 0

    signature_subject = ""
    if _amir_subject_os.getenv("AMIR_TAXON_USE_TRAIT_SIGNATURES", "0").strip() == "1":
        signature_subject = _amir_taxon_signature_from_evidence(evidence)

    if signature_subject:
        return signature_subject, 88

    model = _amir_subject_os.getenv("AMIR_TAXON_REFINE_MODEL", "qwen2.5vl:3b").strip() or "qwen2.5vl:3b"
    candidates = ", ".join(_amir_taxon_labels())

    prompt = f"""
Return JSON only: {{"subject":"","confidence":0,"reason":""}}
Use general field-guide knowledge, but do not invent.
Current broad or uncertain subject: {subject}
Visible traits from the image: {evidence}
Candidate list: {candidates}
Choose one exact subject from the candidate list only when the visible traits match it.
Return the candidate text exactly as written in the candidate list.
If no candidate is safe, return an empty subject.
Do not use location, filename, folder, camera, or hidden context.
""".strip()

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0.0,
            "num_predict": 160,
            "num_ctx": 4096,
        },
    }

    try:
        request = _amir_subject_urlreq.Request(
            "http://127.0.0.1:11434/api/generate",
            data=_amir_subject_json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with _amir_subject_urlreq.urlopen(request, timeout=120) as response:
            raw = _amir_subject_json.loads(response.read().decode("utf-8", errors="replace"))
    except Exception:
        return "", 0

    response = str(raw.get("response") or "").strip()

    if not response:
        response = str(raw.get("thinking") or "").strip()

    try:
        data = _amir_subject_json.loads(response)
    except Exception:
        match = _amir_subject_re.search(r"\{[\s\S]*\}", response)

        if not match:
            return "", 0

        try:
            data = _amir_subject_json.loads(match.group(0))
        except Exception:
            return "", 0

    if not isinstance(data, dict):
        return "", 0

    refined = _amir_subject_norm(data.get("subject"))
    confidence = normalize_confidence(data.get("confidence"), default=0)

    if 0 < confidence <= 1:
        confidence = int(round(confidence * 100))

    label_keys = _amir_taxon_label_keys()

    if refined not in label_keys:
        return "", confidence

    if _amir_taxon_is_broad(refined) or _amir_taxon_is_group_label(refined):
        return "", confidence

    if confidence < int(_amir_subject_os.getenv("AMIR_TAXON_REFINE_MIN_CONFIDENCE", "70") or "70"):
        return "", confidence

    return _amir_taxon_title(refined), confidence


def _amir_taxon_refine_from_candidate_image(image_path, subject, evidence, model):
    candidates = ", ".join(_amir_taxon_labels())
    prompt = f"""
Return JSON only: {{"subject":"","confidence":0,"reason":""}}

Identify the main visible living or macro subject by choosing from this candidate list only:
{candidates}

Current broad or uncertain subject: {subject}
Visible traits already observed: {evidence or "none"}

Rules:
- Use the image itself as the authority.
- Return the exact candidate-list text only if visible traits support it.
- If the image is too unclear or no candidate is safe, return an empty subject.
- Do not return descriptive fallback phrases such as duck with brown head, bird in flight, animal in grass, flower close up, or insect on leaf.
- Do not use filename, folder, location, camera, or hidden context.
""".strip()

    try:
        raw_text = _amir_subject_call_model(
            image_path=image_path,
            prompt=prompt,
            model=model,
            temperature=0.0,
            num_predict=180,
            json_mode=True,
        )
    except Exception:
        return "", 0

    try:
        data = _amir_subject_json.loads(str(raw_text or "").strip())
    except Exception:
        match = _amir_subject_re.search(r"\{[\s\S]*\}", str(raw_text or ""))
        if not match:
            return "", 0
        try:
            data = _amir_subject_json.loads(match.group(0))
        except Exception:
            return "", 0

    if not isinstance(data, dict):
        return "", 0

    refined = _amir_subject_norm(data.get("subject"))
    confidence = normalize_confidence(data.get("confidence"), default=0)
    if 0 < confidence <= 1:
        confidence = int(round(confidence * 100))

    if refined not in _amir_taxon_label_keys():
        return "", confidence

    if _amir_taxon_is_broad(refined) or _amir_taxon_is_group_label(refined):
        return "", confidence

    if confidence < int(_amir_subject_os.getenv("AMIR_TAXON_CANDIDATE_MIN_CONFIDENCE", "65") or "65"):
        return "", confidence

    return _amir_taxon_title(refined), confidence


def _amir_taxon_refine_from_image(image_path, subject, model):
    prompt = f"""
    Return JSON only:
    {{"subject":"", "confidence":0, "evidence":"visible traits supporting the safest identification"}}

The previous subject was broad or uncertain:
{subject}

    Look only at the main visible living or macro subject. This may be a bird, flower, plant, insect, animal, fungus, or macro detail.
First identify concrete visible traits:
- birds/animals: bill or muzzle color, head pattern, plumage or fur, legs, body shape, posture, wing markings, tail shape, size, habitat.
- flowers/plants/fungi: petal or cap shape, color, center/stamen details, leaf shape, stem structure, growth form.
- insects/macro: wing shape, body pattern, markings, antennae, legs, color pattern, surface texture.
    If a safe common species or narrow common type is visible, put it in subject.
    In strict identify mode, broad descriptive phrases are not valid: color plus broad taxon, plant part plus broad taxon, body part plus taxon, or taxon plus setting.
    If a real common-name style identification is not safe, return an empty subject.
    Outside strict identify mode, if exact species is not safe, use a useful visible-trait subject instead of a bare category.
    Do not use filename, folder, location, camera, or hidden context.
    """.strip()

    try:
        raw_text = _amir_subject_call_model(
            image_path=image_path,
            prompt=prompt,
            model=model,
            temperature=0.0,
            num_predict=220,
            json_mode=True,
        )
    except Exception:
        return "", 0

    if _amir_subject_identifier_mode():
        direct_subject, direct_confidence = _amir_identifier_direct_subject_from_raw(raw_text, subject)

        if direct_subject:
            return direct_subject, direct_confidence

    refined, confidence = _amir_taxon_refine_from_evidence(subject, raw_text)

    if refined:
        return refined, confidence

    evidence = _amir_taxon_evidence_from_raw(raw_text)
    candidate_subject, candidate_confidence = _amir_taxon_refine_from_candidate_image(
        image_path,
        subject,
        evidence,
        model,
    )

    if candidate_subject:
        if not _amir_subject_identifier_mode() or candidate_confidence >= _amir_identifier_target_confidence():
            return candidate_subject, candidate_confidence

        try:
            log(
                "[SUBJECT AI IDENTIFY] below confidence target, trying zoom "
                f"| subject={candidate_subject!r} | confidence={candidate_confidence} "
                f"| target={_amir_identifier_target_confidence()}"
            )
        except Exception:
            pass

    best_subject = candidate_subject
    best_confidence = candidate_confidence if candidate_subject else 0

    if _amir_subject_identifier_mode():
        for zoom_path in _amir_identifier_zoom_sheet_paths(image_path):
            zoom_subject, zoom_confidence = _amir_taxon_refine_from_candidate_image(
                zoom_path,
                subject,
                evidence,
                model,
            )

            try:
                log(
                    "[SUBJECT AI IDENTIFY] zoom result "
                    f"| zoom={_amir_subject_Path(zoom_path).name} "
                    f"| subject={zoom_subject!r} | confidence={zoom_confidence}"
                )
            except Exception:
                pass

            if zoom_subject and (not best_subject or zoom_confidence >= best_confidence):
                best_subject = zoom_subject
                best_confidence = zoom_confidence

            if best_subject and best_confidence >= _amir_identifier_target_confidence():
                return best_subject, best_confidence

        if best_subject:
            try:
                log(
                    "[SUBJECT AI IDENTIFY] stopped below confidence target "
                    f"| subject={best_subject!r} | confidence={best_confidence} "
                    f"| target={_amir_identifier_target_confidence()}"
                )
            except Exception:
                pass

            return "", best_confidence

        try:
            log("[SUBJECT AI IDENTIFY] stopped after zoom retries with no confident taxon")
        except Exception:
            pass

        return "", best_confidence

    if candidate_subject:
        return candidate_subject, candidate_confidence

    try:
        data = _amir_subject_json.loads(raw_text)
    except Exception:
        data = {}

    if isinstance(data, dict):
        direct_subject = _amir_subject_norm(data.get("subject"))

        if direct_subject and direct_subject in _amir_taxon_label_keys() and _amir_taxon_is_specific_label(direct_subject):
            return _amir_taxon_title(direct_subject), 78

    return "", confidence
# AMIR_TAXONOMIC_SUBJECT_SUPPORT_V1_END


_AMIR_LAST_DIRECT_SUBJECT_EVIDENCE = ""


def _amir_subject_evidence_from_model_raw(raw_text):
    text = str(raw_text or "").strip()

    if not text:
        return ""

    data = None

    try:
        data = _amir_subject_json.loads(text)
    except Exception:
        match = _amir_subject_re.search(r"\{[\s\S]*\}", text)

        if match:
            try:
                data = _amir_subject_json.loads(match.group(0))
            except Exception:
                data = None

    if not isinstance(data, dict):
        return ""

    parts = []

    for key in ["evidence", "visible_traits", "traits", "reason", "primary_focus_reason"]:
        value = data.get(key)

        if isinstance(value, list):
            parts.extend(clean_text(item) for item in value if clean_text(item))
        else:
            value = clean_text(value)

            if value:
                parts.append(value)

    return clean_text(" ".join(parts))


def _amir_subject_direct_model_subject(image_path, force_regenerate=False, hints="", current_subject=""):
    global _AMIR_LAST_DIRECT_SUBJECT_EVIDENCE
    _AMIR_LAST_DIRECT_SUBJECT_EVIDENCE = ""
    models = _amir_subject_direct_model_candidates(force_regenerate=force_regenerate)

    hints = str(hints or "").strip()
    current_subject = str(current_subject or "").strip()

    if hints:
        hint_text = f"""
Optional soft hints from the user:
{hints}

Use these hints only if they match what is visibly in the image.
Do not copy the hint list blindly.
Do not invent hidden objects from hints.
If a hint names a visible role, activity, object, or setting, prefer that natural word in the subject.
When regenerate has hints, create a better subject phrase that combines the visible main subject with matching hint concepts.
""".strip()
    else:
        hint_text = "No user hints. Use the image only."

    if current_subject:
        current_text = f"""
Current subject already shown in the app:
{current_subject}

Do not return exactly the same subject on regenerate.
Give a different valid subject phrase based on the image.
""".strip()
    else:
        current_text = ""

    identify_contract = ""

    if _amir_subject_identifier_mode():
        identify_contract = """
Strict Identify mode:
- For living or macro subjects, return a real common-name style identification when the visible evidence supports it.
- Broad descriptive phrases are not valid: color plus broad taxon, plant part plus broad taxon, body part plus taxon, or taxon plus setting.
- If you cannot safely identify beyond a broad visual description, return {"subject": "", "confidence": 0, "evidence": "why the image is not identifiable enough"}.
- Do not use filename, folder, location, camera, or hidden context.
""".strip()

    prompts = []

    prompts.append(
        f"""
You are identifying the main visible subject of a real photograph.

Return JSON only:
{{"subject": "short subject", "confidence": 0, "evidence": "short visible traits supporting the subject"}}

Rules:
- The subject must be 2 to 7 normal English words.
- Name the main visible subject.
- For birds, flowers, plants, insects, and animals, prefer the safest common species or common group name when visible traits support it.
- Use visible traits such as bill color, wing shape, leg color, flower shape, petal color, insect body pattern, markings, and habitat before choosing a broad label.
- Do not return bare taxonomy labels like birds, animals, flowers, plants, insects, wildlife, or waterfowl when a more useful visible name is possible.
- Include visible action, count, setting, or context only when it helps identify the subject.
- Prefer visible activity, role, object, and setting over clothing or accessory details.
- Use clothing or accessory details only when they are the main meaningful subject.
- Do not name a specific machine, structure, vehicle, or tool unless it is clearly visible.
- If the exact equipment or structure is uncertain, use a broader role or action phrase.
- If exact species is uncertain, use a useful descriptive taxon phrase with visible traits instead of a bare category.
- Use user hints only when they are visibly supported by the image.
- Do not output codes, hashes, coordinates, colors only, camera words, or random tokens.
- Do not write a caption.
- Do not describe image quality.
- On regenerate, produce a different useful wording.

{identify_contract}

{current_text}

{hint_text}

Good examples:
{{"subject": "Workers On Scaffolding"}}
{{"subject": "Boat With Water Reflection"}}
{{"subject": "Flower Branches In Blossom"}}
{{"subject": "Wading Birds With Orange Bills"}}
{{"subject": "Butterfly On Flower Head"}}
{{"subject": "Building Facade With Reflection"}}
""".strip()
    )

    prompts.append(
        f"""
Look at the image again and return a better alternative subject phrase.

Return JSON only:
{{"subject": "short subject"}}

Current rejected wording:
{current_subject}

Soft hints:
{hints}

Rules:
- Do not copy the hint list.
- Do not return the current rejected wording.
- Use hints only when visually compatible.
- If a hint is visually compatible, use it to make the subject more specific.
- If the image shows birds, flowers, plants, insects, or animals, use the safest common species or common group name supported by visible traits.
- Do not return bare taxonomy labels like birds, animals, flowers, plants, insects, wildlife, or waterfowl when a more useful visible name is possible.
- Prefer a natural subject phrase with visible context when useful.
- Prefer visible role, action, object, and setting over clothing or accessory wording.
- Do not guess a specific machine, structure, vehicle, or tool from hints alone.
- If the exact equipment or structure is uncertain, use broader role or action wording.
- 2 to 7 words.
""".strip()
    )

    if _amir_subject_identifier_mode():
        prompts = prompts[:1]

    last_raw = ""
    last_cleaned = ""
    last_model = models[0] if models else "qwen2.5vl:3b"

    for model in models:
        last_model = model

        for attempt, prompt in enumerate(prompts, start=1):
            try:
                raw_text = _amir_subject_call_model(
                    image_path=image_path,
                    prompt=prompt,
                    model=model,
                    temperature=0.2 if force_regenerate else 0.0,
                    json_mode=True,
                )
            except Exception as exc:
                try:
                    log(f"[SUBJECT AI MODEL] failed | model={model} | {type(exc).__name__}: {exc}")
                except Exception:
                    print(f"[SUBJECT AI MODEL] failed | model={model} | {type(exc).__name__}: {exc}")

                break

            _AMIR_LAST_DIRECT_SUBJECT_EVIDENCE = _amir_subject_evidence_from_model_raw(raw_text)
            subject = _amir_subject_clean(raw_text)
            subject = _amir_subject_broaden_unprompted_specific(subject, hints, current_subject)

            if _amir_subject_identifier_mode() and subject:
                direct_subject, direct_confidence = _amir_identifier_direct_subject_from_raw(raw_text, current_subject)

                if direct_subject:
                    try:
                        log(
                            "[SUBJECT AI IDENTIFY] direct specific accepted "
                            f"| old={subject!r} | new={direct_subject!r} | confidence={direct_confidence}"
                        )
                    except Exception:
                        pass

                    subject = direct_subject

            if (
                _amir_subject_identifier_mode()
                and subject
                and "_amir_subject_should_run_taxon_identifier" in globals()
                and _amir_subject_should_run_taxon_identifier(subject, raw_text)
            ):
                taxon_subject = ""
                taxon_score = 0.0
                taxon_label = ""
                underidentified_taxon = bool(
                    (
                        "_amir_subject_underidentified_taxon" in globals()
                        and _amir_subject_underidentified_taxon(subject)
                    )
                    or (
                        "_amir_taxon_is_group_label" in globals()
                        and _amir_taxon_is_group_label(subject)
                    )
                    or (
                        "_amir_taxon_is_broad" in globals()
                        and _amir_taxon_is_broad(subject)
                    )
                )

                if "_amir_taxon_subject_candidate" in globals():
                    taxon_subject, taxon_score, taxon_label = _amir_taxon_subject_candidate(image_path)

                strong_specific_taxon = bool(
                    taxon_subject
                    and "_amir_taxon_is_specific_label" in globals()
                    and _amir_taxon_is_specific_label(taxon_subject)
                    and taxon_score >= float(_amir_subject_os.getenv("AMIR_TAXON_OVERRIDE_MIN_SCORE", "0.35") or "0.35")
                )

                if strong_specific_taxon:
                    try:
                        log(
                            "[SUBJECT AI TAXON] upgraded taxonomic subject "
                            f"| old={subject!r} | new={taxon_subject!r} | score={taxon_score:.3f} | label={taxon_label}"
                        )
                    except Exception:
                        pass

                    subject = taxon_subject
                elif underidentified_taxon:
                    refined_subject = ""
                    refined_confidence = 0

                    if "_amir_taxon_refine_from_evidence" in globals():
                        refined_subject, refined_confidence = _amir_taxon_refine_from_evidence(subject, raw_text)

                    if not refined_subject and "_amir_taxon_refine_from_image" in globals():
                        refined_subject, refined_confidence = _amir_taxon_refine_from_image(image_path, subject, model)

                    if refined_subject:
                        try:
                            log(
                                "[SUBJECT AI TAXON] field-guide refined broad subject "
                                f"| old={subject!r} | new={refined_subject!r} | confidence={refined_confidence}"
                            )
                        except Exception:
                            pass

                        subject = refined_subject
                    elif taxon_subject and not _amir_subject_identifier_mode():
                        try:
                            log(
                                "[SUBJECT AI TAXON] kept safer taxonomic group "
                                f"| old={subject!r} | new={taxon_subject!r} | score={taxon_score:.3f} | label={taxon_label}"
                            )
                        except Exception:
                            pass

                        subject = taxon_subject
                    else:
                        try:
                            log(
                                "[SUBJECT AI TAXON] rejected underidentified subject "
                                f"| subject={subject!r} | top={taxon_label!r} | score={taxon_score:.3f}"
                            )
                        except Exception:
                            pass

                        subject = ""
                elif taxon_subject and taxon_score >= float(_amir_subject_os.getenv("AMIR_TAXON_GROUP_NOTE_MIN_SCORE", "0.60") or "0.60"):
                    try:
                        log(
                            "[SUBJECT AI TAXON] model subject kept with classifier note "
                            f"| subject={subject!r} | classifier={taxon_subject!r} | score={taxon_score:.3f} | label={taxon_label}"
                        )
                    except Exception:
                        pass

            last_raw = raw_text
            last_cleaned = subject

            same_as_current = bool(current_subject) and _amir_subject_same_regen_frame(subject, current_subject)
            weak_result = _amir_subject_is_weak_regen_subject(subject, hints)
            hint_tokens = set(_amir_subj_hint_tokens(hints)) if hints else set()
            subject_tokens = set(_amir_subj_hint_tokens(subject)) if subject else set()
            hint_used = bool(hint_tokens & subject_tokens)
            needs_hint_second_pass = bool(
                force_regenerate
                and hint_tokens
                and attempt == 1
                and subject
                and not hint_used
            )

            try:
                log(
                    f"[SUBJECT AI MODEL] attempt={attempt} model={model} "
                    f"hints={'yes' if hints else 'no'} current={current_subject!r} "
                    f"raw={raw_text!r} cleaned={subject!r} "
                    f"same_current={same_as_current} weak={weak_result} "
                    f"hint_used={hint_used} second_pass={needs_hint_second_pass}"
                )
            except Exception:
                print(
                    f"[SUBJECT AI MODEL] attempt={attempt} model={model} "
                    f"hints={'yes' if hints else 'no'} current={current_subject!r} "
                    f"raw={raw_text!r} cleaned={subject!r} "
                    f"same_current={same_as_current} weak={weak_result} "
                    f"hint_used={hint_used} second_pass={needs_hint_second_pass}"
                )

            if subject and not same_as_current and not weak_result:
                if needs_hint_second_pass:
                    continue

                return subject, model, hints

    if current_subject and _amir_subject_same_regen_frame(last_cleaned, current_subject):
        return "", last_model, hints

    return last_cleaned, last_model, hints


try:
    _amir_original_analyze_one_image_proper_regen_v2
except NameError:
    _amir_original_analyze_one_image_proper_regen_v2 = analyze_one_image


def analyze_one_image(*args, **kwargs):
    ctx = _amir_subject_read_context()
    context_file_explicit = bool(_amir_subject_os.getenv("AMIR_SUBJECT_CONTEXT_FILE", "").strip())
    env_regenerate = _amir_subject_os.getenv("AMIR_SUBJECT_REGENERATE", "").strip() == "1"
    context_regenerate = context_file_explicit and bool(ctx.get("active"))

    force_regenerate = env_regenerate or context_regenerate

    soft_hints = str(ctx.get("hints") or "").strip() if force_regenerate else ""
    current_subject = str(ctx.get("current_subject") or "").strip() if force_regenerate else ""

    row = None
    image_path = _amir_subject_find_image_path(args, kwargs)
    identify_mode = _amir_subject_identifier_mode()

    if not force_regenerate and not soft_hints:
        if image_path is not None and _amir_subject_os.getenv("AMIR_SUBJECT_DIRECT_NORMAL", "1").strip() != "0":
            try:
                subject, model, hints = _amir_subject_direct_model_subject(
                    image_path=image_path,
                    force_regenerate=False,
                    hints="",
                    current_subject="",
                )

                if subject and not _amir_subject_is_weak_regen_subject(subject, ""):
                    model_evidence = clean_text(globals().get("_AMIR_LAST_DIRECT_SUBJECT_EVIDENCE", ""))
                    if not model_evidence:
                        model_evidence = "Generic direct vision subject route."

                    try:
                        log(f"[SUBJECT AI MODEL] normal direct accepted | {image_path.name} | {subject} | model={model}")
                    except Exception:
                        print(f"[SUBJECT AI MODEL] normal direct accepted | {image_path.name} | {subject} | model={model}")

                    return {
                        "image": str(image_path),
                        "image_name": image_path.name,
                        "accepted": True,
                        "subject": subject,
                        "specific": subject,
                        "descriptive": subject,
                        "category": "vision_direct",
                        "confidence": 82,
                        "score": 82,
                        "model": model,
                        "source": "vision_model_image_only",
                        "evidence": model_evidence,
                        "reason": model_evidence,
                        "attempts": [],
                    }

                if identify_mode:
                    try:
                        log(
                            "[SUBJECT AI IDENTIFY] stopped "
                            f"| {image_path.name} | no confident specific subject after bounded zoom retries"
                        )
                    except Exception:
                        print(
                            "[SUBJECT AI IDENTIFY] stopped "
                            f"| {image_path.name} | no confident specific subject after bounded zoom retries"
                        )

                    return {
                        "image": str(image_path),
                        "image_name": image_path.name,
                        "accepted": False,
                        "subject": "",
                        "specific": "",
                        "descriptive": "",
                        "category": "identify_no_confident_subject",
                        "confidence": 0,
                        "score": 0,
                        "model": model,
                        "source": "identify_zoom_limited",
                        "evidence": "Identify stopped after full-frame and zoom retries.",
                        "reason": "Identify could not confidently resolve a specific visible subject.",
                        "notes": "Identify could not confidently resolve a specific visible subject.",
                        "attempts": [],
                    }
            except Exception as exc:
                try:
                    log(f"[SUBJECT AI MODEL] normal direct failed | {type(exc).__name__}: {exc}")
                except Exception:
                    print(f"[SUBJECT AI MODEL] normal direct failed | {type(exc).__name__}: {exc}")

                if identify_mode:
                    return {
                        "image": str(image_path),
                        "image_name": image_path.name,
                        "accepted": False,
                        "subject": "",
                        "specific": "",
                        "descriptive": "",
                        "category": "identify_error",
                        "confidence": 0,
                        "score": 0,
                        "model": "",
                        "source": "identify_zoom_limited",
                        "evidence": f"{type(exc).__name__}: {exc}",
                        "reason": f"Identify failed before fallback: {type(exc).__name__}: {exc}",
                        "notes": f"Identify failed before fallback: {type(exc).__name__}: {exc}",
                        "attempts": [],
                    }

        row = _amir_original_analyze_one_image_proper_regen_v2(*args, **kwargs)

        try:
            if isinstance(row, dict):
                existing_subject = str(row.get("subject") or "").strip()
                accepted = bool(row.get("accepted"))

                if existing_subject and accepted and not _amir_subject_is_garbage(existing_subject):
                    row_evidence = ""
                    try:
                        if "_amir_set_attempt_values" in globals():
                            row_evidence = " ".join(_amir_set_attempt_values([row]))
                    except Exception:
                        row_evidence = ""
                    taxon_identifier_needed = bool(
                        _amir_subject_identifier_mode()
                        and "_amir_subject_should_run_taxon_identifier" in globals()
                        and _amir_subject_should_run_taxon_identifier(existing_subject, row_evidence)
                    )
                    underidentified_existing_taxon = bool(
                        taxon_identifier_needed
                        and (
                            (
                                "_amir_subject_underidentified_taxon" in globals()
                                and _amir_subject_underidentified_taxon(existing_subject)
                            )
                            or (
                                "_amir_taxon_is_group_label" in globals()
                                and _amir_taxon_is_group_label(existing_subject)
                            )
                            or (
                                "_amir_taxon_is_broad" in globals()
                                and _amir_taxon_is_broad(existing_subject)
                            )
                        )
                    )
                    if (
                        image_path is not None
                        and underidentified_existing_taxon
                    ):
                        taxon_subject = ""
                        taxon_score = 0.0
                        taxon_label = ""

                        if "_amir_taxon_subject_candidate" in globals():
                            taxon_subject, taxon_score, taxon_label = _amir_taxon_subject_candidate(image_path)

                        refined_subject = ""
                        refined_confidence = 0

                        if "_amir_taxon_refine_from_image" in globals():
                            refined_subject, refined_confidence = _amir_taxon_refine_from_image(image_path, existing_subject, str(row.get("model") or "qwen2.5vl:3b"))

                        if refined_subject:
                            row = dict(row)
                            row.update(
                                {
                                    "subject": refined_subject,
                                    "specific": refined_subject,
                                    "descriptive": refined_subject,
                                    "confidence": max(normalize_confidence(row.get("confidence"), default=0), refined_confidence, 78),
                                    "score": max(normalize_confidence(row.get("score"), default=0), refined_confidence, 78),
                                    "source": "taxonomic_subject_refiner",
                                    "reason": f"Generic taxonomic refiner upgraded broad subject from {existing_subject!r}.",
                                }
                            )
                            try:
                                log(
                                    "[SUBJECT AI TAXON] refined accepted row "
                                    f"| old={existing_subject!r} | new={refined_subject!r} | confidence={refined_confidence}"
                                )
                            except Exception:
                                pass
                            return row

                        if taxon_subject:
                            row = dict(row)
                            row.update(
                                {
                                    "subject": taxon_subject,
                                    "specific": taxon_subject,
                                    "descriptive": taxon_subject,
                                    "confidence": max(normalize_confidence(row.get("confidence"), default=0), 78),
                                    "score": max(normalize_confidence(row.get("score"), default=0), 78),
                                    "source": "taxonomic_subject_classifier",
                                    "reason": f"Generic taxonomic classifier upgraded broad subject from {existing_subject!r}.",
                                }
                            )
                            try:
                                log(
                                    "[SUBJECT AI TAXON] upgraded accepted row "
                                    f"| old={existing_subject!r} | new={taxon_subject!r} | score={taxon_score:.3f} | label={taxon_label}"
                                )
                            except Exception:
                                pass
                            return row

                        row = dict(row)
                        row["accepted"] = False
                        row["reason"] = f"Underidentified taxonomic subject: {existing_subject}"
                        row["notes"] = row["reason"]
                        try:
                            log(
                                "[SUBJECT AI TAXON] blocked underidentified accepted row "
                                f"| subject={existing_subject!r} | top={taxon_label!r} | score={taxon_score:.3f}"
                            )
                        except Exception:
                            pass
                        return row

                    return row
        except Exception:
            pass
    else:
        row = {}

    if image_path is None:
        if row is not None:
            return row

        return {}

    try:
        subject, model, hints = _amir_subject_direct_model_subject(
            image_path=image_path,
            force_regenerate=force_regenerate,
            hints=soft_hints,
            current_subject=current_subject,
        )
    except Exception as exc:
        try:
            log(f"[SUBJECT AI MODEL] failed | {type(exc).__name__}: {exc}")
        except Exception:
            print(f"[SUBJECT AI MODEL] failed | {type(exc).__name__}: {exc}")

        if row is not None:
            return row

        return {}

    if not subject:
        if row is not None:
            return row

        return {}

    new_row = dict(row) if isinstance(row, dict) else {}
    model_evidence = clean_text(globals().get("_AMIR_LAST_DIRECT_SUBJECT_EVIDENCE", ""))
    if not model_evidence:
        model_evidence = "Generic vision model accepted. Hints were soft evidence only." if hints else "Generic vision model accepted."

    new_row.update(
        {
            "subject": subject,
            "specific": subject,
            "descriptive": subject,
            "accepted": True,
            "confidence": 80 if force_regenerate else 75,
            "score": 80 if force_regenerate else 75,
            "source": "vision_model_soft_hint" if hints else "vision_model_image_only",
            "model": model,
            "evidence": model_evidence,
            "reason": model_evidence,
        }
    )

    try:
        log(f"[SUBJECT AI MODEL] accepted | {image_path.name} | {subject}")
    except Exception:
        print(f"[SUBJECT AI MODEL] accepted | {image_path.name} | {subject}")

    return new_row
# AMIR_SUBJECT_PROPER_MODEL_REGENERATE_V2_END

# AMIR_SET_SUBJECT_DIVERSITY_GUARD_V1_START
# Generic set-subject guard.
# No folder rules. No topic rules. No hard-coded current-image fixes.
# The problem this solves is structural:
# - edge-only sampling can skip a distinct middle frame
# - two matching detail labels can overrule a broader mixed set
# - regenerate must get a true second opinion, not the same current subject as a hint

_AMIR_SET_DETAIL_WORDS = {
    "detail",
    "details",
    "closeup",
    "closeups",
    "close",
    "macro",
    "texture",
    "pattern",
    "fragment",
    "part",
    "portion",
}

_AMIR_SET_CONTEXT_SKIP_WORDS = {
    "none",
    "unknown",
    "specific",
    "alternative",
    "main",
    "primary",
    "subject",
    "visible",
    "image",
    "photo",
    "photograph",
    "background",
    "foreground",
    "central",
    "prominent",
    "clear",
    "detailed",
    "detail",
    "details",
    "architecture",
    "architectural",
}

_AMIR_SET_CONNECTOR_WORDS = {
    "a",
    "an",
    "and",
    "across",
    "against",
    "along",
    "around",
    "at",
    "behind",
    "beside",
    "between",
    "by",
    "for",
    "from",
    "in",
    "inside",
    "into",
    "near",
    "of",
    "on",
    "or",
    "outside",
    "over",
    "the",
    "through",
    "to",
    "under",
    "with",
    "without",
}


def _amir_set_unique_paths(paths):
    seen = set()
    out = []

    for path in paths or []:
        key = str(path)

        if key in seen:
            continue

        seen.add(key)
        out.append(path)

    return out


def _amir_set_pick_by_fraction(paths, fraction):
    if not paths:
        return None

    last = len(paths) - 1
    return paths[max(0, min(last, int(round(last * fraction))))]


def _amir_subj_initial_samples(paths):
    paths = list(paths or [])

    if len(paths) <= 3:
        return paths[:]

    return _amir_set_unique_paths([
        paths[0],
        _amir_set_pick_by_fraction(paths, 0.50),
        paths[-1],
    ])


def _amir_subj_extra_samples(paths):
    paths = list(paths or [])

    if len(paths) <= 3:
        return []

    candidates = [
        _amir_set_pick_by_fraction(paths, 0.16),
        _amir_set_pick_by_fraction(paths, 0.33),
        _amir_set_pick_by_fraction(paths, 0.67),
        _amir_set_pick_by_fraction(paths, 0.25),
        _amir_set_pick_by_fraction(paths, 0.75),
    ]

    if len(paths) >= 12:
        candidates.extend([paths[1], paths[-2]])

    initial = {str(path) for path in _amir_subj_initial_samples(paths)}
    max_total = min(max(3, int(MAX_IMAGES)), 6, len(paths))
    out = []

    for path in _amir_set_unique_paths([item for item in candidates if item is not None]):
        if str(path) in initial:
            continue

        out.append(path)

        if len(out) + len(initial) >= max_total:
            break

    return out


def choose_samples(paths: list[_amir_subj_Path], max_images: int) -> list[_amir_subj_Path]:
    paths = list(paths or [])

    if not paths:
        return []

    target_count = min(max(1, int(max_images or 1)), 6, len(paths))

    if len(paths) > 2:
        target_count = max(target_count, min(3, len(paths)))

    return _amir_set_unique_paths(_amir_subj_initial_samples(paths) + _amir_subj_extra_samples(paths))[:target_count]


def _amir_subj_accepted_rows(rows):
    return [
        row
        for row in rows or []
        if isinstance(row, dict) and row.get("accepted") and clean_text(row.get("subject"))
    ]


def _amir_subj_result_coverage(rows, subject):
    subject = clean_text(subject)
    accepted = _amir_subj_accepted_rows(rows)

    if not subject or not accepted:
        return {
            "accepted": accepted,
            "similarities": [],
            "coverage": 0.0,
            "strong_conflict": False,
            "category_mixed": False,
        }

    similarities = [
        _amir_subj_similarity(subject, clean_text(row.get("subject")))
        for row in accepted
    ]
    covered = sum(1 for value in similarities if value >= 0.50)
    categories = {
        _amir_subj_norm(row.get("category"))
        for row in accepted
        if _amir_subj_norm(row.get("category"))
    }

    return {
        "accepted": accepted,
        "similarities": similarities,
        "coverage": covered / max(1, len(accepted)),
        "strong_conflict": any(value < 0.30 for value in similarities),
        "category_mixed": len(categories) > 1,
    }


def _amir_subj_has_uncovered_evidence(rows, subject):
    coverage = _amir_subj_result_coverage(rows, subject)

    if len(coverage["accepted"]) < 3:
        return False

    if coverage["strong_conflict"]:
        return True

    if coverage["category_mixed"] and coverage["coverage"] < 0.80:
        return True

    return coverage["coverage"] < 0.67


def _amir_subj_rows_agree(rows, result):
    if not getattr(result, "subject", ""):
        return False

    if int(getattr(result, "confidence", 0) or 0) < 85:
        return False

    accepted_subjects = [
        clean_text(row.get("subject"))
        for row in _amir_subj_accepted_rows(rows)
    ]

    if len(accepted_subjects) < 2:
        return False

    # For multi-image sets, do not stop after only two agreeing samples.
    # A third sample is the cheapest generic diversity check.
    if len(accepted_subjects) == 2:
        return False

    base = str(getattr(result, "subject", "") or accepted_subjects[0])

    if _amir_subj_has_uncovered_evidence(rows, base):
        try:
            coverage = _amir_subj_result_coverage(rows, base)
            log(
                "[SUBJECT AI] adaptive continue | uncovered sampled evidence "
                f"| coverage={coverage['coverage']:.2f} | category_mixed={coverage['category_mixed']}"
            )
        except Exception:
            pass

        return False

    similar = [
        subject
        for subject in accepted_subjects
        if _amir_subj_similarity(base, subject) >= 0.50
    ]

    return len(similar) >= max(2, int(round(len(accepted_subjects) * 0.67)))


def _amir_set_subject_is_narrow_detail(subject):
    tokens = set(_amir_subj_tokens(subject))

    if not tokens:
        return False

    return bool(tokens & _AMIR_SET_DETAIL_WORDS)


def _amir_set_attempt_values(row):
    values = []

    if not isinstance(row, dict):
        return values

    for value in [row.get("subject"), row.get("specific"), row.get("descriptive"), row.get("evidence"), row.get("reason")]:
        value = clean_text(value)

        if value:
            values.append(value)

    for attempt in row.get("attempts", []) or []:
        if not isinstance(attempt, dict):
            continue

        for key in [
            "subject_text",
            "specific_name",
            "descriptive_subject",
            "group_subject",
            "action_or_state",
            "setting",
            "primary_focus_reason",
            "visible_text",
        ]:
            value = clean_text(attempt.get(key))

            if value:
                values.append(value)

        for key in ["visible_traits", "keywords_seed"]:
            items = attempt.get(key)

            if isinstance(items, list):
                values.extend(clean_text(item) for item in items if clean_text(item))

        for alt in attempt.get("alternatives", []) or []:
            if isinstance(alt, dict):
                value = clean_text(alt.get("name"))

                if value:
                    values.append(value)

    return values


def _amir_set_context_phrase_score(phrase, evidence_text, positive_hints):
    phrase = clean_subject_label(phrase, max_words=6, max_chars=55)

    if not phrase:
        return -999

    key = _amir_subj_norm(phrase)
    tokens = [token for token in _amir_subj_tokens(phrase) if token not in _AMIR_SET_CONTEXT_SKIP_WORDS]

    if len(tokens) < 2:
        return -999

    if _amir_set_subject_is_narrow_detail(phrase):
        return -999

    if key in _AMIR_SUBJECT_BAD:
        return -999

    if _amir_subject_identifier_mode():
        if (
            "_amir_subject_underidentified_taxon" in globals()
            and _amir_subject_underidentified_taxon(phrase)
        ):
            return -999

        if "_amir_taxon_is_group_label" in globals() and _amir_taxon_is_group_label(phrase):
            return -999

    score = len(set(tokens)) * 8

    for hint in positive_hints:
        hint_tokens = set(_amir_subj_tokens(hint))

        if hint_tokens and hint_tokens <= set(tokens) and all(token in evidence_text for token in hint_tokens):
            score += 35

    if any(token in {"scene", "view", "setting", "surroundings", "reflection", "reflections"} for token in tokens):
        score += 10

    if "background" in key or "foreground" in key:
        score -= 20

    return score


def _amir_set_synthesize_context_subject(rows, fallback_subject=""):
    values = []

    for row in rows or []:
        values.extend(_amir_set_attempt_values(row))

    evidence_text = _amir_subj_norm(" ".join(values))
    hints = _amir_subj_hint_get() if "_amir_subj_hint_get" in globals() else ""
    if not hints and "_amir_subject_read_context" in globals():
        try:
            hints = str((_amir_subject_read_context() or {}).get("hints") or "").strip()
        except Exception:
            hints = ""
    positive_hints, _negative = _amir_subj_hint_parse(hints) if "_amir_subj_hint_parse" in globals() else ([], [])

    candidates = []

    for value in values:
        value = clean_subject_label(value, max_words=6, max_chars=55)

        if value:
            candidates.append(value)

    visible_hints = []

    for hint in positive_hints:
        hint_tokens = [token for token in _amir_subj_tokens(hint) if token not in _AMIR_SET_CONTEXT_SKIP_WORDS]

        if hint_tokens and all(token in evidence_text for token in hint_tokens):
            visible_hints.extend(hint_tokens)

    visible_hints = list(dict.fromkeys(visible_hints))

    if len(visible_hints) >= 2:
        candidates.append(smart_title(" ".join(visible_hints[:3] + ["scene"])))

    scored = []

    for order, candidate in enumerate(candidates):
        score = _amir_set_context_phrase_score(candidate, evidence_text, positive_hints)

        if score > -999:
            scored.append((score, len(_amir_subj_tokens(candidate)), -order, candidate))

    if not scored:
        return ""

    scored.sort(reverse=True)

    for _score, _token_count, _order, candidate in scored:
        chosen = clean_subject_label(candidate, max_words=6, max_chars=55)

        if chosen and norm_key(chosen) != norm_key(fallback_subject):
            if not _amir_set_group_subject_ok(
                chosen,
                allow_identify_descriptive=False,
            ):
                continue

            support = _amir_set_group_support(rows, chosen)

            if not support["ok"]:
                try:
                    log(
                        "[SUBJECT AI] set synth ignored unsupported subject "
                        f"| subject={chosen!r} "
                        f"| coverage={support['coverage']:.2f} "
                        f"| max_root_support={support['max_root_support']:.2f} "
                        f"| min_root_support={support.get('min_root_support', 0.0):.2f}"
                    )
                except Exception:
                    pass
                continue

            return chosen

    return ""


_AMIR_SET_GROUP_BAD = {
    "outdoor scene",
    "outdoor scenes",
    "nature scene",
    "nature scenes",
    "landscape",
    "landscapes",
    "travel scene",
    "travel scenes",
    "mixed photos",
    "mixed images",
    "photo set",
    "image set",
    "photography",
    "various subjects",
    "selected photos",
}

_AMIR_SET_GROUP_UNGROUNDED_CONTEXT_WORDS = {
    "african",
    "american",
    "asian",
    "british",
    "dutch",
    "english",
    "european",
    "french",
    "german",
    "italian",
    "scottish",
    "spanish",
}

_AMIR_SET_GROUP_FILLER_WORDS = {
    "image",
    "images",
    "landscape",
    "landscapes",
    "photo",
    "photos",
    "scene",
    "scenes",
    "view",
    "views",
}


def _amir_set_clean_group_label(value, max_words=7, max_chars=70):
    cleaner = globals().get("_AMIR_ORIGINAL_CLEAN_SUBJECT_LABEL")

    if callable(cleaner):
        subject = cleaner(value, max_words=max_words, max_chars=max_chars)
    else:
        subject = _amir_subject_clean(value)

        words = subject.split()

        if len(words) > max_words:
            subject = " ".join(words[:max_words])

        if len(subject) > max_chars:
            subject = subject[:max_chars].rsplit(" ", 1)[0].strip()

    words = str(subject or "").strip().split()
    while words and words[0].lower() in _AMIR_SET_CONNECTOR_WORDS:
        words.pop(0)
    while words and words[-1].lower() in _AMIR_SET_CONNECTOR_WORDS:
        words.pop()

    useful_words = [word for word in words if word.lower() not in _AMIR_SET_GROUP_FILLER_WORDS]

    if len(useful_words) >= 2:
        subject = " ".join(useful_words)
    else:
        subject = " ".join(words)

    return smart_title(str(subject or "").strip())


def _amir_set_group_subject_ok(subject, *, allow_identify_descriptive=False):
    subject = _amir_set_clean_group_label(subject, max_words=7, max_chars=70)

    if not subject:
        return False

    key = _amir_subj_norm(subject)

    if re.search(r"\band\s+[a-z]+ed\b\s*$", key):
        return False

    if key in _AMIR_SET_GROUP_BAD or key in _AMIR_SUBJECT_BAD:
        return False

    if _amir_subject_identifier_mode() and not allow_identify_descriptive:
        if (
            "_amir_subject_underidentified_taxon" in globals()
            and _amir_subject_underidentified_taxon(subject)
        ):
            return False

        if "_amir_taxon_is_group_label" in globals() and _amir_taxon_is_group_label(subject):
            return False

        if "_amir_taxon_is_broad" in globals() and _amir_taxon_is_broad(subject):
            return False

    tokens = [
        token
        for token in _amir_subj_tokens(subject)
        if token not in _AMIR_SET_CONTEXT_SKIP_WORDS
    ]

    if len(tokens) < 2:
        return False

    if tokens[0] in _AMIR_SET_CONNECTOR_WORDS or tokens[-1] in _AMIR_SET_CONNECTOR_WORDS:
        return False

    content_tokens = [token for token in tokens if token not in _AMIR_SET_CONNECTOR_WORDS]

    if len(content_tokens) < 2:
        return False

    if any(token in _AMIR_SET_GROUP_UNGROUNDED_CONTEXT_WORDS for token in tokens):
        return False

    return True


def _amir_set_roots_from_value(value):
    raw_value = _amir_subj_norm(value)

    if (
        "generic direct vision subject route" in raw_value
        or "vision subject route" in raw_value
        or "subject route" in raw_value
    ):
        return set()

    roots = set()

    for token in word_tokens(value):
        root = singular_token(token)

        if not root:
            continue

        if token in _AMIR_SET_CONTEXT_SKIP_WORDS or root in _AMIR_SET_CONTEXT_SKIP_WORDS:
            continue

        if token in _AMIR_SET_CONNECTOR_WORDS or root in _AMIR_SET_CONNECTOR_WORDS:
            continue

        if token in _AMIR_SET_GROUP_FILLER_WORDS or root in _AMIR_SET_GROUP_FILLER_WORDS:
            continue

        if root in {"direct", "generic", "route", "vision"}:
            continue

        roots.add(root)

    return roots


def _amir_set_scene_support_roots(values):
    """Infer broad scene support from visible labels/evidence.

    This is for set-level grouping only. It does not name a place or topic; it
    lets varied visible parts such as fields, houses, streets, trees, hills, and
    towers support a shared scene/set subject when the model proposes one.
    """
    text = _amir_subj_norm(" ".join(clean_text(value) for value in values or [] if clean_text(value)))

    if not text:
        return set()

    tokens = set()
    for token in word_tokens(text):
        root = singular_token(token)
        if root:
            tokens.add(root)
        if token:
            tokens.add(token)

    roots = set()

    natural = {
        "field", "hill", "hillside", "mountain", "slope", "forest",
        "tree", "woodland", "meadow", "grass", "terrain", "valley",
        "lake", "loch", "river", "water", "shore", "sky",
    }
    rural = natural | {
        "farm", "farmhouse", "barn", "pasture", "cottage", "castle",
        "tower", "road", "stone",
    }
    built = {
        "building", "house", "home", "inn", "hotel", "shop", "sign",
        "street", "road", "facade", "chimney", "window", "door",
        "roof", "town", "village", "castle", "tower", "bridge",
        "vehicle", "car", "motorcycle", "motorcyclist",
    }

    if tokens & natural:
        roots.update({"countryside", "landscape"})

    if tokens & rural:
        roots.update({"rural", "countryside"})

    if "hillside" in tokens or "hilly" in tokens:
        roots.add("hill")

    if tokens & built:
        roots.update({"building", "town", "village"})

    if tokens & {"street", "road", "vehicle", "car", "motorcycle", "motorcyclist"}:
        roots.update({"street", "road"})

    return roots


def _amir_set_row_support_roots(row):
    roots = set()

    if not isinstance(row, dict):
        return roots

    roots.update(_amir_set_roots_from_value(row.get("subject")))

    attempt_values = _amir_set_attempt_values(row)

    for value in attempt_values:
        roots.update(_amir_set_roots_from_value(value))

    roots.update(_amir_set_scene_support_roots([row.get("subject"), *attempt_values]))

    return roots


def _amir_set_group_support(rows, subject):
    subject_roots = _amir_set_roots_from_value(subject)
    row_root_sets = []

    for row in rows or []:
        if not isinstance(row, dict):
            continue

        roots = _amir_set_row_support_roots(row)

        if roots:
            row_root_sets.append(roots)

    if not subject_roots or not row_root_sets:
        return {
            "ok": False,
            "coverage": 0.0,
            "max_root_support": 0.0,
            "rows": len(row_root_sets),
        }

    covered_rows = sum(1 for roots in row_root_sets if roots & subject_roots)
    root_support = Counter()

    for roots in row_root_sets:
        root_support.update(roots & subject_roots)

    row_count = len(row_root_sets)
    coverage = covered_rows / max(1, row_count)
    max_root_count = root_support.most_common(1)[0][1] if root_support else 0
    max_root_support = (max_root_count / row_count) if row_root_sets else 0.0
    min_root_count = min((root_support.get(root, 0) for root in subject_roots), default=0)
    min_root_support = (min_root_count / row_count) if row_root_sets else 0.0
    pair_scores = []

    for index, left in enumerate(row_root_sets):
        for right in row_root_sets[index + 1:]:
            union = left | right

            if not union:
                continue

            pair_scores.append(len(left & right) / max(1, len(union)))

    cohesion = sum(pair_scores) / len(pair_scores) if pair_scores else 0.0

    if row_count <= 2:
        ok = coverage >= 1.0
    else:
        support_ok = (covered_rows * 3) >= (row_count * 2) and (max_root_count * 2) >= row_count
        strong_ok = coverage >= 0.75 or max_root_support >= 0.67 or cohesion >= 0.18
        # A proposed set subject cannot be carried by one common word while
        # another word is a one-frame detail. This is topic-neutral and blocks
        # minority details from becoming the whole batch subject.
        every_root_repeated = min_root_count >= 2
        ok = support_ok and strong_ok and every_root_repeated

    return {
        "ok": ok,
        "coverage": coverage,
        "max_root_support": max_root_support,
        "min_root_support": min_root_support,
        "cohesion": cohesion,
        "rows": row_count,
    }


def _amir_set_phrase_from_selected_roots(subject, selected_roots):
    selected_roots = {root for root in selected_roots or [] if root}

    if len(selected_roots) < 2:
        return ""

    words = str(subject or "").strip().split()

    if not words:
        return ""

    stop = set(_AMIR_SET_CONTEXT_SKIP_WORDS) | set(_AMIR_SET_GROUP_FILLER_WORDS)
    content_indexes = []

    for index, word in enumerate(words):
        tokens = _amir_subj_tokens(word)

        if not tokens:
            continue

        token = tokens[0]
        root = singular_token(token)

        if not root or token in _AMIR_SET_CONNECTOR_WORDS or root in _AMIR_SET_CONNECTOR_WORDS:
            continue

        if token in stop or root in stop:
            continue

        if root in selected_roots:
            content_indexes.append(index)

    if len(content_indexes) < 2:
        return ""

    first = content_indexes[0]
    last = content_indexes[-1]
    output_words = []
    pending_connectors = []
    emitted_content = 0

    for index in range(first, last + 1):
        word = words[index]
        raw_tokens = word_tokens(word)
        raw_token = raw_tokens[0] if raw_tokens else ""
        raw_root = singular_token(raw_token)

        if raw_token in _AMIR_SET_CONNECTOR_WORDS or raw_root in _AMIR_SET_CONNECTOR_WORDS:
            if output_words:
                pending_connectors.append(word)
            continue

        tokens = _amir_subj_tokens(word)

        if not tokens:
            continue

        token = tokens[0]
        root = singular_token(token)

        if token in _AMIR_SET_CONNECTOR_WORDS or root in _AMIR_SET_CONNECTOR_WORDS:
            if output_words:
                pending_connectors.append(word)
            continue

        if root in selected_roots and token not in stop and root not in stop:
            if pending_connectors and output_words:
                output_words.extend(pending_connectors)

            output_words.append(word)
            pending_connectors = []
            emitted_content += 1
            continue

        continue

    if emitted_content < 2:
        return ""

    return _amir_set_clean_group_label(" ".join(output_words), max_words=7, max_chars=70)


def _amir_set_repeated_core_subject(rows, subject, *, allow_identify_descriptive=False):
    """Trim a proposed group subject down to words repeated in the set evidence."""
    subject = _amir_set_clean_group_label(subject, max_words=7, max_chars=70)

    if not subject:
        return ""

    row_root_sets = [
        roots
        for row in (rows or [])
        if isinstance(row, dict)
        for roots in [_amir_set_row_support_roots(row)]
        if roots
    ]

    if len(row_root_sets) < 2:
        return ""

    counts = Counter()
    for roots in row_root_sets:
        counts.update(roots)

    row_count = len(row_root_sets)
    threshold = max(2, int(round(row_count * (0.50 if row_count <= 3 else 0.60))))
    stop = set(_AMIR_SET_CONTEXT_SKIP_WORDS) | set(_AMIR_SET_GROUP_FILLER_WORDS) | set(_AMIR_SET_CONNECTOR_WORDS)
    selected_roots = []
    selected_words = []

    for token in _amir_subj_tokens(subject):
        root = singular_token(token)

        if not root or root in stop or token in stop:
            continue

        if root in selected_roots:
            continue

        if counts.get(root, 0) >= threshold:
            selected_roots.append(root)
            selected_words.append(token)

    if len(selected_roots) < 2:
        return ""

    covered = sum(1 for roots in row_root_sets if roots & set(selected_roots))
    min_coverage = 0.67 if row_count <= 3 else 0.75

    if (covered / max(1, row_count)) < min_coverage:
        return ""

    core = _amir_set_phrase_from_selected_roots(subject, selected_roots)

    if not _amir_set_group_subject_ok(
        core,
        allow_identify_descriptive=allow_identify_descriptive,
    ):
        return ""

    return core


def _amir_set_evidence_consensus_subject(rows, current_subject="", fallback_subject=""):
    accepted = [
        row
        for row in rows or []
        if isinstance(row, dict) and row.get("accepted") and clean_text(row.get("subject"))
    ]

    if len(accepted) < 2:
        return ""

    candidates = []

    for value in [current_subject, fallback_subject]:
        value = _amir_set_clean_group_label(value, max_words=7, max_chars=70)

        if value:
            candidates.append(value)

    for row in accepted:
        for value in [row.get("subject")]:
            value = _amir_set_clean_group_label(value, max_words=7, max_chars=70)

            if value:
                candidates.append(value)

    scored = []
    seen = set()

    for index, candidate in enumerate(candidates):
        key = _amir_subj_norm(candidate)

        if not key or key in seen:
            continue

        seen.add(key)

        if not _amir_set_group_subject_ok(candidate):
            continue

        support = _amir_set_group_support(accepted, candidate)

        if not support["ok"]:
            continue

        scored.append(
            (
                support["coverage"],
                support["max_root_support"],
                len(_amir_subj_tokens(candidate)),
                -index,
                candidate,
            )
        )

    if scored:
        scored.sort(reverse=True)
        return _amir_set_clean_group_label(scored[0][-1], max_words=7, max_chars=70)

    row_root_sets = []
    first_seen = {}

    for row in accepted:
        roots = _amir_set_row_support_roots(row)

        if not roots:
            continue

        row_root_sets.append(roots)

        for value in [row.get("subject"), *_amir_set_attempt_values(row)]:
            if not _amir_set_roots_from_value(value):
                continue

            for token in _amir_subj_tokens(value):
                root = singular_token(token)

                if root in roots:
                    first_seen.setdefault(root, token)

    if len(row_root_sets) < 2:
        return ""

    counts = Counter()

    for roots in row_root_sets:
        counts.update(roots)

    if not counts:
        return ""

    row_count = len(row_root_sets)
    high_threshold = max(2, int(round(row_count * 0.50)))
    low_threshold = max(2, int(round(row_count * 0.34)))
    selected = []

    for root, count in counts.most_common(8):
        if count >= high_threshold:
            selected.append(root)

        if len(selected) >= 3:
            break

    if len(selected) < 2:
        top_root, top_count = counts.most_common(1)[0]

        if top_count < max(2, int(round(row_count * 0.67))):
            return ""

        selected = [top_root]

        for root, count in counts.most_common(10):
            if root == top_root:
                continue

            if count >= low_threshold:
                selected.append(root)

            if len(selected) >= 3:
                break

    if len(selected) < 2:
        return ""

    words = [first_seen.get(root, root) for root in selected[:3]]
    subject = _amir_set_clean_group_label(" ".join(words), max_words=7, max_chars=70)

    if not _amir_set_group_subject_ok(subject):
        return ""

    support = _amir_set_group_support(accepted, subject)

    if not support["ok"]:
        return ""

    return subject


def _amir_set_shared_subject_from_labels(rows, current_subject="", hints=""):
    """Build a conservative group subject from repeated candidate terms.

    This is a generic fallback for regenerate/group mode only. It does not use
    topic rules; it requires repeated support across selected image candidates
    or a soft hint that is also visible in candidate text.
    """
    labels = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        label = _amir_set_clean_group_label(row.get("subject") or "", max_words=7, max_chars=70)
        if label:
            labels.append(label)

    if len(labels) < 2:
        return ""

    stop = set(_AMIR_SET_CONTEXT_SKIP_WORDS) | {
        "a", "an", "and", "at", "by", "for", "from", "in", "near", "of",
        "on", "or", "the", "to", "with", "without", "against", "beside",
    }
    row_token_sets = []
    first_seen: dict[str, str] = {}

    for label in labels:
        roots = set()
        for token in _amir_subj_tokens(label):
            root = singular_token(token)
            if not root or root in stop or token in stop:
                continue
            if root in _AMIR_SET_GROUP_UNGROUNDED_CONTEXT_WORDS:
                continue
            roots.add(root)
            first_seen.setdefault(root, token)
        if roots:
            row_token_sets.append(roots)

    if len(row_token_sets) < 2:
        return ""

    counts = Counter()
    for roots in row_token_sets:
        counts.update(roots)

    threshold = max(2, int((len(row_token_sets) + 1) // 2))
    selected = []
    # Hints may affect ordering, but every chosen word still needs repeated
    # support from the selected images.
    ordered_sources = [hints or "", current_subject or "", *labels]

    for source in ordered_sources:
        for token in _amir_subj_tokens(source):
            root = singular_token(token)
            if not root or root in stop or root in selected:
                continue
            if counts.get(root, 0) >= threshold:
                selected.append(root)
        if len(selected) >= 4:
            break

    if len(selected) < 2:
        selected = [root for root, count in counts.most_common(4) if count >= threshold]

    if len(selected) < 2:
        return ""

    selected_set = set(selected)
    natural_candidates = []

    for order, label in enumerate(labels):
        label_roots = {
            singular_token(token)
            for token in _amir_subj_tokens(label)
            if singular_token(token)
            and singular_token(token) not in stop
            and token not in stop
        }
        hits = len(label_roots & selected_set)

        if hits < min(2, len(selected_set)):
            continue

        support = _amir_set_group_support(rows, label)

        if not support["ok"]:
            continue

        natural_candidates.append(
            (
                hits,
                support["coverage"],
                support["max_root_support"],
                len(_amir_subj_tokens(label)),
                -order,
                label,
            )
        )

    if natural_candidates:
        natural_candidates.sort(reverse=True)
        return _amir_set_clean_group_label(natural_candidates[0][-1], max_words=7, max_chars=70)

    if "reflection" in selected and "water" in selected and any(root in selected for root in {"canal", "river", "lake", "sea", "ocean", "pond"}):
        selected = [root for root in selected if root != "water"]

    words = [first_seen.get(root, root) for root in selected[:4]]
    if "reflection" in words:
        words = ["reflections" if word == "reflection" else word for word in words]

    subject = _amir_set_clean_group_label(" ".join(words), max_words=7, max_chars=70)

    if not _amir_set_group_subject_ok(subject):
        return ""

    support = _amir_set_group_support(rows, subject)
    if not support["ok"]:
        return ""

    return subject


def _amir_set_contact_sheet(rows):
    try:
        from PIL import Image, ImageOps
    except Exception:
        return None

    paths = []
    seen = set()

    for row in rows or []:
        if not isinstance(row, dict):
            continue

        raw_path = row.get("image") or row.get("path") or ""

        if not raw_path:
            continue

        try:
            path = _amir_subject_Path(str(raw_path))

            if not path.exists() or not path.is_file():
                continue

            key = str(path.resolve()).lower()

            if key in seen:
                continue

            seen.add(key)
            paths.append(path)
        except Exception:
            continue

        if len(paths) >= 6:
            break

    if len(paths) < 2:
        return None

    thumbs = []

    for path in paths:
        try:
            with Image.open(path) as image:
                image = ImageOps.exif_transpose(image).convert("RGB")
                image.thumbnail((360, 260))

                tile = Image.new("RGB", (360, 260), (245, 245, 245))
                x = max(0, (360 - image.width) // 2)
                y = max(0, (260 - image.height) // 2)
                tile.paste(image, (x, y))
                thumbs.append(tile)
        except Exception:
            continue

    if len(thumbs) < 2:
        return None

    cols = 3 if len(thumbs) > 2 else len(thumbs)
    rows_count = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 360, rows_count * 260), (245, 245, 245))

    for index, thumb in enumerate(thumbs):
        sheet.paste(thumb, ((index % cols) * 360, (index // cols) * 260))

    try:
        out_dir = _amir_subject_Path(__file__).resolve().parent.parent / "data" / "ollama_tmp"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"set_subject_contact_{int(_amir_subject_time.time() * 1000)}.jpg"
        sheet.save(out_path, format="JPEG", quality=88, optimize=True)
        return out_path
    except Exception:
        return None


def _amir_set_parse_group_response(raw):
    text = str(raw or "").strip()

    if not text:
        return False, ""

    data = {}

    try:
        data = _amir_subject_json.loads(text)
    except Exception:
        first = text.find("{")
        last = text.rfind("}")

        if first >= 0 and last > first:
            try:
                data = _amir_subject_json.loads(text[first:last + 1])
            except Exception:
                data = {}

    if isinstance(data, dict):
        shared = data.get("shared")

        if isinstance(shared, str):
            shared = shared.strip().lower() in {"1", "true", "yes"}
        else:
            shared = bool(shared)

        subject = _amir_set_clean_group_label(
            data.get("subject") or "",
            max_words=7,
            max_chars=70,
        )
        return shared, subject

    return False, ""


def _amir_set_group_subject_from_contact_sheet(rows):
    try:
        context = _amir_subject_read_context()
    except Exception:
        context = {"active": False, "hints": "", "current_subject": ""}

    force_group_regenerate = bool(context.get("active"))
    current_subject = _amir_set_clean_group_label(
        context.get("current_subject") or "",
        max_words=7,
        max_chars=70,
    )
    hints = str(context.get("hints") or "").strip()

    if force_group_regenerate and current_subject:
        current_support = _amir_set_group_support(rows, current_subject)

        if not current_support["ok"]:
            try:
                log(
                    "[SUBJECT AI] set group ignored unsupported current subject "
                    f"| subject={current_subject!r} "
                    f"| coverage={current_support['coverage']:.2f} "
                    f"| max_root_support={current_support['max_root_support']:.2f} "
                    f"| min_root_support={current_support.get('min_root_support', 0.0):.2f}"
                )
            except Exception:
                pass

            current_subject = ""

    sheet_path = _amir_set_contact_sheet(rows)

    if sheet_path is None:
        if force_group_regenerate:
            shared_subject = _amir_set_shared_subject_from_labels(
                rows,
                current_subject=current_subject,
                hints=hints,
            )
            if shared_subject:
                try:
                    log(f"[SUBJECT AI] set group label fallback | subject={shared_subject!r}")
                except Exception:
                    pass
                return shared_subject
        return ""

    labels = []

    for row in rows or []:
        if not isinstance(row, dict):
            continue

        label = _amir_set_clean_group_label(row.get("subject") or "", max_words=7, max_chars=70)

        if label and label not in labels:
            labels.append(label)

        if len(labels) >= 8:
            break

    label_text = "\n".join(f"- {label}" for label in labels) or "- none"
    user_context = ""

    if force_group_regenerate and (current_subject or hints):
        user_context = f"""
User context for this regeneration:
- Current subject in the app: {current_subject or "none"}
- Optional soft hints: {hints or "none"}

Use the current subject and hints as user intent when they fit the contact sheet.
Do not copy hints blindly.
If the current subject is a reasonable shared subject for most panels, keep or improve it instead of returning a conflict.
""".strip()

    prompt = f"""
You are looking at a contact sheet made from multiple selected photos.

Individual image subject guesses:
{label_text}

{user_context}

Decide if the selected photos share one useful visual set subject.

Return JSON only:
{{"shared": true, "subject": "2 to 7 word group subject"}}

Rules:
- The subject must describe what most selected photos visibly share.
- It may be a shared setting, object type, activity, or visual theme.
- It must be specific enough for a public photo batch title.
- If the shared subject is a living or macro subject, use the safest specific common species or narrow visible type supported by the panels.
- Do not accept broad living labels with only scene words, such as birds in flight, ducks in water, animals in grass, flowers close up, or insects on leaves.
- Use neutral visible words.
- Use the individual guesses only as grounding, not as text to copy.
- Do not stitch unrelated panels together as a list of separate subjects.
- If one sampled panel is clearly a different subject, return shared false.
- The subject should apply naturally to at least 70 percent of the panels.
- Do not infer country, region, nationality, architectural style, era, season, or event name.
- Reject vague labels like outdoor scene, nature, landscape, travel, mixed photos, photography, or details.
- If the photos do not share a specific visible theme, return {{"shared": false, "subject": ""}}.
""".strip()

    for model in _amir_subject_direct_model_candidates(force_regenerate=force_group_regenerate):
        try:
            raw = _amir_subject_call_model(
                image_path=sheet_path,
                prompt=prompt,
                model=model,
                temperature=0.0,
                num_predict=1024 if str(model).lower().startswith("qwen3-vl:") else 160,
                json_mode=True,
            )
        except Exception as exc:
            try:
                log(f"[SUBJECT AI] set group model failed | model={model} | {type(exc).__name__}: {exc}")
            except Exception:
                pass

            continue

        shared, subject = _amir_set_parse_group_response(raw)

        try:
            log(
                "[SUBJECT AI] set group model "
                f"| model={model} | shared={shared} | raw={raw!r} | subject={subject!r}"
            )
        except Exception:
            pass

        support = _amir_set_group_support(rows, subject)

        try:
            log(
                "[SUBJECT AI] set group support "
                f"| subject={subject!r} | ok={support['ok']} "
                f"| coverage={support['coverage']:.2f} "
                f"| max_root_support={support['max_root_support']:.2f}"
            )
        except Exception:
            pass

        if shared and _amir_set_group_subject_ok(subject) and support["ok"]:
            return _amir_set_clean_group_label(subject, max_words=7, max_chars=70)

        if shared and _amir_set_group_subject_ok(subject):
            core_subject = _amir_set_repeated_core_subject(
                rows,
                subject,
                allow_identify_descriptive=False,
            )

            if core_subject:
                try:
                    log(
                        "[SUBJECT AI] set group repeated-core fallback "
                        f"| original={subject!r} | core={core_subject!r}"
                    )
                except Exception:
                    pass

                return core_subject

    if force_group_regenerate:
        shared_subject = _amir_set_shared_subject_from_labels(
            rows,
            current_subject=current_subject,
            hints=hints,
        )
        if shared_subject:
            try:
                log(f"[SUBJECT AI] set group label fallback | subject={shared_subject!r}")
            except Exception:
                pass
            return shared_subject

    if force_group_regenerate and current_subject and _amir_set_group_subject_ok(current_subject):
        try:
            log(f"[SUBJECT AI] set group fallback | kept user subject={current_subject!r}")
        except Exception:
            pass

        return current_subject

    return ""


def _amir_identify_specific_taxon_consensus(rows):
    if not _amir_subject_identifier_mode():
        return ""

    accepted = [
        row
        for row in rows or []
        if isinstance(row, dict) and row.get("accepted") and clean_text(row.get("subject"))
    ]

    if len(accepted) < 2:
        return ""

    try:
        label_keys = _amir_taxon_label_keys()
    except Exception:
        label_keys = set()

    if not label_keys:
        return ""

    specific = []
    incompatible = []

    for row in accepted:
        subject = clean_text(row.get("subject"))
        key = _amir_subject_norm(subject)
        evidence = " ".join(_amir_set_attempt_values([row]))

        if key in label_keys and _amir_taxon_is_specific_label(key):
            specific.append(_amir_taxon_title(key))
            continue

        if _amir_identifier_subject_is_specific_enough(subject, evidence):
            specific.append(_amir_set_clean_group_label(subject, max_words=7, max_chars=70))
            continue

        broad_or_descriptive_living = bool(
            _amir_subject_should_run_taxon_identifier(subject, evidence)
            and (
                _amir_subject_underidentified_taxon(subject)
                or _amir_taxon_is_group_label(subject)
                or _amir_taxon_is_broad(subject)
            )
        )

        if not broad_or_descriptive_living:
            incompatible.append(subject)

    if not specific or incompatible:
        return ""

    counts = Counter(_amir_subject_norm(item) for item in specific if _amir_subject_norm(item))
    if not counts:
        return ""

    top_key, top_count = counts.most_common(1)[0]
    specific_ratio = top_count / max(1, len(specific))

    if top_count < 2 and len(accepted) > 2:
        return ""

    if specific_ratio < 0.67:
        return ""

    subject = _amir_taxon_title(top_key)

    try:
        log(
            "[SUBJECT AI IDENTIFY] specific taxon consensus "
            f"| subject={subject!r} | support={top_count}/{len(accepted)} "
            f"| specific_ratio={specific_ratio:.2f}"
        )
    except Exception:
        pass

    return subject


try:
    _amir_original_combine_subjects_diversity_guard_v1
except NameError:
    _amir_original_combine_subjects_diversity_guard_v1 = combine_subjects


def combine_subjects(rows):
    result = _amir_original_combine_subjects_diversity_guard_v1(rows)

    try:
        accepted = [
            row
            for row in rows or []
            if isinstance(row, dict) and row.get("accepted") and clean_text(row.get("subject"))
        ]

        subject = str(getattr(result, "subject", "") or "")
        force_group_regenerate = False

        try:
            force_group_regenerate = bool((_amir_subject_read_context() or {}).get("active"))
        except Exception:
            force_group_regenerate = False

        if force_group_regenerate and len(accepted) >= 2:
            group_subject = _amir_set_group_subject_from_contact_sheet(accepted)

            if group_subject:
                try:
                    log(
                        "[SUBJECT AI] regenerate group first | "
                        f"original={subject!r} | group={group_subject!r}"
                    )
                except Exception:
                    pass

                return SubjectSuggestion(
                    subject=group_subject,
                    confidence=76,
                    category="set_group",
                    error="",
                    details={
                        "rows": rows,
                        "mode": "regenerate_contact_sheet_group_subject_first",
                        "original_subject": subject,
                    },
                )

        if not subject and len(accepted) >= 2:
            group_subject = _amir_set_group_subject_from_contact_sheet(accepted)

            if not group_subject:
                group_subject = _amir_set_evidence_consensus_subject(accepted)

            if group_subject:
                return SubjectSuggestion(
                    subject=group_subject,
                    confidence=76,
                    category="set_group",
                    error="",
                    details={
                        "rows": rows,
                        "mode": "set_contact_sheet_group_subject",
                    },
                )

        if (
            _amir_subject_identifier_mode()
            and subject
            and len(rows or []) > 1
            and len(accepted) < 2
        ):
            try:
                log(
                    "[SUBJECT AI IDENTIFY] blocked weak set support "
                    f"| subject={subject!r} | accepted={len(accepted)}/{len(rows or [])}"
                )
            except Exception:
                pass

            return SubjectSuggestion(
                subject="",
                confidence=0,
                category="identify_insufficient_set_support",
                error="Identify needs repeated support across the selected images.",
                details={
                    "rows": rows,
                    "mode": "identify_blocked_single_image_set_subject",
                    "original_subject": subject,
                },
            )

        if not subject or len(accepted) < 2:
            return result

        identify_specific_subject = _amir_identify_specific_taxon_consensus(accepted)

        if identify_specific_subject:
            return SubjectSuggestion(
                subject=identify_specific_subject,
                confidence=86,
                category="identify_specific_taxon_consensus",
                error="",
                details={
                    "rows": rows,
                    "mode": "identify_specific_taxon_consensus",
                    "original_subject": subject,
                },
            )

        broad_living_subject = bool(
            _amir_subject_identifier_mode()
            and (
                (
                    "_amir_subject_underidentified_taxon" in globals()
                    and _amir_subject_underidentified_taxon(subject)
                )
                or (
                    "_amir_taxon_is_group_label" in globals()
                    and _amir_taxon_is_group_label(subject)
                )
                or (
                    "_amir_taxon_is_broad" in globals()
                    and _amir_taxon_is_broad(subject)
                )
            )
        )

        if broad_living_subject:
            group_subject = _amir_set_group_subject_from_contact_sheet(accepted)

            if group_subject:
                try:
                    log(
                        "[SUBJECT AI] set taxon guard | replaced broad living subject "
                        f"| original={subject!r} | group={group_subject!r}"
                    )
                except Exception:
                    pass

                return SubjectSuggestion(
                    subject=group_subject,
                    confidence=76,
                    category="set_group",
                    error="",
                    details={
                        "rows": rows,
                        "mode": "set_taxon_guard_group_subject",
                        "original_subject": subject,
                    },
                )

            try:
                log(
                    "[SUBJECT AI] set taxon guard | blocked broad living subject "
                    f"| subject={subject!r}"
                )
            except Exception:
                pass

            return SubjectSuggestion(
                subject="",
                confidence=0,
                category="underidentified_taxon",
                error="Living/macro subject was too broad. Use a narrower visible type or split the set.",
                details={
                    "rows": rows,
                    "mode": "set_taxon_guard_blocked",
                    "original_subject": subject,
                },
            )

        subject_counts = Counter(clean_text(row.get("subject")) for row in accepted)
        best_count = subject_counts.most_common(1)[0][1] if subject_counts else 0
        all_agree = best_count == len(accepted)
        mixed_set = len(subject_counts) > 1
        coverage = _amir_subj_result_coverage(accepted, subject)
        subset_result = (
            mixed_set
            and len(accepted) >= 3
            and (
                coverage["strong_conflict"]
                or (coverage["category_mixed"] and coverage["coverage"] < 0.80)
                or coverage["coverage"] < 0.67
            )
        )

        if subset_result:
            group_subject = _amir_set_group_subject_from_contact_sheet(accepted)
            if not group_subject:
                group_subject = _amir_set_synthesize_context_subject(accepted, fallback_subject=subject)
            if not group_subject:
                group_subject = _amir_set_evidence_consensus_subject(
                    accepted,
                    fallback_subject=subject,
                )

            if group_subject:
                try:
                    log(
                        "[SUBJECT AI] set diversity guard | accepted shared group subject "
                        f"| original={subject!r} | group={group_subject!r}"
                    )
                except Exception:
                    pass

                return SubjectSuggestion(
                    subject=group_subject,
                    confidence=76,
                    category="set_group",
                    error="",
                    details={
                        "rows": rows,
                        "mode": "set_contact_sheet_group_subject",
                        "original_subject": subject,
                        "coverage": coverage["coverage"],
                        "category_mixed": coverage["category_mixed"],
                    },
                )

            try:
                log(
                    "[SUBJECT AI] set diversity guard | blocked subset subject "
                    f"| subject={subject!r} | coverage={coverage['coverage']:.2f} "
                    f"| category_mixed={coverage['category_mixed']}"
                )
            except Exception:
                pass

            return SubjectSuggestion(
                subject="",
                confidence=0,
                category="mixed_specific",
                error="Specific subjects conflict across selected images. Split the set or type the shared subject manually.",
                details={
                    "rows": rows,
                    "mode": "set_context_diversity_guard_mixed_subset",
                    "original_subject": subject,
                    "coverage": coverage["coverage"],
                    "category_mixed": coverage["category_mixed"],
                },
            )

        if _amir_set_subject_is_narrow_detail(subject) and (mixed_set or not all_agree):
            broader = _amir_set_synthesize_context_subject(accepted, fallback_subject=subject)

            if broader:
                try:
                    log(f"[SUBJECT AI] set diversity guard | replaced narrow detail subject={subject!r} with {broader!r}")
                except Exception:
                    pass

                return SubjectSuggestion(
                    subject=broader,
                    confidence=min(int(getattr(result, "confidence", 0) or 0), 78),
                    category="set_context",
                    error="",
                    details={
                        "rows": rows,
                        "mode": "set_context_diversity_guard",
                        "original_subject": subject,
                    },
                )

            return SubjectSuggestion(
                subject="",
                confidence=0,
                category="mixed_specific",
                error="Narrow detail subject does not safely describe the selected image set.",
                details={
                    "rows": rows,
                    "mode": "set_context_diversity_guard_blocked",
                    "original_subject": subject,
                },
            )
    except Exception as exc:
        try:
            log(f"[SUBJECT AI] set diversity guard warning | {type(exc).__name__}: {exc}")
        except Exception:
            pass

    return result
# AMIR_SET_SUBJECT_DIVERSITY_GUARD_V1_END

if __name__ == "__main__":
    main()



