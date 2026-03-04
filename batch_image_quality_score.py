# batch_image_quality_score.py
import os
import sys
import sqlite3
import argparse
import shutil
import stat
import time
import cv2
import numpy as np
from PIL import Image
# Avoid Pillow's decompression-bomb warning while still keeping a guard
Image.MAX_IMAGE_PIXELS = 300_000_000  # ~300 MP cap; your 129 MP file is safe
from tqdm import tqdm

# Keep HF/timm cache deterministic and local to this app tree.
# IMPORTANT: do this before importing pyiqa/timm, otherwise those libraries may
# lock cache paths from parent env (e.g. Anaconda XDG cache).
_APP_ROOT = (
    os.path.dirname(sys.executable)
    if getattr(sys, "frozen", False)
    else os.path.dirname(os.path.abspath(__file__))
)
_APP_CACHE_ROOT = os.path.join(_APP_ROOT, ".cache")
_HF_HOME = os.path.join(_APP_CACHE_ROOT, "huggingface")
_HF_HUB_CACHE = os.path.join(_HF_HOME, "hub")
os.makedirs(_HF_HUB_CACHE, exist_ok=True)
os.makedirs(os.path.join(_APP_CACHE_ROOT, "pyiqa"), exist_ok=True)
os.environ["XDG_CACHE_HOME"] = _APP_CACHE_ROOT
os.environ["HF_HOME"] = _HF_HOME
os.environ["HUGGINGFACE_HUB_CACHE"] = _HF_HUB_CACHE
os.environ["PYIQA_ROOT"] = os.path.join(_APP_CACHE_ROOT, "pyiqa")
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

# Strict mode is ON by default: scoring must use pyiqa (NIMA/BRISQUE) or fail.
SAFE_SCORING_MODE = os.getenv("AMIR_SCORE_SAFE_MODE", "0") == "1"
STRICT_PYIQA_REQUIRED = os.getenv("AMIR_SCORE_REQUIRE_PYIQA", "1") == "1"

def _known_timm_model_cache_dir() -> str:
    hf_cache_root = os.path.join(
        os.environ.get("HUGGINGFACE_HUB_CACHE") or os.path.join(
            os.environ.get("HF_HOME") or os.path.join(
                os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache"),
                "huggingface",
            ),
            "hub",
        )
    )
    return os.path.join(hf_cache_root, "models--timm--inception_resnet_v2.tf_in1k")


def _try_open_readable(path: str) -> bool:
    try:
        with open(path, "rb") as fh:
            fh.read(16)
        return True
    except Exception:
        return False


def _rmtree_force(path: str, retries: int = 3) -> bool:
    def _on_rm_error(func, p, exc_info):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass

    for _ in range(max(1, int(retries))):
        try:
            if os.path.lexists(path):
                shutil.rmtree(path, onerror=_on_rm_error)
        except Exception:
            pass
        if not os.path.lexists(path):
            return True
        time.sleep(0.4)
    return not os.path.lexists(path)


def _materialize_regular_file(target_path: str, source_path: str) -> bool:
    """
    Replace target_path with a regular file copied from source_path.
    Useful when target_path is a broken symlink in HF snapshot cache.
    """
    try:
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        if os.path.lexists(target_path):
            try:
                os.chmod(target_path, stat.S_IWRITE)
            except Exception:
                pass
            try:
                os.remove(target_path)
            except Exception:
                try:
                    shutil.rmtree(target_path, ignore_errors=True)
                except Exception:
                    pass
        shutil.copy2(source_path, target_path)
        return _try_open_readable(target_path)
    except Exception:
        return False


