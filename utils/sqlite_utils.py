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

import sqlite3
from pathlib import Path


def connect_sqlite(
    db_path: str | Path,
    *,
    timeout: float = 30.0,
    row_factory=None,
    wal: bool = True,
    busy_timeout_ms: int = 30000,
) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=float(timeout))
    if row_factory is not None:
        conn.row_factory = row_factory
    try:
        conn.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
    except Exception:
        pass
    try:
        conn.execute("PRAGMA foreign_keys=ON")
    except Exception:
        pass
    if wal:
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except Exception:
            pass
        try:
            conn.execute("PRAGMA synchronous=NORMAL")
        except Exception:
            pass
    return conn
