from __future__ import annotations

import builtins
import logging
import os
from pathlib import Path


_INSTALLED = False
_ORIGINAL_OPEN = builtins.open
_ORIGINAL_PATH_OPEN = Path.open
_ORIGINAL_WRITE_TEXT = Path.write_text
_ORIGINAL_WRITE_BYTES = Path.write_bytes
_ORIGINAL_FILE_HANDLER = logging.FileHandler


PROJECT_ROOT = Path(__file__).resolve().parent.parent

if PROJECT_ROOT.name == "_runtime_scripts" and PROJECT_ROOT.parent.name == "data":
    PROJECT_ROOT = PROJECT_ROOT.parent.parent

LOGS_DIR = PROJECT_ROOT / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

os.environ["AMIR_LOG_DIR"] = str(LOGS_DIR)


_REDIRECT_SUFFIXES = {
    ".log",
    ".txt",
}


_BLOCKED_PARTS = {
    ".git",
    ".venv",
    ".venv313",
    "backup",
    "build",
    "dist",
    "docs",
    "fonts",
    "vendor",
    "__pycache__",
}


def logs_dir() -> Path:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    return LOGS_DIR


def log_path(filename: str | Path) -> Path:
    name = Path(filename).name
    return logs_dir() / name


def _is_write_mode(mode: str) -> bool:
    mode = str(mode or "")

    return any(flag in mode for flag in ["w", "a", "x"])


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve(strict=False).relative_to(parent.resolve(strict=False))
        return True
    except Exception:
        return False


def _should_redirect(path_value, mode: str = "w") -> bool:
    if isinstance(path_value, int):
        return False

    if not _is_write_mode(mode):
        return False

    try:
        path = Path(path_value)
    except TypeError:
        return False

    if path.suffix.lower() not in _REDIRECT_SUFFIXES:
        return False

    if not path.is_absolute():
        full_path = PROJECT_ROOT / path
    else:
        full_path = path

    if _inside(full_path, LOGS_DIR):
        return False

    try:
        parts = set(full_path.resolve(strict=False).relative_to(PROJECT_ROOT).parts)
    except Exception:
        parts = set(full_path.parts)

    if parts & _BLOCKED_PARTS:
        return False

    return True


def _redirect_path(path_value, mode: str = "w"):
    if not _should_redirect(path_value, mode):
        return path_value

    path = Path(path_value)
    target = log_path(path.name)

    return str(target) if isinstance(path_value, str) else target


def _patched_open(file, mode="r", *args, **kwargs):
    return _ORIGINAL_OPEN(_redirect_path(file, mode), mode, *args, **kwargs)


def _patched_path_open(self, mode="r", *args, **kwargs):
    target = _redirect_path(self, mode)

    if target is self:
        return _ORIGINAL_PATH_OPEN(self, mode, *args, **kwargs)

    return _ORIGINAL_PATH_OPEN(Path(target), mode, *args, **kwargs)


def _patched_write_text(self, data, *args, **kwargs):
    target = _redirect_path(self, "w")

    if target is self:
        return _ORIGINAL_WRITE_TEXT(self, data, *args, **kwargs)

    return _ORIGINAL_WRITE_TEXT(Path(target), data, *args, **kwargs)


def _patched_write_bytes(self, data, *args, **kwargs):
    target = _redirect_path(self, "wb")

    if target is self:
        return _ORIGINAL_WRITE_BYTES(self, data, *args, **kwargs)

    return _ORIGINAL_WRITE_BYTES(Path(target), data, *args, **kwargs)


class _PatchedFileHandler(_ORIGINAL_FILE_HANDLER):
    def __init__(self, filename, mode="a", encoding=None, delay=False, errors=None):
        redirected = _redirect_path(filename, mode)

        super().__init__(
            redirected,
            mode=mode,
            encoding=encoding,
            delay=delay,
            errors=errors,
        )


def install() -> Path:
    global _INSTALLED

    if _INSTALLED:
        return LOGS_DIR

    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    builtins.open = _patched_open
    Path.open = _patched_path_open
    Path.write_text = _patched_write_text
    Path.write_bytes = _patched_write_bytes
    logging.FileHandler = _PatchedFileHandler

    _INSTALLED = True

    return LOGS_DIR