def _ensure_known_timm_model_file(max_attempts: int = 3) -> str:
    """
    Ensure the timm backbone file exists and is actually readable.
    This protects strict scoring from broken symlink/snapshot states.
    """
    last_err: Exception | None = None
    model_dir = _known_timm_model_cache_dir()

    for attempt in range(1, max(1, int(max_attempts)) + 1):
        try:
            from huggingface_hub import hf_hub_download  # type: ignore

            model_path = hf_hub_download(
                repo_id="timm/inception_resnet_v2.tf_in1k",
                filename="model.safetensors",
                force_download=(attempt > 1),
            )
            if _try_open_readable(model_path):
                return model_path

            # Fallback: fetch a plain local file (no symlinks), then materialize
            # that file at the cache snapshot path expected by timm/hf_hub.
            fallback_dir = os.path.join(_APP_CACHE_ROOT, "hf_fallback_files", "timm_inception_resnet_v2_tf_in1k")
            os.makedirs(fallback_dir, exist_ok=True)
            fallback_file = hf_hub_download(
                repo_id="timm/inception_resnet_v2.tf_in1k",
                filename="model.safetensors",
                local_dir=fallback_dir,
                local_dir_use_symlinks=False,
                force_download=True,
            )
            if not _try_open_readable(fallback_file):
                raise FileNotFoundError(f"Fallback model file is not readable: {fallback_file}")
            if _materialize_regular_file(model_path, fallback_file):
                return model_path
            raise FileNotFoundError(f"Downloaded model path is not readable: {model_path}")
        except Exception as e:
            last_err = e
            if attempt < max_attempts:
                print(
                    "[WARN] Detected broken timm cache snapshot for strict scoring; "
                    "clearing cache entry and retrying once."
                )
                _rmtree_force(model_dir, retries=3)
                time.sleep(min(1.2, 0.4 * attempt))
                continue
            break

    raise RuntimeError(f"Unable to prepare timm cache for strict scoring: {last_err}")


def _repair_known_timm_cache_if_broken() -> bool:
    """
    Repair known broken HF cache state for timm/inception_resnet_v2.tf_in1k.
    This keeps strict scoring enabled while allowing one self-heal retry.
    """
    try:
        _ensure_known_timm_model_file(max_attempts=2)
        return True
    except Exception:
        return False


def _create_metric_with_single_repair_retry(metric_name: str):
    if pyiqa is None:
        return None
    try:
        return pyiqa.create_metric(metric_name).cpu()
    except Exception as first_err:
        msg = str(first_err)
        should_try_repair = (
            "No such file or directory" in msg
            and "models--timm--inception_resnet_v2.tf_in1k" in msg
        )
        if should_try_repair and _repair_known_timm_cache_if_broken():
            return pyiqa.create_metric(metric_name).cpu()
        raise

if SAFE_SCORING_MODE and STRICT_PYIQA_REQUIRED:
    print("[ERROR] Invalid scoring config: safe mode is enabled while strict pyiqa scoring is required.")
    sys.exit(2)

pyiqa = None
if not SAFE_SCORING_MODE:
    try:
        import pyiqa as _pyiqa  # type: ignore
        pyiqa = _pyiqa
    except Exception as e:
        pyiqa = None
        if STRICT_PYIQA_REQUIRED:
            print(f"[ERROR] pyiqa unavailable and strict scoring is enabled: {e}")
            sys.exit(2)
        print(f"[WARN] pyiqa unavailable, running without NIMA/BRISQUE: {e}")
else:
    print("[INFO] Safe scoring mode enabled: skipping pyiqa (NIMA/BRISQUE).")

if pyiqa is not None:
    try:
        _ensure_known_timm_model_file(max_attempts=3)
    except Exception as e:
        if STRICT_PYIQA_REQUIRED:
            print(f"[ERROR] TIMM cache unavailable and strict scoring is enabled: {e}")
            sys.exit(2)
        print(f"[WARN] TIMM cache unavailable, proceeding with fallback scoring: {e}")

# ---------------- resource helpers ----------------
from pathlib import Path
import importlib.util

