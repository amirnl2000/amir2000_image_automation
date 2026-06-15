
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
import random
import re
from typing import Dict, List, Optional

# Load caption templates from ../data/caption_templates.json (relative to this file)
def _templates_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    cand1 = os.path.normpath(os.path.join(here, "..", "data", "caption_templates_v3_merged.json"))
    cand2 = os.path.normpath(os.path.join(here, "..", "data", "caption_templates.json"))
    return cand1 if os.path.exists(cand1) else cand2

def _load_templates() -> Dict:
    path = _templates_path()
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

# --- text helpers ------------------------------------------------------------

_SMALL = {"a","an","and","or","the","of","in","on","at","to","for","by","with","from"}
_ROMAN = {"i","ii","iii","iv","v","vi","vii","viii","ix","x"}

def _smart_title(s: str) -> str:
    if not s: return ""
    words = re.findall(r"[A-Za-z0-9]+", s)
    out = []
    for i,w in enumerate(words):
        low = w.lower()
        if i != 0 and low in _SMALL:
            out.append(low)
        elif low in _ROMAN:
            out.append(low.upper())
        else:
            out.append(w[:1].upper()+w[1:].lower())
    return " ".join(out)

def _clean_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()

def _safe_replace(template: str, **vals) -> str:
    """
    Replace placeholders but drop the surrounding phrase when a value is empty.
    e.g. "Shot in {location}" -> "Shot in Amsterdam" OR "Shot" if location is ""
    """
    txt = template

    # remove ", at {location}"-style chunks if value empty
    for key, val in vals.items():
        if not val:
            # Remove patterns like " in {key}", " at {key}", ", {key}", " ({key})"
            txt = re.sub(rf"\s*(?:,|\(|\[)?\s*(?:in|at|from|near|around|shot in|made in)?\s*{{\s*{re.escape(key)}\s*}}\s*(?:\)|\])?", "", txt, flags=re.IGNORECASE)
            txt = txt.replace("{"+key+"}", "")

    # Now do a simple format
    for key, val in vals.items():
        txt = txt.replace("{"+key+"}", val or "")

    # Clean doubles
    txt = re.sub(r"\s+,", ",", txt)
    txt = re.sub(r"\s+\.", ".", txt)
    txt = re.sub(r"\s{2,}", " ", txt).strip(" ,")
    return txt.strip()

def _pick(seq: List[str], rnd: random.Random) -> str:
    return seq[rnd.randrange(len(seq))]

# --- public API --------------------------------------------------------------

def generate_caption(category: str,
                     subject: Optional[str],
                     location: Optional[str],
                     camera: Optional[str] = None,
                     seed: Optional[str] = None,
                     length: Optional[str] = None) -> str:
    """
    Returns a single-sentence, human-sounding caption. Keeps it natural first, SEO second.
    - category: folder/category key mapping to templates
    - subject/location/camera: optional; omissions won't produce awkward fragments
    - seed: for stable randomness per image
    - length: optional hint ('short'|'medium'|'long'); currently we keep < 300 chars
    """
    rnd = random.Random(str(seed) if seed is not None else None)
    templates = _load_templates()

    # Normalize category key
    cat = (category or "miscellaneous").strip()
    key = cat.lower().replace(" ", "_")
    # fallback chain
    data = templates.get(key) or templates.get(category) or templates.get(cat) or templates.get("default") or {}

    # Pull caption list
    cap_list = data.get("captions") if isinstance(data, dict) else None
    if not cap_list or not isinstance(cap_list, list):
        # very safe fallbacks
        cap_list = [
            "{subject} in {location}.",
            "A quiet moment with {subject} in {location}.",
            "Seen in {location}: {subject}.",
            "{subject}—made on a walk in {location}.",
            "A simple frame from {location}.",
        ]

    # Provide a few micro-phrases to improve flow when subject missing
    intros = [
        "A quiet frame of {subject}",
        "{subject} in natural light",
        "{subject}, found by chance",
        "A simple look at {subject}",
        "A fleeting moment with {subject}",
    ]

    # Pick a template
    base = _pick(cap_list, rnd)
    # If subject is empty, optionally swap to a simpler pattern
    if not (subject and subject.strip()):
        base = _pick([
            "A simple frame in {location}.",
            "Made in {location}.",
            "A moment from {location}.",
            "From {location}.",
        ], rnd)

    # humanize values
    subj = _smart_title(subject or "")
    loc  = _smart_title(location or "")

    caption = _safe_replace(base, subject=subj, location=loc, camera=camera or "")

    # Optionally append a soft credit (kept short & natural)
    # Keep it minimal to avoid sounding like ad copy.
    # You can toggle this line on/off if you prefer no credit in captions.
    # caption += " — Photo by Amir Darzi (YOUR_HOST)"

    # Final cleanup
    caption = _clean_spaces(caption)
    # Ensure sentence ends with a period
    if caption and caption[-1] not in ".!?":
        caption += "."
    return caption

def generate_keywords(category: str,
                      subject: Optional[str],
                      location: Optional[str],
                      extra: Optional[List[str]] = None) -> str:
    """
    Returns a comma-separated string of keyword phrases, deduped and tidy.
    Keeps human-friendly phrases, avoids spammy stuffing.
    """
    templates = _load_templates()

    cat = (category or "miscellaneous").strip()
    key = cat.lower().replace(" ", "_")
    data = templates.get(key) or templates.get(category) or templates.get(cat) or {}
    base_kw = (data.get("keywords") or []) if isinstance(data, dict) else []

    bucket: List[str] = []

    # keep camera phrase exact-case if present
    if extra:
        for x in extra:
            x = (x or "").strip()
            if not x:
                continue
            # Canon EOS R5 Mark II -> keep full phrase
            bucket.append(x)

    # subject/location phrases
    if subject:
        bucket.append(_smart_title(subject))
    if location:
        bucket.append(_smart_title(location))

    # category hints (keep short)
    bucket.append(_smart_title(cat))

    # add curated base keywords from templates
    for k in base_kw:
        k = str(k).strip()
        if k:
            bucket.append(k)

    # always include brand & site once
    essentials = ["Amir Darzi", "YOUR_HOST", "photography"]
    for e in essentials:
        if e not in bucket:
            bucket.append(e)

    # dedupe while preserving order
    seen = set()
    clean_list = []
    for item in bucket:
        norm = re.sub(r"\s+", " ", item).strip().lower()
        if not norm or norm in seen:
            continue
        seen.add(norm)
        clean_list.append(item)

    # avoid trailing "photography" repetition if the category already implies it
    # (light touch—leave as-is otherwise)
    if len(clean_list) >= 2 and clean_list[-1].lower() == "photography" and "photography" in clean_list[-2].lower():
        clean_list.pop()

    return ", ".join(clean_list[:30])  # keep it compact

