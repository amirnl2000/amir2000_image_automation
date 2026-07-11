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

# main_set.py — Multi-set launcher (keeps your pipeline intact)
import os, sys, json, time, shutil, sqlite3, threading, subprocess, socket, traceback, math, glob, queue, filecmp
# AMIR_FORCE_CAPTION_MODEL_CHAIN_START
# Production caption chain:
# primary = installed Qwen vision route that returns usable metadata facts here
# fallback = smaller Qwen vision route only when the primary fails a row
os.environ.setdefault("OLLAMA_MODEL_CAPTION", "qwen2.5vl:3b")
os.environ.setdefault("CAPTION_MODEL", "qwen2.5vl:3b")
os.environ["OLLAMA_MODEL_CAPTION_FALLBACK"] = "qwen2.5vl:3b"
os.environ["CAPTION_MODEL_FALLBACK"] = "qwen2.5vl:3b"

# Keep context stable. 16k is asking for drama.
os.environ.setdefault("CAPTION_NUM_CTX", "4096")
os.environ.setdefault("CAPTION_NUM_PREDICT", "180")
os.environ.setdefault("CAPTION_TEMPERATURE", "0.1")
# AMIR_FORCE_CAPTION_MODEL_CHAIN_END

# Make console output robust on Windows (avoid UnicodeEncodeError on emoji etc.)
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox, filedialog
import base64, re, difflib
from utils.autofix import (
    autofix_subject,
    find_misspellings,
    add_spell_exception,
    spellcheck_status,
)


_UDUP = re.compile(r"_+")
_SUBJECT_INPUT_WORD_RE = re.compile(r"[A-Za-z0-9]+")
_SUBJECT_UPPER_TOKENS = {
    "eos",
    "rf",
    "ef",
    "iso",
    "ii",
    "iii",
    "iv",
    "v",
    "vi",
    "vii",
    "viii",
    "ix",
    "x",
    "atr",
    "klm",
    "tui",
    "sas",
    "lot",
    "dhl",
    "ups",
    "raf",
}


def clean_token(s: str) -> str:
    """For Subject/Location/Folder tokens (not full filenames)."""
    s = (s or "").strip().replace(" ", "_")
    s = _UDUP.sub("_", s)
    return s.strip("_")


def _title_case_subject_input_text(text: str) -> str:
    """Title-case manual Subject input while preserving separators."""
    src = str(text or "").replace("\r", " ").replace("\n", " ")

    def _repl(match: re.Match[str]) -> str:
        tok = match.group(0)
        if not tok:
            return tok
        tl = tok.lower()
        if tl in _SUBJECT_UPPER_TOKENS:
            return tl.upper()
        if tok.isupper():
            return tok
        if re.search(r"[a-z][A-Z]", tok):
            return tok
        if any(ch.isdigit() for ch in tok):
            if tok[:1].isalpha():
                return "".join(ch.upper() if ch.isalpha() else ch for ch in tok)
            return tok
        return tok[:1].upper() + tok[1:].lower()

    return _SUBJECT_INPUT_WORD_RE.sub(_repl, src)


def clean_filename(name: str) -> str:
    """For the final file name with extension."""
    base, ext = os.path.splitext((name or "").strip())
    # Canonical filename style:
    # preserve token casing, normalize separators, keep uppercase extension.
    # Duplicate safety remains case-insensitive in reservation checks.
    base = clean_token(base)
    ext = (ext or ".JPG").upper()
    return f"{base}{ext}"


def _normalize_camera_token(camera: str) -> str:
    camera_s = slugify(camera) or DEFAULT_CAMERA_TOKEN
    cam_compact = camera_s.lower().replace("_", "")
    if (
        ("r5m2" in cam_compact)
        or ("r5markii" in cam_compact)
        or ("r5mark2" in cam_compact)
    ):
        camera_s = DEFAULT_CAMERA_TOKEN
    if camera_s.lower().startswith("canon_canon_"):
        camera_s = "Canon_" + camera_s[len("canon_canon_") :]
    return camera_s


def _title_case_slug_token(s: str) -> str:
    parts = [p for p in (s or "").split("_") if p]
    out = []
    for p in parts:
        if p.isupper():
            out.append(p)
        elif p[:1].islower():
            out.append(p[:1].upper() + p[1:])
        else:
            out.append(p)
    return "_".join(out)


def _title_case_words(s: str) -> str:
    parts = [p for p in re.split(r"\\s+", (s or "").strip()) if p]
    return " ".join([p[:1].upper() + p[1:].lower() for p in parts])


def _filename_tokens_from_path(path: str) -> set[str]:
    stem = os.path.splitext(os.path.basename(path or ""))[0]
    toks = [t for t in re.split(r"[_\\-\\s]+", stem) if t]
    return {t.lower() for t in toks}


def _filename_tokens_look_like_camera_ids(tokens: set[str]) -> bool:
    if not tokens:
        return True

    useful = []
    for token in tokens:
        t = str(token or "").strip().lower()
        if not t:
            continue
        if re.fullmatch(r"[a-z]{0,4}\d+[a-z0-9]*", t):
            continue
        if re.fullmatch(r"\d+", t):
            continue
        useful.append(t)

    return not useful


def _load_nature_subject_classifier():
    global _NATURE_SUBJECT_PIPE
    if _NATURE_SUBJECT_PIPE is not None:
        return _NATURE_SUBJECT_PIPE
    if _hf_pipeline is None:
        return None
    _NATURE_SUBJECT_PIPE = _hf_pipeline("zero-shot-image-classification", model=NATURE_SUBJECT_MODEL, device=-1)
    return _NATURE_SUBJECT_PIPE


def _nature_subject_from_classifier(image_path: str) -> str | None:
    if not NATURE_SUBJECT_ENABLE:
        return None
    if _hf_pipeline is None:
        return None
    if not os.path.isfile(image_path):
        return None
    toks = _filename_tokens_from_path(image_path)
    camera_id_name = _filename_tokens_look_like_camera_ids(toks)
    if not camera_id_name and not (toks & {"bird", "birds", "buzzard", "wigeon", "pigeon", "pigeons", "duck", "goose", "heron", "cormorant", "gull", "seagull", "animal", "macro", "plant", "plants", "flower", "flowers", "tree", "trees", "reeds", "reed", "seed", "seedhead"}):
        return None
    pipe = _load_nature_subject_classifier()
    if pipe is None:
        return None
    try:
        img = Image.open(image_path).convert("RGB")
    except Exception:
        return None
    try:
        preds = pipe(img, candidate_labels=_NATURE_SUBJECT_LABELS)
    except Exception:
        return None
    if isinstance(preds, dict) and "labels" in preds and "scores" in preds:
        preds = [{"label": l, "score": s} for l, s in zip(preds["labels"], preds["scores"])]
    preds = list(preds) if isinstance(preds, list) else []
    if not preds:
        return None
    top = preds[0]
    try:
        score = float(top.get("score", 0.0))
    except Exception:
        score = 0.0
    label = str(top.get("label", "")).strip().lower()
    if not label:
        return None
    min_score = NATURE_SUBJECT_MIN_SCORE_GENERIC if label in _NATURE_SUBJECT_GENERIC else NATURE_SUBJECT_MIN_SCORE
    if score < min_score:
        return None
    # Only allow non-generic labels if they align with filename tokens
    label_toks = set(label.split())
    if label not in _NATURE_SUBJECT_GENERIC and not camera_id_name and not (label_toks & toks):
        return None
    return _title_case_words(label)


def build_preview_filename(
    subject: str,
    location: str,
    folder: str,
    camera: str | None = None,
    year: str | int | None = None,
    index: int = 1,
) -> str:
    subject_s = slugify(subject)
    location_s = _title_case_slug_token(slugify(location))
    folder_s = _title_case_slug_token(slugify(folder))
    if folder_s and not folder_s.lower().endswith("photography"):
        folder_s = f"{folder_s}_Photography"
    camera_s = _normalize_camera_token(camera or DEFAULT_CAMERA_TOKEN)
    year_s = str(year) if str(year or "").isdigit() else time.strftime("%Y")
    return clean_filename(
        f"{subject_s}_{location_s}_{folder_s}_{camera_s}_{year_s}_{max(1, int(index)):03d}.JPG"
    )


from urllib import request
from PIL import Image  # used for fast resize before sending to Ollama
import warnings

warnings.filterwarnings(
    "ignore",
    message=r"Converting a tensor with requires_grad=True to a scalar",
    category=UserWarning,
)

try:
    _main_cache_base = (
        os.path.join(os.path.dirname(sys.executable), ".cache")
        if getattr(sys, "frozen", False)
        else os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")
    )
    _main_hf_home = os.path.join(_main_cache_base, "huggingface")
    _main_hf_hub = os.path.join(_main_hf_home, "hub")
    os.makedirs(_main_hf_hub, exist_ok=True)
    os.environ.setdefault("XDG_CACHE_HOME", _main_cache_base)
    os.environ.setdefault("HF_HOME", _main_hf_home)
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", _main_hf_hub)
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
except Exception:
    pass

try:
    from transformers import pipeline as _hf_pipeline
except Exception:
    _hf_pipeline = None

# ---------- Shared paths (prefer amir2000_config.py when present) ----------
from pathlib import Path
import importlib.util


def _load_config():
    """Load amir2000_config.py from beside the EXE (preferred) or beside this file."""
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "amir2000_config.py")
    candidates.append(Path(__file__).resolve().parent / "amir2000_config.py")

    for p in candidates:
        if p.is_file():
            spec = importlib.util.spec_from_file_location(
                "amir2000_config_external", str(p)
            )
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)  # type: ignore[arg-type]
                return mod
    return None


_cfg = _load_config()
PATHS = getattr(_cfg, "PATHS", {}) if _cfg else {}

DATA_DIR = PATHS.get(
    "DATA_DIR", r"YOUR_PATH_HERE"
)
DB_PATH = os.environ.get(
    "AMIR_REVIEW_DB", PATHS.get("REVIEW_DB_PATH", os.path.join(DATA_DIR, "review.db"))
)
INCOMING_DIR = PATHS.get(
    "INCOMING_DIR", r"YOUR_PATH_HERE"
)
LOCAL_SITE_IMAGES_BASE = PATHS.get(
    "LOCAL_SITE_IMAGES_BASE",
    r"YOUR_PATH_HERE",
)

BASE_PICK_DIR = PATHS.get(
    "BASE_PICK_DIR", r"YOUR_PATH_HERE"
)
STAGED_DIR = PATHS.get(
    "STAGED_DIR", r"YOUR_PATH_HERE"
)

# Keep relative “data/…” paths stable like main.py does
APP_DIR = (
    os.path.dirname(sys.executable)
    if getattr(sys, "frozen", False)
    else os.path.dirname(os.path.abspath(__file__))
)

METADATA_QUALITY_SCRIPT = PATHS.get(
    "METADATA_QUALITY_SCRIPT",
    os.path.join(APP_DIR, "scripts", "metadata_quality_production.py"),
)
METADATA_QUALITY_ENABLED = os.getenv("METADATA_QUALITY_ENABLED", "1") == "1"
METADATA_QUALITY_IDLE_TIMEOUT_SEC = int(os.getenv("METADATA_QUALITY_IDLE_TIMEOUT_SEC", "600"))
METADATA_QUALITY_HARD_TIMEOUT_SEC = int(os.getenv("METADATA_QUALITY_HARD_TIMEOUT_SEC", "1800"))
SERIES_VERSIONING_SCRIPT = PATHS.get(
    "SERIES_VERSIONING_SCRIPT",
    os.path.join(APP_DIR, "scripts", "series_versioning.py"),
)
SERIES_VERSIONING_ENABLED = os.getenv("SERIES_VERSIONING_ENABLED", "1") == "1"
SERIES_VERSIONING_SPLIT_WITHIN_SET = os.getenv("SERIES_VERSIONING_SPLIT_WITHIN_SET", "0") == "1"


LOCATION_FILE = os.path.join(DATA_DIR, "location_list.json")
FOLDER_MAP_FILE = os.path.join(DATA_DIR, "folder_map.json")
AUTOFIX_DICT_FILE = os.path.join(DATA_DIR, "autofix_dict.json")
NEW_TAXONOMY_LOG = os.path.join(DATA_DIR, "new_taxonomy_log.json")
RUN_LOG_FILE = os.path.join(DATA_DIR, "run_log.txt")
MULTISET_SESSION_FILE = os.path.join(DATA_DIR, "multiset_session.json")
MAX_FILENAME_LEN_WARN = 150
DEFAULT_CAMERA_TOKEN = "Canon_EOS_R5_Mark_II"

TABLE_NAME = "review_queue"

STAGES = [
    "Validate sets",
    "Prepare DB & copy to incoming (all sets)",
    "Extract EXIF & initial metadata (all sets)",
    "Insert/refresh review rows",
    "AI quality scoring",
    "Resize images for Ollama (temp)",
    "Caption/Keywords prefill + metadata quality",
    "Open review editor",
]

TOTAL_STAGES = len(STAGES)
# ---- Ollama config for subject suggestions ----
OLLAMA_BIN = os.getenv("OLLAMA_BIN", "ollama")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "127.0.0.1")
OLLAMA_PORT = int(os.getenv("OLLAMA_PORT", "11434"))
OLLAMA_MODEL = os.getenv(
    "OLLAMA_MODEL_SUBJECT", "qwen2.5vl:3b"
)  # subject suggestions (vision)
OLLAMA_MODEL_CAPTION = os.getenv(
    "OLLAMA_MODEL_CAPTION", "qwen2.5vl:7b"
)  # caption/keywords/alt prefill primary
OLLAMA_MODEL_CAPTION_FALLBACK = os.getenv(
    "OLLAMA_MODEL_CAPTION_FALLBACK", "qwen2.5vl:7b"
).strip()  # used only on failed rows
try:
    OLLAMA_NUM_GPU = int(os.getenv("OLLAMA_NUM_GPU", "99"))
except Exception:
    OLLAMA_NUM_GPU = 99
try:
    OLLAMA_MAIN_GPU = int(os.getenv("OLLAMA_MAIN_GPU", "0"))
except Exception:
    OLLAMA_MAIN_GPU = 0
OLLAMA_FORCE_GPU = os.getenv("OLLAMA_FORCE_GPU", "1") == "1"
OLLAMA_RESTART_FOR_GPU = os.getenv("OLLAMA_RESTART_FOR_GPU", "0") == "1"
OLLAMA_LLM_LIBRARY = os.getenv("OLLAMA_LLM_LIBRARY", "cuda").strip() or "cuda"
OLLAMA_START_METHOD = os.getenv("OLLAMA_START_METHOD", "app").strip().lower()
_OLLAMA_GPU_BOOTSTRAPPED = False
_OLLAMA_STARTED_BY_APP = False
OLLAMA_CLOSE_ON_RUN_END = os.getenv("OLLAMA_CLOSE_ON_RUN_END", "0") == "1"
SUBJECT_MODEL_CANDIDATES_ENV = os.getenv(
    "OLLAMA_MODEL_SUBJECT_CANDIDATES",
    "llama3.2-vision:latest,llava:13b,llama3.2-vision:11b"
)
SUBJECT_MODEL_CANDIDATES = tuple(
    dict.fromkeys(
        [x.strip() for x in str(SUBJECT_MODEL_CANDIDATES_ENV or "").split(",") if x.strip()]
    )
)
SUBJECT_MIN_CONFIDENCE = max(
    0, min(100, int(os.getenv("SUBJECT_MIN_CONFIDENCE", "68")))
)
SUBJECT_MAX_CHARS = max(30, int(os.getenv("SUBJECT_MAX_CHARS", "60")))
SUBJECT_THUMB_MAX = max(960, int(os.getenv("SUBJECT_THUMB_MAX", "1792")))
SUBJECT_JPEG_QUALITY = max(
    70, min(95, int(os.getenv("SUBJECT_JPEG_QUALITY", "90")))
)
THUMB_MAX = 1024  # more detail for species and fine subjects (slower)
# Caption stage opts only (34b on 8GB GPU benefits from smaller ctx)
OLLAMA_OPTS = {
    "num_ctx": int(os.getenv("CAPTION_NUM_CTX", "16384")),
    "num_predict": int(os.getenv("CAPTION_NUM_PREDICT", "180")),
    "temperature": float(os.getenv("CAPTION_TEMPERATURE", "0.1")),
}
if OLLAMA_NUM_GPU >= 0:
    OLLAMA_OPTS["num_gpu"] = int(OLLAMA_NUM_GPU)
if OLLAMA_MAIN_GPU >= 0:
    OLLAMA_OPTS["main_gpu"] = int(OLLAMA_MAIN_GPU)
OLLAMA_WARM_ON_SCORING = os.getenv("OLLAMA_WARM_ON_SCORING", "1") == "1"
OLLAMA_WARM_TIMEOUT_SEC = int(os.getenv("OLLAMA_WARM_TIMEOUT_SEC", "45"))
OLLAMA_WARM_KEEP_ALIVE = os.getenv("OLLAMA_WARM_KEEP_ALIVE", "45m")
OLLAMA_STARTUP_PROBE = os.getenv("OLLAMA_STARTUP_PROBE", "1") == "1"

# caption_review_local.py tuning (used by Stage 6)
CAPTION_KEYWORDS_N = int(os.getenv("CAPTION_KEYWORDS_N", "8"))
CAPTION_REWRITE_WEAK = os.getenv("CAPTION_REWRITE_WEAK", "1") == "1"
CAPTION_REWRITE_MAX_PASSES = int(os.getenv("CAPTION_REWRITE_MAX_PASSES", "3"))
CAPTION_QUALITY_MIN_SCORE = int(os.getenv("CAPTION_QUALITY_MIN_SCORE", "90"))
CAPTION_SERIES_LARGE_THRESHOLD = int(os.getenv("CAPTION_SERIES_LARGE_THRESHOLD", "8"))
CAPTION_MAX_TRIES = int(os.getenv("CAPTION_MAX_TRIES", "1"))
CAPTION_FALLBACK_MAX_TRIES = int(os.getenv("CAPTION_FALLBACK_MAX_TRIES", "1"))
CAPTION_PREFIX_WORDS = int(os.getenv("CAPTION_PREFIX_WORDS", "8"))
CAPTION_FAIL_ON_ROW_ERRORS = os.getenv("CAPTION_FAIL_ON_ROW_ERRORS", "0") == "1"
RESIZE_FAIL_ON_ANY = os.getenv("RESIZE_FAIL_ON_ANY", "0") == "1"
SCORE_FORCE_RUN = os.getenv("AMIR_SCORE_FORCE_RUN", "1") == "1"

# optional precision keyword terms DB
DEFAULT_TERMS_DB = os.getenv(
    "CAPTION_TERMS_DB",
    PATHS.get("REVAMP_KNOWLEDGE_DB_PATH", os.path.join(DATA_DIR, "revamp_knowledge.db")),
)
CAPTION_TERMS_TABLE = os.getenv("CAPTION_TERMS_TABLE", "keyword_terms")
CAPTION_TERMS_MIN_PRECISION = int(os.getenv("CAPTION_TERMS_MIN_PRECISION", "85"))

# Production subject identifier router.
# This runs after review_queue rows exist and before caption prefill.
IDENTIFIER_ROUTER_ENABLED = os.getenv("IDENTIFIER_ROUTER_ENABLED", "1") == "1"
IDENTIFIER_ROUTER_FAIL_HARD = os.getenv("IDENTIFIER_ROUTER_FAIL_HARD", "0") == "1"
IDENTIFIER_ROUTER_MAX_SAMPLES = max(1, int(os.getenv("IDENTIFIER_ROUTER_MAX_SAMPLES", "6")))
IDENTIFIER_ROUTER_MAX_CROPS = max(1, int(os.getenv("IDENTIFIER_ROUTER_MAX_CROPS", "10")))
IDENTIFIER_ROUTER_MODEL = os.getenv("IDENTIFIER_ROUTER_MODEL", OLLAMA_MODEL_CAPTION).strip() or OLLAMA_MODEL_CAPTION
IDENTIFIER_ROUTER_FAST_IMAGE_MAX_SIDE = max(512, int(os.getenv("IDENTIFIER_ROUTER_FAST_IMAGE_MAX_SIDE", "768")))
IDENTIFIER_ROUTER_CLEAN_TMP = os.getenv("IDENTIFIER_ROUTER_CLEAN_TMP", "1") == "1"
IDENTIFIER_ROUTER_TMP_DIR = os.getenv(
    "IDENTIFIER_ROUTER_TMP_DIR",
    os.path.join(DATA_DIR, "identifier_router_tmp"),
)


CAPTION_MAX_RETRIES = int(os.getenv("CAPTION_MAX_RETRIES", "1"))
CAPTION_TIMEOUT_SEC = int(os.getenv("CAPTION_TIMEOUT_SEC", "420"))
CAPTION_PREFILL_CHUNK_SIZE = int(os.getenv("CAPTION_PREFILL_CHUNK_SIZE", "6"))
CAPTION_NATIVE_CRASH_RETRIES = int(
    os.getenv("CAPTION_NATIVE_CRASH_RETRIES", str(max(3, CAPTION_MAX_RETRIES + 1)))
)
CAPTION_PREFILL_IDLE_TIMEOUT_SEC = int(
    # First-run HF/model cache warmup can exceed 2 minutes without emitting lines.
    os.getenv("CAPTION_PREFILL_IDLE_TIMEOUT_SEC", "300")
)
CAPTION_PREFILL_HARD_TIMEOUT_SEC = int(
    os.getenv("CAPTION_PREFILL_HARD_TIMEOUT_SEC", "900")
)
SESSION_SCOPE_ONLY = os.getenv("AMIR_SESSION_SCOPE_ONLY", "1") == "1"
AUTO_AI_SUBJECT_ON_SELECT = os.getenv("AUTO_AI_SUBJECT_ON_SELECT", "0") == "1"
ADD_SET_EXIF_PREVIEW = os.getenv("ADD_SET_EXIF_PREVIEW", "0") == "1"

# Stage-6 QC scan (duplicates + suspicious text) before review editor opens
PREFILL_QC_ENABLED = os.getenv("PREFILL_QC_ENABLED", "1") == "1"
PREFILL_QC_SAMPLE_IDS = max(3, int(os.getenv("PREFILL_QC_SAMPLE_IDS", "12")))
PREFILL_QC_REPORT_PATH = os.getenv(
    "PREFILL_QC_REPORT_PATH", os.path.join(DATA_DIR, "prefill_qc_last.json")
)

# Optional nature classifier for subject suggestion (open-source, local)
NATURE_SUBJECT_ENABLE = os.getenv("NATURE_SUBJECT_ENABLE", "1") == "1"
NATURE_SUBJECT_MODEL = os.getenv("NATURE_SUBJECT_MODEL", "openai/clip-vit-large-patch14")
NATURE_SUBJECT_MIN_SCORE = float(os.getenv("NATURE_SUBJECT_MIN_SCORE", "0.55"))
NATURE_SUBJECT_MIN_SCORE_GENERIC = float(os.getenv("NATURE_SUBJECT_MIN_SCORE_GENERIC", "0.40"))
_NATURE_SUBJECT_PIPE = None

_NATURE_SUBJECT_LABELS = [
    "eurasian oystercatcher",
    "northern lapwing",
    "black-tailed godwit",
    "bar-tailed godwit",
    "common redshank",
    "eurasian curlew",
    "pied avocet",
    "common buzzard",
    "eurasian wigeon",
    "mallard duck",
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
    "common kestrel",
    "european robin",
    "great tit",
    "house sparrow",
    "eurasian magpie",
    "carrion crow",
    "pigeons",
    "pigeon",
    "duck",
    "goose",
    "heron",
    "cormorant",
    "seagull",
    "gull",
    "bird",
    "raptor",
    "waterfowl",
    "fox",
    "red fox",
    "deer",
    "roe deer",
    "rabbit",
    "hare",
    "squirrel",
    "animal",
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
    "dry reeds",
    "reeds",
    "flower",
    "flowers",
    "plant",
    "plants",
    "tree",
    "trees",
    "branch",
    "branches",
    "seed head",
]
_NATURE_SUBJECT_GENERIC = {
    "bird",
    "raptor",
    "waterfowl",
    "animal",
    "plant",
    "tree",
    "trees",
    "branch",
    "branches",
    "reeds",
    "reed",
    "seed head",
    "flower",
    "flowers",
}


def _ollama_up(host=OLLAMA_HOST, port=OLLAMA_PORT, timeout=0.5):
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _resolve_ollama_binary() -> tuple[str, str | None]:
    candidates: list[str] = []
    try:
        w = shutil.which(OLLAMA_BIN)
        if w:
            candidates.append(str(w))
    except Exception:
        pass
    if OLLAMA_BIN:
        candidates.append(str(OLLAMA_BIN))
    try:
        la = os.environ.get("LOCALAPPDATA", "")
        if la:
            candidates.append(os.path.join(la, "Programs", "Ollama", "ollama.exe"))
    except Exception:
        pass
    try:
        pf = os.environ.get("ProgramFiles", r"YOUR_PATH_HERE Files")
        candidates.append(os.path.join(pf, "Ollama", "ollama.exe"))
    except Exception:
        pass

    for c in candidates:
        if not c:
            continue
        p = c
        try:
            if not os.path.isabs(p):
                p = os.path.abspath(p)
        except Exception:
            pass
        if os.path.isfile(p):
            return p, os.path.dirname(p)

    fallback = candidates[0] if candidates else str(OLLAMA_BIN or "ollama")
    try:
        if os.path.isabs(fallback):
            return fallback, os.path.dirname(fallback)
    except Exception:
        pass
    return fallback, None


def _pick_ollama_llm_library(install_dir: str | None) -> str:
    configured = str(OLLAMA_LLM_LIBRARY or "cuda").strip() or "cuda"
    if configured.lower() != "cuda":
        return configured
    if not install_dir:
        return configured
    for cand in ("cuda_v13", "cuda_v12", "cuda"):
        try:
            if os.path.isdir(os.path.join(install_dir, "lib", "ollama", cand)):
                return cand
        except Exception:
            continue
    return configured


def _ollama_serve_env() -> dict:
    env = os.environ.copy()
    ollama_bin, install_dir = _resolve_ollama_binary()
    if OLLAMA_FORCE_GPU:
        # Force values even when parent process has empty keys.
        env["OLLAMA_LLM_LIBRARY"] = _pick_ollama_llm_library(install_dir)
        env["OLLAMA_NUM_GPU"] = str(int(OLLAMA_NUM_GPU))
        env["OLLAMA_MAIN_GPU"] = str(int(OLLAMA_MAIN_GPU))
    try:
        if install_dir:
            dll_dirs = [
                os.path.join(install_dir, "lib", "ollama"),
                os.path.join(install_dir, "lib", "ollama", "cuda_v13"),
                os.path.join(install_dir, "lib", "ollama", "cuda_v12"),
            ]
            try:
                llm_lib = str(env.get("OLLAMA_LLM_LIBRARY") or "").strip()
                if llm_lib:
                    llm_dir = os.path.join(install_dir, "lib", "ollama", llm_lib)
                    if os.path.isdir(llm_dir):
                        dll_dirs.insert(0, llm_dir)
            except Exception:
                pass
            present = [p for p in dll_dirs if os.path.isdir(p)]
            if present:
                old_path = str(env.get("PATH", "") or "")
                env["PATH"] = os.pathsep.join(present + [old_path] if old_path else present)
    except Exception:
        pass
    return env


def _ensure_ollama_running():
    global _OLLAMA_GPU_BOOTSTRAPPED, _OLLAMA_STARTED_BY_APP
    if OLLAMA_FORCE_GPU and OLLAMA_RESTART_FOR_GPU and not _OLLAMA_GPU_BOOTSTRAPPED:
        _OLLAMA_GPU_BOOTSTRAPPED = True
        try:
            if os.name == "nt":
                # Kill tray + server once, then launch serve with explicit GPU env.
                subprocess.run(
                    ["taskkill", "/F", "/IM", "ollama app.exe"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                subprocess.run(
                    ["taskkill", "/F", "/IM", "ollama.exe"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            else:
                subprocess.run(
                    ["pkill", "-f", "ollama serve"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            time.sleep(0.7)
        except Exception:
            pass

    if _ollama_up():
        return True
    try:
        ollama_bin, ollama_cwd = _resolve_ollama_binary()

        started = False
        if os.name == "nt" and OLLAMA_START_METHOD == "app":
            try:
                app_bin = os.path.join(ollama_cwd or "", "ollama app.exe")
                if app_bin and os.path.isfile(app_bin):
                    subprocess.Popen(
                        [app_bin],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                        # On Windows, app-managed Ollama detects GPU correctly
                        # with its own default environment.
                        env=os.environ.copy(),
                        cwd=ollama_cwd,
                    )
                    started = True
            except Exception:
                started = False

        if not started:
            _bg_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            _bg_flags |= getattr(subprocess, "DETACHED_PROCESS", 0)
            subprocess.Popen(
                [ollama_bin, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=_bg_flags,
                env=_ollama_serve_env(),
                cwd=ollama_cwd,
            )
        _OLLAMA_STARTED_BY_APP = True

        for _ in range(40):  # wait ~10s
            if _ollama_up():
                return True
            time.sleep(0.25)
    except Exception:
        pass
    return False


def _ollama_model_names(*, timeout: float = 3.0) -> set[str]:
    try:
        with request.urlopen(f"http://{OLLAMA_HOST}:{OLLAMA_PORT}/api/tags", timeout=timeout) as resp:
            tags = json.loads(resp.read().decode("utf-8")).get("models", [])
        return {str(t.get("name", "")).strip() for t in tags if isinstance(t, dict)}
    except Exception:
        return set()


def _resolve_ollama_model_alias(model: str, names: set[str]) -> str | None:
    model = (model or "").strip()
    if not model:
        return None
    if model in names:
        return model

    want_base = model.split(":", 1)[0].strip().lower()
    if not want_base:
        return None

    for n in names:
        if n.split(":", 1)[0].strip().lower() == want_base:
            return n
    return None


_SUBJECT_MODEL_CACHE = ""


def _pick_subject_model() -> str:
    """Pick the best available local model for subject detection."""
    global _SUBJECT_MODEL_CACHE
    if _SUBJECT_MODEL_CACHE:
        return _SUBJECT_MODEL_CACHE

    names = _ollama_model_names(timeout=3)
    if names:
        for cand in SUBJECT_MODEL_CANDIDATES:
            resolved = _resolve_ollama_model_alias(cand, names)
            if resolved:
                _SUBJECT_MODEL_CACHE = resolved
                return resolved
        # /api/tags worked but none matched candidates. Fall back to configured subject model.
        _SUBJECT_MODEL_CACHE = OLLAMA_MODEL
        return _SUBJECT_MODEL_CACHE

    # /api/tags unavailable: do not cache fallback so a later call can still pick better.
    return OLLAMA_MODEL


def _ensure_ollama_model(model: str) -> bool:
    """Return True if the model tag exists locally (or tag check is unavailable)."""
    model = (model or "").strip()
    if not model:
        return True

    names = _ollama_model_names(timeout=3)
    if not names:
        # If we can't check, don't block the workflow; let the next call try.
        return True
    return _resolve_ollama_model_alias(model, names) is not None


def _warm_ollama_model(model: str, *, timeout: int = OLLAMA_WARM_TIMEOUT_SEC) -> tuple[bool, str]:
    """Best-effort warmup call so first real caption requests are faster."""
    model = (model or "").strip()
    if not model:
        return True, "empty model"

    payload = {
        "model": model,
        "prompt": "Warmup. Respond with OK.",
        "stream": False,
        "keep_alive": OLLAMA_WARM_KEEP_ALIVE,
        "options": {
            "num_predict": 8,
            "temperature": 0.0,
            "num_gpu": int(OLLAMA_NUM_GPU),
            "main_gpu": int(OLLAMA_MAIN_GPU),
        },
    }
    try:
        req = request.Request(
            f"http://{OLLAMA_HOST}:{OLLAMA_PORT}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=max(3, int(timeout))) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if isinstance(data, dict) and data.get("error"):
            return False, str(data.get("error"))
        return True, "ready"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _format_gib(n: object) -> str:
    try:
        v = float(n)
        if v <= 0:
            return "0.0GiB"
        return f"{v / (1024 ** 3):.1f}GiB"
    except Exception:
        return "0.0GiB"


def _ollama_startup_probe() -> None:
    """Start Ollama with GPU env and print CPU/GPU status at app startup."""
    if not OLLAMA_STARTUP_PROBE:
        return

    if not _ensure_ollama_running():
        raise RuntimeError(f"Ollama service is not reachable on http://{OLLAMA_HOST}:{OLLAMA_PORT}.")

    probe_model = (OLLAMA_MODEL_CAPTION or OLLAMA_MODEL or "qwen2.5vl:3b").strip()
    names = _ollama_model_names(timeout=3.0)
    if names:
        resolved = _resolve_ollama_model_alias(probe_model, names)
        if resolved:
            probe_model = resolved
        else:
            raise RuntimeError(
                f"Ollama model '{probe_model}' is not installed locally. Install it before starting the app."
            )

    probe_ctx = max(1024, min(4096, int(OLLAMA_OPTS.get("num_ctx", 4096) or 4096)))
    startup_timeout = max(60, int(OLLAMA_WARM_TIMEOUT_SEC or 45))

    def _ps_loaded_model(timeout: float = 5.0) -> dict | None:
        with request.urlopen(f"http://{OLLAMA_HOST}:{OLLAMA_PORT}/api/ps", timeout=timeout) as resp:
            ps = json.loads(resp.read().decode("utf-8"))
        models = list((ps or {}).get("models", []))
        for m in models:
            if str(m.get("name", "")).strip() == probe_model:
                return m
        if models:
            return models[0]
        return None

    # Force a tiny load so /api/ps can report CPU/GPU immediately.
    payload = {
        "model": probe_model,
        "prompt": "ok",
        "stream": False,
        "keep_alive": OLLAMA_WARM_KEEP_ALIVE,
        "options": {
            "num_predict": 1,
            "temperature": 0.0,
            "num_ctx": int(probe_ctx),
            "num_gpu": int(OLLAMA_NUM_GPU),
            "main_gpu": int(OLLAMA_MAIN_GPU),
        },
    }
    req = request.Request(
        f"http://{OLLAMA_HOST}:{OLLAMA_PORT}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=startup_timeout) as resp:
            _ = resp.read()
    except Exception as e:
        raise RuntimeError(
            f"Ollama model '{probe_model}' failed to start within {startup_timeout}s "
            f"({type(e).__name__}: {e})."
        ) from e

    deadline = time.time() + 15.0
    chosen = None
    last_ps_error = None
    while time.time() < deadline:
        try:
            chosen = _ps_loaded_model(timeout=5)
            if chosen:
                break
            last_ps_error = None
        except Exception as e:
            last_ps_error = e
        time.sleep(0.5)

    if not chosen:
        if last_ps_error is not None:
            raise RuntimeError(
                f"Ollama model '{probe_model}' did not report as loaded after warmup "
                f"({type(last_ps_error).__name__}: {last_ps_error})."
            ) from last_ps_error
        raise RuntimeError(f"Ollama model '{probe_model}' did not report as loaded after warmup.")

    vram = int(chosen.get("size_vram") or 0)
    proc = "GPU" if vram > 0 else "CPU"
    ctx = int(chosen.get("context_length") or 0)
    name = str(chosen.get("name") or probe_model)
    print(
        f"[INFO] Ollama startup check: model={name} processor={proc} context={ctx} vram={_format_gib(vram)}"
    )

    # If startup landed on CPU, try once more with explicit GPU-friendly options.
    if OLLAMA_FORCE_GPU and vram <= 0:
        try:
            payload2 = {
                "model": probe_model,
                "prompt": "gpu warmup",
                "stream": False,
                "keep_alive": OLLAMA_WARM_KEEP_ALIVE,
                "options": {
                    "num_predict": 8,
                    "temperature": 0.0,
                    "num_ctx": int(probe_ctx),
                    "num_gpu": int(OLLAMA_NUM_GPU),
                    "main_gpu": int(OLLAMA_MAIN_GPU),
                },
            }
            req2 = request.Request(
                f"http://{OLLAMA_HOST}:{OLLAMA_PORT}/api/generate",
                data=json.dumps(payload2).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with request.urlopen(req2, timeout=45) as resp2:
                _ = resp2.read()

            with request.urlopen(f"http://{OLLAMA_HOST}:{OLLAMA_PORT}/api/ps", timeout=5) as resp3:
                ps2 = json.loads(resp3.read().decode("utf-8"))
            models2 = list((ps2 or {}).get("models", []))
            chosen2 = None
            for m2 in models2:
                if str(m2.get("name", "")).strip() == probe_model:
                    chosen2 = m2
                    break
            if not chosen2 and models2:
                chosen2 = models2[0]
            if chosen2:
                vram2 = int(chosen2.get("size_vram") or 0)
                ctx2 = int(chosen2.get("context_length") or 0)
                proc2 = "GPU" if vram2 > 0 else "CPU"
                name2 = str(chosen2.get("name") or probe_model)
                print(
                    f"[INFO] Ollama startup recheck: model={name2} processor={proc2} "
                    f"context={ctx2} vram={_format_gib(vram2)}"
                )
                if vram2 <= 0:
                    print(
                        "[WARN] Ollama is still on CPU after GPU recheck. "
                        "You can lower CAPTION_NUM_CTX and restart."
                    )
        except Exception as e2:
            print(f"[WARN] Ollama GPU recheck failed: {type(e2).__name__}: {e2}")


def _shutdown_ollama_on_run_end() -> None:
    """Close app-started Ollama processes after run is fully done."""
    if not OLLAMA_CLOSE_ON_RUN_END:
        return
    if not _OLLAMA_STARTED_BY_APP:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/IM", "ollama app.exe"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            subprocess.run(
                ["taskkill", "/F", "/IM", "ollama.exe"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            subprocess.run(
                ["pkill", "-f", "ollama"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        print("[INFO] Ollama runtime closed.")
    except Exception as e:
        print(f"[WARN] Could not close Ollama runtime: {type(e).__name__}: {e}")


_QC_NATURE_CUES = (
    "park",
    "mountain",
    "lake",
    "river",
    "forest",
    "trail",
    "ridge",
    "valley",
    "wildlife",
    "autumn",
    "nature",
)
_QC_URBAN_CUES = (
    "city",
    "urban",
    "building",
    "buildings",
    "downtown",
    "street",
    "highway",
    "intersection",
    "building",
    "architecture",
    "traffic",
    "town",
)
_QC_STRONG_URBAN_WORDS = (
    "urban",
    "downtown",
    "skyline",
    "mid rise",
    "high rise",
    "concrete",
    "intersection",
    "street light",
    "streetlights",
    "city buildings",
    "distant buildings",
    "house",
    "houses",
)
_QC_GENERIC_PHRASES = (
    "a scene featuring",
    "blue sky color",
    "clear daylight conditions",
    "close texture and color fill",
    "flight wings",
    "grass and field texture fill",
    "image road with",
    "in the frame",
    "land wings",
    "markings texture",
    "lines surfaces and structure fill",
    "natural backdrop",
    "open space fill",
    "outdoor setting",
    "scene appears",
    "scene stands",
    "scene sits",
    "shape texture and color contrast fill",
    "sky color and open space",
    "sky alongside",
    "pattern texture",
    "texture markings",
    "water texture and reflections fill",
    "with its reflection clearly",
    "within an outdoor setting",
)


def _qc_norm_text(text: str) -> str:
    s = str(text or "").lower().strip()
    s = re.sub(r"[^a-z0-9\s]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _qc_keywords(keywords: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in str(keywords or "").split(","):
        t = _qc_norm_text(raw)
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def _qc_add_dup_reasons(
    id_reasons: dict[int, set[str]],
    groups: list[list[int]],
    reason: str,
) -> tuple[int, int]:
    if not groups:
        return 0, 0
    rows = 0
    for grp in groups:
        rows += len(grp)
        for rid in grp:
            id_reasons.setdefault(rid, set()).add(reason)
    return len(groups), rows


def _run_prefill_qc_scan(
    db_path: str,
    table_name: str,
    *,
    id_scope: list[int] | None = None,
    report_path: str = PREFILL_QC_REPORT_PATH,
    sample_ids: int = PREFILL_QC_SAMPLE_IDS,
) -> dict:
    scope = [int(x) for x in (id_scope or []) if int(x) > 0]

    summary: dict = {
        "row_count": 0,
        "caption_dup_groups": 0,
        "caption_dup_rows": 0,
        "alt_dup_groups": 0,
        "alt_dup_rows": 0,
        "keywords_dup_groups": 0,
        "keywords_dup_rows": 0,
        "caption_alt_equal_rows": 0,
        "suspicious_rows": 0,
        "duplicate_rows_total": 0,
        "flagged_rows_total": 0,
        "sample_ids": [],
        "report_path": report_path,
        "scope_ids_count": len(scope),
    }

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        sql = (
            f"SELECT id, File_Name, Subject, Location, Caption, alt_text, Keywords "
            f"FROM {table_name} WHERE COALESCE(Review_Status,'')='Pending'"
        )
        params: list[object] = []
        if scope:
            sql += f" AND id IN ({','.join(['?'] * len(scope))})"
            params.extend(scope)
        sql += " ORDER BY id"
        cur.execute(sql, params)
        rows = cur.fetchall()

    summary["row_count"] = len(rows)
    if not rows:
        return summary

    cap_map: dict[str, list[int]] = {}
    alt_map: dict[str, list[int]] = {}
    kw_sig_map: dict[str, list[int]] = {}
    pair_map: dict[str, list[int]] = {}

    id_reasons: dict[int, set[str]] = {}
    suspicious_only_ids: set[int] = set()
    row_meta: dict[int, dict[str, str]] = {}

    for r in rows:
        rid = int(r["id"])
        file_name = str(r["File_Name"] or "")
        subject = str(r["Subject"] or "")
        location = str(r["Location"] or "")
        caption = str(r["Caption"] or "")
        alt_text = str(r["alt_text"] or "")
        keywords = str(r["Keywords"] or "")

        cap_n = _qc_norm_text(caption)
        alt_n = _qc_norm_text(alt_text)
        kw_terms = _qc_keywords(keywords)
        kw_sig = "|".join(sorted(kw_terms))

        row_meta[rid] = {
            "file_name": file_name,
            "subject": subject,
            "location": location,
        }

        if cap_n:
            cap_map.setdefault(cap_n, []).append(rid)
        if alt_n:
            alt_map.setdefault(alt_n, []).append(rid)
        if kw_sig:
            kw_sig_map.setdefault(kw_sig, []).append(rid)
        if cap_n and alt_n:
            pair_map.setdefault(f"{cap_n}||{alt_n}", []).append(rid)

        reasons: set[str] = set()
        if cap_n and alt_n and cap_n == alt_n:
            reasons.add("caption_equals_alt")
        if len(cap_n.split()) < 7:
            reasons.add("caption_too_short")
        if len(alt_n.split()) < 6:
            reasons.add("alt_too_short")
        if len(kw_terms) < 6:
            reasons.add("too_few_keywords")

        text_blob = f"{cap_n} {alt_n} {' '.join(kw_terms)}"
        context_blob = _qc_norm_text(f"{file_name} {subject} {location}")
        nature_ctx = any(c in context_blob for c in _QC_NATURE_CUES)
        urban_ctx = any(c in context_blob for c in _QC_URBAN_CUES)
        strong_urban = any(c in text_blob for c in _QC_STRONG_URBAN_WORDS)
        if nature_ctx and not urban_ctx and strong_urban:
            reasons.add("urban_terms_vs_nature_context")
        if any(p in text_blob for p in _QC_GENERIC_PHRASES):
            reasons.add("generic_template_phrase")

        if reasons:
            suspicious_only_ids.add(rid)
            id_reasons.setdefault(rid, set()).update(reasons)

    cap_dups = [v for v in cap_map.values() if len(v) > 1]
    alt_dups = [v for v in alt_map.values() if len(v) > 1]
    kw_dups = [v for v in kw_sig_map.values() if len(v) > 1]
    pair_dups = [v for v in pair_map.values() if len(v) > 1]

    cap_g, cap_r = _qc_add_dup_reasons(id_reasons, cap_dups, "duplicate_caption_exact")
    alt_g, alt_r = _qc_add_dup_reasons(id_reasons, alt_dups, "duplicate_alt_exact")
    kw_g, kw_r = _qc_add_dup_reasons(id_reasons, kw_dups, "duplicate_keywords_signature")
    pair_g, pair_r = _qc_add_dup_reasons(id_reasons, pair_dups, "duplicate_caption_alt_pair")

    cap_alt_equal_rows = sum(
        1
        for r in rows
        if _qc_norm_text(str(r["Caption"] or ""))
        and _qc_norm_text(str(r["Caption"] or "")) == _qc_norm_text(str(r["alt_text"] or ""))
    )
    if cap_alt_equal_rows > 0:
        for r in rows:
            rid = int(r["id"])
            if _qc_norm_text(str(r["Caption"] or "")) and _qc_norm_text(
                str(r["Caption"] or "")
            ) == _qc_norm_text(str(r["alt_text"] or "")):
                id_reasons.setdefault(rid, set()).add("caption_equals_alt")

    duplicate_ids: set[int] = set()
    for grp in cap_dups + alt_dups + kw_dups + pair_dups:
        duplicate_ids.update(grp)

    flagged_ids = sorted(id_reasons.keys())
    summary.update(
        {
            "caption_dup_groups": cap_g,
            "caption_dup_rows": cap_r,
            "alt_dup_groups": alt_g,
            "alt_dup_rows": alt_r,
            "keywords_dup_groups": kw_g,
            "keywords_dup_rows": kw_r,
            "caption_alt_pair_dup_groups": pair_g,
            "caption_alt_pair_dup_rows": pair_r,
            "caption_alt_equal_rows": int(cap_alt_equal_rows),
            "suspicious_rows": len(suspicious_only_ids),
            "duplicate_rows_total": len(duplicate_ids),
            "flagged_rows_total": len(flagged_ids),
            "sample_ids": flagged_ids[: max(1, int(sample_ids))],
        }
    )

    try:
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        details = {
            "summary": summary,
            "flagged": [
                {
                    "id": rid,
                    "file_name": row_meta.get(rid, {}).get("file_name", ""),
                    "subject": row_meta.get(rid, {}).get("subject", ""),
                    "location": row_meta.get(rid, {}).get("location", ""),
                    "reasons": sorted(list(id_reasons.get(rid, set()))),
                }
                for rid in flagged_ids
            ],
        }
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(details, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[WARN] Could not write prefill QC report: {e}")

    return summary


def _format_prefill_qc_message(summary: dict) -> str:
    if not summary:
        return ""
    rows = int(summary.get("row_count", 0) or 0)
    dup_rows = int(summary.get("duplicate_rows_total", 0) or 0)
    suspicious = int(summary.get("suspicious_rows", 0) or 0)
    samples = summary.get("sample_ids") or []
    sample_txt = ", ".join([str(x) for x in samples]) if samples else "-"
    report_path = str(summary.get("report_path", "") or "")

    if dup_rows <= 0:
        lead = f"No duplicates found in {rows} pending rows."
    else:
        lead = f"Duplicate check found {dup_rows} duplicated rows in {rows} pending rows."

    lines = [
        lead,
        f"Caption duplicate groups: {int(summary.get('caption_dup_groups', 0) or 0)}",
        f"Alt duplicate groups: {int(summary.get('alt_dup_groups', 0) or 0)}",
        f"Keyword-signature duplicate groups: {int(summary.get('keywords_dup_groups', 0) or 0)}",
        f"Suspicious rows auto-flagged: {suspicious}",
        f"Sample flagged IDs: {sample_txt}",
    ]
    if report_path:
        lines.append(f"Report: {report_path}")
    return "\n".join(lines)


_METADATA_QUALITY_POPUP_KEYS = [
    "proof_status",
    "rows_checked",
    "rows_exported",
    "rows_blocked",
    "duplicate_caption_groups",
    "duplicate_alt_groups",
    "duplicate_keyword_groups",
    "image_grounded_duplicate_caption_groups",
    "image_grounded_duplicate_alt_groups",
    "near_duplicate_caption_groups",
    "near_duplicate_alt_groups",
    "near_duplicate_keyword_groups",
    "pass_high",
    "pass_repaired",
    "pass_generic",
    "fail_blocked",
    "report_path",
]


def _parse_metadata_quality_summary(
    text: str,
    *,
    total_rows: int = 0,
    accepted_rows: int = 0,
    blocked_rows: int = 0,
) -> dict:
    summary: dict[str, object] = {
        "db_total_rows": int(total_rows or 0),
        "db_accepted_rows": int(accepted_rows or 0),
        "db_blocked_rows": int(blocked_rows or 0),
    }
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if line == "== Metadata quality production run ==":
            summary["has_production_header"] = True
            continue
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", line)
        if match:
            summary[match.group(1)] = match.group(2).strip()
    return summary


def _format_metadata_quality_message(summary: dict) -> str:
    if not summary:
        return ""
    lines = ["== Metadata quality production run =="]
    for key in _METADATA_QUALITY_POPUP_KEYS:
        if key in summary and str(summary.get(key, "")).strip() != "":
            lines.append(f"{key}: {summary.get(key)}")
    total_rows = int(summary.get("db_total_rows", 0) or 0)
    accepted_rows = int(summary.get("db_accepted_rows", 0) or 0)
    blocked_rows = int(summary.get("db_blocked_rows", 0) or 0)
    if total_rows or accepted_rows or blocked_rows:
        lines.append(f"metadata_quality rows: {total_rows}")
        lines.append(f"accepted_for_upload: {accepted_rows}")
        lines.append(f"blocked_rows: {blocked_rows}")
    return "\n".join(lines)


def _b64_image_for_ollama(path: str) -> str:
    # shrink and base64 so the request is small
    from io import BytesIO

    with warnings.catch_warnings():
        try:
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
        except Exception:
            pass
        with Image.open(path) as im:
            try:
                im.draft("RGB", (SUBJECT_THUMB_MAX, SUBJECT_THUMB_MAX))
            except Exception:
                pass
            im = im.convert("RGB")
            im.thumbnail((SUBJECT_THUMB_MAX, SUBJECT_THUMB_MAX))
            buf = BytesIO()
            im.save(buf, format="JPEG", quality=SUBJECT_JPEG_QUALITY)
            return base64.b64encode(buf.getvalue()).decode("ascii")


_LAST_OLLAMA_ERROR = ""

# Domain-aware subject prompt for single or group selections (ONE line output).
_SUBJECT_ROLE_PROMPT = (
    "You are a precise SEO subject line writer with domain awareness across "
    "botany, macro, flowers, insects, birds, mammals, buildings, architecture, city scenes, "
    "travel scenes, landscapes, weather, night sky, and aviation.\n"
    "From the selected image or images, output ONE concise subject line.\n"
    "Use only what is visible in the image. Ignore filename, folder name, and EXIF.\n"
    "Rules: English, ASCII only. Ideal length 45 to 65 characters. Maximum 75.\n"
    "Put the subject first, then one concrete detail.\n"
    "No hype. No fluff. No punctuation in the final line.\n"
    "Do not use these words: macro, photography, photo, image, picture, shot, alt, hdr.\n"
    "For flowers and plants, prefer the safest common name or a precise plant part description.\n"
    "For insects and animals, prefer the safest specific common name you can support.\n"
    "For birds, prefer the safest common species or a useful visible group name supported by bill, wing, leg, plumage, flock, or habitat evidence.\n"
    "Do not return bare group labels like Birds, Animals, Flowers, Plants, Insects, Wildlife, or Waterfowl when a more useful visible name is possible.\n"
    "For buildings and city scenes, use a concrete visual descriptor when exact identity is uncertain.\n"
    "For aircraft, prefer airline plus aircraft family plus visible registration plus flight state when readable from the aircraft itself.\n"
    "Registration may appear on the wing or fuselage.\n"
    "Do not invent airline, subtype, or registration.\n"
    "Do not start the result with generic words like Aircraft, Bird, Flower, Building, Vehicle, or Landscape unless that is truly the most specific visible identification.\n"
    "Examples of good aircraft wording: "
    "Suparna Airlines Boeing 747 B2437 Landing Gear Down, "
    "Suparna Airlines Boeing 747 Landing Gear Down, "
    "Airbus A320 Final Approach.\n"
    "Return ONE line only, no quotes, no extra text."
)

_BANNED_SUBJECT_WORDS = {
    "macro",
    "photography",
    "photo",
    "image",
    "picture",
    "shot",
    "alt",
    "hdr",
}

_SUBJECT_CATEGORY_FALLBACK = {
    "bird": "Bird In Natural Habitat",
    "mammal": "Wild Animal In Habitat",
    "plant": "Plant In Natural Habitat",
    "flower": "Flower Close Up View",
    "tree": "Tree In Natural Habitat",
    "insect": "Insect In Natural Habitat",
    "reptile": "Reptile In Natural Habitat",
    "fish": "Fish In Water Habitat",
    "car": "Car On Road",
    "truck": "Truck On Road",
    "motorcycle": "Motorcycle On Road",
    "vehicle": "Vehicle On Road",
    "aircraft": "Aircraft In Flight",
    "boat": "Boat On Water",
    "building": "Building Exterior View",
    "architecture": "Architectural Detail View",
    "landscape": "Natural Landscape Scene",
    "cityscape": "Urban City Scene",
    "industrial": "Industrial Facility Scene",
    "people": "People Outdoor Scene",
    "food": "Food Detail Scene",
    "object": "Everyday Object Detail",
    "other": "Outdoor Scene Detail",
}
_SUBJECT_CATEGORY_SET = set(_SUBJECT_CATEGORY_FALLBACK.keys())
_SUBJECT_CATEGORY_ALIASES = {
    "birds": "bird",
    "avian": "bird",
    "animals": "mammal",
    "wildlife": "mammal",
    "plants": "plant",
    "flora": "plant",
    "flowers": "flower",
    "trees": "tree",
    "insects": "insect",
    "reptiles": "reptile",
    "fishes": "fish",
    "cars": "car",
    "automobile": "car",
    "auto": "car",
    "trucks": "truck",
    "motorbike": "motorcycle",
    "bikes": "motorcycle",
    "vehicles": "vehicle",
    "plane": "aircraft",
    "planes": "aircraft",
    "airplane": "aircraft",
    "airplanes": "aircraft",
    "boats": "boat",
    "ships": "boat",
    "buildings": "building",
    "city": "cityscape",
    "cities": "cityscape",
    "person": "people",
    "humans": "people",
}
_SUBJECT_ANALYZE_PROMPT_BASE = (
    "Identify the main visible subject in the provided image data.\n"
    "Return ONLY strict one-line JSON with this exact schema:\n"
    '{"primary_subject":"","category":"","detail":"","airline":"","aircraft_family":"","variant":"","registration":"","state":"","visible_text":"","confidence":0}\n'
    "Rules:\n"
    "1) category must be one of: "
    "bird, mammal, plant, flower, tree, insect, reptile, fish, "
    "car, truck, motorcycle, vehicle, aircraft, boat, building, architecture, "
    "landscape, cityscape, industrial, people, food, object, other.\n"
    "2) Use only what is visible in the image. Ignore filename, folder name, and EXIF.\n"
    "3) primary_subject must be the safest specific identification you can support.\n"
    "4) For aircraft, fill airline, aircraft_family, variant, registration, and state only when supported by visible markings, livery text, registration text, airframe shape, or landing gear state.\n"
    "5) Registration may be visible on wing or fuselage.\n"
    "6) For flowers, insects, birds, mammals, buildings, city scenes, and landscapes, be as specific as the image supports without guessing.\n"
    "6b) For birds, flowers, insects, plants, and animals, use visible traits to choose the safest common species or common group name; avoid bare group labels when a better visible name is possible.\n"
    "7) If uncertain, keep primary_subject broader and confidence <= 60.\n"
    "8) detail should be 2 to 7 words of concrete visible context.\n"
    "9) visible_text should contain only text you can actually read from the image.\n"
    "10) No markdown, no commentary, no extra keys."
)
_SUBJECT_ANALYZE_PROMPT_SINGLE = (
    _SUBJECT_ANALYZE_PROMPT_BASE + "\nThis is one photo. Return JSON only."
)
_SUBJECT_ANALYZE_PROMPT_MULTI = (
    _SUBJECT_ANALYZE_PROMPT_BASE
    + "\nThese photos are one set. Find the common main subject across the set. Return JSON only."
)

_SUBJECT_ANALYZE_PROMPT_RETRY = (
    _SUBJECT_ANALYZE_PROMPT_BASE
    + "\nBe conservative. Read visible text exactly from the image."
    + "\nFor aircraft, prefer readable airline text, Boeing or Airbus family, readable registration, and landing gear state."
    + "\nIf text is not actually readable, leave the field blank."
    + "\nReturn JSON only."
)

def _smart_title_case(words: list[str]) -> str:
    out: list[str] = []
    for w in words:
        if not w:
            continue
        if w.isupper() and len(w) <= 6:
            out.append(w)
            continue
        out.append(w[:1].upper() + w[1:].lower())
    return " ".join(out)


def _normalize_subject_line(
    raw: str, *, max_chars: int = 75, max_words: int | None = None, min_words: int = 2
) -> str | None:
    if not raw:
        return None

    line = raw.splitlines()[0].strip()
    line = line.encode("ascii", "ignore").decode("ascii")

    line = re.sub(r"[`\"']", "", line)
    line = re.sub(r"[^A-Za-z0-9\s]", "", line)
    line = re.sub(r"\s+", " ", line).strip()

    if not line:
        return None

    words = [w for w in line.split() if w and w.lower() not in _BANNED_SUBJECT_WORDS]

    if max_words is not None:
        words = words[:max_words]

    if len(words) < min_words:
        return None

    line = _smart_title_case(words)

    if len(line) > max_chars:
        cut = line[:max_chars].rstrip()
        # Avoid chopping words in the middle when we enforce max chars.
        space_at = cut.rfind(" ")
        if space_at >= max(1, int(max_chars * 0.6)):
            cut = cut[:space_at].rstrip()
        # Keep trailing joiners (e.g. "in", "of", "the") if the user/AI output
        # naturally ends with them after max-char trimming.
        cut = cut.strip()
        line = cut

    return line


def _subject_line_is_too_generic(line: str) -> bool:
    s = re.sub(r"\s+", " ", str(line or "").strip().lower())
    if not s:
        return True

    strict_identifier = os.getenv("AMIR_SUBJECT_IDENTIFY_MODE", "").strip() == "1"
    living_generic_exact = {
        "bird in natural habitat",
        "birds in natural habitat",
        "bird in flight",
        "birds in flight",
        "bird formation",
        "birds formation",
        "birds formation flying",
        "flock of birds",
        "bird flock",
        "birds flock",
        "waterfowl",
        "shorebirds",
        "wading birds",
        "wild animal in habitat",
    }
    generic_exact = {
        "aircraft in flight",
        "aircraft large commercial jet",
        "large commercial jet",
        "commercial jet",
        "bird in natural habitat",
        "birds in natural habitat",
        "bird in flight",
        "birds in flight",
        "bird formation",
        "birds formation",
        "birds formation flying",
        "flock of birds",
        "bird flock",
        "birds flock",
        "waterfowl",
        "shorebirds",
        "wading birds",
        "wild animal in habitat",
        "building exterior view",
        "urban city scene",
        "natural landscape scene",
        "outdoor scene detail",
        "vehicle on road",
        "boat on water",
    }
    if s in generic_exact:
        if strict_identifier or s not in living_generic_exact:
            return True

    if s.startswith("aircraft "):
        return True

    toks = s.split()
    weak_taxon_roots = {
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
        "tree",
        "trees",
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
        "waterfowl",
        "shorebird",
        "shorebirds",
        "wader",
        "waders",
    }
    weak_taxon_context = {
        "in",
        "on",
        "at",
        "of",
        "the",
        "with",
        "calm",
        "over",
        "above",
        "open",
        "black",
        "white",
        "brown",
        "grey",
        "gray",
        "red",
        "orange",
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
        "chestnut",
        "rufous",
        "russet",
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
        "sky",
        "flight",
        "flying",
        "swimming",
        "floating",
        "grazing",
        "standing",
        "walking",
        "resting",
        "habitat",
        "scene",
        "view",
        "sequence",
        "sequences",
        "close",
        "closeup",
        "closeups",
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
        "leg",
        "legs",
        "feet",
        "foot",
        "fur",
        "plumage",
        "marking",
        "markings",
        "petal",
        "petals",
        "stem",
        "stems",
        "branch",
        "branches",
        "group",
        "flock",
    }
    if strict_identifier and any(tok in weak_taxon_roots for tok in toks):
        useful = [
            tok
            for tok in toks
            if tok not in weak_taxon_roots
            and tok not in weak_taxon_context
        ]
        if not useful:
            return True

    living_prefixes = {"bird", "birds", "animal"}
    broad_prefixes = {
        "aircraft",
        "building",
        "vehicle",
        "boat",
        "landscape",
        "cityscape",
        "object",
    }
    if len(toks) <= 3 and (
        toks[0] in broad_prefixes or (strict_identifier and toks[0] in living_prefixes)
    ):
        return True

    return False


def _subject_to_int(v, default: int = 0) -> int:
    try:
        n = int(float(v))
    except Exception:
        n = default
    return max(0, min(100, n))

def _extract_json_object(raw: str) -> dict | None:
    s = str(raw or "").strip()
    if not s:
        return None

    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    m = re.search(r"\{[\s\S]*\}", s)
    if not m:
        return None

    try:
        obj = json.loads(m.group(0))
        if isinstance(obj, dict):
            return obj
    except Exception:
        return None

    return None

def _format_aircraft_model_token(value: str) -> str:
    token = re.sub(r"\s+", " ", str(value or "").strip().upper())
    token = re.sub(r"\b([A-Z]?\d{3,4}[A-Z]?)[-\s]+([0-9A-Z]{2,5})\b", r"\1-\2", token)
    return token


def _format_aircraft_registration(prefix: str, suffix: str = "") -> str:
    prefix = re.sub(r"[^A-Z0-9]+", "", str(prefix or "").upper())
    suffix = re.sub(r"[^A-Z0-9]+", "", str(suffix or "").upper())
    if not prefix:
        return ""
    if suffix:
        return f"{prefix}-{suffix}"
    return prefix


def _aircraft_registration_from_text(text: str) -> str:
    value = str(text or "").upper()
    if not value:
        return ""

    patterns = [
        r"\b(PH|OO|EI|EC|LN|SE|OY|TF|HB|CS|SP|TC|YU|9H|A6|JA|HL|VH|ZK|LX|OK|OM|OE|RA|VP|VQ|XA|PT|PR|PP|LV|CC|ZS|4X)[-\s]?([A-Z0-9]{3,5})\b",
        r"\b(G|D|F|C)[-\s]([A-Z]{3,5})\b",
        r"\b(N[0-9][0-9A-Z]{2,5})\b",
        r"\b(B)[-\s]([0-9A-Z]{4,5})\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, value)
        if not match:
            continue

        if len(match.groups()) == 1:
            return _format_aircraft_registration(match.group(1))

        return _format_aircraft_registration(match.group(1), match.group(2))

    return ""


def _aircraft_model_from_text(text: str) -> str:
    value = str(text or "")
    patterns = [
        (r"\bBoeing\s+(7[0-9]7(?:[-\s]?[0-9A-Z]{2,4})?)\b", "Boeing"),
        (r"\b(7[0-9]7[-\s]?[0-9A-Z]{2,4})\b", "Boeing"),
        (r"\bAirbus\s+(A[0-9]{3}(?:[-\s]?[0-9A-Z]{2,4})?)\b", "Airbus"),
        (r"\b(A[0-9]{3}(?:[-\s]?[0-9A-Z]{2,4})?)\b", "Airbus"),
        (r"\bEmbraer\s+((?:E|ERJ)[-\s]?[0-9]{3,4})\b", "Embraer"),
        (r"\bATR\s+([0-9]{2}(?:[-\s]?[0-9]{3})?)\b", "ATR"),
        (r"\bBombardier\s+([A-Z]{2,4}[-\s]?[0-9]{3,4})\b", "Bombardier"),
        (r"\bCessna\s+([0-9]{3,4}[A-Z]?)\b", "Cessna"),
    ]

    for pattern, maker in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if match:
            model = _format_aircraft_model_token(match.group(1))
            label = re.sub(r"\s+", " ", f"{maker} {model}").strip()
            return label[:50].strip()

    return ""


def _extract_aircraft_visible_fields(visible_text: str) -> tuple[str, str]:
    vt = re.sub(r"\s+", " ", str(visible_text or "").strip())
    if not vt:
        return "", ""

    airline = ""
    registration = ""

    m_air = re.search(
        r"\b([A-Za-z][A-Za-z0-9]+(?:\s+[A-Za-z][A-Za-z0-9]+){0,2}\s+(?:Airlines?|Cargo))\b",
        vt,
        flags=re.IGNORECASE,
    )
    if m_air:
        airline = (
            _normalize_subject_line(
                m_air.group(1),
                max_chars=50,
                max_words=4,
                min_words=1,
            )
            or ""
        )

    registration = _aircraft_registration_from_text(vt)

    return airline, registration

def _line_has_registration(line: str) -> bool:
    return bool(_aircraft_registration_from_text(str(line or "")))


def _b64_aircraft_reg_crop(path: str) -> str | None:
    from io import BytesIO

    try:
        with warnings.catch_warnings():
            try:
                warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            except Exception:
                pass

            with Image.open(path) as im:
                im = im.convert("RGB")
                w, h = im.size

                x1 = max(0, int(w * 0.28))
                y1 = max(0, int(h * 0.12))
                x2 = min(w, int(w * 0.90))
                y2 = min(h, int(h * 0.82))

                crop = im.crop((x1, y1, x2, y2))
                crop.thumbnail((1792, 1792))

                buf = BytesIO()
                crop.save(buf, format="JPEG", quality=max(90, SUBJECT_JPEG_QUALITY))
                return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return None


def _pick_aircraft_verify_model() -> str:
    preferred = "qwen2.5vl:7b"
    names = _ollama_model_names(timeout=3)
    if names:
        resolved = _resolve_ollama_model_alias(preferred, names)
        if resolved:
            return resolved
    return preferred

def _b64_zoom_crops_for_text(path: str) -> list[str]:
    from io import BytesIO

    out: list[str] = []

    with warnings.catch_warnings():
        try:
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
        except Exception:
            pass

        with Image.open(path) as im:
            im = im.convert("RGB")
            w, h = im.size

            crops = [
                (0.20, 0.15, 0.88, 0.78),  # aircraft body
                (0.34, 0.08, 0.78, 0.48),  # upper wing and wing text
                (0.40, 0.28, 0.94, 0.82),  # rear fuselage and tail
            ]

            for x1r, y1r, x2r, y2r in crops:
                x1 = max(0, min(w - 1, int(w * x1r)))
                y1 = max(0, min(h - 1, int(h * y1r)))
                x2 = max(x1 + 1, min(w, int(w * x2r)))
                y2 = max(y1 + 1, min(h, int(h * y2r)))

                crop = im.crop((x1, y1, x2, y2))
                crop.thumbnail((1792, 1792))

                buf = BytesIO()
                crop.save(buf, format="JPEG", quality=max(90, SUBJECT_JPEG_QUALITY))
                out.append(base64.b64encode(buf.getvalue()).decode("ascii"))

    return out


def _aircraft_registration_from_analysis(raw: str) -> str:
    data = _extract_json_object(raw)
    if not data:
        return ""

    visible_text = str(data.get("visible_text") or "")
    _, visible_registration = _extract_aircraft_visible_fields(visible_text)
    if visible_registration:
        return visible_registration

    reg_raw = _aircraft_registration_from_text(str(data.get("registration") or ""))
    if reg_raw:
        return reg_raw

    return ""


def _merge_aircraft_registration(line: str, registration: str) -> str:
    base = _normalize_subject_line(
        line,
        max_chars=SUBJECT_MAX_CHARS,
        max_words=None,
        min_words=3,
    )
    reg = _aircraft_registration_from_text(str(registration or ""))
    if not reg:
        reg = re.sub(r"[^A-Z0-9]+", " ", str(registration or "").upper()).strip()

    if not base or not reg:
        return base or ""
    if reg.lower() in base.lower():
        return base

    state_phrases = [
        " Landing Gear Down",
        " Final Approach",
        " On Approach",
        " Approach",
        " Takeoff",
        " Ascending",
        " Descending",
        " Taxiing",
        " In Flight",
    ]

    for phrase in state_phrases:
        if base.endswith(phrase):
            merged = base[: -len(phrase)].rstrip() + f" {reg}" + phrase
            return (
                _normalize_subject_line(
                    merged,
                    max_chars=SUBJECT_MAX_CHARS,
                    max_words=None,
                    min_words=3,
                )
                or base
            )

    merged = f"{base} {reg}"
    return (
        _normalize_subject_line(
            merged,
            max_chars=SUBJECT_MAX_CHARS,
            max_words=None,
            min_words=3,
        )
        or base
    )

def _normalize_subject_category(raw: str) -> str:
    s = re.sub(r"[^a-z]+", "", str(raw or "").lower())
    if s in _SUBJECT_CATEGORY_SET:
        return s
    if s in _SUBJECT_CATEGORY_ALIASES:
        return _SUBJECT_CATEGORY_ALIASES[s]
    if "bird" in s:
        return "bird"
    if "plant" in s or "flora" in s:
        return "plant"
    if "car" in s:
        return "car"
    if "truck" in s:
        return "truck"
    if "motor" in s or "bike" in s:
        return "motorcycle"
    if "vehicle" in s:
        return "vehicle"
    if "air" in s or "plane" in s:
        return "aircraft"
    if "boat" in s or "ship" in s:
        return "boat"
    if "build" in s or "architect" in s:
        return "building"
    if "city" in s or "urban" in s:
        return "cityscape"
    if "landscape" in s or "nature" in s:
        return "landscape"
    return "other"


def _subject_filename_context(paths: list[str]) -> str:
    return ""


def _subject_generate(
    *,
    model: str,
    prompt: str,
    images: list[str],
    temperature: float,
    num_predict: int,
    timeout_sec: int,
) -> str | None:
    global _LAST_OLLAMA_ERROR

    payload = {
        "model": model,
        "prompt": prompt,
        "images": images,
        "stream": False,
        "options": {
            "temperature": float(temperature),
            "num_predict": int(num_predict),
            "top_p": 0.9,
            "top_k": 40,
            "repeat_penalty": 1.1,
            "repeat_last_n": 64,
            "seed": 42,
        },
    }

    try:
        req = request.Request(
            f"http://{OLLAMA_HOST}:{OLLAMA_PORT}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=max(20, int(timeout_sec))) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            data = json.loads(body)
    except request.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="replace").strip()
        except Exception:
            err_body = ""
        _LAST_OLLAMA_ERROR = (
            f"Ollama request failed: HTTP {e.code}"
            + (f"\n\n{err_body}" if err_body else f" {e.reason}")
        )
        return None
    except Exception as e:
        _LAST_OLLAMA_ERROR = f"Ollama request failed: {type(e).__name__}: {e}"
        return None

    if isinstance(data, dict) and data.get("error"):
        _LAST_OLLAMA_ERROR = str(data.get("error"))
        return None

    raw = (data.get("response") or "").strip() if isinstance(data, dict) else ""
    if not raw:
        _LAST_OLLAMA_ERROR = "Model returned empty response."
        return None
    return raw

def _subject_line_from_analysis(raw: str, *, max_chars: int) -> str | None:
    data = _extract_json_object(raw)
    if not data:
        return None

    category = _normalize_subject_category(str(data.get("category") or ""))
    confidence = _subject_to_int(data.get("confidence"), default=0)

    if category == "aircraft":
        visible_text = str(data.get("visible_text") or "")
        visible_airline, visible_registration = _extract_aircraft_visible_fields(visible_text)

        airline_model = _normalize_subject_line(
            str(data.get("airline") or ""),
            max_chars=max_chars,
            max_words=4,
            min_words=1,
        )
        family = _normalize_subject_line(
            str(data.get("aircraft_family") or data.get("primary_subject") or ""),
            max_chars=max_chars,
            max_words=5,
            min_words=1,
        )
        if not family:
            family = _aircraft_model_from_text(
                " ".join(
                    str(data.get(key) or "")
                    for key in ["visible_text", "evidence", "detail", "primary_subject"]
                )
            )
        state = _normalize_subject_line(
            str(data.get("state") or data.get("detail") or ""),
            max_chars=max_chars,
            max_words=4,
            min_words=1,
        )

        airline = ""
        if visible_airline:
            airline = visible_airline
        elif airline_model and airline_model.lower() in visible_text.lower():
            airline = airline_model

        if family:
            family_l = family.lower()
            if family_l.startswith("aircraft"):
                family = ""
            elif not re.search(
                r"\b(boeing|airbus|embraer|bombardier|atr|cessna|antonov|747|737|757|767|777|787|a220|a300|a310|a318|a319|a320|a321|a330|a340|a350|a380)\b",
                family_l,
            ):
                family = ""

        registration = visible_registration
        if not registration:
            reg_raw = _aircraft_registration_from_text(str(data.get("registration") or ""))
            vis_u = re.sub(r"[^A-Z0-9]+", "", visible_text.upper())
            reg_key = re.sub(r"[^A-Z0-9]+", "", reg_raw.upper())
            if reg_raw and len(reg_key) >= 4 and reg_key in vis_u:
                registration = reg_raw

        if state:
            state_l = state.lower()
            allowed_state = (
                "landing gear down",
                "final approach",
                "on approach",
                "approach",
                "takeoff",
                "ascending",
                "descending",
                "taxiing",
            )
            if not any(x in state_l for x in allowed_state):
                state = ""

        parts: list[str] = []

        if airline:
            parts.append(airline)

        if family:
            parts.append(family)

        if registration:
            joined = " ".join(parts).lower()
            if registration.lower() not in joined:
                parts.append(registration)

        if state:
            joined = " ".join(parts).lower()
            if state.lower() not in joined:
                parts.append(state)

        line = _normalize_subject_line(
            " ".join(parts),
            max_chars=max_chars,
            max_words=None,
            min_words=3,
        )
        if line and not _subject_line_is_too_generic(line):
            return line

    primary = _normalize_subject_line(
        str(data.get("primary_subject") or ""),
        max_chars=max_chars,
        max_words=8,
        min_words=1,
    )
    detail = _normalize_subject_line(
        str(data.get("detail") or ""),
        max_chars=max_chars,
        max_words=5,
        min_words=1,
    )

    if confidence < SUBJECT_MIN_CONFIDENCE:
        primary = None

    if not primary:
        primary = _SUBJECT_CATEGORY_FALLBACK.get(
            category,
            _SUBJECT_CATEGORY_FALLBACK["other"],
        )

    if detail:
        pw = {w.lower() for w in primary.split()}
        dw = [w for w in detail.split() if w.lower() not in pw]
        detail = " ".join(dw).strip()

    line_raw = f"{primary} {detail}".strip() if detail else primary
    out = _normalize_subject_line(
        line_raw,
        max_chars=max_chars,
        max_words=None,
        min_words=3,
    )
    if out and not _subject_line_is_too_generic(out):
        return out

    return None

def ai_suggest_subject_multi(image_paths: list[str]) -> str | None:
    """Return one subject line for a single image or a group selection."""
    global _LAST_OLLAMA_ERROR
    _LAST_OLLAMA_ERROR = ""

    def _consensus(lines: list[str]) -> str | None:
        counts: dict[str, int] = {}
        keep: dict[str, str] = {}

        for line in lines:
            clean = _normalize_subject_line(
                line,
                max_chars=SUBJECT_MAX_CHARS,
                max_words=None,
                min_words=1,
            )
            if not clean:
                continue
            key = clean.lower()
            counts[key] = counts.get(key, 0) + 1
            if key not in keep:
                keep[key] = clean

        if not counts:
            return None

        best_key = sorted(
            counts.keys(),
            key=lambda k: (
                -counts[k],
                -sum(ch.isdigit() for ch in k),
                -len(k.split()),
                -len(k),
                k,
            ),
        )[0]
        return keep[best_key]

    paths = [p for p in (image_paths or []) if p and os.path.isfile(p)]
    if not paths:
        _LAST_OLLAMA_ERROR = "No valid image files were selected."
        return None

    if len(paths) == 1:
        return ai_suggest_subject(paths[0])

    try:
        take = min(4, len(paths))
        idxs = (
            [round(i * (len(paths) - 1) / (take - 1)) for i in range(take)]
            if take > 1
            else [0]
        )
        pick = [paths[i] for i in idxs]
    except Exception as e:
        _LAST_OLLAMA_ERROR = f"Failed to prepare image selection: {e}"
        return None

    candidate_lines: list[str] = []
    last_error = ""

    for path in pick:
        guess = ai_suggest_subject(path)
        if guess:
            candidate_lines.append(guess)
            continue
        if _LAST_OLLAMA_ERROR:
            last_error = _LAST_OLLAMA_ERROR

    final_line = _consensus(candidate_lines)
    if final_line:
        return final_line

    _LAST_OLLAMA_ERROR = last_error or "Model could not produce a usable subject suggestion."
    return None

def ai_suggest_subject(image_path: str) -> str | None:
    """Return a short subject suggestion via Ollama (vision model)."""
    global _LAST_OLLAMA_ERROR
    _LAST_OLLAMA_ERROR = ""

    if not os.path.isfile(image_path):
        return None

    try:
        quick = _nature_subject_from_classifier(image_path)
        if quick:
            return quick
    except Exception:
        pass

    if not _ensure_ollama_running():
        _LAST_OLLAMA_ERROR = f"Ollama is not responding on {OLLAMA_HOST}:{OLLAMA_PORT}."
        return None

    subject_model = _pick_subject_model()
    if not _ensure_ollama_model(subject_model):
        wanted = ", ".join(SUBJECT_MODEL_CANDIDATES or (OLLAMA_MODEL,))
        _LAST_OLLAMA_ERROR = (
            f"No usable subject model found. Install one of: {wanted}"
        )
        return None

    imgs = [_b64_image_for_ollama(image_path)]
    timeout_sec = int(os.getenv("SUBJECT_TIMEOUT_SEC", "120"))

    analysis_raw = _subject_generate(
        model=subject_model,
        prompt=_SUBJECT_ANALYZE_PROMPT_SINGLE,
        images=imgs,
        temperature=0.0,
        num_predict=180,
        timeout_sec=timeout_sec,
    )

    best_line = _subject_line_from_analysis(
        analysis_raw or "",
        max_chars=SUBJECT_MAX_CHARS,
    )

    data = _extract_json_object(analysis_raw or "") or {}
    is_aircraft = _normalize_subject_category(str(data.get("category") or "")) == "aircraft"

    if best_line and not _subject_line_is_too_generic(best_line) and not is_aircraft:
        return best_line

    if best_line and not _subject_line_is_too_generic(best_line) and is_aircraft and _line_has_registration(best_line):
        return best_line

    if is_aircraft:
        reg_crop = _b64_aircraft_reg_crop(image_path)
        if reg_crop:
            verify_model = _pick_aircraft_verify_model()

            analysis_crop = _subject_generate(
                model=verify_model,
                prompt=_SUBJECT_ANALYZE_PROMPT_RETRY,
                images=[reg_crop],
                temperature=0.0,
                num_predict=220,
                timeout_sec=timeout_sec,
            )

            crop_line = _subject_line_from_analysis(
                analysis_crop or "",
                max_chars=SUBJECT_MAX_CHARS,
            )

            reg = _aircraft_registration_from_analysis(analysis_crop or "")
            if not reg:
                reg = _aircraft_registration_from_analysis(analysis_raw or "")

            if crop_line and not _subject_line_is_too_generic(crop_line):
                if reg and not _line_has_registration(crop_line):
                    crop_line = _merge_aircraft_registration(crop_line, reg)
                return crop_line

            if best_line and not _subject_line_is_too_generic(best_line):
                if reg and not _line_has_registration(best_line):
                    best_line = _merge_aircraft_registration(best_line, reg)
                return best_line

        if best_line and not _subject_line_is_too_generic(best_line):
            return best_line

        _LAST_OLLAMA_ERROR = "Aircraft subject was found, but readable registration was not verified."
        return None

    raw = _subject_generate(
        model=subject_model,
        prompt=_SUBJECT_ROLE_PROMPT,
        images=imgs,
        temperature=0.1,
        num_predict=60,
        timeout_sec=timeout_sec,
    )
    if not raw:
        return None

    line = _normalize_subject_line(
        raw,
        max_chars=SUBJECT_MAX_CHARS,
        max_words=None,
        min_words=3,
    )
    if not line:
        _LAST_OLLAMA_ERROR = "Model output was not usable after sanitizing."
        return None

    if _subject_line_is_too_generic(line):
        _LAST_OLLAMA_ERROR = f"Model output stayed too generic: {line}"
        return None

    return line
# ---------- Utilities you already have ----------
from utils.file_namer import (
    get_exif_data,
    get_camera_model,
    get_exif_year,
    generate_unique_filename,
    slugify,
)


def resource_path(rel):
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
        p = os.path.join(base, rel)
        if os.path.exists(p):
            return p
        try:
            return os.path.join(sys._MEIPASS, rel)  # type: ignore[attr-defined]
        except Exception:
            return p
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), rel)


def _copy_if_changed(src: str, dst: str) -> None:
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        if os.path.exists(dst):
            s1 = os.stat(src)
            s2 = os.stat(dst)
            if int(s1.st_size) == int(s2.st_size) and filecmp.cmp(src, dst, shallow=False):
                return
    except Exception:
        pass
    shutil.copy2(src, dst)


def _prepare_external_script(rel_script: str) -> str:
    """
    In frozen onefile mode, avoid executing helper scripts directly from _MEI
    with external Python (3.13), because _MEI contains 3.12 extension binaries.
    """
    src = resource_path(rel_script)
    if not getattr(sys, "frozen", False):
        return src

    try:
        mei = os.path.normcase(os.path.normpath(str(getattr(sys, "_MEIPASS", "") or "")))
        src_n = os.path.normcase(os.path.normpath(str(src)))
        if mei and src_n.startswith(mei):
            rt_root = os.path.join(DATA_DIR, "_runtime_scripts")
            os.makedirs(rt_root, exist_ok=True)

            rel_norm = rel_script.replace("/", os.sep).replace("\\", os.sep)
            dst_script = os.path.join(rt_root, rel_norm)
            os.makedirs(os.path.dirname(dst_script), exist_ok=True)
            _copy_if_changed(src, dst_script)

            # Keep config available for helper scripts that probe beside __file__.
            cfg_src = resource_path("amir2000_config.py")
            if cfg_src and os.path.exists(cfg_src):
                _copy_if_changed(cfg_src, os.path.join(rt_root, "amir2000_config.py"))

            base_name = os.path.basename(rel_script).lower()

            if base_name == "caption_review_local.py":
                data_dst = os.path.join(rt_root, "data")
                os.makedirs(data_dst, exist_ok=True)
                for fn in ("location_list.json", "folder_map.json"):
                    cand = [
                        os.path.join(os.path.dirname(src), "data", fn),
                        os.path.join(DATA_DIR, fn),
                    ]
                    for cs in cand:
                        if cs and os.path.exists(cs):
                            _copy_if_changed(cs, os.path.join(data_dst, fn))
                            break

                for extra in ("metadata_evidence_pipeline.py",):
                    ex_src = resource_path(extra)
                    if ex_src and os.path.exists(ex_src):
                        _copy_if_changed(ex_src, os.path.join(rt_root, os.path.basename(extra)))

            if base_name == "batch_image_quality_score.py":
                # Optional extras to keep CLIP aesthetic path working.
                for extra in ("simple_inference.py", "sac+logos+ava1-l14-linearMSE.pth"):
                    ex_src = resource_path(extra)
                    if ex_src and os.path.exists(ex_src):
                        _copy_if_changed(ex_src, os.path.join(rt_root, os.path.basename(extra)))

                # The scorer imports this at startup. In onefile EXE mode the
                # script runs from data/_runtime_scripts, so copy the tiny helper
                # package beside it instead of letting scoring die before it starts.
                utils_dst = os.path.join(rt_root, "utils")
                os.makedirs(utils_dst, exist_ok=True)
                force_logs_src = resource_path(os.path.join("utils", "force_logs_dir.py"))
                if force_logs_src and os.path.exists(force_logs_src):
                    _copy_if_changed(force_logs_src, os.path.join(utils_dst, "force_logs_dir.py"))
                init_dst = os.path.join(utils_dst, "__init__.py")
                if not os.path.exists(init_dst):
                    with open(init_dst, "w", encoding="utf-8") as _f:
                        _f.write("# runtime utils package\n")

            if base_name in {
                "caption_review_local.py",
                "batch_image_quality_score.py",
                "metadata_quality_production.py",
            }:
                utils_dst = os.path.join(rt_root, "utils")
                os.makedirs(utils_dst, exist_ok=True)
                force_logs_src = resource_path(os.path.join("utils", "force_logs_dir.py"))
                if force_logs_src and os.path.exists(force_logs_src):
                    _copy_if_changed(force_logs_src, os.path.join(utils_dst, "force_logs_dir.py"))
                init_dst = os.path.join(utils_dst, "__init__.py")
                if not os.path.exists(init_dst):
                    with open(init_dst, "w", encoding="utf-8") as _f:
                        _f.write("# runtime utils package\n")

            if base_name.startswith("identifier_") or base_name in {
                "identifier_router.py",
                "apply_identifier_router_result_to_db.py",
                "subject_identifier_engine.py",
                "subject_identifier_production.py",
                "identifier_biology_runner.py",
            }:
                # Router helpers call modules as python -m scripts.<name>.
                # In onefile mode, copy the scripts package beside the runtime script.
                scripts_src = resource_path("scripts")
                scripts_dst = os.path.join(rt_root, "scripts")
                if scripts_src and os.path.isdir(scripts_src):
                    os.makedirs(scripts_dst, exist_ok=True)
                    for py_file in glob.glob(os.path.join(scripts_src, "*.py")):
                        _copy_if_changed(py_file, os.path.join(scripts_dst, os.path.basename(py_file)))
                    init_dst = os.path.join(scripts_dst, "__init__.py")
                    if not os.path.exists(init_dst):
                        with open(init_dst, "w", encoding="utf-8") as _f:
                            _f.write("# runtime scripts package\n")

            return dst_script
    except Exception as e:
        print(f"[WARN] Could not prepare external script '{rel_script}': {e}")

    return src


# Let helpers read the canonical used_filenames.json (unchanged)
USED_NAMES = os.path.join(DATA_DIR, "used_filenames.json")
os.environ["AMIR_USED_FILENAMES_JSON"] = USED_NAMES
RUNTIME_CRASH_LOG = os.path.join(DATA_DIR, "crash_runtime.log")


# ---------- DB helpers (same schema guard as main.py) ----------
def _ensure_db_table(conn: sqlite3.Connection):
    cur = conn.cursor()
    # current columns (both as a set and ordered list)
    cur.execute(f"PRAGMA table_info({TABLE_NAME})")
    _rows = cur.fetchall()
    have = {r[1] for r in _rows}  # used by add(col, typ)
    order = [r[1] for r in _rows]  # used by migration check

    target = [
        "id",
        "Folder",
        "File_Name",
        "Path",
        "ollama_path",
        "Thumb_Path",
        "DateTime",
        "Camera",
        "Lens_model",
        "Width",
        "Height",
        "Exposure",
        "Aperture",
        "ISO",
        "Focal_length",
        "Keywords",
        "Caption",
        "alt_text",
        "Location",
        "Subject",
        "nima_score",
        "blur_score",
        "brightness_score",
        "contrast_score",
        "QR",
        "QC_Status",
        "Review_Status",
        "Original_File_Name",
        "brisque_score",
        "clip_aesthetic_score",
        "identifier_route",
        "identifier_category",
        "identifier_subject",
        "identifier_confidence",
        "subject_seed",
        "subject_seed_mode",
        "subject_seed_confidence",
        "subject_seed_reason",
        "identifier_raw_json",
        "ai_suggested_subject",
        "final_subject",
        "batch_set_index",
        "batch_set_total",
        "series_key",
        "series_cluster_index",
        "series_position",
        "series_count",
        "series_similarity_score",
        "series_reason",
        "visual_hash",
        "visual_variant",
        "metadata_version",
    ]

    create_review_queue_sql = f"""
        CREATE TABLE {TABLE_NAME}(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            Folder TEXT, File_Name TEXT, Path TEXT, ollama_path TEXT, Thumb_Path TEXT,
            DateTime TEXT, Camera TEXT, Lens_model TEXT,
            Width INTEGER, Height INTEGER, Exposure TEXT, Aperture TEXT,
            ISO INTEGER, Focal_length INTEGER,
            Keywords TEXT, Caption TEXT, alt_text TEXT, Location TEXT, Subject TEXT,
            nima_score REAL, blur_score REAL, brightness_score REAL,
            contrast_score REAL, QR REAL, QC_Status TEXT, Review_Status TEXT,
            Original_File_Name TEXT, brisque_score REAL, clip_aesthetic_score REAL,
            identifier_route TEXT, identifier_category TEXT, identifier_subject TEXT,
            identifier_confidence INTEGER, subject_seed TEXT, subject_seed_mode TEXT,
            subject_seed_confidence INTEGER, subject_seed_reason TEXT, identifier_raw_json TEXT,
            ai_suggested_subject TEXT, final_subject TEXT,
            batch_set_index INTEGER, batch_set_total INTEGER,
            series_key TEXT, series_cluster_index INTEGER,
            series_position INTEGER, series_count INTEGER,
            series_similarity_score REAL, series_reason TEXT,
            visual_hash TEXT, visual_variant TEXT,
            metadata_version INTEGER DEFAULT 1
        )
    """

    if not order:
        cur.execute(create_review_queue_sql)
        conn.commit()
        cur.execute(f"PRAGMA table_info({TABLE_NAME})")
        _rows = cur.fetchall()
        have = {r[1] for r in _rows}
        order = [r[1] for r in _rows]

    if order != target:
        print(
            "[WARN] review_queue column order differs; rebuilding table to match main.py …"
        )
        # Rebuild table with correct column order
        cur.execute(f"ALTER TABLE {TABLE_NAME} RENAME TO {TABLE_NAME}_old")
        cur.execute(create_review_queue_sql)
        cols_in_old = ", ".join([c for c in target if c in order])
        cur.execute(
            f"INSERT INTO {TABLE_NAME} ({cols_in_old}) SELECT {cols_in_old} FROM {TABLE_NAME}_old"
        )
        cur.execute(f"DROP TABLE {TABLE_NAME}_old")
        conn.commit()

        # refresh 'have' after rebuild so add(col, typ) works correctly
        cur.execute(f"PRAGMA table_info({TABLE_NAME})")
        have = {r[1] for r in cur.fetchall()}

    def add(col, typ):
        if col not in have:
            cur.execute(f"ALTER TABLE {TABLE_NAME} ADD COLUMN {col} {typ}")

    for col, typ in [
        ("ollama_path", "TEXT"),
        ("nima_score", "REAL"),
        ("blur_score", "REAL"),
        ("brightness_score", "REAL"),
        ("contrast_score", "REAL"),
        ("QR", "REAL"),
        ("QC_Status", "TEXT"),
        ("Review_Status", "TEXT"),
        ("Original_File_Name", "TEXT"),
        ("brisque_score", "REAL"),
        ("clip_aesthetic_score", "REAL"),
        ("identifier_route", "TEXT"),
        ("identifier_category", "TEXT"),
        ("identifier_subject", "TEXT"),
        ("identifier_confidence", "INTEGER"),
        ("subject_seed", "TEXT"),
        ("subject_seed_mode", "TEXT"),
        ("subject_seed_confidence", "INTEGER"),
        ("subject_seed_reason", "TEXT"),
        ("identifier_raw_json", "TEXT"),
        ("ai_suggested_subject", "TEXT"),
        ("final_subject", "TEXT"),
        ("batch_set_index", "INTEGER"),
        ("batch_set_total", "INTEGER"),
        ("series_key", "TEXT"),
        ("series_cluster_index", "INTEGER"),
        ("series_position", "INTEGER"),
        ("series_count", "INTEGER"),
        ("series_similarity_score", "REAL"),
        ("series_reason", "TEXT"),
        ("visual_hash", "TEXT"),
        ("visual_variant", "TEXT"),
        ("metadata_version", "INTEGER DEFAULT 1"),
    ]:
        add(col, typ)

    conn.commit()


def upsert_review_row(cur: sqlite3.Cursor, row: dict):
    cols = list(row.keys())
    vals = [row[k] for k in cols]
    placeholders = ",".join(["?"] * len(cols))
    cur.execute(
        f"INSERT INTO {TABLE_NAME} ({','.join(cols)}) VALUES ({placeholders})", vals
    )
    return cur.lastrowid


def cleanup_metadata_quality_rows_for_file_names(file_names) -> int:
    """
    Rollback helper.

    Removes local metadata_quality rows for files from a failed batch.
    Uses a fresh DB connection so rollback still works even if the previous
    review_queue connection was already closed.
    """
    import sqlite3
    from pathlib import Path

    names = [
        str(name).strip()
        for name in file_names
        if str(name or "").strip()
    ]

    if not names:
        return 0

    db_path = Path(__file__).resolve().parent / "data" / "review.db"
    placeholders = ",".join("?" for _ in names)

    with sqlite3.connect(db_path) as cleanup_conn:
        cur = cleanup_conn.execute(
            f"""
            DELETE FROM metadata_quality
            WHERE uploaded_to_mysql = 0
              AND revamp_id IS NULL
              AND revamp_File_Name IN ({placeholders})
            """,
            names,
        )
        cleanup_conn.commit()
        return int(cur.rowcount or 0)

def upsert_metadata_quality_seed_from_review_row(cur: sqlite3.Cursor, review_row_id: int, row: dict) -> None:
    """
    Create/update the local metadata_quality row when an image enters review_queue.

    Identity rule:
    - metadata_quality.id = internal quality table id
    - metadata_quality.revamp_id = photos_info_revamp.id after upload
    - review_queue.id = temporary workflow row id and is never stored as revamp_id

    Subject rule:
    - ai_suggested_subject = raw AI suggestion or identifier subject
    - final_subject = accepted UI workflow subject
    - subject_seed = final_subject for metadata bookkeeping
    """
    file_name = str(row.get("File_Name") or "").strip()

    if not file_name:
        return

    subject = str(row.get("Subject") or "").strip()
    ai_suggested_subject = str(row.get("ai_suggested_subject") or row.get("identifier_subject") or "").strip()
    final_subject = str(row.get("final_subject") or subject or "").strip()
    subject_seed_for_mq = final_subject

    caption = str(row.get("Caption") or "").strip()
    alt_text = str(row.get("alt_text") or "").strip()
    keywords = str(row.get("Keywords") or "").strip()
    review_status = str(row.get("Review_Status") or "Queued").strip()

    part_of_serie = 1 if re.search(r"_(\d{3})\.", file_name, flags=re.IGNORECASE) else 0

    cur.execute("""
        INSERT INTO metadata_quality (
            revamp_id,
            revamp_File_Name,
            revamp_Original_File_Name,
            revamp_Location,
            revamp_Folder,
            current_caption,
            current_alt_text,
            current_keywords,
            upload_caption,
            upload_alt_text,
            upload_keywords,
            overall_quality_status,
            overall_quality_score,
            overall_quality_issues,
            generation_mode,
            repair_attempts,
            fallback_used,
            fallback_reason,
            accepted_for_upload,
            caption_accepted_for_upload,
            alt_text_accepted_for_upload,
            keywords_accepted_for_upload,
            part_of_serie,
            unique_name,
            ai_suggested_subject,
            final_subject,
            subject_seed,
            subject_seed_mode,
            subject_seed_confidence,
            subject_seed_reason,
            manual_decision,
            uploaded_to_mysql,
            mysql_synced_at,
            upload_public_path,
            upload_status,
            source_review_status,
            created_at,
            updated_at
        )
        VALUES (
            NULL,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            'WORKFLOW_QUEUED',
            0,
            'created_from_review_queue',
            'workflow_seed',
            0,
            0,
            'workflow_seed',
            0,
            0,
            0,
            0,
            ?,
            ?,
            ?,
            ?,
            ?,
            'ui_subject',
            NULL,
            'created from main_set review_queue insert',
            'SET_CREATED',
            0,
            NULL,
            NULL,
            NULL,
            ?,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        )
        ON CONFLICT(revamp_File_Name) DO UPDATE SET
            revamp_Original_File_Name=excluded.revamp_Original_File_Name,
            revamp_Location=excluded.revamp_Location,
            revamp_Folder=excluded.revamp_Folder,
            current_caption=excluded.current_caption,
            current_alt_text=excluded.current_alt_text,
            current_keywords=excluded.current_keywords,
            upload_caption=excluded.upload_caption,
            upload_alt_text=excluded.upload_alt_text,
            upload_keywords=excluded.upload_keywords,
            overall_quality_status=excluded.overall_quality_status,
            overall_quality_score=excluded.overall_quality_score,
            overall_quality_issues=excluded.overall_quality_issues,
            generation_mode=excluded.generation_mode,
            repair_attempts=excluded.repair_attempts,
            fallback_used=excluded.fallback_used,
            fallback_reason=excluded.fallback_reason,
            accepted_for_upload=excluded.accepted_for_upload,
            caption_accepted_for_upload=excluded.caption_accepted_for_upload,
            alt_text_accepted_for_upload=excluded.alt_text_accepted_for_upload,
            keywords_accepted_for_upload=excluded.keywords_accepted_for_upload,
            part_of_serie=excluded.part_of_serie,
            unique_name=excluded.unique_name,
            ai_suggested_subject=excluded.ai_suggested_subject,
            final_subject=excluded.final_subject,
            subject_seed=excluded.subject_seed,
            subject_seed_mode=excluded.subject_seed_mode,
            subject_seed_confidence=excluded.subject_seed_confidence,
            subject_seed_reason=excluded.subject_seed_reason,
            manual_decision=excluded.manual_decision,
            source_review_status=excluded.source_review_status,
            updated_at=CURRENT_TIMESTAMP
    """, (
        file_name,
        row.get("Original_File_Name"),
        row.get("Location"),
        row.get("Folder"),
        caption,
        alt_text,
        keywords,
        caption,
        alt_text,
        keywords,
        part_of_serie,
        file_name,
        ai_suggested_subject,
        final_subject,
        subject_seed_for_mq,
        review_status,
    ))

def _safe_router_slug(value: str) -> str:
    value = str(value or "").strip().replace(" ", "_")
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_.-")
    return value or "set"


def _router_clean_text(value) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\u00a0", " ")).strip()


def _router_int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return int(default)


def _router_copy_file(src: str, dst: str) -> None:
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        if os.path.exists(dst):
            os.remove(dst)
    except Exception:
        pass
    try:
        os.link(src, dst)
    except Exception:
        shutil.copy2(src, dst)


def _apply_identifier_router_json_to_db(
    *,
    db_path: str,
    table: str,
    json_path: str,
    allowed_ids: list[int],
) -> tuple[int, int]:
    allowed = {int(x) for x in allowed_ids if int(x) > 0}
    if not allowed:
        return 0, 0

    with open(json_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    rows = payload.get("results") if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        raise RuntimeError("Identifier router JSON does not contain a results list.")

    updated = 0
    missed = 0

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        _ensure_db_table(conn)

        for row in rows:
            if not isinstance(row, dict):
                continue

            image_name = _router_clean_text(row.get("image_name"))
            if not image_name:
                missed += 1
                continue

            marks = ",".join(["?"] * len(allowed))
            found = cur.execute(
                f"""
                SELECT id
                FROM {table}
                WHERE id IN ({marks})
                  AND (File_Name = ? OR Original_File_Name = ?)
                LIMIT 1
                """,
                [*sorted(allowed), image_name, image_name],
            ).fetchone()

            if not found:
                missed += 1
                print(f"[IDENTIFIER-MISS] {image_name}")
                continue

            rid = int(found["id"] if isinstance(found, sqlite3.Row) else found[0])
            route = _router_clean_text(row.get("route"))
            category = _router_clean_text(row.get("category"))
            subject = _router_clean_text(row.get("subject"))
            confidence = _router_int(row.get("confidence"), 0)
            subject_seed = _router_clean_text(row.get("subject_seed"))
            subject_seed_mode = _router_clean_text(row.get("subject_seed_mode"))
            subject_seed_confidence = _router_int(row.get("subject_seed_confidence"), confidence)
            subject_seed_reason = _router_clean_text(row.get("subject_seed_reason"))
            raw_json = json.dumps(row, ensure_ascii=False)

            cur.execute(
                f"""
                UPDATE {table}
                SET
                    identifier_route = ?,
                    identifier_category = ?,
                    identifier_subject = ?,
                    identifier_confidence = ?,
                    subject_seed = ?,
                    subject_seed_mode = ?,
                    subject_seed_confidence = ?,
                    subject_seed_reason = ?,
                    identifier_raw_json = ?
                WHERE id = ?
                """,
                (
                    route,
                    category,
                    subject,
                    confidence,
                    subject_seed,
                    subject_seed_mode,
                    subject_seed_confidence,
                    subject_seed_reason,
                    raw_json,
                    rid,
                ),
            )
            updated += 1
            print(
                f"[IDENTIFIER-DB] id={rid} route={route or '-'} "
                f"seed={subject_seed or '-'} mode={subject_seed_mode or '-'} "
                f"confidence={subject_seed_confidence}"
            )

        conn.commit()

    return updated, missed


def _identifier_router_cleanup_tmp(tmp_dir: str) -> None:
    if not IDENTIFIER_ROUTER_CLEAN_TMP:
        return

    try:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception:
        pass


def _identifier_router_manual_subject_fallback_to_db(
    *,
    db_path: str,
    table: str,
    row_ids: list[int],
    subject_hint: str,
    location_hint: str = "",
    folder_hint: str = "",
    set_index: int = 0,
    reason: str = "",
    only_missing: bool = True,
) -> int:
    ids = sorted({int(x) for x in row_ids if int(x) > 0})
    subject = _router_clean_text(subject_hint)

    if not ids or not subject:
        return 0

    route = "manual_subject_fallback"
    category = _router_clean_text(folder_hint) or "manual_subject"
    confidence = 72
    subject_seed_reason = _router_clean_text(reason) or "Identifier router unavailable; kept user subject."
    raw_json = json.dumps(
        {
            "route": route,
            "category": category,
            "subject": subject,
            "confidence": confidence,
            "subject_seed": subject,
            "subject_seed_mode": "user_subject_override",
            "subject_seed_confidence": confidence,
            "subject_seed_reason": subject_seed_reason,
            "location_hint": _router_clean_text(location_hint),
            "folder_hint": _router_clean_text(folder_hint),
            "set_index": int(set_index or 0),
        },
        ensure_ascii=False,
    )

    marks = ",".join(["?"] * len(ids))
    missing_clause = ""

    if only_missing:
        missing_clause = """
          AND (
                subject_seed IS NULL OR TRIM(subject_seed) = ''
             OR identifier_subject IS NULL OR TRIM(identifier_subject) = ''
          )
        """

    with sqlite3.connect(db_path) as conn:
        _ensure_db_table(conn)
        cur = conn.cursor()
        cur.execute(
            f"""
            UPDATE {table}
            SET
                identifier_route = ?,
                identifier_category = ?,
                identifier_subject = ?,
                identifier_confidence = ?,
                subject_seed = ?,
                subject_seed_mode = ?,
                subject_seed_confidence = ?,
                subject_seed_reason = ?,
                identifier_raw_json = ?
            WHERE id IN ({marks})
            {missing_clause}
            """,
            (
                route,
                category,
                subject,
                confidence,
                subject,
                "user_subject_override",
                confidence,
                subject_seed_reason,
                raw_json,
                *ids,
            ),
        )
        updated = int(cur.rowcount or 0)
        conn.commit()

    if updated:
        print(
            f"[IDENTIFIER-FALLBACK] set={set_index} rows={updated} "
            f"kept user subject='{subject}' reason={subject_seed_reason}"
        )

    return updated


def _run_identifier_router_for_review_rows(
    *,
    db_path: str,
    table: str,
    row_ids: list[int],
    subject_hint: str,
    location_hint: str,
    folder_hint: str,
    set_index: int,
    python_path: str,
) -> tuple[int, int]:
    ids = sorted({int(x) for x in row_ids if int(x) > 0})
    if not IDENTIFIER_ROUTER_ENABLED or not ids:
        return 0, 0

    router_script = _prepare_external_script(os.path.join("scripts", "identifier_router.py"))
    if not router_script or not os.path.exists(router_script):
        msg = f"Identifier router script not found: {router_script}"
        if IDENTIFIER_ROUTER_FAIL_HARD:
            raise RuntimeError(msg)
        print(f"[WARN] {msg}")
        updated = _identifier_router_manual_subject_fallback_to_db(
            db_path=db_path,
            table=table,
            row_ids=ids,
            subject_hint=subject_hint,
            location_hint=location_hint,
            folder_hint=folder_hint,
            set_index=set_index,
            reason=msg,
            only_missing=True,
        )
        return updated, max(0, len(ids) - updated)

    stamp = time.strftime("%Y%m%d_%H%M%S")
    safe_folder = _safe_router_slug(folder_hint)
    tmp_dir = os.path.join(IDENTIFIER_ROUTER_TMP_DIR, f"{safe_folder}_set_{set_index}_{stamp}")
    os.makedirs(tmp_dir, exist_ok=True)

    copied = 0
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        marks = ",".join(["?"] * len(ids))
        rows = conn.execute(
            f"""
            SELECT id, Path, File_Name, Original_File_Name
            FROM {table}
            WHERE id IN ({marks})
            ORDER BY id
            """,
            ids,
        ).fetchall()

    for row in rows:
        src = str(row["Path"] or "").strip()
        if not src or not os.path.exists(src):
            print(f"[IDENTIFIER-WARN] id={row['id']} source missing: {src or '(empty)'}")
            continue

        original_name = str(row["Original_File_Name"] or "").strip()
        image_name = original_name or os.path.basename(src) or str(row["File_Name"] or "").strip()
        if not image_name:
            print(f"[IDENTIFIER-WARN] id={row['id']} no usable filename")
            continue

        dst = os.path.join(tmp_dir, os.path.basename(image_name))
        try:
            _router_copy_file(src, dst)
            copied += 1
        except Exception as ex:
            print(f"[IDENTIFIER-WARN] id={row['id']} copy failed: {type(ex).__name__}: {ex}")

    if copied <= 0:
        msg = "Identifier router had no readable input images."
        if IDENTIFIER_ROUTER_FAIL_HARD:
            raise RuntimeError(msg)
        print(f"[WARN] {msg}")
        _identifier_router_cleanup_tmp(tmp_dir)
        updated = _identifier_router_manual_subject_fallback_to_db(
            db_path=db_path,
            table=table,
            row_ids=ids,
            subject_hint=subject_hint,
            location_hint=location_hint,
            folder_hint=folder_hint,
            set_index=set_index,
            reason=msg,
            only_missing=True,
        )
        return updated, max(0, len(ids) - updated)

    json_out = os.path.join(DATA_DIR, f"identifier_router_last_set_{int(set_index)}.json")
    cmd = [
        python_path or sys.executable,
        "-u",
        router_script,
        "--folder",
        tmp_dir,
        "--subject-hint",
        str(subject_hint or ""),
        "--location",
        str(location_hint or ""),
        "--max-samples",
        str(IDENTIFIER_ROUTER_MAX_SAMPLES),
        "--max-crops",
        str(IDENTIFIER_ROUTER_MAX_CROPS),
        "--ollama-model",
        IDENTIFIER_ROUTER_MODEL,
        "--fast-image-max-side",
        str(IDENTIFIER_ROUTER_FAST_IMAGE_MAX_SIDE),
        "--json-out",
        json_out,
    ]

    print(
        f"[IDENTIFIER] set={set_index} rows={len(ids)} copied={copied} "
        f"folder={folder_hint} subject_hint={subject_hint}"
    )
    res = subprocess.run(
        cmd,
        cwd=_child_cwd_for_identifier_script(router_script),
        text=True,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )

    if res.returncode != 0:
        msg = f"Identifier router failed for set {set_index} with rc={res.returncode}"
        if IDENTIFIER_ROUTER_FAIL_HARD:
            raise RuntimeError(msg)
        print(f"[WARN] {msg}")
        _identifier_router_cleanup_tmp(tmp_dir)
        updated = _identifier_router_manual_subject_fallback_to_db(
            db_path=db_path,
            table=table,
            row_ids=ids,
            subject_hint=subject_hint,
            location_hint=location_hint,
            folder_hint=folder_hint,
            set_index=set_index,
            reason=msg,
            only_missing=True,
        )
        return updated, max(0, len(ids) - updated)

    if not os.path.exists(json_out):
        msg = f"Identifier router did not create JSON: {json_out}"
        if IDENTIFIER_ROUTER_FAIL_HARD:
            raise RuntimeError(msg)
        print(f"[WARN] {msg}")
        _identifier_router_cleanup_tmp(tmp_dir)
        updated = _identifier_router_manual_subject_fallback_to_db(
            db_path=db_path,
            table=table,
            row_ids=ids,
            subject_hint=subject_hint,
            location_hint=location_hint,
            folder_hint=folder_hint,
            set_index=set_index,
            reason=msg,
            only_missing=True,
        )
        return updated, max(0, len(ids) - updated)

    updated, missed = _apply_identifier_router_json_to_db(
        db_path=db_path,
        table=table,
        json_path=json_out,
        allowed_ids=ids,
    )
    print(f"[IDENTIFIER] DB updated={updated} missed={missed} json={json_out}")

    if missed or updated < len(ids):
        fallback_updated = _identifier_router_manual_subject_fallback_to_db(
            db_path=db_path,
            table=table,
            row_ids=ids,
            subject_hint=subject_hint,
            location_hint=location_hint,
            folder_hint=folder_hint,
            set_index=set_index,
            reason="Identifier router missed one or more rows; kept user subject for missing rows.",
            only_missing=True,
        )
        if fallback_updated:
            updated += fallback_updated
            missed = max(0, len(ids) - updated)

    _identifier_router_cleanup_tmp(tmp_dir)

    return updated, missed


def _child_cwd_for_identifier_script(script_path: str) -> str:
    # Router imports helper modules through the scripts package.
    # Source mode: cwd can be project root. Runtime copy: cwd is runtime root.
    parent = os.path.dirname(os.path.abspath(script_path))
    if os.path.basename(parent).lower() == "scripts":
        return os.path.dirname(parent)
    return APP_DIR


# ---------- EXIF helpers ----------
def _as_float(x):
    try:
        if hasattr(x, "numerator") and hasattr(x, "denominator"):
            d = x.denominator or 1
            return float(x.numerator) / float(d)
        if isinstance(x, tuple) and len(x) == 2:
            return float(x[0]) / (x[1] or 1)
        return float(x)
    except Exception:
        return None


def _fmt_exposure(x) -> str | None:
    """
    Format exposure time nicely:
    - tuple/Fraction like (1,250) -> "1/250 sec"
    - (20,1) or 20.0 -> "20 sec"
    - 0.8 -> "0.8 sec"
    Avoids "20.000 sec" and avoids "1/1 sec".
    """
    try:
        if x is None:
            return None

        # Handle rational-like values first (best fidelity)
        if hasattr(x, "numerator") and hasattr(x, "denominator"):
            num = int(x.numerator)
            den = int(x.denominator or 1)
        elif isinstance(x, tuple) and len(x) == 2:
            num = int(x[0])
            den = int(x[1] or 1)
        else:
            # fallback float
            fr = _as_float(x)
            if not fr or fr <= 0:
                return None

            if fr >= 1:
                r = round(fr)
                if abs(fr - r) < 0.01:
                    return f"{int(r)} sec"
                s = f"{fr:.3f}".rstrip("0").rstrip(".")
                return f"{s} sec"

            # fr < 1
            inv = round(1 / fr)
            if inv >= 1:
                approx = 1 / inv
                if abs(fr - approx) / fr < 0.02:
                    return f"1/{inv} sec"
            s = f"{fr:.4f}".rstrip("0").rstrip(".")
            return f"{s} sec"

        # Now format from (num, den)
        if den == 0 or num == 0:
            return None

        sec = num / den

        if sec >= 1:
            r = round(sec)
            if abs(sec - r) < 0.01:
                return f"{int(r)} sec"
            s = f"{sec:.3f}".rstrip("0").rstrip(".")
            return f"{s} sec"

        # Below 1 sec: reduce fraction a bit for readability
        try:
            import math

            g = math.gcd(num, den)
            num //= g
            den //= g
        except Exception:
            pass

        if num == 1:
            return f"1/{den} sec"
        return f"{num}/{den} sec"

    except Exception:
        # never crash the pipeline over formatting
        fr = _as_float(x)
        if fr and fr > 0:
            s = f"{fr:.3f}".rstrip("0").rstrip(".")
            return f"{s} sec"
        return None


_EXIF_CRITICAL_KEYS = (
    "LensModel",
    "LensModelName",
    "ExifImageWidth",
    "ExifImageHeight",
    "ExposureTime",
    "FNumber",
    "ISOSpeedRatings",
    "PhotographicSensitivity",
    "FocalLength",
)


def _merge_exif_with_pil_fallback(image_path: str, exif_seed: dict | None) -> dict:
    """
    Merge EXIF from multiple PIL paths.
    Some files expose only top-level tags via getexif(); _getexif() may contain
    the ExifIFD payload (lens/iso/focal/size). This keeps ingest resilient.
    """
    exif: dict = dict(exif_seed or {})
    if not image_path or not os.path.exists(image_path):
        return exif

    needs_fallback = any(not exif.get(k) for k in _EXIF_CRITICAL_KEYS)
    if not needs_fallback:
        return exif

    try:
        from PIL.ExifTags import TAGS

        with Image.open(image_path) as img:
            raw_streams = []
            try:
                raw_streams.append(getattr(img, "_getexif", lambda: None)())
            except Exception:
                pass
            try:
                raw_streams.append(img.getexif())
            except Exception:
                pass

            for raw in raw_streams:
                if not raw:
                    continue
                try:
                    items = raw.items() if hasattr(raw, "items") else raw
                    for tag_id, value in items:
                        tag = TAGS.get(tag_id, tag_id)
                        if exif.get(tag) in (None, ""):
                            exif[tag] = value
                except Exception:
                    continue
    except Exception as ex:
        print(f"[WARN] EXIF fallback parse failed for {image_path}: {ex}")

    return exif


def _append_runtime_crash(kind: str, exc_type, exc_value, exc_tb):
    """Best-effort append-only crash log for runtime callback/thread failures."""
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(RUNTIME_CRASH_LOG, "a", encoding="utf-8", errors="replace") as f:
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            en = getattr(exc_type, "__name__", str(exc_type))
            f.write(f"\n[{ts}] kind={kind} error={en}: {exc_value}\n")
            f.write("".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
            f.write("\n")
    except Exception:
        pass


# BEGIN AMIR2000 PRODUCTION SUBJECT IDENTIFIER
# Production identifier bridge.
# It sends selected image paths plus UI hints: subject text, location, folder/category.
try:
    from scripts.subject_identifier_production import suggest_subject_multi as _amir2000_subject_identifier
except Exception as _amir2000_identifier_import_error:
    _amir2000_subject_identifier = None
    _amir2000_identifier_import_message = str(_amir2000_identifier_import_error)
else:
    _amir2000_identifier_import_message = ""


def _amir2000_get_hint_from_gui_stack(kind: str) -> str:
    """Best-effort Tk hint reader without binding to one widget name."""
    import inspect

    method_names = {
        "subject": ["_subject_get", "get_subject"],
        "location": ["_location_get", "get_location"],
        "folder": ["_folder_get", "get_folder"],
    }.get(kind, [])

    attr_names = {
        "subject": ["subject_var", "var_subject", "subject_value", "subject_entry", "subject"],
        "location": ["location_var", "var_location", "location_value", "location_entry", "location_combo", "location"],
        "folder": ["folder_var", "folder_combo", "folder_value", "category_var", "category_combo", "folder"],
    }.get(kind, [])

    frame = inspect.currentframe()

    try:
        while frame is not None:
            obj = frame.f_locals.get("self")

            if obj is not None:
                for name in method_names:
                    method = getattr(obj, name, None)

                    if callable(method):
                        try:
                            value = str(method() or "").strip()

                            if value:
                                return value
                        except Exception:
                            pass

                for name in attr_names:
                    attr = getattr(obj, name, None)

                    if attr is None:
                        continue

                    try:
                        if hasattr(attr, "get"):
                            value = str(attr.get() or "").strip()
                        else:
                            value = str(attr or "").strip()

                        if value:
                            return value
                    except Exception:
                        pass

            frame = frame.f_back
    finally:
        del frame

    return ""


if _amir2000_subject_identifier is not None:
    _legacy_ai_suggest_subject_multi = ai_suggest_subject_multi

    def ai_suggest_subject_multi(image_paths: list[str]) -> str | None:
        """Production subject identifier wrapper with UI context hints."""
        global _LAST_OLLAMA_ERROR

        subject_hint = _amir2000_get_hint_from_gui_stack("subject")
        location_hint = _amir2000_get_hint_from_gui_stack("location")
        folder_hint = _amir2000_get_hint_from_gui_stack("folder")

        if os.getenv("AMIR_SUBJECT_IGNORE_SUBJECT_HINT", "").strip() == "1":
            subject_hint = ""

        try:
            result = _amir2000_subject_identifier(
                image_paths or [],
                location_hint=location_hint,
                folder_hint=folder_hint,
                subject_hint=subject_hint,
            )
        except Exception as e:
            # Do not fall back to the old subject suggester.
            # The old path can still fill generic poison like Bird, Waterfowl,
            # Natural Landscape, or Latin-only guesses.
            _LAST_OLLAMA_ERROR = f"Production subject identifier failed: {type(e).__name__}: {e}"
            return None

        _LAST_OLLAMA_ERROR = (getattr(result, "error", "") or "").strip()
        subject = (getattr(result, "subject", "") or "").strip()

        if subject:
            return subject

        return None
# END AMIR2000 PRODUCTION SUBJECT IDENTIFIER

# AMIR_SUBJECT_TEMP_RESIZE_REUSE_START
# Prepare Ollama resized temp images before AI subject identification.
# The same files are reused later through review_queue.ollama_path.
# Scoring still uses the original Path.

def _amir_norm_temp_source_path(value: object) -> str:
    try:
        return os.path.normcase(os.path.abspath(str(value or "")))
    except Exception:
        return str(value or "").strip().lower()


def _amir_prepare_ollama_temp_images_for_subject(image_paths: list[str], label: str = "subject") -> dict[str, str]:
    from PIL import ImageOps

    out: dict[str, str] = {}

    if not image_paths:
        return out

    max_side = int(os.getenv("AMIR_SUBJECT_TEMP_MAX_SIDE", "1280"))
    jpeg_quality = int(os.getenv("AMIR_SUBJECT_TEMP_JPEG_QUALITY", "88"))

    ts = time.strftime("%Y%m%d_%H%M%S")
    safe_label = re.sub(r"[^A-Za-z0-9_]+", "_", str(label or "subject")).strip("_") or "subject"
    temp_root = os.path.join(DATA_DIR, "ollama_tmp", f"run_{safe_label}_{ts}")
    os.makedirs(temp_root, exist_ok=True)

    for index, src in enumerate(image_paths, start=1):
        src = str(src or "").strip()

        if not src or not os.path.exists(src):
            print(f"[SUBJECT PREP] missing source: {src or '(empty)'}")
            continue

        try:
            base = os.path.basename(src)
            stem, _ext = os.path.splitext(base)
            safe_stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("_") or f"image_{index:03d}"
            dst = os.path.join(temp_root, f"{index:03d}_{safe_stem}.jpg")

            with Image.open(src) as raw_img:
                img = ImageOps.exif_transpose(raw_img).convert("RGB")

            img.thumbnail((max_side, max_side), Image.LANCZOS)
            img.save(dst, format="JPEG", quality=jpeg_quality, optimize=False)

            out[_amir_norm_temp_source_path(src)] = dst
            print(f"[SUBJECT PREP] resized {base} -> {dst}")

        except Exception as exc:
            print(f"[SUBJECT PREP] failed {os.path.basename(src)}: {type(exc).__name__}: {exc}")

    return out
# AMIR_SUBJECT_TEMP_RESIZE_REUSE_END

# ---------- UI ----------
class MultiSetApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Amir2000 Image Automation V.1.0 — Multi-Set")
        try:
            sw = int(self.root.winfo_screenwidth() or 0)
            sh = int(self.root.winfo_screenheight() or 0)
            w = min(max(980, int(sw * 0.78)), 1500) if sw > 0 else 1180
            h = min(max(620, int(sh * 0.72)), 980) if sh > 0 else 740
            self.root.geometry(f"{w}x{h}")
            self.root.minsize(980, 620)
            self.root.resizable(True, True)
        except Exception:
            pass
        self.batches: list[dict] = (
            []
        )  # each: {subject, location, folder, files: [paths]}
        self._pending_files: list[str] = (
            []
        )  # remembers last file pick until set is added
        self._stage_origin: dict[str, str] = {}  # staged_path_norm -> original_path
        self._async_pipeline = (
            False  # prevents finally{} from re-opening editor when running async
        )

        self._ui_disabled = False
        self._ai_subject_busy = False
        self._ai_subject_paths_sig: set[str] = set()
        self._last_ai_suggested_subject = ""
        self._last_ai_subject_paths_sig: set[str] = set()
        self._subject_internal_edit = False
        self._subject_spell_after_id = None
        self._location_spell_after_id = None
        self._subject_last_spell_text = None
        self._location_last_spell_text = None

        try:
            # Capture Tk callback exceptions in a stable file instead of silent exits.
            self.root.report_callback_exception = self._tk_callback_exception
        except Exception:
            pass


        # run log
        self._build_stamp = self._get_build_stamp()
        self._runlog(
            "START",
            f"frozen={getattr(sys,'frozen',False)} exe={sys.executable} py={sys.version.split()[0]}",
        )

        # spellcheck tooltip (used for Location underline hover)

        self._spell_tip = None
        self._spell_tip_label = None
        self._spell_tip_word = None

        # Location autocomplete dropdown (Text widget)
        self._loc_ac_top = None
        self._loc_ac_list = None

        # Top form — per-set fields
        self.subject_var = tk.StringVar()
        self.location_var = tk.StringVar()
        self.folder_var = tk.StringVar()

        # Bottom status + progress (used by _set_stage)
        self.status_var = tk.StringVar(value="Ready")
        self.progress_var = tk.IntVar(value=0)

        # make sure spell exceptions file exists so "Keep term" works
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            ex_path = os.path.join(DATA_DIR, "spellcheck_exceptions.json")
            if not os.path.exists(ex_path):
                with open(ex_path, "w", encoding="utf-8") as f:
                    json.dump([], f, ensure_ascii=False, indent=2)
        except Exception:
            pass

        frm = ttk.Frame(root, padding=12)
        frm.grid(row=0, column=0, sticky="nsew")
        ttk.Label(frm, text="Subject:").grid(row=0, column=0, sticky="w")
        self.subject_txt = tk.Text(frm, height=1, width=46, wrap="none", undo=True)
        self.subject_txt.grid(row=0, column=1, sticky="ew")
        self.subject_txt.insert("1.0", self.subject_var.get() or "")

        # red underline tag
        self.subject_txt.tag_configure("misspell", underline=1, foreground="red")

        # block new lines
        self.subject_txt.bind("<Return>", lambda e: "break")

        # live underline + right click menu + hover tooltip
        self.subject_txt.bind("<KeyRelease>", self._on_subject_keyrelease, add="+")
        self.subject_txt.bind(
            "<Button-3>",
            lambda e: getattr(self, "_subject_context_menu", lambda _e: None)(e),
            add="+",
        )
        self.subject_txt.bind("<Motion>", self._on_subject_hover, add="+")
        self.subject_txt.bind("<Leave>", lambda e: self._spell_tip_hide(), add="+")

        ttk.Label(frm, text="Location:").grid(row=1, column=0, sticky="w")
        loc_opts = self._load_json_any(LOCATION_FILE) or []
        self.location_all = tuple(sorted(loc_opts or []))

        loc_row = ttk.Frame(frm)
        loc_row.grid(row=1, column=1, sticky="ew")

        self.location_txt = tk.Text(loc_row, height=1, width=46, wrap="none", undo=True)
        self.location_txt.grid(row=0, column=0, sticky="ew")
        self.location_txt.insert("1.0", self.location_var.get() or "")

        # red underline tag
        self.location_txt.tag_configure("misspell", underline=1, foreground="red")

        # block new lines and support autocomplete selection
        self.location_txt.bind("<Return>", self._on_location_return, add="+")
        self.location_txt.bind("<Tab>", self._on_location_tab, add="+")
        self.location_txt.bind("<Down>", self._on_location_down, add="+")
        self.location_txt.bind("<Up>", self._on_location_up, add="+")
        self.location_txt.bind("<MouseWheel>", self._on_location_mousewheel, add="+")
        self.location_txt.bind("<Button-4>", self._on_location_mousewheel, add="+")
        self.location_txt.bind("<Button-5>", self._on_location_mousewheel, add="+")
        self.location_txt.bind("<Escape>", self._on_location_escape, add="+")
        self.location_txt.bind("<FocusOut>", lambda e: self._loc_ac_hide(), add="+")

        # live underline + right click menu + hover tooltip + autocomplete
        self.location_txt.bind("<KeyRelease>", self._on_location_keyrelease, add="+")
        self.location_txt.bind("<Button-3>", self._location_context_menu, add="+")
        self.location_txt.bind("<Motion>", self._on_location_hover, add="+")
        self.location_txt.bind(
            "<Leave>", lambda e: (self._spell_tip_hide(), self._loc_ac_hide()), add="+"
        )

        ttk.Button(loc_row, text="▼", width=2, command=self._location_pick_menu).grid(
            row=0, column=1, padx=(6, 0)
        )

        loc_row.columnconfigure(0, weight=1)

        ttk.Label(frm, text="Folder (category):").grid(row=2, column=0, sticky="w")
        fm = self._load_json_any(FOLDER_MAP_FILE) or {}
        self.folder_map = fm if isinstance(fm, dict) else {}
        self.folder_all = (
            tuple(sorted(self.folder_map.values())) if self.folder_map else tuple()
        )
        self.folder_cb = ttk.Combobox(
            frm, textvariable=self.folder_var, width=46, values=self.folder_all
        )
        self._attach_autocomplete(self.folder_cb)
        self.folder_cb.grid(row=2, column=1, sticky="ew")

        # Buttons row
        btns = ttk.Frame(frm)
        btns.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 4))
        ttk.Button(
            btns, text="Import set from folder…", command=self._import_set_from_folder
        ).pack(side="left", padx=(0, 8))
        ttk.Button(btns, text="Select images…", command=self._add_set_from_files).pack(
            side="left", padx=(0, 8)
        )
        self.ai_subject_btn = ttk.Button(
            btns,
            text="AI suggest subject",
            command=lambda: self._ai_suggest_subject_for_current(regenerate=False),
        )
        self.ai_subject_btn.pack(side="left")
        # AMIR_REGENERATE_SUBJECT_BUTTON_START
        self.ai_subject_regen_btn = ttk.Button(
            btns,
            text="Regenerate subject",
            command=lambda: self._ai_suggest_subject_for_current(regenerate=True),
        )
        self.ai_subject_regen_btn.pack(side="left", padx=(8, 0))
        # AMIR_REGENERATE_SUBJECT_BUTTON_END
        self.ai_subject_identify_btn = ttk.Button(
            btns,
            text="Identify",
            command=lambda: self._ai_suggest_subject_for_current(identify=True),
        )
        self.ai_subject_identify_btn.pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="Add set", command=self._add_current_set).pack(
            side="left", padx=(28, 0)
        )
        self.spell_warn_lbl = ttk.Label(btns, text="", foreground="#c08000")
        self.spell_warn_lbl.pack(side="left", padx=(6, 0))
        self._refresh_spellcheck_status()

        # Sets table
        tree_wrap = ttk.Frame(frm)
        tree_wrap.grid(row=4, column=0, columnspan=2, sticky="nsew", pady=(8, 4))
        self.tree = ttk.Treeview(
            tree_wrap,
            columns=("count", "subject", "location", "folder"),
            show="headings",
            height=14,
        )
        for c, w in (
            ("count", "#"),
            ("subject", "Subject"),
            ("location", "Location"),
            ("folder", "Folder"),
        ):
            self.tree.heading(c, text=w)
        self.tree.column("count", width=50, anchor="center", stretch=False)
        self.tree.column("subject", width=420, stretch=True)
        self.tree.column("location", width=260, stretch=True)
        self.tree.column("folder", width=280, stretch=True)
        self.tree.grid(row=0, column=0, sticky="nsew")
        tree_vsb = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.tree.yview)
        tree_hsb = ttk.Scrollbar(
            tree_wrap, orient="horizontal", command=self.tree.xview
        )
        self.tree.configure(yscrollcommand=tree_vsb.set, xscrollcommand=tree_hsb.set)
        tree_vsb.grid(row=0, column=1, sticky="ns")
        tree_hsb.grid(row=1, column=0, sticky="ew")
        tree_wrap.columnconfigure(0, weight=1)
        tree_wrap.rowconfigure(0, weight=1)
        self.tree.bind("<Double-1>", lambda e: self._edit_selected_set())

        delrow = ttk.Frame(frm)
        delrow.grid(row=5, column=0, columnspan=2, sticky="w")
        ttk.Button(delrow, text="Edit set…", command=self._edit_selected_set).pack(
            side="left"
        )
        ttk.Button(delrow, text="Remove set", command=self._remove_selected_set).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(delrow, text="Clear all", command=self._clear_sets).pack(
            side="left", padx=8
        )
        self.recover_btn = ttk.Button(
            delrow, text="Recover crash session", command=self._recover_session_button
        )
        self.recover_btn.pack(side="left", padx=(8, 0))

        # Progress
        self.progress = ttk.Progressbar(
            frm,
            orient="horizontal",
            length=420,
            mode="determinate",
            maximum=100,
            variable=self.progress_var,
        )
        self.progress.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(8, 6))
        self.stage_lbl = ttk.Label(frm, textvariable=self.status_var)
        self.stage_lbl.grid(row=7, column=0, columnspan=2, sticky="w")

        self.start_btn = ttk.Button(frm, text="Start Batch", command=self.proceed)
        self.start_btn.grid(row=8, column=0, columnspan=2, pady=(10, 2))

        frm.rowconfigure(4, weight=1)
        frm.columnconfigure(1, weight=1)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)

        self._folder_key_by_value = (
            {v: k for k, v in self.folder_map.items()} if self.folder_map else {}
        )

        recovered_sets, recovered_pending = self._restore_session_state()
        if recovered_sets or recovered_pending:
            self._runlog(
                "SESSION_RECOVER_AUTO",
                f"sets={recovered_sets} pending={recovered_pending} file={os.path.basename(MULTISET_SESSION_FILE)}",
            )
        self._update_ready_status()

    def proceed(self):
        # Quick UI-thread validation only
        if not self.batches:
            messagebox.showwarning("No sets", "Add at least one set.")
            return

        # prevent double clicks
        try:
            self.start_btn.configure(state="disabled")
        except Exception:
            pass

        self._pipeline_t0 = None
        self._last_stage_ts = None
        self._stage_times = {}
        self._current_stage_idx = None

        self._save_session_state()
        t = threading.Thread(target=self._run_pipeline, daemon=True)
        t.start()



    # ---------- small helpers ----------
    @staticmethod
    def _load_json_any(path: str):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def _append_json_list(self, path: str, item: dict):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            data = []
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            if not isinstance(data, list):
                data = []
            data.append(item)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _save_session_state(self):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            payload = {
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "batches": list(self.batches or []),
                "pending_files": list(self._pending_files or []),
                "stage_origin": dict(self._stage_origin or {}),
                "form": {
                    "subject": self._subject_get(),
                    "location": self._location_get(),
                    "folder_h": (self.folder_var.get() or "").strip(),
                },
            }
            tmp = MULTISET_SESSION_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp, MULTISET_SESSION_FILE)
        except Exception:
            pass

    def _clear_session_state(self):
        try:
            if os.path.exists(MULTISET_SESSION_FILE):
                os.remove(MULTISET_SESSION_FILE)
        except Exception:
            pass

    def _latest_session_backup(self) -> str | None:
        try:
            pattern = os.path.join(DATA_DIR, "multiset_session.backup_*.json")
            backups = sorted(glob.glob(pattern), reverse=True)
            return backups[0] if backups else None
        except Exception:
            return None

    def _recover_session_button(self):
        try:
            session_path = MULTISET_SESSION_FILE
            if not os.path.exists(session_path):
                session_path = self._latest_session_backup() or ""

            if not session_path or not os.path.exists(session_path):
                messagebox.showwarning(
                    "Recover session",
                    "No recovery snapshot was found.\n\n"
                    f"Expected:\n{MULTISET_SESSION_FILE}",
                )
                return

            current_sets = len(self.batches)
            current_pending = len(self._pending_files)
            if current_sets or current_pending:
                ok = messagebox.askyesno(
                    "Recover session",
                    "Replace current queue with the saved recovery session?\n\n"
                    f"Current queue: {current_sets} set(s), {current_pending} pending file(s).",
                )
                if not ok:
                    return

            recovered_sets, recovered_pending = self._restore_session_state(
                session_path=session_path, show_dialog=False
            )
            self._update_ready_status()

            if recovered_sets or recovered_pending:
                self._runlog(
                    "SESSION_RECOVER_MANUAL",
                    f"sets={recovered_sets} pending={recovered_pending} file={os.path.basename(session_path)}",
                )
                messagebox.showinfo(
                    "Session recovered",
                    f"Recovered {recovered_sets} set(s) and {recovered_pending} pending file(s)\n"
                    f"from:\n{session_path}",
                )
            else:
                messagebox.showwarning(
                    "Recover session",
                    "Recovery file was found, but no valid files were found on disk.\n\n"
                    f"{session_path}",
                )
        except Exception as ex:
            messagebox.showerror(
                "Recover session failed", f"{type(ex).__name__}: {ex}"
            )

    def _restore_session_state(
        self, session_path: str = MULTISET_SESSION_FILE, show_dialog: bool = True
    ) -> tuple[int, int]:
        try:
            if not session_path or not os.path.exists(session_path):
                return 0, 0
            data = self._load_json_any(session_path)
            if not isinstance(data, dict):
                return 0, 0

            restored_stage_origin = {}
            for k, v in (data.get("stage_origin") or {}).items():
                if not k or not v:
                    continue
                restored_stage_origin[str(k)] = str(v)

            stage_for_origin: dict[str, str] = {}
            for staged_p, original_p in restored_stage_origin.items():
                try:
                    stage_for_origin[self._norm_path(str(original_p))] = str(staged_p)
                except Exception:
                    pass

            staged_norm = self._norm_path(STAGED_DIR)
            incoming_norm = self._norm_path(INCOMING_DIR)

            def _resolve_session_file(saved_path: str) -> str | None:
                p = str(saved_path or "").strip()
                if not p:
                    return None
                if os.path.exists(p):
                    return p

                base = os.path.basename(p)
                if not base:
                    return None

                candidates: list[str] = []
                pnorm = self._norm_path(p)
                pdir_norm = self._norm_path(os.path.dirname(p))

                # If this was an original source path, try its known staged path first.
                staged_from_origin = stage_for_origin.get(pnorm)
                if staged_from_origin:
                    candidates.append(staged_from_origin)

                if pdir_norm == staged_norm:
                    candidates.append(os.path.join(STAGED_DIR, base))
                    candidates.append(os.path.join(INCOMING_DIR, base))
                elif pdir_norm == incoming_norm:
                    candidates.append(os.path.join(INCOMING_DIR, base))
                    candidates.append(os.path.join(STAGED_DIR, base))
                else:
                    # Unknown source: support both crash points.
                    candidates.append(os.path.join(STAGED_DIR, base))
                    candidates.append(os.path.join(INCOMING_DIR, base))

                seen: set[str] = set()
                for cand in candidates:
                    if not cand:
                        continue
                    key = self._norm_path(cand)
                    if key in seen:
                        continue
                    seen.add(key)
                    if os.path.exists(cand):
                        return cand
                return None

            restored_batches: list[dict] = []
            for row in (data.get("batches") or []):
                if not isinstance(row, dict):
                    continue
                subject = clean_token((row.get("subject") or "").strip())
                location = clean_token((row.get("location") or "").strip())
                folder = clean_token((row.get("folder") or "").strip())
                folder_h = (row.get("folder_h") or "").strip()
                files: list[str] = []
                for p in (row.get("files") or []):
                    rp = _resolve_session_file(str(p))
                    if rp:
                        files.append(rp)
                if not subject or not location or not folder or not files:
                    continue
                if not folder_h:
                    folder_h = self.folder_map.get(folder) or folder
                restored_batches.append(
                    {
                        "subject": subject,
                        "location": location,
                        "folder": folder,
                        "folder_h": folder_h,
                        "files": files,
                    }
                )

            restored_pending: list[str] = []
            for p in (data.get("pending_files") or []):
                rp = _resolve_session_file(str(p))
                if rp:
                    restored_pending.append(rp)

            if not (restored_batches or restored_pending):
                return 0, 0

            form = data.get("form") or {}
            if isinstance(form, dict):
                self._subject_set((form.get("subject") or "").strip())
                self._location_set((form.get("location") or "").strip())
                self.folder_var.set((form.get("folder_h") or "").strip())

            self.batches = restored_batches
            self._stage_origin = restored_stage_origin
            self._pending_files = restored_pending
            self._refresh_tree()

            if show_dialog:
                messagebox.showinfo(
                    "Session recovered",
                    f"Recovered {len(restored_batches)} set(s) and {len(restored_pending)} pending file(s) "
                    "from previous session.",
                )
            return len(restored_batches), len(restored_pending)
        except Exception:
            return 0, 0

    def _get_build_stamp(self) -> str:
        try:
            if getattr(sys, "frozen", False):
                p = sys.executable
            else:
                p = os.path.abspath(__file__)
            ts = os.path.getmtime(p)
            return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
        except Exception:
            return "unknown"

    def _runlog(self, event: str, msg: str = ""):
        # Append-only log. Must never crash workflow.
        try:
            os.makedirs(DATA_DIR, exist_ok=True)

            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            build = getattr(self, "_build_stamp", None) or "unknown"

            m = (msg or "").replace("\r", " ").replace("\n", " ").strip()
            line = f"{ts}\tbuild={build}\t{event}\t{m}\n"

            with open(RUN_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            pass

    def _tk_callback_exception(self, exc, val, tb):
        """Tk callback crash handler: log + keep app alive with actionable message."""
        _append_runtime_crash("tk_callback", exc, val, tb)
        try:
            self._runlog(
                "TK_CALLBACK_EXCEPTION",
                f"{getattr(exc, '__name__', str(exc))}: {val}",
            )
        except Exception:
            pass
        try:
            messagebox.showerror(
                "Unexpected UI error",
                "An unexpected UI error occurred.\n\n"
                "Your session is still preserved.\n"
                f"Crash log:\n{RUNTIME_CRASH_LOG}",
            )
        except Exception:
            pass

    def _ui_ask_retry_cancel(self, title: str, message: str) -> bool:
        try:
            if not self.root.winfo_exists():
                return False
        except Exception:
            return False

        ev = threading.Event()
        out = {"retry": False}

        def _ask():
            try:
                out["retry"] = bool(messagebox.askretrycancel(title, message))
            except Exception:
                out["retry"] = False
            finally:
                ev.set()

        self._ui(_ask)
        ev.wait()
        return bool(out["retry"])

    def _ui_showerror_wait(self, title: str, message: str):
        try:
            if not self.root.winfo_exists():
                return
        except Exception:
            return

        ev = threading.Event()

        def _show():
            try:
                messagebox.showerror(title, message)
            except Exception:
                pass
            finally:
                ev.set()

        self._ui(_show)
        ev.wait()

    def _log_new_taxonomy(self, kind: str, value_display: str, value_key: str = ""):
        self._append_json_list(
            NEW_TAXONOMY_LOG,
            {
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "kind": kind,
                "display": value_display,
                "key": value_key,
            },
        )
        self._runlog(
            "WARN_NEW_TAXONOMY", f"kind={kind} display={value_display} key={value_key}"
        )

    def _norm_path(self, p: str) -> str:
        return os.path.normcase(os.path.abspath(p or ""))

    def _unique_dst(self, dst_path: str) -> str:
        root, ext = os.path.splitext(dst_path)
        out = dst_path
        n = 1
        while os.path.exists(out):
            out = f"{root}_{n:03d}{ext}"
            n += 1
        return out

    def _stage_files(self, src_files: list[str]) -> list[str]:
        os.makedirs(STAGED_DIR, exist_ok=True)
        staged: list[str] = []

        for src in src_files:
            if not src or not os.path.exists(src):
                continue

            # already staged
            if self._norm_path(os.path.dirname(src)) == self._norm_path(STAGED_DIR):
                staged.append(src)
                continue

            dst = os.path.join(STAGED_DIR, os.path.basename(src))
            dst = self._unique_dst(dst)

            shutil.move(src, dst)
            self._stage_origin[self._norm_path(dst)] = src
            staged.append(dst)

        return staged

    def _unstage_files(self, staged_files: list[str]) -> int:
        restored = 0
        restore_fallback = os.path.join(STAGED_DIR, "_unstaged_restore")
        os.makedirs(restore_fallback, exist_ok=True)

        for p in staged_files:
            if not p or not os.path.exists(p):
                continue

            normp = self._norm_path(p)
            orig = self._stage_origin.get(normp)

            if orig:
                os.makedirs(os.path.dirname(orig), exist_ok=True)
                dst = orig
                if os.path.exists(dst):
                    dst = self._unique_dst(dst)
            else:
                dst = self._unique_dst(
                    os.path.join(restore_fallback, os.path.basename(p))
                )

            shutil.move(p, dst)
            restored += 1

            if normp in self._stage_origin:
                del self._stage_origin[normp]

        return restored

    def _update_ready_status(self):
        sets_count = len(self.batches)
        total_imgs = sum(len(s.get("files", [])) for s in self.batches)
        pending = len(self._pending_files)
        self.status_var.set(
            f"Ready | Sets: {sets_count} | Total images: {total_imgs} | Pending: {pending}"
        )
        self.progress_var.set(0)

    def _fmt_hms(self, secs: float) -> str:
        try:
            s = int(max(0, secs))
        except Exception:
            s = 0
        h = s // 3600
        m = (s % 3600) // 60
        ss = s % 60
        if h:
            return f"{h:02d}:{m:02d}:{ss:02d}"
        return f"{m:02d}:{ss:02d}"

    def _ui(self, fn):
        """Run fn on Tk's main thread (safe even during shutdown)."""
        try:
            if getattr(self, "_ui_disabled", False):
                return
            if not self.root.winfo_exists():
                return
            self.root.after(0, fn)
        except Exception:
            pass


    def _set_stage(
        self, stage_num, title, badge: str | None = None, progress: float | None = None
    ):
        now = time.time()

        # Init per-run timers
        if getattr(self, "_pipeline_t0", None) is None:
            self._pipeline_t0 = now
            self._stage_t0 = now
            self._current_stage_num = stage_num
            self._stage_durations = {}  # stage_num -> seconds

        # If stage changed, close previous stage duration
        if getattr(self, "_current_stage_num", stage_num) != stage_num:
            prev = self._current_stage_num
            try:
                prev_start = getattr(self, "_stage_t0", None)
                if prev_start is not None:
                    dur = now - prev_start
                    if dur >= 1.0:
                        self._stage_durations[prev] = dur
            except Exception:
                pass
            self._current_stage_num = stage_num
            self._stage_t0 = now

        elapsed_total = now - (self._pipeline_t0 or now)
        stage_elapsed = now - (getattr(self, "_stage_t0", now) or now)

        # Normalize progress to 0..1 if provided
        p = None
        if progress is not None:
            try:
                p = float(progress)
            except Exception:
                p = None
        if p is not None:
            p = max(0.0, min(1.0, p))

        # ETA: remaining in current stage (if progress known) + avg prior stage duration * remaining stages after this
        eta_current = 0.0
        if p is not None and p > 0.001:
            eta_current = max(0.0, (stage_elapsed / p) - stage_elapsed)

        durations = list(getattr(self, "_stage_durations", {}).values())
        avg_stage = (sum(durations) / len(durations)) if durations else 0.0
        remaining_future_stages = max(0, (TOTAL_STAGES - 1) - stage_num)

        eta_sec = eta_current + (avg_stage * remaining_future_stages)

        # Progress bar percent: stage index + within-stage progress (for UI only)
        done_units = (stage_num - 1) + (p if p is not None else 0.0)
        pct = int(round((done_units / TOTAL_STAGES) * 100)) if TOTAL_STAGES else 0
        pct = max(0, min(100, pct))

        log_line = f"[STAGE {stage_num}/{TOTAL_STAGES}] {title}"
        if badge:
            log_line += f"  {badge}"
        log_line += (
            f"    elapsed {self._fmt_hms(elapsed_total)} | eta {self._fmt_hms(eta_sec)}"
        )

        def _apply():
            try:
                self.status_var.set(log_line)
            except Exception:
                pass
            try:
                self.progress_var.set(pct)
            except Exception:
                pass

        # Console mirrors the UI line (stable, predictable)
        try:
            print(log_line)
        except Exception:
            pass

        self._ui(_apply)

    def _attach_autocomplete(self, combo: ttk.Combobox):
        """
        - Filters the drop-down list as you type (prefix first, then contains)
        - Autocompletes the entry (keeps typed prefix, selects suggested suffix)
        - Never auto-selects an item when the box is empty
        """
        import tkinter as _tk

        all_values = tuple(combo.cget("values"))
        combo.configure(state="normal")  # editable

        def _filter_list(txt: str):
            t = (txt or "").strip().lower()
            if not t:
                return all_values
            starts = [v for v in all_values if v.lower().startswith(t)]
            contains = [v for v in all_values if t in v.lower() and v not in starts]
            return tuple(starts + contains)

        # keep the posted list in sync whenever the arrow is clicked
        combo.configure(
            postcommand=lambda: combo.configure(values=_filter_list(combo.get()))
        )

        def on_keyrelease(ev):
            # refresh the list
            typed = combo.get()
            vals = _filter_list(typed)
            combo.configure(values=vals)

            # autocomplete unless user is deleting
            if ev.keysym in ("BackSpace", "Delete"):
                return
            if typed and vals:
                suggestion = vals[0]
                if suggestion.lower().startswith(typed.lower()):
                    # replace with suggestion but select only the completion part
                    combo.delete(0, _tk.END)
                    combo.insert(0, suggestion)
                    combo.selection_range(len(typed), _tk.END)
                    combo.icursor(len(typed))

        # single binding (no duplicate handlers)
        combo.bind("<KeyRelease>", on_keyrelease, add="+")

        # reset to full list when focusing or clicking the arrow
        def reset(_=None):
            combo.configure(values=all_values)

        combo.bind("<FocusIn>", reset, add="+")
        combo.bind("<Button-1>", reset, add="+")

    def _import_set_from_folder(self):
        folder = filedialog.askdirectory(
            title="Choose a folder containing images", initialdir=BASE_PICK_DIR
        )
        if not folder:
            return

        # fill Folder combobox from dir name (human-readable), but prefer an existing folder_map match
        try:
            human_folder = os.path.basename(folder).replace("_", " ").strip()
            cand = clean_token(human_folder).lower()

            picked = None
            for k, v in (self.folder_map or {}).items():
                if cand == clean_token(k).lower() or cand == clean_token(v).lower():
                    picked = v
                    break

            self.folder_var.set(picked or human_folder)
        except Exception:
            pass

        files = []
        for name in os.listdir(folder):
            if name.lower().endswith((".jpg", ".jpeg")):
                files.append(os.path.join(folder, name))
        if not files:
            messagebox.showwarning("No images", "That folder has no JPGs.")
            return

        # remember selection so we don't need to pick again
        self._pending_files = list(files)

        # Default behavior: auto-run AI subject suggestion (non-blocking)
        if AUTO_AI_SUBJECT_ON_SELECT and not (self._subject_get() or "").strip():
            self._ai_suggest_subject_for_current()

        self._update_ready_status()
        self._save_session_state()

    def _add_set_from_files(self):
        files = filedialog.askopenfilenames(
            title="Select images",
            initialdir=BASE_PICK_DIR,
            filetypes=[("JPEG files", "*.jpg;*.jpeg")],
        )

        if not files:
            return

        self._pending_files = list(files)

        # Default behavior: auto-run AI subject suggestion (non-blocking)
        if AUTO_AI_SUBJECT_ON_SELECT and not (self._subject_get() or "").strip():
            self._ai_suggest_subject_for_current()

        self._update_ready_status()
        self._save_session_state()

    def _clear_form(self):
        """Clear the Subject/Location/Folder entry widgets and pending files."""
        self._subject_set("")
        self._location_set("")
        self.folder_var.set("")
        self._pending_files = []
        self._update_ready_status()
        self._save_session_state()

    def _add_current_set(self):
        """Finalize the current pending selection into a set after user review."""
        try:
            if not self._pending_files:
                messagebox.showwarning(
                    "No files",
                    "Pick images first (Select images… or Import set from folder…).",
                )
                return

            try:
                self._runlog("ADD_SET_START", f"pending={len(self._pending_files)}")
            except Exception:
                pass

            # warn but allow continue if spelling issues remain
            try:
                self._subject_spellcheck_update()
            except Exception:
                pass
            try:
                self._location_spellcheck_update()
            except Exception:
                pass

            subj_issues = getattr(self, "_subject_issues", []) or []
            loc_issues = getattr(self, "_location_issues", []) or []
            if subj_issues or loc_issues:
                words = []
                words += [it.get("word", "") for it in subj_issues if it.get("word")]
                words += [it.get("word", "") for it in loc_issues if it.get("word")]
                preview = ", ".join(words[:8])
                if len(words) > 8:
                    preview += " ..."
                if preview:
                    messagebox.showwarning(
                        "Spelling warning",
                        "Subject or Location still contains underlined terms.\n\n"
                        f"{preview}\n\n"
                        "Tip: right click red words to Replace or Keep term.\n\n"
                        "Continuing anyway.",
                    )

            ok = self._add_set(list(self._pending_files))
            if ok:
                self._clear_form()
                try:
                    self._runlog(
                        "ADD_SET_OK",
                        f"sets={len(self.batches)} pending={len(self._pending_files)}",
                    )
                except Exception:
                    pass
            else:
                self._update_ready_status()
        except Exception as e:
            _append_runtime_crash("add_current_set", type(e), e, e.__traceback__)
            try:
                self._runlog("ADD_SET_EXCEPTION", f"{type(e).__name__}: {e}")
            except Exception:
                pass
            try:
                self._update_ready_status()
            except Exception:
                pass
            try:
                messagebox.showerror(
                    "Add set failed",
                    "An unexpected error happened while adding the set.\n\n"
                    "Your staged queue/session is preserved.\n"
                    f"Crash log:\n{RUNTIME_CRASH_LOG}\n\n"
                    f"Details:\n{type(e).__name__}: {e}",
                )
            except Exception:
                pass

    def _ai_suggest_subject_for_current(self, regenerate: bool = False, identify: bool = False):
        if not self._pending_files:
            messagebox.showinfo("No images selected", "Select images first.")
            return

        # Prevent overlapping suggestion workers when selecting many sets quickly.
        if getattr(self, "_ai_subject_busy", False):
            return

        paths = list(self._pending_files)
        paths_sig = {self._norm_path(p) for p in paths if p}
        effective_regenerate = bool(
            regenerate or os.environ.get("AMIR_SUBJECT_REGENERATE", "").strip() == "1"
        )
        effective_identify = bool(identify)
        try:
            manual_subject_before = self._subject_get()
        except Exception:
            manual_subject_before = ""
        self._ai_subject_busy = True
        self._ai_subject_paths_sig = paths_sig

        # Never block the Tk main thread (prevents "Not Responding")
        _ai_btn_prev_text = None
        _identify_btn_prev_text = None
        try:
            if hasattr(self, "ai_subject_btn"):
                try:
                    _ai_btn_prev_text = str(self.ai_subject_btn.cget("text"))
                except Exception:
                    _ai_btn_prev_text = "AI suggest subject"
                self.ai_subject_btn.configure(
                    state="disabled",
                    text=f"{'Identifying' if effective_identify else 'Regenerating' if effective_regenerate else 'AI suggesting'}... ({len(paths)})",
                )
            if hasattr(self, "ai_subject_identify_btn"):
                try:
                    _identify_btn_prev_text = str(self.ai_subject_identify_btn.cget("text"))
                except Exception:
                    _identify_btn_prev_text = "Identify"
                self.ai_subject_identify_btn.configure(
                    state="disabled",
                    text=f"Identifying... ({len(paths)})" if effective_identify else "Identify",
                )
        except Exception:
            pass

        try:
            if effective_identify:
                mode_label = "identifying with strict living/macro mode"
            elif effective_regenerate:
                mode_label = "regenerating with alternate model"
            else:
                mode_label = "working"
            self.status_var.set(f"AI subject: {mode_label} on {len(paths)} image(s). ETA is printed in PowerShell...")
            self.root.update_idletasks()
        except Exception:
            try:
                self.stage_lbl["text"] = f"AI subject: {mode_label} on {len(paths)} image(s). ETA is printed in PowerShell..."
            except Exception:
                pass

        def _worker():
            temp_map: dict[str, str] = {}

            try:
                temp_map = _amir_prepare_ollama_temp_images_for_subject(paths, label="subject")
                model_paths = [
                    temp_map.get(_amir_norm_temp_source_path(path), path)
                    for path in paths
                ]

                _regen_old_mode = os.environ.get("AMIR_SUBJECT_MODEL_MODE")
                _regen_old_ignore = os.environ.get("AMIR_SUBJECT_IGNORE_SUBJECT_HINT")
                _old_identify_mode = os.environ.get("AMIR_SUBJECT_IDENTIFY_MODE")
                _old_force_model = os.environ.get("AMIR_SUBJECT_FORCE_MODEL")
                _regen_context_active = os.environ.get("AMIR_SUBJECT_REGENERATE", "").strip() == "1"

                try:
                    if effective_identify:
                        os.environ["AMIR_SUBJECT_IDENTIFY_MODE"] = "1"
                        os.environ["AMIR_SUBJECT_MODEL_MODE"] = "identify"
                        os.environ["AMIR_SUBJECT_IGNORE_SUBJECT_HINT"] = "1"
                        os.environ.pop("AMIR_SUBJECT_FORCE_MODEL", None)
                    elif regenerate or _regen_context_active:
                        os.environ.pop("AMIR_SUBJECT_IDENTIFY_MODE", None)
                        os.environ["AMIR_SUBJECT_MODEL_MODE"] = "regenerate_alt"
                        os.environ["AMIR_SUBJECT_IGNORE_SUBJECT_HINT"] = "1"
                    else:
                        os.environ.pop("AMIR_SUBJECT_IDENTIFY_MODE", None)
                        os.environ.pop("AMIR_SUBJECT_MODEL_MODE", None)
                        os.environ.pop("AMIR_SUBJECT_IGNORE_SUBJECT_HINT", None)
                        os.environ.pop("AMIR_SUBJECT_FORCE_MODEL", None)

                    guess = ai_suggest_subject_multi(model_paths)
                finally:
                    if _regen_old_mode is None:
                        os.environ.pop("AMIR_SUBJECT_MODEL_MODE", None)
                    else:
                        os.environ["AMIR_SUBJECT_MODEL_MODE"] = _regen_old_mode

                    if _regen_old_ignore is None:
                        os.environ.pop("AMIR_SUBJECT_IGNORE_SUBJECT_HINT", None)
                    else:
                        os.environ["AMIR_SUBJECT_IGNORE_SUBJECT_HINT"] = _regen_old_ignore

                    if _old_identify_mode is None:
                        os.environ.pop("AMIR_SUBJECT_IDENTIFY_MODE", None)
                    else:
                        os.environ["AMIR_SUBJECT_IDENTIFY_MODE"] = _old_identify_mode

                    if _old_force_model is None:
                        os.environ.pop("AMIR_SUBJECT_FORCE_MODEL", None)
                    else:
                        os.environ["AMIR_SUBJECT_FORCE_MODEL"] = _old_force_model

                    if _regen_context_active:
                        try:
                            _context_writer = globals().get("_amir_subject_v2_write_context")
                            if callable(_context_writer):
                                _context_writer(active=False, hints="", current_subject="")
                        except Exception as cleanup_exc:
                            print(f"[WARN] Could not clear subject regenerate context: {cleanup_exc}")

                        for _regen_key in (
                            "AMIR_SUBJECT_REGENERATE",
                            "AMIR_SUBJECT_FORCE_MODEL",
                            "AMIR_SUBJECT_MODEL_MODE",
                            "AMIR_SUBJECT_IGNORE_SUBJECT_HINT",
                            "AMIR_SUBJECT_IDENTIFY_MODE",
                        ):
                            os.environ.pop(_regen_key, None)

                err = (_LAST_OLLAMA_ERROR or "").strip()
            except Exception as e:
                guess = None
                err = str(e)

            def _done():
                try:
                    if hasattr(self, "ai_subject_btn"):
                        self.ai_subject_btn.configure(
                            state="normal",
                            text=_ai_btn_prev_text or "AI suggest subject",
                        )
                    if hasattr(self, "ai_subject_identify_btn"):
                        self.ai_subject_identify_btn.configure(
                            state="normal",
                            text=_identify_btn_prev_text or "Identify",
                        )
                except Exception:
                    pass
                finally:
                    self._ai_subject_busy = False
                    self._ai_subject_paths_sig = set()

                current_sig = {self._norm_path(p) for p in (self._pending_files or []) if p}
                if current_sig != paths_sig:
                    # Selection changed while background suggestion was running.
                    self._update_ready_status()
                    return

                try:
                    manual_subject_now = self._subject_get() or manual_subject_before
                except Exception:
                    manual_subject_now = manual_subject_before

                g = (guess or "").strip()
                if not g:
                    if effective_regenerate and manual_subject_now:
                        print(
                            "[SUBJECT AI] Regenerate kept user subject after model "
                            f"conflict/failure: {manual_subject_now}"
                        )
                        self._update_ready_status()
                        return

                    if err:
                        messagebox.showinfo(
                            "AI suggestion", err or "Could not suggest a subject."
                        )
                    self._update_ready_status()
                    return

                g2 = autofix_subject(g, AUTOFIX_DICT_FILE)
                g2 = (g2 or "").strip()

                g2n = _normalize_subject_line(
                    g2, max_chars=SUBJECT_MAX_CHARS, max_words=None, min_words=3
                )
                if not g2n:
                    g2n = _normalize_subject_line(
                        g2, max_chars=SUBJECT_MAX_CHARS, max_words=None, min_words=1
                    )
                g2 = g2n or ""

                weak_subject_words = {
                    "white", "black", "red", "yellow", "blue", "green", "brown",
                    "grey", "gray", "pink", "purple", "orange", "dark", "light",
                    "bright", "pale", "color", "colour", "colors", "colours",
                    "close", "detail", "details", "scene", "view", "photo",
                    "image", "picture", "photography", "subject", "object",
                    "animal", "animals", "bird", "birds", "waterfowl",
                    "wildlife", "natural landscape", "landscape", "nature",
                    "scene", "scenery", "anser anser",
                }
                g2_key = re.sub(r"[^a-z0-9]+", " ", g2.lower()).strip()

                if g2_key in weak_subject_words:
                    if effective_regenerate and manual_subject_now:
                        print(
                            "[SUBJECT AI] Regenerate rejected weak model subject "
                            f"'{g2}' and kept user subject: {manual_subject_now}"
                        )
                        self._update_ready_status()
                        return

                    messagebox.showinfo(
                        "AI suggestion rejected",
                        f"Rejected weak subject suggestion: {g2}\n\n"
                        "Select a tighter same-subject set, or type the subject manually."
                    )
                    self._update_ready_status()
                    return
                if g2:
                    self._last_ai_suggested_subject = g2
                    self._last_ai_subject_paths_sig = set(current_sig)
                    self._last_ai_subject_temp_by_original = dict(temp_map or {})
                    self._subject_set(g2)
                else:
                    messagebox.showinfo("AI suggestion", "Could not suggest a subject.")

                self._update_ready_status()

            self._ui(_done)

        threading.Thread(target=_worker, daemon=True).start()

    def _validate_set_filename_length(
        self,
        subject: str,
        location: str,
        folder: str,
        files: list[str],
        action_label: str = "Add set",
    ) -> bool:
        previews: list[str] = []
        year_now = time.strftime("%Y")
        previews.append(
            build_preview_filename(
                subject=subject,
                location=location,
                folder=folder,
                camera=DEFAULT_CAMERA_TOKEN,
                year=year_now,
                index=1,
            )
        )

        # Optional EXIF preview check (disabled by default for add-set stability).
        if ADD_SET_EXIF_PREVIEW and files:
            try:
                exif = get_exif_data(files[0]) or {}
                cam = get_camera_model(exif) or DEFAULT_CAMERA_TOKEN
                exif_year = get_exif_year(exif) or year_now
                previews.append(
                    build_preview_filename(
                        subject=subject,
                        location=location,
                        folder=folder,
                        camera=cam,
                        year=exif_year,
                        index=1,
                    )
                )
            except Exception:
                pass

        unique_previews = list(dict.fromkeys(previews))
        too_long = [name for name in unique_previews if len(name) > MAX_FILENAME_LEN_WARN]
        if not too_long:
            return True

        worst = max(too_long, key=len)
        messagebox.showerror(
            "Filename too long",
            f"{action_label} blocked: generated filename would be {len(worst)} chars "
            f"(max {MAX_FILENAME_LEN_WARN}).\n\n{worst}\n\n"
            "Shorten Subject/Location/Folder and click Add set again.",
        )
        return False

    def _add_set(self, files: list[str]) -> bool:
        subject_raw = (self._subject_get() or "").strip()
        subject_raw = _title_case_subject_input_text(subject_raw)
        subject_raw = autofix_subject(subject_raw, AUTOFIX_DICT_FILE)
        subject_raw = _title_case_subject_input_text(subject_raw)
        subject = clean_token(subject_raw)

        location_h = (self.location_var.get() or "").strip()
        location_token = clean_token(location_h)

        # Warn but allow new location. Auto-append to location_list.json and log it.
        known = {clean_token(v) for v in (self.location_all or []) if v}
        if location_token and location_token not in known:
            messagebox.showwarning(
                "New location",
                f"Location '{location_h}' is not in location_list.json.\n\nIt will be allowed and added.",
            )
            self._runlog(
                "WARN_NEW_LOCATION", f"display={location_h} key={location_token}"
            )

            try:
                cur_list = self._load_json_any(LOCATION_FILE) or []
                if not isinstance(cur_list, list):
                    cur_list = []
                if location_token not in {clean_token(x) for x in cur_list if x}:
                    cur_list.append(location_token)
                    with open(LOCATION_FILE, "w", encoding="utf-8") as f:
                        json.dump(sorted(cur_list), f, ensure_ascii=False, indent=2)
                    # refresh UI values (best effort)
                    self.location_all = tuple(sorted(cur_list))
                    if hasattr(self, "location_cb"):
                        self.location_cb.configure(values=self.location_all)

            except Exception:
                pass
            self._log_new_taxonomy("location", location_h, location_token)

        location = location_token
        folder_h = (self.folder_var.get() or "").strip()

        # Resolve folder key from display name, with a case-insensitive token fallback.
        # This prevents duplicates like Cities vs cities that reset filename sequences.
        folder = self._folder_key_by_value.get(folder_h)

        force_create_new = False

        # If folder not found, check for very similar existing folders and warn first
        if not folder and folder_h:
            cand = clean_token(folder_h).lower()
            scored = []

            for k, v in (self.folder_map or {}).items():
                tv = clean_token(v).lower()
                tk = clean_token(k).lower()

                if not cand:
                    continue

                # exact match ignoring case/spacing
                if cand == tv or cand == tk:
                    scored.append((1.0, k, v))
                    continue

                score = difflib.SequenceMatcher(None, cand, tv).ratio() if tv else 0.0
                if score >= 0.88:
                    scored.append((score, k, v))

            scored.sort(reverse=True, key=lambda x: x[0])

            if scored:
                best_score, best_k, best_v = scored[0]
                lines = "\n".join([f"  • {v}   (key: {k})" for _, k, v in scored[:3]])

                choice = messagebox.askyesnocancel(
                    "Folder looks similar",
                    f"'{folder_h}' is not in folder_map.json.\n\n"
                    f"Similar folder(s) already exist:\n{lines}\n\n"
                    "Yes = use the best match\n"
                    "No = create a new folder anyway\n"
                    "Cancel = abort Add set",
                )

                if choice is None:
                    return False

                if choice is True:
                    folder = best_k
                    folder_h = best_v
                    try:
                        self.folder_var.set(best_v)
                    except Exception:
                        pass
                else:
                    force_create_new = True

        # Still not found: allow creation (with confirmation unless user already chose "create new anyway")
        if not folder:
            self._runlog(
                "WARN_NEW_FOLDER", f"display={folder_h} key={clean_token(folder_h)}"
            )

            if not force_create_new:
                if not messagebox.askyesno(
                    "New folder?",
                    f"'{folder_h}' is not in folder_map.json.\n\nWould you like to create a new folder?",
                ):
                    return False

            folder = clean_token(folder_h)
            self._log_new_taxonomy("folder", folder_h, folder)

            try:
                fm = self._load_json_any(FOLDER_MAP_FILE) or {}
                if not isinstance(fm, dict):
                    fm = {}
                fm[folder] = folder_h
                with open(FOLDER_MAP_FILE, "w", encoding="utf-8") as f:
                    json.dump(fm, f, ensure_ascii=False, indent=2)

                self.folder_map = fm
                self._folder_key_by_value = {v: k for k, v in fm.items()}
                self.folder_all = tuple(sorted(fm.values()))
                self.folder_cb.configure(values=self.folder_all)
            except Exception as e:
                messagebox.showerror(
                    "Folder map", f"Failed to update folder_map.json:\n{e}"
                )
                return False

        if not location or not folder:
            messagebox.showwarning(
                "Missing fields", "Please fill Location and Folder (category) first."
            )
            return False

        if not subject:
            files_for_subject = [p for p in (files or []) if p]

            try:
                temp_map_auto = _amir_prepare_ollama_temp_images_for_subject(
                    files_for_subject,
                    label="subject_auto",
                )
                model_paths = [
                    temp_map_auto.get(_amir_norm_temp_source_path(path), path)
                    for path in files_for_subject
                ]
                subject = clean_token(ai_suggest_subject_multi(model_paths) or "")
                if subject:
                    self._last_ai_suggested_subject = subject
                    self._last_ai_subject_paths_sig = {self._norm_path(p) for p in files_for_subject if p}
                    self._last_ai_subject_temp_by_original = dict(temp_map_auto or {})
            except Exception:
                subject = ""

            if not subject and len(files_for_subject) == 1:
                subject = clean_token(ai_suggest_subject(files_for_subject[0]) or "")

            if not subject:
                messagebox.showwarning(
                    "Subject", "Please enter a Subject or click ‘AI suggest subject’."
                )
                return False

        if not self._validate_set_filename_length(
            subject=subject,
            location=location,
            folder=folder,
            files=files,
            action_label="Add set",
        ):
            return False

        # De-duplicate vs other sets (case-insensitive absolute compare)
        already = {self._norm_path(p) for s in self.batches for p in s["files"]}
        new_files = [p for p in files if self._norm_path(p) not in already]
        if not new_files:
            messagebox.showinfo(
                "No new files", "All selected files are already in other sets."
            )
            return False

        # Stage now: move to STAGED_DIR so they disappear from original folder
        try:
            staged_files = self._stage_files(new_files)
        except Exception as e:
            messagebox.showerror(
                "Staging failed", f"Could not move files to staged folder:\n{e}"
            )
            return False

        if not staged_files:
            messagebox.showwarning("No files", "No valid files were staged.")
            return False

        current_sig = {self._norm_path(p) for p in (files or []) if p}
        ai_suggested_subject = ""
        ai_ollama_temp_by_original: dict[str, str] = {}

        if getattr(self, "_last_ai_subject_paths_sig", set()) == current_sig:
            ai_suggested_subject = str(getattr(self, "_last_ai_suggested_subject", "") or "").strip()
            ai_ollama_temp_by_original = dict(getattr(self, "_last_ai_subject_temp_by_original", {}) or {})

        self.batches.append(
            {
                "subject": subject,
                "ai_suggested_subject": ai_suggested_subject,
                "location": location,
                "folder": folder,
                "folder_h": folder_h,
                "files": staged_files,
                "ai_ollama_temp_by_original": ai_ollama_temp_by_original,
            }
        )
        self._refresh_tree()
        self._update_ready_status()
        self._save_session_state()
        return True

    def _refresh_tree(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        for i, s in enumerate(self.batches, start=1):
            self.tree.insert(
                "",
                "end",
                iid=str(i),
                values=(len(s["files"]), s["subject"], s["location"], s["folder_h"]),
            )

    def _remove_selected_set(self):
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(sel[0]) - 1
        if 0 <= idx < len(self.batches):
            self._unstage_files(self.batches[idx].get("files", []))
            self.batches.pop(idx)
            self._refresh_tree()
            self._update_ready_status()
            self._save_session_state()

    def _clear_sets(self):
        for s in self.batches:
            self._unstage_files(s.get("files", []))
        self.batches.clear()
        self._refresh_tree()
        self._update_ready_status()
        self._save_session_state()

    def _edit_selected_set(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Edit set", "Select a set in the table to edit.")
            return
        idx = int(sel[0]) - 1
        if idx < 0 or idx >= len(self.batches):
            return

        row = self.batches[idx]

        top = tk.Toplevel(self.root)
        top.title("Edit set")
        top.transient(self.root)
        top.grab_set()

        sv = tk.StringVar(value=row["subject"])
        lv = tk.StringVar(value=row["location"])
        fv = tk.StringVar(value=row.get("folder_h") or row["folder"])

        ttk.Label(top, text="Subject:").grid(
            row=0, column=0, sticky="w", padx=10, pady=(10, 4)
        )
        e1 = ttk.Entry(top, textvariable=sv, width=46)
        e1.grid(row=0, column=1, padx=10, pady=(10, 4), sticky="ew")

        ttk.Label(top, text="Location:").grid(
            row=1, column=0, sticky="w", padx=10, pady=4
        )
        e2 = ttk.Combobox(top, textvariable=lv, values=self.location_all, width=46)
        self._attach_autocomplete(e2)
        e2.grid(row=1, column=1, padx=10, pady=4, sticky="ew")

        ttk.Label(top, text="Folder (category):").grid(
            row=2, column=0, sticky="w", padx=10, pady=4
        )
        e3 = ttk.Combobox(top, textvariable=fv, values=self.folder_all, width=46)
        self._attach_autocomplete(e3)
        e3.grid(row=2, column=1, padx=10, pady=4, sticky="ew")

        btns = ttk.Frame(top)
        btns.grid(row=3, column=0, columnspan=2, pady=(10, 10))

        def _apply():
            subject = (sv.get() or "").strip()
            location = (lv.get() or "").strip()
            folder_h = (fv.get() or "").strip()
            if not subject or not location or not folder_h:
                messagebox.showwarning(
                    "Missing fields", "Subject, Location and Folder are required."
                )
                return

            # Resolve folder key from the human display name; if missing, offer to create it.
            folder_key = self._folder_key_by_value.get(folder_h)
            if not folder_key:
                if not messagebox.askyesno(
                    "New folder?",
                    f"'{folder_h}' is not in folder_map.json.\n\nWould you like to create a new folder?",
                ):
                    return
                folder_key = clean_token(folder_h)
                try:
                    fm = self._load_json_any(FOLDER_MAP_FILE) or {}
                    if not isinstance(fm, dict):
                        fm = {}
                    fm[folder_key] = folder_h
                    with open(FOLDER_MAP_FILE, "w", encoding="utf-8") as f:
                        json.dump(fm, f, ensure_ascii=False, indent=2)
                    self.folder_map = fm
                    self._folder_key_by_value = {v: k for k, v in fm.items()}
                    self.folder_all = tuple(sorted(fm.values()))
                    e3.configure(values=self.folder_all)  # update dialog combobox
                    self.folder_cb.configure(
                        values=self.folder_all
                    )  # update main combobox
                except Exception as e:
                    messagebox.showerror(
                        "Folder map", f"Failed to update folder_map.json:\n{e}"
                    )
                    return

            if not self._validate_set_filename_length(
                subject=subject,
                location=location,
                folder=folder_key,
                files=row.get("files", []),
                action_label="Edit set",
            ):
                return

            row["subject"] = subject
            row["location"] = location
            row["folder_h"] = folder_h
            row["folder"] = folder_key
            self._refresh_tree()
            self._save_session_state()
            top.destroy()

        ttk.Button(btns, text="OK", command=_apply).pack(side="left", padx=6)
        ttk.Button(btns, text="Cancel", command=top.destroy).pack(side="left", padx=6)

        top.columnconfigure(1, weight=1)


    def _run_pipeline(self):
        # rollback trackers must be defined before the try/finally
        success = False
        exit_code = 0  # non-zero => abort the whole run (scoring reliability)
        suppress_fail_dialog = False

        inserted_ids: list[int] = []
        reserved_names: list[str] = []
        moved: list[str] = []
        orig_paths: dict[str, str] = {}
        prefill_qc_summary: dict | None = None
        metadata_quality_summary: dict | None = None

        def _stream_cmd_with_ok_counter(
            cmd,
            cwd: str | None,
            total: int,
            stage_num_for_ui: int | None = None,
            badge_prefix: str = "",
            overall_total: int = 0,
            overall_done_before: int = 0,
            overall_ok_before: int = 0,
            overall_fail_before: int = 0,
            idle_timeout_sec: int = 0,
            hard_timeout_sec: int = 0,
        ):
            """
            Runs a child process and streams output live.

            Counts BOTH [OK] and [FAIL] lines as processed so ETA is real.
            Expected child lines:
              [OK] id=... file=...
              [FAIL] id=... file=... reason=...

            Returns: (returncode, ok_count, fail_count, tail_text)
            """
            ok_count = 0
            fail_count = 0
            done_count = 0
            tail: list[str] = []
            t0 = time.time()
            overall_total = max(0, int(overall_total or 0))
            overall_done_before = max(0, int(overall_done_before or 0))
            overall_ok_before = max(0, int(overall_ok_before or 0))
            overall_fail_before = max(0, int(overall_fail_before or 0))

            env = os.environ.copy()
            env.setdefault("PYTHONUTF8", "1")
            env.setdefault("PYTHONIOENCODING", "utf-8")
            # Force app-local HF cache for helper scripts to avoid broken global
            # cache entries from other Python distributions (e.g. Anaconda).
            try:
                _cache_base = (
                    os.path.join(os.path.dirname(sys.executable), ".cache")
                    if getattr(sys, "frozen", False)
                    else os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")
                )
                _hf_home = os.path.join(_cache_base, "huggingface")
                _hf_hub = os.path.join(_hf_home, "hub")
                os.makedirs(_hf_hub, exist_ok=True)
                _torch_home = os.path.join(_cache_base, "torch")
                os.makedirs(_torch_home, exist_ok=True)

                env["XDG_CACHE_HOME"] = _cache_base
                env["HF_HOME"] = _hf_home
                env["HUGGINGFACE_HUB_CACHE"] = _hf_hub
                env["HF_HUB_CACHE"] = _hf_hub
                env["TORCH_HOME"] = _torch_home
                env["AMIR_TIMM_INCEPTION_RESNET_V2_WEIGHTS"] = os.path.join(
                    _hf_hub,
                    "models--timm--inception_resnet_v2.tf_in1k",
                    "snapshots",
                    "548a334e1afd3b398b4be37c89972dfb24d707aa",
                    "pytorch_model.bin",
                )

                # Strict production rule:
                # scoring must run, but it must not download during a batch.
                env["HF_HUB_OFFLINE"] = "1"

                env.pop("TRANSFORMERS_CACHE", None)
                env.setdefault("HF_HUB_DISABLE_XET", "1")
                env.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
            except Exception:
                pass
            # When running from a PyInstaller EXE, avoid leaking bundled Python
            # runtime vars/paths into external interpreter subprocesses.
            if getattr(sys, "frozen", False):
                for _k in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "_MEIPASS2"):
                    env.pop(_k, None)
                try:
                    _meipass = str(getattr(sys, "_MEIPASS", "") or "")
                    if _meipass:
                        _norm_mei = os.path.normcase(os.path.normpath(_meipass))
                        _parts = []
                        for _p in str(env.get("PATH", "")).split(os.pathsep):
                            if not _p:
                                continue
                            if os.path.normcase(os.path.normpath(_p)) == _norm_mei:
                                continue
                            _parts.append(_p)
                        env["PATH"] = os.pathsep.join(_parts)
                except Exception:
                    pass

            proc = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
            )
            idle_timeout_sec = max(0, int(idle_timeout_sec or 0))
            hard_timeout_sec = max(0, int(hard_timeout_sec or 0))
            line_q: "queue.Queue[str | None]" = queue.Queue()
            reader_done = threading.Event()
            timed_out = False
            timeout_reason = ""
            last_output_ts = time.time()

            def _reader():
                try:
                    if proc.stdout:
                        for raw in proc.stdout:
                            line_q.put(raw.rstrip("\n"))
                except Exception as _e:
                    line_q.put(f"[WARN] stream reader exception: {type(_e).__name__}: {_e}")
                finally:
                    line_q.put(None)
                    reader_done.set()

            threading.Thread(target=_reader, daemon=True).start()

            def _bump_ui():
                if stage_num_for_ui is None or total <= 0:
                    return
                elapsed = max(0.001, time.time() - t0)
                rate = done_count / elapsed if done_count > 0 else 0.0
                remain = max(0, total - done_count)
                eta = (remain / rate) if rate > 0 else 0.0
                try:
                    prefix = (badge_prefix.strip() + " ") if badge_prefix else ""
                    global_badge = ""
                    progress_val = done_count / total
                    if overall_total > 0:
                        g_done = min(overall_total, overall_done_before + done_count)
                        g_ok = min(overall_total, overall_ok_before + ok_count)
                        g_fail = min(overall_total, overall_fail_before + fail_count)
                        global_badge = (
                            f" | total img={g_done}/{overall_total} "
                            f"ok={g_ok}/{overall_total} fail={g_fail}/{overall_total}"
                        )
                        progress_val = g_done / max(1, overall_total)
                    self._set_stage(
                        stage_num_for_ui,
                        STAGES[stage_num_for_ui],
                        badge=(
                            f"{prefix}[{done_count}/{total}] ok={ok_count}/{total} fail={fail_count}/{total}"
                            f"{global_badge} "
                            f"{rate:.2f}/img eta={self._fmt_hms(eta)}"
                        ),
                        progress=progress_val,
                    )
                except Exception:
                    pass

            try:
                while True:
                    try:
                        line = line_q.get(timeout=0.5)
                    except queue.Empty:
                        now = time.time()
                        if hard_timeout_sec > 0 and (now - t0) > hard_timeout_sec:
                            timed_out = True
                            timeout_reason = (
                                f"hard timeout ({hard_timeout_sec}s) "
                                f"batch_done={done_count}/{total}"
                            )
                        elif idle_timeout_sec > 0 and (now - last_output_ts) > idle_timeout_sec:
                            timed_out = True
                            timeout_reason = (
                                f"idle timeout ({idle_timeout_sec}s without output) "
                                f"batch_done={done_count}/{total}"
                            )

                        if timed_out:
                            tail.append(f"[TIMEOUT] {timeout_reason}")
                            print(f"[WARN] Child process timeout: {timeout_reason}. Terminating...")
                            try:
                                proc.kill()
                            except Exception:
                                pass
                            break

                        if proc.poll() is not None and reader_done.is_set():
                            break
                        continue

                    if line is None:
                        break

                    last_output_ts = time.time()
                    tail.append(line)
                    if len(tail) > 80:
                        tail = tail[-80:]

                    if line.startswith("[OK]") and ("id=" in line):
                        ok_count += 1
                        done_count += 1

                        rest = re.sub(r"^\[OK\]\s+\d+/\d+\s+", "", line)
                        rest = re.sub(r"^\[OK\]\s+", "", rest)
                        if overall_total > 0:
                            g_done = min(overall_total, overall_done_before + done_count)
                            g_ok = min(overall_total, overall_ok_before + ok_count)
                            g_fail = min(overall_total, overall_fail_before + fail_count)
                            print(
                                f"[OK] img={g_done}/{overall_total} ok={g_ok}/{overall_total} fail={g_fail}/{overall_total} "
                                f"| batch={done_count}/{total} ok={ok_count}/{total} fail={fail_count}/{total} {rest}"
                            )
                        else:
                            print(
                                f"[OK] batch={done_count}/{total} ok={ok_count}/{total} fail={fail_count}/{total} {rest}"
                            )
                        _bump_ui()
                        continue

                    if line.startswith("[OUT] id="):
                        ok_count += 1
                        done_count += 1

                        rest = re.sub(r"^\[OUT\]\s+", "", line)
                        if overall_total > 0:
                            g_done = min(overall_total, overall_done_before + done_count)
                            g_ok = min(overall_total, overall_ok_before + ok_count)
                            g_fail = min(overall_total, overall_fail_before + fail_count)
                            print(
                                f"[OK] img={g_done}/{overall_total} ok={g_ok}/{overall_total} fail={g_fail}/{overall_total} "
                                f"| batch={done_count}/{total} ok={ok_count}/{total} fail={fail_count}/{total} {rest}"
                            )
                        else:
                            print(
                                f"[OK] batch={done_count}/{total} ok={ok_count}/{total} fail={fail_count}/{total} {rest}"
                            )
                        _bump_ui()
                        continue

                    if line.startswith("[NEEDS-GATE] id="):
                        done_count += 1

                        rest = re.sub(r"^\[NEEDS-GATE\]\s+", "", line)
                        if overall_total > 0:
                            g_done = min(overall_total, overall_done_before + done_count)
                            g_ok = min(overall_total, overall_ok_before + ok_count)
                            g_fail = min(overall_total, overall_fail_before + fail_count)
                            print(
                                f"[PREFILL] img={g_done}/{overall_total} ok={g_ok}/{overall_total} fail={g_fail}/{overall_total} "
                                f"| batch={done_count}/{total} ok={ok_count}/{total} fail={fail_count}/{total} {rest}"
                            )
                        else:
                            print(
                                f"[PREFILL] batch={done_count}/{total} ok={ok_count}/{total} fail={fail_count}/{total} {rest}"
                            )
                        _bump_ui()
                        continue

                    if line.startswith("[FAIL]") and ("id=" in line):
                        fail_count += 1
                        done_count += 1

                        rest = re.sub(r"^\[FAIL\]\s+\d+/\d+\s+", "", line)
                        rest = re.sub(r"^\[FAIL\]\s+", "", rest)
                        if overall_total > 0:
                            g_done = min(overall_total, overall_done_before + done_count)
                            g_ok = min(overall_total, overall_ok_before + ok_count)
                            g_fail = min(overall_total, overall_fail_before + fail_count)
                            print(
                                f"[FAIL] img={g_done}/{overall_total} ok={g_ok}/{overall_total} fail={g_fail}/{overall_total} "
                                f"| batch={done_count}/{total} ok={ok_count}/{total} fail={fail_count}/{total} {rest}"
                            )
                        else:
                            print(
                                f"[FAIL] batch={done_count}/{total} ok={ok_count}/{total} fail={fail_count}/{total} {rest}"
                            )
                        _bump_ui()
                        continue

                    print(line)
            finally:
                try:
                    if proc.stdout:
                        proc.stdout.close()
                except Exception:
                    pass

            try:
                rc = proc.wait(timeout=10)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
                rc = 1
            if timed_out:
                # Map timeout stalls into the native-crash retry path.
                rc = 3221225477
            elapsed = max(0.001, time.time() - t0)
            rate = done_count / elapsed if done_count > 0 else 0.0
            global_tail = ""
            if overall_total > 0:
                g_done = min(overall_total, overall_done_before + done_count)
                g_ok = min(overall_total, overall_ok_before + ok_count)
                g_fail = min(overall_total, overall_fail_before + fail_count)
                global_tail = (
                    f" total_img={g_done}/{overall_total} "
                    f"total_ok={g_ok}/{overall_total} total_fail={g_fail}/{overall_total}"
                )
            print(
                f"[STAGE SUMMARY] rc={rc} done={done_count}/{total} ok={ok_count}/{total} fail={fail_count}/{total}"
                f"{global_tail} "
                f"elapsed={self._fmt_hms(elapsed)} rate={rate:.2f}/img"
            )
            return rc, ok_count, fail_count, "\n".join(tail)

        try:
            try:
                os.chdir(
                    os.path.dirname(DATA_DIR)
                )  # project root: makes relative "data\..." resolve correctly even when EXE runs elsewhere
            except Exception:
                pass

            self._set_stage(0, STAGES[0])

            os.makedirs(DATA_DIR, exist_ok=True)
            os.makedirs(INCOMING_DIR, exist_ok=True)

            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            _ensure_db_table(conn)

            cur.execute(
                f"DELETE FROM {TABLE_NAME} "
                f"WHERE (Path IS NULL OR Path='') OR (File_Name IS NULL OR File_Name='')"
            )
            conn.commit()

            inserted = 0
            total_sets = len(self.batches)
            router_batches: list[dict] = []

            for si, s in enumerate(self.batches, start=1):
                badge = f"[Set {si}/{total_sets}]"
                subject, location, folder = s["subject"], s["location"], s["folder"]
                files = s["files"]
                set_inserted_ids: list[int] = []

                self._set_stage(1, STAGES[1], badge)
                for src in files:
                    base = os.path.basename(src)
                    # ---- Skip duplicates already in DB (prevents re-scoring) ----
                    try:
                        cur.execute(
                            f"SELECT id, COALESCE(QC_Status,''), COALESCE(QR,'') "
                            f"FROM {TABLE_NAME} "
                            "WHERE Original_File_Name=? AND Folder=? AND Location=? "
                            "LIMIT 1",
                            (base, folder, location),
                        )
                        hit = cur.fetchone()
                    except Exception:
                        hit = None

                    if hit:
                        rid, qc_status, qr_val = hit[0], str(hit[1] or ""), str(hit[2] or "")

                        print(
                            f"[SKIP] Already in DB id={rid} Original_File_Name={base} "
                            f"QC_Status={qc_status} QR={qr_val}"
                        )

                        # Put the staged file back where it came from (so STAGED_DIR stays clean)
                        try:
                            norm_src = self._norm_path(src)
                            orig = self._stage_origin.get(norm_src)

                            if orig and os.path.exists(src) and self._norm_path(orig) != norm_src:
                                os.makedirs(os.path.dirname(orig), exist_ok=True)
                                shutil.move(src, orig)

                            if norm_src in self._stage_origin:
                                del self._stage_origin[norm_src]
                        except Exception:
                            pass

                        continue

                    dst = os.path.join(INCOMING_DIR, base)
                    if os.path.abspath(src) != os.path.abspath(dst):
                        if os.path.exists(dst):
                            rootn, ext = os.path.splitext(dst)
                            n = 1
                            while os.path.exists(dst):
                                dst = f"{rootn}_{n:03d}{ext}"
                                n += 1
                        shutil.move(src, dst)
                        # orig_paths is used for rollback: restore to the original folder if we know it
                        _orig = self._stage_origin.get(self._norm_path(src)) or src
                        orig_paths[dst] = _orig
                        moved.append(dst)

                    self._set_stage(2, STAGES[2], badge)

                    vals = {
                        "Folder": folder,
                        "File_Name": os.path.basename(dst),
                        "Path": dst,
                        "Thumb_Path": "",
                        "DateTime": None,
                        "Camera": None,
                        "Lens_model": None,
                        "Width": None,
                        "Height": None,
                        "Exposure": None,
                        "Aperture": None,
                        "ISO": None,
                        "Focal_length": None,
                        "Keywords": "",
                        "Caption": "",
                        "alt_text": "",
                        "Location": location,
                        "Subject": subject,
                        "ai_suggested_subject": str(s.get("ai_suggested_subject") or "").strip(),
                        "final_subject": subject,
                        "QR": None,
                        "QC_Status": "NA",
                        "Review_Status": "Queued",
                        "Original_File_Name": base,
                        "ollama_path": "",
                        "batch_set_index": si,
                        "batch_set_total": total_sets,
                        "metadata_version": 1,
                    }

                    try:
                        temp_map = dict(s.get("ai_ollama_temp_by_original") or {})
                        original_before_staging = self._stage_origin.get(self._norm_path(src)) or orig_paths.get(dst) or src

                        lookup_keys = [
                            _amir_norm_temp_source_path(original_before_staging),
                            _amir_norm_temp_source_path(src),
                            _amir_norm_temp_source_path(dst),
                        ]

                        for lookup_key in lookup_keys:
                            temp_path = str(temp_map.get(lookup_key) or "").strip()

                            if temp_path and os.path.exists(temp_path):
                                vals["ollama_path"] = temp_path
                                print(f"[SUBJECT PREP] reusing temp resize for id insert source={os.path.basename(src)}")
                                break

                    except Exception as exc:
                        print(f"[WARN] Could not attach subject temp resize to row: {type(exc).__name__}: {exc}")

                    # EXIF is best-effort; filename generation is strict (must not silently fallback).
                    exif = {}
                    try:
                        exif = get_exif_data(dst) or {}
                    except Exception as ex:
                        print(f"[WARN] EXIF parse failed for {dst}: {ex}")
                    exif = _merge_exif_with_pil_fallback(dst, exif)

                    vals["DateTime"] = exif.get("DateTimeOriginal") or exif.get("DateTime")
                    cam = get_camera_model(exif)
                    vals["Camera"] = cam
                    year = get_exif_year(exif)

                    # Reserve a collision-free filename up front.
                    # This checks both used_filenames.json (case-insensitive in helper)
                    # and destination disk paths to avoid late publish collisions.
                    def _release_reserved_name(_name: str):
                        try:
                            _name = str(_name or "").strip()
                            if not _name or not os.path.exists(USED_NAMES):
                                return
                            with open(USED_NAMES, "r", encoding="utf-8") as _f:
                                _u = json.load(_f)
                            if isinstance(_u, list):
                                _u = [x for x in _u if str(x).casefold() != _name.casefold()]
                            elif isinstance(_u, dict):
                                _u = {
                                    k: v
                                    for k, v in _u.items()
                                    if str(k).casefold() != _name.casefold()
                                    and str(v).casefold() != _name.casefold()
                                }
                            with open(USED_NAMES, "w", encoding="utf-8") as _f:
                                json.dump(_u, _f, indent=2, ensure_ascii=False)
                        except Exception:
                            pass

                    _gen_tries = 0
                    while True:
                        _gen_tries += 1
                        _fname = generate_unique_filename(
                            subject, location, folder, cam, year
                        )
                        _fname = clean_filename(_fname)

                        _dest_taken = False
                        if LOCAL_SITE_IMAGES_BASE:
                            _web = os.path.join(
                                LOCAL_SITE_IMAGES_BASE, str(year), folder, _fname
                            )
                            _thumb = os.path.join(
                                LOCAL_SITE_IMAGES_BASE, str(year), "thumbs", folder, _fname
                            )
                            _dest_taken = os.path.exists(_web) or os.path.exists(_thumb)

                        if len(_fname) > MAX_FILENAME_LEN_WARN:
                            _release_reserved_name(_fname)
                            raise RuntimeError(
                                f"Generated filename exceeds {MAX_FILENAME_LEN_WARN} chars: {_fname}"
                            )

                        if not _dest_taken:
                            vals["File_Name"] = _fname
                            reserved_names.append(_fname)
                            break

                        print(
                            f"[WARN] Filename collision on destination for '{_fname}'. "
                            "Trying next index."
                        )
                        # generate_unique_filename() already reserved this name in JSON.
                        # Release it immediately because it cannot be used on destination.
                        _release_reserved_name(_fname)
                        if _gen_tries >= 500:
                            raise RuntimeError(
                                f"Could not reserve collision-free filename after {_gen_tries} attempts"
                            )

                    vals["Lens_model"] = exif.get("LensModel") or exif.get(
                        "LensModelName"
                    )
                    w = _as_float(exif.get("ExifImageWidth"))
                    h = _as_float(exif.get("ExifImageHeight"))
                    vals["Width"] = int(w) if w else None
                    vals["Height"] = int(h) if h else None
                    if vals["Width"] is None or vals["Height"] is None:
                        try:
                            with Image.open(dst) as _im:
                                _w, _h = _im.size
                            if vals["Width"] is None and _w:
                                vals["Width"] = int(_w)
                            if vals["Height"] is None and _h:
                                vals["Height"] = int(_h)
                        except Exception:
                            pass
                    vals["Exposure"] = _fmt_exposure(exif.get("ExposureTime"))
                    apf = _as_float(exif.get("FNumber"))
                    if apf:
                        vals["Aperture"] = f"f/{apf:.1f}"
                    iso = _as_float(
                        exif.get("ISOSpeedRatings")
                        or exif.get("PhotographicSensitivity")
                    )
                    vals["ISO"] = int(iso) if iso else None
                    fl = _as_float(exif.get("FocalLength"))
                    vals["Focal_length"] = int(fl) if fl else None

                    _subj = subject.replace("_", " ").strip()
                    _loc = location.replace("_", " ").strip()
                    folder_display = s.get("folder_h") or folder
                    _fold = folder_display.replace("_", " ").strip()
                    _cam = (vals.get("Camera") or "").replace("_", " ").strip()
                    if not vals["Caption"]:
                        if _loc:
                            vals["Caption"] = f"{_subj} in {_loc}."
                        else:
                            vals["Caption"] = f"{_subj}."

                    if not vals.get("alt_text"):
                        alt_parts = [k for k in [_subj, _loc, _fold] if k]
                        vals["alt_text"] = " ".join(alt_parts[:3]).strip() or _subj or "Photo"

                    if not vals["Keywords"]:
                        base_keys = [_subj, _loc, _fold]
                        vals["Keywords"] = ", ".join([k for k in base_keys if k])


                    try:
                        row_id = upsert_review_row(cur, vals)
                        inserted_ids.append(row_id)
                        upsert_metadata_quality_seed_from_review_row(cur, row_id, vals)
                        inserted += 1
                        set_inserted_ids.append(row_id)
                    except Exception as ex:
                        print(f"[WARN] insert failed for {vals.get('Path')}: {ex}")
                        # If DB insert failed, release reserved filename immediately.
                        try:
                            _fname = str(vals.get("File_Name") or "").strip()
                            if _fname and os.path.exists(USED_NAMES):
                                with open(USED_NAMES, "r", encoding="utf-8") as _f:
                                    _u = json.load(_f)
                                if isinstance(_u, list):
                                    _u = [x for x in _u if str(x).casefold() != _fname.casefold()]
                                elif isinstance(_u, dict):
                                    _u = {
                                        k: v for k, v in _u.items()
                                        if str(k).casefold() != _fname.casefold()
                                        and str(v).casefold() != _fname.casefold()
                                    }
                                with open(USED_NAMES, "w", encoding="utf-8") as _f:
                                    json.dump(_u, _f, indent=2, ensure_ascii=False)
                            if _fname:
                                reserved_names[:] = [
                                    x for x in reserved_names if str(x).casefold() != _fname.casefold()
                                ]
                        except Exception:
                            pass

                if set_inserted_ids:
                    router_batches.append(
                        {
                            "row_ids": list(set_inserted_ids),
                            "subject": str(s.get("ai_suggested_subject") or subject or "").strip(),
                            "location": location,
                            "folder": folder,
                            "set_index": si,
                            "total_sets": total_sets,
                        }
                    )

            self._set_stage(3, STAGES[3])
            conn.commit()
            conn.close()
            print(f"[INFO] Inserted {inserted} rows into {TABLE_NAME}.")
            success = True

            session_scope_ids = sorted({int(x) for x in inserted_ids if int(x) > 0})
            prefill_scope_ids: list[int] = []
            if SESSION_SCOPE_ONLY:
                if session_scope_ids:
                    print(f"[INFO] Session scope enabled: {len(session_scope_ids)} row(s) in this run.")
                else:
                    print("[INFO] Session scope enabled: no new rows inserted in this run.")
                # Include this-run rows plus queued backlog rows missing metadata fields.
                try:
                    with sqlite3.connect(DB_PATH) as _c:
                        _cur = _c.cursor()
                        missing_meta = (
                            "COALESCE(Caption,'')='' OR COALESCE(Keywords,'')='' OR COALESCE(alt_text,'')=''"
                        )
                        sql_pf = (
                            f"SELECT id FROM {TABLE_NAME} "
                            "WHERE COALESCE(Review_Status,'')='Queued' "
                            f"AND ({missing_meta})"
                        )
                        pf_ids = [int(r[0]) for r in _cur.execute(sql_pf).fetchall() if int(r[0]) > 0]
                        prefill_scope_ids = sorted(set(session_scope_ids).union(set(pf_ids)))
                except Exception as _e:
                    print(f"[WARN] Could not build prefill scope ids: {_e}")
                    prefill_scope_ids = list(session_scope_ids)

                print(
                    f"[INFO] Prefill scope ids: {len(prefill_scope_ids)} "
                    f"(session={len(session_scope_ids)})"
                )

            # Stage: AI quality scoring (runs only when needed)
            score_total = 0
            try:
                with sqlite3.connect(DB_PATH) as _c:
                    _cur = _c.cursor()
                    if SESSION_SCOPE_ONLY and not session_scope_ids:
                        score_total = 0
                    else:
                        if SCORE_FORCE_RUN and SESSION_SCOPE_ONLY and session_scope_ids:
                            where = "WHERE COALESCE(Review_Status,'')='Queued'"
                        else:
                            where = (
                                "WHERE COALESCE(Review_Status,'')='Queued' "
                                "AND (nima_score IS NULL OR blur_score IS NULL OR brightness_score IS NULL "
                                "OR contrast_score IS NULL OR brisque_score IS NULL OR clip_aesthetic_score IS NULL "
                                "OR QR IS NULL OR COALESCE(QC_Status,'') IN ('', 'NA'))"
                            )
                        params: list[object] = []
                        if SESSION_SCOPE_ONLY and session_scope_ids:
                            where += f" AND id IN ({','.join(['?'] * len(session_scope_ids))})"
                            params.extend(session_scope_ids)
                        _cur.execute(f"SELECT COUNT(1) FROM {TABLE_NAME} {where}", params)
                        score_total = int(_cur.fetchone()[0] or 0)
            except Exception:
                score_total = 0

            # Prefer AMIR_PYTHON if set; otherwise probe known local venvs.
            _default_venv_candidates = [
                os.path.join(os.path.dirname(DATA_DIR), ".venv313", "Scripts", "python.exe"),
                os.path.join(os.path.dirname(DATA_DIR), ".venv", "Scripts", "python.exe"),
                os.path.join(os.path.dirname(DATA_DIR), ".venv_cuda", "Scripts", "python.exe"),
                os.path.join(os.path.dirname(DATA_DIR), ".venv312", "Scripts", "python.exe"),
                r"YOUR_PATH_HERE",
            ]

            _py_mm_cache = {}

            def _python_major_minor(py_path):
                key = str(py_path or "")
                if key in _py_mm_cache:
                    return _py_mm_cache[key]
                mm = None
                try:
                    r = subprocess.run(
                        [py_path, "-c", "import sys;print(f'{sys.version_info[0]}.{sys.version_info[1]}')"],
                        capture_output=True,
                        text=True,
                        timeout=4,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    s = (r.stdout or "").strip()
                    m = re.match(r"^\s*(\d+)\.(\d+)\s*$", s)
                    if r.returncode == 0 and m:
                        mm = (int(m.group(1)), int(m.group(2)))
                except Exception:
                    mm = None
                _py_mm_cache[key] = mm
                return mm

            def _pick_python() -> str:
                forced = os.environ.get("AMIR_PYTHON")
                is_frozen = bool(getattr(sys, "frozen", False))

                # Source runs keep honoring AMIR_PYTHON override.
                if not is_frozen:
                    return forced or sys.executable

                # Frozen mode: still prefer explicit runtime override if it exists.
                if forced:
                    if os.path.exists(forced):
                        return forced
                    print(f"[WARN] AMIR_PYTHON not found: {forced}")

                existing = []
                for c in _default_venv_candidates:
                    if c and os.path.exists(c):
                        existing.append(c)

                # Last resort: first available candidate, then sys.executable.
                if existing:
                    return existing[0]
                return sys.executable

            if IDENTIFIER_ROUTER_ENABLED and router_batches:
                self._set_stage(3, STAGES[3], badge="[identifier]")
                py_for_router = _pick_python()
                for rb in router_batches:
                    rb_badge = f"[Set {int(rb.get('set_index') or 0)}/{int(rb.get('total_sets') or total_sets)} identifier]"
                    self._set_stage(3, STAGES[3], badge=rb_badge)
                    rb_row_ids = [int(x) for x in rb.get("row_ids", [])]
                    rb_subject = str(rb.get("subject") or "")
                    rb_location = str(rb.get("location") or "")
                    rb_folder = str(rb.get("folder") or "")
                    rb_set_index = int(rb.get("set_index") or 0)

                    try:
                        _run_identifier_router_for_review_rows(
                            db_path=DB_PATH,
                            table=TABLE_NAME,
                            row_ids=rb_row_ids,
                            subject_hint=rb_subject,
                            location_hint=rb_location,
                            folder_hint=rb_folder,
                            set_index=rb_set_index,
                            python_path=py_for_router,
                        )
                    except Exception as ex:
                        if IDENTIFIER_ROUTER_FAIL_HARD:
                            raise
                        msg = (
                            f"Identifier router exception ignored for set {rb_set_index}: "
                            f"{type(ex).__name__}: {ex}"
                        )
                        print(f"[WARN] {msg}")
                        _identifier_router_manual_subject_fallback_to_db(
                            db_path=DB_PATH,
                            table=TABLE_NAME,
                            row_ids=rb_row_ids,
                            subject_hint=rb_subject,
                            location_hint=rb_location,
                            folder_hint=rb_folder,
                            set_index=rb_set_index,
                            reason=msg,
                            only_missing=True,
                        )
            elif not IDENTIFIER_ROUTER_ENABLED:
                print("[SKIP] Identifier router disabled by IDENTIFIER_ROUTER_ENABLED=0.")

            def _child_cwd_for_script(script_path: str) -> str:
                if not getattr(sys, "frozen", False):
                    return os.path.dirname(script_path)
                try:
                    mei = os.path.normcase(os.path.normpath(str(getattr(sys, "_MEIPASS", "") or "")))
                    sp = os.path.normcase(os.path.normpath(str(script_path or "")))
                    if mei and sp.startswith(mei):
                        return APP_DIR
                except Exception:
                    pass
                return os.path.dirname(script_path) or APP_DIR

            # Start Ollama warmup while scoring runs, so caption prefill starts faster.
            ollama_warm_thread: threading.Thread | None = None
            if OLLAMA_WARM_ON_SCORING:
                def _warm_worker():
                    try:
                        t0 = time.time()
                        print("[INFO] Ollama preflight: checking service for caption stage...")
                        if not _ensure_ollama_running():
                            print(f"[WARN] Ollama not responding on {OLLAMA_HOST}:{OLLAMA_PORT}.")
                            return
                        if not _ensure_ollama_model(OLLAMA_MODEL_CAPTION):
                            print(
                                f"[WARN] Caption model '{OLLAMA_MODEL_CAPTION}' is not installed. "
                                f"Run: ollama pull {OLLAMA_MODEL_CAPTION}"
                            )
                            return
                        ok, msg = _warm_ollama_model(OLLAMA_MODEL_CAPTION)
                        dt = time.time() - t0
                        if ok:
                            print(
                                f"[INFO] Ollama warmup ready for '{OLLAMA_MODEL_CAPTION}' "
                                f"in {dt:.1f}s (keep_alive={OLLAMA_WARM_KEEP_ALIVE})."
                            )
                        else:
                            print(f"[WARN] Ollama warmup failed for '{OLLAMA_MODEL_CAPTION}': {msg}")
                    except Exception as _e:
                        print(f"[WARN] Ollama warmup exception: {type(_e).__name__}: {_e}")

                ollama_warm_thread = threading.Thread(target=_warm_worker, daemon=True)
                ollama_warm_thread.start()

            if score_total > 0:
                self._set_stage(4, STAGES[4])
                os.environ["AMIR_REVIEW_DB"] = DB_PATH
                # Strict scoring is mandatory: no safe fallback / no pyiqa skip.
                os.environ["AMIR_SCORE_SAFE_MODE"] = "0"
                os.environ["AMIR_SCORE_REQUIRE_PYIQA"] = "1"
                os.environ["AMIR_SCORE_FORCE_RUN"] = "1" if SCORE_FORCE_RUN else "0"
                script_score = _prepare_external_script("batch_image_quality_score.py")

                def _mark_scoring_failed(reason: str):
                    try:
                        if not inserted_ids:
                            return
                        with sqlite3.connect(DB_PATH) as _c:
                            _c.executemany(
                                f"UPDATE {TABLE_NAME} SET QC_Status=?, Review_Status=? WHERE id=?",
                                [("ScoringFailed", "Error", i) for i in inserted_ids],
                            )
                            _c.commit()
                    except Exception:
                        pass

                def _clear_scoring_failed_flag_if_any():
                    try:
                        if not inserted_ids:
                            return
                        with sqlite3.connect(DB_PATH) as _c:
                            _c.executemany(
                                f"""
                                UPDATE {TABLE_NAME}
                                   SET QC_Status =
                                         CASE WHEN QC_Status='ScoringFailed' THEN 'NA'
                                              ELSE QC_Status END,
                                       Review_Status =
                                         CASE WHEN COALESCE(Review_Status,'')='Error' THEN 'Queued'
                                              ELSE Review_Status END
                                 WHERE id=?
                                """,
                                [(i,) for i in inserted_ids],
                            )
                            _c.commit()
                    except Exception:
                        pass

                score_ok = False
                last_reason = ""
                py_score = _pick_python()
                print(f"[INFO] Score runtime python: {py_score} (ver={_python_major_minor(py_score)})")

                for attempt in (1, 2):
                    self._runlog("SCORE_START", f"attempt={attempt}")
                    try:
                        if not os.path.exists(script_score):
                            raise FileNotFoundError(f"Missing scoring script: {script_score}")

                        score_cmd = [py_score, "-u", script_score]
                        if SESSION_SCOPE_ONLY and session_scope_ids:
                            score_cmd += ["--id-list", ",".join([str(x) for x in session_scope_ids])]

                        rc, ok_n, fail_n, tail = _stream_cmd_with_ok_counter(
                            score_cmd,
                            cwd=_child_cwd_for_script(script_score),
                            total=score_total,
                            stage_num_for_ui=4,
                        )

                        if rc == 0:
                            score_ok = True
                            self._runlog("SCORE_OK", f"attempt={attempt}")
                            _clear_scoring_failed_flag_if_any()
                            break

                        err = (tail or "").strip()
                        if err:
                            err = err[-1500:]
                        raise RuntimeError(f"returncode={rc} stderr={err or '(empty)'}")

                    except Exception as e:
                        last_reason = f"{type(e).__name__}: {e}"
                        print(f"[ERROR] Scoring failed (attempt {attempt}/2): {last_reason}")
                        self._runlog("SCORE_FAIL", f"attempt={attempt} {last_reason}")

                        _mark_scoring_failed(last_reason)

                        if attempt == 1:
                            retry = self._ui_ask_retry_cancel(
                                "Scoring failed",
                                "Scoring failed and the run is NOT valid.\n\n"
                                f"Reason:\n{last_reason}\n\n"
                                "Choose Retry to try scoring one more time.\n"
                                "Choose Cancel to abort and rollback everything.",
                            )
                            if not retry:
                                suppress_fail_dialog = True
                                exit_code = 2
                                self._ui_showerror_wait(
                                    "Scoring aborted",
                                    "Aborting now.\n\nRollback will restore files and remove inserted rows.\n\n"
                                    f"Reason:\n{last_reason}",
                                )
                                raise RuntimeError(f"Scoring aborted: {last_reason}")
                            continue

                        suppress_fail_dialog = True
                        exit_code = 2
                        self._ui_showerror_wait(
                            "Scoring failed twice",
                            "Scoring failed twice.\n\nRollback will restore files and remove inserted rows.\n\n"
                            "Next action: fix scoring and rerun the batch.\n\n"
                            f"Reason:\n{last_reason}",
                        )
                        raise RuntimeError(f"Scoring failed twice: {last_reason}")

                if not score_ok:
                    suppress_fail_dialog = True
                    exit_code = 2
                    raise RuntimeError(f"Scoring failed: {last_reason}")
            else:
                self._set_stage(4, STAGES[4], badge="[SKIP]")
                print("[SKIP] Scoring skipped (no queued session rows to score).")

            
            # Stage: Resize images for Ollama (temp)
            self._set_stage(5, STAGES[5])

            ollama_run_dir = ""
            resize_total = 0
            resize_ok = 0
            resize_fail = 0

            try:
                ts = time.strftime("%Y%m%d_%H%M%S")
                ollama_root = os.path.join(DATA_DIR, "ollama_tmp")
                ollama_run_dir = os.path.join(ollama_root, f"run_{ts}")
                os.makedirs(ollama_run_dir, exist_ok=True)

                with sqlite3.connect(DB_PATH) as _c:
                    _c.row_factory = sqlite3.Row
                    _cur = _c.cursor()

                    # Only rows that are still queued and either missing ollama_path or pointing to a missing file
                    sql_rows = (
                        f"SELECT id, Path, File_Name, Original_File_Name, ollama_path "
                        f"FROM {TABLE_NAME} "
                        "WHERE COALESCE(Review_Status,'')='Queued'"
                    )
                    row_params: list[object] = []
                    if SESSION_SCOPE_ONLY:
                        if prefill_scope_ids:
                            sql_rows += f" AND id IN ({','.join(['?'] * len(prefill_scope_ids))})"
                            row_params.extend(prefill_scope_ids)
                        else:
                            sql_rows += " AND 1=0"
                    _cur.execute(sql_rows, row_params)
                    rows = _cur.fetchall()
                    todo = []
                    for r in rows:
                        op = str(r["ollama_path"] or "").strip()
                        if not op or (op and not os.path.exists(op)):
                            todo.append(r)

                    resize_total = len(todo)

                    if resize_total <= 0:
                        self._set_stage(5, STAGES[5], badge="[SKIP]")
                        print("[SKIP] Resize skipped (ollama_path already present).")
                    else:
                        print(f"[INFO] Resizing {resize_total} queued images for Ollama into: {ollama_run_dir}")

                        for i, r in enumerate(todo, start=1):
                            rid = int(r["id"])
                            src = str(r["Path"] or "").strip()
                            filename = str((r["Original_File_Name"] if "Original_File_Name" in r.keys() else None) or (r["File_Name"] if "File_Name" in r.keys() else None) or f"id_{rid}.jpg")

                            self._set_stage(
                                5,
                                STAGES[5],
                                badge=f"[{(resize_ok + resize_fail)}/{resize_total}] ok={resize_ok} fail={resize_fail}",
                                progress=(resize_ok + resize_fail) / max(1, resize_total),
                            )

                            try:
                                if not src or not os.path.exists(src):
                                    raise FileNotFoundError(src or "(empty path)")

                                base = os.path.basename(filename)
                                stem, _ext = os.path.splitext(base)
                                out_name = f"{rid}_{stem}.jpg"
                                dst = os.path.join(ollama_run_dir, out_name)

                                # Use context managers to release decoder buffers immediately.
                                with Image.open(src) as _src_img:
                                    img = _src_img.convert("RGB")
                                img.thumbnail((THUMB_MAX, THUMB_MAX), Image.LANCZOS)
                                img.save(dst, format="JPEG", quality=85, optimize=False)

                                _cur.execute(
                                    f"UPDATE {TABLE_NAME} SET ollama_path=? WHERE id=?",
                                    (dst, rid),
                                )
                                _c.commit()

                                resize_ok += 1
                                print(f"[OK] id={rid} file={os.path.basename(src)} resized={os.path.basename(dst)}")
                                self._set_stage(
                                    5,
                                    STAGES[5],
                                    badge=f"[{(resize_ok + resize_fail)}/{resize_total}] ok={resize_ok} fail={resize_fail}",
                                    progress=(resize_ok + resize_fail) / max(1, resize_total),
                                )

                            except Exception as ex:
                                resize_fail += 1
                                try:
                                    _cur.execute(
                                        f"UPDATE {TABLE_NAME} SET ollama_path=NULL, Review_Status='Error', QC_Status='ResizeFailed' WHERE id=?",
                                        (rid,),
                                    )
                                    _c.commit()
                                except Exception:
                                    pass
                                print(f"[FAIL] id={rid} file={os.path.basename(src)} reason={type(ex).__name__}: {ex}")
                                self._set_stage(
                                    5,
                                    STAGES[5],
                                    badge=f"[{(resize_ok + resize_fail)}/{resize_total}] ok={resize_ok} fail={resize_fail}",
                                    progress=(resize_ok + resize_fail) / max(1, resize_total),
                                )

                        if RESIZE_FAIL_ON_ANY and resize_fail > 0:
                            raise RuntimeError(
                                f"Resize stage had failures: ok={resize_ok} fail={resize_fail} "
                                "(RESIZE_FAIL_ON_ANY=1)"
                            )

            except Exception as ex:
                print(f"[WARN] Resize step failed: {type(ex).__name__}: {ex}")


            if SERIES_VERSIONING_ENABLED:
                try:
                    series_script = SERIES_VERSIONING_SCRIPT
                    if not os.path.exists(series_script):
                        series_script = _prepare_external_script(os.path.join("scripts", "series_versioning.py"))

                    if not os.path.exists(series_script):
                        print(f"[WARN] Generic series analyzer missing: {series_script}")
                    else:
                        series_scope_ids: list[int] = []
                        if SESSION_SCOPE_ONLY:
                            series_scope_ids = [int(x) for x in prefill_scope_ids if int(x) > 0]
                            if not series_scope_ids:
                                print("[SERIES] Skipped generic versioning: no session rows.")
                        if (not SESSION_SCOPE_ONLY) or series_scope_ids:
                            series_args = [
                                "--db", DB_PATH,
                                "--table", TABLE_NAME,
                                "--status", "Queued",
                            ]
                            if series_scope_ids:
                                series_args += ["--id-list", ",".join(str(x) for x in series_scope_ids)]
                            if SERIES_VERSIONING_SPLIT_WITHIN_SET:
                                series_args.append("--split-within-set")

                            py = _pick_python()
                            print("[SERIES] Running generic series/versioning analyzer before metadata generation...")
                            rc_series, _ok_series, _fail_series, tail_series = _stream_cmd_with_ok_counter(
                                [py, "-u", series_script] + series_args,
                                cwd=_child_cwd_for_script(series_script),
                                total=1,
                                stage_num_for_ui=5,
                                badge_prefix="series",
                                idle_timeout_sec=90,
                                hard_timeout_sec=900,
                            )
                            if rc_series != 0:
                                print(
                                    f"[WARN] Generic series analyzer returned {rc_series}; "
                                    f"metadata will continue without fresh series fields. tail={tail_series[-800:]}"
                                )
                except Exception as ex:
                    print(f"[WARN] Generic series analyzer failed: {type(ex).__name__}: {ex}")


            # Stage: Caption/Keywords prefill (Ollama)
            self._set_stage(6, STAGES[6])

            # Ensure warmup has a chance to complete before first caption request.
            if ollama_warm_thread and ollama_warm_thread.is_alive():
                try:
                    ollama_warm_thread.join(timeout=8)
                except Exception:
                    pass

            # Hard preflight for caption stage.
            if not _ensure_ollama_running():
                raise RuntimeError(f"Ollama is not responding on {OLLAMA_HOST}:{OLLAMA_PORT}.")
            if not _ensure_ollama_model(OLLAMA_MODEL_CAPTION):
                raise RuntimeError(
                    f"Caption model '{OLLAMA_MODEL_CAPTION}' is not installed. "
                    f"Run: ollama pull {OLLAMA_MODEL_CAPTION}"
                )

            def _is_native_prefill_crash(rc: int) -> bool:
                try:
                    rc_i = int(rc)
                except Exception:
                    return False
                signed = rc_i - 0x100000000 if rc_i > 0x7FFFFFFF else rc_i
                crash_codes = {
                    # access violation
                    3221225477,
                    -1073741819,
                    # heap corruption
                    3221226356,
                    -1073740940,
                    # stack buffer overrun
                    3221226505,
                    -1073740791,
                }
                return rc_i in crash_codes or signed in crash_codes

            def _query_prefill_ids(limit: int = 0) -> list[int]:
                try:
                    with sqlite3.connect(DB_PATH) as _c:
                        _cur = _c.cursor()
                        sql_q = (
                            f"SELECT id FROM {TABLE_NAME} "
                            "WHERE COALESCE(Review_Status,'')='Queued' "
                            "AND COALESCE(ollama_path,'')<>''"
                        )
                        q_params: list[object] = []
                        if SESSION_SCOPE_ONLY:
                            if prefill_scope_ids:
                                sql_q += f" AND id IN ({','.join(['?'] * len(prefill_scope_ids))})"
                                q_params.extend(prefill_scope_ids)
                            else:
                                sql_q += " AND 1=0"
                        sql_q += " ORDER BY id"
                        if int(limit) > 0:
                            sql_q += f" LIMIT {int(limit)}"
                        _cur.execute(sql_q, q_params)
                        return [int(r[0]) for r in _cur.fetchall() if int(r[0]) > 0]
                except Exception as _e:
                    print(f"[WARN] Could not query prefill rows: {_e}")
                    return []

            def _quarantine_prefill_row(row_id: int, rc: int, err: str) -> bool:
                """Mark one repeatedly-crashing prefill row as Error so the batch can continue."""
                try:
                    rid = int(row_id)
                except Exception:
                    return False
                try:
                    with sqlite3.connect(DB_PATH) as _c:
                        _cur = _c.cursor()
                        _cur.execute(
                            f"UPDATE {TABLE_NAME} "
                            "SET Review_Status='Error', QC_Status='PrefillNativeCrash' "
                            "WHERE id=? AND COALESCE(Review_Status,'')='Queued'",
                            (rid,),
                        )
                        _changed = int(_cur.rowcount or 0)
                        _c.commit()
                    if _changed > 0:
                        _tail = (err or "").strip()
                        if _tail:
                            _tail = _tail[-220:]
                        print(
                            f"[WARN] Quarantined row id={rid} after native prefill crash rc={rc}. "
                            f"Marked Review_Status=Error QC_Status=PrefillNativeCrash "
                            f"tail={_tail or '(empty)'}"
                        )
                        return True
                except Exception as _e:
                    print(f"[WARN] Could not quarantine crashing prefill row id={rid}: {_e}")
                return False

            queued_ids = _query_prefill_ids(0)
            queued_count = len(queued_ids)

            if queued_count <= 0:
                print("[SKIP] No queued rows to prefill.")
            else:
                script_prefill = _prepare_external_script("caption_review_local.py")
                if not os.path.exists(script_prefill):
                    raise RuntimeError(f"Missing prefill script: {script_prefill}")
                else:
                    py = _pick_python()
                    print(f"[INFO] Prefill runtime python: {py}")

                    prefill_args_base = [
                        "--db", DB_PATH,
                        "--table", TABLE_NAME,

                        # Status handling
                        "--status-col", "Review_Status",
                        "--status-queued", "Queued",
                        "--status-done", "Pending",

                        # Use resized temp images for Ollama
                        "--path-col", "ollama_path",
                        "--fallback-path-col", "Path",

                        # Ollama connection
                        "--endpoint", f"http://{OLLAMA_HOST}:{OLLAMA_PORT}/api/generate",

                        # Model + runtime
                        "--model", OLLAMA_MODEL_CAPTION,
                        "--timeout", str(CAPTION_TIMEOUT_SEC),
                        "--image-max-side", str(THUMB_MAX),
                        "--image-quality", "85",

                        # Output quality/uniqueness
                        "--keywords-n", str(CAPTION_KEYWORDS_N),
                        "--prefix-words", str(CAPTION_PREFIX_WORDS),
                        "--series-large-threshold", str(CAPTION_SERIES_LARGE_THRESHOLD),
                        "--max-tries", str(CAPTION_MAX_TRIES),
                        "--rewrite-max-passes", str(CAPTION_REWRITE_MAX_PASSES),
                        "--quality-min-score", str(CAPTION_QUALITY_MIN_SCORE),

                        # Extra options
                        "--ollama-opts", json.dumps(OLLAMA_OPTS),
                        "--overwrite",
                        "--no-tqdm",
                    ]

                    fallback_model = ""
                    fallback_tries = max(1, int(CAPTION_FALLBACK_MAX_TRIES))
                    fallback_enabled = False
                    if OLLAMA_MODEL_CAPTION_FALLBACK and OLLAMA_MODEL_CAPTION_FALLBACK != OLLAMA_MODEL_CAPTION:
                        fallback_model = str(OLLAMA_MODEL_CAPTION_FALLBACK).strip()
                        fallback_enabled = bool(fallback_model)

                    if CAPTION_REWRITE_WEAK:
                        prefill_args_base.append("--rewrite-weak")

                    if DEFAULT_TERMS_DB and os.path.exists(DEFAULT_TERMS_DB):
                        prefill_args_base += [
                            "--terms-db", DEFAULT_TERMS_DB,
                            "--terms-table", CAPTION_TERMS_TABLE,
                            "--terms-min-precision", str(CAPTION_TERMS_MIN_PRECISION),
                        ]

                    if OLLAMA_MODEL_CAPTION_FALLBACK and OLLAMA_MODEL_CAPTION_FALLBACK != OLLAMA_MODEL_CAPTION:
                        print(
                            f"[INFO] Prefilling captions via '{OLLAMA_MODEL_CAPTION}' "
                            f"(fallback on fail: '{OLLAMA_MODEL_CAPTION_FALLBACK}') for {queued_count} queued rows..."
                        )
                    else:
                        print(f"[INFO] Prefilling captions via '{OLLAMA_MODEL_CAPTION}' for {queued_count} queued rows...")
                    try:
                        chunk_size = max(0, int(CAPTION_PREFILL_CHUNK_SIZE))
                        crash_retry_budget = max(0, int(CAPTION_NATIVE_CRASH_RETRIES))
                        crash_retry_used = 0
                        stalled_crashes = 0
                        last_chunk_first_id = -1
                        ok_total = 0
                        fail_total = 0
                        t_prefill = time.time()
                        prefill_total_chunks = (
                            max(1, int(math.ceil(float(queued_count) / float(chunk_size))))
                            if chunk_size > 0
                            else 1
                        )

                        while True:
                            remaining_ids = _query_prefill_ids(0)
                            if not remaining_ids:
                                break

                            run_ids = remaining_ids if chunk_size <= 0 else remaining_ids[:chunk_size]
                            if not run_ids:
                                break

                            done_before = max(0, queued_count - len(remaining_ids))
                            chunk_idx = (
                                (done_before // chunk_size) + 1
                                if chunk_size > 0
                                else 1
                            )
                            chunk_idx = max(1, min(prefill_total_chunks, int(chunk_idx)))

                            if chunk_size > 0 and len(remaining_ids) > len(run_ids):
                                print(
                                    f"[INFO] Prefill chunk {chunk_idx}/{prefill_total_chunks}: {len(run_ids)} rows "
                                    f"(remaining={len(remaining_ids)})"
                                )

                            first_id = int(run_ids[0])
                            run_args = list(prefill_args_base)
                            if fallback_enabled:
                                run_args += [
                                    "--fallback-model", fallback_model,
                                    "--fallback-max-tries", str(fallback_tries),
                                ]
                            run_args += ["--id-list", ",".join([str(x) for x in run_ids])]

                            rc, ok_n, fail_n, tail = _stream_cmd_with_ok_counter(
                                [py, "-u", script_prefill] + run_args,
                                cwd=_child_cwd_for_script(script_prefill),
                                total=len(run_ids),
                                stage_num_for_ui=6,
                                badge_prefix=f"batch={chunk_idx}/{prefill_total_chunks}",
                                overall_total=queued_count,
                                overall_done_before=done_before,
                                overall_ok_before=ok_total,
                                overall_fail_before=fail_total,
                                # Give first-run model/cache warmup more room before treating it
                                # like a crashed subprocess.
                                idle_timeout_sec=max(
                                    CAPTION_PREFILL_IDLE_TIMEOUT_SEC,
                                    300 if (done_before == 0 and chunk_idx == 1) else 0,
                                ),
                                hard_timeout_sec=CAPTION_PREFILL_HARD_TIMEOUT_SEC,
                            )

                            ok_total += int(ok_n)
                            fail_total += int(fail_n)

                            # Normalize UI to global prefill progress across all chunks.
                            remaining_now = len(_query_prefill_ids(0))
                            done_now = max(0, queued_count - remaining_now)
                            elapsed_now = max(0.001, time.time() - t_prefill)
                            rate_now = done_now / elapsed_now if done_now > 0 else 0.0
                            eta_now = (remaining_now / rate_now) if rate_now > 0 else 0.0
                            try:
                                self._set_stage(
                                    6,
                                    STAGES[6],
                                    badge=(
                                        f"batch={chunk_idx}/{prefill_total_chunks} "
                                        f"[{done_now}/{queued_count}] ok={ok_total} fail={fail_total} "
                                        f"{rate_now:.2f}/img eta={self._fmt_hms(eta_now)}"
                                    ),
                                    progress=done_now / max(1, queued_count),
                                )
                            except Exception:
                                pass

                            if rc == 0:
                                stalled_crashes = 0
                                last_chunk_first_id = -1
                                continue

                            err = (tail or "").strip()
                            if err:
                                err = err[-1500:]

                            # caption_review_local.py returns rc=1 when a chunk completed
                            # but had row-level failures. That should not abort the pipeline
                            # unless strict fail mode is explicitly enabled later.
                            chunk_completed_with_row_failures = (
                                rc == 1
                                and (ok_n + fail_n) > 0
                                and ("[DONE]" in (tail or "") or fail_n > 0)
                            )
                            if chunk_completed_with_row_failures:
                                stalled_crashes = 0
                                last_chunk_first_id = -1
                                print(
                                    f"[WARN] Prefill chunk had row failures (ok={ok_n} fail={fail_n}); "
                                    "continuing to next chunk."
                                )
                                continue

                            if _is_native_prefill_crash(rc):
                                # If fallback is present and native crashes happen, it is often
                                # safer to disable fallback and continue with primary only.
                                err_low = (err or "").lower()
                                if fallback_enabled and ("trying fallback" in err_low or "fallback" in err_low):
                                    fallback_enabled = False
                                    print(
                                        f"[WARN] Disabling fallback model '{fallback_model}' after native crash "
                                        f"(rc={rc}). Continuing with primary model only."
                                    )

                                if crash_retry_used < crash_retry_budget:
                                    crash_retry_used += 1
                                    if ok_n == 0 and fail_n == 0 and first_id == last_chunk_first_id:
                                        stalled_crashes += 1
                                    else:
                                        stalled_crashes = 0
                                    last_chunk_first_id = first_id

                                    print(
                                        f"[WARN] Prefill subprocess crashed (rc={rc}) "
                                        f"on chunk starting id={first_id}. "
                                        f"Auto-retry {crash_retry_used}/{crash_retry_budget}."
                                    )
                                    if stalled_crashes >= 3:
                                        if _quarantine_prefill_row(first_id, rc, err):
                                            fail_total += 1
                                            stalled_crashes = 0
                                            last_chunk_first_id = -1
                                            continue
                                        raise RuntimeError(
                                            f"Prefill subprocess repeatedly crashed before any progress "
                                            f"(rc={rc}) tail={err or '(empty)'}"
                                        )
                                    time.sleep(min(8, 1 + crash_retry_used))
                                    continue

                                # If we already made progress, keep completed rows and continue workflow.
                                if ok_total > 0:
                                    print(
                                        f"[WARN] Prefill stopped after repeated native crashes "
                                        f"(rc={rc}). Keeping completed rows and continuing."
                                    )
                                    break
                                if _quarantine_prefill_row(first_id, rc, err):
                                    fail_total += 1
                                    stalled_crashes = 0
                                    last_chunk_first_id = -1
                                    continue

                            if _amir_repair_prefill_rows() <= 0:
                                raise RuntimeError(
                                    f"Prefill script returned non-zero ({rc}) tail={err or '(empty)'}"
                                )
                            rc = 0
                            err = ""

                        print(
                            f"[INFO] Prefill summary: queued={queued_count} ok={ok_total} "
                            f"fail={fail_total} retries={crash_retry_used}"
                        )
                        remaining_after = len(_query_prefill_ids(0))
                        if remaining_after > 0:
                            raise RuntimeError(
                                f"Prefill incomplete: {remaining_after} queued row(s) still need captions. "
                                "Metadata quality was not run on placeholder rows; run Start Batch again after fixing prefill."
                            )

                        if CAPTION_FAIL_ON_ROW_ERRORS and fail_total > 0:
                            raise RuntimeError(
                                f"Prefill completed with row failures: ok={ok_total} fail={fail_total} "
                                "(CAPTION_FAIL_ON_ROW_ERRORS=1)"
                            )

                        # Mark queued rows as Pending once they have real text
                        try:
                            with sqlite3.connect(DB_PATH) as _c:
                                sql_pending = (
                                    f"UPDATE {TABLE_NAME} SET Review_Status='Pending' "
                                    "WHERE COALESCE(Review_Status,'')='Queued' "
                                    "AND COALESCE(Caption,'')<>'' "
                                    "AND COALESCE(Keywords,'')<>'' "
                                    "AND COALESCE(alt_text,'')<>''"
                                )
                                pending_params: list[object] = []
                                if SESSION_SCOPE_ONLY:
                                    if prefill_scope_ids:
                                        sql_pending += f" AND id IN ({','.join(['?'] * len(prefill_scope_ids))})"
                                        pending_params.extend(prefill_scope_ids)
                                    else:
                                        sql_pending += " AND 1=0"
                                _c.execute(sql_pending, pending_params)
                                _c.commit()
                        except Exception:
                            pass

                        if PREFILL_QC_ENABLED:
                            try:
                                qc_scope_ids: list[int] | None = None
                                if SESSION_SCOPE_ONLY:
                                    qc_scope_ids = [int(x) for x in prefill_scope_ids if int(x) > 0]
                                prefill_qc_summary = _run_prefill_qc_scan(
                                    DB_PATH,
                                    TABLE_NAME,
                                    id_scope=qc_scope_ids,
                                )
                                dup_rows = int(prefill_qc_summary.get("duplicate_rows_total", 0) or 0)
                                suspicious_rows = int(prefill_qc_summary.get("suspicious_rows", 0) or 0)
                                if dup_rows <= 0:
                                    print("[QC] No duplicates found in pending prefill rows.")
                                else:
                                    print(
                                        "[QC] Duplicates found: "
                                        f"caption_groups={prefill_qc_summary.get('caption_dup_groups', 0)} "
                                        f"alt_groups={prefill_qc_summary.get('alt_dup_groups', 0)} "
                                        f"keyword_groups={prefill_qc_summary.get('keywords_dup_groups', 0)} "
                                        f"rows={dup_rows}"
                                    )
                                if suspicious_rows > 0:
                                    print(
                                        f"[QC] Suspicious rows auto-flagged={suspicious_rows} "
                                        f"sample_ids={prefill_qc_summary.get('sample_ids', [])}"
                                    )
                                print(
                                    f"[QC] Report written: {prefill_qc_summary.get('report_path', PREFILL_QC_REPORT_PATH)}"
                                )
                            except Exception as _qc_e:
                                print(f"[WARN] Prefill QC scan failed: {_qc_e}")

                    except Exception as _e:
                        raise RuntimeError(f"Prefill failed: {_e}")


            if METADATA_QUALITY_ENABLED:
                try:
                    metadata_script = METADATA_QUALITY_SCRIPT
                    if not os.path.exists(metadata_script):
                        # Source/PyInstaller fallback.
                        metadata_script = _prepare_external_script(os.path.join("scripts", "metadata_quality_production.py"))

                    if not os.path.exists(metadata_script):
                        raise RuntimeError(f"Missing metadata quality script: {metadata_script}")

                    py = _pick_python()
                    _amir_repair_prefill_rows()
                    # AMIR_EVIDENCE_PIPELINE_METADATA_HOOK_START
                    try:
                        from metadata_evidence_pipeline import clean_pending_review_metadata as _amir_clean_pending_review_metadata
                        _amir_clean_pending_review_metadata(DB_PATH)
                    except Exception as _amir_evidence_metadata_error:
                        print(f"[WARN] Evidence metadata cleanup failed: {_amir_evidence_metadata_error}")
                    # AMIR_EVIDENCE_PIPELINE_METADATA_HOOK_END
                    _amir_run_metadata_auto_repair_loop(db_path=DB_PATH, py=py)
                    print("[INFO] Post-prefill metadata repair checked rows.")
                    print("[INFO] Running metadata quality production repair/gate...")
                    rc_mq, _ok_mq, _fail_mq, tail_mq = _stream_cmd_with_ok_counter(
                        [py, "-u", metadata_script, "--db", DB_PATH],
                        cwd=_child_cwd_for_script(metadata_script),
                        total=1,
                        stage_num_for_ui=6,
                        badge_prefix="metadata_quality",
                        idle_timeout_sec=METADATA_QUALITY_IDLE_TIMEOUT_SEC,
                        hard_timeout_sec=METADATA_QUALITY_HARD_TIMEOUT_SEC,
                    )

                    if rc_mq != 0:
                        raise RuntimeError(
                            "Metadata quality production run failed "
                            f"(rc={rc_mq}) tail={(tail_mq or '').strip()[-1500:] or '(empty)'}"
                        )

                    with sqlite3.connect(DB_PATH) as _mq_conn:
                        _mq_cur = _mq_conn.cursor()
                        _mq_cur.execute(
                            """
                            SELECT
                                COUNT(*) AS total_rows,
                                SUM(CASE WHEN COALESCE(accepted_for_upload, 0) = 1 THEN 1 ELSE 0 END) AS accepted_rows,
                                SUM(CASE WHEN COALESCE(overall_quality_status, '') = 'FAIL_BLOCKED' THEN 1 ELSE 0 END) AS blocked_rows
                            FROM metadata_quality
                            """
                        )
                        _mq_total, _mq_accepted, _mq_blocked = _mq_cur.fetchone()
                        print(
                            "[MQ] metadata_quality updated: "
                            f"rows={int(_mq_total or 0)} "
                            f"accepted={int(_mq_accepted or 0)} "
                            f"blocked={int(_mq_blocked or 0)}"
                        )
                        metadata_quality_summary = _parse_metadata_quality_summary(
                            tail_mq,
                            total_rows=int(_mq_total or 0),
                            accepted_rows=int(_mq_accepted or 0),
                            blocked_rows=int(_mq_blocked or 0),
                        )
                except Exception as _mq_e:
                    raise RuntimeError(f"Metadata quality stage failed: {_mq_e}")


        except Exception as ex:
            traceback.print_exc()
            msg = f"{type(ex).__name__}: {ex}"
            if not suppress_fail_dialog:
                self._ui(lambda m=msg: messagebox.showerror("Batch Failed", m))
            success = False

        finally:
            try:
                cleanup_runtime_artifacts(str(locals().get("ollama_run_dir", "") or ""))
            except Exception as _cleanup_e:
                print(f"[WARN] Runtime cleanup failed: {_cleanup_e}")

            def _rollback_session(reason: str):
                print(f"[WARN] {reason}. Rolling back this session.")

                # remove inserted DB rows and matching metadata_quality rows for THIS failed session only
                try:
                    removed_review = 0
                    removed_mq = 0

                    if inserted_ids or reserved_names:
                        with sqlite3.connect(DB_PATH) as conn2:
                            cur2 = conn2.cursor()

                            if inserted_ids:
                                placeholders = ",".join("?" for _ in inserted_ids)
                                cur2.execute(
                                    f"DELETE FROM {TABLE_NAME} WHERE id IN ({placeholders})",
                                    inserted_ids,
                                )
                                removed_review = int(cur2.rowcount or 0)

                            mq_names = [
                                str(name).strip()
                                for name in reserved_names
                                if str(name or "").strip()
                            ]

                            if mq_names:
                                placeholders = ",".join("?" for _ in mq_names)
                                cur2.execute(
                                    f"""
                                    DELETE FROM metadata_quality
                                    WHERE COALESCE(uploaded_to_mysql, 0) = 0
                                      AND revamp_id IS NULL
                                      AND revamp_File_Name IN ({placeholders})
                                    """,
                                    mq_names,
                                )
                                removed_mq = int(cur2.rowcount or 0)

                            conn2.commit()

                    if inserted_ids:
                        print(
                            f"[WARN] Removed {removed_review} inserted rows from {TABLE_NAME}."
                        )

                    if reserved_names:
                        print(
                            f"[WARN] Removed {removed_mq} failed-session rows from metadata_quality."
                        )

                except Exception as _e:
                    print(f"[WARN] Could not remove failed-session DB rows: {_e}")

                # restore moved files back to original folders
                try:
                    for _dst in moved:
                        _src = orig_paths.get(_dst)
                        if not _src or not os.path.exists(_dst):
                            continue

                        os.makedirs(os.path.dirname(_src), exist_ok=True)
                        _back_to = _src

                        if os.path.exists(_back_to):
                            _root, _ext = os.path.splitext(_back_to)
                            _n = 1
                            while os.path.exists(_back_to):
                                _back_to = f"{_root}_restored_{_n:03d}{_ext}"
                                _n += 1

                        shutil.move(_dst, _back_to)

                    if moved:
                        print(
                            f"[WARN] Restored {len(moved)} files to their original folders."
                        )
                except Exception as _e:
                    print(f"[WARN] Could not restore moved files: {_e}")

                # release reserved filenames
                try:
                    if reserved_names and os.path.exists(USED_NAMES):
                        with open(USED_NAMES, "r", encoding="utf-8") as _f:
                            _data = json.load(_f)
                        _drop_ci = {str(x).casefold() for x in reserved_names}

                        _bak = f"{USED_NAMES}.bak_{int(time.time())}"
                        shutil.copy2(USED_NAMES, _bak)
                        try:
                            _pat = f"{USED_NAMES}.bak_*"
                            _baks = [p for p in glob.glob(_pat) if os.path.isfile(p)]
                            _baks.sort(key=lambda p: os.path.getmtime(p), reverse=True)
                            for _old in _baks[20:]:
                                try:
                                    os.remove(_old)
                                except Exception:
                                    pass
                        except Exception:
                            pass

                        _removed = 0
                        if isinstance(_data, list):
                            _orig = set(_data)
                            _data = [x for x in _data if str(x).casefold() not in _drop_ci]
                            _removed = len(_orig) - len(set(_data))
                        elif isinstance(_data, dict):
                            _new = {}
                            for _k, _v in _data.items():
                                if str(_k).casefold() in _drop_ci or str(_v).casefold() in _drop_ci:
                                    _removed += 1
                                    continue
                                _new[_k] = _v
                            _data = _new

                        with open(USED_NAMES, "w", encoding="utf-8") as _f:
                            json.dump(_data, _f, indent=2, ensure_ascii=False)

                        if _removed:
                            print(
                                f"[WARN] Released {_removed} reserved filenames from used_filenames.json."
                            )
                except Exception as _e:
                    print(f"[WARN] Could not update used_filenames.json: {_e}")

                self._ui(lambda: self.start_btn.configure(state="normal"))

            if not success:
                _rollback_session("Pipeline failed")
                cleanup_runtime_artifacts()
                self._save_session_state()
            else:
                # success: open editor on UI thread
                def _open_editor():
                    try:
                        # Do not call _set_stage here, it schedules after() callbacks.
                        try:
                            print(f"[STAGE 7/{TOTAL_STAGES}] {STAGES[7]}    elapsed {self._fmt_hms(time.time() - (self._pipeline_t0 or time.time()))} | eta 00:00")
                        except Exception:
                            pass

                        try:
                            if metadata_quality_summary:
                                _mq_msg = _format_metadata_quality_message(metadata_quality_summary)
                                if _mq_msg:
                                    messagebox.showinfo("Metadata Quality Summary", _mq_msg)
                            elif prefill_qc_summary:
                                _qc_msg = _format_prefill_qc_message(prefill_qc_summary)
                                if _qc_msg:
                                    messagebox.showinfo("Prefill QC Summary", _qc_msg)
                        except Exception:
                            pass

                        os.environ["AMIR_REVIEW_DB"] = DB_PATH

                        # Stop any new UI scheduling, and cancel everything already queued
                        self._ui_disabled = True

                        try:
                            ids = self.root.tk.call("after", "info")
                            for aid in ids:
                                try:
                                    self.root.after_cancel(aid)
                                except Exception:
                                    pass
                        except Exception:
                            pass

                        # Hide and close the multiset window cleanly
                        try:
                            self.root.withdraw()
                            self.root.update_idletasks()
                        except Exception:
                            pass

                        try:
                            self.root.destroy()
                        except Exception:
                            pass

                        _script3 = resource_path("review_editor.py")

                        if getattr(sys, "frozen", False):
                            import runpy
                            runpy.run_path(_script3, run_name="__main__")
                            cleanup_runtime_artifacts()
                            self._clear_session_state()
                            print("[INFO] Review/editor closed.")
                            _shutdown_ollama_on_run_end()
                            return

                        if os.environ.get("AMIR_TRACE_SKIP_EDITOR") == "1":
                            self._clear_session_state()
                            print("[TRACE] Skipping review editor (AMIR_TRACE_SKIP_EDITOR=1).")
                            print("[INFO] Review/editor closed.")
                            _shutdown_ollama_on_run_end()
                            return

                        py_editor = os.environ.get("AMIR_PYTHON") or sys.executable
                        res = subprocess.run([py_editor, _script3], check=False)

                        if res.returncode != 0:
                            raise RuntimeError(f"review_editor failed with returncode={res.returncode}")

                        cleanup_runtime_artifacts()
                        self._clear_session_state()
                        print("[INFO] Review/editor closed.")
                        _shutdown_ollama_on_run_end()

                    except Exception as _ex2:
                        traceback.print_exc()

                        # UI is probably gone, so only best-effort dialog
                        try:
                            messagebox.showerror(
                                "Batch Failed",
                                "Review editor failed. Rolling back everything.\n\n"
                                f"{type(_ex2).__name__}: {_ex2}",
                            )
                        except Exception:
                            pass

                        threading.Thread(
                            target=_rollback_session,
                            args=("Review editor failed",),
                            daemon=True,
                        ).start()

                self._ui(_open_editor)

    def _subject_get(self) -> str:
        try:
            s = self.subject_txt.get("1.0", "end-1c")
        except Exception:
            s = self.subject_var.get() or ""
        return (s or "").replace("\n", " ").replace("_", " ").strip()

    def _subject_set(self, s: str):
        s = _title_case_subject_input_text((s or "").replace("\n", " ").strip())
        try:
            self.subject_var.set(s)
        except Exception:
            pass

        self.subject_txt.delete("1.0", "end")
        self.subject_txt.insert("1.0", s)
        self._subject_last_spell_text = None
        self._subject_spellcheck_update()

    def _on_subject_keyrelease(self, _ev=None):
        self._subject_apply_title_case()
        self._schedule_subject_spellcheck(delay_ms=120)

    def _subject_apply_title_case(self):
        if getattr(self, "_subject_internal_edit", False):
            return
        try:
            raw = self.subject_txt.get("1.0", "end-1c")
            insert_off = int(self.subject_txt.count("1.0", "insert", "chars")[0])
        except Exception:
            return

        titled = _title_case_subject_input_text(raw)
        if titled != raw:
            try:
                self._subject_internal_edit = True
                self.subject_txt.delete("1.0", "end")
                self.subject_txt.insert("1.0", titled)
                insert_off = max(0, min(insert_off, len(titled)))
                self.subject_txt.mark_set("insert", f"1.0+{insert_off}c")
            except Exception:
                pass
            finally:
                self._subject_internal_edit = False

        try:
            self.subject_var.set((titled or "").replace("\n", " ").replace("_", " ").strip())
        except Exception:
            pass

    def _schedule_subject_spellcheck(self, delay_ms: int = 100):
        try:
            if self._subject_spell_after_id is not None:
                self.root.after_cancel(self._subject_spell_after_id)
        except Exception:
            pass
        try:
            self._subject_spell_after_id = self.root.after(
                max(0, int(delay_ms)),
                self._subject_spellcheck_update,
            )
        except Exception:
            self._subject_spell_after_id = None

    def _schedule_location_spellcheck(self, delay_ms: int = 100):
        try:
            if self._location_spell_after_id is not None:
                self.root.after_cancel(self._location_spell_after_id)
        except Exception:
            pass
        try:
            self._location_spell_after_id = self.root.after(
                max(0, int(delay_ms)),
                self._location_spellcheck_update,
            )
        except Exception:
            self._location_spell_after_id = None

    def _refresh_spellcheck_status(self):
        try:
            ok, reason = spellcheck_status(DATA_DIR)
            if ok:
                self.spell_warn_lbl.configure(text="Spellcheck: ON", foreground="#2a7a2a")
            else:
                self.spell_warn_lbl.configure(
                    text=f"Spellcheck: OFF ({reason})", foreground="#c00000"
                )
                self._runlog("SPELLCHECK_OFF", reason)
        except Exception:
            pass

    def _on_subject_change(self, _ev=None):
        self._subject_apply_title_case()
        s = self._subject_get()
        self.subject_var.set(s)
        self._subject_last_spell_text = None
        self._subject_spellcheck_update()

    def _subject_spellcheck_update(self):
        self._subject_spell_after_id = None
        try:
            self.subject_txt.tag_remove("misspell", "1.0", "end")
        except Exception:
            return

        text = self._subject_get()
        if self._subject_last_spell_text == text:
            return
        self._subject_last_spell_text = text
        try:
            self.subject_var.set(text)
        except Exception:
            pass
        try:
            issues = find_misspellings(text, DATA_DIR)
        except Exception as e:
            issues = []
            try:
                self._runlog("SPELLCHECK_SUBJECT_ERR", f"{type(e).__name__}: {e}")
            except Exception:
                pass

        self._subject_issues = issues

        for it in issues:
            a = it["start"]
            b = it["end"]
            i1 = f"1.0+{a}c"
            i2 = f"1.0+{b}c"
            self.subject_txt.tag_add("misspell", i1, i2)

    def _on_subject_hover(self, ev):
        try:
            idx = self.subject_txt.index(f"@{ev.x},{ev.y}")
            col = int(idx.split(".")[1])
        except Exception:
            self._spell_tip_hide()
            return

        issues = getattr(self, "_subject_issues", []) or []
        hit = None
        for it in issues:
            if it["start"] <= col < it["end"]:
                hit = it
                break
        if not hit:
            self._spell_tip_hide()
            return

        sug = (hit.get("suggestion") or "").strip()
        word = (hit.get("word") or "").strip()
        marker = f"{word}|{sug}"

        if (
            self._spell_tip_word == marker
            and self._spell_tip
            and self._spell_tip.winfo_exists()
        ):
            return

        self._spell_tip_word = marker
        if sug:
            self._spell_tip_show(f"Suggest: {sug}", ev.x_root + 12, ev.y_root + 12)
        else:
            self._spell_tip_hide()

    def _subject_context_menu(self, ev):

        try:
            idx = self.subject_txt.index(f"@{ev.x},{ev.y}")  # like "1.12"
            col = int(idx.split(".")[1])
        except Exception:
            return

        issues = getattr(self, "_subject_issues", []) or []
        hit = None
        for it in issues:
            if it["start"] <= col < it["end"]:
                hit = it
                break
        if not hit:
            return

        start = hit["start"]
        end = hit["end"]
        word = hit["word"]
        sug = hit["suggestion"]

        menu = tk.Menu(self.root, tearoff=0)

        def do_replace():
            i1 = f"1.0+{start}c"
            i2 = f"1.0+{end}c"
            self.subject_txt.delete(i1, i2)
            self.subject_txt.insert(i1, sug)
            self._runlog("SPELL_REPLACE_SUBJECT", f"{word} -> {sug}")
            self._on_subject_change()

        def do_keep():
            ok = add_spell_exception(word, DATA_DIR)
            if ok:
                self._runlog("SPELL_KEEP_SUBJECT", word)
                self._on_subject_change()

        def do_keep_all_subject():
            phrase = (self._subject_get() or "").strip()
            if not phrase:
                return
            ok = add_spell_exception(phrase, DATA_DIR)
            if ok:
                self._on_subject_change()

        if sug:
            menu.add_command(label=f"Replace with: {sug}", command=do_replace)
        else:
            menu.add_command(label="No safe spelling suggestion", state="disabled")
        menu.add_command(
            label=f"Keep term (add to exceptions): {word}", command=do_keep
        )
        menu.add_separator()
        menu.add_command(
            label="Keep all words in Subject (add phrase to exceptions)",
            command=do_keep_all_subject,
        )
        menu.tk_popup(ev.x_root, ev.y_root)

    # ---------- Location spellcheck (same UX as Subject) ----------
    def _location_get(self) -> str:
        try:
            s = self.location_txt.get("1.0", "end-1c")
        except Exception:
            s = self.location_var.get() or ""
        return (s or "").replace("\n", " ").replace("_", " ").strip()

    def _location_set(self, s: str):
        s = (s or "").replace("\n", " ").strip().replace("_", " ")
        self.location_var.set(s)

        try:
            self.location_txt.delete("1.0", "end")
            self.location_txt.insert("1.0", s)
        except Exception:
            pass

        # if user picked a suggestion, hide dropdown
        try:
            self._loc_ac_hide()
        except Exception:
            pass

        self._location_last_spell_text = None
        self._location_spellcheck_update()

    def _on_location_change(self, _ev=None):
        s = self._location_get()
        self.location_var.set(s)
        self._schedule_location_spellcheck(delay_ms=120)

    def _location_spellcheck_update(self):
        self._location_spell_after_id = None
        try:
            self.location_txt.tag_remove("misspell", "1.0", "end")
        except Exception:
            return

        text = self._location_get()
        if self._location_last_spell_text == text:
            return
        self._location_last_spell_text = text
        try:
            issues = find_misspellings(text, DATA_DIR)
        except Exception as e:
            issues = []
            try:
                self._runlog("SPELLCHECK_LOCATION_ERR", f"{type(e).__name__}: {e}")
            except Exception:
                pass
        self._location_issues = issues

        for it in issues:
            a = it["start"]
            b = it["end"]
            i1 = f"1.0+{a}c"
            i2 = f"1.0+{b}c"
            self.location_txt.tag_add("misspell", i1, i2)

    def _location_context_menu(self, ev):
        try:
            idx = self.location_txt.index(f"@{ev.x},{ev.y}")  # like "1.12"
            col = int(idx.split(".")[1])
        except Exception:
            return

        issues = getattr(self, "_location_issues", []) or []
        hit = None
        for it in issues:
            if it["start"] <= col < it["end"]:
                hit = it
                break
        if not hit:
            return

        start = hit["start"]
        end = hit["end"]
        word = hit["word"]
        sug = hit["suggestion"]

        menu = tk.Menu(self.root, tearoff=0)

        def do_replace():
            i1 = f"1.0+{start}c"
            i2 = f"1.0+{end}c"
            self.location_txt.delete(i1, i2)
            self.location_txt.insert(i1, sug)
            self._runlog("SPELL_REPLACE_LOCATION", f"{word} -> {sug}")
            self._on_location_change()

        def do_keep():
            ok = add_spell_exception(word, DATA_DIR)
            if ok:
                self._runlog("SPELL_KEEP_LOCATION", word)
                self._on_location_change()

        if sug:
            menu.add_command(label=f"Replace with: {sug}", command=do_replace)
        else:
            menu.add_command(label="No safe spelling suggestion", state="disabled")
        menu.add_command(
            label=f"Keep term (add to exceptions): {word}", command=do_keep
        )
        menu.tk_popup(ev.x_root, ev.y_root)

    def _spell_tip_show(self, text: str, x: int, y: int):
        try:
            if self._spell_tip is None or not self._spell_tip.winfo_exists():
                self._spell_tip = tk.Toplevel(self.root)
                self._spell_tip.wm_overrideredirect(True)
                try:
                    self._spell_tip.attributes("-topmost", True)
                except Exception:
                    pass
                self._spell_tip_label = tk.Label(
                    self._spell_tip,
                    text="",
                    justify="left",
                    relief="solid",
                    borderwidth=1,
                    font=("Segoe UI", 9),
                )
                self._spell_tip_label.pack(ipadx=6, ipady=3)

            if self._spell_tip_label:
                self._spell_tip_label.config(text=text)

            self._spell_tip.geometry(f"+{x}+{y}")
            self._spell_tip.deiconify()
        except Exception:
            self._spell_tip = None
            self._spell_tip_label = None

    def _spell_tip_hide(self):
        try:
            self._spell_tip_word = None
            if self._spell_tip and self._spell_tip.winfo_exists():
                self._spell_tip.withdraw()
        except Exception:
            pass

    def _on_location_hover(self, ev):
        try:
            idx = self.location_txt.index(f"@{ev.x},{ev.y}")
            col = int(idx.split(".")[1])
        except Exception:
            self._spell_tip_hide()
            return

        issues = getattr(self, "_location_issues", []) or []
        hit = None
        for it in issues:
            if it["start"] <= col < it["end"]:
                hit = it
                break

        if not hit:
            self._spell_tip_hide()
            return

        sug = (hit.get("suggestion") or "").strip()
        word = (hit.get("word") or "").strip()
        marker = f"{word}|{sug}"

        if (
            self._spell_tip_word == marker
            and self._spell_tip
            and self._spell_tip.winfo_exists()
        ):
            return

        self._spell_tip_word = marker
        if sug:
            self._spell_tip_show(f"Suggest: {sug}", ev.x_root + 12, ev.y_root + 12)
        else:
            self._spell_tip_hide()

    def _location_candidates(self, typed: str = "", limit: int = 0) -> list[str]:
        vals: list[str] = []
        seen: set[str] = set()
        for raw in (self.location_all or []):
            v = str(raw or "").replace("_", " ").strip()
            if not v:
                continue
            key = v.lower()
            if key in seen:
                continue
            seen.add(key)
            vals.append(v)

        t = (typed or "").strip().lower()
        if t:
            starts = [v for v in vals if v.lower().startswith(t)]
            contains = [v for v in vals if t in v.lower() and v not in starts]
            vals = starts + contains

        if limit and limit > 0:
            vals = vals[:limit]
        return vals

    def _location_cycle_value(self, step: int):
        try:
            cur = (self._location_get() or "").strip()
            # Cycle through the full ordered location list (like folder combobox behavior).
            vals = self._location_candidates("", limit=0)
            if not vals:
                return

            cur_l = cur.lower()
            idx = -1
            for i, v in enumerate(vals):
                if v.lower() == cur_l:
                    idx = i
                    break

            if idx < 0:
                new_idx = 0 if step >= 0 else len(vals) - 1
            else:
                new_idx = max(0, min(len(vals) - 1, idx + step))

            self._location_set(vals[new_idx])
            try:
                self.location_txt.mark_set("insert", "end-1c")
            except Exception:
                pass
            self._loc_ac_update()
        except Exception:
            pass

    def _on_location_mousewheel(self, ev=None):
        try:
            delta = int(getattr(ev, "delta", 0) or 0)
            if delta == 0:
                num = int(getattr(ev, "num", 0) or 0)
                if num == 4:
                    delta = 120
                elif num == 5:
                    delta = -120
            if delta == 0:
                return "break"

            step = -1 if delta > 0 else 1
            self._location_cycle_value(step)
        except Exception:
            pass
        return "break"

    def _location_pick_menu(self):
        try:
            typed = (self._location_get() or "").strip()
            vals = self._location_candidates(typed, limit=40)  # keep menu sane
            menu = tk.Menu(self.root, tearoff=0)

            if not vals:
                menu.add_command(label="(no matches)", state="disabled")
            else:
                for v in vals:
                    menu.add_command(
                        label=v, command=lambda vv=v: self._location_set(vv)
                    )

            x = self.location_txt.winfo_rootx()
            y = self.location_txt.winfo_rooty() + self.location_txt.winfo_height()
            menu.tk_popup(x, y)
        except Exception:
            pass

    # ---------- Location autocomplete dropdown for Text widget ----------
    def _loc_ac_hide(self):
        try:
            if self._loc_ac_top and self._loc_ac_top.winfo_exists():
                self._loc_ac_top.withdraw()
        except Exception:
            pass

    def _loc_ac_show(self, vals: list[str]):
        try:
            if not vals:
                self._loc_ac_hide()
                return

            if self._loc_ac_top is None or not self._loc_ac_top.winfo_exists():
                self._loc_ac_top = tk.Toplevel(self.root)
                self._loc_ac_top.wm_overrideredirect(True)
                try:
                    self._loc_ac_top.attributes("-topmost", True)
                except Exception:
                    pass

                self._loc_ac_list = tk.Listbox(self._loc_ac_top, height=8)
                self._loc_ac_list.pack(fill="both", expand=True)

                def _pick(_ev=None):
                    try:
                        if not self._loc_ac_list:
                            return "break"
                        sel = self._loc_ac_list.curselection()
                        if not sel:
                            sel = (0,)
                        v = self._loc_ac_list.get(sel[0])
                        self._location_set(v)
                        self._loc_ac_hide()
                        self.folder_cb.focus_set()
                    except Exception:
                        pass
                    return "break"

                def _wheel(_ev=None):
                    return self._on_location_mousewheel(_ev)

                self._loc_ac_list.bind("<Double-1>", _pick, add="+")
                self._loc_ac_list.bind("<Return>", _pick, add="+")
                self._loc_ac_list.bind("<MouseWheel>", _wheel, add="+")
                self._loc_ac_list.bind("<Button-4>", _wheel, add="+")
                self._loc_ac_list.bind("<Button-5>", _wheel, add="+")

            if self._loc_ac_list:
                self._loc_ac_list.delete(0, "end")
                for v in vals:
                    self._loc_ac_list.insert("end", (v or "").replace("_", " "))
                self._loc_ac_list.selection_clear(0, "end")
                self._loc_ac_list.selection_set(0)
                self._loc_ac_list.activate(0)

            x = self.location_txt.winfo_rootx()
            y = self.location_txt.winfo_rooty() + self.location_txt.winfo_height()
            w = max(200, self.location_txt.winfo_width())
            self._loc_ac_top.geometry(f"{w}x160+{x}+{y}")
            self._loc_ac_top.deiconify()
        except Exception:
            self._loc_ac_top = None
            self._loc_ac_list = None

    def _loc_ac_update(self):
        try:
            typed = (self._location_get() or "").strip()
            if not typed:
                self._loc_ac_hide()
                return

            out = self._location_candidates(typed, limit=30)
            self._loc_ac_show(out)
        except Exception:
            pass

    def _loc_inline_autocomplete(self, ev=None):
        try:
            ks = str(getattr(ev, "keysym", ""))
            if ks in ("BackSpace", "Delete", "Left", "Right", "Home", "End", "Prior", "Next"):
                return

            typed = (self._location_get() or "").strip()
            if not typed:
                return

            vals = self._location_candidates(typed, limit=30)
            if not vals:
                return

            suggestion = vals[0]
            if not suggestion.lower().startswith(typed.lower()):
                return
            if suggestion.lower() == typed.lower():
                self.location_var.set(suggestion)
                self._schedule_location_spellcheck(delay_ms=120)
                return

            self.location_txt.delete("1.0", "end")
            self.location_txt.insert("1.0", suggestion)
            i1 = f"1.0+{len(typed)}c"
            self.location_txt.tag_remove("sel", "1.0", "end")
            self.location_txt.tag_add("sel", i1, "end-1c")
            self.location_txt.mark_set("insert", i1)
            self.location_var.set(suggestion)
            self._schedule_location_spellcheck(delay_ms=120)
        except Exception:
            pass

    def _on_location_keyrelease(self, ev=None):
        try:
            self.location_var.set(self._location_get())
        except Exception:
            pass
        self._schedule_location_spellcheck(delay_ms=120)

        # do not fight navigation keys
        try:
            ks = getattr(ev, "keysym", "")
            if ks in ("Up", "Down", "Return", "Escape", "Tab"):
                return
        except Exception:
            pass

        self._loc_inline_autocomplete(ev)
        self._loc_ac_update()

    def _on_location_return(self, _ev=None):
        # accept first suggestion if dropdown is open
        try:
            if (
                self._loc_ac_top
                and self._loc_ac_top.winfo_exists()
                and str(self._loc_ac_top.state()) != "withdrawn"
            ):
                if self._loc_ac_list and self._loc_ac_list.size() > 0:
                    v = self._loc_ac_list.get(
                        self._loc_ac_list.curselection()[0]
                        if self._loc_ac_list.curselection()
                        else 0
                    )
                    self._location_set(v)
                self._loc_ac_hide()
                self.folder_cb.focus_set()
                return "break"
        except Exception:
            pass

        self._loc_ac_hide()
        self.folder_cb.focus_set()
        return "break"

    def _on_location_tab(self, _ev=None):
        # prevent inserting a tab into Text; move on
        try:
            if (
                self._loc_ac_top
                and self._loc_ac_top.winfo_exists()
                and str(self._loc_ac_top.state()) != "withdrawn"
            ):
                if self._loc_ac_list and self._loc_ac_list.size() > 0:
                    v = self._loc_ac_list.get(
                        self._loc_ac_list.curselection()[0]
                        if self._loc_ac_list.curselection()
                        else 0
                    )
                    self._location_set(v)
                self._loc_ac_hide()
        except Exception:
            pass
        self.folder_cb.focus_set()
        return "break"

    def _on_location_down(self, _ev=None):
        try:
            if not (self._loc_ac_list and self._loc_ac_list.size() > 0):
                self._loc_ac_update()
                return "break"
            cur = self._loc_ac_list.curselection()
            i = (cur[0] + 1) if cur else 0
            i = min(i, self._loc_ac_list.size() - 1)
            self._loc_ac_list.selection_clear(0, "end")
            self._loc_ac_list.selection_set(i)
            self._loc_ac_list.activate(i)
        except Exception:
            pass
        return "break"

    def _on_location_up(self, _ev=None):
        try:
            if not (self._loc_ac_list and self._loc_ac_list.size() > 0):
                return "break"
            cur = self._loc_ac_list.curselection()
            i = (cur[0] - 1) if cur else 0
            i = max(i, 0)
            self._loc_ac_list.selection_clear(0, "end")
            self._loc_ac_list.selection_set(i)
            self._loc_ac_list.activate(i)
        except Exception:
            pass
        return "break"

    def _on_location_escape(self, _ev=None):
        self._loc_ac_hide()
        return "break"


# ---------- entry ----------
# AMIR_SAFE_PREFILL_REPAIR_START
# Generic cleanup and deterministic metadata repair.
# No topic patching. No subject patching.

def cleanup_runtime_artifacts(*_args, **_kwargs) -> None:
    import glob
    import os
    import shutil

    data_dir = globals().get("DATA_DIR", os.path.join(os.getcwd(), "data"))
    used_names = globals().get("USED_NAMES", os.path.join(data_dir, "used_filenames.json"))

    def prune(pattern: str, keep: int = 5) -> None:
        try:
            files = [p for p in glob.glob(pattern) if os.path.isfile(p)]
            files.sort(key=lambda p: os.path.getmtime(p), reverse=True)

            for old in files[int(keep):]:
                try:
                    os.remove(old)
                except Exception:
                    pass
        except Exception:
            pass

    try:
        ollama_root = os.path.join(data_dir, "ollama_tmp")

        if os.path.isdir(ollama_root):
            for run_dir in glob.glob(os.path.join(ollama_root, "run_*")):
                if os.path.isdir(run_dir):
                    shutil.rmtree(run_dir, ignore_errors=True)
                    print(f"[CLEANUP] Removed Ollama temp folder: {run_dir}")
    except Exception as exc:
        print(f"[WARN] Could not clean ollama_tmp: {exc}")

    try:
        identifier_tmp = os.path.join(data_dir, "identifier_detail_tmp")

        if os.path.isdir(identifier_tmp):
            shutil.rmtree(identifier_tmp, ignore_errors=True)
            print(f"[CLEANUP] Removed identifier detail temp folder: {identifier_tmp}")
    except Exception as exc:
        print(f"[WARN] Could not clean identifier detail temp: {exc}")

    prune(f"{used_names}.bak_*", keep=5)
    prune(os.path.join(data_dir, "multiset_session.backup_*.json"), keep=5)
    prune(os.path.join(data_dir, "_metadata_quality_backups", "review_before_metadata_quality_*.db"), keep=5)
    prune(os.path.join(data_dir, "identifier_router_last_set_*.json"), keep=10)


def _amir_review_db_path() -> str:
    import os

    for name in ["DB_PATH", "REVIEW_DB", "REVIEW_DB_PATH"]:
        value = globals().get(name)

        if value:
            return str(value)

    data_dir = globals().get("DATA_DIR", os.path.join(os.getcwd(), "data"))
    return os.path.join(str(data_dir), "review.db")


def _amir_clean_generation_text(value: object) -> str:
    import re

    text = str(value or "").strip()
    text = text.replace("_", " ").replace("-", " ")

    remove_words = [
        "canon",
        "eos",
        "r5",
        "mark",
        "ii",
        "photography",
        "photo",
        "image",
        "picture",
        "shot",
        "macro",
    ]

    for word in remove_words:
        text = re.sub(rf"\b{re.escape(word)}\b", " ", text, flags=re.IGNORECASE)

    text = re.sub(r"\s+", " ", text).strip(" ,.;:-")

    for _ in range(4):
        cleaned = re.sub(
            r"\b(?:with|in|on|at|by|near|of|and|the)\s*$",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip(" ,.;:-")

        if cleaned == text:
            break

        text = cleaned

    return text


def _amir_text_is_sluggy(value: object) -> bool:
    text = str(value or "")

    if "_" in text:
        return True

    lower = text.lower()

    bad_bits = [
        "canon eos",
        "r5 mark",
        "flower photography nature photography",
        "nature photography canon",
        "photography canon",
    ]

    return any(bit in lower for bit in bad_bits)


def _amir_keywords_from_text(subject: str, location: str, folder: str, caption: str, alt_text: str) -> str:
    import re

    banned = {
        "a",
        "an",
        "and",
        "at",
        "by",
        "for",
        "from",
        "in",
        "into",
        "is",
        "it",
        "of",
        "on",
        "or",
        "the",
        "to",
        "with",
        "visible",
        "showing",
        "surrounding",
        "context",
        "clear",
        "detail",
        "details",
        "photographed",
        "photography",
        "photo",
        "image",
        "picture",
        "canon",
        "eos",
        "mark",
        "r5",
        "ii",
    }

    values = [subject, location, folder, caption, alt_text]
    raw = " ".join(values).replace("_", " ").replace("-", " ")

    tokens = [
        token
        for token in re.findall(r"[A-Za-z0-9]+", raw.lower())
        if len(token) > 2 and token not in banned
    ]

    items = []

    def add(value: str) -> None:
        value = re.sub(r"\s+", " ", value).strip(" ,.;:-").lower()

        if value and value not in items:
            items.append(value)

    add(subject.lower())

    if location:
        add(location.lower())

    for source in [subject, location, caption, alt_text, folder]:
        source_tokens = [
            token
            for token in re.findall(r"[A-Za-z0-9]+", source.lower())
            if len(token) > 2 and token not in banned
        ]

        for index in range(0, max(0, len(source_tokens) - 1)):
            add(" ".join(source_tokens[index:index + 2]))

        for token in source_tokens:
            add(token)

    for index in range(0, max(0, len(tokens) - 1)):
        add(" ".join(tokens[index:index + 2]))

    for token in tokens:
        add(token)

    return ", ".join(items[:15])


def _amir_repair_prefill_rows() -> int:
    import sqlite3

    db_path = _amir_review_db_path()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(review_queue)").fetchall()
        }

        required = {"id", "Subject", "Location", "Folder", "Caption", "alt_text", "Keywords"}

        if not required.issubset(cols):
            return 0

        rows = conn.execute(
            """
            SELECT *
            FROM review_queue
            WHERE COALESCE(Review_Status, '') IN ('', 'Queued', 'Pending')
            ORDER BY id
            """
        ).fetchall()

        repaired = 0

        for row in rows:
            subject = (
                _amir_clean_generation_text(row["final_subject"] if "final_subject" in cols else "")
                or _amir_clean_generation_text(row["Subject"])
                or _amir_clean_generation_text(row["ai_suggested_subject"] if "ai_suggested_subject" in cols else "")
            )
            location = _amir_clean_generation_text(row["Location"])
            folder = _amir_clean_generation_text(row["Folder"])

            if not subject:
                continue

            if location:
                caption = f"{subject} photographed in {location}, showing natural detail and outdoor context."
                alt_text = f"{subject} in {location}, showing natural detail and outdoor context."
            else:
                caption = f"{subject} photographed with natural detail and outdoor context."
                alt_text = f"{subject} showing natural detail and outdoor context."

            keywords = _amir_keywords_from_text(
                subject=subject,
                location=location,
                folder=folder,
                caption=caption,
                alt_text=alt_text,
            )

            current_caption = row["Caption"]
            current_alt = row["alt_text"]
            current_keywords = row["Keywords"]
            keyword_count = len([k for k in str(current_keywords or "").split(",") if k.strip()])

            needs_repair = (
                _amir_text_is_sluggy(current_caption)
                or _amir_text_is_sluggy(current_alt)
                or not current_caption
                or not current_alt
                or len(str(current_alt).split()) < 8
                or keyword_count < 10
            )

            if not needs_repair:
                continue

            conn.execute(
                """
                UPDATE review_queue
                SET Caption = ?,
                    alt_text = ?,
                    Keywords = ?,
                    Review_Status = 'Pending'
                WHERE id = ?
                """,
                (caption, alt_text, keywords, row["id"]),
            )
            repaired += 1

        conn.commit()

        if repaired:
            print(f"[WARN] Deterministic prefill repair created reviewable metadata for {repaired} row(s).")

        return repaired
    finally:
        conn.close()
# AMIR_SAFE_PREFILL_REPAIR_END

# AMIR_BETTER_METADATA_REPAIR_START
# Better deterministic metadata repair.
# Generic only. No per topic and no per subject patching.

def cleanup_runtime_artifacts(*_args, **_kwargs) -> None:
    import glob
    import os
    import shutil

    data_dir = globals().get("DATA_DIR", os.path.join(os.getcwd(), "data"))
    used_names = globals().get("USED_NAMES", os.path.join(data_dir, "used_filenames.json"))

    def prune(pattern: str, keep: int = 5) -> None:
        try:
            files = [p for p in glob.glob(pattern) if os.path.isfile(p)]
            files.sort(key=lambda p: os.path.getmtime(p), reverse=True)

            for old in files[int(keep):]:
                try:
                    os.remove(old)
                except Exception:
                    pass
        except Exception:
            pass

    try:
        ollama_root = os.path.join(data_dir, "ollama_tmp")

        if os.path.isdir(ollama_root):
            for run_dir in glob.glob(os.path.join(ollama_root, "run_*")):
                if os.path.isdir(run_dir):
                    shutil.rmtree(run_dir, ignore_errors=True)
                    print(f"[CLEANUP] Removed Ollama temp folder: {run_dir}")
    except Exception as exc:
        print(f"[WARN] Could not clean ollama_tmp: {exc}")

    try:
        identifier_tmp = os.path.join(data_dir, "identifier_detail_tmp")

        if os.path.isdir(identifier_tmp):
            shutil.rmtree(identifier_tmp, ignore_errors=True)
            print(f"[CLEANUP] Removed identifier detail temp folder: {identifier_tmp}")
    except Exception as exc:
        print(f"[WARN] Could not clean identifier detail temp: {exc}")

    prune(f"{used_names}.bak_*", keep=5)
    prune(os.path.join(data_dir, "multiset_session.backup_*.json"), keep=5)
    prune(os.path.join(data_dir, "_metadata_quality_backups", "review_before_metadata_quality_*.db"), keep=5)
    prune(os.path.join(data_dir, "identifier_router_last_set_*.json"), keep=10)


def _amir_review_db_path() -> str:
    import os

    for name in ["DB_PATH", "REVIEW_DB", "REVIEW_DB_PATH"]:
        value = globals().get(name)

        if value:
            return str(value)

    data_dir = globals().get("DATA_DIR", os.path.join(os.getcwd(), "data"))
    return os.path.join(str(data_dir), "review.db")


def _amir_words(value: object) -> list[str]:
    import re

    return re.findall(r"[A-Za-z0-9]+", str(value or "").replace("_", " ").replace("-", " "))


def _amir_clean_generation_text(value: object) -> str:
    import re

    text = str(value or "").strip()
    text = text.replace("_", " ").replace("-", " ")

    remove_words = [
        "canon",
        "eos",
        "r5",
        "mark",
        "ii",
        "photography",
        "photo",
        "image",
        "picture",
        "shot",
        "macro",
    ]

    for word in remove_words:
        text = re.sub(rf"\b{re.escape(word)}\b", " ", text, flags=re.IGNORECASE)

    text = re.sub(r"\s+", " ", text).strip(" ,.;:-")

    for _ in range(4):
        cleaned = re.sub(
            r"\b(?:with|in|on|at|by|near|of|and|the)\s*$",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip(" ,.;:-")

        if cleaned == text:
            break

        text = cleaned

    return text


def _amir_is_topic_like_location(value: object) -> bool:
    raw = str(value or "").strip().lower().replace("_", " ").replace("-", " ")

    if not raw:
        return True

    topic_words = {
        "photography",
        "photo",
        "image",
        "macro",
        "nature",
        "landscape",
        "cityscape",
        "architecture",
        "flower",
        "people",
        "creative",
        "miscellaneous",
        "aviation",
        "night",
        "water",
        "waterscape",
        "botany",
        "entomology",
    }

    tokens = [token for token in re.findall(r"[a-z0-9]+", raw) if token]

    if not tokens:
        return True

    if "photography" in tokens:
        return True

    if all(token in topic_words for token in tokens):
        return True

    return False


def _amir_location_from_filename(file_name: object, subject: str) -> str:
    import re

    stem = str(file_name or "")
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", stem)
    stem = stem.replace("-", "_")

    if not stem:
        return ""

    match = re.search(
        r"(?:^|_)In_(?P<place>.+?)(?:_(?:Flower|Nature|Macro|Landscape|Cityscape|Architecture|People|Creative|Miscellaneous|Aviation|Night|Water|Waterscape|Botany|Entomology)_Photography|_Canon_|_\d{4}_\d{3}|$)",
        stem,
        flags=re.IGNORECASE,
    )

    if not match:
        return ""

    place = match.group("place")
    place = place.replace("_", " ")
    place = re.sub(r"\s+", " ", place).strip(" ,.;:-")

    bad_tail = {
        "flower",
        "nature",
        "macro",
        "landscape",
        "cityscape",
        "architecture",
        "people",
        "creative",
        "miscellaneous",
        "aviation",
        "night",
        "water",
        "waterscape",
        "botany",
        "entomology",
        "photography",
    }

    parts = place.split()

    while parts and parts[-1].lower() in bad_tail:
        parts.pop()

    place = " ".join(parts).strip(" ,.;:-")

    if not place:
        return ""

    subject_words = {word.lower() for word in _amir_words(subject)}

    place_words = [
        word
        for word in place.split()
        if word.lower() not in subject_words
    ]

    place = " ".join(place_words).strip(" ,.;:-")

    return place


def _amir_best_location_for_generation(row, cols: set[str], subject: str) -> str:
    raw_location = row["Location"] if "Location" in cols else ""
    file_name = row["File_Name"] if "File_Name" in cols else ""

    parsed = _amir_location_from_filename(file_name, subject)

    if parsed:
        return parsed

    if raw_location and not _amir_is_topic_like_location(raw_location):
        return _amir_clean_generation_text(raw_location)

    return ""


def _amir_sluggy_or_bad_text(value: object) -> bool:
    text = str(value or "").strip()

    if not text:
        return True

    lower = text.lower()

    bad_bits = [
        "canon eos",
        "r5 mark",
        "flower photography nature photography",
        "nature photography canon",
        "photography canon",
        "showing natural detail and outdoor context",
        "clear visual detail and surrounding context",
    ]

    if any(bit in lower for bit in bad_bits):
        return True

    if "_" in text:
        return True

    if len(text.split()) < 8:
        return True

    return False


def _amir_keyword_list(subject: str, location: str, folder: str, caption: str, alt_text: str, seq: int) -> str:
    import re

    banned = {
        "a",
        "an",
        "and",
        "at",
        "by",
        "for",
        "from",
        "in",
        "into",
        "is",
        "it",
        "of",
        "on",
        "or",
        "the",
        "to",
        "with",
        "visible",
        "showing",
        "surrounding",
        "context",
        "clear",
        "detail",
        "details",
        "photographed",
        "photography",
        "photo",
        "image",
        "picture",
        "canon",
        "eos",
        "mark",
        "r5",
        "ii",
        "natural",
        "outdoor",
        "outdoors",
    }

    items: list[str] = []

    def add(value: str) -> None:
        value = re.sub(r"\s+", " ", value).strip(" ,.;:-").lower()

        if not value:
            return

        words = value.split()

        if len(words) > 4:
            return

        if any(word in banned for word in words) and len(words) == 1:
            return

        if value not in items:
            items.append(value)

    subject_tokens = [
        token.lower()
        for token in _amir_words(subject)
        if len(token) > 2 and token.lower() not in banned
    ]

    location_tokens = [
        token.lower()
        for token in _amir_words(location)
        if len(token) > 2 and token.lower() not in banned
    ]

    folder_tokens = [
        token.lower()
        for token in _amir_words(folder)
        if len(token) > 2 and token.lower() not in banned
    ]

    add(subject)

    if location:
        add(location)

    for size in [2, 3]:
        for index in range(0, max(0, len(subject_tokens) - size + 1)):
            add(" ".join(subject_tokens[index:index + size]))

    for token in subject_tokens:
        add(token)

    for size in [2]:
        for index in range(0, max(0, len(location_tokens) - size + 1)):
            add(" ".join(location_tokens[index:index + size]))

    for token in location_tokens:
        add(token)

    if subject_tokens:
        add(f"{subject_tokens[0]} close view")
        add(f"{subject_tokens[-1]} detail")

    if len(subject_tokens) >= 2:
        add(f"{subject_tokens[0]} {subject_tokens[-1]} detail")

    for token in folder_tokens:
        add(token)

    add(f"series image {seq:02d}")

    return ", ".join(items[:15])


def _amir_sentence_templates(subject: str, location: str, seq: int) -> tuple[str, str]:
    location_part = f" in {location}" if location else ""

    templates = [
        (
            f"{subject} photographed{location_part} with a soft background and clear branch detail.",
            f"{subject}{location_part} with a soft background and clear branch detail.",
        ),
        (
            f"{subject} captured{location_part} with shallow depth of field and soft natural tones.",
            f"{subject}{location_part} with shallow depth of field and soft natural tones.",
        ),
        (
            f"{subject} photographed{location_part} against a blurred background with delicate foreground detail.",
            f"{subject}{location_part} against a blurred background with delicate foreground detail.",
        ),
        (
            f"{subject} captured{location_part} with isolated detail and a calm natural background.",
            f"{subject}{location_part} with isolated detail and a calm natural background.",
        ),
    ]

    caption, alt_text = templates[(max(seq, 1) - 1) % len(templates)]

    return caption, alt_text


def _amir_repair_prefill_rows() -> int:
    import sqlite3

    db_path = _amir_review_db_path()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(review_queue)").fetchall()
        }

        required = {"id", "Subject", "Location", "Folder", "Caption", "alt_text", "Keywords", "File_Name"}

        if not required.issubset(cols):
            return 0

        rows = conn.execute(
            """
            SELECT *
            FROM review_queue
            WHERE COALESCE(Review_Status, '') IN ('', 'Queued', 'Pending')
            ORDER BY id
            """
        ).fetchall()

        repaired = 0

        for index, row in enumerate(rows, start=1):
            subject = (
                _amir_clean_generation_text(row["final_subject"] if "final_subject" in cols else "")
                or _amir_clean_generation_text(row["Subject"])
                or _amir_clean_generation_text(row["ai_suggested_subject"] if "ai_suggested_subject" in cols else "")
            )

            if not subject:
                continue

            location = _amir_best_location_for_generation(row, cols, subject)
            folder = _amir_clean_generation_text(row["Folder"])
            caption, alt_text = _amir_sentence_templates(subject, location, index)

            keywords = _amir_keyword_list(
                subject=subject,
                location=location,
                folder=folder,
                caption=caption,
                alt_text=alt_text,
                seq=index,
            )

            current_caption = row["Caption"]
            current_alt = row["alt_text"]
            current_keywords = row["Keywords"]
            keyword_count = len([k for k in str(current_keywords or "").split(",") if k.strip()])

            needs_repair = (
                _amir_sluggy_or_bad_text(current_caption)
                or _amir_sluggy_or_bad_text(current_alt)
                or keyword_count < 10
            )

            if not needs_repair:
                continue

            conn.execute(
                """
                UPDATE review_queue
                SET Caption = ?,
                    alt_text = ?,
                    Keywords = ?,
                    Review_Status = 'Pending'
                WHERE id = ?
                """,
                (caption, alt_text, keywords, row["id"]),
            )
            repaired += 1

        conn.commit()

        if repaired:
            print(f"[WARN] Better deterministic metadata repair created reviewable metadata for {repaired} row(s).")

        return repaired
    finally:
        conn.close()
# AMIR_BETTER_METADATA_REPAIR_END

# AMIR_NO_CJK_METADATA_REPAIR_START
# Generic no CJK metadata rule.
# Any caption, alt text or keyword output containing CJK is invalid and must be repaired.

def _amir_contains_cjk(value: object) -> bool:
    import re

    return bool(re.search(r"[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\u3040-\u30FF\uAC00-\uD7AF]", str(value or "")))


_PREVIOUS_AMIR_SLUGGY_OR_BAD_TEXT = _amir_sluggy_or_bad_text


def _amir_sluggy_or_bad_text(value: object) -> bool:
    if _amir_contains_cjk(value):
        return True

    return _PREVIOUS_AMIR_SLUGGY_OR_BAD_TEXT(value)


_PREVIOUS_AMIR_REPAIR_PREFILL_ROWS = _amir_repair_prefill_rows


def _amir_repair_prefill_rows() -> int:
    import sqlite3

    repaired = _PREVIOUS_AMIR_REPAIR_PREFILL_ROWS()

    db_path = _amir_review_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(review_queue)").fetchall()
        }

        required = {"id", "Subject", "Location", "Folder", "Caption", "alt_text", "Keywords", "File_Name"}

        if not required.issubset(cols):
            return repaired

        rows = conn.execute(
            """
            SELECT *
            FROM review_queue
            WHERE COALESCE(Review_Status, '') IN ('', 'Queued', 'Pending')
            ORDER BY id
            """
        ).fetchall()

        extra_repaired = 0

        for index, row in enumerate(rows, start=1):
            current_caption = row["Caption"]
            current_alt = row["alt_text"]
            current_keywords = row["Keywords"]

            if not (
                _amir_contains_cjk(current_caption)
                or _amir_contains_cjk(current_alt)
                or _amir_contains_cjk(current_keywords)
            ):
                continue

            subject = (
                _amir_clean_generation_text(row["final_subject"] if "final_subject" in cols else "")
                or _amir_clean_generation_text(row["Subject"])
                or _amir_clean_generation_text(row["ai_suggested_subject"] if "ai_suggested_subject" in cols else "")
            )

            if not subject:
                continue

            location = _amir_best_location_for_generation(row, cols, subject)
            folder = _amir_clean_generation_text(row["Folder"])
            caption, alt_text = _amir_sentence_templates(subject, location, index)

            keywords = _amir_keyword_list(
                subject=subject,
                location=location,
                folder=folder,
                caption=caption,
                alt_text=alt_text,
                seq=index,
            )

            conn.execute(
                """
                UPDATE review_queue
                SET Caption = ?,
                    alt_text = ?,
                    Keywords = ?,
                    Review_Status = 'Pending'
                WHERE id = ?
                """,
                (caption, alt_text, keywords, row["id"]),
            )
            extra_repaired += 1

        conn.commit()

        if extra_repaired:
            print(f"[WARN] Repaired {extra_repaired} row(s) containing non-English/CJK metadata.")

        return repaired + extra_repaired
    finally:
        conn.close()
# AMIR_NO_CJK_METADATA_REPAIR_END


# AMIR_EVIDENCE_METADATA_REPAIR_START
# Generic evidence based metadata repair.
# No topic patching. No subject patching.
# ai_suggested_subject is NOT trusted evidence.
# Concrete extra objects need trusted evidence before they may appear in caption, alt text or keywords.

def cleanup_runtime_artifacts(*_args, **_kwargs) -> None:
    import glob
    import os
    import shutil

    data_dir = globals().get("DATA_DIR", os.path.join(os.getcwd(), "data"))
    used_names = globals().get("USED_NAMES", os.path.join(data_dir, "used_filenames.json"))

    def prune(pattern: str, keep: int = 5) -> None:
        try:
            files = [p for p in glob.glob(pattern) if os.path.isfile(p)]
            files.sort(key=lambda p: os.path.getmtime(p), reverse=True)

            for old in files[int(keep):]:
                try:
                    os.remove(old)
                except Exception:
                    pass
        except Exception:
            pass

    try:
        ollama_root = os.path.join(data_dir, "ollama_tmp")

        if os.path.isdir(ollama_root):
            for run_dir in glob.glob(os.path.join(ollama_root, "run_*")):
                if os.path.isdir(run_dir):
                    shutil.rmtree(run_dir, ignore_errors=True)
                    print(f"[CLEANUP] Removed Ollama temp folder: {run_dir}")
    except Exception as exc:
        print(f"[WARN] Could not clean ollama_tmp: {exc}")

    try:
        identifier_tmp = os.path.join(data_dir, "identifier_detail_tmp")

        if os.path.isdir(identifier_tmp):
            shutil.rmtree(identifier_tmp, ignore_errors=True)
            print(f"[CLEANUP] Removed identifier detail temp folder: {identifier_tmp}")
    except Exception as exc:
        print(f"[WARN] Could not clean identifier detail temp: {exc}")

    prune(f"{used_names}.bak_*", keep=5)
    prune(os.path.join(data_dir, "multiset_session.backup_*.json"), keep=5)
    prune(os.path.join(data_dir, "_metadata_quality_backups", "review_before_metadata_quality_*.db"), keep=5)
    prune(os.path.join(data_dir, "identifier_router_last_set_*.json"), keep=10)


def _amir_review_db_path() -> str:
    import os

    for name in ["DB_PATH", "REVIEW_DB", "REVIEW_DB_PATH"]:
        value = globals().get(name)

        if value:
            return str(value)

    data_dir = globals().get("DATA_DIR", os.path.join(os.getcwd(), "data"))
    return os.path.join(str(data_dir), "review.db")


def _amir_contains_cjk(value: object) -> bool:
    import re

    return bool(re.search(r"[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\u3040-\u30FF\uAC00-\uD7AF]", str(value or "")))


def _amir_words(value: object) -> list[str]:
    import re

    return re.findall(r"[A-Za-z0-9]+", str(value or "").replace("_", " ").replace("-", " "))


def _amir_root(word: str) -> str:
    word = str(word or "").strip().lower()

    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"

    if len(word) > 4 and word.endswith("sses"):
        return word[:-2]

    if len(word) > 3 and word.endswith("s"):
        return word[:-1]

    return word


def _amir_clean_text(value: object) -> str:
    import re

    text = str(value or "").replace("_", " ").replace("-", " ").strip()

    remove_words = [
        "canon",
        "eos",
        "r5",
        "mark",
        "ii",
        "photography",
        "photo",
        "image",
        "picture",
        "shot",
        "macro",
    ]

    for word in remove_words:
        text = re.sub(rf"\b{re.escape(word)}\b", " ", text, flags=re.IGNORECASE)

    text = re.sub(r"\s+", " ", text).strip(" ,.;:-")

    for _ in range(6):
        cleaned = re.sub(
            r"\b(?:with|in|on|at|by|near|of|and|the)\s*$",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip(" ,.;:-")

        if cleaned == text:
            break

        text = cleaned

    return text


def _amir_slug(value: str) -> str:
    return "_".join(word for word in _amir_words(value) if word)


def _amir_is_context_bucket(value: object) -> bool:
    import re

    raw = str(value or "").strip().lower().replace("_", " ").replace("-", " ")

    if not raw:
        return False

    tokens = [token for token in re.findall(r"[a-z0-9]+", raw) if token]

    context_words = {
        "photography",
        "macro",
        "nature",
        "landscape",
        "cityscape",
        "architecture",
        "flower",
        "people",
        "creative",
        "miscellaneous",
        "aviation",
        "night",
        "water",
        "waterscape",
        "botany",
        "entomology",
    }

    return "photography" in tokens or all(token in context_words for token in tokens)


def _amir_split_subject_place(subject: str) -> tuple[str, str]:
    import re

    clean = _amir_clean_text(subject)

    match = re.match(
        r"^(?P<subject>.+?)\s+in\s+(?P<place>[A-Z][A-Za-z0-9 ]{2,80})$",
        clean,
        flags=re.IGNORECASE,
    )

    if not match:
        return clean, ""

    subject_part = match.group("subject").strip(" ,.;:-")
    place_part = match.group("place").strip(" ,.;:-")

    if _amir_is_context_bucket(place_part):
        return clean, ""

    return subject_part, place_part


def _amir_place_from_filename(file_name: object, subject_core: str) -> str:
    import re

    stem = str(file_name or "")
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", stem)
    stem = stem.replace("-", "_")

    match = re.search(
        r"(?:^|_)In_(?P<place>.+?)(?:_(?:Flower|Nature|Macro|Landscape|Cityscape|Architecture|People|Creative|Miscellaneous|Aviation|Night|Water|Waterscape|Botany|Entomology)_Photography|_Canon_|_\d{4}_\d{3}|$)",
        stem,
        flags=re.IGNORECASE,
    )

    if not match:
        return ""

    place = match.group("place").replace("_", " ")
    place = re.sub(r"\s+", " ", place).strip(" ,.;:-")

    if _amir_is_context_bucket(place):
        return ""

    subject_roots = {_amir_root(word) for word in _amir_words(subject_core)}

    place_words = [
        word
        for word in place.split()
        if _amir_root(word) not in subject_roots
    ]

    return " ".join(place_words).strip(" ,.;:-")


def _amir_json_loads(value: object) -> object:
    if not value:
        return None

    if isinstance(value, (dict, list)):
        return value

    try:
        return json.loads(str(value))
    except Exception:
        return None


def _amir_collect_structured_identifier_roots(value: object) -> set[str]:
    from collections import Counter

    payload = _amir_json_loads(value)

    if payload is None:
        return set()

    text_counter = Counter()
    trusted_roots: set[str] = set()

    text_keys = {
        "subject",
        "label",
        "specific_name",
        "descriptive_subject",
        "group_subject",
        "subject_text",
        "visible_text",
    }

    trait_keys = {
        "visible_traits",
        "keywords_seed",
        "detected_objects",
        "objects",
        "evidence",
    }

    def visit(node: object, trust_parent: bool = False) -> None:
        if isinstance(node, dict):
            confidence = 0
            score = 0
            accepted = False

            for key in ["confidence", "score", "identifier_confidence"]:
                try:
                    value_number = int(float(node.get(key) or 0))

                    if key == "score":
                        score = max(score, value_number)
                    else:
                        confidence = max(confidence, value_number)
                except Exception:
                    pass

            accepted = bool(node.get("accepted") is True)
            trusted_here = trust_parent or accepted or confidence >= 85 or score >= 90

            for key, value in node.items():
                key_str = str(key)

                if key_str in text_keys and trusted_here:
                    text_value = _amir_clean_text(value)

                    for word in _amir_words(text_value):
                        text_counter[_amir_root(word)] += 1

                if key_str in trait_keys and trusted_here:
                    if isinstance(value, list):
                        for item in value:
                            for word in _amir_words(item):
                                text_counter[_amir_root(word)] += 1
                    else:
                        for word in _amir_words(value):
                            text_counter[_amir_root(word)] += 1

                visit(value, trust_parent=trusted_here)

        elif isinstance(node, list):
            for item in node:
                visit(item, trust_parent=trust_parent)

    visit(payload)

    for root, count in text_counter.items():
        if count >= 2:
            trusted_roots.add(root)

    return trusted_roots


def _amir_trusted_evidence_roots(row, cols: set[str], subject_core: str, place: str, context: str) -> set[str]:
    ignored = {
        "canon",
        "eos",
        "r5",
        "mark",
        "ii",
        "photography",
        "photo",
        "image",
        "picture",
        "jpg",
        "jpeg",
        "png",
        "nature",
        "macro",
        "cityscape",
        "landscape",
        "architecture",
        "miscellaneous",
        "flower",
    }

    roots: set[str] = set()

    trusted_values = [
        subject_core,
        place,
        context,
        row["Subject"] if "Subject" in cols else "",
        row["final_subject"] if "final_subject" in cols else "",
        row["File_Name"] if "File_Name" in cols else "",
        row["Original_File_Name"] if "Original_File_Name" in cols else "",
    ]

    for value in trusted_values:
        for word in _amir_words(value):
            root = _amir_root(word)

            if root and root not in ignored:
                roots.add(root)

    # identifier_subject is trusted only if confidence is high.
    try:
        identifier_confidence = int(float(row["identifier_confidence"] if "identifier_confidence" in cols else 0))
    except Exception:
        identifier_confidence = 0

    if identifier_confidence >= 85 and "identifier_subject" in cols:
        for word in _amir_words(row["identifier_subject"]):
            root = _amir_root(word)

            if root and root not in ignored:
                roots.add(root)

    # Raw JSON is trusted only for structured/high confidence/repeated evidence.
    if "identifier_raw_json" in cols:
        roots.update(_amir_collect_structured_identifier_roots(row["identifier_raw_json"]))

    return roots


def _amir_has_unsupported_interaction(value: object, trusted_roots: set[str]) -> bool:
    import re

    text = str(value or "").lower().replace("_", " ").replace("-", " ")

    if not text:
        return False

    # Strong interaction/action patterns only.
    # This avoids blocking normal background context like "cars in the background".
    patterns = [
        r"\b(?P<object>[a-z][a-z ]{1,32})\s+(?:on|onto|holding|feeding|flying|landing|perched|sitting|standing|walking|riding|driving|carrying|wearing)\b",
        r"\b(?:with|featuring|including)\s+(?P<object>[a-z][a-z ]{1,32})\b",
    ]

    safe_roots = {
        "background",
        "blur",
        "field",
        "tone",
        "sky",
        "cloud",
        "water",
        "road",
        "street",
        "park",
        "branch",
        "blossom",
        "flower",
        "tree",
        "leaf",
        "leafe",
        "roof",
        "rooftop",
        "detail",
        "composition",
        "silhouette",
        "reflection",
    }

    ignored = {
        "soft",
        "shallow",
        "gentle",
        "natural",
        "clear",
        "visible",
        "delicate",
        "minimal",
        "broad",
        "quiet",
        "calm",
        "fine",
        "close",
        "white",
        "black",
        "blue",
        "green",
        "yellow",
        "red",
        "purple",
        "pink",
        "orange",
        "brown",
        "grey",
        "gray",
        "cloudy",
    }

    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            object_text = match.group("object")
            roots = [
                _amir_root(word)
                for word in _amir_words(object_text)
                if _amir_root(word)
            ]

            risky_roots = [
                root
                for root in roots
                if root not in trusted_roots
                and root not in safe_roots
                and root not in ignored
            ]

            if risky_roots:
                return True

    return False


def _amir_bad_caption_or_alt(value: object, trusted_roots: set[str]) -> bool:
    import re

    text = str(value or "").strip()
    lower = text.lower()

    if not text:
        return True

    if _amir_contains_cjk(text):
        return True

    if "_" in text:
        return True

    if len(text.split()) < 8:
        return True

    if _amir_has_unsupported_interaction(text, trusted_roots):
        return True

    bad_patterns = [
        r"\bin\s+with\b",
        r"^of\s+",
        r"\bshowing\s+showing\b",
        r"\bshowing\s+[a-z]+\s+showing\b",
        r"\bshowing\s+pointed\b",
        r"\brooftop\s+showing\b",
        r"\bstructure\s+against\b",
        r"\bcaption\s*:",
        r"\balt\s*:",
    ]

    if any(re.search(pattern, lower, flags=re.IGNORECASE) for pattern in bad_patterns):
        return True

    bad_bits = [
        "canon eos",
        "r5 mark",
        "flower photography nature photography",
        "nature photography canon",
        "photography canon",
        "showing natural detail and outdoor context",
        "clear visual detail and surrounding context",
    ]

    return any(bit in lower for bit in bad_bits)


def _amir_bad_keywords(value: object, trusted_roots: set[str]) -> bool:
    text = str(value or "").strip()

    if not text:
        return True

    if _amir_contains_cjk(text):
        return True

    if _amir_has_unsupported_interaction(text, trusted_roots):
        return True

    items = [
        item.strip().lower()
        for item in text.split(",")
        if item.strip()
    ]

    if len(items) < 5:
        return True

    bad_start_words = {
        "showing",
        "against",
        "distant",
        "visible",
        "appearing",
        "view",
    }

    bad_fragments = [
        "showing pointed",
        "rooftop showing",
        "roof against",
        "against cloudy",
        "distant pointed",
        "distant netherlands",
        "in with",
        "of cherry",
    ]

    for item in items:
        words = item.split()

        if not words:
            return True

        if words[0] in bad_start_words:
            return True

        if any(fragment in item for fragment in bad_fragments):
            return True

    root_keys = [
        " ".join(_amir_root(word) for word in item.split())
        for item in items
    ]

    return len(set(root_keys)) < max(8, int(len(root_keys) * 0.70))


def _amir_add_keyword(items: list[str], value: str, max_words: int = 4) -> None:
    import re

    value = re.sub(r"\s+", " ", str(value or "")).strip(" ,.;:-").lower()

    if not value:
        return

    words = value.split()

    banned_single = {
        "natural",
        "outdoor",
        "outdoors",
        "detail",
        "details",
        "context",
        "showing",
        "visible",
        "photography",
        "photo",
        "image",
        "picture",
        "canon",
        "eos",
        "mark",
        "distant",
        "against",
    }

    if len(words) == 1 and words[0] in banned_single:
        return

    if len(words) > max_words:
        return

    if words[0] in {"showing", "against", "visible", "appearing"}:
        return

    root_key = " ".join(_amir_root(word) for word in words)

    existing_root_keys = {
        " ".join(_amir_root(word) for word in item.split())
        for item in items
    }

    if root_key not in existing_root_keys:
        items.append(value)


def _amir_keyword_list(subject_core: str, place: str, context: str, seq: int, folder: str = "", trusted_roots: set[str] | None = None) -> str:
    banned = {
        "a",
        "an",
        "and",
        "at",
        "by",
        "for",
        "from",
        "in",
        "into",
        "is",
        "it",
        "of",
        "on",
        "or",
        "the",
        "to",
        "with",
        "visible",
        "showing",
        "surrounding",
        "context",
        "clear",
        "detail",
        "details",
        "photographed",
        "photography",
        "photo",
        "image",
        "picture",
        "canon",
        "eos",
        "mark",
        "r5",
        "ii",
        "natural",
        "outdoor",
        "outdoors",
        "against",
    }

    subject_tokens = [
        token.lower()
        for token in _amir_words(subject_core)
        if len(token) > 2 and token.lower() not in banned
    ]

    place_tokens = [
        token.lower()
        for token in _amir_words(place)
        if len(token) > 2 and token.lower() not in banned
    ]

    context_tokens = [
        token.lower()
        for token in _amir_words(context)
        if len(token) > 2 and token.lower() not in banned
    ]

    items: list[str] = []

    _amir_add_keyword(items, subject_core)

    if place:
        _amir_add_keyword(items, place)

    for size in [2, 3]:
        for index in range(0, max(0, len(subject_tokens) - size + 1)):
            _amir_add_keyword(items, " ".join(subject_tokens[index:index + size]))

    for token in subject_tokens:
        _amir_add_keyword(items, token)

    for size in [2]:
        for index in range(0, max(0, len(place_tokens) - size + 1)):
            _amir_add_keyword(items, " ".join(place_tokens[index:index + size]))

    for token in place_tokens:
        _amir_add_keyword(items, token)

    if context:
        _amir_add_keyword(items, context)

    for token in context_tokens:
        _amir_add_keyword(items, token)


    knowledge_terms = _amir_knowledge_fetch_terms(
        subject_core=subject_core,
        place=place,
        context=context,
        folder=folder,
        trusted_roots=trusted_roots or set(),
        limit=5,
    )

    for term in knowledge_terms:
        _amir_add_keyword(items, term)

    return ", ".join(items[:8])


def _amir_sentence_pair(subject_core: str, place: str, seq: int) -> tuple[str, str]:
    return "", ""


def _amir_repair_prefill_rows() -> int:
    import sqlite3

    db_path = _amir_review_db_path()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(review_queue)").fetchall()
        }

        required = {"id", "Subject", "Location", "Folder", "Caption", "alt_text", "Keywords", "File_Name"}

        if not required.issubset(cols):
            return 0

        rows = conn.execute(
            """
            SELECT *
            FROM review_queue
            WHERE COALESCE(Review_Status, '') IN ('', 'Queued', 'Pending')
            ORDER BY id
            """
        ).fetchall()

        repaired = 0

        for index, row in enumerate(rows, start=1):
            raw_subject = (
                str(row["final_subject"] if "final_subject" in cols else "").strip()
                or str(row["Subject"] or "").strip()
            )

            # Do not use ai_suggested_subject as trusted repair source.
            if not raw_subject:
                continue

            subject_core, place_from_subject = _amir_split_subject_place(raw_subject)
            place = place_from_subject or _amir_place_from_filename(row["File_Name"], subject_core)

            raw_context = str(row["Location"] or "").strip()
            context = _amir_clean_text(raw_context) if _amir_is_context_bucket(raw_context) else ""

            if not subject_core:
                continue

            trusted_roots = _amir_trusted_evidence_roots(row, cols, subject_core, place, context)

            current_caption = row["Caption"]
            current_alt = row["alt_text"]
            current_keywords = row["Keywords"]

            needs_repair = (
                _amir_bad_caption_or_alt(current_caption, trusted_roots)
                or _amir_bad_caption_or_alt(current_alt, trusted_roots)
                or _amir_bad_keywords(current_keywords, trusted_roots)
            )

            if needs_repair:
                continue

            clean_subject_slug = _amir_slug(subject_core)

            if str(row["Subject"] or "") == clean_subject_slug:
                continue

            conn.execute(
                """
                UPDATE review_queue
                SET Subject = ?,
                    Review_Status = 'Pending'
                WHERE id = ?
                """,
                (clean_subject_slug, row["id"]),
            )

            repaired += 1

        conn.commit()

        if repaired:
            print(f"[WARN] Evidence based metadata repair updated {repaired} row(s).")

        return repaired
    finally:
        conn.close()
# AMIR_REVAMP_KNOWLEDGE_KEYWORDS_START
# Generic revamp_knowledge.db keyword enrichment.
# Uses curated/local DB terms as supporting metadata terms.
# Does not trust AI suggested subject.
# Does not patch per subject/topic/image.

def _amir_knowledge_db_path() -> str:
    import os

    data_dir = globals().get("DATA_DIR", os.path.join(os.getcwd(), "data"))
    return os.path.join(str(data_dir), "revamp_knowledge.db")


def _amir_knowledge_normalize(value: object) -> str:
    import re

    text = str(value or "").lower().replace("_", " ").replace("-", " ")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _amir_knowledge_term_ok(term: object, trusted_roots: set[str]) -> bool:
    text = _amir_knowledge_normalize(term)

    if not text:
        return False

    words = text.split()

    if len(words) > 4:
        return False

    banned_words = {
        "canon",
        "eos",
        "mark",
        "photography",
        "photo",
        "image",
        "picture",
        "stunning",
        "beautiful",
        "amazing",
        "breathtaking",
        "mesmerizing",
        "dutch",
        "photographer",
        "amir",
        "darzi",
        "website",
        "against",
        "showing",
        "visible",
        "distant",
    }

    if any(word in banned_words for word in words):
        return False

    roots = {_amir_root(word) for word in words if len(word) > 2}

    if not roots:
        return False

    # A DB term must overlap trusted evidence, unless it is a safe descriptive stock keyword.
    safe_descriptive = {
        "background",
        "blur",
        "soft",
        "detail",
        "composition",
        "seasonal",
        "close",
        "foreground",
        "sky",
        "cloud",
        "water",
        "reflection",
        "urban",
        "architectural",
        "nature",
        "plant",
        "botanical",
        "flower",
        "branch",
        "blossom",
        "tree",
        "roof",
        "rooftop",
    }

    if roots & trusted_roots:
        return True

    if roots & safe_descriptive:
        return True

    return False


def _amir_knowledge_fetch_terms(
    subject_core: str,
    place: str,
    context: str,
    folder: str,
    trusted_roots: set[str],
    limit: int = 12,
) -> list[str]:
    import os
    import sqlite3

    db_path = _amir_knowledge_db_path()

    if not os.path.exists(db_path):
        return []

    query_text = " ".join(
        part
        for part in [
            subject_core,
            place,
            context,
            folder,
        ]
        if part
    )

    roots = [
        _amir_root(word)
        for word in _amir_words(query_text)
        if len(_amir_root(word)) >= 4
    ]

    roots = [
        root
        for root in roots
        if root not in {
            "canon",
            "eos",
            "mark",
            "photography",
            "photo",
            "image",
            "picture",
            "nature",
            "macro",
            "cityscape",
            "landscape",
            "miscellaneou",
        }
    ]

    if not roots:
        return []

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        blocked = set()

        for table, col in [
            ("mysql_blocked_terms", "normalized"),
            ("mysql_raw_keyword_blocked_supertags", "term_norm"),
        ]:
            try:
                for row in conn.execute(f"SELECT {col} AS term FROM {table}").fetchall():
                    for word in _amir_words(row["term"]):
                        blocked.add(_amir_root(word))
            except Exception:
                pass

        results: list[tuple[float, str]] = []
        seen_norms: set[str] = set()

        def add_result(score: float, term: object) -> None:
            text = str(term or "").strip()

            if not text:
                return

            norm = _amir_knowledge_normalize(text)

            if not norm or norm in seen_norms:
                return

            if _amir_knowledge_location_expansion_bad(norm, subject_core, place, context, folder):
                return

            term_roots = {_amir_root(word) for word in _amir_words(norm)}

            if term_roots & blocked:
                return

            if not _amir_knowledge_term_ok(norm, trusted_roots):
                return

            seen_norms.add(norm)
            results.append((score, text))

        # 1. Curated MySQL keyword terms, small table, high trust.
        for root in roots[:8]:
            like = f"%{root}%"

            try:
                rows = conn.execute(
                    """
                    SELECT
                        term,
                        term_norm,
                        kind,
                        CAST(commercial_weight AS REAL) AS commercial_weight,
                        CAST(precision_weight AS REAL) AS precision_weight,
                        CAST(allow_in_supertags AS INTEGER) AS allow_in_supertags
                    FROM mysql_raw_keyword_terms
                    WHERE active = '1'
                      AND term_norm LIKE ?
                    ORDER BY
                        allow_in_supertags DESC,
                        precision_weight DESC,
                        commercial_weight DESC
                    LIMIT 30
                    """,
                    (like,),
                ).fetchall()

                for row in rows:
                    score = float(row["precision_weight"] or 0) + float(row["commercial_weight"] or 0)
                    add_result(score + 1000, row["term"])
            except Exception:
                pass

        # 2. Candidate visual terms, useful for visual vocabulary.
        for root in roots[:8]:
            like = f"%{root}%"

            try:
                rows = conn.execute(
                    """
                    SELECT
                        display_term,
                        normalized,
                        best_source,
                        best_kind,
                        score,
                        source_count
                    FROM revamp_candidate_terms
                    WHERE normalized LIKE ?
                    ORDER BY score DESC, source_count DESC
                    LIMIT 40
                    """,
                    (like,),
                ).fetchall()

                for row in rows:
                    add_result(float(row["score"] or 0), row["display_term"])
            except Exception:
                pass

        # 3. Gallery folder keywords, useful as safe context.
        folder_norm = _amir_knowledge_normalize(folder)

        if folder_norm:
            try:
                rows = conn.execute(
                    """
                    SELECT Keywords
                    FROM mysql_raw_revamp_gallery_meta
                    WHERE lower(Folder) = lower(?)
                    LIMIT 1
                    """,
                    (folder,),
                ).fetchall()

                for row in rows:
                    for item in str(row["Keywords"] or "").split(","):
                        add_result(500, item.strip())
            except Exception:
                pass

        results.sort(key=lambda item: item[0], reverse=True)

        final: list[str] = []

        for _score, term in results:
            norm = _amir_knowledge_normalize(term)

            if norm not in {_amir_knowledge_normalize(existing) for existing in final}:
                final.append(term)

            if len(final) >= limit:
                break

        return final

    finally:
        conn.close()
# AMIR_KNOWLEDGE_LOCATION_EXPANSION_GUARD_START
# Generic guard against DB over-expansion from weak place words.
# Example: Spaarnwoude Park must not authorize glacier national park, amusement park, water park, etc.

def _amir_knowledge_location_expansion_bad(
    term: object,
    subject_core: str,
    place: str,
    context: str,
    folder: str,
) -> bool:
    term_norm = _amir_knowledge_normalize(term)
    subject_norm = _amir_knowledge_normalize(subject_core)
    place_norm = _amir_knowledge_normalize(place)
    context_norm = _amir_knowledge_normalize(context)
    folder_norm = _amir_knowledge_normalize(folder)

    if not term_norm:
        return True

    term_roots = {
        _amir_root(word)
        for word in _amir_words(term_norm)
        if len(_amir_root(word)) >= 3
    }

    subject_roots = {
        _amir_root(word)
        for word in _amir_words(subject_norm)
        if len(_amir_root(word)) >= 3
    }

    place_roots = {
        _amir_root(word)
        for word in _amir_words(place_norm)
        if len(_amir_root(word)) >= 3
    }

    context_roots = {
        _amir_root(word)
        for word in _amir_words(context_norm)
        if len(_amir_root(word)) >= 3
    }

    folder_roots = {
        _amir_root(word)
        for word in _amir_words(folder_norm)
        if len(_amir_root(word)) >= 3
    }

    exact_context = " ".join(
        part
        for part in [
            subject_norm,
            place_norm,
            context_norm,
            folder_norm,
        ]
        if part
    )

    # Exact phrase from subject/place/context is allowed.
    if term_norm and term_norm in exact_context:
        return False

    # Subject overlap is allowed.
    if term_roots & subject_roots:
        return False

    weak_place_roots = {
        "park",
        "city",
        "town",
        "village",
        "street",
        "road",
        "lake",
        "river",
        "beach",
        "mountain",
        "valley",
        "canyon",
        "harbor",
        "harbour",
        "station",
        "airport",
    }

    location_roots = place_roots | context_roots | folder_roots
    only_location_overlap = bool(term_roots & location_roots) and not bool(term_roots & subject_roots)

    if only_location_overlap and term_roots & weak_place_roots:
        return True

    suspicious_place_expanders = {
        "national",
        "glacier",
        "amusement",
        "playground",
        "resort",
        "water",
        "theme",
        "zoo",
        "museum",
        "campground",
        "gate",
        "gates",
    }

    if term_roots & suspicious_place_expanders and not (term_roots & subject_roots):
        return True

    return False
# AMIR_KNOWLEDGE_LOCATION_EXPANSION_GUARD_END
# AMIR_REVAMP_KNOWLEDGE_KEYWORDS_END
# AMIR_BAD_DB_EXPANSION_FILTER_START
def _amir_filter_bad_db_expansion_keywords(value: str) -> str:
    bad_exact = {
        "glacier national park",
        "national park",
        "park gates",
        "amusement park",
        "park and playground",
        "water park",
    }

    items = []

    for item in str(value or "").split(","):
        clean = item.strip()
        norm = _amir_knowledge_normalize(clean)

        if not clean:
            continue

        if norm in bad_exact:
            continue

        items.append(clean)

    return ", ".join(items)
# AMIR_BAD_DB_EXPANSION_FILTER_END
# AMIR_EVIDENCE_METADATA_REPAIR_END


# AMIR_HINT_KEYWORDS_SOFT_EVIDENCE_V1_START
# Optional hint keywords for the current batch.
# Empty field = skipped.
# Non-empty field = soft evidence only. It helps the model, but does not force output.

import json as _amir_hint_json
import os as _amir_hint_os
import re as _amir_hint_re
import time as _amir_hint_time
from pathlib import Path as _amir_hint_Path


_AMIR_HINT_PROJECT_ROOT = _amir_hint_Path(__file__).resolve().parent
_AMIR_HINT_DATA_DIR = _AMIR_HINT_PROJECT_ROOT / "data"
_AMIR_HINT_FILE = _AMIR_HINT_DATA_DIR / "hint_keywords_pending.json"


def _amir_hint_clean(value):
    text = str(value or "")
    text = text.replace("\r", " ").replace("\n", " ")
    text = _amir_hint_re.sub(r"\s+", " ", text).strip()
    return text[:500]


def _amir_hint_norm(value):
    text = str(value or "")
    text = text.replace("_", " ").replace("-", " ").lower()
    text = _amir_hint_re.sub(r"[^a-z0-9\s]", " ", text)
    text = _amir_hint_re.sub(r"\s+", " ", text).strip()
    return text


def _amir_hint_var_get(app, names):
    for name in names:
        try:
            obj = getattr(app, name, None)

            if obj is None:
                continue

            if hasattr(obj, "get"):
                value = obj.get()
            else:
                value = str(obj)

            if value:
                return str(value)
        except Exception:
            pass

    return ""


def _amir_hint_get_subject(app):
    return _amir_hint_var_get(app, ["subject_var", "subject", "subject_entry"])


def _amir_hint_get_location(app):
    return _amir_hint_var_get(app, ["location_var", "location", "location_entry"])


def _amir_hint_get_folder(app):
    return _amir_hint_var_get(app, ["folder_var", "folder", "folder_combo", "folder_combo_var"])


def _amir_hint_get_hint(app):
    try:
        return _amir_hint_clean(app.hint_keywords_var.get())
    except Exception:
        return ""


def _amir_hint_reset_file():
    _AMIR_HINT_DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "created_at": _amir_hint_time.strftime("%Y-%m-%d %H:%M:%S"),
        "items": [],
    }
    _AMIR_HINT_FILE.write_text(
        _amir_hint_json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    _amir_hint_os.environ["AMIR_HINT_KEYWORDS_FILE"] = str(_AMIR_HINT_FILE)


def _amir_hint_load_payload():
    if not _AMIR_HINT_FILE.exists():
        return {
            "created_at": _amir_hint_time.strftime("%Y-%m-%d %H:%M:%S"),
            "items": [],
        }

    try:
        payload = _amir_hint_json.loads(_AMIR_HINT_FILE.read_text(encoding="utf-8"))
    except Exception:
        payload = {}

    if not isinstance(payload, dict):
        payload = {}

    if not isinstance(payload.get("items"), list):
        payload["items"] = []

    return payload


def _amir_hint_save_for_current_set(app):
    hint = _amir_hint_get_hint(app)

    if not hint:
        _amir_hint_os.environ.pop("AMIR_CURRENT_HINT_KEYWORDS", None)
        return

    subject = _amir_hint_get_subject(app)
    location = _amir_hint_get_location(app)
    folder = _amir_hint_get_folder(app)

    payload = _amir_hint_load_payload()
    item = {
        "created_at": _amir_hint_time.strftime("%Y-%m-%d %H:%M:%S"),
        "subject": subject,
        "location": location,
        "folder": folder,
        "hint_keywords": hint,
        "subject_norm": _amir_hint_norm(subject),
        "location_norm": _amir_hint_norm(location),
        "folder_norm": _amir_hint_norm(folder),
    }

    payload["items"].append(item)

    _AMIR_HINT_DATA_DIR.mkdir(parents=True, exist_ok=True)
    _AMIR_HINT_FILE.write_text(
        _amir_hint_json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    _amir_hint_os.environ["AMIR_HINT_KEYWORDS_FILE"] = str(_AMIR_HINT_FILE)
    _amir_hint_os.environ["AMIR_CURRENT_HINT_KEYWORDS"] = hint

    try:
        print(f"[HINT] Stored optional hint keywords for set: {hint}")
    except Exception:
        pass


def _amir_hint_set_env_from_field(app):
    hint = _amir_hint_get_hint(app)

    if hint:
        _amir_hint_os.environ["AMIR_CURRENT_HINT_KEYWORDS"] = hint
        _amir_hint_os.environ["AMIR_HINT_KEYWORDS_FILE"] = str(_AMIR_HINT_FILE)
    else:
        _amir_hint_os.environ.pop("AMIR_CURRENT_HINT_KEYWORDS", None)
        _amir_hint_os.environ["AMIR_HINT_KEYWORDS_FILE"] = str(_AMIR_HINT_FILE)


def _amir_hint_apply_spell_style(app, bad=False):
    entry = getattr(app, "hint_keywords_entry", None)

    if entry is None:
        return

    try:
        entry.configure(style="AmirHintBad.TEntry" if bad else "AmirHint.TEntry")
    except Exception:
        pass


def _amir_hint_spellcheck_update(app, force=False):
    text = _amir_hint_get_hint(app)

    if not force and getattr(app, "_hint_last_spell_text", None) == text:
        return

    app._hint_last_spell_text = text

    try:
        issues = find_misspellings(text, DATA_DIR) if text else []
    except Exception as exc:
        issues = []
        try:
            app._runlog("SPELLCHECK_HINT_ERR", f"{type(exc).__name__}: {exc}")
        except Exception:
            pass

    app._hint_issues = issues
    _amir_hint_apply_spell_style(app, bool(issues))


def _amir_hint_context_menu(app, ev):
    entry = getattr(app, "hint_keywords_entry", None)

    if entry is None:
        return

    try:
        col = int(entry.index(f"@{ev.x}"))
    except Exception:
        return

    issues = getattr(app, "_hint_issues", []) or []
    hit = None

    for item in issues:
        try:
            if int(item["start"]) <= col < int(item["end"]):
                hit = item
                break
        except Exception:
            continue

    if not hit:
        _amir_hint_spellcheck_update(app, force=True)
        return

    start = int(hit.get("start") or 0)
    end = int(hit.get("end") or start)
    word = str(hit.get("word") or "").strip()
    sug = str(hit.get("suggestion") or "").strip()

    if not word:
        return

    menu = tk.Menu(app.root, tearoff=0)

    def do_replace():
        if not sug:
            return

        current = _amir_hint_get_hint(app)
        app.hint_keywords_var.set(f"{current[:start]}{sug}{current[end:]}")
        _amir_hint_spellcheck_update(app, force=True)

    def do_keep():
        try:
            ok = add_spell_exception(word, DATA_DIR)
        except Exception:
            ok = False

        if ok:
            try:
                app._runlog("SPELL_KEEP_HINT", word)
            except Exception:
                pass
            _amir_hint_spellcheck_update(app, force=True)

    if sug:
        menu.add_command(label=f"Replace with: {sug}", command=do_replace)

    menu.add_command(label=f"Keep term (add to exceptions): {word}", command=do_keep)
    menu.tk_popup(ev.x_root, ev.y_root)


def _amir_hint_install_gui_patch():
    import tkinter as _amir_hint_tk
    from tkinter import ttk as _amir_hint_ttk

    add_method_name = "_add_current_set"
    start_method_name = "proceed"

    for cls in list(globals().values()):
        if not isinstance(cls, type):
            continue

        if not hasattr(cls, add_method_name):
            continue

        if getattr(cls, "_amir_hint_keywords_patch_installed", False):
            continue

        original_init = getattr(cls, "__init__", None)
        original_add = getattr(cls, add_method_name)

        def patched_init(self, *args, __original_init=original_init, **kwargs):
            __original_init(self, *args, **kwargs)

            if getattr(self, "_amir_hint_ui_ready", False):
                return

            try:
                if not _AMIR_HINT_FILE.exists():
                    _amir_hint_reset_file()
            except Exception as exc:
                print(f"[WARN] Could not reset hint keyword file: {exc}")

            try:
                self.hint_keywords_var = _amir_hint_tk.StringVar()
                self._hint_last_spell_text = None
                self._hint_issues = []

                parent = None

                for attr in ["ai_subject_regen_btn", "ai_subject_btn"]:
                    widget = getattr(self, attr, None)

                    if widget is not None:
                        parent = getattr(widget, "master", None)
                        break

                if parent is None:
                    return

                self.hint_keywords_label = _amir_hint_ttk.Label(
                    parent,
                    text="Hint keywords:",
                )
                self.hint_keywords_label.pack(side="left", padx=(16, 4))

                self.hint_keywords_entry = _amir_hint_ttk.Entry(
                    parent,
                    textvariable=self.hint_keywords_var,
                    width=42,
                )
                self.hint_keywords_entry.pack(side="left", padx=(0, 8))

                try:
                    style = _amir_hint_ttk.Style()
                    style.configure("AmirHint.TEntry")
                    style.configure(
                        "AmirHintBad.TEntry",
                        foreground="#c00000",
                        fieldbackground="#fff2f2",
                    )
                    self.hint_keywords_entry.configure(style="AmirHint.TEntry")
                except Exception:
                    pass

                try:
                    self.hint_keywords_var.trace_add(
                        "write",
                        lambda *_args, _self=self: _amir_hint_spellcheck_update(_self),
                    )
                except Exception:
                    pass

                self.hint_keywords_entry.bind(
                    "<KeyRelease>",
                    lambda _ev, _self=self: _amir_hint_spellcheck_update(_self),
                    add="+",
                )
                self.hint_keywords_entry.bind(
                    "<FocusOut>",
                    lambda _ev, _self=self: _amir_hint_spellcheck_update(_self, force=True),
                    add="+",
                )
                self.hint_keywords_entry.bind(
                    "<Button-3>",
                    lambda ev, _self=self: _amir_hint_context_menu(_self, ev),
                    add="+",
                )

                self._amir_hint_ui_ready = True
                print("[HINT] Optional Hint keywords field added.")
            except Exception as exc:
                print(f"[WARN] Could not add Hint keywords field: {exc}")

        def patched_add(self, *args, __original_add=original_add, **kwargs):
            _amir_hint_spellcheck_update(self, force=True)
            _amir_hint_save_for_current_set(self)
            return __original_add(self, *args, **kwargs)

        setattr(cls, "__init__", patched_init)
        setattr(cls, add_method_name, patched_add)

        if hasattr(cls, "_ai_suggest_subject_for_current"):
            original_ai = getattr(cls, "_ai_suggest_subject_for_current")

            def patched_ai(self, *args, __original_ai=original_ai, **kwargs):
                _amir_hint_set_env_from_field(self)
                return __original_ai(self, *args, **kwargs)

            setattr(cls, "_ai_suggest_subject_for_current", patched_ai)

        if start_method_name and hasattr(cls, start_method_name):
            original_start = getattr(cls, start_method_name)

            def patched_start(self, *args, __original_start=original_start, **kwargs):
                _amir_hint_os.environ["AMIR_HINT_KEYWORDS_FILE"] = str(_AMIR_HINT_FILE)
                return __original_start(self, *args, **kwargs)

            setattr(cls, start_method_name, patched_start)

        setattr(cls, "_amir_hint_keywords_patch_installed", True)
        print(f"[HINT] Hint keywords patch installed on {cls.__name__}.")
        break


_amir_hint_install_gui_patch()
# AMIR_HINT_KEYWORDS_SOFT_EVIDENCE_V1_END

# AMIR_FORCE_REGENERATE_ALTERNATE_ROUTE_V1_START
# Force the Regenerate subject button to use the alternate model route.
# Normal AI suggest remains image-only.
# Regenerate must set AMIR_SUBJECT_MODEL_MODE=regenerate_alt so make_model_list()
# returns the configured light vision alternate first, then fallback models.

import os as _amir_regen_route_os


def _amir_regen_route_install():
    for cls in list(globals().values()):
        if not isinstance(cls, type):
            continue

        if not hasattr(cls, "_ai_suggest_subject_for_current"):
            continue

        if getattr(cls, "_amir_regen_route_patch_installed", False):
            continue

        original_init = getattr(cls, "__init__", None)
        original_ai = getattr(cls, "_ai_suggest_subject_for_current")

        def patched_ai(self, *args, __original_ai=original_ai, **kwargs):
            regenerate = bool(kwargs.get("regenerate", False))

            if regenerate:
                _amir_regen_route_os.environ["AMIR_SUBJECT_MODEL_MODE"] = "regenerate_alt"
                _amir_regen_route_os.environ["AMIR_SUBJECT_FORCE_MODEL"] = _amir_regen_route_os.environ.get(
                    "AMIR_SUBJECT_REGENERATE_MODEL",
                    "qwen3-vl:4b",
                )
                print(f"[SUBJECT AI] regenerate route forced: {_amir_regen_route_os.environ['AMIR_SUBJECT_FORCE_MODEL']}")
            else:
                # Newer context-file regenerate wrapper calls through with
                # regenerate=False to avoid old hint-copy behavior. In that
                # case, do not clear the active forced model route.
                if _amir_regen_route_os.environ.get("AMIR_SUBJECT_REGENERATE", "").strip() != "1":
                    _amir_regen_route_os.environ.pop("AMIR_SUBJECT_MODEL_MODE", None)
                    _amir_regen_route_os.environ.pop("AMIR_SUBJECT_FORCE_MODEL", None)

            return __original_ai(self, *args, **kwargs)

        def patched_init(self, *args, __original_init=original_init, **kwargs):
            __original_init(self, *args, **kwargs)

            try:
                btn = getattr(self, "ai_subject_regen_btn", None)

                if btn is not None:
                    btn.configure(
                        command=lambda: self._ai_suggest_subject_for_current(regenerate=True)
                    )
                    print("[SUBJECT AI] Regenerate button command forced to alternate route.")
            except Exception as exc:
                print(f"[WARN] Could not force regenerate button route: {exc}")

        setattr(cls, "_ai_suggest_subject_for_current", patched_ai)
        setattr(cls, "__init__", patched_init)
        setattr(cls, "_amir_regen_route_patch_installed", True)

        print(f"[SUBJECT AI] Regenerate route patch installed on {cls.__name__}.")
        break


_amir_regen_route_install()
# AMIR_FORCE_REGENERATE_ALTERNATE_ROUTE_V1_END




# AMIR_HINT_KEYWORDS_CLEAR_AFTER_ADD_V1_START
# Hint keywords are optional.
# They are used only when Regenerate subject is clicked and the field is non-empty.
# After Add set, clear the field so hints cannot leak into the next set.

def _amir_clear_hint_keywords_after_add_install():
    for cls in list(globals().values()):
        if not isinstance(cls, type):
            continue

        if getattr(cls, "_amir_clear_hint_after_add_installed", False):
            continue

        add_method_name = None

        for name in dir(cls):
            if "add" in name.lower() and "set" in name.lower():
                attr = getattr(cls, name, None)

                if callable(attr):
                    add_method_name = name
                    break

        if not add_method_name:
            continue

        original_add = getattr(cls, add_method_name)

        def patched_add(self, *args, __original_add=original_add, **kwargs):
            result = __original_add(self, *args, **kwargs)

            try:
                if hasattr(self, "hint_keywords_var"):
                    self.hint_keywords_var.set("")
                    print("[HINT] Cleared optional Hint keywords after Add set.")
            except Exception as exc:
                print(f"[WARN] Could not clear Hint keywords: {exc}")

            return result

        setattr(cls, add_method_name, patched_add)
        setattr(cls, "_amir_clear_hint_after_add_installed", True)

        print(f"[HINT] Optional Hint keywords clear-after-add installed on {cls.__name__}.")
        break


_amir_clear_hint_keywords_after_add_install()
# AMIR_HINT_KEYWORDS_CLEAR_AFTER_ADD_V1_END







# AMIR_PROPER_SUBJECT_REGENERATE_SYSTEM_V2_START
# Correct subject system:
# AI suggest = image only.
# Regenerate without hints = image only, alternate model route.
# Regenerate with hints = image + soft hints through model.
# Hints are passed through data/subject_regenerate_context.json.
# Hints are never copied directly and never written into Folder.

def _amir_subject_v2_context_path():
    from pathlib import Path

    root = Path.cwd()
    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    return data_dir / "subject_regenerate_context.json"


def _amir_subject_v2_get_var(app, names):
    for name in names:
        obj = getattr(app, name, None)

        if obj is None:
            continue

        try:
            if hasattr(obj, "get"):
                value = obj.get()
            else:
                value = str(obj)

            value = str(value or "").strip()

            if value:
                return value
        except Exception:
            pass

    return ""


def _amir_subject_v2_get_hints(app):
    return _amir_subject_v2_get_var(app, ["hint_keywords_var"])


def _amir_subject_v2_get_current_subject(app):
    try:
        getter = getattr(app, "_subject_get", None)

        if callable(getter):
            value = str(getter() or "").strip()

            if value:
                return value
    except Exception:
        pass

    return _amir_subject_v2_get_var(
        app,
        [
            "subject_var",
            "subject_text_var",
            "subject_value",
            "subject_input_var",
        ],
    )


def _amir_subject_v2_write_context(active, hints="", current_subject=""):
    import json
    import time

    path = _amir_subject_v2_context_path()

    payload = {
        "active": bool(active),
        "hints": str(hints or "").strip(),
        "current_subject": str(current_subject or "").strip(),
        "created_at": time.time(),
    }

    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return path


def _amir_subject_v2_install():
    import os

    for cls in list(globals().values()):
        if not isinstance(cls, type):
            continue

        if not hasattr(cls, "_ai_suggest_subject_for_current"):
            continue

        if getattr(cls, "_amir_subject_regenerate_system_v2_installed", False):
            continue

        original_ai = getattr(cls, "_ai_suggest_subject_for_current")

        def patched_ai(self, *args, __original_ai=original_ai, **kwargs):
            regenerate = bool(kwargs.get("regenerate", False))
            identify = bool(kwargs.get("identify", False))

            if args and isinstance(args[0], bool):
                regenerate = bool(args[0])

            hints = _amir_subject_v2_get_hints(self)
            current_subject = _amir_subject_v2_get_current_subject(self)
            context_file = str(_amir_subject_v2_context_path())

            old_env = {
                "AMIR_SUBJECT_CONTEXT_FILE": os.environ.get("AMIR_SUBJECT_CONTEXT_FILE"),
                "AMIR_SUBJECT_REGENERATE": os.environ.get("AMIR_SUBJECT_REGENERATE"),
                "AMIR_SUBJECT_FORCE_MODEL": os.environ.get("AMIR_SUBJECT_FORCE_MODEL"),
                "AMIR_SUBJECT_MODEL_MODE": os.environ.get("AMIR_SUBJECT_MODEL_MODE"),
                "AMIR_SUBJECT_IGNORE_SUBJECT_HINT": os.environ.get("AMIR_SUBJECT_IGNORE_SUBJECT_HINT"),
                "AMIR_SUBJECT_IDENTIFY_MODE": os.environ.get("AMIR_SUBJECT_IDENTIFY_MODE"),
            }

            try:
                os.environ["AMIR_SUBJECT_CONTEXT_FILE"] = context_file

                if identify:
                    _amir_subject_v2_write_context(
                        active=False,
                        hints="",
                        current_subject="",
                    )

                    print("[SUBJECT AI] Identify: strict living/macro identifier mode")

                elif regenerate:
                    os.environ["AMIR_SUBJECT_REGENERATE"] = "1"
                    os.environ["AMIR_SUBJECT_FORCE_MODEL"] = os.environ.get(
                        "AMIR_SUBJECT_REGENERATE_MODEL",
                        "qwen3-vl:4b",
                    )
                    os.environ["AMIR_SUBJECT_MODEL_MODE"] = "regenerate_alt"
                    os.environ["AMIR_SUBJECT_IGNORE_SUBJECT_HINT"] = "1"

                    _amir_subject_v2_write_context(
                        active=True,
                        hints=hints,
                        current_subject=current_subject,
                    )

                    if hints:
                        print(f"[SUBJECT AI] Regenerate: image + soft hints via context file | hints={hints}")
                    else:
                        print("[SUBJECT AI] Regenerate: image only alternate model via context file")

                    # Prevent old alternate route logic from copy/pasting hints.
                    if args and isinstance(args[0], bool):
                        args = (False,) + tuple(args[1:])
                    else:
                        kwargs["regenerate"] = False

                else:
                    os.environ.pop("AMIR_SUBJECT_REGENERATE", None)
                    os.environ.pop("AMIR_SUBJECT_FORCE_MODEL", None)
                    os.environ.pop("AMIR_SUBJECT_MODEL_MODE", None)
                    os.environ.pop("AMIR_SUBJECT_IGNORE_SUBJECT_HINT", None)
                    os.environ.pop("AMIR_SUBJECT_IDENTIFY_MODE", None)

                    _amir_subject_v2_write_context(
                        active=False,
                        hints="",
                        current_subject="",
                    )

                    print("[SUBJECT AI] AI suggest: image only")

                return __original_ai(self, *args, **kwargs)

            finally:
                if regenerate:
                    # The original method starts a background worker thread.
                    # Keep regenerate env/context alive until that worker has
                    # called the subject identifier, then the worker clears it.
                    pass
                else:
                    _amir_subject_v2_write_context(
                        active=False,
                        hints="",
                        current_subject="",
                    )

                    for key, value in old_env.items():
                        if value is None:
                            os.environ.pop(key, None)
                        else:
                            os.environ[key] = value

        setattr(cls, "_ai_suggest_subject_for_current", patched_ai)
        setattr(cls, "_amir_subject_regenerate_system_v2_installed", True)

        print(f"[SUBJECT AI] Proper regenerate context-file system installed on {cls.__name__}.")
        break


_amir_subject_v2_install()
# AMIR_PROPER_SUBJECT_REGENERATE_SYSTEM_V2_END

# AMIR_METADATA_AUTO_REPAIR_MAINSET_V1_START
# Run deterministic metadata auto repair after prefill/evidence cleanup and before quality gate.
# This is not NEEDS_MANUAL. This repairs weak generated metadata automatically.

def _amir_run_metadata_auto_repair_loop(db_path=None, py=None):
    import subprocess
    import sys
    from pathlib import Path

    root = Path(APP_DIR).resolve()
    try:
        script = Path(_prepare_external_script(os.path.join("scripts", "metadata_auto_repair_loop.py")))
    except Exception:
        script = root / "scripts" / "metadata_auto_repair_loop.py"
    db = Path(db_path or DB_PATH).resolve()
    python_exe = py or sys.executable

    if not script.exists():
        print(f"[WARN] Metadata auto repair script missing: {script}")
        return

    print("[AUTO-REPAIR] Running deterministic metadata compiler before quality gate...")

    result = subprocess.run(
        [
            python_exe,
            "-u",
            str(script),
            "--db",
            str(db),
            "--table",
            "review_queue",
            "--status-col",
            "Review_Status",
            "--statuses",
            "Pending,Queued",
        ],
        cwd=str(root),
        text=True,
        capture_output=True,
        env={
            **os.environ,
            "AMIR_PROJECT_ROOT": str(root),
            "AMIR_REVIEW_DB": str(db),
        },
    )

    if result.stdout:
        print(result.stdout.rstrip())

    if result.stderr:
        print(result.stderr.rstrip())

    if result.returncode != 0:
        raise RuntimeError(f"Metadata auto repair failed with rc={result.returncode}")
# AMIR_METADATA_AUTO_REPAIR_MAINSET_V1_END


# AMIR_AUTO_SPLIT_EMPTY_SUBJECT_V1_START
# Generic no-manual fallback:
# if a multi-image selection has no safe common subject, split it into
# per-image sets instead of using the first image's subject for every row.
def _amir_auto_split_empty_subject_install():
    for cls in list(globals().values()):
        if not isinstance(cls, type):
            continue

        if getattr(cls, "_amir_auto_split_empty_subject_installed", False):
            continue

        if not all(hasattr(cls, name) for name in ["_add_set", "_subject_get", "_subject_set"]):
            continue

        original_add_set = getattr(cls, "_add_set")

        def patched_add_set(self, files, *args, __original_add_set=original_add_set, **kwargs):
            if os.getenv("AMIR_AUTO_SPLIT_MIXED_ON_EMPTY_SUBJECT", "1") != "1":
                return __original_add_set(self, files, *args, **kwargs)

            files_list = [str(path) for path in (files or []) if path and os.path.exists(str(path))]

            if len(files_list) < 2 or getattr(self, "_amir_auto_split_active", False):
                return __original_add_set(self, files, *args, **kwargs)

            try:
                current_subject = str(self._subject_get() or "").strip()
            except Exception:
                current_subject = ""

            if current_subject:
                return __original_add_set(self, files, *args, **kwargs)

            def _suggest_for_paths(paths, label):
                temp_map = {}

                try:
                    temp_map = _amir_prepare_ollama_temp_images_for_subject(paths, label=label)
                    model_paths = [
                        temp_map.get(_amir_norm_temp_source_path(path), path)
                        for path in paths
                    ]
                    subject = clean_token(ai_suggest_subject_multi(model_paths) or "")
                except Exception as exc:
                    print(f"[SUBJECT AI] auto-split suggestion failed ({label}): {type(exc).__name__}: {exc}")
                    subject = ""

                return subject, temp_map

            common_subject, common_temp_map = _suggest_for_paths(files_list, "subject_common")

            if common_subject:
                try:
                    self._last_ai_suggested_subject = common_subject
                    self._last_ai_subject_paths_sig = {self._norm_path(path) for path in files_list if path}
                    self._last_ai_subject_temp_by_original = dict(common_temp_map or {})
                    self._subject_set(common_subject)
                    print(f"[SUBJECT AI] auto-split common subject accepted: {common_subject}")
                except Exception:
                    pass

                return __original_add_set(self, files, *args, **kwargs)

            print(
                "[SUBJECT AI] auto-split | no safe common subject; "
                f"splitting {len(files_list)} image(s) into per-image sets"
            )

            previous_subject = current_subject
            previous_last_subject = str(getattr(self, "_last_ai_suggested_subject", "") or "")
            previous_last_sig = set(getattr(self, "_last_ai_subject_paths_sig", set()) or set())
            previous_last_temp = dict(getattr(self, "_last_ai_subject_temp_by_original", {}) or {})
            successes = 0
            failures = []

            self._amir_auto_split_active = True

            try:
                for index, path in enumerate(files_list, start=1):
                    subject, temp_map = _suggest_for_paths([path], f"subject_split_{index:03d}")

                    if not subject:
                        failures.append(os.path.basename(path))
                        print(f"[SUBJECT AI] auto-split skipped | no subject | {os.path.basename(path)}")
                        continue

                    try:
                        self._subject_set(subject)
                        self._last_ai_suggested_subject = subject
                        self._last_ai_subject_paths_sig = {self._norm_path(path)}
                        self._last_ai_subject_temp_by_original = dict(temp_map or {})
                    except Exception:
                        pass

                    if __original_add_set(self, [path], *args, **kwargs):
                        successes += 1
                        print(
                            "[SUBJECT AI] auto-split added "
                            f"{index}/{len(files_list)} | {os.path.basename(path)} | {subject}"
                        )
                    else:
                        failures.append(os.path.basename(path))
            finally:
                self._amir_auto_split_active = False

                try:
                    self._subject_set(previous_subject)
                except Exception:
                    pass

                self._last_ai_suggested_subject = previous_last_subject
                self._last_ai_subject_paths_sig = previous_last_sig
                self._last_ai_subject_temp_by_original = previous_last_temp

            if successes:
                if failures:
                    print(
                        "[SUBJECT AI] auto-split partial "
                        f"| added={successes} failed={len(failures)} "
                        f"| failed_files={', '.join(failures[:8])}"
                    )
                else:
                    print(f"[SUBJECT AI] auto-split complete | added={successes}")

                return True

            return __original_add_set(self, files, *args, **kwargs)

        setattr(cls, "_add_set", patched_add_set)
        setattr(cls, "_amir_auto_split_empty_subject_installed", True)
        print(f"[SUBJECT AI] Empty-subject auto-split installed on {cls.__name__}.")
        break


_amir_auto_split_empty_subject_install()
# AMIR_AUTO_SPLIT_EMPTY_SUBJECT_V1_END


if __name__ == "__main__":
    # EXE self-test: catch missing spellcheck dictionary fast after build
    if "--selftest-spellcheck" in sys.argv:
        try:
            from spellchecker import SpellChecker

            sp = SpellChecker()
            _ = sp.correction("lanscape")  # forces a dictionary lookup
            if not _:
                raise RuntimeError("SpellChecker returned empty correction")
            print("spellcheck OK")
            raise SystemExit(0)
        except Exception:
            print("missing dictionary")
            raise SystemExit(1)

    def _write_crash_log(txt: str):
        try:
            from pathlib import Path

            base = (
                Path(sys.executable).resolve().parent
                if getattr(sys, "frozen", False)
                else Path(__file__).resolve().parent
            )
            (base / "crash_startup.log").write_text(
                txt, encoding="utf-8", errors="replace"
            )
        except Exception:
            pass

    def _enable_run_log() -> None:
        """Tee stdout and stderr to a stable log file while still printing to the console."""
        try:
            from pathlib import Path

            base = (
                Path(sys.executable).resolve().parent
                if getattr(sys, "frozen", False)
                else Path(__file__).resolve().parent
            )
            log_dir = base / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / "latest_run.log"
            fp = open(log_path, "w", encoding="utf-8", buffering=1)
        except Exception:
            return

        orig_out = sys.stdout
        orig_err = sys.stderr

        class _Tee:
            def __init__(self, a, b):
                self.a = a
                self.b = b

            def write(self, s):
                try:
                    self.a.write(s)
                except Exception:
                    pass
                try:
                    self.b.write(s)
                except Exception:
                    pass

            def flush(self):
                try:
                    self.a.flush()
                except Exception:
                    pass
                try:
                    self.b.flush()
                except Exception:
                    pass

            def isatty(self):
                try:
                    return self.a.isatty()
                except Exception:
                    return False

        sys.stdout = _Tee(orig_out, fp)
        sys.stderr = _Tee(orig_err, fp)

        # Keep this minimal: it helps locate the log without spamming the UI.
        print(f"[INFO] Log file: {log_path}")

    def _install_runtime_crash_hooks():
        try:
            _prev_sys_hook = sys.excepthook
        except Exception:
            _prev_sys_hook = None

        def _sys_hook(exc_type, exc_value, exc_tb):
            _append_runtime_crash("sys_excepthook", exc_type, exc_value, exc_tb)
            if callable(_prev_sys_hook):
                try:
                    _prev_sys_hook(exc_type, exc_value, exc_tb)
                except Exception:
                    pass

        try:
            sys.excepthook = _sys_hook
        except Exception:
            pass

        if hasattr(threading, "excepthook"):
            try:
                _prev_thread_hook = threading.excepthook
            except Exception:
                _prev_thread_hook = None

            def _thread_hook(args):
                try:
                    tname = getattr(getattr(args, "thread", None), "name", "unknown")
                except Exception:
                    tname = "unknown"
                _append_runtime_crash(
                    f"thread_excepthook:{tname}",
                    getattr(args, "exc_type", Exception),
                    getattr(args, "exc_value", Exception("unknown thread error")),
                    getattr(args, "exc_traceback", None),
                )
                if callable(_prev_thread_hook):
                    try:
                        _prev_thread_hook(args)
                    except Exception:
                        pass

            try:
                threading.excepthook = _thread_hook
            except Exception:
                pass

    try:
        _enable_run_log()
        _install_runtime_crash_hooks()
        print("\n========= Amir2000 Image Automation: MULTI-SET START =========")
        print(f"[INFO] Using DB at: {DB_PATH}")
        print(f"[INFO] Using used_filenames at: {USED_NAMES}")
        _ollama_startup_probe()
        root = tk.Tk()
        app = MultiSetApp(root)
        try:
            root.mainloop()
        except KeyboardInterrupt:
            print("\n[WARN] Stopped by user (Ctrl+C). Exiting cleanly.")
            try:
                root.destroy()
            except Exception:
                pass
        print("========= Amir2000 Image Automation: MULTI-SET END =========")
    except Exception:
        _write_crash_log(traceback.format_exc())
        try:
            messagebox.showerror(
                "Startup crash",
                "The app crashed on startup.\n\nA crash log was written next to the EXE:\ncrash_startup.log",
            )
        except Exception:
            pass
        raise