def resource_path(rel: str) -> str:
    """Resolve paths for source runs and PyInstaller builds (also checks _internal)."""
    rel = rel.replace("/", os.sep).replace("\\", os.sep)
    candidates: list[str] = []

    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        candidates.append(os.path.join(exe_dir, rel))
        candidates.append(os.path.join(exe_dir, "_internal", rel))
        try:
            meipass = sys._MEIPASS  # type: ignore[attr-defined]
            candidates.append(os.path.join(meipass, rel))
            candidates.append(os.path.join(meipass, "_internal", rel))
        except Exception:
            pass

    src_dir = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(src_dir, rel))
    candidates.append(os.path.join(src_dir, "_internal", rel))

    for p in candidates:
        if os.path.exists(p):
            return p
    return candidates[0]

def _load_config():
    """Load amir2000_config.py from beside the EXE (preferred) or beside this file."""
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "amir2000_config.py")
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

# Ensure simple_inference can find the .pth when frozen
try:
    model_dir = os.path.dirname(resource_path("sac+logos+ava1-l14-linearMSE.pth"))
    if model_dir and os.path.isdir(model_dir):
        os.chdir(model_dir)
except Exception:
    pass

try:
    from simple_inference import get_image_aesthetic_score
except Exception as e:
    get_image_aesthetic_score = None
    print(f"[WARN] CLIP aesthetic unavailable, continuing without it: {e}")


# ---------------- constants/paths ----------------
INCOMING_DIR = PATHS.get("INCOMING_DIR", r"YOUR_PATH_HERE")
TABLE_NAME   = PUBLISH.get("REVIEW_QUEUE_TABLE", "review_queue")

DB_PATH = os.environ.get(
    "AMIR_REVIEW_DB",
    PATHS.get("REVIEW_DB_PATH", r"YOUR_PATH_HERE")
)

# pyiqa cache location (writeable when frozen)
os.environ.setdefault(
    "PYIQA_ROOT",
    os.path.join(
        (os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))),
        ".cache",
        "pyiqa",
    )
)

# ---------------- metrics setup ----------------
# In-memory proxy loader for scoring only (does not write to disk)
def _load_pil_proxy(path: str, max_edge: int = 4096):
    im = Image.open(path).convert("RGB")
    w, h = im.size
    if max(w, h) > max_edge:
        scale = max(w, h) / max_edge
        im = im.resize((int(w/scale), int(h/scale)), Image.Resampling.LANCZOS)
    return im

# NIMA (pyiqa) when available, else None
nima = None
if pyiqa is not None:
    try:
        nima = _create_metric_with_single_repair_retry("nima")
    except Exception as e:
        nima = None
        if STRICT_PYIQA_REQUIRED:
            print(f"[ERROR] NIMA unavailable and strict scoring is enabled: {e}")
            sys.exit(2)
        print(f"[WARN] NIMA unavailable, using fallback score: {e}")

# BRISQUE (pyiqa). If creation fails, we’ll return None for BRISQUE.
_py_brisque = None
if pyiqa is not None:
    try:
        _py_brisque = _create_metric_with_single_repair_retry("brisque")
    except Exception as e:
        _py_brisque = None
        if STRICT_PYIQA_REQUIRED:
            print(f"[ERROR] BRISQUE unavailable and strict scoring is enabled: {e}")
            sys.exit(2)

def _brisque(path: str):
    if _py_brisque is None:
        return None
    try:
        im = _load_pil_proxy(path, max_edge=4096)
        return float(_py_brisque(im).item())
    except Exception as e:
        print(f"[WARN] pyiqa BRISQUE failed for {os.path.basename(path)}: {e}")
        return None

def _blur(img_bgr: np.ndarray) -> float:
    return cv2.Laplacian(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()

def _bright(img_bgr: np.ndarray) -> float:
    return float(np.mean(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)))

def _contr(img_bgr: np.ndarray) -> float:
    return float(np.std(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)))

def _n(x): return x
def _n_brisque(x): return 0 if x is None else (1 - min(x/100.0, 1.0)) * 10

def _qr(clip_s, nima_s, blur_s, bri_s, con_s, briq):
    # Weighted quality rating (same weights you had)
    return round(
        _n(clip_s or 0)*0.23 + (nima_s or 0)*0.20 + (blur_s or 0)*0.17 +
        (bri_s or 0)*0.17 + (con_s or 0)*0.13 + _n_brisque(briq)*0.10, 2
    )

