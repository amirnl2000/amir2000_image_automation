# batch_image_quality_score.py
import os
import sys
import sqlite3
import argparse
import cv2
import numpy as np
from PIL import Image
# Avoid Pillow's decompression-bomb warning while still keeping a guard
Image.MAX_IMAGE_PIXELS = 300_000_000  # ~300 MP cap; your 129 MP file is safe
import pyiqa
from tqdm import tqdm

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
        (os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.expanduser("~")),
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

# NIMA (pyiqa)
nima = pyiqa.create_metric("nima").cpu()

# BRISQUE (pyiqa). If creation fails, we’ll return None for BRISQUE.
try:
    _py_brisque = pyiqa.create_metric("brisque").cpu()
except Exception:
    _py_brisque = None

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
    missing_conds = [
        "nima_score IS NULL",
        "blur_score IS NULL",
        "brightness_score IS NULL",
        "contrast_score IS NULL",
        "QR IS NULL OR QC_Status IS NULL",
    ]
    if _py_brisque is not None:
        missing_conds.append("brisque_score IS NULL")
    if get_image_aesthetic_score is not None:
        missing_conds.append("clip_aesthetic_score IS NULL")

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

    pbar = tqdm(rows, desc="Scoring images", dynamic_ncols=True, leave=False)
    for img_id, file_name, orig_file_name in pbar:


        # Resolve path inside incoming
        path = os.path.join(INCOMING_DIR, orig_file_name)
        if not os.path.isfile(path):
            alt = os.path.join(INCOMING_DIR, file_name)
            if not os.path.isfile(alt):
                print(f"❌ Not in incoming: {orig_file_name} (id {img_id})")
                had_error = True
                continue
            path = alt

        try:
            # NIMA (pyiqa) on a proxy PIL image (in-memory resize only)
            pim = _load_pil_proxy(path, max_edge=4096)
            nima_score = float(nima(pim).item())

            # Use the same proxy for OpenCV metrics to keep runtime and memory low
            cv = cv2.cvtColor(np.array(pim), cv2.COLOR_RGB2BGR)
            blur_raw   = _blur(cv)
            bright_raw = _bright(cv)
            contr_raw  = _contr(cv)

            # Scale to 0..10
            blur_s   = min(blur_raw/200.0, 1.0)*10
            bright_s = max(0, min(1 - abs((bright_raw-128)/128), 1.0))*10
            contr_s  = min(contr_raw/64.0, 1.0)*10

            # BRISQUE (pyiqa) and CLIP aesthetic
            brisque   = _brisque(path)  # may be None
            clip_aes = None
            if get_image_aesthetic_score is not None:
                try:
                    clip_aes = get_image_aesthetic_score(path)
                except Exception as e:
                    print(f"[WARN] CLIP aesthetic failed for id={img_id}: {e}")
                    clip_aes = None


            # Compute QR/QC even if one metric is None (we treat missing as 0 in _qr)
            qr = _qr(clip_aes, nima_score, blur_s, bright_s, contr_s, brisque)
            qc = _qc(qr)

            
            # 2) Also write directly to review_queue so the editor sees it immediately
            cur.execute(f"""
                UPDATE {TABLE_NAME}
                   SET nima_score=?,
                       blur_score=?,
                       brightness_score=?,
                       contrast_score=?,
                       brisque_score=?,
                       clip_aesthetic_score=?,
                       QR=?, QC_Status=?,
                       Review_Status=COALESCE(Review_Status,'Pending')
                 WHERE id=?""",
                (round(nima_score, 2), round(blur_s, 2), round(bright_s, 2),
                 round(contr_s, 2), None if brisque is None else round(brisque, 2),
                 None if clip_aes is None else round(clip_aes, 2),
                 qr, qc, img_id)
            )
            conn.commit()

            pbar.write(f"[OK] id={img_id} scored QR={qr} QC={qc}")



        except Exception as e:
            print(f"❌ Error processing {path}: {e}")
            had_error = True
            try:
                cur.execute(f"UPDATE {TABLE_NAME} SET Review_Status='Error' WHERE id=?", (img_id,))
                conn.commit()
            except Exception:
                pass
            continue

    pbar.close()
    conn.close()


    if had_error:
        print("\n[WARN] One or more images failed to score. Check 'Error' rows in the editor.")


    print("\n✅ All done! Scores written to your database.")

