# review_editor.py
import os
import sys
import shutil
import sqlite3
import subprocess
import json
import traceback
import threading
import uuid
import tempfile
from tkinter import Tk, Label, Entry, Button, StringVar, messagebox, Frame, Text, END, DISABLED, Menu
from tkinter import ttk
from PIL import Image, ImageTk
from datetime import datetime
import re
from PIL import Image, ImageDraw, ImageFont  # ensure collected by PyInstaller
import os, re

# Ensure local runs (including snapshot paths) can import project-level `utils`.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = None
for _cand in (
    _THIS_DIR,
    os.path.abspath(os.path.join(_THIS_DIR, "..")),
    os.path.abspath(os.path.join(_THIS_DIR, "..", "..")),
):
    if os.path.isfile(os.path.join(_cand, "utils", "file_namer.py")):
        _PROJECT_ROOT = _cand
        if _cand not in sys.path:
            sys.path.insert(0, _cand)
        break

# If another third-party `utils` module was loaded first, remove it so
# imports resolve to our project package.
_u = sys.modules.get("utils")
if _u is not None and _PROJECT_ROOT:
    _u_file = os.path.abspath(str(getattr(_u, "__file__", "") or ""))
    _u_path = [os.path.abspath(str(p)) for p in (getattr(_u, "__path__", []) or [])]
    _wanted = os.path.abspath(os.path.join(_PROJECT_ROOT, "utils"))
    _is_project_utils = _u_file.startswith(_wanted) or any(p.startswith(_wanted) for p in _u_path)
    if not _is_project_utils:
        sys.modules.pop("utils", None)

_UDUP = re.compile(r'_+')

def clean_token(s: str) -> str:
    s = (s or '').strip().replace(' ', '_')
    s = _UDUP.sub('_', s)
    return s.strip('_')

def clean_filename(name: str) -> str:
    base, ext = os.path.splitext((name or '').strip())
    # Canonical filename style:
    # preserve token casing, normalize separators, keep uppercase extension.
    # Duplicate safety remains case-insensitive in reservation checks.
    base = clean_token(base)
    ext = (ext or ".JPG").upper()
    return f"{base}{ext}"

# ---------------- Paths & helpers ----------------
from pathlib import Path
import importlib.util

def resource_path(rel_path: str) -> str:
    """Resolve paths for source runs and PyInstaller builds.

    Search order:
      1) EXE folder
      2) EXE folder/_internal
      3) PyInstaller temp (sys._MEIPASS)
      4) PyInstaller temp/_internal
      5) Source folder
      6) Source folder/_internal
    """
    rel_path = rel_path.replace("/", os.sep).replace("\\", os.sep)

    candidates: list[str] = []

    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        candidates.append(os.path.join(exe_dir, rel_path))
        candidates.append(os.path.join(exe_dir, "_internal", rel_path))
        try:
            meipass = sys._MEIPASS  # type: ignore[attr-defined]
            candidates.append(os.path.join(meipass, rel_path))
            candidates.append(os.path.join(meipass, "_internal", rel_path))
        except Exception:
            pass

    src_dir = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(src_dir, rel_path))
    candidates.append(os.path.join(src_dir, "_internal", rel_path))

    for p in candidates:
        if os.path.exists(p):
            return p
    return candidates[0]

def _load_config():
    """Load amir2000_config.py from beside the EXE (preferred) or beside the source file."""
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "amir2000_config.py")
        candidates.append(Path(sys.executable).resolve().parent / "_internal" / "amir2000_config.py")

    candidates.append(Path(__file__).resolve().parent / "amir2000_config.py")

    for p in candidates:
        if p.is_file():
            spec = importlib.util.spec_from_file_location("amir2000_config_external", str(p))
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)  # type: ignore[arg-type]
                return mod
    return None

_cfg = _load_config()

PATHS = getattr(_cfg, "PATHS", {}) if _cfg else {}
PUBLISH = getattr(_cfg, "PUBLISH", {}) if _cfg else {}

# Expose the public URL base from config. Do not hard-code any domain here; it will be
# defined in amir2000_config.py or supplied via environment variables. If missing,
# fallback to an empty string.
PUBLIC_URL_BASE = PUBLISH.get("PUBLIC_URL_BASE", "")

# Canonical data location
DATA_DIR = PATHS.get("DATA_DIR", r"YOUR_PATH_HERE")
UI_STATE_FILE = os.path.join(DATA_DIR, "ui_state.json")
REVIEW_EDITOR_CRASH_LOG = os.path.join(DATA_DIR, "review_editor_crash.log")
PUBLISH_QUEUE_FILE = os.path.join(DATA_DIR, "publish_queue.json")

# DB location (allow env override)
DB_PATH = os.environ.get("AMIR_REVIEW_DB", PATHS.get("REVIEW_DB_PATH", os.path.join(DATA_DIR, "review.db")))
TABLE_NAME = PUBLISH.get("REVIEW_QUEUE_TABLE", "review_queue")

# Other folders
INCOMING_DIR    = PATHS.get("INCOMING_DIR", r"YOUR_PATH_HERE")
REJECTED_FOLDER = PATHS.get("REJECTED_DIR", r"YOUR_PATH_HERE")
LOCAL_BASE      = PATHS.get("LOCAL_SITE_IMAGES_BASE", r"YOUR_PATH_HERE")
DESKTOP_ROOT    = PATHS.get("DESKTOP_ROOT", r"YOUR_PATH_HERE")
ARCHIVE_ROOT    = PATHS.get("ARCHIVE_ROOT", r"YOUR_PATH_HERE")

FONT_PATH      = resource_path(os.path.join("fonts", "Montserrat-Light.ttf"))
WATERMARK_TEXT = "© YOUR_HOST\nPhotography"

# ---- Regenerate (caption/alt/keywords) via caption_review_local.py ----
CAPTION_ENDPOINT = os.getenv("CAPTION_ENDPOINT", "http://127.0.0.1:11434/api/generate")
CAPTION_MODEL = os.getenv("OLLAMA_MODEL_CAPTION", "llava:13b")
CAPTION_MODEL_FALLBACK = os.getenv("OLLAMA_MODEL_CAPTION_FALLBACK", "").strip()
CAPTION_TIMEOUT_SEC = int(os.getenv("CAPTION_TIMEOUT_SEC", "420"))
CAPTION_OPTS = {
    "num_ctx": int(os.getenv("CAPTION_NUM_CTX", "4096")),
    "num_predict": int(os.getenv("CAPTION_NUM_PREDICT", "180")),
    "temperature": float(os.getenv("CAPTION_TEMPERATURE", "0.1")),
}
try:
    _caption_num_gpu = int(os.getenv("CAPTION_NUM_GPU", os.getenv("OLLAMA_NUM_GPU", "99")))
except Exception:
    _caption_num_gpu = 99
try:
    _caption_main_gpu = int(os.getenv("CAPTION_MAIN_GPU", os.getenv("OLLAMA_MAIN_GPU", "0")))
except Exception:
    _caption_main_gpu = 0
if _caption_num_gpu >= 0:
    CAPTION_OPTS["num_gpu"] = _caption_num_gpu
if _caption_main_gpu >= 0:
    CAPTION_OPTS["main_gpu"] = _caption_main_gpu
CAPTION_KEYWORDS_N = int(os.getenv("CAPTION_KEYWORDS_N", "15"))
CAPTION_PREFIX_WORDS = int(os.getenv("CAPTION_PREFIX_WORDS", "8"))
CAPTION_SERIES_LARGE_THRESHOLD = int(os.getenv("CAPTION_SERIES_LARGE_THRESHOLD", "8"))
CAPTION_MAX_TRIES = int(os.getenv("CAPTION_MAX_TRIES", "5"))
CAPTION_REWRITE_WEAK = os.getenv("CAPTION_REWRITE_WEAK", "1") == "1"
CAPTION_REWRITE_MAX_PASSES = int(os.getenv("CAPTION_REWRITE_MAX_PASSES", "3"))
CAPTION_QUALITY_MIN_SCORE = int(os.getenv("CAPTION_QUALITY_MIN_SCORE", "90"))

# Use the one true JSON in DATA_DIR
USED_FILENAMES_JSON = os.path.join(DATA_DIR, "used_filenames.json")
if not os.environ.get("AMIR_USED_FILENAMES_JSON"):
    os.environ["AMIR_USED_FILENAMES_JSON"] = USED_FILENAMES_JSON


# Utilities you already have
try:
    from utils.image_processor import resize_and_watermark
except ModuleNotFoundError as e:
    # Most common: utils.image_processor imports piexif
    missing = getattr(e, "name", "") or str(e)
    msg = (
        "Missing dependency while starting review_editor.\n\n"
        f"Missing module: {missing}\n\n"
        "Fix:\n"
        "1) Install into your venv:\n"
        "   YOUR_PATH_HERE -m pip install piexif\n"
        "2) Re-run review_editor via that venv python.\n"
    )
    print("[ERROR] " + msg.replace("\n", " | "))

    # Try to show a UI popup too (best effort)
    try:
        r = Tk()
        r.withdraw()
        messagebox.showerror("review_editor missing dependency", msg)
        r.destroy()
    except Exception:
        pass

    raise SystemExit(2)

