import logging
from pathlib import Path
import sys

LOGGER = logging.getLogger("db_uploader")

# Do not override app logging if it already exists
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

# Also log to file (best effort)
try:
    if getattr(sys, "frozen", False):
        _root = Path(sys.executable).resolve().parent
    else:
        _root = Path(__file__).resolve().parent
    _log_dir = _root / "logs"
    _log_dir.mkdir(parents=True, exist_ok=True)

    _fh = logging.FileHandler(_log_dir / "db_uploader.log", encoding="utf-8")
    _fh.setLevel(logging.INFO)
    _fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    LOGGER.addHandler(_fh)
except Exception:
    pass

try:
    from tqdm import tqdm
except Exception:

    def tqdm(it, **kwargs):
        return it


# db_uploader.py - uploader used after review_editor
import os
import sys
import sqlite3
import json
from ftplib import FTP
from datetime import datetime
try:
    import mysql.connector  # type: ignore[import]
    _MYSQL_IMPORT_ERROR = None
except Exception as _mx_ex:
    mysql = None  # type: ignore[assignment]
    _MYSQL_IMPORT_ERROR = _mx_ex

# PyInstaller safety: make auth plugins importable and avoid C-extension DLL issues
if _MYSQL_IMPORT_ERROR is None:
    try:
        import mysql.connector.plugins.mysql_native_password  # noqa: F401
        import mysql.connector.plugins.caching_sha2_password  # noqa: F401
        import mysql.connector.plugins.sha256_password  # noqa: F401
    except Exception:
        pass

import re

_UDUP = re.compile(r"_+")


def clean_token(s: str) -> str:
    s = (s or "").strip().replace(" ", "_")
    s = _UDUP.sub("_", s)
    return s.strip("_")


def clean_filename(name: str) -> str:
    base, ext = os.path.splitext((name or "").strip())
    base = clean_token(base)
    return f"{base}{ext}"


def warn_filename_length(fname: str, max_len: int = 150):
    try:
        n = len(fname or "")
    except Exception:
        n = 0
    if n > max_len:
        try:
            LOGGER.warning("Long filename (%s chars): %s", n, fname)
        except Exception:
            pass
        print(f"[WARN] Long filename ({n} chars): {fname}", file=sys.stderr)


# ---------- resource path helpers for PyInstaller ----------
import importlib.util


def resource_path(rel_path: str) -> str:
    """Resolve paths for source runs and PyInstaller builds (also checks _internal)."""
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
    """Load amir2000_config.py from beside the EXE (preferred) or beside the source file.

    Also checks _internal and sys._MEIPASS locations for PyInstaller builds.
    """
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / "amir2000_config.py")
        candidates.append(exe_dir / "_internal" / "amir2000_config.py")
        try:
            meipass = Path(getattr(sys, "_MEIPASS"))
            candidates.append(meipass / "amir2000_config.py")
            candidates.append(meipass / "_internal" / "amir2000_config.py")
        except Exception:
            pass
    src_dir = Path(__file__).resolve().parent
    candidates.append(src_dir / "amir2000_config.py")
    candidates.append(src_dir / "_internal" / "amir2000_config.py")
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

# Derive key paths strictly from the config or environment.
DATA_DIR = PATHS.get("DATA_DIR") or ""
DB_PATH = os.environ.get("AMIR_REVIEW_DB") or PATHS.get("REVIEW_DB_PATH", os.path.join(DATA_DIR, "review.db"))

# Local mirror DB for syncing with the remote MySQL table.
LOCAL_MIRROR_DB = PATHS.get("LOCAL_MIRROR_DB", os.path.join(DATA_DIR, "photos_info_revamp.db"))
FOLDER_MAP_FILE = os.path.join(DATA_DIR, "folder_map.json")

# Location where review_editor saved the exported images/thumbs.
LOCAL_BASE = PATHS.get("LOCAL_SITE_IMAGES_BASE", "")

# Remote FTP base (directory on the server) and public URL base for Path/Thumb_Path.
REMOTE_BASE = PUBLISH.get("REMOTE_BASE") or ""
PUBLIC_URL_BASE = PUBLISH.get("PUBLIC_URL_BASE") or ""