def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(x)))

def _fallback_brisque(blur_s: float, bright_s: float, contr_s: float, nima_s: float) -> float:
    """
    Deterministic BRISQUE proxy (0..100, lower is better) when pyiqa is unavailable.
    This keeps DB fields non-null and stable across reruns.
    """
    q = (
        _clamp(blur_s, 0.0, 10.0) * 0.35
        + _clamp(bright_s, 0.0, 10.0) * 0.20
        + _clamp(contr_s, 0.0, 10.0) * 0.20
        + _clamp(nima_s, 0.0, 10.0) * 0.25
    ) / 10.0
    return round((1.0 - _clamp(q, 0.0, 1.0)) * 100.0, 2)

def _fallback_clip_aesthetic(blur_s: float, bright_s: float, contr_s: float, nima_s: float) -> float:
    """
    Deterministic CLIP-aesthetic proxy (0..10) when the CLIP scorer is unavailable.
    """
    return round(
        _clamp(
            _clamp(nima_s, 0.0, 10.0) * 0.55
            + _clamp(blur_s, 0.0, 10.0) * 0.20
            + _clamp(bright_s, 0.0, 10.0) * 0.15
            + _clamp(contr_s, 0.0, 10.0) * 0.10,
            0.0,
            10.0,
        ),
        2,
    )

def _qc(qr):
    if qr is None: return "NA"
    try:
        q = float(qr)
    except Exception:
        return "NA"
    if q >= 7.5: return "Top"
    if q >= 6.5: return "Good"
    if q >= 5.5: return "Average"
    if q >= 4.5: return "Low"
    return "Very Low"

# ---------------- DB helpers ----------------

def _ensure_review_columns(db_path):
    # Make sure review_queue has all scoring columns even if this script runs standalone
    with sqlite3.connect(db_path, timeout=30) as conn:
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(review_queue)")
        have = {row[1] for row in cur.fetchall()}
        needed = [
            ("nima_score","REAL"), ("blur_score","REAL"), ("brightness_score","REAL"),
            ("contrast_score","REAL"), ("brisque_score","REAL"), ("clip_aesthetic_score","REAL"),
            ("QR","REAL"), ("QC_Status","TEXT")
        ]
        for col, typ in needed:
            if col not in have:
                cur.execute(f"ALTER TABLE review_queue ADD COLUMN {col} {typ}")
        conn.commit()


def _parse_id_list(raw: str) -> list[int]:
    out: list[int] = []
    if not raw:
        return out
    for part in str(raw).split(","):
        t = part.strip()
        if not t:
            continue
        try:
            v = int(t)
        except Exception:
            continue
        if v > 0:
            out.append(v)
    # keep stable order, dedupe
    seen = set()
    uniq: list[int] = []
    for v in out:
        if v in seen:
            continue
        seen.add(v)
        uniq.append(v)
    return uniq