from utils.file_namer import generate_unique_filename
from utils.caption_keyword_generator import generate_caption, generate_keywords
from utils.autofix import find_misspellings, add_spell_exception, spellcheck_status


QR_EXPLANATION = (
    "QR (Quality Rating) Guide (New Logic):\n"
    "  • Top (≥7.5): Outstanding. Publish or license with confidence.\n"
    "  • Good (6.5–7.5): Strong image for web/stock/blog.\n"
    "  • Average (5.5–6.5): Acceptable, may need improvement.\n"
    "  • Low (4.5–5.5): Major issues. Consider removing or retouching.\n"
    "  • Very Low (<4.5): Not suitable for use.\n"
    "\n"
    "Metrics now shown: CLIP Aesthetic, NIMA, Blur, Brightness, Contrast, BRISQUE.\n"
    "Tips: High QR = sharp, well-exposed, visually appealing, strong subject/focus.\n"
    "BRISQUE: Lower = better. CLIP: 1-10 (higher=better)."
)

# ---------------- Small helpers ----------------
def qc_status(qr):
    try:
        q = float(qr)
    except Exception:
        return "NA"
    if q >= 7.5: return "Top"
    if q >= 6.5: return "Good"
    if q >= 5.5: return "Average"
    if q >= 4.5: return "Low"
    return "Very Low"

def log_manual_edit(
    image_id, file_name,
    auto_caption, edited_caption,
    auto_keywords, edited_keywords,
    auto_score, override_score,
    auto_qc_status, override_qc_status,
    auto_filename, edited_filename,
    decision, comment, fields_changed, edited_by,
    mysql_id=None
):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO learning_log (
            image_id, file_name,
            auto_caption, edited_caption,
            auto_keywords, edited_keywords,
            auto_score, override_score,
            auto_qc_status, override_qc_status,
            auto_filename, edited_filename,
            decision, comment, fields_changed,
            edited_by, edit_timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        mysql_id, file_name,
        auto_caption, edited_caption,
        auto_keywords, edited_keywords,
        auto_score, override_score,
        auto_qc_status, override_qc_status,
        auto_filename, edited_filename,
        decision, comment, fields_changed,
        edited_by, datetime.now().isoformat()
    ))
    conn.commit()
    conn.close()

def _ensure_used_json():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(USED_FILENAMES_JSON):
        with open(USED_FILENAMES_JSON, "w", encoding="utf-8") as f:
            json.dump([], f)

def load_used_filenames() -> set[str]:
    _ensure_used_json()
    try:
        with open(USED_FILENAMES_JSON, "r", encoding="utf-8") as f:
            arr = json.load(f)
            if isinstance(arr, list):
                return {str(x).strip() for x in arr if str(x).strip()}
            if isinstance(arr, dict):
                out = set()
                for k, v in arr.items():
                    ks = str(k).strip()
                    vs = str(v).strip()
                    if ks:
                        out.add(ks)
                    if vs:
                        out.add(vs)
                return out
            return set()
    except Exception:
        return set()