TABLE_NAME = (PUBLISH.get("MYSQL_MIRROR_TABLE") or os.getenv("AMIR_MYSQL_TABLE") or "photos_info_revamp").strip()
REVIEW_QUEUE = (PUBLISH.get("REVIEW_QUEUE_TABLE") or os.getenv("AMIR_REVIEW_QUEUE_TABLE") or "review_queue").strip()

if not TABLE_NAME or not REVIEW_QUEUE:
    raise RuntimeError(
        "Missing table names. Check amir2000_config.py: PUBLISH.MYSQL_MIRROR_TABLE and PUBLISH.REVIEW_QUEUE_TABLE"
    )

# ---------- credentials (config only) ----------
if not _cfg:
    raise RuntimeError("amir2000_config.py not found. Put it next to the EXE or inside the _internal folder.")

if not getattr(_cfg, "MYSQL", None):
    raise RuntimeError(
        'Missing MYSQL dict in amir2000_config.py (expected MYSQL = {"host":..., "user":..., "password":..., "database":...}).'
    )

MYSQL = dict(getattr(_cfg, "MYSQL"))

for _k in ("host", "user", "password", "database"):
    if not MYSQL.get(_k):
        raise RuntimeError(f'MYSQL["{_k}"] is missing or blank in amir2000_config.py')

MYSQL.setdefault("charset", "utf8mb4")
MYSQL.setdefault("use_unicode", True)
MYSQL.setdefault("autocommit", False)

if not getattr(_cfg, "FTP_CONFIG", None):
    raise RuntimeError(
        'Missing FTP_CONFIG dict in amir2000_config.py (expected FTP_CONFIG = {"host":..., "user":..., "passwd":..., "port":21}).'
    )

FTP_CONFIG = dict(getattr(_cfg, "FTP_CONFIG"))

for _k in ("host", "user", "passwd"):
    if not FTP_CONFIG.get(_k):
        raise RuntimeError(f'FTP_CONFIG["{_k}"] is missing or blank in amir2000_config.py')

FTP_CONFIG["port"] = int(FTP_CONFIG.get("port", 21) or 21)


