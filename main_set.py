# main_set.py — Multi-set launcher (keeps your pipeline intact)
import os, sys, json, time, shutil, sqlite3, threading, subprocess, socket, traceback, math, glob

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
from utils.autofix import autofix_subject, find_misspellings, add_spell_exception


_UDUP = re.compile(r"_+")


def clean_token(s: str) -> str:
    """For Subject/Location/Folder tokens (not full filenames)."""
    s = (s or "").strip().replace(" ", "_")
    s = _UDUP.sub("_", s)
    return s.strip("_")


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


def build_preview_filename(
    subject: str,
    location: str,
    folder: str,
    camera: str | None = None,
    year: str | int | None = None,
    index: int = 1,
) -> str:
    subject_s = slugify(subject)
    location_s = slugify(location)
    folder_s = slugify(folder)
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
    "DATA_DIR", r"C:\Users\ad341\amir2000\amir2000_image_automation\data"
)
DB_PATH = os.environ.get(
    "AMIR_REVIEW_DB", PATHS.get("REVIEW_DB_PATH", os.path.join(DATA_DIR, "review.db"))
)
INCOMING_DIR = PATHS.get(
    "INCOMING_DIR", r"C:\Users\ad341\amir2000\amir2000_image_automation\incoming"
)
LOCAL_SITE_IMAGES_BASE = PATHS.get(
    "LOCAL_SITE_IMAGES_BASE",
    r"C:\Users\ad341\amir2000\amir2000.nl\pic\images\new",
)

BASE_PICK_DIR = PATHS.get(
    "BASE_PICK_DIR", r"C:\Users\ad341\Desktop\xxx\_images to be uploaded"
)
STAGED_DIR = PATHS.get(
    "STAGED_DIR", r"C:\Users\ad341\Desktop\xxx\_images to be uploaded\staged"
)

# Keep relative “data/…” paths stable like main.py does
APP_DIR = (
    os.path.dirname(sys.executable)
    if getattr(sys, "frozen", False)
    else os.path.dirname(os.path.abspath(__file__))
)


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
    "Caption/Keywords prefill (Ollama)",
    "Open review editor",
]

