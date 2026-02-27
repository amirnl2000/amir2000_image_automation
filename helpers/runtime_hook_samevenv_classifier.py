import os
import sys
from pathlib import Path


def _add_sys_path(path: Path) -> bool:
    try:
        p = str(path.resolve())
    except Exception:
        p = str(path)
    if not path.is_dir():
        return False
    if p not in sys.path:
        # Append (do not prepend) to avoid shadowing stdlib modules
        # such as `http` with third-party packages from site-packages.
        sys.path.append(p)
    return True


def _add_dll_dir(path: Path) -> None:
    if not hasattr(os, "add_dll_directory"):
        return
    try:
        if path.is_dir():
            os.add_dll_directory(str(path))
    except Exception:
        pass


def _enable_same_venv_classifier_stack() -> None:
    if not getattr(sys, "frozen", False):
        return

    exe_dir = Path(sys.executable).resolve().parent
    env_override = os.environ.get("AMIR_AUTOMATION_SITEPACKAGES") or os.environ.get(
        "AMIR_AUTOMATION_VENV_SITEPACKAGES"
    )

    candidates = []
    if env_override:
        candidates.append(Path(env_override))
    for base in (exe_dir, exe_dir.parent, Path.cwd()):
        candidates.append(base / ".venv313" / "Lib" / "site-packages")
        candidates.append(base / ".venv" / "Lib" / "site-packages")

    chosen = None
    seen = set()
    for cand in candidates:
        key = str(cand).lower()
        if key in seen:
            continue
        seen.add(key)
        if _add_sys_path(cand):
            chosen = cand
            break

    if chosen is None:
        return

    # Make compiled extensions and torch DLLs discoverable on Windows.
    _add_dll_dir(chosen)
    _add_dll_dir(chosen / "torch" / "lib")
    _add_dll_dir(chosen / "torchvision")
    _add_dll_dir(chosen / "tokenizers.libs")
    _add_dll_dir(chosen / "numpy.libs")
    _add_dll_dir(chosen / "Pillow.libs")


_enable_same_venv_classifier_stack()