def load_folder_map():
    try:
        with open(FOLDER_MAP_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def folder_to_key(display_or_key: str, fmap: dict) -> str:
    s = (display_or_key or "").strip()
    if not s:
        return ""
    if s in fmap:
        return s
    for k, v in fmap.items():
        if s == v:
            return k
    raise ValueError(
        f"Folder '{s}' is not in folder_map.json. Would you like to create a new folder? Add it in main_set first."
    )


def canonical_folder_slug(folder_in: str, fmap: dict) -> str:
    s = (folder_in or "").strip()
    if not s:
        return ""
    if s in fmap:
        return s
    for k, v in fmap.items():
        if s == v:
            return k

    def _norm(x: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", (x or "").lower())

    ns = _norm(s)
    for k, v in fmap.items():
        if ns == _norm(k) or ns == _norm(v):
            return k
    _s = s.replace(" ", "_")
    return re.sub(r"[^A-Za-z0-9_]+", "", _s).strip("_").lower()


def mkdir_p(ftp: FTP, remote_dir: str):
    ftp.cwd("/")
    for part in remote_dir.strip("/").split("/"):
        if not part:
            continue
        try:
            ftp.cwd(part)
        except Exception:
            ftp.mkd(part)
            ftp.cwd(part)


def ensure_mirror_schema(conn: sqlite3.Connection):
    """Keep the local mirror schema compatible with the website table (best-effort)."""
    cur = conn.cursor()

    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            id INTEGER PRIMARY KEY,
            Folder TEXT, File_Name TEXT, Path TEXT, Thumb_Path TEXT,
            DateTime TEXT, Camera TEXT, Lens_model TEXT,
            Width INTEGER, Height INTEGER, Exposure TEXT, Aperture TEXT, ISO INTEGER, Focal_length INTEGER,
            Keywords TEXT, Caption TEXT, alt_text TEXT, Location TEXT, QR REAL, QC_Status TEXT, Original_File_Name TEXT,
            nima_score REAL, blur_score REAL, brightness_score REAL, contrast_score REAL,
            brisque_score REAL, clip_aesthetic_score REAL
        )
    """
    )
    conn.commit()

    cur.execute(f"PRAGMA table_info({TABLE_NAME})")
    have = {r[1] for r in cur.fetchall()}

    wanted = [
        ("Folder", "TEXT"),
        ("File_Name", "TEXT"),
        ("Path", "TEXT"),
        ("Thumb_Path", "TEXT"),
        ("DateTime", "TEXT"),
        ("Camera", "TEXT"),
        ("Lens_model", "TEXT"),
        ("Width", "INTEGER"),
        ("Height", "INTEGER"),
        ("Exposure", "TEXT"),
        ("Aperture", "TEXT"),
        ("ISO", "INTEGER"),
        ("Focal_length", "INTEGER"),
        ("Keywords", "TEXT"),
        ("Caption", "TEXT"),
        ("alt_text", "TEXT"),
        ("Location", "TEXT"),
        ("QR", "REAL"),
        ("QC_Status", "TEXT"),
        ("Original_File_Name", "TEXT"),
        ("nima_score", "REAL"),
        ("blur_score", "REAL"),
        ("brightness_score", "REAL"),
        ("contrast_score", "REAL"),
        ("brisque_score", "REAL"),
        ("clip_aesthetic_score", "REAL"),
    ]
    for col, typ in wanted:
        if col not in have:
            cur.execute(f"ALTER TABLE {TABLE_NAME} ADD COLUMN {col} {typ}")
    conn.commit()


def none_if_empty(v):
    if v is None:
        return None
    if isinstance(v, str) and v.strip() == "":
        return None
    return v


def row_get(row, key, default=None):
    """Safe getter for sqlite3.Row or dict."""
    try:
        if isinstance(row, sqlite3.Row):
            return row[key] if key in row.keys() else default
        if isinstance(row, dict):
            return row.get(key, default)
        return getattr(row, key, default)
    except Exception:
        return default


def _derive_local_src(path_val: str, local_base: str, public_base: str, year: str, folder_key: str, fname: str) -> str:
    """
    Resolve a local filesystem source path for upload.
    Handles both local paths and already-published URL paths.
    """
    p = (path_val or "").strip()
    if p and os.path.exists(p):
        return p

    candidates = []
    if local_base:
        # If Path is a URL under PUBLIC_URL_BASE, map it to LOCAL_BASE.
        if p.lower().startswith(("http://", "https://")) and public_base:
            pb = public_base.rstrip("/")
            if p.startswith(pb + "/"):
                rel = p[len(pb) + 1 :].replace("/", os.sep)
                candidates.append(os.path.join(local_base, rel))

        # Deterministic local layout used by review_editor.
        if year:
            candidates.append(os.path.join(local_base, year, folder_key, fname))
        candidates.append(os.path.join(local_base, folder_key, fname))

    for c in candidates:
        if c and os.path.exists(c):
            return c
    return p


def _derive_year(dt: str, fname: str) -> str:
    d = (dt or "").strip()
    if len(d) >= 4 and d[:4].isdigit():
        return d[:4]
    m = re.search(r"_(20\d{2})_", fname or "")
    if m:
        return m.group(1)
    return datetime.now().strftime("%Y")


# ---------- core ----------
def upload():
    if _MYSQL_IMPORT_ERROR is not None:
        raise RuntimeError(
            "mysql-connector-python is required for upload stage. "
            "Install with: python -m pip install mysql-connector-python "
            f"(details: {type(_MYSQL_IMPORT_ERROR).__name__}: {_MYSQL_IMPORT_ERROR})"
        )

    fmap = load_folder_map()

    # open local queue
    qconn = sqlite3.connect(DB_PATH)
    qconn.row_factory = sqlite3.Row
    qc = qconn.cursor()
    qc.execute(f"SELECT * FROM {REVIEW_QUEUE} WHERE Review_Status='Approved'")
    rows = qc.fetchall()
    run_dirs_to_cleanup = _collect_ollama_run_dirs(qconn, rows)

    if not rows:
        print("0 images were processed and uploaded successfully.")
        print("Click OK to close.")
        qconn.close()
        return 0

    # MySQL
    conn_kwargs = {
        "host": MYSQL["host"],
        "user": MYSQL["user"],
        "password": MYSQL["password"],
        "database": MYSQL["database"],
        "charset": MYSQL.get("charset", "utf8mb4"),
        "use_unicode": bool(MYSQL.get("use_unicode", True)),
        # Important for packaged EXE runs: avoid C-extension auth plugin DLL loading issues.
        "use_pure": bool(MYSQL.get("use_pure", True)),
        "autocommit": False,
    }
    if MYSQL.get("port"):
        conn_kwargs["port"] = int(MYSQL["port"])
    if MYSQL.get("auth_plugin"):
        conn_kwargs["auth_plugin"] = MYSQL["auth_plugin"]

    try:
        mconn = mysql.connector.connect(**conn_kwargs)
    except Exception as ex:
        msg = str(ex)
        if "2059" in msg or ("Authentication plugin" in msg and "cannot be loaded" in msg):
            retry = dict(conn_kwargs)
            retry["use_pure"] = True
            retry.setdefault("auth_plugin", "mysql_native_password")
            LOGGER.warning("Retrying MySQL connect in pure mode after auth-plugin load failure.")
            mconn = mysql.connector.connect(**retry)
        else:
            raise
    mcur = mconn.cursor()

    # local mirror db
    lconn = sqlite3.connect(LOCAL_MIRROR_DB)
    ensure_mirror_schema(lconn)
    lcur = lconn.cursor()

    # FTP
    ftp = FTP()
    ftp.connect(FTP_CONFIG["host"], FTP_CONFIG["port"], timeout=60)
    ftp.login(FTP_CONFIG["user"], FTP_CONFIG["passwd"])
    ftp.encoding = "utf-8"

    success = 0
    fail = 0

    for r in tqdm(rows, desc="Uploading", unit="img"):
        try:
            folder = str(r["Folder"] or "")
            display_folder = folder
            folder_key = canonical_folder_slug(folder, fmap)

            fname = str(r["File_Name"] or "")
            if not fname:
                raise ValueError("Missing File_Name in review_queue row")

            warn_filename_length(fname)

            local_src = str(row_get(r, "Path", "") or "")
            if not local_src:
                raise ValueError("Missing Path in review_queue row")

            dt = str(row_get(r, "DateTime", "") or "")
            year = _derive_year(dt, fname)
            local_src = _derive_local_src(local_src, LOCAL_BASE, PUBLIC_URL_BASE, year, folder_key, fname)

            if not os.path.exists(local_src):
                raise FileNotFoundError(local_src)

            # Compute remote target
            remote_dir = REMOTE_BASE.strip("/")
            if remote_dir:
                remote_dir = f"{remote_dir}/{year}/{folder_key}"
            else:
                remote_dir = f"{year}/{folder_key}"

            remote_thumb_dir = REMOTE_BASE.strip("/")
            if remote_thumb_dir:
                remote_thumb_dir = f"{remote_thumb_dir}/{year}/thumbs/{folder_key}"
            else:
                remote_thumb_dir = f"{year}/thumbs/{folder_key}"

            mkdir_p(ftp, remote_dir)
            ftp.cwd("/")
            ftp.cwd(remote_dir)

            # Upload main image
            with open(local_src, "rb") as f:
                ftp.storbinary(f"STOR {fname}", f)

            # Build public URL path
            public_path = "/".join([p.strip("/") for p in [PUBLIC_URL_BASE, year, folder_key, fname] if p])
            public_path = public_path.replace(" ", "%20")

            # Upload thumb from local mirror if present
            thumb_local = os.path.join(LOCAL_BASE, year, "thumbs", folder_key, fname) if LOCAL_BASE else ""
            thumb_path = None
            if thumb_local and os.path.exists(thumb_local):
                mkdir_p(ftp, remote_thumb_dir)
                ftp.cwd("/")
                ftp.cwd(remote_thumb_dir)
                with open(thumb_local, "rb") as tf:
                    ftp.storbinary(f"STOR {fname}", tf)
                thumb_path = "/".join([p.strip("/") for p in [PUBLIC_URL_BASE, year, "thumbs", folder_key, fname] if p])
                thumb_path = thumb_path.replace(" ", "%20")

            # Insert/update by File_Name (UNIQUE). Never reuse review_queue id for MySQL PK.
            sql = f"""
                INSERT INTO {TABLE_NAME} (
                    Folder, File_Name, Path, Thumb_Path,
                    DateTime, Camera, Lens_model,
                    Width, Height, Exposure, Aperture, ISO, Focal_length,
                    Keywords, Caption, alt_text, Location, QR, QC_Status, Original_File_Name,
                    nima_score, blur_score, brightness_score, contrast_score,
                    brisque_score, clip_aesthetic_score
                )
                VALUES (
                    %s,%s,%s,%s,
                    %s,%s,%s,
                    %s,%s,%s,%s,%s,%s,
                    %s,%s,%s,%s,%s,%s,%s,
                    %s,%s,%s,%s,
                    %s,%s
                )
                ON DUPLICATE KEY UPDATE
                    Folder=VALUES(Folder),
                    File_Name=VALUES(File_Name),
                    Path=VALUES(Path),
                    Thumb_Path=VALUES(Thumb_Path),
                    DateTime=VALUES(DateTime),
                    Camera=VALUES(Camera),
                    Lens_model=VALUES(Lens_model),
                    Width=VALUES(Width),
                    Height=VALUES(Height),
                    Exposure=VALUES(Exposure),
                    Aperture=VALUES(Aperture),
                    ISO=VALUES(ISO),
                    Focal_length=VALUES(Focal_length),
                    Keywords=VALUES(Keywords),
                    Caption=VALUES(Caption),
                    alt_text=VALUES(alt_text),
                    Location=VALUES(Location),
                    QR=VALUES(QR),
                    QC_Status=VALUES(QC_Status),
                    Original_File_Name=VALUES(Original_File_Name),
                    nima_score=VALUES(nima_score),
                    blur_score=VALUES(blur_score),
                    brightness_score=VALUES(brightness_score),
                    contrast_score=VALUES(contrast_score),
                    brisque_score=VALUES(brisque_score),
                    clip_aesthetic_score=VALUES(clip_aesthetic_score)
            """

            vals_no_id = (
                display_folder,
                fname,
                public_path,
                thumb_path,
                none_if_empty(row_get(r, "DateTime")),
                none_if_empty(row_get(r, "Camera")),
                none_if_empty(row_get(r, "Lens_model")),
                row_get(r, "Width"),
                row_get(r, "Height"),
                none_if_empty(row_get(r, "Exposure")),
                none_if_empty(row_get(r, "Aperture")),
                row_get(r, "ISO"),
                row_get(r, "Focal_length"),
                none_if_empty(row_get(r, "Keywords")),
                none_if_empty(row_get(r, "Caption")),
                none_if_empty(row_get(r, "alt_text")),
                none_if_empty(row_get(r, "Location")),
                row_get(r, "QR"),
                none_if_empty(row_get(r, "QC_Status")),
                none_if_empty(row_get(r, "Original_File_Name")),
                row_get(r, "nima_score"),
                row_get(r, "blur_score"),
                row_get(r, "brightness_score"),
                row_get(r, "contrast_score"),
                row_get(r, "brisque_score"),
                row_get(r, "clip_aesthetic_score"),
            )

            mcur.execute(sql, vals_no_id)

            # Resolve canonical MySQL id after insert/update (by unique filename)
            mcur.execute(f"SELECT id FROM {TABLE_NAME} WHERE File_Name=%s", (fname,))
            _row = mcur.fetchone()
            if not _row:
                raise RuntimeError(f"Could not resolve MySQL id after upsert for {fname}")
            mysql_row_id = int(_row[0])
            vals_with_id = (mysql_row_id, *vals_no_id)

            # Keep local mirror in sync
            lcur.execute(
                f"""
                INSERT OR REPLACE INTO {TABLE_NAME} (
                    id, Folder, File_Name, Path, Thumb_Path,
                    DateTime, Camera, Lens_model,
                    Width, Height, Exposure, Aperture, ISO, Focal_length,
                    Keywords, Caption, alt_text, Location, QR, QC_Status, Original_File_Name,
                    nima_score, blur_score, brightness_score, contrast_score,
                    brisque_score, clip_aesthetic_score
                )
                VALUES (
                    ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
                )
            """,
                vals_with_id,
            )
            lconn.commit()

            # Delete from queue once uploaded
            qc.execute(f"DELETE FROM {REVIEW_QUEUE} WHERE id=?", (r["id"],))
            qconn.commit()

            success += 1
            LOGGER.info("Uploaded: %s", fname)
            print(f"Uploaded: {fname}", flush=True)

        except Exception as e:
            fail += 1
            fname = str(row_get(r, "File_Name") or "<unknown>")
            try:
                LOGGER.exception("Upload failed for %s", fname)
            except Exception:
                pass
            print(f"[UPLOAD ERROR] {fname}: {e}", file=sys.stderr)

    # close everything
    try:
        mconn.commit()
    except Exception:
        pass
    mcur.close()
    mconn.close()
    lconn.close()

    if fail == 0:
        _cleanup_ollama_tmp(qconn, run_dirs_to_cleanup)

    qconn.close()
    try:
        ftp.quit()
    except Exception:
        pass

    # Console/UI output
    if fail == 0:
        print(f"{success} images were processed and uploaded successfully.")
        print("Click OK to close.")
    else:
        print(f"Uploaded {success} images. {fail} failed.")
        print("See logs/uploader.log for details.")
        print("Click OK to close.")

    return 0 if fail == 0 else 1


# ---------- Ollama temp cleanup ----------
def _has_column(conn: sqlite3.Connection, table: str, col: str) -> bool:
    try:
        cur = conn.cursor()
        cur.execute(f"PRAGMA table_info({table})")
        return any(r[1] == col for r in cur.fetchall())
    except Exception:
        return False


def _collect_ollama_run_dirs(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> list[str]:
    """Collect unique run directories referenced by ollama_path, without deleting anything."""
    run_dirs: set[str] = set()

    # From the rows we are about to process (Approved)
    try:
        for r in rows:
            try:
                p = str(row_get(r, "ollama_path") or "").strip()
            except Exception:
                p = ""
            if p:
                try:
                    run_dirs.add(str(Path(p).resolve().parent))
                except Exception:
                    run_dirs.add(str(Path(p).parent))
    except Exception:
        pass

    # From the remaining DB, if the column exists
    if _has_column(conn, REVIEW_QUEUE, "ollama_path"):
        try:
            cur = conn.cursor()
            cur.execute(f"SELECT DISTINCT ollama_path FROM {REVIEW_QUEUE} WHERE COALESCE(ollama_path,'')<>''")
            for (p,) in cur.fetchall():
                if not p:
                    continue
                try:
                    run_dirs.add(str(Path(p).resolve().parent))
                except Exception:
                    run_dirs.add(str(Path(p).parent))
        except Exception:
            pass

    # Keep only paths that look like: ...\\data\\ollama_tmp\\run_YYYYMMDD_HHMMSS
    safe_root = Path(DATA_DIR) / "ollama_tmp"
    safe_root_str = str(safe_root.resolve()).lower() if DATA_DIR else ""
    out: list[str] = []
    for d in sorted(run_dirs):
        try:
            dp = Path(d).resolve()
            if not dp.name.startswith("run_"):
                continue
            if safe_root_str and safe_root_str not in str(dp).lower():
                continue
            out.append(str(dp))
        except Exception:
            continue
    return out


def _cleanup_ollama_tmp(conn: sqlite3.Connection, run_dirs: list[str]) -> None:
    """Clear ollama_path values and delete run folders. Best effort."""
    if not run_dirs and not _has_column(conn, REVIEW_QUEUE, "ollama_path"):
        return

    # Clear column first
    if _has_column(conn, REVIEW_QUEUE, "ollama_path"):
        try:
            cur = conn.cursor()
            cur.execute(f"UPDATE {REVIEW_QUEUE} SET ollama_path=NULL WHERE COALESCE(ollama_path,'')<>''")
            conn.commit()
        except Exception as ex:
            print(f"[WARN] Could not clear ollama_path: {type(ex).__name__}: {ex}", file=sys.stderr)

    # Delete run dirs
    import shutil

    for d in run_dirs:
        try:
            dp = Path(d)
            if dp.exists() and dp.is_dir() and dp.name.startswith("run_"):
                shutil.rmtree(dp, ignore_errors=True)
        except Exception:
            pass

    # Best effort remove leftover empty run dirs
    try:
        root = Path(DATA_DIR) / "ollama_tmp"
        if root.exists() and root.is_dir():
            for child in root.iterdir():
                if child.is_dir() and child.name.startswith("run_"):
                    try:
                        shutil.rmtree(child, ignore_errors=True)
                    except Exception:
                        pass
    except Exception:
        pass

    print("[OK] Cleaned ollama_tmp and cleared ollama_path.", flush=True)


if __name__ == "__main__":
    raise SystemExit(upload())