TOTAL_STAGES = len(STAGES)
# ---- Ollama config for subject suggestions ----
OLLAMA_BIN = os.getenv("OLLAMA_BIN", "ollama")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "127.0.0.1")
OLLAMA_PORT = int(os.getenv("OLLAMA_PORT", "11434"))
OLLAMA_MODEL = os.getenv(
    "OLLAMA_MODEL_SUBJECT", "llama3.2-vision:latest"
)  # subject suggestions (vision)
OLLAMA_MODEL_CAPTION = os.getenv(
    "OLLAMA_MODEL_CAPTION", "minicpm-v:latest"
)  # caption/keywords/alt prefill default (better grounding for mixed sets)
SUBJECT_MODEL_CANDIDATES_ENV = os.getenv(
    "OLLAMA_MODEL_SUBJECT_CANDIDATES", f"{OLLAMA_MODEL_CAPTION},{OLLAMA_MODEL}"
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
SUBJECT_THUMB_MAX = max(640, int(os.getenv("SUBJECT_THUMB_MAX", "1344")))
SUBJECT_JPEG_QUALITY = max(
    70, min(95, int(os.getenv("SUBJECT_JPEG_QUALITY", "90")))
)
THUMB_MAX = 1024  # more detail for species and fine subjects (slower)
# Caption stage opts only (34b on 8GB GPU benefits from smaller ctx)
OLLAMA_OPTS = {
    "num_ctx": int(os.getenv("CAPTION_NUM_CTX", "3072")),
    "num_predict": int(os.getenv("CAPTION_NUM_PREDICT", "120")),
    "temperature": float(os.getenv("CAPTION_TEMPERATURE", "0.2")),
}
OLLAMA_WARM_ON_SCORING = os.getenv("OLLAMA_WARM_ON_SCORING", "1") == "1"
OLLAMA_WARM_TIMEOUT_SEC = int(os.getenv("OLLAMA_WARM_TIMEOUT_SEC", "45"))
OLLAMA_WARM_KEEP_ALIVE = os.getenv("OLLAMA_WARM_KEEP_ALIVE", "45m")

# caption_review_local.py tuning (used by Stage 6)
CAPTION_KEYWORDS_N = int(os.getenv("CAPTION_KEYWORDS_N", "15"))
CAPTION_REWRITE_WEAK = os.getenv("CAPTION_REWRITE_WEAK", "1") == "1"
CAPTION_REWRITE_MAX_PASSES = int(os.getenv("CAPTION_REWRITE_MAX_PASSES", "2"))
CAPTION_QUALITY_MIN_SCORE = int(os.getenv("CAPTION_QUALITY_MIN_SCORE", "86"))
CAPTION_SERIES_LARGE_THRESHOLD = int(os.getenv("CAPTION_SERIES_LARGE_THRESHOLD", "8"))
CAPTION_MAX_TRIES = int(os.getenv("CAPTION_MAX_TRIES", "5"))
CAPTION_PREFIX_WORDS = int(os.getenv("CAPTION_PREFIX_WORDS", "8"))
CAPTION_FAIL_ON_ROW_ERRORS = os.getenv("CAPTION_FAIL_ON_ROW_ERRORS", "0") == "1"
RESIZE_FAIL_ON_ANY = os.getenv("RESIZE_FAIL_ON_ANY", "0") == "1"

# optional precision keyword terms DB
DEFAULT_TERMS_DB = os.getenv(
    "CAPTION_TERMS_DB", r"C:\Users\ad341\amir2000\Alamy\data\alamy_local.db"
)
CAPTION_TERMS_TABLE = os.getenv("CAPTION_TERMS_TABLE", "keyword_terms")
CAPTION_TERMS_MIN_PRECISION = int(os.getenv("CAPTION_TERMS_MIN_PRECISION", "85"))


CAPTION_MAX_RETRIES = int(os.getenv("CAPTION_MAX_RETRIES", "1"))
CAPTION_TIMEOUT_SEC = int(os.getenv("CAPTION_TIMEOUT_SEC", "420"))
CAPTION_PREFILL_CHUNK_SIZE = int(os.getenv("CAPTION_PREFILL_CHUNK_SIZE", "24"))
CAPTION_NATIVE_CRASH_RETRIES = int(
    os.getenv("CAPTION_NATIVE_CRASH_RETRIES", str(max(8, CAPTION_MAX_RETRIES + 2)))
)
SESSION_SCOPE_ONLY = os.getenv("AMIR_SESSION_SCOPE_ONLY", "1") == "1"
AUTO_AI_SUBJECT_ON_SELECT = os.getenv("AUTO_AI_SUBJECT_ON_SELECT", "1") == "1"
ADD_SET_EXIF_PREVIEW = os.getenv("ADD_SET_EXIF_PREVIEW", "0") == "1"

# Stage-6 QC scan (duplicates + suspicious text) before review editor opens
PREFILL_QC_ENABLED = os.getenv("PREFILL_QC_ENABLED", "1") == "1"
PREFILL_QC_SAMPLE_IDS = max(3, int(os.getenv("PREFILL_QC_SAMPLE_IDS", "12")))
PREFILL_QC_REPORT_PATH = os.getenv(
    "PREFILL_QC_REPORT_PATH", os.path.join(DATA_DIR, "prefill_qc_last.json")
)


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


def _ensure_ollama_running():
    if _ollama_up():
        return True
    try:
        subprocess.Popen(
            [OLLAMA_BIN, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
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
        "options": {"num_predict": 8, "temperature": 0.0},
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
)
_QC_GENERIC_PHRASES = (
    "open sky",
    "clear daylight conditions",
    "natural backdrop",
    "outdoor setting",
    "scene appears",
    "scene stands",
    "scene sits",
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
        if len(kw_terms) < 10:
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
    "You are a precise subject line titler with domain awareness across: "
    "botany and entomology; birds and mammals; buildings and architecture; "
    "cars, trucks, aircraft, and boats; city and travel scenes; landscapes, weather, and night sky.\n"
    "From the selected photo or photos, output ONE concise SEO subject line. "
    "If the selection shows the same main subject in the same setting, write one line that fits the group.\n"
    "Rules: English, ASCII only. Ideal length 35 to 55 characters, max 60. "
    "Subject first, then one concrete detail. No hype. Title Case.\n"
    "If the main subject is a bird, use the specific common species name ONLY if clearly identifiable. "
    "If not certain, use a broader accurate group like Gull, Heron, Raptor, Duck, Goose, Songbird.\n"
    "Do NOT guess. Do NOT invent species.\n"
    "Do not use these words: macro, photography, photo, image, picture, shot, alt, hdr.\n"
    "Avoid locations unless readable signage is visible.\n"
    "Return ONE line only, no quotes, no punctuation, no extra text."
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
    "Classify the main visual subject in the provided image data.\n"
    "Return ONLY strict one-line JSON with this exact schema:\n"
    '{"primary_subject":"","category":"","detail":"","confidence":0}\n'
    "Rules:\n"
    "1) category must be one of: "
    "bird, mammal, plant, flower, tree, insect, reptile, fish, "
    "car, truck, motorcycle, vehicle, aircraft, boat, building, architecture, "
    "landscape, cityscape, industrial, people, food, object, other.\n"
    "2) Use common names only.\n"
    "3) Use specific species/brand/model only if clearly visible.\n"
    "4) If uncertain, keep primary_subject broad and confidence <= 60.\n"
    "5) detail should be 2 to 5 words of visible context.\n"
    "6) No markdown, no commentary, no extra keys."
)
_SUBJECT_ANALYZE_PROMPT_SINGLE = (
    _SUBJECT_ANALYZE_PROMPT_BASE + "\nThis is one photo. Return JSON only."
)
_SUBJECT_ANALYZE_PROMPT_MULTI = (
    _SUBJECT_ANALYZE_PROMPT_BASE
    + "\nThese photos are one set. Find the common main subject across the set. Return JSON only."
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
        trailing_joiners = {
            "a",
            "an",
            "and",
            "at",
            "by",
            "for",
            "from",
            "in",
            "near",
            "of",
            "on",
            "over",
            "the",
            "to",
            "under",
            "with",
        }
        cut = line[:max_chars].rstrip()
        # Avoid chopping words in the middle when we enforce max chars.
        space_at = cut.rfind(" ")
        if space_at >= max(1, int(max_chars * 0.6)):
            cut = cut[:space_at].rstrip()
        parts = cut.split()
        while len(parts) > max(1, min_words) and parts[-1].lower() in trailing_joiners:
            parts.pop()
        cut = " ".join(parts).strip()
        line = cut

    return line


def _subject_to_int(v, default: int = 0) -> int:
    try:
        n = int(float(v))
    except Exception:
        n = default
    return max(0, min(100, n))


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


def _extract_json_object(raw: str) -> dict | None:
    s = (raw or "").strip()
    if not s:
        return None
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass

    m = re.search(r"\{[\s\S]*\}", s)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


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
            "stop": ["\n"],
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
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        _LAST_OLLAMA_ERROR = f"Ollama request failed: {e}"
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
            category, _SUBJECT_CATEGORY_FALLBACK["other"]
        )

    if detail:
        pw = {w.lower() for w in primary.split()}
        dw = [w for w in detail.split() if w.lower() not in pw]
        detail = " ".join(dw).strip()

    line_raw = f"{primary} {detail}".strip() if detail else primary
    out = _normalize_subject_line(line_raw, max_chars=max_chars, max_words=None, min_words=3)
    if out:
        return out
    return _normalize_subject_line(primary, max_chars=max_chars, max_words=None, min_words=1)


def ai_suggest_subject_multi(image_paths: list[str]) -> str | None:
    """Return one subject line for a single image or a group selection."""
    global _LAST_OLLAMA_ERROR
    _LAST_OLLAMA_ERROR = ""

    paths = [p for p in (image_paths or []) if p and os.path.isfile(p)]
    if not paths:
        _LAST_OLLAMA_ERROR = "No valid image files were selected."
        return None

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

    # up to 4 images is usually enough to describe a set
    try:
        take = min(4, len(paths))
        idxs = (
            [round(i * (len(paths) - 1) / (take - 1)) for i in range(take)]
            if take > 1
            else [0]
        )
        pick = [paths[i] for i in idxs]
        imgs = [_b64_image_for_ollama(p) for p in pick]

    except Exception as e:
        _LAST_OLLAMA_ERROR = f"Failed to read image: {e}"
        return None

    timeout_sec = int(os.getenv("SUBJECT_TIMEOUT_SEC", "120"))

    # First pass: strict JSON classification for reliable category grounding.
    analysis_prompt = (
        _SUBJECT_ANALYZE_PROMPT_MULTI if len(imgs) > 1 else _SUBJECT_ANALYZE_PROMPT_SINGLE
    )
    analysis_raw = _subject_generate(
        model=subject_model,
        prompt=analysis_prompt,
        images=imgs,
        temperature=0.0,
        num_predict=180,
        timeout_sec=timeout_sec,
    )
    line = _subject_line_from_analysis(analysis_raw or "", max_chars=SUBJECT_MAX_CHARS)
    if line:
        return line

    # Fallback: free-form one-line subject prompt.
    raw = _subject_generate(
        model=subject_model,
        prompt=_SUBJECT_ROLE_PROMPT,
        images=imgs,
        temperature=0.1,
        num_predict=48,
        timeout_sec=timeout_sec,
    )
    if not raw:
        return None
    line = _normalize_subject_line(
        raw, max_chars=SUBJECT_MAX_CHARS, max_words=None, min_words=3
    )
    if not line:
        _LAST_OLLAMA_ERROR = "Model output was not usable after sanitizing."
        return None

    return line


def ai_suggest_subject(image_path: str) -> str | None:
    """Return a short subject suggestion via Ollama (vision model)."""
    global _LAST_OLLAMA_ERROR

    if not os.path.isfile(image_path):
        return None
    if not _ensure_ollama_running():
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
        num_predict=160,
        timeout_sec=timeout_sec,
    )
    line = _subject_line_from_analysis(analysis_raw or "", max_chars=SUBJECT_MAX_CHARS)
    if line:
        return line

    raw = _subject_generate(
        model=subject_model,
        prompt=_SUBJECT_ROLE_PROMPT,
        images=imgs,
        temperature=0.1,
        num_predict=40,
        timeout_sec=timeout_sec,
    )
    if not raw:
        return None
    return _normalize_subject_line(
        raw, max_chars=SUBJECT_MAX_CHARS, max_words=6, min_words=3
    )


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
    ]
    if order != target:
        print(
            "[WARN] review_queue column order differs; rebuilding table to match main.py …"
        )
        # Rebuild table with correct column order
        cur.execute(f"ALTER TABLE {TABLE_NAME} RENAME TO {TABLE_NAME}_old")
        cur.execute(
            f"""
            CREATE TABLE {TABLE_NAME}(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                Folder TEXT, File_Name TEXT, Path TEXT, ollama_path TEXT, Thumb_Path TEXT,
                DateTime TEXT, Camera TEXT, Lens_model TEXT,
                Width INTEGER, Height INTEGER, Exposure TEXT, Aperture TEXT,
                ISO INTEGER, Focal_length INTEGER,
                Keywords TEXT, Caption TEXT, alt_text TEXT, Location TEXT, Subject TEXT,
                nima_score REAL, blur_score REAL, brightness_score REAL,
                contrast_score REAL, QR REAL, QC_Status TEXT, Review_Status TEXT,
                Original_File_Name TEXT, brisque_score REAL, clip_aesthetic_score REAL
            )
        """
        )
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