def save_used_filenames(used: set[str]):
    """
    Safe write (supports removals too):
      - backup existing file
      - atomic write via temp file
    """
    import time, tempfile, shutil, glob
    os.makedirs(DATA_DIR, exist_ok=True)

    used = set(used)

    def _prune_used_backups(keep: int = 20) -> None:
        try:
            pat = f"{USED_FILENAMES_JSON}.bak_*"
            files = [p for p in glob.glob(pat) if os.path.isfile(p)]
            files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
            for old in files[max(1, int(keep)):]:
                try:
                    os.remove(old)
                except Exception:
                    pass
        except Exception:
            pass

    # backup
    try:
        if os.path.exists(USED_FILENAMES_JSON):
            bak = f"{USED_FILENAMES_JSON}.bak_{int(time.time())}"
            shutil.copy2(USED_FILENAMES_JSON, bak)
            _prune_used_backups(keep=20)
    except Exception:
        pass

    # atomic write
    fd, tmp = tempfile.mkstemp(
        prefix="used_", suffix=".json",
        dir=os.path.dirname(USED_FILENAMES_JSON) or None
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(sorted(list(used)), f, indent=2, ensure_ascii=False)
        os.replace(tmp, USED_FILENAMES_JSON)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass



def split_filename_num(filename: str):
    import re
    m = re.match(r"(.+?)(?:_(\d{3}))?(\.[^.]+)$", filename, re.IGNORECASE)
    if m: return m.group(1), m.group(2), m.group(3)
    base, ext = os.path.splitext(filename)
    return base, None, ext

def _remove_used_name_ci(used: set[str], target: str) -> bool:
    """Remove filename from used set case-insensitively."""
    if not target:
        return False
    t = target.casefold()
    drop = [x for x in used if str(x).casefold() == t]
    for x in drop:
        used.discard(x)
    return bool(drop)

def next_free_filename(
    base: str,
    ext: str,
    used: set[str],
    blocked_ci: set[str] | None = None,
    start_num: int | None = None,
) -> str:
    used_ci = {str(x).casefold() for x in used}
    blocked_ci = blocked_ci or set()
    if start_num is not None:
        for i in range(max(1, int(start_num)), 2000):
            cand = f"{base}_{i:03d}{ext}"
            c = cand.casefold()
            if c not in used_ci and c not in blocked_ci:
                return cand
    else:
        # Legacy fallback: allow bare base first, then numbered suffixes.
        for i in range(1, 2000):
            suffix = f"_{i:03d}" if i > 1 else ""
            cand = f"{base}{suffix}{ext}"
            c = cand.casefold()
            if c not in used_ci and c not in blocked_ci:
                return cand
    raise RuntimeError("Too many duplicates")

# ---------------- UI ----------------
class ReviewApp:
    def __init__(self, master: Tk):
        self.master = master
        # Restore last geometry if available
        self._apply_ui_state(default_geometry="1700x1050")
        self.master.resizable(True, True)
        self.master.protocol("WM_DELETE_WINDOW", self._on_close)
        self.master.title("Amir2000 Image Review & Publish")
        try:
            self.master.report_callback_exception = self._report_callback_exception
        except Exception:
            pass



        self.conn = sqlite3.connect(DB_PATH)
        self.cur  = self.conn.cursor()

        self.images = self.get_images_to_review()   # list[dict]
        self.idx = 0
        self.field_vars: dict[str, StringVar] = {}
        self.text_widgets: dict[str, Text] = {}
        self._text_spell_after_ids: dict[str, str] = {}
        self._text_spell_hits: dict[str, list[dict]] = {}
        self._spellcheck_ok_cached: bool | None = None
        self.file_ops_queue: list[tuple[dict, dict]] = []  # legacy in-memory queue
        self._wants_upload = False
        self._qr_updating = False  # guard to prevent slider->callback recursion
        self._action_in_progress = False
        self._autoscan_spell_on_load = os.getenv(
            "AMIR_AUTOSPELLCHECK_ON_LOAD", "0"
        ).strip().lower() in ("1", "true", "yes", "on")
        self._publish_lock = threading.Lock()
        self.publish_queue: list[dict] = []
        self._publish_thread: threading.Thread | None = None
        self._publish_running = False
        self._publish_last_result: dict | None = None
        self._publish_progress = {
            "total": 0,
            "processed": 0,
            "uploaded": 0,
            "failed": 0,
            "phase": "idle",
            "last": "",
        }
        self.publish_status_var = StringVar(value="Publish queue: 0 pending")
        self._load_publish_queue()

        self.build_layout()
        self._refresh_publish_status()
        self._set_review_actions_enabled(bool(self.images))

        if self.images:
            self.load_image()
        else:
            if self._has_pending_publish_items():
                if messagebox.askyesno(
                    "Resume publish",
                    "No pending review rows were found, but there are pending publish tasks from a previous run.\n\n"
                    "Do you want to resume publishing now?",
                ):
                    self._start_publish_worker()
                else:
                    messagebox.showinfo(
                        "No Images",
                        "No images found to review. You can still use 'Resume Publish' to continue queued uploads.",
                    )
            else:
                messagebox.showinfo("No Images", "No images found to review.")
                self.master.destroy()

    def _apply_ui_state(self, default_geometry: str = "1700x1050"):
        geo = default_geometry
        try:
            if os.path.exists(UI_STATE_FILE):
                with open(UI_STATE_FILE, "r", encoding="utf-8") as f:
                    st = json.load(f)
                if isinstance(st, dict) and st.get("review_editor_geometry"):
                    geo = str(st.get("review_editor_geometry"))
        except Exception:
            pass
        try:
            self.master.geometry(geo)
        except Exception:
            self.master.geometry(default_geometry)
        # If last saved position was on a disconnected screen, force it visible.
        try:
            self.master.update_idletasks()
            sw = int(self.master.winfo_screenwidth())
            sh = int(self.master.winfo_screenheight())
            x = int(self.master.winfo_x())
            y = int(self.master.winfo_y())
            w = int(self.master.winfo_width())
            h = int(self.master.winfo_height())
            visible_w = max(0, min(x + w, sw) - max(x, 0))
            visible_h = max(0, min(y + h, sh) - max(y, 0))
            if visible_w < 120 or visible_h < 120:
                self.master.geometry(default_geometry)
                self.master.update_idletasks()
                cw = int(self.master.winfo_width())
                ch = int(self.master.winfo_height())
                nx = max(0, (sw - cw) // 2)
                ny = max(0, (sh - ch) // 2)
                self.master.geometry(f"{cw}x{ch}+{nx}+{ny}")
        except Exception:
            pass

    def _save_ui_state(self):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            st = {}
            if os.path.exists(UI_STATE_FILE):
                with open(UI_STATE_FILE, "r", encoding="utf-8") as f:
                    st = json.load(f)
            if not isinstance(st, dict):
                st = {}
            st["review_editor_geometry"] = self.master.geometry()
            with open(UI_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(st, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _on_close(self):
        if self._publish_running:
            if not messagebox.askyesno(
                "Publish running",
                "Background publish is still running.\n\n"
                "Close anyway? You can resume later from the saved publish queue.",
            ):
                return
        try:
            self._cancel_pending_spellchecks()
        except Exception:
            pass
        try:
            self._save_ui_state()
        except Exception:
            pass
        try:
            self.conn.commit()
        except Exception:
            pass
        try:
            self.conn.close()
        except Exception:
            pass
        self.master.destroy()

    def _append_error_log(self, header: str, detail: str):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(REVIEW_EDITOR_CRASH_LOG, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now().isoformat(timespec='seconds')}] {header}\n")
                f.write((detail or "").rstrip() + "\n\n")
        except Exception:
            pass

    def _report_callback_exception(self, exc, val, tb):
        msg = "".join(traceback.format_exception(exc, val, tb))
        self._append_error_log("Tk callback exception", msg)
        try:
            messagebox.showerror(
                "Action failed",
                "The action failed but the app stayed open.\n\n"
                f"Details were logged to:\n{REVIEW_EDITOR_CRASH_LOG}",
            )
        except Exception:
            pass

    def _run_ui_action(self, action_name: str, fn):
        if self._action_in_progress:
            return
        self._action_in_progress = True
        try:
            fn()
        except Exception:
            self._append_error_log(
                f"Action failed: {action_name}",
                traceback.format_exc(),
            )
            try:
                messagebox.showerror(
                    "Action failed",
                    f"'{action_name}' failed. Nothing was deleted.\n\n"
                    f"Check:\n{REVIEW_EDITOR_CRASH_LOG}",
                )
            except Exception:
                pass
        finally:
            self._action_in_progress = False

    def _set_review_actions_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        for b in getattr(self, "_review_action_buttons", []):
            try:
                b.configure(state=state)
            except Exception:
                pass

    def _atomic_write_json(self, path: str, payload):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix="pubq_", suffix=".json", dir=os.path.dirname(path) or None)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        finally:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass

    def _normalize_publish_item(self, item) -> dict | None:
        if not isinstance(item, dict):
            return None
        try:
            row_id = int(item.get("row_id") or item.get("id") or 0)
        except Exception:
            row_id = 0
        if row_id <= 0:
            return None
        state = str(item.get("state") or "approved").strip().lower()
        if state not in {"approved", "processed", "uploaded", "failed"}:
            state = "approved"
        original_img = item.get("original_img") if isinstance(item.get("original_img"), dict) else {}
        values = item.get("values") if isinstance(item.get("values"), dict) else {}
        if not values and isinstance(item.get("img_updated"), dict):
            values = item.get("img_updated")
        return {
            "queue_id": str(item.get("queue_id") or uuid.uuid4()),
            "row_id": row_id,
            "state": state,
            "attempts": int(item.get("attempts") or 0),
            "last_error": str(item.get("last_error") or ""),
            "created_at": str(item.get("created_at") or datetime.now().isoformat(timespec="seconds")),
            "updated_at": str(item.get("updated_at") or datetime.now().isoformat(timespec="seconds")),
            "original_img": dict(original_img or {}),
            "values": dict(values or {}),
        }

    def _load_publish_queue(self):
        arr = []
        try:
            if os.path.exists(PUBLISH_QUEUE_FILE):
                with open(PUBLISH_QUEUE_FILE, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, list):
                    arr = raw
        except Exception:
            arr = []
        normalized: list[dict] = []
        for x in arr:
            n = self._normalize_publish_item(x)
            if n is not None:
                normalized.append(n)
        with self._publish_lock:
            self.publish_queue = normalized
        # Rewrite normalized format so future loads stay stable.
        try:
            self._atomic_write_json(PUBLISH_QUEUE_FILE, normalized)
        except Exception:
            pass

    def _save_publish_queue(self):
        with self._publish_lock:
            payload = [dict(x) for x in self.publish_queue]
        self._atomic_write_json(PUBLISH_QUEUE_FILE, payload)

    def _pending_publish_items(self) -> list[dict]:
        with self._publish_lock:
            return [dict(x) for x in self.publish_queue if str(x.get("state") or "").lower() != "uploaded"]

    def _has_pending_publish_items(self) -> bool:
        return bool(self._pending_publish_items())

    def _publish_queue_used_names(self) -> set[str]:
        out: set[str] = set()
        for it in self._pending_publish_items():
            vals = it.get("values") if isinstance(it.get("values"), dict) else {}
            fn = clean_filename(vals.get("File_Name") or "")
            if fn:
                out.add(fn)
        return out

    def _enqueue_publish_item(self, original_img: dict, values: dict):
        rid = int(values.get("id") or original_img.get("id") or 0)
        if rid <= 0:
            return
        now = datetime.now().isoformat(timespec="seconds")
        replaced = False
        with self._publish_lock:
            for it in self.publish_queue:
                if int(it.get("row_id") or 0) == rid and str(it.get("state") or "").lower() != "uploaded":
                    it["state"] = "approved"
                    it["values"] = dict(values or {})
                    it["original_img"] = dict(original_img or {})
                    it["updated_at"] = now
                    it["last_error"] = ""
                    replaced = True
                    break
            if not replaced:
                self.publish_queue.append(
                    {
                        "queue_id": str(uuid.uuid4()),
                        "row_id": rid,
                        "state": "approved",
                        "attempts": 0,
                        "last_error": "",
                        "created_at": now,
                        "updated_at": now,
                        "original_img": dict(original_img or {}),
                        "values": dict(values or {}),
                    }
                )
        self._save_publish_queue()
        self._refresh_publish_status()

    def _refresh_publish_status(self):
        with self._publish_lock:
            q = list(self.publish_queue)
            prog = dict(self._publish_progress)
        counts = {"approved": 0, "processed": 0, "uploaded": 0, "failed": 0}
        for it in q:
            st = str(it.get("state") or "").lower()
            if st in counts:
                counts[st] += 1
        pending = counts["approved"] + counts["processed"] + counts["failed"]
        phase = str(prog.get("phase") or "idle")
        if self._publish_running:
            tail = (
                f" | running {phase}: {int(prog.get('processed') or 0)}/{int(prog.get('total') or pending)}"
                f" uploaded={int(prog.get('uploaded') or 0)} failed={int(prog.get('failed') or 0)}"
            )
        else:
            tail = ""
        self.publish_status_var.set(
            f"Publish queue pending={pending} approved={counts['approved']} processed={counts['processed']} failed={counts['failed']}{tail}"
        )

    def _run_recovery_from_revamp(self):
        script = os.path.join(os.path.dirname(__file__), "helpers", "recover_actual_images_from_revamp.py")
        if not os.path.exists(script):
            messagebox.showerror("Recovery", f"Recovery script not found:\n{script}")
            return
        res = subprocess.run(
            [sys.executable, script],
            capture_output=True,
            text=True,
            check=False,
        )
        out = ((res.stdout or "") + "\n" + (res.stderr or "")).strip()[-3500:]
        if res.returncode == 0:
            messagebox.showinfo("Recovery Complete", out or "Done.")
        else:
            messagebox.showerror("Recovery Failed", out or f"Exit code {res.returncode}")

    def _start_publish_worker(self):
        if self._publish_running:
            messagebox.showinfo("Publish", "Publish is already running in background.")
            return
        pending = self._pending_publish_items()
        if not pending:
            messagebox.showinfo("Publish", "No pending publish tasks.")
            return
        with self._publish_lock:
            self._publish_progress = {
                "total": len(pending),
                "processed": 0,
                "uploaded": 0,
                "failed": 0,
                "phase": "local",
                "last": "",
            }
            self._publish_last_result = None
        self._publish_running = True
        self._publish_thread = threading.Thread(target=self._publish_worker_main, daemon=True)
        self._publish_thread.start()
        self._refresh_publish_status()
        self.master.after(250, self._poll_publish_worker)

    def _run_db_uploader_worker(self) -> tuple[int, str]:
        try:
            if getattr(sys, "frozen", False):
                import runpy
                try:
                    runpy.run_path(resource_path("db_uploader.py"), run_name="__main__")
                    return 0, "Uploader finished."
                except SystemExit as se:
                    code = int(se.code) if se.code is not None else 0
                    return code, f"Uploader exit {code}"
            res = subprocess.run(
                [sys.executable, resource_path("db_uploader.py")],
                capture_output=True,
                text=True,
                check=False,
            )
            merged = ((res.stdout or "") + "\n" + (res.stderr or "")).strip()
            return int(res.returncode), merged
        except Exception:
            return 1, traceback.format_exc()

    def _process_publish_item(
        self,
        item: dict,
        qcur,
        qconn,
        used: set[str],
        used_ci: set[str],
    ) -> tuple[bool, str]:
        original_img = item.get("original_img") if isinstance(item.get("original_img"), dict) else {}
        values = item.get("values") if isinstance(item.get("values"), dict) else {}
        row_id = int(item.get("row_id") or 0)
        if row_id <= 0:
            return False, "missing row_id"

        folder = str(values.get("Folder") or original_img.get("Folder") or "").strip()
        year = str(values.get("DateTime") or original_img.get("DateTime") or "")[:4] or "unknown"
        newname = clean_filename(values.get("File_Name") or original_img.get("File_Name") or "")
        oldname = clean_filename(original_img.get("File_Name") or "")
        orig = str(original_img.get("Path") or values.get("Path") or "").strip()
        if not folder or not newname:
            return False, "missing folder or filename"

        web_dir = os.path.join(LOCAL_BASE, year, folder)
        thumb_dir = os.path.join(LOCAL_BASE, year, "thumbs", folder)
        desk_dir = os.path.join(DESKTOP_ROOT, folder)
        arch_dir = os.path.join(ARCHIVE_ROOT, year, folder)
        for d in (web_dir, thumb_dir, desk_dir, arch_dir):
            os.makedirs(d, exist_ok=True)

        web_path = os.path.join(web_dir, newname)
        thumb_path = os.path.join(thumb_dir, newname)
        desk_path = os.path.join(desk_dir, newname)
        arch_path = os.path.join(arch_dir, newname)

        exists_on_dest = os.path.exists(web_path) or os.path.exists(thumb_path)
        if exists_on_dest and (not os.path.exists(web_path) or not os.path.exists(thumb_path)):
            base, _num, ext = split_filename_num(newname)
            start_num = (int(_num) + 1) if (_num and str(_num).isdigit()) else None
            tried_ci = {newname.casefold()}
            fixed = False
            for _ in range(1, 2000):
                cand = next_free_filename(base, ext, used, blocked_ci=tried_ci, start_num=start_num)
                tried_ci.add(cand.casefold())
                cweb = os.path.join(web_dir, cand)
                cthumb = os.path.join(thumb_dir, cand)
                if not os.path.exists(cweb) and not os.path.exists(cthumb):
                    newname = cand
                    values["File_Name"] = cand
                    web_path = cweb
                    thumb_path = cthumb
                    desk_path = os.path.join(desk_dir, cand)
                    arch_path = os.path.join(arch_dir, cand)
                    fixed = True
                    break
            if not fixed:
                return False, f"destination collision unresolved for {newname}"

        if os.path.exists(orig):
            try:
                if not os.path.exists(arch_path):
                    shutil.copy2(orig, arch_path)
            except Exception:
                pass
            if os.path.abspath(orig) != os.path.abspath(web_path):
                shutil.move(orig, web_path)
        elif not os.path.exists(web_path):
            return False, f"source missing and web not found: {orig}"

        ok = resize_and_watermark(web_path, web_path, thumb_path, desk_path, WATERMARK_TEXT, FONT_PATH)
        if not ok:
            return False, f"resize/watermark failed for {newname}"

        with Image.open(web_path) as im:
            width, height = im.size

        path_url = f"{PUBLIC_URL_BASE}/{year}/{folder}/{newname}"
        thumb_url = f"{PUBLIC_URL_BASE}/{year}/thumbs/{folder}/{newname}"
        # Keep DB status as Approved so uploader semantics remain unchanged.
        qcur.execute(
            f"UPDATE {TABLE_NAME} SET File_Name=?, Width=?, Height=?, Path=?, Thumb_Path=?, Review_Status=? WHERE id=?",
            (newname, width, height, path_url, thumb_url, "Approved", row_id),
        )
        qconn.commit()

        if oldname:
            _remove_used_name_ci(used, oldname)
            used_ci.discard(oldname.casefold())
        if newname.casefold() not in used_ci:
            used.add(newname)
            used_ci.add(newname.casefold())
        return True, ""

    def _publish_worker_main(self):
        result = {"processed": 0, "uploaded": 0, "failed": 0, "uploader_rc": 0, "errors": []}
        try:
            qconn = sqlite3.connect(DB_PATH)
            qcur = qconn.cursor()
            used = load_used_filenames()
            used_ci = {x.casefold() for x in used}

            with self._publish_lock:
                idxs = [
                    i
                    for i, it in enumerate(self.publish_queue)
                    if str(it.get("state") or "").lower() in {"approved", "failed"}
                ]
                self._publish_progress["total"] = max(int(self._publish_progress.get("total") or 0), len(idxs))

            for n, idx in enumerate(idxs, start=1):
                with self._publish_lock:
                    if idx >= len(self.publish_queue):
                        continue
                    item = self.publish_queue[idx]
                ok, err = self._process_publish_item(item, qcur, qconn, used, used_ci)
                now = datetime.now().isoformat(timespec="seconds")
                with self._publish_lock:
                    if idx < len(self.publish_queue):
                        it = self.publish_queue[idx]
                        it["updated_at"] = now
                        it["attempts"] = int(it.get("attempts") or 0) + 1
                        if ok:
                            it["state"] = "processed"
                            it["last_error"] = ""
                            result["processed"] += 1
                            self._publish_progress["last"] = f"processed row_id={it.get('row_id')}"
                        else:
                            it["state"] = "failed"
                            it["last_error"] = err
                            result["failed"] += 1
                            result["errors"].append(f"row_id={it.get('row_id')} {err}")
                            self._publish_progress["last"] = f"failed row_id={it.get('row_id')}"
                        self._publish_progress["processed"] = n
                save_used_filenames(used)
                self._save_publish_queue()

            with self._publish_lock:
                self._publish_progress["phase"] = "upload"

            # Upload stage still reads Review_Status='Approved' from review_queue.
            rc, out = self._run_db_uploader_worker()
            result["uploader_rc"] = int(rc)
            if rc != 0:
                result["errors"].append((out or "")[-1600:])

            # Reconcile uploaded state: db_uploader deletes uploaded rows from review_queue.
            qcur.execute(f"SELECT id FROM {TABLE_NAME}")
            remain_ids = {int(r[0]) for r in qcur.fetchall()}
            with self._publish_lock:
                for it in self.publish_queue:
                    if str(it.get("state") or "").lower() != "processed":
                        continue
                    rid = int(it.get("row_id") or 0)
                    if rid > 0 and rid not in remain_ids:
                        it["state"] = "uploaded"
                        it["updated_at"] = datetime.now().isoformat(timespec="seconds")
                        it["last_error"] = ""
                        result["uploaded"] += 1
                self._publish_progress["uploaded"] = result["uploaded"]
                self._publish_progress["failed"] = result["failed"]
                self._publish_progress["phase"] = "done"
            self._save_publish_queue()
            qconn.close()
        except Exception:
            result["failed"] += 1
            result["errors"].append(traceback.format_exc())
            with self._publish_lock:
                self._publish_progress["phase"] = "error"
                self._publish_progress["last"] = "publish worker crashed"
        finally:
            with self._publish_lock:
                self._publish_last_result = result

    def _poll_publish_worker(self):
        self._refresh_publish_status()
        t = self._publish_thread
        if t and t.is_alive():
            self.master.after(300, self._poll_publish_worker)
            return
        self._publish_running = False
        self._refresh_publish_status()
        with self._publish_lock:
            r = dict(self._publish_last_result or {})
        errs = r.get("errors") or []
        if errs:
            tail = "\n".join([str(x) for x in errs][-5:])
            messagebox.showwarning(
                "Publish finished",
                f"processed={r.get('processed',0)} uploaded={r.get('uploaded',0)} failed={r.get('failed',0)}\n\n{tail}\n\nClick OK to close.",
            )
        else:
            messagebox.showinfo(
                "Publish complete",
                f"processed={r.get('processed',0)} uploaded={r.get('uploaded',0)} failed={r.get('failed',0)}\n\nClick OK to close.",
            )
        self._on_close()

    # ---------- Shared dictionary spellcheck for editable text fields ----------
    def _spellcheck_available(self) -> bool:
        if self._spellcheck_ok_cached is not None:
            return bool(self._spellcheck_ok_cached)
        try:
            ok, _reason = spellcheck_status(DATA_DIR)
            self._spellcheck_ok_cached = bool(ok)
        except Exception:
            self._spellcheck_ok_cached = False
        return bool(self._spellcheck_ok_cached)

    def _schedule_text_spellcheck(self, field_name: str, delay_ms: int = 120):
        if field_name not in self.text_widgets:
            return
        self._fit_text_height(field_name)
        old = self._text_spell_after_ids.get(field_name)
        if old:
            try:
                self.master.after_cancel(old)
            except Exception:
                pass
        try:
            self._text_spell_after_ids[field_name] = self.master.after(
                max(0, int(delay_ms)),
                lambda k=field_name: self._text_spellcheck_update(k),
            )
        except Exception:
            pass

    def _fit_text_height(self, field_name: str):
        w = self.text_widgets.get(field_name)
        if not w:
            return
        min_lines = 3 if field_name == "Keywords" else 2
        max_lines = 8 if field_name == "Keywords" else 6
        try:
            disp = int(w.count("1.0", "end-1c", "displaylines")[0])
        except Exception:
            try:
                txt = w.get("1.0", "end-1c")
                disp = max(1, txt.count("\n") + 1)
            except Exception:
                disp = min_lines
        target = max(min_lines, min(max_lines, disp + 1))
        try:
            if int(w.cget("height")) != target:
                w.configure(height=target)
        except Exception:
            pass

    def _cancel_pending_spellchecks(self):
        for _k, aid in list(self._text_spell_after_ids.items()):
            if not aid:
                continue
            try:
                self.master.after_cancel(aid)
            except Exception:
                pass
        self._text_spell_after_ids.clear()

    def _refresh_text_spellchecks(self, delay_ms: int = 160):
        for k in ("Keywords", "Caption", "alt_text"):
            if k in self.text_widgets:
                self._schedule_text_spellcheck(k, delay_ms=delay_ms)

    def _text_spellcheck_update(self, field_name: str):
        self._text_spell_after_ids.pop(field_name, None)
        w = self.text_widgets.get(field_name)
        if not w:
            return
        try:
            if not int(w.winfo_exists()):
                return
        except Exception:
            return
        try:
            w.tag_remove("spell_miss", "1.0", END)
        except Exception:
            pass

        txt = ""
        try:
            txt = w.get("1.0", "end-1c")
        except Exception:
            txt = ""
        if not txt.strip():
            self._text_spell_hits[field_name] = []
            return
        if not self._spellcheck_available():
            self._text_spell_hits[field_name] = []
            return

        try:
            hits = find_misspellings(txt, DATA_DIR)
        except Exception:
            hits = []
        self._text_spell_hits[field_name] = list(hits or [])

        for h in self._text_spell_hits[field_name]:
            try:
                s = int(h.get("start", -1))
                e = int(h.get("end", -1))
            except Exception:
                continue
            if s < 0 or e <= s:
                continue
            try:
                w.tag_add("spell_miss", f"1.0 + {s} chars", f"1.0 + {e} chars")
            except Exception:
                continue

    @staticmethod
    def _apply_case_like(original: str, replacement: str) -> str:
        if not replacement:
            return original
        if (original or "").isupper():
            return original
        if original[:1].isupper() and original[1:].islower():
            return replacement[:1].upper() + replacement[1:]
        return replacement

    def _text_spell_context_menu(self, ev, field_name: str):
        w = self.text_widgets.get(field_name)
        if not w:
            return
        try:
            w.focus_set()
            click_idx = w.index(f"@{ev.x},{ev.y}")
        except Exception:
            return

        # Ensure hit list is fresh enough for this widget content.
        self._text_spellcheck_update(field_name)
        hits = self._text_spell_hits.get(field_name, [])
        click_off = 0
        try:
            click_off = len(w.get("1.0", click_idx))
        except Exception:
            click_off = 0

        hit = None
        for h in hits:
            try:
                s = int(h.get("start", -1))
                e = int(h.get("end", -1))
            except Exception:
                continue
            if s <= click_off < e:
                hit = h
                break

        menu = Menu(self.master, tearoff=0)

        if hit:
            word = str(hit.get("word") or "").strip()
            sug = str(hit.get("suggestion") or "").strip()
            s = int(hit.get("start", 0))
            e = int(hit.get("end", s))
            start_idx = f"1.0 + {s} chars"
            end_idx = f"1.0 + {e} chars"

            if sug:
                def do_replace():
                    repl = self._apply_case_like(word, sug)
                    try:
                        w.delete(start_idx, end_idx)
                        w.insert(start_idx, repl)
                    except Exception:
                        return
                    self._schedule_text_spellcheck(field_name, delay_ms=30)

                menu.add_command(label=f"Replace with: {sug}", command=do_replace)

            def do_keep_word():
                try:
                    add_spell_exception(word, DATA_DIR)
                except Exception:
                    pass
                self._spellcheck_ok_cached = None
                self._refresh_text_spellchecks()

            menu.add_command(label=f"Keep term (add to exceptions): {word}", command=do_keep_word)
            menu.add_separator()

        # Optional phrase keep from selection
        try:
            sel = (w.get("sel.first", "sel.last") or "").strip()
        except Exception:
            sel = ""
        if sel:
            short_sel = sel if len(sel) <= 42 else (sel[:39] + "...")

            def do_keep_selection():
                try:
                    add_spell_exception(sel, DATA_DIR)
                except Exception:
                    pass
                self._spellcheck_ok_cached = None
                self._refresh_text_spellchecks()

            menu.add_command(
                label=f"Keep selection (add to exceptions): {short_sel}",
                command=do_keep_selection,
            )
        elif not hit:
            menu.add_command(label="No spelling suggestion here", state="disabled")

        try:
            menu.tk_popup(ev.x_root, ev.y_root)
        finally:
            try:
                menu.grab_release()
            except Exception:
                pass


    def get_images_to_review(self) -> list[dict]:
        self.cur.execute(f"""
            SELECT *
            FROM {TABLE_NAME}
            WHERE COALESCE(Review_Status,'Queued') = 'Pending'
            ORDER BY id DESC
        """)
        cols = [c[0] for c in self.cur.description]
        return [dict(zip(cols, row)) for row in self.cur.fetchall()]

    

            # --- QR mouse-wheel control ---
    def _get_qr(self) -> float:
        try:
            return float(self.field_vars['QR'].get())
        except Exception:
            return 6.5

    def _set_qr(self, val: float):
        try:
            v = float(val)
        except Exception:
            v = 6.50
        v = max(1.0, min(10.0, round(v, 2)))       # clamp + 2 decimals
        self.field_vars['QR'].set(f"{v:.2f}")      # update entry (2 dp)
        if 'QC_Status' in self.field_vars:
            self.field_vars['QC_Status'].set(qc_status(v))
        # update slider without re-entering this method via its command
        if hasattr(self, 'qr_scale'):
            self._qr_updating = True
            try:
                self.qr_scale.set(v)
            finally:
                self._qr_updating = False




    def _on_qr_wheel(self, event):
        steps = 1 if getattr(event, "delta", 0) > 0 else -1
        step = 0.01                 # base 0.01
        if event.state & 0x0001:    # Shift -> 0.05
            step = 0.05
        if event.state & 0x0004:    # Ctrl  -> 0.25
            step = 0.25
        self._set_qr(self._get_qr() + steps * step)
        return "break"

    def _on_qr_wheel_up(self, _event):
        self._set_qr(self._get_qr() + 0.01); return "break"

    def _on_qr_wheel_down(self, _event):
        self._set_qr(self._get_qr() - 0.01); return "break"





    def build_layout(self):
        try:
            self.master.grid_rowconfigure(0, weight=1)
            # Keep preview area at its natural width and let the metadata pane
            # absorb extra window width, so the main image area stays in place.
            self.master.grid_columnconfigure(0, weight=0)
            self.master.grid_columnconfigure(1, weight=1)
        except Exception:
            pass

        self.left_frame  = Frame(self.master)
        self.right_frame = Frame(self.master)
        self.left_frame.grid(row=0, column=0, padx=8, pady=8, sticky="nw")
        self.right_frame.grid(row=0, column=1, padx=8, pady=8, sticky="nsew")

        self.image_progress_var = StringVar(value=f"Image 0/{max(1, len(self.images))}")
        self.image_progress_label = Label(
            self.left_frame,
            textvariable=self.image_progress_var,
            font=("Arial", 10, "bold"),
            anchor="e",
            justify="right",
        )

        # image preview + QR guide
        # Fixed-size preview area so the UI never shifts between landscape/portrait
        self.preview_frame = Frame(self.left_frame, width=620, height=620)
        self.preview_frame.pack_propagate(False)
        self.preview_frame.pack()

        self.image_label = Label(self.preview_frame)
        self.image_label.place(relx=0.5, rely=0.5, anchor="center")

        # wheel over the image also tweaks QR
        self.image_label.bind("<MouseWheel>", self._on_qr_wheel)   # Win/mac
        self.image_label.bind("<Button-4>",  self._on_qr_wheel_up) # Linux up
        self.image_label.bind("<Button-5>",  self._on_qr_wheel_down) # Linux down

        qr = Text(self.left_frame, height=13, width=56, wrap='word', fg='#144', font=('Arial', 9))
        qr.insert(END, QR_EXPLANATION)
        qr.config(state=DISABLED)
        qr.pack(pady=(10, 0))
        # Place image counter near the lower-right of the left pane (per requested spot).
        self.image_progress_label.pack(fill="x", pady=(6, 0), padx=(0, 6))

        labels = [
            'id', 'Folder', 'File_Name', 'Path', 'Thumb_Path', 'DateTime',
            'Camera', 'Lens_model', 'Width', 'Height', 'Exposure', 'Aperture',
            'ISO', 'Focal_length', 'Keywords', 'Caption', 'alt_text', 'Location',
            'Subject', 'nima_score', 'blur_score', 'brightness_score', 'contrast_score',
            'brisque_score', 'clip_aesthetic_score', 'QR', 'QC_Status',
            'Review_Status', 'Original_File_Name'
        ]
        for i, label in enumerate(labels):
            # Hide QC_Status: keep a variable but render no widgets
            if label == "QC_Status":
                v = StringVar()
                self.field_vars[label] = v
                continue
            Label(self.right_frame, text=label).grid(row=i, column=0, sticky='e')

            if label in ('Keywords', 'Caption', 'alt_text'):
                # Wider than regular entries (so no scrolling for common edits),
                # but still capped so the fields do not consume the full pane.
                if label == 'Keywords':
                    t_height = 3
                    t_width = 64
                else:
                    t_height = 2
                    t_width = 64
                t = Text(self.right_frame, height=t_height, width=t_width, wrap='word')
                # Keep a capped width; do not stretch across the whole right pane.
                t.grid(row=i, column=1, sticky='w', pady=(1, 1))
                try:
                    t.tag_configure("spell_miss", underline=1, foreground="#b00020")
                except Exception:
                    pass
                t.bind("<KeyRelease>", lambda e, k=label: self._schedule_text_spellcheck(k), add="+")
                t.bind("<<Paste>>", lambda e, k=label: self._schedule_text_spellcheck(k), add="+")
                t.bind("<Button-3>", lambda e, k=label: self._text_spell_context_menu(e, k), add="+")
                self.text_widgets[label] = t
            else:
                v = StringVar()
                e = Entry(self.right_frame, textvariable=v, width=60)
                e.grid(row=i, column=1, sticky='w')
                self.field_vars[label] = v
                locked = {
                    'id', 'Path', 'Thumb_Path', 'Original_File_Name',
                    'DateTime', 'Camera', 'Lens_model',
                    'Width', 'Height', 'Exposure', 'Aperture', 'ISO', 'Focal_length',
                    'nima_score', 'blur_score', 'brightness_score', 'contrast_score',
                    'brisque_score', 'clip_aesthetic_score'
                }
                if label in locked:
                    e.config(state='readonly')


                if label == 'QR':
                    self.qr_entry = e
                    # Windows / macOS
                    self.qr_entry.bind("<MouseWheel>", self._on_qr_wheel)
                    # Linux
                    self.qr_entry.bind("<Button-4>",  self._on_qr_wheel_up)
                    self.qr_entry.bind("<Button-5>",  self._on_qr_wheel_down)
                            # Place a horizontal slider right under the QR entry
                    self.qr_row = i  # remember where QR lives to place slider on next row

        # Let the action row use real pane width; fields stay capped because their widgets
        # use a fixed width and do not stretch east-west.
        self.right_frame.grid_columnconfigure(1, weight=0)
        self.right_frame.grid_columnconfigure(0, weight=0)

        # Primary actions (Generate / Approve) aligned to the metadata region,
        # with a stable, visible spacing.
        self.primary_action_bar = Frame(self.right_frame)
        self.primary_action_bar.grid(row=99, column=1, sticky="w", pady=(10, 8))
        self.btn_generate = Button(
            self.primary_action_bar,
            text="Generate",
            width=14,
            height=2,
            command=lambda: self._run_ui_action("generate", self.regenerate_current),
        )
        self.btn_generate.grid(row=0, column=0, sticky="w")
        Frame(self.primary_action_bar, width=160).grid(row=0, column=1)
        self.btn_approve = Button(
            self.primary_action_bar,
            text="Approve",
            width=14,
            height=2,
            command=lambda: self._run_ui_action("approve", self.approve),
        )
        self.btn_approve.grid(row=0, column=2, sticky="w")

        # Secondary actions stay together below.
        self.button_bar = Frame(self.right_frame)
        self.button_bar.grid(row=100, column=1, sticky="w", pady=(0, 2))
        self._review_action_buttons = [self.btn_generate, self.btn_approve]
        for i, (key, txt, cmd, action_name) in enumerate([
            ("back", "Back", self.back, "back"),
            ("reject", "Reject", self.reject, "reject"),
            ("pending", "Pending", self.pending, "pending"),
            ("publish", "Publish", self.publish, "publish"),
        ]):
            b = Button(
                self.button_bar,
                text=txt,
                command=lambda _c=cmd, _a=action_name: self._run_ui_action(_a, _c),
            )
            setattr(self, f"btn_{key}", b)
            self._review_action_buttons.append(b)
            b.grid(row=0, column=i, padx=(0, 6))

        self.publish_control_bar = Frame(self.right_frame)
        self.publish_control_bar.grid(row=101, column=1, sticky="w", pady=(2, 4))
        Button(
            self.publish_control_bar,
            text="Resume Publish",
            command=lambda: self._run_ui_action("resume_publish", self._start_publish_worker),
        ).grid(row=0, column=0, padx=(0, 6))
        Button(
            self.publish_control_bar,
            text="Recover Actual",
            command=lambda: self._run_ui_action("recover_actual", self._run_recovery_from_revamp),
        ).grid(row=0, column=1, padx=(0, 6))

        Label(
            self.right_frame,
            textvariable=self.publish_status_var,
            anchor="w",
            justify="left",
            fg="#245",
        ).grid(row=102, column=1, sticky="w", pady=(2, 4))

        # ---- QR slider under the QR row (recursion-safe) ----
        try:
            r = getattr(self, "qr_row", None)
            if r is not None:
                def _on_qr_scale(v: str):
                    # ignore callbacks triggered by our own programmatic .set()
                    if self._qr_updating:
                        return
                    self._set_qr(float(v))

                self.qr_scale = ttk.Scale(
                    self.right_frame,
                    from_=1.0, to=10.0, orient='horizontal', length=380,
                    command=_on_qr_scale
                )
                # initial value (matches the entry; two decimals supported)
                self._qr_updating = True
                try:
                    init = float(self.field_vars.get('QR', StringVar(value="6.50")).get() or 6.50)
                    self.qr_scale.set(init)
                finally:
                    self._qr_updating = False

                # put it right under the QR entry
                self.qr_scale.grid(row=r+1, column=1, sticky='w', pady=(2, 10))
        except Exception:
            pass



    def load_image(self):
        img = self.images[self.idx]
        try:
            self.image_progress_var.set(f"Image {self.idx + 1}/{max(1, len(self.images))}")
        except Exception:
            pass

        # Fill widgets
        for k, v in img.items():
            if k in self.field_vars:
                self.field_vars[k].set("" if v is None else str(v))
            if k in self.text_widgets:
                self.text_widgets[k].delete("1.0", END)
                if v: self.text_widgets[k].insert(END, str(v))
                self._fit_text_height(k)

        # Try to display the image: prefer Path; fall back to LOCAL_BASE/year/folder/name
        display_path = None
        orig_path = img.get("Path")
        if orig_path and os.path.exists(orig_path):
            display_path = orig_path
        else:
            year   = (img.get("DateTime") or "")[:4]
            folder = img.get("Folder") or ""
            name   = img.get("File_Name") or ""
            alt = os.path.join(LOCAL_BASE, year, folder, name)
            if os.path.exists(alt):
                display_path = alt
            else:
                # also try the incoming folder while still in review
                inc_try = os.path.join(INCOMING_DIR, img.get("Original_File_Name") or img.get("File_Name") or "")
                if inc_try and os.path.exists(inc_try):
                    display_path = inc_try


        try:
            if display_path and os.path.exists(display_path):
                im = Image.open(display_path)
                im.thumbnail((600, 600))
                tkimg = ImageTk.PhotoImage(im)
                self.image_label.configure(image=tkimg, text="")
                self.image_label.image = tkimg
            else:
                self.image_label.configure(image=None, text="Image not found")
        except Exception:
            self.image_label.configure(image=None, text="Image not found")

        # Derive QC_Status from QR if blank
        cur_qc = self.field_vars.get('QC_Status').get()
        if not cur_qc:
            self.field_vars['QC_Status'].set(qc_status(self.field_vars.get('QR').get()))

        # Spellcheck refresh can be expensive. Keep it disabled on image-load by
        # default to avoid navigation crashes during rapid approve/reject runs.
        # It still runs on text edits and context-menu checks.
        self._cancel_pending_spellchecks()
        if self._autoscan_spell_on_load:
            self._refresh_text_spellchecks(delay_ms=220)
        else:
            self._text_spell_hits.clear()
            for _w in self.text_widgets.values():
                try:
                    _w.tag_remove("spell_miss", "1.0", END)
                except Exception:
                    pass

        # Keep the QR slider synced with the freshly loaded value (guard re-entrancy)
        try:
            if hasattr(self, "qr_scale"):
                cur = self.field_vars.get('QR').get()
                self._qr_updating = True
                try:
                    self.qr_scale.set(float(cur) if cur not in ("", None) else 6.50)
                finally:
                    self._qr_updating = False
        except Exception:
            pass



    def get_field_values(self) -> dict:
        values = {k: v.get() for k, v in self.field_vars.items()}
        for k, txt in self.text_widgets.items():
            values[k] = txt.get("1.0", END).strip()
        return values

    # -------- Actions --------
    def save_current(self, status: str):
        img    = self.images[self.idx]
        values = self.get_field_values()
        values['QC_Status'] = qc_status(float(values.get('QR', 0) or 0))

        set_cols = [k for k in values.keys() if k not in ('id', 'Review_Status')]
        set_sql  = ", ".join([f"{k}=?" for k in set_cols])
        args     = [values[k] for k in set_cols] + [status, img['id']]
        self.cur.execute(f"UPDATE {TABLE_NAME} SET {set_sql}, Review_Status=? WHERE id=?", args)
        self.conn.commit()

                # ---- ST ledger: upsert into review.db:st_items ----
        try:
            # values comes from self.get_field_values(); we have datetime imported
            st_qr = values.get('QR')
            st_qr = float(st_qr) if (st_qr not in ("", None)) else None

            with sqlite3.connect(DB_PATH) as st_con:
                st_con.execute("""
                INSERT INTO st_items (
                    File_Name, Path, Thumb_Path, Folder, Subject, DateTime,
                    Camera, Lens_model, Width, Height, Exposure, Aperture, ISO, Focal_length,
                    QR_user, Rated_at, source
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(File_Name) DO UPDATE SET
                    Path=excluded.Path, Thumb_Path=excluded.Thumb_Path, Folder=excluded.Folder,
                    Subject=excluded.Subject, DateTime=excluded.DateTime, Camera=excluded.Camera,
                    Lens_model=excluded.Lens_model, Width=excluded.Width, Height=excluded.Height,
                    Exposure=excluded.Exposure, Aperture=excluded.Aperture, ISO=excluded.ISO,
                    Focal_length=excluded.Focal_length,
                    QR_user=excluded.QR_user, Rated_at=excluded.Rated_at, source='editor'
                """, (
                    values.get('File_Name'), values.get('Path'), values.get('Thumb_Path'),
                    values.get('Folder'), values.get('Subject'), values.get('DateTime'),
                    values.get('Camera'), values.get('Lens_model'), values.get('Width'), values.get('Height'),
                    values.get('Exposure'), values.get('Aperture'), values.get('ISO'), values.get('Focal_length'),
                    st_qr, datetime.now().isoformat(timespec="seconds"), 'editor'
                ))
        except Exception as e:
            print("ST upsert failed:", e)


        # Update local copy so moving forward/back keeps edits visible
        self.images[self.idx].update(values)
        self.images[self.idx]['Review_Status'] = status

    def log_action_wrapper(self, decision: str):
        img = self.images[self.idx]
        vals = self.get_field_values()
        changed = []
        for key in ('Caption','alt_text','Keywords','QR','QC_Status','File_Name'):
            if str(img.get(key, '')).strip() != str(vals.get(key, '')).strip():
                changed.append(key.lower())
        log_manual_edit(
            image_id=img['id'],
            file_name=img.get('File_Name'),
            auto_caption=img.get('Caption'),   edited_caption=vals.get('Caption'),
            auto_keywords=img.get('Keywords'), edited_keywords=vals.get('Keywords'),
            auto_score=img.get('QR'),          override_score=vals.get('QR'),
            auto_qc_status=img.get('QC_Status'), override_qc_status=vals.get('QC_Status'),
            auto_filename=img.get('File_Name'),  edited_filename=vals.get('File_Name'),
            decision=decision, comment='',
            fields_changed=",".join(changed),
            edited_by='amir', mysql_id=img['id']
        )

    def _load_caption_module(self):
        if getattr(self, "_caption_mod", None) is not None:
            return self._caption_mod
        try:
            import importlib
            self._caption_mod = importlib.import_module("caption_review_local")
            return self._caption_mod
        except Exception as e:
            messagebox.showerror("Generate", f"Failed to load caption_review_local:\n{e}")
            return None

    def _prefill_generate_uniqueness_ledger(self, crl, ledger, *, exclude_id: int) -> int:
        added = 0
        for row in self.images:
            try:
                rid = int(row.get("id"))
            except Exception:
                rid = -1
            if rid == int(exclude_id):
                continue

            status = str(row.get("Review_Status") or "Pending").strip().lower()
            if status != "pending":
                continue

            caption = str(row.get("Caption") or "").strip()
            alt_text = str(row.get("alt_text") or "").strip()
            keywords_raw = str(row.get("Keywords") or "").strip()
            if not (caption or alt_text or keywords_raw):
                continue

            folder_r = str(row.get("Folder") or "").strip()
            subject_r = str(row.get("Subject") or "").strip()
            file_name_r = str(row.get("File_Name") or "").strip()
            try:
                series_key_r, _ = crl._detect_series_key(folder_r, subject_r, file_name_r)
            except Exception:
                series_key_r = f"{folder_r}|{subject_r}|{file_name_r}"

            kw_list = [k.strip() for k in keywords_raw.split(",") if k.strip()]
            try:
                kw_list = crl._clean_keywords_list(kw_list)
            except Exception:
                pass

            try:
                ledger.add(
                    series_key=series_key_r,
                    caption=caption,
                    alt_text=alt_text,
                    keywords=kw_list,
                    prefix_words=CAPTION_PREFIX_WORDS,
                )
                added += 1
            except Exception:
                # Fallback: still guard exact caption duplicates if helper internals change.
                try:
                    cap_norm = crl._norm_text_strict(caption)
                    if cap_norm:
                        ledger.caption_global.add(cap_norm)
                except Exception:
                    pass
        return added

    def regenerate_current(self):
        img = self.images[self.idx]
        values = self.get_field_values()
        image_path = (values.get("ollama_path") or img.get("ollama_path") or values.get("Path") or img.get("Path") or "").strip()
        if not image_path:
            messagebox.showerror("Generate", "No image path available for this row.")
            return

        crl = self._load_caption_module()
        if crl is None:
            return

        folder = str(values.get("Folder") or img.get("Folder") or "").strip()
        subject = str(values.get("Subject") or img.get("Subject") or "").strip()
        location = str(values.get("Location") or img.get("Location") or "").strip()
        file_name = str(values.get("File_Name") or img.get("File_Name") or "").strip()

        try:
            series_key, sequence_no = crl._detect_series_key(folder, subject, file_name)
        except Exception:
            series_key, sequence_no = f"{folder}|{subject}|{file_name}", 1

        ledger = crl.UniquenessLedger()
        try:
            self._prefill_generate_uniqueness_ledger(
                crl,
                ledger,
                exclude_id=int(img.get("id") or 0),
            )
        except Exception:
            pass

        ok, cap, kws, alt_or_err = crl.process_one(
            ledger=ledger,
            series_key=series_key,
            file_name=file_name,
            sequence_no=int(sequence_no or 1),
            series_size=1,
            folder=folder,
            subject=subject,
            location=location,
            image_path=Path(image_path),
            endpoint=CAPTION_ENDPOINT,
            model=CAPTION_MODEL,
            timeout=CAPTION_TIMEOUT_SEC,
            options=CAPTION_OPTS,
            img_max_side=1024,
            img_quality=85,
            keywords_n=CAPTION_KEYWORDS_N,
            prefix_words=CAPTION_PREFIX_WORDS,
            series_large_threshold=CAPTION_SERIES_LARGE_THRESHOLD,
            max_tries=CAPTION_MAX_TRIES,
            rewrite_weak=CAPTION_REWRITE_WEAK,
            rewrite_max_passes=CAPTION_REWRITE_MAX_PASSES,
            quality_min_score=CAPTION_QUALITY_MIN_SCORE,
        )

        if not ok and CAPTION_MODEL_FALLBACK:
            ok, cap, kws, alt_or_err = crl.process_one(
                ledger=ledger,
                series_key=series_key,
                file_name=file_name,
                sequence_no=int(sequence_no or 1),
                series_size=1,
                folder=folder,
                subject=subject,
                location=location,
                image_path=Path(image_path),
                endpoint=CAPTION_ENDPOINT,
                model=CAPTION_MODEL_FALLBACK,
                timeout=CAPTION_TIMEOUT_SEC,
                options=CAPTION_OPTS,
                img_max_side=1024,
                img_quality=85,
                keywords_n=CAPTION_KEYWORDS_N,
                prefix_words=CAPTION_PREFIX_WORDS,
                series_large_threshold=CAPTION_SERIES_LARGE_THRESHOLD,
                max_tries=max(2, CAPTION_MAX_TRIES),
                rewrite_weak=CAPTION_REWRITE_WEAK,
                rewrite_max_passes=CAPTION_REWRITE_MAX_PASSES,
                quality_min_score=CAPTION_QUALITY_MIN_SCORE,
            )

        if not ok:
            messagebox.showerror("Generate", f"Regenerate failed: {alt_or_err}")
            return

        # Update UI fields but do not change status until the user approves.
        try:
            self.text_widgets["Caption"].delete("1.0", END)
            self.text_widgets["Caption"].insert(END, cap)
            self._fit_text_height("Caption")
            self.text_widgets["alt_text"].delete("1.0", END)
            self.text_widgets["alt_text"].insert(END, alt_or_err)
            self._fit_text_height("alt_text")
            self.text_widgets["Keywords"].delete("1.0", END)
            self.text_widgets["Keywords"].insert(END, kws)
            self._fit_text_height("Keywords")
        except Exception:
            pass

        # Persist to DB with current status to avoid losing the regenerate result.
        try:
            status = str(img.get("Review_Status") or "Pending")
            self.save_current(status)
        except Exception:
            pass

    def approve(self):
        img   = self.images[self.idx]
        vals  = self.get_field_values()
        year      = (img.get("DateTime") or "")[:4]
        folder_in = (vals.get("Folder") or "").strip()

        # enforce folder_map.json as source of truth
        FOLDER_MAP_FILE = os.path.join(DATA_DIR, "folder_map.json")
        try:
            with open(FOLDER_MAP_FILE, "r", encoding="utf-8") as _f:
                _fmap = json.load(_f)
        except Exception:
            _fmap = {}
        if not isinstance(_fmap, dict):
            _fmap = {}

        # resolve key from map (accept key or display)
        folder = next((k for k, v in _fmap.items() if folder_in == k or folder_in == v), "")

        if not folder:
            if not messagebox.askyesno("New folder?", f"'{folder_in}' is not in folder_map.json.\n\nWould you like to create a new folder?"):
                self._wants_upload = False
                return
            # create new mapping
            folder = clean_token(folder_in)
            try:
                _fmap[folder] = folder_in
                with open(FOLDER_MAP_FILE, "w", encoding="utf-8") as _f:
                    json.dump(_fmap, _f, ensure_ascii=False, indent=2)
            except Exception as e:
                messagebox.showerror("Folder map", f"Failed to update folder_map.json:\n{e}")
                self._wants_upload = False
                return


        _ensure_used_json()
        used = load_used_filenames()
        # Reserve names already queued in durable publish queue so two approvals
        # across restarts cannot pick the same destination filename.
        used |= self._publish_queue_used_names()
        used_ci = {x.casefold() for x in used}

        suggested = clean_filename(vals.get("File_Name"))

        if not suggested:
            messagebox.showerror("Filename missing", "File_Name cannot be empty.")
            return

        base, num, ext = split_filename_num(suggested)
        next_num_start = (int(num) + 1) if (num and str(num).isdigit()) else None

        web_dir    = os.path.join(LOCAL_BASE, year, folder)
        thumb_dir  = os.path.join(LOCAL_BASE, year, "thumbs", folder)
        web_path   = os.path.join(web_dir,   suggested)
        thumb_path = os.path.join(thumb_dir, suggested)

        exists_on_disk = os.path.exists(web_path) or os.path.exists(thumb_path)
        original = suggested
        current_row_name = clean_filename(img.get("File_Name") or "")
        tried_ci: set[str] = set()

        # If the suggested name is already taken (JSON or disk), pick the next free slot
        while suggested.casefold() in used_ci or exists_on_disk:
            # Keep user-entered current row name only when destination is actually free.
            if current_row_name and current_row_name.casefold() == suggested.casefold() and not exists_on_disk:
                break
            tried_ci.add(suggested.casefold())
            suggested   = next_free_filename(
                base, ext, used, blocked_ci=tried_ci, start_num=next_num_start
            )
            web_path    = os.path.join(web_dir,   suggested)
            thumb_path  = os.path.join(thumb_dir, suggested)
            exists_on_disk = os.path.exists(web_path) or os.path.exists(thumb_path)

        if suggested != original:
            messagebox.showinfo("Renamed", f"'{original}' exists. Using next available: '{suggested}'")
            self.field_vars['File_Name'].set(suggested)

        # Final overwrite guard
        if os.path.exists(web_path) or os.path.exists(thumb_path):
            messagebox.showerror("Critical Error",
                f"'{suggested}' already exists in destination. Aborting to avoid overwrite.")
            self._wants_upload = False
            return

        # Persist this row as 'Approved' and queue file ops
        self.save_current('Approved')
        self.log_action_wrapper('approved')

        img_updated = self.get_field_values()
        img_updated['id'] = img['id']
        self._enqueue_publish_item(img.copy(), img_updated.copy())
        self._wants_upload = True

        self.next_image()


    def reject(self):
        img = self.images[self.idx]
        try:
            # Move original file to rejected folder (best-effort)
            if img.get("Path") and os.path.exists(img["Path"]):
                os.makedirs(REJECTED_FOLDER, exist_ok=True)
                shutil.move(img["Path"], os.path.join(REJECTED_FOLDER, os.path.basename(img["Path"])))
        except Exception as e:
            print(f"[WARN] Could not move to rejected: {e}")

        # NEW: free the suggested name so you can reuse it later
        try:
            _ensure_used_json()
            used = load_used_filenames()

            # remove both the current suggested File_Name and the Original_File_Name, if present
            fn = clean_filename((img.get("File_Name") or "").strip())
            ofn = clean_filename((img.get("Original_File_Name") or "").strip())

            changed = False
            if fn:
                changed = _remove_used_name_ci(used, fn) or changed
            if ofn:
                changed = _remove_used_name_ci(used, ofn) or changed

            if changed:
                save_used_filenames(used)
                # optional: print(f"[USED] Freed: {fn or ofn}")
        except Exception as e:
            print(f"[WARN] Could not update used_filenames.json on reject: {e}")

        # Log & remove DB row
        self.log_action_wrapper('rejected')
        self.cur.execute(f"DELETE FROM {TABLE_NAME} WHERE id=?", (img['id'],))
        self.conn.commit()

        self._wants_upload = False
        self.next_image()


    def pending(self):
        self.save_current('Pending')
        self.log_action_wrapper('pending')
        self._wants_upload = False
        self.next_image()

    def publish(self):
        self.save_current('Published')
        self.log_action_wrapper('published')
        self._wants_upload = True
        self.next_image()

    def process_all_file_ops(self):
        # Legacy compatibility entrypoint: publishing is now always done by
        # the durable background worker.
        self._start_publish_worker()


    def next_image(self):
        self._cancel_pending_spellchecks()
        self.idx += 1
        if self.idx < len(self.images):
            self.load_image()
            return

        # End of queue
        if self._wants_upload and self._has_pending_publish_items():
            self._set_review_actions_enabled(False)
            if messagebox.askyesno(
                "Done",
                "All images reviewed.\n\nStart move/rename/resize/upload now in background?",
            ):
                self._start_publish_worker()
                messagebox.showinfo(
                    "Publishing started",
                    "Background publish started.\n\nYou can keep this window open to monitor progress.",
                )
                return
            messagebox.showinfo(
                "Review complete",
                "Review is complete.\n\nPublish queue is saved. Use 'Resume Publish' anytime.",
            )
            return

        messagebox.showinfo("Done", "Review complete.")
        # Cancel any pending Tk "after" callbacks to avoid:
        # invalid command name "<id>_apply" ("after" script)
        try:
            for aid in self.master.tk.call("after", "info"):
                try:
                    self.master.tk.call("after", "cancel", aid)
                except Exception:
                    pass
        except Exception:
            pass

        self.master.destroy()

    def back(self):
        if self.idx > 0:
            self._cancel_pending_spellchecks()
            self.idx -= 1
            self.load_image()
        else:
            messagebox.showinfo("Back", "This is the first image.")

# ---------------- Entry ----------------
if __name__ == "__main__":
    print(f"[EDITOR] Using DB: {DB_PATH}")
    _ensure_used_json()  # guarantee the main JSON exists
    root = Tk()
    app  = ReviewApp(root)
    root.mainloop()