# ---------------- main ----------------
if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Score image quality metrics into review_queue.")
    ap.add_argument(
        "--id-list",
        default=os.getenv("AMIR_SCORE_ID_LIST", ""),
        help="Optional comma-separated review_queue ids to score (session-scope).",
    )
    args = ap.parse_args()

    _ensure_review_columns(DB_PATH)  # <— add this line
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()


    # Score only rows that are active AND missing required quality metrics.
    # Always include BRISQUE/CLIP columns so reruns can backfill legacy NULLs.
    missing_conds = [
        "nima_score IS NULL",
        "blur_score IS NULL",
        "brightness_score IS NULL",
        "contrast_score IS NULL",
        "brisque_score IS NULL",
        "clip_aesthetic_score IS NULL",
        "QR IS NULL OR QC_Status IS NULL",
    ]

    where_parts = [
        "COALESCE(Review_Status,'Queued') IN ('Pending','Queued','Error')",
        "(" + " OR ".join(missing_conds) + ")",
    ]
    params: list[object] = []

    scoped_ids = _parse_id_list(args.id_list)
    if scoped_ids:
        q = ",".join(["?"] * len(scoped_ids))
        where_parts.append(f"id IN ({q})")
        params.extend(scoped_ids)

    where = " AND ".join(where_parts)

    cur.execute(f"""
      SELECT id, File_Name, COALESCE(Original_File_Name, File_Name)
      FROM {TABLE_NAME}
      WHERE {where}
    """, params)

    rows = cur.fetchall()
    if scoped_ids:
        print(f"[INFO] Scoring scope ids: {len(scoped_ids)}")
    print(f"Scoring {len(rows)} images pending quality...")

    had_error = False

    def _write_scores(
        *,
        rid: int,
        nima_score: float,
        blur_s: float,
        bright_s: float,
        contr_s: float,
        brisque_s: float,
        clip_s: float,
        qr: float,
        qc: str,
        mark_error: bool = False,
    ) -> None:
        if mark_error:
            cur.execute(
                f"""
                UPDATE {TABLE_NAME}
                   SET nima_score=?,
                       blur_score=?,
                       brightness_score=?,
                       contrast_score=?,
                       brisque_score=?,
                       clip_aesthetic_score=?,
                       QR=?, QC_Status=?,
                       Review_Status='Error'
                 WHERE id=?""",
                (
                    round(_clamp(nima_score, 0.0, 10.0), 2),
                    round(_clamp(blur_s, 0.0, 10.0), 2),
                    round(_clamp(bright_s, 0.0, 10.0), 2),
                    round(_clamp(contr_s, 0.0, 10.0), 2),
                    round(_clamp(brisque_s, 0.0, 100.0), 2),
                    round(_clamp(clip_s, 0.0, 10.0), 2),
                    round(_clamp(qr, 0.0, 10.0), 2),
                    str(qc or "Very Low"),
                    rid,
                ),
            )
            return

        cur.execute(
            f"""
            UPDATE {TABLE_NAME}
               SET nima_score=?,
                   blur_score=?,
                   brightness_score=?,
                   contrast_score=?,
                   brisque_score=?,
                   clip_aesthetic_score=?,
                   QR=?, QC_Status=?,
                   Review_Status=COALESCE(NULLIF(Review_Status,''),'Pending')
             WHERE id=?""",
            (
                round(_clamp(nima_score, 0.0, 10.0), 2),
                round(_clamp(blur_s, 0.0, 10.0), 2),
                round(_clamp(bright_s, 0.0, 10.0), 2),
                round(_clamp(contr_s, 0.0, 10.0), 2),
                round(_clamp(brisque_s, 0.0, 100.0), 2),
                round(_clamp(clip_s, 0.0, 10.0), 2),
                round(_clamp(qr, 0.0, 10.0), 2),
                str(qc or "NA"),
                rid,
            ),
        )

    pbar = tqdm(rows, desc="Scoring images", dynamic_ncols=True, leave=False)
    for img_id, file_name, orig_file_name in pbar:


        # Resolve path inside incoming
        path = os.path.join(INCOMING_DIR, orig_file_name)
        if not os.path.isfile(path):
            alt = os.path.join(INCOMING_DIR, file_name)
            if not os.path.isfile(alt):
                if STRICT_PYIQA_REQUIRED:
                    print(f"[ERROR] Missing in incoming during strict scoring: {orig_file_name} (id {img_id})")
                    had_error = True
                    break
                # Do not skip: write deterministic worst-case scores so all fields are non-null.
                nima_score = 0.0
                blur_s = 0.0
                bright_s = 0.0
                contr_s = 0.0
                brisque = 100.0
                clip_aes = 0.0
                qr = _qr(clip_aes, nima_score, blur_s, bright_s, contr_s, brisque)
                qc = _qc(qr)
                _write_scores(
                    rid=img_id,
                    nima_score=nima_score,
                    blur_s=blur_s,
                    bright_s=bright_s,
                    contr_s=contr_s,
                    brisque_s=brisque,
                    clip_s=clip_aes,
                    qr=qr,
                    qc=qc,
                    mark_error=True,
                )
                conn.commit()
                print(f"[ERROR] Missing in incoming -> fallback scores written: {orig_file_name} (id {img_id})")
                had_error = True
                continue
            path = alt

        try:
            # Load proxy once for all metrics
            pim = _load_pil_proxy(path, max_edge=4096)

            # Use the same proxy for OpenCV metrics to keep runtime and memory low
            cv = cv2.cvtColor(np.array(pim), cv2.COLOR_RGB2BGR)
            blur_raw   = _blur(cv)
            bright_raw = _bright(cv)
            contr_raw  = _contr(cv)

            # Scale to 0..10
            blur_s   = min(blur_raw/200.0, 1.0)*10
            bright_s = max(0, min(1 - abs((bright_raw-128)/128), 1.0))*10
            contr_s  = min(contr_raw/64.0, 1.0)*10

            if nima is not None:
                try:
                    nima_score = float(nima(pim).item())
                except Exception as e:
                    if STRICT_PYIQA_REQUIRED:
                        raise RuntimeError(f"NIMA failed for id={img_id}: {e}")
                    print(f"[WARN] NIMA failed for id={img_id}: {e}")
                    nima_score = max(0.0, min(10.0, (bright_s + contr_s) / 2.0))
            else:
                if STRICT_PYIQA_REQUIRED:
                    raise RuntimeError(f"NIMA metric unavailable for id={img_id}")
                # Lightweight fallback when pyiqa is disabled/unavailable.
                nima_score = max(0.0, min(10.0, (bright_s + contr_s) / 2.0))

            # BRISQUE (pyiqa) and CLIP aesthetic
            brisque   = _brisque(path)  # may be None
            if STRICT_PYIQA_REQUIRED and brisque is None:
                raise RuntimeError(f"BRISQUE failed or unavailable for id={img_id}")
            clip_aes = None
            if get_image_aesthetic_score is not None:
                try:
                    clip_aes = get_image_aesthetic_score(path)
                except Exception as e:
                    print(f"[WARN] CLIP aesthetic failed for id={img_id}: {e}")
                    clip_aes = None

            if brisque is None:
                brisque = _fallback_brisque(blur_s, bright_s, contr_s, nima_score)
            if clip_aes is None:
                clip_aes = _fallback_clip_aesthetic(blur_s, bright_s, contr_s, nima_score)

            # Compute QR/QC with fully populated numeric metrics.
            qr = _qr(clip_aes, nima_score, blur_s, bright_s, contr_s, brisque)
            qc = _qc(qr)

            _write_scores(
                rid=img_id,
                nima_score=nima_score,
                blur_s=blur_s,
                bright_s=bright_s,
                contr_s=contr_s,
                brisque_s=brisque,
                clip_s=clip_aes,
                qr=qr,
                qc=qc,
                mark_error=False,
            )
            conn.commit()

            pbar.write(f"[OK] id={img_id} scored QR={qr} QC={qc}")



        except Exception as e:
            print(f"[ERROR] Error processing {path}: {e}")
            had_error = True
            if STRICT_PYIQA_REQUIRED:
                break
            try:
                nima_score = 0.0
                blur_s = 0.0
                bright_s = 0.0
                contr_s = 0.0
                brisque = 100.0
                clip_aes = 0.0
                qr = _qr(clip_aes, nima_score, blur_s, bright_s, contr_s, brisque)
                qc = _qc(qr)
                _write_scores(
                    rid=img_id,
                    nima_score=nima_score,
                    blur_s=blur_s,
                    bright_s=bright_s,
                    contr_s=contr_s,
                    brisque_s=brisque,
                    clip_s=clip_aes,
                    qr=qr,
                    qc=qc,
                    mark_error=True,
                )
                conn.commit()
            except Exception:
                pass
            continue

    pbar.close()
    conn.close()


    if had_error:
        print("\n[ERROR] One or more images failed to score.")
        sys.exit(2)


    print("\n[OK] All done! Scores written to your database.")

