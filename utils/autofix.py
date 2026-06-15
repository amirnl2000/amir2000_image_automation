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

import json
import os
import re
from typing import Dict, Iterable, List, Set, Tuple

_WORD = re.compile(r"[A-Za-z][A-Za-z']*")
_MAX_SPELL_TOKEN_LEN = 24
_MAX_SPELL_CORRECTIONS_PER_CALL = 64
_SPELL_SUGGESTIONS_ENABLED = os.getenv("AMIR_SPELL_SUGGEST", "0").strip().lower() in (
    "1", "true", "yes", "on"
)

# Optional dependency. If missing, we fall back to mapping-only.
try:
    from spellchecker import SpellChecker  # type: ignore[import-not-found]
except Exception:
    SpellChecker = None

# cache
_SPELL = None
_SPELL_DIR = None


def _norm_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("_", " ")).strip()


def load_autofix_dict(dict_path: str) -> Dict[str, str]:
    """
    Loads a mapping like:
      { "teh": "the", "architechture": "architecture" }
    Keys are matched case-insensitively.
    """
    try:
        with open(dict_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            out = {}
            for k, v in data.items():
                kk = str(k).strip().lower()
                vv = _norm_spaces(str(v))
                if kk and vv:
                    out[kk] = vv
            return out
    except Exception:
        pass
    return {}


def autocorrect_text(text: str, mapping: Dict[str, str]) -> Tuple[str, bool]:
    """
    Applies word-level replacements. Does not guess, only replaces what is in mapping.
    Returns (fixed_text, changed_bool).
    """
    src = _norm_spaces(text)
    if not src or not mapping:
        return src, False

    changed = False

    def repl(match: re.Match) -> str:
        nonlocal changed
        w = match.group(0)
        key = w.lower()
        if key in mapping:
            changed = True
            return mapping[key]
        return w

    fixed = _WORD.sub(repl, src)
    fixed = _norm_spaces(fixed)
    return fixed, changed


def _levenshtein(a: str, b: str) -> int:
    # small, fast DP for short words
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    la, lb = len(a), len(b)
    prev = list(range(lb + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            ins = cur[j - 1] + 1
            dele = prev[j] + 1
            sub = prev[j - 1] + (0 if ca == cb else 1)
            cur.append(min(ins, dele, sub))
        prev = cur
    return prev[-1]


def _read_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _tokenize_words(items: Iterable[str]) -> Set[str]:
    out: Set[str] = set()
    for s in items:
        if not s:
            continue
        s2 = str(s).replace("_", " ")
        for w in _WORD.findall(s2):
            out.add(w.lower())
    return out


def _load_spell_exceptions(data_dir: str) -> Set[str]:
    """
    Builds the ignore list from:
      - data/spellcheck_exceptions.json (manual)
      - data/location_list.json (auto)
      - data/folder_map.json (auto)
    """
    manual_path = os.path.join(data_dir, "spellcheck_exceptions.json")
    location_path = os.path.join(data_dir, "location_list.json")
    folder_map_path = os.path.join(data_dir, "folder_map.json")

    words: Set[str] = set()

    manual = _read_json(manual_path)
    if isinstance(manual, list):
        words |= _tokenize_words([str(x) for x in manual])

    locs = _read_json(location_path)
    if isinstance(locs, list):
        words |= _tokenize_words([str(x) for x in locs])

    fm = _read_json(folder_map_path)
    if isinstance(fm, dict):
        # include keys + values
        words |= _tokenize_words([str(k) for k in fm.keys()])
        words |= _tokenize_words([str(v) for v in fm.values()])

    # add a small “always safe” core set (prevents silly fixes)
    core = [
        "canon", "eos", "rf", "ef", "macro", "photography", "photo", "photos",
        "amd", "iso", "exif", "jpeg", "jpg", "png", "webp"
    ]
    words |= set(core)

    return words


def _get_spellchecker(data_dir: str):
    global _SPELL, _SPELL_DIR
    if SpellChecker is None:
        return None
    if _SPELL is not None and _SPELL_DIR == data_dir:
        return _SPELL

    sp = SpellChecker(language="en", distance=2)

    # Load extra known words so they are NOT marked misspelled
    extras = _load_spell_exceptions(data_dir)
    if extras:
        sp.word_frequency.load_words(list(extras))

    _SPELL = sp
    _SPELL_DIR = data_dir
    return sp


def spellcheck_status(data_dir: str) -> Tuple[bool, str]:
    """Return spellcheck availability and short reason."""
    if os.getenv("AMIR_SPELLCHECK", "1").strip() in ("0", "false", "False"):
        return False, "disabled by AMIR_SPELLCHECK"
    if SpellChecker is None:
        return False, "pyspellchecker not installed"
    sp = _get_spellchecker(data_dir)
    if sp is None:
        return False, "spellchecker init failed"
    try:
        probe = sp.correction("teh")
        if not probe:
            return False, "dictionary not loaded"
    except Exception:
        return False, "spellchecker runtime error"
    return True, "ready"


def _apply_case(original: str, corrected: str) -> str:
    if not corrected:
        return original
    if original.isupper():
        return original
    if original[:1].isupper() and original[1:].islower():
        return corrected[:1].upper() + corrected[1:]
    return corrected


def _skip_spell_token(word: str) -> bool:
    w = str(word or "")
    if not w:
        return True
    if len(w) < 3:
        return True
    if w.isupper():
        return True
    wl = w.lower()
    if len(wl) > _MAX_SPELL_TOKEN_LEN:
        return True
    if any(ch.isdigit() for ch in wl):
        return True
    if "_" in wl or "-" in wl:
        return True
    if wl.count("'") > 1:
        return True
    # Skip very repetitive tokens that trigger expensive candidate generation.
    if len(wl) >= 7 and len(set(wl.replace("'", ""))) <= 2:
        return True
    return False


def spellcheck_text(text: str, data_dir: str) -> Tuple[str, bool]:
    """
    Dictionary-based spellcheck with a strict safety filter.
    Only changes a word when:
      - word length >= 3
      - word is unknown to the spellchecker
      - correction exists
      - edit distance is small (prevents wild changes)
    """
    if os.getenv("AMIR_SPELLCHECK", "1").strip() in ("0", "false", "False"):
        return _norm_spaces(text), False

    src = _norm_spaces(text)
    if not src:
        return src, False

    sp = _get_spellchecker(data_dir)
    if sp is None:
        return src, False

    changed = False
    corrections_used = 0

    def repl(match: re.Match) -> str:
        nonlocal changed, corrections_used
        w = match.group(0)

        if _skip_spell_token(w):
            return w

        wl = w.lower()

        # skip if spellchecker already knows it
        if wl in sp:
            return w

        if corrections_used >= _MAX_SPELL_CORRECTIONS_PER_CALL:
            return w

        # attempt correction
        try:
            cand = sp.correction(wl)
        except Exception:
            return w
        corrections_used += 1
        if not cand or cand == wl:
            return w

        # safety: do not allow big jumps
        dist = _levenshtein(wl, cand.lower())
        max_dist = 1 if len(wl) <= 4 else (2 if len(wl) <= 8 else 3)
        if dist > max_dist:
            return w

        changed = True
        return _apply_case(w, cand)

    fixed = _WORD.sub(repl, src)
    fixed = _norm_spaces(fixed)
    return fixed, changed


def find_misspellings(text: str, data_dir: str) -> List[dict]:
    """
    Returns a list of:
      {"start": int, "end": int, "word": str, "suggestion": str}
    Positions are character offsets into the ORIGINAL input string.
    """
    if os.getenv("AMIR_SPELLCHECK", "1").strip() in ("0", "false", "False"):
        return []

    src = (text or "")
    if not src:
        return []

    sp = _get_spellchecker(data_dir)
    if sp is None:
        return []

    out: List[dict] = []
    corrections_used = 0

    for m in _WORD.finditer(src):
        w = m.group(0)

        if _skip_spell_token(w):
            continue

        wl = w.lower()

        # known word, skip
        if wl in sp:
            continue

        cand = ""
        if _SPELL_SUGGESTIONS_ENABLED:
            if corrections_used >= _MAX_SPELL_CORRECTIONS_PER_CALL:
                break
            try:
                cand = sp.correction(wl) or ""
            except Exception:
                cand = ""
            corrections_used += 1
            if cand and cand != wl:
                dist = _levenshtein(wl, cand.lower())
                max_dist = 1 if len(wl) <= 4 else (2 if len(wl) <= 8 else 3)
                if dist > max_dist:
                    cand = ""

        out.append({
            "start": m.start(),
            "end": m.end(),
            "word": w,
            "suggestion": cand
        })

    return out


def add_spell_exception(word: str, data_dir: str) -> bool:
    """
    Adds a word or phrase to data/spellcheck_exceptions.json so it will be treated as known.
    Smarter behavior:
      - also adds lowercase variant
      - adds simple singular/plural variants (when obvious)
      - if a phrase is provided, applies the above per-word as well
    Returns True if anything was added.
    """
    global _SPELL, _SPELL_DIR

    src = (word or "").strip()
    if not src:
        return False

    def _word_variants(w: str) -> set[str]:
        w = (w or "").strip()
        if not w:
            return set()
        out = {w, w.lower()}

        lw = w.lower()

        # plural forms (simple, "obvious" heuristics)
        if len(lw) >= 2:
            if lw.endswith("y") and len(lw) >= 3 and lw[-2] not in "aeiou":
                out.add(lw[:-1] + "ies")
            if lw.endswith(("s", "x", "z", "ch", "sh")):
                out.add(lw + "es")
            else:
                out.add(lw + "s")

        # singular forms (simple reversals)
        if lw.endswith("ies") and len(lw) > 3:
            out.add(lw[:-3] + "y")
        if lw.endswith("es") and len(lw) > 3:
            if lw.endswith(("ses", "xes", "zes", "ches", "shes")):
                out.add(lw[:-2])  # buses->bus, boxes->box, etc.
        if lw.endswith("s") and not lw.endswith("ss") and len(lw) > 3:
            out.add(lw[:-1])  # cats->cat

        # keep only reasonably word-like entries
        cleaned = set()
        for v in out:
            v2 = (v or "").strip()
            if not v2:
                continue
            # allow letters, apostrophes and underscores/spaces (phrases stored as-is)
            cleaned.add(v2)
        return cleaned

    # Collect variants for the whole input and for each token inside it
    variants: set[str] = set()
    variants |= _word_variants(src)

    # If it's a phrase, add variants per word token too
    src_for_tokens = src.replace("_", " ")
    for tok in _WORD.findall(src_for_tokens):
        variants |= _word_variants(tok)

    path = os.path.join(data_dir, "spellcheck_exceptions.json")
    try:
        os.makedirs(data_dir, exist_ok=True)

        data = []
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        if not isinstance(data, list):
            data = []

        lower_set = {str(x).strip().lower() for x in data if isinstance(x, str) and x.strip()}

        added_any = False
        # Preserve casing for the first entry if possible, then add the rest
        for v in sorted(variants, key=lambda s: (s.lower() != src.lower(), s.lower())):
            if v.strip().lower() in lower_set:
                continue
            data.append(v)
            lower_set.add(v.strip().lower())
            added_any = True

        if not added_any:
            return False

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        # Reset cache if it was built for this data_dir
        if _SPELL_DIR == data_dir:
            _SPELL = None
            _SPELL_DIR = None

        return True
    except Exception:
        return False


def add_spell_exception_smart(word: str, data_dir: str) -> bool:
    """
    Backward-compatible alias.
    main_set.py imports this name, so we provide it even if older code calls it.
    """
    return add_spell_exception(word, data_dir)


def autofix_subject(subject: str, dict_path: str) -> str:
    """
    Subject cleanup:
      - normalize spaces/underscores
      - apply manual mapping replacements (autofix_dict.json)
      - apply English spellcheck (pyspellchecker) with exceptions
      - keep user wording (including trailing small words like "in/of/the")
    """
    s = _norm_spaces(subject)
    if not s:
        return ""

    # manual mapping first (high precision)
    mapping = load_autofix_dict(dict_path)
    s2, _ = autocorrect_text(s, mapping)

    # spellcheck next (helps with general spelling)
    data_dir = os.path.dirname(dict_path)
    s3, _ = spellcheck_text(s2, data_dir)

    return _norm_spaces(s3)