# ---------- UI ----------
class MultiSetApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Amir2000 Image Automation — Multi-Set")
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
        self.subject_txt.bind(
            "<KeyRelease>", lambda e: self._subject_spellcheck_update(), add="+"
        )
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
            command=self._ai_suggest_subject_for_current,
        )
        self.ai_subject_btn.pack(side="left")
        ttk.Button(btns, text="Add set", command=self._add_current_set).pack(
            side="left", padx=(28, 0)
        )
        self.spell_warn_lbl = ttk.Label(btns, text="", foreground="#c08000")
        self.spell_warn_lbl.pack(side="left", padx=(6, 0))

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

            restored_batches: list[dict] = []
            for row in (data.get("batches") or []):
                if not isinstance(row, dict):
                    continue
                subject = clean_token((row.get("subject") or "").strip())
                location = clean_token((row.get("location") or "").strip())
                folder = clean_token((row.get("folder") or "").strip())
                folder_h = (row.get("folder_h") or "").strip()
                files = [
                    str(p)
                    for p in (row.get("files") or [])
                    if p and os.path.exists(str(p))
                ]
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

            restored_stage_origin = {}
            for k, v in (data.get("stage_origin") or {}).items():
                if not k or not v:
                    continue
                restored_stage_origin[str(k)] = str(v)

            restored_pending = [
                str(p)
                for p in (data.get("pending_files") or [])
                if p and os.path.exists(str(p))
            ]

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

    def _ai_suggest_subject_for_current(self):
        if not self._pending_files:
            messagebox.showinfo("No images selected", "Select images first.")
            return

        # Prevent overlapping suggestion workers when selecting many sets quickly.
        if getattr(self, "_ai_subject_busy", False):
            return

        paths = list(self._pending_files)
        paths_sig = {self._norm_path(p) for p in paths if p}
        self._ai_subject_busy = True
        self._ai_subject_paths_sig = paths_sig

        # Never block the Tk main thread (prevents "Not Responding")
        try:
            if hasattr(self, "ai_subject_btn"):
                self.ai_subject_btn.configure(state="disabled")
        except Exception:
            pass

        try:
            self.stage_lbl["text"] = "AI subject: working..."
        except Exception:
            pass

        def _worker():
            try:
                guess = ai_suggest_subject_multi(paths)
                err = (_LAST_OLLAMA_ERROR or "").strip()
            except Exception as e:
                guess = None
                err = str(e)

            def _done():
                try:
                    if hasattr(self, "ai_subject_btn"):
                        self.ai_subject_btn.configure(state="normal")
                except Exception:
                    pass
                finally:
                    self._ai_subject_busy = False
                    self._ai_subject_paths_sig = set()

                g = (guess or "").strip()
                if not g:
                    if err:
                        messagebox.showinfo(
                            "AI suggestion", err or "Could not suggest a subject."
                        )
                    self._update_ready_status()
                    return

                current_sig = {self._norm_path(p) for p in (self._pending_files or []) if p}
                if current_sig != paths_sig:
                    # Selection changed while background suggestion was running.
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

                if g2:
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

        subject_raw = autofix_subject(subject_raw, AUTOFIX_DICT_FILE)
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
            subject = clean_token(ai_suggest_subject(files[0]) or "")
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

        self.batches.append(
            {
                "subject": subject,
                "location": location,
                "folder": folder,
                "folder_h": folder_h,
                "files": staged_files,
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
                for raw in proc.stdout:
                    line = raw.rstrip("\n")
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

            rc = proc.wait()
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

            for si, s in enumerate(self.batches, start=1):
                badge = f"[Set {si}/{total_sets}]"
                subject, location, folder = s["subject"], s["location"], s["folder"]
                files = s["files"]

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
                        "QR": None,
                        "QC_Status": "NA",
                        "Review_Status": "Queued",
                        "Original_File_Name": base,
                    }

                    # EXIF is best-effort; filename generation is strict (must not silently fallback).
                    exif = {}
                    try:
                        exif = get_exif_data(dst) or {}
                    except Exception as ex:
                        print(f"[WARN] EXIF parse failed for {dst}: {ex}")

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
                        inserted += 1
                        inserted_ids.append(row_id)
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
                r"C:\\Users\\ad341\\amir2000\\.venv\\Scripts\\python.exe",
            ]

            def _pick_python() -> str:
                py = os.environ.get("AMIR_PYTHON") or sys.executable
                if getattr(sys, "frozen", False) and not os.environ.get("AMIR_PYTHON"):
                    for c in _default_venv_candidates:
                        if c and os.path.exists(c):
                            py = c
                            break
                return py

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
                script_score = resource_path("batch_image_quality_score.py")

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
                                f"UPDATE {TABLE_NAME} SET QC_Status=? WHERE id=? AND QC_Status=?",
                                [("NA", i, "ScoringFailed") for i in inserted_ids],
                            )
                            _c.commit()
                    except Exception:
                        pass

                score_ok = False
                last_reason = ""
                py_score = _pick_python()

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
                            cwd=os.path.dirname(script_score),
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
                print("[SKIP] Scoring skipped (QC already present).")

            
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

            queued_ids = _query_prefill_ids(0)
            queued_count = len(queued_ids)

            if queued_count <= 0:
                print("[SKIP] No queued rows to prefill.")
            else:
                script_prefill = resource_path("caption_review_local.py")
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

                    if CAPTION_REWRITE_WEAK:
                        prefill_args_base.append("--rewrite-weak")

                    if DEFAULT_TERMS_DB and os.path.exists(DEFAULT_TERMS_DB):
                        prefill_args_base += [
                            "--terms-db", DEFAULT_TERMS_DB,
                            "--terms-table", CAPTION_TERMS_TABLE,
                            "--terms-min-precision", str(CAPTION_TERMS_MIN_PRECISION),
                        ]

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
                            run_args += ["--id-list", ",".join([str(x) for x in run_ids])]

                            rc, ok_n, fail_n, tail = _stream_cmd_with_ok_counter(
                                [py, "-u", script_prefill] + run_args,
                                cwd=os.path.dirname(script_prefill),
                                total=len(run_ids),
                                stage_num_for_ui=6,
                                badge_prefix=f"batch={chunk_idx}/{prefill_total_chunks}",
                                overall_total=queued_count,
                                overall_done_before=done_before,
                                overall_ok_before=ok_total,
                                overall_fail_before=fail_total,
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
                                and "[OK] Completed. Updated rows:" in (tail or "")
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

                            raise RuntimeError(
                                f"Prefill script returned non-zero ({rc}) tail={err or '(empty)'}"
                            )

                        print(
                            f"[INFO] Prefill summary: queued={queued_count} ok={ok_total} "
                            f"fail={fail_total} retries={crash_retry_used}"
                        )
                        remaining_after = len(_query_prefill_ids(0))
                        if remaining_after > 0:
                            print(
                                f"[WARN] Prefill incomplete: remaining queued rows={remaining_after}. "
                                "Run Start Batch again to continue from where it stopped."
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


        except Exception as ex:
            traceback.print_exc()
            msg = f"{type(ex).__name__}: {ex}"
            if not suppress_fail_dialog:
                self._ui(lambda m=msg: messagebox.showerror("Batch Failed", m))
            success = False

        finally:

            def _rollback_session(reason: str):
                print(f"[WARN] {reason}. Rolling back this session.")

                # remove inserted DB rows
                try:
                    if inserted_ids:
                        conn2 = sqlite3.connect(DB_PATH)
                        cur2 = conn2.cursor()
                        cur2.execute(
                            f"DELETE FROM {TABLE_NAME} WHERE id IN ({','.join('?' * len(inserted_ids))})",
                            inserted_ids,
                        )
                        conn2.commit()
                        conn2.close()
                        print(
                            f"[WARN] Removed {len(inserted_ids)} inserted rows from {TABLE_NAME}."
                        )
                except Exception as _e:
                    print(f"[WARN] Could not remove inserted rows: {_e}")

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
                            if prefill_qc_summary:
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
                            self._clear_session_state()
                            print("[INFO] Review/editor closed.")
                            return

                        if os.environ.get("AMIR_TRACE_SKIP_EDITOR") == "1":
                            self._clear_session_state()
                            print("[TRACE] Skipping review editor (AMIR_TRACE_SKIP_EDITOR=1).")
                            print("[INFO] Review/editor closed.")
                            return

                        py_editor = os.environ.get("AMIR_PYTHON") or sys.executable
                        res = subprocess.run([py_editor, _script3], check=False)

                        if res.returncode != 0:
                            raise RuntimeError(f"review_editor failed with returncode={res.returncode}")

                        self._clear_session_state()
                        print("[INFO] Review/editor closed.")

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
        s = (s or "").replace("\n", " ").strip()
        try:
            self.subject_var.set(s)
        except Exception:
            pass

        self.subject_txt.delete("1.0", "end")
        self.subject_txt.insert("1.0", s)
        self._subject_spellcheck_update()

    def _on_subject_change(self, event=None):
        self._subject_spellcheck_update()

    def _on_subject_change(self, _ev=None):
        s = self._subject_get()
        self.subject_var.set(s)
        self._subject_spellcheck_update()

    def _subject_spellcheck_update(self):
        try:
            self.subject_txt.tag_remove("misspell", "1.0", "end")
        except Exception:
            return

        text = self._subject_get()
        try:
            self.subject_var.set(text)
        except Exception:
            pass
        issues = find_misspellings(text, DATA_DIR)

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

        menu.add_command(label=f"Replace with: {sug}", command=do_replace)
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

        self._location_spellcheck_update()

    def _on_location_change(self, _ev=None):
        s = self._location_get()
        self.location_var.set(s)
        self._location_spellcheck_update()

    def _location_spellcheck_update(self):
        try:
            self.location_txt.tag_remove("misspell", "1.0", "end")
        except Exception:
            return

        text = self._location_get()
        issues = find_misspellings(text, DATA_DIR)
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

        menu.add_command(label=f"Replace with: {sug}", command=do_replace)
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
                return

            self.location_txt.delete("1.0", "end")
            self.location_txt.insert("1.0", suggestion)
            i1 = f"1.0+{len(typed)}c"
            self.location_txt.tag_remove("sel", "1.0", "end")
            self.location_txt.tag_add("sel", i1, "end-1c")
            self.location_txt.mark_set("insert", i1)
            self.location_var.set(suggestion)
            self._location_spellcheck_update()
        except Exception:
            pass

    def _on_location_keyrelease(self, ev=None):
        # keep existing behavior
        self._on_location_change(ev)

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
