from __future__ import annotations

import argparse
import ast
import base64
import csv
import hashlib
import io
import json
import re
import sqlite3
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

import requests
from PIL import Image
from tqdm import tqdm

# ============================================================
# Goals (your requirements)
# - READ images from ollama_path column (fallback to Path)
# - OUTPUT: basic acceptable quality, human readable
# - NO duplicates (strict global + series prefix guards)
# - NO hallucinations (no guessing, no invented species/location)
# - EXACT keyword count (keywords_n)
# - alt_text: 10-18 words, factual
# - caption: 1 sentence, factual, include location ONLY if provided in DB
# ============================================================

_WS_RE = re.compile(r"\s+")
_NON_WORD_RE = re.compile(r"[^a-z0-9 ]+", re.IGNORECASE)
_SEQ_SUFFIX_RE = re.compile(r"(?:^|[_-])(\d{1,5})$", re.IGNORECASE)

_LOCATION_LIST_PATH = Path(__file__).resolve().parent / "data" / "location_list.json"
_FOLDER_MAP_PATH = Path(__file__).resolve().parent / "data" / "folder_map.json"
_KNOWN_LOCATION_PHRASES: Set[str] = set()
_KNOWN_LOCATION_TOKENS: Set[str] = set()
_KNOWN_FOLDER_TOKENS: Set[str] = set()
_FOLDER_MAP_BY_KEY: Dict[str, str] = {}

# Words we do not want in keywords (fluff, meta, and your website/gear junk)
_KW_BANNED: Set[str] = {
    "angle",
    "composition",
    "background",
    "setting",
    "beautiful",
    "serene",
    "stunning",
    "photography",
    "photo",
    "image",
    "picture",
    "canon",
    "eos",
    "r5",
    "mark",
    "ii",
    "camera",
    "lens",
    # filename and generic junk
    "collection",
    "scenes",
    "scene",
    "highway",
    "roadscenes",
    "this",
    "frame",
    "shows",
    "features",
    "featuring",
    "captures",
    "capture",
    "perspective",
    "vantage",
    "framing",
    "view",
    "detail",
    "details",
    "context",
    "surrounding",
    "surroundings",
    "nearby",
    "possibly",
    "maybe",
    "likely",
    "appears",
    "season",
    "during",
    "above",
    "area",
    "depth",
    "foreground",
    "open",
    "clear",
    "natural",
    "outdoor",
    "outdoors",
    "travel",
    "scenic",
    "environment",
    "environmental",
    "transport",
    "transportation",
    "vehicle",
    "traffic",
    "seen",
    "shown",
    "viewed",
    "look",
    "looks",
    "looking",
    "image",
    "photo",
    "picture",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "distant",
    "large",
    "flat",
    "grassy",
    "western",
    "american",
    "cities",
    "towns",
    "nature",
    "landscape",
}

_KW_STOPWORDS: Set[str] = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "near",
    "of",
    "on",
    "or",
    "out",
    "over",
    "the",
    "through",
    "to",
    "with",
    "without",
    "around",
    "along",
    "across",
    "behind",
    "beyond",
    "under",
    "toward",
    "towards",
    "stretches",
    "stretch",
    "stretched",
    "visible",
    "its",
    "few",
    "small",
    "most",
    "more",
    "less",
}

# Keep empty by default: never force geography or unrelated filler tokens.
_KW_VARIANT_POOL: Sequence[str] = ()

_KW_WEAK: Set[str] = {
    "western",
    "american",
    "cities",
    "towns",
    "nature",
    "rural",
    "urban",
    "landscape",
    "transport",
    "vehicle",
    "traffic",
    "road",
}

_PRECISION_TERMS: List[Tuple[str, int]] = []


# Words we do not want in captions/alt (template junk)
_BAD_PHRASES = (
    "appears outdoors",
    "natural daylight",
    "broad scenery",
    "visible horizon",
    "american west",
    "urban scene",
    "metropolitan street setting",
    "cityscape view of urban scene",
)

_QUALITY_WEAK_TOKENS: Set[str] = {
    "scene",
    "view",
    "composition",
    "frame",
    "setting",
    "area",
    "background",
    "foreground",
    "outdoor",
    "outdoors",
    "scenic",
    "natural",
    "terrain",
    "surroundings",
    "details",
    "context",
}

_SCENE_MOUNTAIN_TERMS: Set[str] = {
    "mountain",
    "mountains",
    "ridge",
    "ridgeline",
    "foothill",
    "foothills",
    "peak",
    "peaks",
    "alpine",
    "valley",
    "trail",
}

_SCENE_URBAN_TERMS: Set[str] = {
    "city",
    "urban",
    "downtown",
    "road",
    "roads",
    "roadway",
    "highway",
    "lane",
    "street",
    "intersection",
    "traffic",
    "building",
    "buildings",
    "suburb",
    "suburban",
    "neighborhood",
}

_SCENE_RURAL_TERMS: Set[str] = {
    "rural",
    "farm",
    "county",
    "prairie",
    "plains",
    "meadow",
}

_URBAN_EVIDENCE_TERMS: Set[str] = {
    "city",
    "urban",
    "downtown",
    "road",
    "roadway",
    "highway",
    "lane",
    "street",
    "intersection",
    "building",
    "buildings",
    "storefront",
    "sidewalk",
    "crosswalk",
    "traffic",
    "vehicle",
    "vehicles",
    "car",
    "cars",
    "truck",
    "bus",
    "trolley",
    "theatre",
    "theater",
    "marquee",
}

_NATURE_EVIDENCE_TERMS: Set[str] = {
    "tree",
    "trees",
    "foliage",
    "leaf",
    "leaves",
    "branch",
    "branches",
    "flower",
    "flowers",
    "wildflower",
    "wildflowers",
    "sky",
    "sun",
    "sunlight",
    "mountain",
    "mountains",
    "ridge",
    "ridgeline",
    "forest",
    "rock",
    "rocks",
    "river",
    "creek",
    "water",
    "shoreline",
    "trail",
    "valley",
    "hills",
}

_URBAN_KEYWORD_TERMS: Set[str] = {
    "city",
    "urban",
    "downtown",
    "road",
    "roads",
    "highway",
    "lane",
    "skyline",
    "street",
    "buildings",
    "architecture",
    "avenue",
    "sidewalk",
    "intersection",
    "cityscape",
    "metro",
    "district",
    "roadway",
}

# Keep empty: do not force generic terrain keywords into the output.
_NATURE_KEYWORD_POOL: Sequence[str] = ()

_STRONG_NATURE_KEYWORD_TERMS: Set[str] = {
    "mountain",
    "mountains",
    "ridge",
    "ridgeline",
    "foothill",
    "foothills",
    "peak",
    "peaks",
    "alpine",
    "lake",
    "lakes",
    "river",
    "rivers",
    "creek",
    "forest",
    "woodland",
    "valley",
    "trail",
    "meadow",
    "shoreline",
    "tundra",
    "basin",
}

_STRONG_NATURE_KEYWORD_PHRASES: Set[str] = {
    "national park",
    "national forest",
    "state park",
}

_TERRAIN_HEAVY_TERMS: Set[str] = {
    "mountain",
    "mountains",
    "ridge",
    "ridgeline",
    "foothill",
    "foothills",
    "peak",
    "peaks",
    "alpine",
    "lake",
    "lakes",
    "river",
    "rivers",
    "forest",
    "woodland",
    "valley",
    "trail",
    "meadow",
    "tundra",
    "basin",
    "shoreline",
}

_EVIDENCE_SENSITIVE_KEYWORDS: Set[str] = {
    "usa",
    "united states",
    "colorado",
    "mountain",
    "mountains",
    "lake",
    "lakes",
    "forest",
    "river",
    "rivers",
    "valley",
    "trail",
}

_EVIDENCE_TERM_ALIASES: Dict[str, Tuple[str, ...]] = {
    "usa": ("usa", "u s a", "united states"),
    "united states": ("united states", "usa", "u s a"),
    "colorado": ("colorado",),
    "mountain": ("mountain", "mountains"),
    "mountains": ("mountain", "mountains"),
    "lake": ("lake", "lakes"),
    "lakes": ("lake", "lakes"),
    "forest": ("forest", "forests"),
    "river": ("river", "rivers"),
    "rivers": ("river", "rivers"),
    "valley": ("valley", "valleys"),
    "trail": ("trail", "trails"),
}

_AVIATION_HINTS: Set[str] = {
    "aviation",
    "aircraft",
    "airplane",
    "plane",
    "airliner",
    "jet",
    "boeing",
    "airbus",
    "helicopter",
    "airport",
    "runway",
    "cockpit",
    "fuselage",
    "wing",
}

_WILDLIFE_BIRD_HINTS: Set[str] = {
    "bird",
    "birds",
    "hawk",
    "eagle",
    "owl",
    "falcon",
    "gull",
    "duck",
    "goose",
    "heron",
    "raptor",
    "avian",
    "jay",
    "kestrel",
    "crow",
    "kingfisher",
    "wagtail",
    "parakeet",
    "woodpecker",
    "bulbul",
    "pigeon",
    "dove",
}

_WILDLIFE_MAMMAL_HINTS: Set[str] = {
    "squirrel",
    "rodent",
    "rabbit",
    "hare",
    "fox",
    "coyote",
    "elk",
    "deer",
    "moose",
    "bison",
    "bear",
    "wolf",
    "jackal",
    "cat",
    "dog",
    "fox",
}

_UNCERTAIN_PHRASES: Sequence[str] = (
    "maybe",
    "possibly",
    "probably",
    "perhaps",
    "likely",
    "might be",
    "appears to be",
    "seems to be",
)

_LOCATION_BAD_TOKENS: Set[str] = {
    "collection",
    "photography",
    "photo",
    "image",
    "images",
    "picture",
    "pictures",
    "scene",
    "scenes",
    "birds",
    "nature",
}

_LOCATION_GOOD_HINTS: Set[str] = {
    "country",
    "state",
    "province",
    "park",
    "district",
    "neighborhood",
    "county",
    "city",
    "town",
    "street",
    "avenue",
    "boulevard",
    "lane",
    "bridge",
    "mountain",
    "lake",
    "river",
    "road",
    "harbor",
    "airport",
    "island",
    "bay",
    "forest",
    "valley",
}


def _norm_text(s: str) -> str:
    s = (s or "").replace("_", " ").replace("-", " ").strip().lower()
    s = _WS_RE.sub(" ", s)
    return s


def _norm_text_strict(s: str) -> str:
    s = _norm_text(s)
    s = _NON_WORD_RE.sub("", s)
    s = _WS_RE.sub(" ", s).strip()
    return s


def _load_taxonomy_context() -> Tuple[Set[str], Set[str], Set[str], Dict[str, str]]:
    """
    Load optional taxonomy context from local JSON files:
    - data/location_list.json (list[str])
    - data/folder_map.json (dict[str, str])
    """
    loc_phrases: Set[str] = set()
    loc_tokens: Set[str] = set()
    folder_tokens: Set[str] = set()
    folder_map: Dict[str, str] = {}

    try:
        if _LOCATION_LIST_PATH.exists():
            raw = json.loads(_LOCATION_LIST_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                for item in raw:
                    norm = _norm_text_strict(str(item or "").replace("_", " "))
                    if not norm:
                        continue
                    loc_phrases.add(norm)
                    for tok in norm.split():
                        if len(tok) >= 3 and tok not in _KW_STOPWORDS and tok not in _KW_BANNED:
                            loc_tokens.add(tok)
    except Exception:
        pass

    try:
        if _FOLDER_MAP_PATH.exists():
            raw = json.loads(_FOLDER_MAP_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for k, v in raw.items():
                    kk = str(k or "").strip()
                    vv = str(v or "").strip()
                    if kk:
                        folder_map[kk.lower()] = vv
                    for text in (kk, vv):
                        norm = _norm_text_strict(text.replace("_", " "))
                        if not norm:
                            continue
                        for tok in norm.split():
                            if len(tok) >= 3 and tok not in _KW_STOPWORDS and tok not in _KW_BANNED:
                                folder_tokens.add(tok)
    except Exception:
        pass

    return loc_phrases, loc_tokens, folder_tokens, folder_map


_KNOWN_LOCATION_PHRASES, _KNOWN_LOCATION_TOKENS, _KNOWN_FOLDER_TOKENS, _FOLDER_MAP_BY_KEY = _load_taxonomy_context()


def _first_words_key(s: str, n_words: int) -> str:
    if int(n_words) <= 0:
        return ""
    s = _norm_text_strict(s)
    if not s:
        return ""
    parts = s.split()
    return " ".join(parts[: max(1, n_words)])


def _normalize_keyword(k: str) -> str:
    k = (k or "").replace("_", " ").replace("-", " ").strip()
    k = _WS_RE.sub(" ", k).strip()
    kn = _norm_text_strict(k)
    if not kn:
        return ""

    parts = kn.split()
    if not parts:
        return ""
    joined_full = " ".join(parts)
    keep_long = False
    if any(x in joined_full for x in ("national park", "state park", "national forest", "national monument")) and len(parts) <= 4:
        keep_long = True
    if joined_full in {"glass ball"}:
        keep_long = True
    if len(parts) > 2 and not keep_long:
        parts = parts[:2]
    if len(parts) == 2 and parts[0] == parts[1]:
        return ""

    for p in parts:
        if p in _KW_BANNED or p in _KW_STOPWORDS:
            return ""
        if p.isdigit() or len(p) < 3:
            return ""

    joined = " ".join(parts)
    if joined in _KW_BANNED or joined in _KW_STOPWORDS:
        return ""
    if joined in {"mountain range", "wide view", "road scene"}:
        return ""
    return joined


def _clean_keywords_list(items: Sequence[str]) -> List[str]:
    out: List[str] = []
    seen: Set[str] = set()
    for it in items:
        kn = _normalize_keyword(str(it or ""))
        if not kn:
            continue
        if kn in seen:
            continue
        seen.add(kn)
        out.append(kn)
    return out


def _extract_phrase_keywords(folder: str, subject: str, location: str, caption: str) -> List[str]:
    src = _norm_text_strict(_clean_phrase(f"{folder} {subject} {location} {caption}"))
    if not src:
        return []

    out: List[str] = []
    seen: Set[str] = set()

    def add(k: str) -> None:
        kn = _normalize_keyword(k)
        if not kn or kn in seen:
            return
        seen.add(kn)
        out.append(kn)

    loc_norm = _norm_text_strict(str(location or "").replace("_", " "))
    if loc_norm and loc_norm in _KNOWN_LOCATION_PHRASES:
        add(loc_norm)

    for m in re.finditer(r"\b([a-z]+(?: [a-z]+){0,3} (?:national park|state park|national forest|national monument))\b", src):
        add(m.group(1))
    for m in re.finditer(r"\b([a-z]+(?: [a-z]+){0,2} city)\b", src):
        add(m.group(1))
    for m in re.finditer(r"\b(downtown [a-z]+(?: [a-z]+)?)\b", src):
        add(m.group(1))

    # Generic named-place extraction for common geo/location phrase endings.
    for m in re.finditer(
        r"\b([a-z]+(?: [a-z]+){0,3} (?:road|street|avenue|boulevard|bridge|park|square|plaza|harbor|airport|station|tower|lake|river|district|island|bay))\b",
        src,
    ):
        add(m.group(1))

    if "glass ball" in src:
        add("glass ball")

    return out


def load_precision_terms(
    *,
    db_path: str,
    table: str = "keyword_terms",
    min_precision: int = 85,
) -> List[Tuple[str, int]]:
    dbp = Path(db_path)
    if not dbp.exists():
        return []

    con = sqlite3.connect(str(dbp))
    try:
        sql = (
            f'SELECT COALESCE(term_norm, term), COALESCE(precision_weight, 0) '
            f'FROM "{table}" '
            f'WHERE COALESCE(active, 1) = 1 '
            f'  AND COALESCE(precision_weight, 0) >= ? '
            f'ORDER BY COALESCE(precision_weight, 0) DESC, COALESCE(term_norm, term) ASC'
        )
        cur = con.execute(sql, (int(min_precision),))
        best: Dict[str, int] = {}
        for term_raw, w_raw in cur.fetchall():
            kn = _normalize_keyword(str(term_raw or ""))
            if not kn:
                continue
            w = int(w_raw or 0)
            prev = best.get(kn)
            if prev is None or w > prev:
                best[kn] = w
        return sorted(best.items(), key=lambda x: (-x[1], x[0]))
    except Exception:
        return []
    finally:
        try:
            con.close()
        except Exception:
            pass


def _precision_candidates(
    *,
    folder: str,
    subject: str,
    location: str,
    caption: str,
    limit: int = 60,
) -> List[str]:
    if not _PRECISION_TERMS:
        return []

    ctx = _norm_text_strict(f"{folder} {subject} {location} {caption}")
    ctx_tokens = set([t for t in ctx.split() if t and t not in _KW_STOPWORDS and t not in _KW_BANNED])
    if not ctx_tokens:
        return []

    scored: List[Tuple[int, str]] = []
    for term, w in _PRECISION_TERMS:
        parts = term.split()
        if not parts:
            continue
        hits = sum(1 for p in parts if p in ctx_tokens)
        if hits == 0:
            continue
        if len(parts) >= 2 and hits < len(parts):
            continue
        score = int(w) + 12 * hits + (8 if hits == len(parts) else 0)
        scored.append((score, term))

    scored.sort(key=lambda x: (-x[0], x[1]))
    out: List[str] = []
    seen: Set[str] = set()
    for _, t in scored:
        if t in seen:
            continue
        if len(t.split()) == 1 and any(t in z.split() for z in out if len(z.split()) > 1):
            continue
        seen.add(t)
        out.append(t)
        if len(out) >= limit:
            break
    return out


def _inject_precision_terms(
    *,
    kw_list: Sequence[str],
    folder: str,
    subject: str,
    location: str,
    caption: str,
    keywords_n: int,
) -> List[str]:
    out = _clean_keywords_list(kw_list)

    # Prefer specific multi-word phrases from context (parks, roads, named places).
    for phr in _extract_phrase_keywords(folder, subject, location, caption):
        if phr in out:
            continue
        if len(out) < keywords_n:
            out.append(phr)
            continue
        weak_ix = next((i for i, k in enumerate(out) if k in _KW_WEAK), None)
        if weak_ix is not None:
            out[weak_ix] = phr

    out = _clean_keywords_list(out)
    if not _PRECISION_TERMS:
        return out[:keywords_n]

    cands = _precision_candidates(
        folder=folder,
        subject=subject,
        location=location,
        caption=caption,
        limit=80,
    )
    if not cands:
        return out[:keywords_n]

    seen = set(out)
    weak_ix = [i for i, k in enumerate(out) if k in _KW_WEAK]

    for cand in cands:
        if cand in seen:
            continue
        if len(out) < keywords_n:
            out.append(cand)
            seen.add(cand)
            continue
        if weak_ix:
            idx = weak_ix.pop(0)
            old = out[idx]
            if old in seen:
                seen.remove(old)
            out[idx] = cand
            seen.add(cand)

    return _clean_keywords_list(out)[:keywords_n]


def _wildlife_mode(folder: str, subject: str) -> str:
    low = _norm_text_strict(_clean_phrase(f"{folder} {subject}"))
    if not low:
        return "general"
    if ("prairie dog" in low) or ("ground squirrel" in low):
        return "mammal"
    if any(h in low for h in _WILDLIFE_BIRD_HINTS):
        return "bird"
    if any(h in low for h in _WILDLIFE_MAMMAL_HINTS):
        return "mammal"
    return "general"


def _scene_expected_mode(folder: str, subject: str, location: str) -> str:
    kind = _infer_subject_kind(folder, subject)
    if kind == "vehicle":
        return _vehicle_scene_mode(folder, subject, location)
    if kind == "aviation":
        return "aviation"
    if kind in {"urban", "architecture", "structure"}:
        return "urban"
    if kind in {"landscape", "waterscape", "desert", "wildlife"}:
        return "nature"
    return "mixed"


def _keyword_matches_context(kn: str, context_text: str, context_tokens: Set[str]) -> bool:
    k = _norm_text_strict(kn)
    if not k:
        return False
    if k in context_text:
        return True
    parts = [p for p in k.split() if p]
    if not parts:
        return False
    return all((p in context_tokens) for p in parts)


def _is_strong_nature_keyword(kn: str) -> bool:
    k = _norm_text_strict(kn)
    if not k:
        return False
    if k in _STRONG_NATURE_KEYWORD_PHRASES:
        return True
    return bool(set(k.split()) & _STRONG_NATURE_KEYWORD_TERMS)


def _is_urban_keyword(kn: str) -> bool:
    k = _norm_text_strict(kn)
    if not k:
        return False
    return bool(set(k.split()) & _URBAN_KEYWORD_TERMS)


def _is_terrain_heavy_keyword(kn: str) -> bool:
    k = _norm_text_strict(kn)
    if not k:
        return False
    if k in _STRONG_NATURE_KEYWORD_PHRASES:
        return True
    return bool(set(k.split()) & _TERRAIN_HEAVY_TERMS)


def _is_wildlife_keyword(kn: str) -> bool:
    k = _norm_text_strict(kn)
    if not k:
        return False
    parts = set(k.split())
    return bool(parts & _WILDLIFE_BIRD_HINTS) or bool(parts & _WILDLIFE_MAMMAL_HINTS)


def _apply_scene_keyword_guardrails(
    *,
    kw_list: Sequence[str],
    folder: str,
    subject: str,
    location: str,
    caption: str,
    alt_text: str,
    keywords_n: int,
) -> List[str]:
    kind = _infer_subject_kind(folder, subject)
    expected = _scene_expected_mode(folder, subject, location)
    context_text = _norm_text_strict(f"{folder} {subject} {location}")
    context_tokens = set(context_text.split())

    filtered: List[str] = []
    seen: Set[str] = set()
    for raw in _clean_keywords_list(kw_list):
        kn = _norm_text_strict(raw)
        if not kn or kn in seen:
            continue
        # Geographic tokens are only valid when supported by row context
        # (location/subject/folder). Prevents cross-country leakage.
        if _KNOWN_LOCATION_TOKENS and (set(kn.split()) & _KNOWN_LOCATION_TOKENS):
            if not _keyword_matches_context(kn, context_text, context_tokens):
                continue
        if expected in {"urban", "road"} and _is_strong_nature_keyword(kn):
            if not _keyword_matches_context(kn, context_text, context_tokens):
                continue
        if expected in {"mountain", "nature", "rural"} and _is_urban_keyword(kn):
            if not _keyword_matches_context(kn, context_text, context_tokens):
                continue
        if expected == "aviation" and _is_urban_keyword(kn):
            if not _keyword_matches_context(kn, context_text, context_tokens):
                continue
        # Avoid generic terrain stuffing for non-landscape subjects unless context explicitly supports it.
        if kind in {"wildlife", "macro", "aviation", "urban", "architecture"} and _is_terrain_heavy_keyword(kn):
            if not _keyword_matches_context(kn, context_text, context_tokens):
                continue
        # Aviation should not borrow wildlife tags unless explicitly present in context.
        if expected == "aviation" and _is_wildlife_keyword(kn):
            if not _keyword_matches_context(kn, context_text, context_tokens):
                continue
        seen.add(kn)
        filtered.append(kn)

    refill_pool: List[str] = []
    refill_pool.extend(_visual_keyword_candidates(caption, alt_text, location))
    refill_pool.extend(_extract_phrase_keywords(folder, subject, location, caption))
    refill_pool.extend(_context_keyword_pool(folder, subject))
    refill_pool.extend(_context_tail_keywords(folder, subject))
    if expected in {"mountain", "nature", "rural"}:
        refill_pool.extend(list(_NATURE_KEYWORD_POOL))

    for cand in refill_pool:
        if len(filtered) >= int(keywords_n):
            break
        kn = _normalize_keyword(cand)
        if not kn or kn in seen:
            continue
        if _KNOWN_LOCATION_TOKENS and (set(kn.split()) & _KNOWN_LOCATION_TOKENS):
            if not _keyword_matches_context(kn, context_text, context_tokens):
                continue
        if expected in {"urban", "road"} and _is_strong_nature_keyword(kn):
            if not _keyword_matches_context(kn, context_text, context_tokens):
                continue
        if expected in {"mountain", "nature", "rural"} and _is_urban_keyword(kn):
            if not _keyword_matches_context(kn, context_text, context_tokens):
                continue
        if expected == "aviation" and _is_urban_keyword(kn):
            if not _keyword_matches_context(kn, context_text, context_tokens):
                continue
        if kind in {"wildlife", "macro", "aviation", "urban", "architecture"} and _is_terrain_heavy_keyword(kn):
            if not _keyword_matches_context(kn, context_text, context_tokens):
                continue
        if expected == "aviation" and _is_wildlife_keyword(kn):
            if not _keyword_matches_context(kn, context_text, context_tokens):
                continue
        seen.add(kn)
        filtered.append(kn)

    return _clean_keywords_list(filtered)[: int(keywords_n)]


def _context_keyword_pool(folder: str, subject: str) -> List[str]:
    kind = _infer_subject_kind(folder, subject)
    s = _norm_text_strict(_clean_phrase(subject))
    st = set(s.split())
    if kind == "vehicle":
        out = ["road", "highway", "street", "lane", "roadway", "intersection", "pavement", "asphalt", "roadside", "lane markings", "road signs"]
        if "car" in st:
            out.append("car")
        if "jeep" in st:
            out.append("jeep")
        if "truck" in st or "semi" in st:
            out.append("truck")
            if "semi" in st:
                out.append("semi truck")
        if "bus" in st:
            out.append("bus")
            if "school" in st:
                out.append("school bus")
        if "suv" in st:
            out.append("suv")
        return out
    if kind == "wildlife":
        wmode = _wildlife_mode(folder, subject)
        if wmode == "bird":
            out = ["wildlife", "bird", "raptor", "perch", "feathers", "beak", "avian", "plumage", "talons", "wings", "habitat"]
            if "hawk" in st:
                out.append("hawk")
        elif wmode == "mammal":
            out = ["wildlife", "animal", "mammal", "rodent", "field", "grassland", "burrow", "foraging", "habitat", "fur", "ground level"]
            if ("prairie" in st and "dog" in st):
                out.append("prairie dog")
            if ("ground" in st and "squirrel" in st):
                out.append("ground squirrel")
            if "squirrel" in st:
                out.append("squirrel")
            if "elk" in st:
                out.append("elk")
            if "deer" in st:
                out.append("deer")
        else:
            out = ["wildlife", "animal", "habitat", "field", "ground level", "natural cover", "outdoor subject", "foraging", "behavior"]
        return out
    if kind == "aviation":
        return ["aviation", "aircraft", "airplane", "flight", "jet", "fuselage", "wing", "landing gear", "airliner", "sky", "clouds", "airport", "runway", "takeoff", "approach"]
    if kind == "structure":
        return ["industrial", "silos", "facility", "storage", "infrastructure", "plant", "warehouse", "yard", "metal", "construction", "utilities", "factory", "grain", "silo complex", "industrial site", "utility yard"]
    if kind == "urban":
        return ["city", "urban", "downtown", "skyline", "street", "buildings", "architecture", "avenue", "sidewalk", "intersection", "cityscape", "metro", "district", "roadway", "bridge"]
    if kind == "architecture":
        return ["architecture", "building", "facade", "structure", "tower", "bridge", "exterior", "design", "urban", "cityscape", "construction", "windows", "roofline", "landmark", "cabin"]
    if kind == "macro":
        return ["macro", "closeup", "texture", "focus", "pattern", "surface", "petal", "leaf", "insect", "flower", "bokeh", "micro", "pollen", "filament", "veins"]
    if kind == "waterscape":
        return ["water", "shoreline", "reflection", "river", "waterfall", "waves", "coast", "lake", "stream", "surface", "ripples", "shore", "waterscape", "wetland", "harbor"]
    if kind == "desert":
        return ["desert", "canyon", "mesa", "butte", "arid", "rock", "sandstone", "dunes", "plateau", "cliffs", "dry terrain", "geology", "southwest", "erosion", "open sky"]
    if kind == "night":
        return ["night", "dusk", "twilight", "evening", "night sky", "stars", "city lights", "silhouette", "long exposure", "skyline", "moonlight", "low light", "after sunset", "nocturnal", "horizon glow"]
    if kind == "glassball":
        return ["glass ball", "sphere", "reflection", "refraction", "lensball", "crystal", "bokeh", "optical", "macro", "closeup", "park", "mountains"]
    if kind == "landscape":
        return ["mountain", "mountains", "lake", "forest", "river", "valley", "trail", "trees", "sky", "hills", "ridgeline", "terrain", "horizon", "foothills", "woodland", "meadow", "national park"]
    return ["landscape", "trees", "sky", "terrain", "horizon", "outdoors", "daylight", "nature", "environment", "scenery"]


def _context_tail_keywords(folder: str, subject: str) -> List[str]:
    kind = _infer_subject_kind(folder, subject)
    if kind == "vehicle":
        return ["road", "street", "lane", "roadway", "highway", "pavement", "intersection", "asphalt", "roadside", "commute", "motorway", "lane markings", "road signs", "city road", "urban road"]
    if kind == "wildlife":
        wmode = _wildlife_mode(folder, subject)
        if wmode == "bird":
            return ["wildlife", "bird", "raptor", "perch", "habitat", "sky", "avian", "plumage", "talons", "wings", "predator"]
        if wmode == "mammal":
            return ["wildlife", "animal", "mammal", "rodent", "squirrel", "prairie dog", "ground squirrel", "grassland", "field", "burrow", "foraging", "habitat", "fur"]
        return ["wildlife", "animal", "habitat", "field", "ground level", "natural cover", "foraging", "behavior"]
    if kind == "aviation":
        return ["aviation", "aircraft", "airplane", "flight", "jet", "airliner", "fuselage", "wing", "landing gear", "airport", "runway", "takeoff", "approach", "sky", "clouds"]
    if kind == "structure":
        return ["industrial", "silos", "facility", "storage", "infrastructure", "plant", "warehouse", "construction", "factory", "grain", "silo complex", "industrial site", "utility yard"]
    if kind == "urban":
        return ["city", "urban", "downtown", "skyline", "street", "buildings", "architecture", "avenue", "sidewalk", "intersection", "cityscape", "metro", "district", "roadway", "bridge"]
    if kind == "architecture":
        return ["architecture", "building", "facade", "structure", "tower", "bridge", "exterior", "design", "roofline", "landmark", "windows", "construction", "urban", "cityscape", "cabin"]
    if kind == "macro":
        return ["macro", "closeup", "texture", "pattern", "focus", "surface", "petal", "leaf", "insect", "flower", "bokeh", "micro", "pollen", "filament", "veins"]
    if kind == "waterscape":
        return ["water", "shoreline", "reflection", "river", "waterfall", "waves", "coast", "lake", "stream", "ripples", "shore", "waterscape", "wetland", "harbor", "water surface"]
    if kind == "desert":
        return ["desert", "canyon", "mesa", "butte", "arid", "rock", "sandstone", "dunes", "plateau", "cliffs", "dry terrain", "geology", "southwest", "erosion", "open sky"]
    if kind == "night":
        return ["night", "dusk", "twilight", "evening", "night sky", "stars", "city lights", "silhouette", "long exposure", "skyline", "moonlight", "low light", "after sunset", "nocturnal", "horizon glow"]
    if kind == "glassball":
        return ["glass ball", "sphere", "reflection", "refraction", "lensball", "crystal", "bokeh", "optical", "macro", "closeup", "park", "mountains"]
    if kind == "landscape":
        return ["mountains", "lake", "forest", "river", "valley", "trail", "trees", "sky", "horizon", "ridgeline", "foothills", "woodland", "meadow", "terrain", "national park"]
    return ["landscape", "trees", "sky", "terrain", "horizon", "outdoors", "daylight", "nature", "environment", "scenery"]


def _split_keywords(raw: str) -> List[str]:
    raw = (raw or "").strip()
    if not raw:
        return []

    items = re.split(r"[,\n]+", raw)
    out: List[str] = []
    seen: Set[str] = set()

    for it in items:
        k = it.strip()
        if not k:
            continue

        kn = _normalize_keyword(k)
        if not kn:
            continue

        if kn in seen:
            continue

        seen.add(kn)
        out.append(kn)

    return out


def _sanitize_sentence(s: str) -> str:
    s = (s or "").strip()
    s = _WS_RE.sub(" ", s).strip()
    if not s:
        return ""
    s = re.sub(r"\s+,", ",", s)
    s = re.sub(r",\s*\.", ".", s)
    s = re.sub(r"\.\s*,", ".", s)
    s = re.sub(r"\s+\.", ".", s)
    s = re.sub(r"\s+\?", "?", s)
    s = re.sub(r"\s+!", "!", s)
    s = re.sub(r"([,.;!?])\1+", r"\1", s)
    s = _WS_RE.sub(" ", s).strip()
    if s[-1] not in ".!?":
        s += "."
    # remove known junk phrases
    low = s.lower()
    for bp in _BAD_PHRASES:
        if bp in low:
            s = re.sub(re.escape(bp), "", s, flags=re.IGNORECASE)
            s = _WS_RE.sub(" ", s).strip()
            if not s:
                return ""
            if s[-1] not in ".!?":
                s += "."
            low = s.lower()
    return s


def _strip_non_ascii(s: str) -> str:
    if not s:
        return ""
    return s.encode("ascii", errors="ignore").decode("ascii", errors="ignore")


def _clean_text_output(s: str) -> str:
    s = _strip_non_ascii(s or "")
    s = s.replace("\uFFFD", " ")
    s = _WS_RE.sub(" ", s).strip()
    return s


def _deawkward_sentence(s: str) -> str:
    s = _clean_text_output(s)
    if not s:
        return s
    s = re.sub(r"\bmountains and a mountain\b", "mountains", s, flags=re.IGNORECASE)
    s = re.sub(r"\b([A-Za-z]+)\s+and\s+a\s+\1\b", r"\1", s, flags=re.IGNORECASE)
    s = re.sub(r"\b([A-Za-z]+)\s+\1\b", r"\1", s, flags=re.IGNORECASE)
    s = _WS_RE.sub(" ", s).strip()
    return s


def _has_repetition_artifact(s: str) -> bool:
    toks = [_norm_text_strict(w) for w in (s or "").split()]
    toks = [t for t in toks if t and t not in _KW_STOPWORDS]
    if len(toks) < 6:
        return False

    freq = Counter(toks)
    top = max(freq.values()) if freq else 0
    if top >= 4:
        return True
    if top >= 3 and (top / float(max(1, len(toks))) >= 0.35):
        return True

    bigrams = [" ".join(toks[i : i + 2]) for i in range(0, max(0, len(toks) - 1))]
    if bigrams:
        bfreq = Counter(bigrams)
        if max(bfreq.values()) >= 3:
            return True
    return False


def _has_low_quality_phrase(s: str) -> bool:
    raw = (s or "").strip()
    txt = _norm_text(raw)
    if not txt:
        return True
    if re.search(r"\b[a-z]{2,}[A-Z][A-Za-z]*\b", raw):
        return True
    if any(len(tok) >= 19 for tok in re.findall(r"[A-Za-z]+", raw)):
        return True
    bad_patterns = (
        r"\bwith background detail\b",
        r"\bwith simple scene detail\b",
        r"\bwith straightforward context\b",
        r"\bin daylight conditions\b",
        r"\bthe scene remains visible\b",
        r"\bvisible in broad daylight\b",
        r"\bvisible in the background\b",
        r"\bwith context\b",
        r"\bshows? a with\b",
        r"\b[a-z]+-\s+with\b",
        r"\b[a-z]+-\.$",
        r"\bfeatures a [a-z ]{1,48} that\b",
        r"\bopen-?terrain view of\b",
        r"\bmountain view of mountain road\b",
        r"\burban scene\b",
        r"\bmetropolitan street setting\b",
        r"\bcityscape view of urban scene\b",
        r"\bsits among dense city buildings\b",
        r"\bappears within downtown streets\b",
        r"\bstreet-level city view of urban scene\b",
        r"\bin this photo\b",
        r",\s*\.$",
    )
    for pat in bad_patterns:
        if re.search(pat, txt):
            return True
    if re.search(r"\b(a|an|the)\s+[a-z]+-\s*(?:with|in|on|at|$)", txt):
        return True
    return False


def _contains_uncertainty(s: str) -> bool:
    low = _norm_text(s)
    for p in _UNCERTAIN_PHRASES:
        if p in low:
            return True
    return False


def _scene_flags(text: str) -> Tuple[bool, bool, bool]:
    low = _norm_text_strict(text)
    if not low:
        return False, False, False
    toks = set(low.split())
    has_mountain = bool(toks & _SCENE_MOUNTAIN_TERMS) or ("national park" in low)
    has_urban = bool(toks & _SCENE_URBAN_TERMS) or ("city street" in low)
    has_rural = bool(toks & _SCENE_RURAL_TERMS)
    return has_mountain, has_urban, has_rural


def _scene_evidence_counts(caption: str, alt_text: str) -> Tuple[int, int]:
    low = _norm_text_strict(f"{caption} {alt_text}")
    if not low:
        return 0, 0
    toks = set(low.split())

    urban_hits = len(toks & _URBAN_EVIDENCE_TERMS)
    nature_hits = len(toks & _NATURE_EVIDENCE_TERMS)

    # Small phrase boosts for clearer visual cues.
    if "street light" in low or "streetlights" in low:
        urban_hits += 2
    if "fall foliage" in low or "autumn foliage" in low:
        nature_hits += 2
    if "blue sky" in low:
        nature_hits += 1

    return urban_hits, nature_hits


def _visual_nature_without_urban(caption: str, alt_text: str) -> bool:
    urban_hits, nature_hits = _scene_evidence_counts(caption, alt_text)
    return nature_hits >= 2 and urban_hits == 0


def _visual_keyword_candidates(caption: str, alt_text: str, location: str = "") -> List[str]:
    raw = _norm_text_strict(f"{caption} {alt_text} {location}")
    if not raw:
        return []
    out: List[str] = []
    seen: Set[str] = set()
    for tok in raw.split():
        kn = _normalize_keyword(tok)
        if not kn or kn in seen:
            continue
        if kn in _KW_BANNED or kn in _KW_STOPWORDS or kn in _QUALITY_WEAK_TOKENS:
            continue
        seen.add(kn)
        out.append(kn)
    return out


def _rebalance_keywords_visual_context(
    *,
    kw_list: Sequence[str],
    caption: str,
    alt_text: str,
    folder: str,
    subject: str,
    location: str,
    keywords_n: int,
) -> List[str]:
    out = _clean_keywords_list(kw_list)
    if not out:
        return out
    if not _visual_nature_without_urban(caption, alt_text):
        return out[:keywords_n]

    # If text is nature-first and contains no urban evidence, remove urban-heavy tags.
    keep_always: Set[str] = set()
    filtered: List[str] = []
    seen: Set[str] = set()
    for kw in out:
        kn = _norm_text_strict(kw)
        if not kn:
            continue
        parts = set(kn.split())
        if (parts & _URBAN_KEYWORD_TERMS) and (kn not in keep_always):
            continue
        if kn in seen:
            continue
        seen.add(kn)
        filtered.append(kn)
    out = filtered

    # Refill from visible cues first, then safe nature pool.
    refill_pool: List[str] = []
    refill_pool.extend(_visual_keyword_candidates(caption, alt_text, location))
    refill_pool.extend(_extract_phrase_keywords(folder, subject, location, f"{caption} {alt_text}"))
    refill_pool.extend(list(_NATURE_KEYWORD_POOL))

    for cand in refill_pool:
        if len(out) >= keywords_n:
            break
        kn = _normalize_keyword(cand)
        if not kn:
            continue
        if set(kn.split()) & _URBAN_KEYWORD_TERMS:
            continue
        if kn in seen:
            continue
        seen.add(kn)
        out.append(kn)

    return _clean_keywords_list(out)[:keywords_n]


def _caption_alt_scene_conflict(caption: str, alt_text: str) -> bool:
    cap_mtn, cap_urban, _ = _scene_flags(caption)
    alt_mtn, alt_urban, _ = _scene_flags(alt_text)
    return (cap_mtn and alt_urban) or (cap_urban and alt_mtn)


def _vehicle_scene_mode(folder: str, subject: str, location: str) -> str:
    low = _norm_text_strict(f"{folder} {subject} {location}")
    if not low:
        return "road"
    toks = set(low.split())

    mountain_hits = len(toks & _SCENE_MOUNTAIN_TERMS)
    if "national park" in low:
        mountain_hits += 2

    urban_hits = len(toks & _SCENE_URBAN_TERMS)
    rural_hits = len(toks & _SCENE_RURAL_TERMS)
    if "highway and road scenes" in low:
        urban_hits += 1
    if "transportation collection" in low:
        urban_hits += 1

    if mountain_hits >= 2:
        return "mountain"
    if urban_hits >= 2 and mountain_hits == 0:
        return "urban"
    if rural_hits >= 2 and mountain_hits == 0:
        return "rural"
    if mountain_hits >= 1 and urban_hits == 0:
        return "mountain"
    if urban_hits >= 1 and mountain_hits == 0:
        return "urban"
    if rural_hits >= 1 and mountain_hits == 0:
        return "rural"
    return "road"


def _token_set_for_similarity(s: str) -> Set[str]:
    toks = [_norm_text_strict(w) for w in (s or "").split()]
    out: Set[str] = set()
    for t in toks:
        if not t:
            continue
        if t in _KW_STOPWORDS:
            continue
        if len(t) < 3:
            continue
        out.add(t)
    return out


def _jaccard_similarity(a: str, b: str) -> float:
    sa = _token_set_for_similarity(a)
    sb = _token_set_for_similarity(b)
    if not sa and not sb:
        return 1.0
    union = sa | sb
    if not union:
        return 0.0
    return len(sa & sb) / float(len(union))


def _caption_alt_too_similar(caption: str, alt_text: str) -> bool:
    cap = _norm_text_strict(caption)
    alt = _norm_text_strict(alt_text)
    if not cap or not alt:
        return True
    if cap == alt:
        return True
    sim = _jaccard_similarity(cap, alt)
    if sim >= 0.86:
        return True
    cap_prefix = _first_words_key(caption, 8)
    alt_prefix = _first_words_key(alt_text, 8)
    return bool(cap_prefix and alt_prefix and cap_prefix == alt_prefix)


def _weak_token_hits(text: str) -> int:
    toks = [_norm_text_strict(t) for t in (text or "").split()]
    return sum(1 for t in toks if t in _QUALITY_WEAK_TOKENS)


def _keywords_quality_penalty(kw_list: Sequence[str], keywords_n: int) -> Tuple[int, List[str]]:
    issues: List[str] = []
    penalty = 0

    cleaned = _clean_keywords_list(list(kw_list))
    if len(cleaned) != int(keywords_n):
        penalty += 25
        issues.append(f"keywords count {len(cleaned)} != {keywords_n}")

    weak_hits = 0
    for kw in cleaned:
        kn = _norm_text_strict(kw)
        if not kn:
            continue
        for tok in kn.split():
            if tok in _KW_BANNED or tok in _QUALITY_WEAK_TOKENS:
                weak_hits += 1
                break
    if weak_hits > 0:
        add = min(20, weak_hits * 3)
        penalty += add
        issues.append(f"keywords weak/banned terms={weak_hits}")

    return penalty, issues


def _keyword_scene_mismatch_penalty(
    *,
    caption: str,
    alt_text: str,
    kw_list: Sequence[str],
    folder: str = "",
    subject: str = "",
    location: str = "",
) -> Tuple[int, List[str]]:
    issues: List[str] = []
    penalty = 0

    if _visual_nature_without_urban(caption, alt_text):
        urban_kw_hits = 0
        for kw in _clean_keywords_list(kw_list):
            parts = set(_norm_text_strict(kw).split())
            if parts & _URBAN_KEYWORD_TERMS:
                urban_kw_hits += 1

        if urban_kw_hits >= 3:
            penalty += min(22, 8 + urban_kw_hits * 2)
            issues.append(f"keywords urban mismatch={urban_kw_hits}")

    expected = _scene_expected_mode(folder, subject, location)
    context_text = _norm_text_strict(f"{folder} {subject} {location}")
    context_tokens = set(context_text.split())

    nature_mismatch_hits = 0
    urban_mismatch_hits = 0
    for kw in _clean_keywords_list(kw_list):
        kn = _norm_text_strict(kw)
        if not kn:
            continue
        if expected in {"urban", "road"} and _is_strong_nature_keyword(kn):
            if not _keyword_matches_context(kn, context_text, context_tokens):
                nature_mismatch_hits += 1
        if expected in {"mountain", "nature", "rural"} and _is_urban_keyword(kn):
            if not _keyword_matches_context(kn, context_text, context_tokens):
                urban_mismatch_hits += 1

    if nature_mismatch_hits >= 2:
        penalty += min(28, 8 + nature_mismatch_hits * 4)
        issues.append(f"keywords nature mismatch={nature_mismatch_hits}")
    if urban_mismatch_hits >= 2:
        penalty += min(24, 8 + urban_mismatch_hits * 3)
        issues.append(f"keywords urban mismatch context={urban_mismatch_hits}")

    return penalty, issues


def _payload_quality_score(
    *,
    caption: str,
    alt_text: str,
    kw_list: Sequence[str],
    keywords_n: int,
    folder: str = "",
    subject: str = "",
    location: str = "",
) -> Tuple[int, List[str]]:
    score = 100
    issues: List[str] = []

    cap_wc = _word_count(caption)
    alt_wc = _word_count(alt_text)

    if not _caption_not_garbage(caption):
        score -= 35
        issues.append("caption garbage")
    if _caption_style_bad(caption):
        score -= 18
        issues.append("caption style")
    if cap_wc < 8 or cap_wc > 24:
        score -= 12
        issues.append(f"caption words={cap_wc}")
    if not _has_visual_detail(caption, min_words=8):
        score -= 16
        issues.append("caption detail")
    if _contains_uncertainty(caption):
        score -= 20
        issues.append("caption uncertainty")
    if _has_repetition_artifact(caption):
        score -= 25
        issues.append("caption repetition")
    if _has_low_quality_phrase(caption):
        score -= 20
        issues.append("caption low-quality phrase")
    cap_weak_hits = _weak_token_hits(caption)
    if cap_weak_hits >= 3:
        score -= min(10, cap_weak_hits * 2)
        issues.append("caption generic wording")

    if not _alt_not_garbage(alt_text):
        score -= 32
        issues.append("alt garbage")
    if _alt_style_bad(alt_text):
        score -= 18
        issues.append("alt style")
    if not _alt_word_count_ok(alt_text):
        score -= 20
        issues.append(f"alt words={alt_wc}")
    if not _has_visual_detail(alt_text, min_words=9):
        score -= 16
        issues.append("alt detail")
    if _contains_uncertainty(alt_text):
        score -= 20
        issues.append("alt uncertainty")
    if _has_repetition_artifact(alt_text):
        score -= 25
        issues.append("alt repetition")
    if _has_low_quality_phrase(alt_text):
        score -= 20
        issues.append("alt low-quality phrase")
    alt_weak_hits = _weak_token_hits(alt_text)
    if alt_weak_hits >= 3:
        score -= min(10, alt_weak_hits * 2)
        issues.append("alt generic wording")

    if _caption_alt_too_similar(caption, alt_text):
        score -= 25
        issues.append("caption-alt similarity")
    if _caption_alt_scene_conflict(caption, alt_text):
        score -= 22
        issues.append("caption-alt scene conflict")

    kind_now = _infer_subject_kind(folder, subject)
    if kind_now == "vehicle":
        mode = _vehicle_scene_mode(folder, subject, location)
        cap_mtn, cap_urban, _ = _scene_flags(caption)
        alt_mtn, alt_urban, _ = _scene_flags(alt_text)
        if mode == "urban" and (cap_mtn or alt_mtn):
            score -= 24
            issues.append("vehicle urban context mismatch")
        elif mode == "mountain" and cap_urban and alt_urban:
            score -= 18
            issues.append("vehicle mountain context mismatch")
    elif kind_now == "wildlife":
        subj_low = _norm_text_strict(subject)
        cap_alt = _norm_text_strict(f"{caption} {alt_text}")
        anchors: List[str] = []
        for a in (
            "prairie dog",
            "ground squirrel",
            "squirrel",
            "hawk",
            "bird",
            "elk",
            "deer",
            "rabbit",
            "fox",
            "coyote",
            "bear",
            "moose",
            "bison",
            "rodent",
            "wildlife",
            "animal",
        ):
            if a in subj_low:
                anchors.append(a)
        if anchors and not any(a in cap_alt for a in anchors):
            score -= 20
            issues.append("wildlife subject missing")

    kw_penalty, kw_issues = _keywords_quality_penalty(kw_list, keywords_n)
    score -= kw_penalty
    issues.extend(kw_issues)

    scene_penalty, scene_issues = _keyword_scene_mismatch_penalty(
        caption=caption,
        alt_text=alt_text,
        kw_list=kw_list,
        folder=folder,
        subject=subject,
        location=location,
    )
    score -= scene_penalty
    issues.extend(scene_issues)

    if score < 0:
        score = 0
    return score, issues


def _has_visual_detail(sentence: str, *, min_words: int) -> bool:
    txt = _norm_text(sentence)
    if _word_count(txt) < min_words:
        return False
    markers = (" with ", " in ", " on ", " under ", " near ", " against ", " beside ", " background")
    if any(m in f" {txt} " for m in markers):
        return True
    return _word_count(txt) >= (min_words + 3)


def _clean_location(location: str) -> str:
    loc = _clean_phrase(location)
    if not loc:
        return ""
    low = _norm_text_strict(loc)
    if not low:
        return ""

    words = [w for w in low.split() if w]
    if not words:
        return ""

    bad_hits = sum(1 for w in words if w in _LOCATION_BAD_TOKENS)
    good_hits = sum(1 for w in words if w in _LOCATION_GOOD_HINTS)
    if low in _KNOWN_LOCATION_PHRASES and "photography" not in words:
        good_hits += 2
    if _KNOWN_LOCATION_TOKENS:
        good_hits += sum(1 for w in words if w in _KNOWN_LOCATION_TOKENS)

    if bad_hits > 0 and good_hits == 0:
        return ""
    if "photography" in words and bad_hits >= 1 and good_hits <= 1:
        return ""
    if bad_hits >= max(2, (len(words) // 2) + 1) and good_hits <= 1:
        return ""
    if len(words) > 8 and good_hits == 0:
        return ""

    return loc


def _strip_leading_article(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    return re.sub(r"^(?:a|an|the)\s+", "", t, flags=re.IGNORECASE).strip()


def _pretty_place_name(raw: str) -> str:
    txt = _norm_text_strict(raw)
    if not txt:
        return ""
    return " ".join([w.capitalize() for w in txt.split()])


def _named_place_phrase(folder: str, subject: str, location: str) -> str:
    phrases = _extract_phrase_keywords(folder, subject, location, "")
    if not phrases:
        return ""

    for p in phrases:
        if any(x in p for x in ("national park", "state park", "national forest", "national monument", "road", "street", "avenue", "park", "lake", "river", "downtown", "city", "district", "airport", "harbor")):
            return _pretty_place_name(p)
    return ""


def _enrich_location(location: str, folder: str, subject: str) -> str:
    loc = _clean_location(location)
    place = _named_place_phrase(folder, subject, loc)
    if not place:
        return loc

    low_loc = _norm_text_strict(loc)
    low_place = _norm_text_strict(place)
    if low_place and low_place in low_loc:
        return loc
    if not loc:
        return place
    if low_loc.startswith(low_place):
        return loc
    return f"{place}, {loc}"


def _subject_phrase(subject: str) -> str:
    s = _clean_phrase(subject)
    if not s:
        return "subject"
    toks: List[str] = []
    for t in re.split(r"[\s]+", s):
        n = _norm_text_strict(t)
        if not n:
            continue
        if n in _KW_BANNED or n in _KW_STOPWORDS:
            continue
        if n in {"canon", "eos", "r5", "mark", "ii", "iii", "iv", "v"}:
            continue
        if n.isdigit():
            continue
        toks.append(n)
    if not toks:
        return "subject"
    return " ".join(toks[:5])


def _subject_label(folder: str, subject: str) -> str:
    kind = _infer_subject_kind(folder, subject)
    toks = [_norm_text_strict(x) for x in _clean_phrase(subject).split()]
    toks = [t for t in toks if t and t not in _KW_STOPWORDS and t not in _KW_BANNED]
    ts = set(toks)

    if kind == "vehicle":
        if "semi" in ts and "truck" in ts:
            return "a semi truck"
        if "school" in ts and "bus" in ts:
            return "a school bus"
        if "jeep" in ts:
            return "a jeep"
        if "truck" in ts:
            return "a truck"
        if "bus" in ts:
            return "a bus"
        if "suv" in ts:
            return "an SUV"
        if "car" in ts:
            return "a car"
        return "a vehicle"

    if kind == "aviation":
        if "helicopter" in ts:
            return "a helicopter"
        if "boeing" in ts:
            return "a boeing aircraft"
        if "airbus" in ts:
            return "an airbus aircraft"
        if "jet" in ts:
            return "a passenger jet"
        if "aircraft" in ts or "airplane" in ts or "plane" in ts:
            return "an aircraft"
        return "an aviation subject"

    if kind == "wildlife":
        if "prairie" in ts and "dog" in ts:
            return "a prairie dog"
        if "ground" in ts and "squirrel" in ts:
            return "a ground squirrel"
        if "squirrel" in ts:
            return "a squirrel"
        if "hawk" in ts:
            return "a hawk"
        if "elk" in ts:
            return "an elk"
        if "deer" in ts:
            return "a deer"
        if "rabbit" in ts or "hare" in ts:
            return "a rabbit"
        if "fox" in ts:
            return "a fox"
        if "coyote" in ts:
            return "a coyote"
        if "bear" in ts:
            return "a bear"
        if "bison" in ts:
            return "a bison"
        if "bird" in ts or "birds" in ts:
            return "a bird"
        return "a wildlife subject"

    if kind == "structure":
        if "silos" in ts or "silo" in ts:
            return "grain silos"
        if "oil" in ts and "field" in ts:
            return "an oil field"
        if "facility" in ts:
            return "an industrial facility"
        return "industrial structures"

    if kind == "glassball":
        return "a glass ball"

    if kind == "macro":
        if "flower" in ts or "blossom" in ts:
            return "a flower close-up"
        if "insect" in ts or "bee" in ts or "butterfly" in ts:
            return "an insect close-up"
        if "spider" in ts:
            return "a spider close-up"
        if "leaf" in ts:
            return "a leaf macro detail"
        if "texture" in ts:
            return "a textured surface close-up"
        return "a macro close-up"

    if kind == "urban":
        if "skyline" in ts:
            return "a city skyline"
        if "street" in ts:
            return "an urban street scene"
        if "bridge" in ts:
            return "a city bridge"
        return "an urban scene"

    if kind == "architecture":
        if "bridge" in ts:
            return "a bridge structure"
        if "tower" in ts:
            return "a tower"
        if "building" in ts or "buildings" in ts:
            return "an architectural building"
        if "cabin" in ts:
            return "a cabin"
        return "an architectural structure"

    if kind == "waterscape":
        if "waterfall" in ts:
            return "a waterfall"
        if "river" in ts:
            return "a river scene"
        if "ocean" in ts or "sea" in ts:
            return "a coastal waterscape"
        if "lake" in ts:
            return "a lake scene"
        return "a waterscape"

    if kind == "desert":
        if "canyon" in ts:
            return "a canyon landscape"
        if "mesa" in ts or "butte" in ts:
            return "a desert rock formation"
        return "a desert landscape"

    if kind == "night":
        if "skyline" in ts:
            return "a nighttime skyline"
        if "stars" in ts or "milky" in ts:
            return "a night sky scene"
        return "a nighttime scene"

    if kind == "landscape":
        if "trail" in ts and "road" in ts:
            return "a mountain road"
        if "lake" in ts:
            return "a lake"
        if "mountain" in ts:
            return "a mountain landscape"
        if "forest" in ts:
            return "a forest landscape"
        if "rural" in ts:
            return "a rural landscape"
        return "a natural landscape"

    return "the scene"


def _caption_style_bad(caption: str) -> bool:
    txt = _norm_text(caption)
    if not txt:
        return True
    wc = _word_count(txt)
    if wc < 8 or wc > 24:
        return True
    if txt.count(" with ") > 1:
        return True
    if txt.count(" in ") > 2:
        return True
    if txt.count(",") > 2:
        return True
    if re.search(r"\b(with|in)\b[^.]{0,28}\b\1\b", txt):
        return True
    if re.search(r"\bfeatures a [a-z ]{1,48} that\b", txt):
        return True
    if re.search(r",\s*\.$", txt):
        return True
    if any(p in txt for p in ("distant context", "environmental context", "foreground depth", "outdoor scenic frame")):
        return True
    if re.search(r"\b(captured|shown|appears)\s+with\b", txt):
        return True
    return False


def _alt_style_bad(alt_text: str) -> bool:
    txt = _norm_text(alt_text)
    if not txt:
        return True
    wc = _word_count(txt)
    if wc < 10 or wc > 18:
        return True
    if txt.count(" with ") > 1:
        return True
    if ". " in txt:
        return True
    if re.search(r"\b(with|in|on|at|to|for|by|under)\.?$", txt):
        return True
    if re.search(r"\b(with|in)\b[^.]{0,24}\b\1\b", txt):
        return True
    if re.search(r",\s*\.$", txt):
        return True
    if txt.startswith("open terrain view of ") or txt.startswith("open-terrain view of "):
        return True
    if txt.startswith("mountain view of mountain road"):
        return True
    if any(p in txt for p in ("distant context", "environmental context", "outdoor scenic frame", "stable.")):
        return True
    return False


def _detect_series_key(folder: str, subject: str, file_name: str) -> Tuple[str, int]:
    stem = Path(file_name or "").stem
    seq_no = 0
    if stem:
        m = _SEQ_SUFFIX_RE.search(stem)
        if m:
            try:
                seq_no = int(m.group(1))
            except Exception:
                seq_no = 0
            stem = _SEQ_SUFFIX_RE.sub("", stem).strip("_- ")

    tokens = []
    for t in re.split(r"[_\-\s]+", stem):
        n = _norm_text_strict(t)
        if not n:
            continue
        if n in _KW_BANNED or n in _KW_STOPWORDS:
            continue
        if n in {"canon", "eos", "r5", "mark", "ii", "iii", "iv", "v"}:
            continue
        if n.isdigit():
            continue
        tokens.append(n)

    file_sig = " ".join(tokens[:14])
    key = f"{_norm_text_strict(folder)}|{_norm_text_strict(subject)}|{_norm_text_strict(file_sig)}"
    return key, seq_no

def _alt_word_count_ok(alt_text: str) -> bool:
    words = [w for w in (alt_text or "").strip().split() if w.strip()]
    return 10 <= len(words) <= 18


def _caption_not_garbage(caption: str) -> bool:
    cap = _norm_text_strict(caption)
    if not cap:
        return False
    if _has_low_quality_phrase(caption):
        return False
    if _has_repetition_artifact(cap):
        return False
    if _contains_uncertainty(cap):
        return False
    for bp in _BAD_PHRASES:
        if bp in cap:
            return False
    bad_starts = (
        "this image",
        "the frame shows",
        "in this scene",
        "a clear view presents",
        "from a side angle",
        "a wide view shows",
    )
    if any(cap.startswith(bs) for bs in bad_starts):
        return False
    # too generic
    if cap in {"a rural landscape.", "a rural landscape", "a landscape.", "a landscape"}:
        return False
    return True


def _alt_not_garbage(alt_text: str) -> bool:
    alt = _norm_text_strict(alt_text)
    if not alt:
        return False
    if _has_low_quality_phrase(alt_text):
        return False
    if _has_repetition_artifact(alt):
        return False
    if _contains_uncertainty(alt):
        return False
    for bp in _BAD_PHRASES:
        if bp in alt:
            return False
    return True


def _kw_signature(keywords: Sequence[str], top_n: int = 0) -> str:
    cleaned = [_norm_text_strict(k) for k in keywords if _norm_text_strict(k)]
    cleaned = sorted(set(cleaned))
    if top_n and top_n > 0:
        cleaned = cleaned[: max(1, top_n)]
    return "|".join(cleaned)


def _clean_phrase(s: str) -> str:
    s = (s or "").replace("_", " ").replace("-", " ").strip()
    s = _WS_RE.sub(" ", s)
    return s


def _stable_seed(*parts: str) -> int:
    raw = "||".join([_norm_text(p) for p in parts if p is not None])
    if not raw:
        return 1
    hx = hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()
    return int(hx[:8], 16)


def _pick_from_pool(pool: Sequence[str], *parts: str) -> str:
    if not pool:
        return ""
    seed = _stable_seed(*[str(p) for p in parts])
    return pool[seed % len(pool)]


def _word_count(s: str) -> int:
    return len([w for w in (s or "").split() if w.strip()])


def _infer_setting_phrase(folder: str, subject: str) -> str:
    low = _norm_text_strict(f"{folder} {subject}")

    if any(x in low for x in ("macro", "closeup", "close up", "flower", "insect", "spider", "texture")):
        return "in a close-up composition with shallow depth cues"
    if any(x in low for x in ("car", "jeep", "truck", "suv", "vehicle", "bus", "van", "road")):
        return "on a road with nearby surroundings"
    if any(x in low for x in ("industrial", "silo", "factory", "plant", "facility", "warehouse")):
        return "at an industrial site with surrounding structures"
    if any(x in low for x in ("city", "urban", "downtown", "skyline", "street", "buildings")):
        return "in an urban setting with built surroundings"
    if any(x in low for x in ("bridge", "tower", "architecture", "facade", "cabin")):
        return "with structural elements and surrounding context"
    if any(x in low for x in ("river", "waterfall", "ocean", "sea", "coast", "shore")):
        return "with visible water features and surrounding terrain"
    if any(x in low for x in ("desert", "canyon", "mesa", "butte", "dunes", "arid")):
        return "in an arid landscape with rock and open sky"
    if any(x in low for x in ("night", "dusk", "dawn", "sunset", "stars", "milky way")):
        return "under low-light conditions with visible scene detail"
    if any(x in low for x in ("mountain", "lake", "river", "forest", "valley", "landscape", "hills")):
        return "with terrain and sky in the background"
    return "in an outdoor setting with visible background detail"


def _infer_subject_kind(folder: str, subject: str) -> str:
    folder_display = _FOLDER_MAP_BY_KEY.get(str(folder or "").strip().lower(), "")
    low = _norm_text_strict(f"{folder} {folder_display} {subject}")
    if any(x in low for x in ("glassball", "glass ball", "lensball", "crystal ball", "crystalball")):
        return "glassball"
    if any(x in low for x in ("macro", "closeup", "close up", "flower", "petal", "insect", "bee", "butterfly", "spider", "texture", "droplet")):
        return "macro"
    if any(x in low for x in _AVIATION_HINTS):
        return "aviation"
    if any(x in low for x in ("car", "jeep", "truck", "suv", "vehicle", "bus", "van")):
        return "vehicle"
    if (
        "wildlife" in low
        or "animal" in low
        or any(x in low for x in _WILDLIFE_BIRD_HINTS)
        or any(x in low for x in _WILDLIFE_MAMMAL_HINTS)
    ):
        return "wildlife"
    if any(x in low for x in ("industrial", "silo", "factory", "facility", "warehouse", "oil")):
        return "structure"
    if any(x in low for x in ("city", "urban", "downtown", "skyline", "town", "street")):
        return "urban"
    if any(x in low for x in ("architecture", "architectural", "building", "bridge", "tower", "facade", "cabin")):
        return "architecture"
    if any(x in low for x in ("waterfall", "river", "ocean", "sea", "coast", "shore", "shoreline")):
        return "waterscape"
    if any(x in low for x in ("desert", "canyon", "mesa", "butte", "dunes", "arid")):
        return "desert"
    if any(x in low for x in ("night", "dusk", "dawn", "sunset", "sunrise", "stars", "milky", "twilight")):
        return "night"
    if any(x in low for x in ("mountain", "lake", "river", "forest", "landscape", "valley", "ridge")):
        return "landscape"
    return "general"


def _trim_or_pad_alt(alt_text: str, min_words: int = 10, max_words: int = 18) -> str:
    core = re.sub(r"[.!?]+", " ", (alt_text or "")).strip()
    words = [w for w in core.split() if w.strip()]
    if len(words) > max_words:
        words = words[:max_words]

    trailing_bad = {
        "with", "and", "or", "in", "on", "at", "of", "to", "for", "by", "from", "under", "near",
        "against", "around", "through", "without", "into", "over", "while", "during", "before",
        "after", "including", "featuring", "the", "a", "an",
    }
    while words and _norm_text_strict(words[-1]) in trailing_bad:
        words.pop()

    out = " ".join(words).strip()
    return _sanitize_sentence(out)


def _trim_caption(caption: str, max_words: int = 24) -> str:
    core = re.sub(r"[.!?]+", " ", (caption or "")).strip()
    words = [w for w in core.split() if w.strip()]
    if len(words) > max_words:
        words = words[:max_words]

    trailing_bad = {
        "with", "and", "or", "in", "on", "at", "of", "to", "for", "by", "from", "under", "near",
        "against", "around", "through", "without", "into", "over", "while", "during", "before",
        "after", "including", "featuring", "as", "the", "a", "an",
    }
    while words and _norm_text_strict(words[-1]) in trailing_bad:
        words.pop()

    return _sanitize_sentence(" ".join(words).strip())


def _fallback_caption_candidate(
    *,
    folder: str,
    subject: str,
    location: str,
    variant: int,
    sequence_no: int = 0,
) -> str:
    subj = _subject_label(folder, subject)
    subj_bare = _strip_leading_article(subj) or subj
    subj_cap = subj[:1].upper() + subj[1:] if subj else "Scene"
    loc = _enrich_location(location, folder, subject)
    kind = _infer_subject_kind(folder, subject)
    vehicle_mode = _vehicle_scene_mode(folder, subject, location) if kind == "vehicle" else "road"
    wildlife_mode = _wildlife_mode(folder, subject) if kind == "wildlife" else "general"
    subj_tokens = set(_norm_text_strict(subj_bare).split())
    plural_subjects = {"grain silos", "industrial structures"}
    is_plural = _norm_text_strict(subj_bare) in plural_subjects

    bg_by_kind: Dict[str, Sequence[str]] = {
        "vehicle": (
            "roadside trees",
            "nearby buildings",
            "a row of houses",
            "utility poles near the roadway",
            "street lights and sidewalks",
            "lane markings and curb lines",
            "road signs and shoulder markings",
            "an intersection in the distance",
            "a parking area and side street",
            "mixed roadside vegetation",
            "suburban blocks behind the road",
            "a broad roadway corridor",
            "traffic signals and street lanes",
        ),
        "wildlife": (
            "short grass and exposed soil",
            "low vegetation and field cover",
            "open habitat with natural ground texture",
            "nearby plants and dry grass",
            "light cloud cover",
            "field terrain with habitat depth",
            "earth and grass texture in the foreground",
            "open background with low brush",
            "ground-level habitat detail",
            "a broad field backdrop",
            "sparse natural cover",
            "outdoor habitat context",
        ),
        "aviation": (
            "open sky and cloud layers",
            "airport approach corridor",
            "runway environment in the distance",
            "clear sky with soft cloud cover",
            "high-altitude backdrop",
            "airspace over an urban edge",
            "flight-path perspective",
            "background cloud texture",
            "daylight sky contrast",
            "open atmosphere detail",
            "approach path context",
            "airfield surroundings",
        ),
        "structure": (
            "open ground",
            "distant hills",
            "service roads",
            "adjacent industrial buildings",
            "utility lines",
            "fenced work areas",
            "stacked metal structures",
            "dry terrain",
            "a broad sky backdrop",
            "yard infrastructure",
            "nearby equipment",
            "site access lanes",
        ),
        "urban": (
            "city blocks and side streets",
            "mid-rise buildings",
            "street lights and sidewalks",
            "downtown facades",
            "traffic lanes and crosswalk markings",
            "an urban skyline",
            "intersections and storefronts",
            "dense city architecture",
            "street signage and buildings",
            "glass and concrete towers",
            "a broad city corridor",
            "urban street depth",
        ),
        "architecture": (
            "structural lines and facade detail",
            "adjacent buildings",
            "street-level context",
            "urban surroundings",
            "geometric rooflines",
            "window and wall textures",
            "nearby landscaping and pathways",
            "foreground pavement detail",
            "an open sky backdrop",
            "surrounding built forms",
            "architectural massing",
            "structural edges and shadows",
        ),
        "macro": (
            "soft background blur",
            "fine texture detail",
            "tight focal depth",
            "subtle color gradients",
            "foreground subject isolation",
            "shallow depth separation",
            "micro-level surface texture",
            "edge detail in focus",
            "small-scale natural forms",
            "selective focus cues",
            "highlight and shadow contrast",
            "close-range composition",
        ),
        "waterscape": (
            "shoreline terrain",
            "surface reflections",
            "water ripples",
            "distant shoreline features",
            "clouds mirrored on water",
            "rocky water edges",
            "nearby tree reflections",
            "a broad water surface",
            "coastal contours",
            "riverbank detail",
            "wave texture and horizon",
            "water and sky contrast",
        ),
        "desert": (
            "layered sandstone formations",
            "dry open terrain",
            "arid ridgelines",
            "rocky plateaus",
            "eroded canyon walls",
            "distant desert hills",
            "sparse vegetation",
            "wide sky over rock forms",
            "desert ground texture",
            "mesa contours",
            "weathered stone surfaces",
            "sunlit arid backdrop",
        ),
        "night": (
            "low-light sky tones",
            "city lights in the distance",
            "evening silhouettes",
            "twilight gradients",
            "nighttime horizon glow",
            "dark foreground contours",
            "illuminated street elements",
            "soft artificial lighting",
            "moonlit terrain",
            "after-sunset contrast",
            "dim skyline detail",
            "night atmosphere",
        ),
        "glassball": (
            "mirrored mountains and trees",
            "a reflected road scene",
            "inverted park terrain",
            "reflected autumn foliage",
            "distorted ridgelines in reflection",
            "a mirrored lake and forest edge",
            "reflected sky and mountain slopes",
            "a reflective trail scene",
            "mirrored roadside textures",
            "inverted clouds and terrain",
            "a crisp landscape reflection",
            "reflected natural contours",
        ),
        "landscape": (
            "distant mountains",
            "forest and ridgeline terrain",
            "rolling hills",
            "a broad valley floor",
            "rocky slopes and sparse trees",
            "a lake and wooded shoreline",
            "autumn foliage",
            "clouds above the ridge",
            "layered terrain",
            "open sky and foothills",
            "mixed forest and meadow",
            "a rugged mountain backdrop",
        ),
        "general": (
            "open sky",
            "distant terrain",
            "nearby trees",
            "rolling hills",
            "a broad natural backdrop",
            "surrounding landscape detail",
            "a visible horizon",
            "mixed outdoor terrain",
            "distant ridges",
            "natural ground texture",
            "wide background terrain",
            "clear daylight conditions",
        ),
    }

    if kind == "vehicle":
        if vehicle_mode == "mountain":
            acts = (
                "travels along a mountain road",
                "moves through a high elevation route",
                "continues across a ridgeline roadway",
                "passes through winding mountain terrain",
                "follows a road between forested slopes",
                "drives along a scenic upland corridor",
                "moves through a mountain pass section",
                "travels along a trail-side roadway",
                "heads through a mountain park route",
                "drives across elevated terrain",
                "continues through alpine roadside terrain",
                "follows a road with surrounding slopes",
            )
        elif vehicle_mode == "urban":
            acts = (
                "drives along a city road",
                "moves through an urban street corridor",
                "travels across a marked city lane",
                "passes through a suburban road segment",
                "continues along a paved street section",
                "heads through a neighborhood roadway",
                "rolls past buildings and side streets",
                "follows a road through a built area",
                "moves across an intersection approach",
                "drives through a city traffic lane",
                "passes along a suburban street corridor",
                "travels across a roadway in town",
            )
        elif vehicle_mode == "rural":
            acts = (
                "drives along a rural road",
                "moves through open roadside terrain",
                "travels on a two lane country route",
                "continues along a lightly developed road",
                "passes through a quiet rural corridor",
                "heads along a paved county road",
                "rolls past open fields and fences",
                "follows a road through broad open ground",
                "moves across a long road stretch",
                "drives through sparse roadside surroundings",
                "passes along an open country roadway",
                "travels through a rural travel lane",
            )
        else:
            acts = (
                "drives along a paved road",
                "moves through a marked roadway",
                "travels on a two lane route",
                "continues along a visible road section",
                "passes through a roadside corridor",
                "heads along a travel lane",
                "rolls past roadside surroundings",
                "follows a road through open space",
                "moves across a clear road stretch",
                "drives through a road segment",
                "passes along a paved travel route",
                "travels through roadway traffic flow",
            )
    elif kind == "aviation":
        acts = (
            "is captured in flight",
            "flies through open sky",
            "is shown on approach with landing gear visible",
            "moves along a clear flight path",
            "appears in an overhead flight angle",
            "crosses the frame with wings fully extended",
            "is seen against cloud cover",
            "holds a stable flight profile",
            "passes through an approach corridor",
            "is framed in midair under daylight",
        )
    elif kind == "wildlife":
        if wildlife_mode == "bird":
            acts = (
                "is perched above the ground",
                "rests on a visible perch",
                "holds a perch above nearby terrain",
                "remains perched with a side profile",
                "is perched near open ground",
                "stays perched against the skyline",
                "is perched near distant trees",
                "holds position on an exposed perch",
                "is perched with folded wings",
                "rests in natural habitat context",
            )
        elif wildlife_mode == "mammal":
            acts = (
                "stands on open ground",
                "moves through short grass and soil",
                "rests near a visible burrow area",
                "holds position in a field habitat",
                "is shown at ground level in natural cover",
                "forages across open habitat terrain",
                "appears in profile above grassy ground",
                "stands near low plants and earth texture",
                "moves through a natural field setting",
                "holds a ground-level posture in habitat",
            )
        else:
            acts = (
                "is shown in natural habitat",
                "appears at ground level outdoors",
                "holds position in open natural cover",
                "remains visible in habitat context",
                "stands in a field environment",
                "is seen with surrounding natural terrain",
                "appears in profile within outdoor habitat",
                "is captured in open habitat conditions",
                "holds a clear posture in natural surroundings",
                "is shown within field and vegetation detail",
            )
    elif kind == "structure":
        if is_plural:
            acts = (
                "stand near service roads",
                "rise above open ground",
                "sit beside industrial yard space",
                "appear across a broad site area",
                "stand in a fenced work zone",
                "rise with utility lines nearby",
                "sit within a visible industrial block",
                "stand against distant hills",
                "appear beside adjacent structures",
                "rise across dry site terrain",
                "stand near access lanes",
                "sit in an open industrial setting",
            )
        else:
            acts = (
                "stands near service roads",
                "rises above open ground",
                "sits beside industrial yard space",
                "appears across a broad site area",
                "stands in a fenced work zone",
                "rises with utility lines nearby",
                "sits within a visible industrial block",
                "stands against distant hills",
                "appears beside adjacent structures",
                "rises across dry site terrain",
                "stands near access lanes",
                "sits in an open industrial setting",
            )
    elif kind == "urban":
        acts = (
            "runs along a main street corridor",
            "shows storefronts and sidewalks",
            "passes through a town-center block",
            "includes mixed street and building detail",
            "follows a visible street segment",
            "shows parked vehicles near shopfronts",
            "is framed by street-facing buildings",
            "crosses an intersection approach",
            "shows architectural detail along the street",
            "includes a built roadside setting",
            "shows a town street with urban elements",
            "extends through a developed neighborhood",
        )
    elif kind == "architecture":
        acts = (
            "shows strong architectural lines",
            "stands with defined structural geometry",
            "is framed by clean facade detail",
            "sits within an architectural streetscape",
            "presents distinct exterior form",
            "shows layered building structure",
            "appears with visible design elements",
            "is captured with geometric perspective",
            "reveals exterior structural detail",
            "shows a clear built-form profile",
            "stands in a structured urban context",
            "appears with pronounced facade texture",
        )
    elif kind == "macro":
        acts = (
            "is shown in close-up focus",
            "fills the frame in macro detail",
            "shows selective focus",
            "is captured at close range",
            "shows fine surface texture",
            "is isolated with shallow focus",
            "reveals micro-level detail",
            "appears in a tight close-up composition",
            "is framed by narrow depth of field",
            "shows crisp close-up texture",
            "is presented as a macro subject",
            "reveals small-scale detail",
        )
    elif kind == "waterscape":
        acts = (
            "extends across a calm water surface",
            "shows water texture and shoreline detail",
            "reflects surrounding terrain and sky",
            "spreads across open water and shoreline",
            "runs along a visible water edge",
            "shows ripples under open sky",
            "rests beside a rocky shoreline",
            "opens across a broad waterscape",
            "captures mirrored sky on water",
            "reveals layered shoreline contours",
            "shows water movement and reflection",
            "extends toward distant waterline features",
        )
    elif kind == "desert":
        acts = (
            "stretches across arid terrain",
            "shows layered desert rock formations",
            "extends toward distant canyon walls",
            "reveals weathered sandstone contours",
            "opens across dry plateau ground",
            "shows rugged desert topography",
            "spans a broad arid landscape",
            "is framed by desert rock structure",
            "shows sparse vegetation in dry terrain",
            "extends through sunlit canyon terrain",
            "reveals open desert horizon",
            "shows texture across rock and sand",
        )
    elif kind == "night":
        acts = (
            "appears under low-light conditions",
            "is shown against evening sky tones",
            "is framed by nighttime lighting",
            "sits within a dusk atmosphere",
            "is visible in twilight light",
            "shows contrast between lights and shadow",
            "appears against a darkening horizon",
            "is captured after sunset",
            "shows depth in nighttime conditions",
            "is presented in evening light",
            "appears with dim ambient light",
            "is framed by night sky tones",
        )
    elif kind == "glassball":
        acts = (
            "reflects a mountain scene",
            "shows a mirrored landscape view",
            "captures reflected trees and sky",
            "contains an inverted outdoor reflection",
            "reveals mirrored terrain details",
            "shows a reflected trail corridor",
            "captures nearby peaks in reflection",
            "reveals a reflected road and trees",
            "shows optical distortion of the landscape",
            "holds a clear mirrored valley view",
            "reflects autumn colors and terrain",
            "shows a crisp reflected ridgeline",
        )
    elif kind == "landscape":
        if "road" in subj_tokens:
            acts = (
                "runs through mountain terrain",
                "curves through autumn scenery",
                "cuts across the landscape",
                "winds through rocky slopes",
                "extends across a high elevation route",
                "leads through forested terrain",
                "continues across open mountain ground",
                "traces ridgeline terrain",
                "passes through mixed forest and slopes",
                "stretches across upland terrain",
                "follows a route through mountain scenery",
                "continues toward higher terrain",
            )
        elif "lake" in subj_tokens:
            acts = (
                "sits beneath surrounding peaks",
                "reflects nearby mountains and trees",
                "lies within a mountain basin",
                "extends across a calm water surface",
                "spreads across a broad alpine setting",
                "rests below rolling hills",
                "shows still water near the shoreline",
                "lies between trees and distant ridges",
                "shows a calm shoreline and open water",
                "rests near forested slopes",
                "stretches below distant ridgelines",
                "sits in a natural mountain setting",
            )
        else:
            acts = (
                "spreads across mountain terrain",
                "stretches toward distant ridges",
                "extends through rolling hills",
                "opens across a broad valley",
                "lies beneath distant peaks",
                "shows layered terrain and trees",
                "covers a broad natural setting",
                "continues toward a ridgeline",
                "extends across mixed forest and slopes",
                "shows open terrain below mountains",
                "spans a rugged outdoor scene",
                "stretches across the valley floor",
            )
    else:
        acts = (
            "stands within an outdoor setting",
            "appears in open terrain",
            "sits against a natural backdrop",
            "appears under clear daylight",
            "is positioned within surrounding landscape",
            "appears beside nearby terrain",
            "is visible against distant hills",
            "sits in a clear outdoor scene",
            "appears in a broad natural view",
            "stands near open ground and sky",
            "remains visible within outdoor terrain",
            "is framed by surrounding landscape",
        )

    seed = _stable_seed(folder, subject, loc, str(variant), str(max(0, sequence_no)))
    bg_pool = bg_by_kind.get(kind, bg_by_kind["general"])
    if kind == "vehicle" and vehicle_mode == "mountain":
        bg_pool = (
            "mountain slopes in view",
            "rolling foothills",
            "a ridgeline in the distance",
            "forest edges and open sky",
            "a broad valley backdrop",
            "roadside pines and rocky ground",
            "high terrain beyond the roadway",
            "a mountain park backdrop",
            "elevated terrain and tree cover",
            "distant peaks and road shoulder",
            "curving mountain roadside terrain",
            "upland terrain along the route",
        )
    bg = _pick_from_pool(bg_pool, folder, subject, loc, str(variant), str(max(0, sequence_no)), "caption_bg")
    act = _pick_from_pool(acts, folder, subject, loc, str(variant), str(max(0, sequence_no)), "caption_act")

    if loc:
        templates = (
            "{subj_cap} {act} with {bg} in {loc}.",
            "In {loc}, {subj} {act} with {bg}.",
            "Near {loc}, {subj} {act} with {bg}.",
            "Against {bg}, {subj} {act} in {loc}.",
            "Across {loc}, {subj} {act} with {bg}.",
            "{subj_cap} {act} while {bg} remains visible in {loc}.",
            "With {bg} in view, {subj} {act} in {loc}.",
            "{subj_cap} {act} through {loc} with {bg}.",
            "{subj_cap} {act} as {bg} frames the scene in {loc}.",
            "From {loc}, {subj} {act} against {bg}.",
        )
    else:
        templates = (
            "{subj_cap} {act} with {bg}.",
            "Against {bg}, {subj} {act}.",
            "Across the frame, {subj} {act} with {bg}.",
            "{subj_cap} {act} with {bg} in the background.",
            "{subj_cap} {act} as {bg} fills the background.",
            "{subj_cap} {act} with {bg} in view.",
            "With {bg} in the background, {subj} {act}.",
            "{subj_cap} {act} while {bg} stays in view.",
        )

    tpl = _pick_from_pool(templates, folder, subject, loc, str(variant), str(max(0, sequence_no)), "caption_tpl")
    txt = tpl.format(subj_cap=subj_cap, subj=subj, act=act, bg=bg, loc=loc)
    txt = _deawkward_sentence(txt)
    txt = _sanitize_sentence(txt)
    return _trim_caption(txt, max_words=24)


def _fallback_alt_candidate(
    *,
    folder: str,
    subject: str,
    location: str,
    variant: int,
    sequence_no: int = 0,
) -> str:
    subj = _subject_label(folder, subject)
    subj_bare = _strip_leading_article(subj) or subj
    loc = _enrich_location(location, folder, subject)
    kind = _infer_subject_kind(folder, subject)
    vehicle_mode = _vehicle_scene_mode(folder, subject, location) if kind == "vehicle" else "road"
    wildlife_mode = _wildlife_mode(folder, subject) if kind == "wildlife" else "general"

    loc_short = ""
    if loc:
        loc_head = _clean_phrase(str(loc).split(",")[0])
        head_words = [w for w in loc_head.split() if w.strip()]
        if 0 < len(head_words) <= 6:
            loc_short = " ".join(head_words)
        else:
            loc_words = [re.sub(r"[^A-Za-z0-9]", "", w) for w in _clean_phrase(loc).split()]
            loc_words = [w for w in loc_words if w]
            if 0 < len(loc_words) <= 6:
                loc_short = " ".join(loc_words[:4])

    view_prefix_by_kind: Dict[str, Sequence[str]] = {
        "vehicle": (
            "Roadside view of",
            "Street-level view of",
            "Roadway view of",
            "Highway-side view of",
            "Open-road view of",
            "Route-level view of",
            "Daylight road view of",
            "Travel-lane view of",
        ),
        "wildlife": (
            "Wildlife view of",
            "Habitat-level view of",
            "Ground-level wildlife view of",
            "Outdoor wildlife view of",
            "Natural-light wildlife view of",
            "Field view of",
            "Close wildlife view of",
            "Subject-focused wildlife view of",
        ),
        "aviation": (
            "Aviation view of",
            "In-flight view of",
            "Airborne view of",
            "Approach-path view of",
            "Aircraft-focused view of",
            "Skyward view of",
            "Flight-level view of",
            "Overhead flight view of",
        ),
        "structure": (
            "Industrial-site view of",
            "Facility view of",
            "Ground-level view of",
            "Exterior view of",
            "Site overview of",
            "Workyard view of",
            "Structural view of",
            "Utility-site view of",
        ),
        "urban": (
            "Urban view of",
            "Downtown view of",
            "City-street view of",
            "Street-level city view of",
            "Cityscape view of",
            "Metro-area view of",
            "Intersection view of",
            "City-corridor view of",
        ),
        "architecture": (
            "Architectural view of",
            "Facade view of",
            "Exterior view of",
            "Design-focused view of",
            "Structural view of",
            "Building-form view of",
            "Street-side architectural view of",
            "Urban-architecture view of",
        ),
        "macro": (
            "Macro view of",
            "Close-up view of",
            "Close-focus view of",
            "Detailed close-up of",
            "Near-field view of",
            "Shallow-focus view of",
            "Micro-scale view of",
            "Tight close-up of",
        ),
        "waterscape": (
            "Shoreline view of",
            "Water-edge view of",
            "Reflected-water view of",
            "Riverbank view of",
            "Open-water view of",
            "Coastal view of",
            "Waterline view of",
            "Surface-water view of",
        ),
        "desert": (
            "Desert view of",
            "Canyon view of",
            "Arid-landscape view of",
            "Rock-formation view of",
            "Plateau view of",
            "Sandstone terrain view of",
            "Open-desert view of",
            "Dry-terrain view of",
        ),
        "night": (
            "Night view of",
            "Twilight view of",
            "Evening-light view of",
            "Low-light view of",
            "After-sunset view of",
            "Night-sky view of",
            "City-lights view of",
            "Dusk view of",
        ),
        "glassball": (
            "Reflective-sphere view of",
            "Lensball close-up of",
            "Glass-reflection view of",
            "Optical close-up of",
            "Mirrored-sphere view of",
            "Crystal-sphere view of",
            "Refraction-focused view of",
            "Reflective close-up view of",
        ),
        "landscape": (
            "Landscape view of",
            "Wide view of",
            "Valley view of",
            "Forest-edge view of",
            "Ridge-line view of",
            "Lakeside view of",
            "Terrain view of",
            "Panoramic view of",
            "Natural view of",
            "Horizon view of",
            "Scenic ridgeline view of",
            "Park landscape view of",
            "Roadside mountain view of",
            "High-elevation view of",
            "Open-valley view of",
            "Slope-side view of",
            "Trail-corridor view of",
            "Summit-area view of",
            "Autumn highland view of",
            "Ridgeline landscape view of",
        ),
        "general": (
            "Outdoor view of",
            "Scene view of",
            "Wide view of",
            "Ground-level view of",
            "Open-air view of",
            "Context view of",
            "Daylight view of",
            "General view of",
        ),
    }

    details_by_kind: Dict[str, Sequence[str]] = {
        "vehicle": (
            "on a paved lane with roadside context",
            "moving through a marked road section",
            "with lane markings and visible pavement",
            "along a curving route with road shoulder detail",
            "near roadside signage and travel lanes",
            "with roadway markings and side-street context",
            "across a paved roadside corridor",
            "with utility poles and road surface detail",
            "on a two lane road segment",
            "with visible asphalt and roadside surroundings",
            "through an active roadway segment",
            "with clear roadway and shoulder context",
        ),
        "wildlife": (
            "in natural habitat with visible ground texture",
            "with grass and soil detail in the foreground",
            "against low vegetation and open background",
            "with field cover and natural daylight",
            "showing body profile and habitat context",
            "with surrounding plants and earth detail",
            "near short brush and open terrain",
            "with visible habitat depth and background",
            "in an outdoor habitat with clear focus",
            "with natural cover and ground detail",
            "showing subject posture within habitat",
            "with environment detail and open-air context",
        ),
        "aviation": (
            "with wings and fuselage detail against the sky",
            "showing landing gear and flight posture",
            "with cloud cover and open airspace in view",
            "with a clear flight profile in daylight",
            "showing aircraft structure and wing geometry",
            "with approach-path alignment and sky contrast",
            "with airborne perspective and cloud texture",
            "showing in-flight detail under natural light",
            "with visible flight attitude and clean sky backdrop",
            "with aircraft body detail and high-contrast sky",
        ),
        "structure": (
            "with open yard space and utility lines",
            "beside service roads and fenced ground",
            "with distant hills behind the site",
            "across an industrial block with equipment",
            "near access lanes and dry terrain",
            "with surrounding metal infrastructure",
            "beside adjacent site structures",
            "with open ground and clear sky",
            "across a broad industrial yard",
            "with nearby buildings and service lanes",
            "in a work site with visible framework",
            "near utility lines and site fencing",
        ),
        "urban": (
            "with city blocks and side streets in view",
            "along a downtown corridor with storefronts",
            "with crosswalk markings and street signs",
            "with layered storefronts and facades",
            "with sidewalk detail and road lanes",
            "with urban building lines in the background",
            "with an intersection and city depth",
            "with street-level perspective and signage",
            "with glass and concrete buildings nearby",
            "with urban street texture and perspective",
            "across a built city district",
            "with visible downtown architectural forms",
        ),
        "architecture": (
            "with facade geometry and window detail",
            "showing clean structural lines and form",
            "with surrounding urban context and scale",
            "with roofline and wall texture visible",
            "showing exterior design elements in view",
            "with perspective lines across the structure",
            "with adjacent built forms and pathways",
            "showing architectural massing and detail",
            "with strong geometric edges and shadows",
            "with visible material and facade texture",
            "showing structural profile against open sky",
            "with foreground context and built surroundings",
        ),
        "macro": (
            "with selective focus and soft background blur",
            "showing fine texture in close-range detail",
            "with shallow depth and crisp foreground focus",
            "with micro-scale surface patterns visible",
            "showing close-up texture and tonal contrast",
            "with isolated subject detail in focus",
            "showing small-form structure and texture",
            "with narrow depth and edge clarity",
            "showing subtle color transitions in close-up",
            "with pronounced texture and close framing",
            "showing macro detail and focused highlights",
            "with near-field subject isolation and blur",
        ),
        "waterscape": (
            "with shoreline contours and water reflections",
            "showing ripple texture across the surface",
            "with mirrored sky across open water",
            "with waterline detail and distant shore",
            "showing riverbank texture and water movement",
            "with reflective water and surrounding terrain",
            "showing edge detail along the shoreline",
            "with layered water surface and horizon",
            "showing coastal contours and open water",
            "with reflections of nearby landscape features",
            "showing water texture under natural light",
            "with shore detail and broad water context",
        ),
        "desert": (
            "with layered sandstone and open sky",
            "showing arid terrain and rock contours",
            "with canyon walls and dry ground texture",
            "showing weathered rock structure and depth",
            "with sparse vegetation across desert ground",
            "showing plateau edges and rugged relief",
            "with sunlit rock surfaces and shadow detail",
            "showing desert horizon and exposed geology",
            "with dry terrain and eroded formations",
            "showing cliff texture and arid backdrop",
            "with rocky forms and broad sky contrast",
            "showing open desert space and rock detail",
        ),
        "night": (
            "with low-light tones and scene contrast",
            "showing evening sky gradients and silhouette detail",
            "with city lights or horizon glow in view",
            "showing nighttime contrast and shadow depth",
            "with twilight color transitions across the sky",
            "showing after-sunset ambient lighting",
            "with dim foreground detail and lit background",
            "showing dusk atmosphere and visual depth",
            "with low-light scene texture and contour",
            "showing night sky tone and structural outline",
            "with evening illumination and dark foreground",
            "showing subdued light and scene separation",
        ),
        "glassball": (
            "showing mirrored mountains and trees",
            "with an inverted reflection of terrain",
            "reflecting road and forest detail",
            "with optical distortion across the scene",
            "showing reflected sky and ridgeline",
            "with mirrored autumn colors in glass",
            "reflecting a trail corridor and trees",
            "with reflected slopes and distant peaks",
            "showing a crisp mirrored landscape",
            "with close optical detail and reflection",
            "reflecting a valley scene in the sphere",
            "with mirrored outdoor features in focus",
        ),
        "landscape": (
            "with mixed aspen and evergreen slopes",
            "with layered ridges under open sky",
            "with roadside curves and mountain terrain",
            "with broad valley depth and ridgelines",
            "with forested slopes and exposed rock",
            "with alpine terrain and distant peaks",
            "with autumn color across the hillsides",
            "with high-elevation road and tree cover",
            "with mountain shoulders and cloud breaks",
            "with open slopes and a long horizon",
            "with winding road lines through terrain",
            "with rugged ridges and sparse trees",
            "with a valley floor and distant ridges",
            "with pine stands along mountain slopes",
            "with roadside tundra and rocky ground",
            "with switchback context and alpine backdrop",
            "with ridgeline layers and open daylight",
            "with steep terrain and forest patches",
            "with mountain contours and autumn brush",
            "with broad upland terrain and sky",
            "with distant peaks and tree-lined slopes",
            "with elevated road context and ridges",
            "with ridge-to-valley terrain contrast",
            "with mountain texture and clear atmosphere",
            "with trail-corridor terrain and tree cover",
            "with open mountain ground and ridges",
            "with hill contours and alpine depth",
            "with rolling uplands and distant rock faces",
            "with shoulder detail and mountain backdrop",
            "with terrain layers and sparse pine clusters",
        ),
        "general": (
            "with visible outdoor surroundings and terrain",
            "in clear daylight with distant backdrop",
            "with nearby trees and open horizon",
            "showing broad terrain and sky detail",
            "with mixed natural elements in view",
            "across an open outdoor setting",
            "with distant hills and foreground detail",
            "showing surrounding landscape context",
            "with natural ground texture and trees",
            "with a broad background terrain view",
            "showing clear outdoor scene detail",
            "with layered terrain and sky conditions",
        ),
    }

    templates = (
        "{prefix} {subj_bare} {detail}",
        "{prefix} {subj_bare} {detail}",
        "{prefix} {subj_bare} {detail}",
        "{prefix} {subj_bare} {detail}",
        "{prefix} {subj_bare} {detail}",
        "{subj_cap} {detail}",
        "{prefix} {subj_bare} {detail}",
        "{prefix} {subj_bare} {detail}",
    )

    seed = _stable_seed(folder, subject, loc, str(variant), str(max(0, sequence_no)))
    prefix_pool = view_prefix_by_kind.get(kind, view_prefix_by_kind["general"])
    prefix = _pick_from_pool(prefix_pool, folder, subject, loc, str(variant), str(max(0, sequence_no)), "alt_prefix")
    detail_pool = details_by_kind.get(kind, details_by_kind["general"])
    if kind == "vehicle":
        if vehicle_mode == "urban":
            detail_pool = (
                "on a paved city street with nearby buildings",
                "moving through an urban road section with lane markings",
                "with traffic lanes and neighborhood structures in view",
                "along a suburban street corridor with side roads",
                "near an intersection with visible pavement detail",
                "with road markings and residential blocks nearby",
                "across a city roadway with curb and lane context",
                "with streetlights and urban roadside detail",
                "on a local road segment with parked cars nearby",
                "with a built streetscape and open road ahead",
                "through a town roadway with clear lane guidance",
                "with paved street context and background housing",
            )
        elif vehicle_mode == "mountain":
            detail_pool = (
                "on a mountain road with ridgeline terrain in view",
                "moving through elevated roadway terrain with forest edges",
                "with road shoulder detail and distant peaks",
                "along a winding route through mountain landscape",
                "near alpine slopes and visible lane markings",
                "with mountain scenery and roadside pines",
                "across a high terrain roadway with open sky",
                "with curving road geometry through upland terrain",
                "on a scenic mountain route with distant ridges",
                "with rugged roadside terrain and paved lanes",
                "through a mountain corridor with clear road markings",
                "with elevated landscape context beyond the roadway",
            )
        elif vehicle_mode == "rural":
            detail_pool = (
                "on a rural two lane road with open fields nearby",
                "moving through open roadside terrain with sparse structures",
                "with lane markings and broad rural background",
                "along a quiet road corridor with fences and grassland",
                "near open ground with clear road surface detail",
                "with county-road context and roadside vegetation",
                "across a paved rural stretch with wide horizon",
                "with sparse roadside development and visible lanes",
                "on a country road segment with open surrounding terrain",
                "with road shoulder detail across lightly developed land",
                "through a rural roadway with open-sky backdrop",
                "with agricultural or open-land roadside context",
            )
    elif kind == "wildlife":
        if wildlife_mode == "bird":
            detail_pool = (
                "with perch detail and open sky behind the subject",
                "showing wings and body profile in natural habitat",
                "with nearby branches and clear background separation",
                "showing a perched position with habitat depth",
                "with natural-light detail across feathers and form",
                "showing wildlife posture against open background",
                "with visible habitat cover and profile detail",
                "showing subject detail in a clear outdoor setting",
            )
        elif wildlife_mode == "mammal":
            detail_pool = (
                "with short grass and soil texture around the subject",
                "showing ground-level posture in open habitat",
                "with visible burrow-area terrain and field cover",
                "showing mammal profile with natural habitat detail",
                "with low vegetation and earth texture in view",
                "showing subject behavior in a field environment",
                "with surrounding grassland and habitat depth",
                "showing clear fur and body detail at ground level",
            )
    detail = _pick_from_pool(detail_pool, folder, subject, loc, str(variant), str(max(0, sequence_no)), "alt_detail")
    if kind == "landscape":
        hint_pool = (
            "at elevation",
            "in autumn light",
            "in clear daylight",
            "under mixed cloud",
            "near the ridgeline",
            "across upland terrain",
            "in mountain weather",
            "above the valley",
            "along the pass",
            "across alpine ground",
            "in high terrain",
            "near open slopes",
        )
        hint = _pick_from_pool(hint_pool, folder, subject, loc, str(variant), str(max(0, sequence_no)), "alt_hint")
        detail = f"{hint} {detail}"
    tpl = _pick_from_pool(templates, folder, subject, loc, str(variant), str(max(0, sequence_no)), "alt_tpl")
    subj_cap = subj_bare[:1].upper() + subj_bare[1:] if subj_bare else "Subject"
    txt = tpl.format(prefix=prefix, subj_bare=subj_bare, subj_cap=subj_cap, detail=detail).rstrip(".")
    use_loc_tail = True
    if loc_short:
        loc_seed = _stable_seed(folder, subject, loc, str(variant), str(max(0, sequence_no)), "alt_loc_tail")
        if kind in {"landscape", "vehicle"} and (loc_seed % 4 == 0):
            use_loc_tail = False
    if loc_short and use_loc_tail:
        txt = f"{txt} in {loc_short}"
    txt = _deawkward_sentence(txt)
    txt = _sanitize_sentence(txt)
    return _trim_or_pad_alt(txt, min_words=10, max_words=18)


def _variant_keywords(
    *,
    kw_list: Sequence[str],
    folder: str,
    subject: str,
    location: str,
    caption: str,
    keywords_n: int,
    variant: int,
    sequence_no: int = 0,
) -> List[str]:
    base = _clean_keywords_list(kw_list)

    if len(base) != keywords_n:
        base = _fallback_keywords(folder, subject, location, caption, keywords_n)
        base = _clean_keywords_list(base)

    seen: Set[str] = set()
    out: List[str] = []
    for k in base:
        if k in seen:
            continue
        seen.add(k)
        out.append(k)

    pool = list(_fallback_keywords(folder, subject, location, caption, keywords_n + 24))
    pool.extend(_context_keyword_pool(folder, subject))
    pool.extend(_KW_VARIANT_POOL)
    pool = _clean_keywords_list(pool)

    if pool:
        start = (variant + max(0, sequence_no)) % len(pool)
        picked = ""
        for i in range(len(pool)):
            cand = pool[(start + i) % len(pool)]
            if cand not in seen:
                picked = cand
                break
        if picked:
            if out:
                out[-1] = picked
            else:
                out.append(picked)
            seen.add(picked)

    for cand in _context_keyword_pool(folder, subject) + list(_KW_VARIANT_POOL):
        c = _normalize_keyword(cand)
        if len(out) >= keywords_n:
            break
        if not c or c in seen:
            continue
        out.append(c)
        seen.add(c)

    out = _inject_precision_terms(
        kw_list=out,
        folder=folder,
        subject=subject,
        location=location,
        caption=caption,
        keywords_n=keywords_n,
    )
    out = _clean_keywords_list(out)
    out = _apply_scene_keyword_guardrails(
        kw_list=out,
        folder=folder,
        subject=subject,
        location=location,
        caption=caption,
        alt_text="",
        keywords_n=keywords_n,
    )
    out = _clean_keywords_list(out)
    return out[:keywords_n]


def _keyword_replacement_count(base: Sequence[str], cand: Sequence[str]) -> int:
    b = set(_clean_keywords_list(base))
    c = set(_clean_keywords_list(cand))
    if not b or not c:
        return 0
    return len(b - c)


def _force_keyword_replacements(
    *,
    base: Sequence[str],
    cand: Sequence[str],
    pool: Sequence[str],
    keywords_n: int,
    min_replacements: int = 2,
    protected: Optional[Set[str]] = None,
) -> List[str]:
    out = _clean_keywords_list(cand)
    if len(out) != int(keywords_n):
        return out
    protected = set([_norm_text_strict(x) for x in (protected or set()) if _norm_text_strict(x)])
    if _keyword_replacement_count(base, out) >= int(min_replacements):
        return out

    pool_clean = _clean_keywords_list(pool)
    seen = set(out)
    for raw in pool_clean:
        if _keyword_replacement_count(base, out) >= int(min_replacements):
            break
        kn = _normalize_keyword(raw)
        if not kn or kn in seen:
            continue
        replace_idx: Optional[int] = None
        for i in range(len(out) - 1, -1, -1):
            cur = _norm_text_strict(out[i])
            if not cur:
                continue
            if cur in protected:
                continue
            replace_idx = i
            break
        if replace_idx is None:
            break
        old = out[replace_idx]
        out[replace_idx] = kn
        seen.discard(old)
        seen.add(kn)

    return _clean_keywords_list(out)[:keywords_n]


def _has_term_evidence(evidence_blob: str, term: str) -> bool:
    forms = _EVIDENCE_TERM_ALIASES.get(term, (term,))
    for form in forms:
        fs = _norm_text_strict(form)
        if not fs:
            continue
        if re.search(rf"(^|[^a-z]){re.escape(fs)}($|[^a-z])", evidence_blob):
            return True
    return False


def _evidence_refill_candidates(
    *,
    folder: str,
    subject: str,
    location: str,
    caption: str,
    alt_text: str,
) -> List[str]:
    pool: List[str] = []
    pool.extend(_extract_phrase_keywords(folder, subject, location, f"{caption} {alt_text}"))
    pool.extend(_visual_keyword_candidates(caption, alt_text, location))

    evidence = _norm_text_strict(f"{folder} {subject} {location} {caption} {alt_text}")
    for tok in evidence.split():
        if len(tok) < 3:
            continue
        if tok in _KW_STOPWORDS or tok in _KW_BANNED:
            continue
        pool.append(tok)

    return _clean_keywords_list(pool)


def _apply_evidence_keyword_guardrails(
    *,
    kw_list: Sequence[str],
    folder: str,
    subject: str,
    location: str,
    caption: str,
    alt_text: str,
    keywords_n: int,
) -> List[str]:
    evidence_blob = _norm_text_strict(f"{folder} {subject} {location} {caption} {alt_text}")
    is_amsterdam = "amsterdam" in evidence_blob

    out: List[str] = []
    seen: Set[str] = set()
    for raw in _clean_keywords_list(kw_list):
        kn = _norm_text_strict(raw)
        if not kn or kn in seen:
            continue

        if kn in _EVIDENCE_SENSITIVE_KEYWORDS and not _has_term_evidence(evidence_blob, kn):
            continue

        # Amsterdam guardrail: do not inject river/lake terms unless explicitly evidenced.
        if is_amsterdam and kn in {"river", "rivers", "lake", "lakes"}:
            if not _has_term_evidence(evidence_blob, kn):
                continue

        out.append(kn)
        seen.add(kn)

    if len(out) < int(keywords_n):
        for cand in _evidence_refill_candidates(
            folder=folder,
            subject=subject,
            location=location,
            caption=caption,
            alt_text=alt_text,
        ):
            if len(out) >= int(keywords_n):
                break
            kn = _norm_text_strict(cand)
            if not kn or kn in seen:
                continue
            if kn in _EVIDENCE_SENSITIVE_KEYWORDS and not _has_term_evidence(evidence_blob, kn):
                continue
            if is_amsterdam and kn in {"river", "rivers", "lake", "lakes"}:
                if not _has_term_evidence(evidence_blob, kn):
                    continue
            out.append(kn)
            seen.add(kn)

    return _clean_keywords_list(out)[: int(keywords_n)]


def _finalize_keywords(
    *,
    kw_list: Sequence[str],
    folder: str,
    subject: str,
    location: str,
    caption: str,
    alt_text: str = "",
    keywords_n: int,
) -> List[str]:
    kw_work = _clean_keywords_list(kw_list)

    dedup: List[str] = []
    seen_kw: Set[str] = set()
    for k in kw_work:
        kn = _norm_text_strict(k)
        if not kn or kn in seen_kw:
            continue
        seen_kw.add(kn)
        dedup.append(kn)
    kw_work = dedup

    if len(kw_work) != keywords_n:
        kw_work = _fallback_keywords(folder, subject, location, caption, keywords_n)
        kw_work = _clean_keywords_list(kw_work)
        seen_kw = set([_norm_text_strict(x) for x in kw_work if _norm_text_strict(x)])

    if len(kw_work) < keywords_n:
        loc_pad: List[str] = []
        for tok in _clean_location(location).split():
            kn_loc = _normalize_keyword(tok)
            if kn_loc:
                loc_pad.append(kn_loc)
        pad = _context_keyword_pool(folder, subject) + loc_pad + _context_tail_keywords(folder, subject)
        for k in pad:
            if len(kw_work) >= keywords_n:
                break
            kn = _normalize_keyword(k)
            if not kn or kn in seen_kw:
                continue
            kw_work.append(kn)
            seen_kw.add(kn)

    kw_work = _inject_precision_terms(
        kw_list=kw_work,
        folder=folder,
        subject=subject,
        location=location,
        caption=caption,
        keywords_n=keywords_n,
    )
    kw_work = _clean_keywords_list(kw_work)
    seen_kw = set([_norm_text_strict(x) for x in kw_work if _norm_text_strict(x)])

    kw_work = _rebalance_keywords_visual_context(
        kw_list=kw_work,
        caption=caption,
        alt_text=alt_text,
        folder=folder,
        subject=subject,
        location=location,
        keywords_n=keywords_n,
    )
    kw_work = _clean_keywords_list(kw_work)
    seen_kw = set([_norm_text_strict(x) for x in kw_work if _norm_text_strict(x)])

    if len(kw_work) < keywords_n:
        if _visual_nature_without_urban(caption, alt_text):
            kw_fill = _visual_keyword_candidates(caption, alt_text, location) + list(_NATURE_KEYWORD_POOL)
        else:
            kw_fill = _fallback_keywords(folder, subject, location, caption, keywords_n)
        for k in kw_fill:
            if len(kw_work) >= keywords_n:
                break
            kn = _normalize_keyword(k)
            if not kn or kn in seen_kw:
                continue
            if _visual_nature_without_urban(caption, alt_text) and (set(kn.split()) & _URBAN_KEYWORD_TERMS):
                continue
            kw_work.append(kn)
            seen_kw.add(kn)

    kw_work = _apply_scene_keyword_guardrails(
        kw_list=kw_work,
        folder=folder,
        subject=subject,
        location=location,
        caption=caption,
        alt_text=alt_text,
        keywords_n=keywords_n,
    )

    kw_work = _apply_evidence_keyword_guardrails(
        kw_list=kw_work,
        folder=folder,
        subject=subject,
        location=location,
        caption=caption,
        alt_text=alt_text,
        keywords_n=keywords_n,
    )

    return _clean_keywords_list(kw_work)[:keywords_n]


def _soft_dedup_keyword_signature(
    *,
    ledger: "UniquenessLedger",
    series_key: str,
    kw_list: Sequence[str],
    folder: str,
    subject: str,
    location: str,
    caption: str,
    keywords_n: int,
    base_seed: int,
    sequence_no: int,
) -> List[str]:
    """Best-effort keyword signature diversification without rejecting the row."""
    base = _clean_keywords_list(list(kw_list))
    if len(base) != int(keywords_n):
        return base

    sig = _kw_signature(base)
    if not sig:
        return base

    series_sigs = ledger.kw_sig_by_series.get(series_key, set())
    used_now = int(ledger.kw_sig_global_count.get(sig, 0))
    if used_now <= 0 and sig not in series_sigs:
        return base

    best = base
    best_sig = sig
    best_used = used_now
    protected = set(_extract_phrase_keywords(folder, subject, location, caption))
    rotate_pool = (
        _visual_keyword_candidates(caption, "", location)
        + _fallback_keywords(folder, subject, location, caption, keywords_n + 24)
        + _context_keyword_pool(folder, subject)
        + list(_KW_VARIANT_POOL)
    )

    for i in range(1, 36):
        cand = _variant_keywords(
            kw_list=best,
            folder=folder,
            subject=subject,
            location=location,
            caption=caption,
            keywords_n=keywords_n,
            variant=base_seed + i * 17,
            sequence_no=sequence_no + i,
        )
        cand = _clean_keywords_list(cand)
        if len(cand) != int(keywords_n):
            continue
        cand = _force_keyword_replacements(
            base=base,
            cand=cand,
            pool=rotate_pool,
            keywords_n=keywords_n,
            min_replacements=2,
            protected=protected,
        )
        if len(cand) != int(keywords_n):
            continue
        cand_sig = _kw_signature(cand)
        if not cand_sig:
            continue
        if cand_sig in series_sigs:
            continue
        cand_used = int(ledger.kw_sig_global_count.get(cand_sig, 0))
        if cand_used == 0:
            return cand
        if cand_sig != best_sig and cand_used < best_used:
            best = cand
            best_sig = cand_sig
            best_used = cand_used

    return best


def _fallback_unique_payload(
    *,
    ledger: "UniquenessLedger",
    series_key: str,
    folder: str,
    subject: str,
    location: str,
    image_path: Path,
    keywords_n: int,
    prefix_words: int,
    sequence_no: int = 0,
) -> Optional[Tuple[str, str, str]]:
    seed = _stable_seed(folder, subject, location, str(image_path))
    for i in range(520):
        v = seed + i
        caption = _fallback_caption_candidate(
            folder=folder,
            subject=subject,
            location=location,
            variant=v,
            sequence_no=sequence_no,
        )
        alt_text = _fallback_alt_candidate(
            folder=folder,
            subject=subject,
            location=location,
            variant=v + 11,
            sequence_no=sequence_no,
        )

        if not _caption_not_garbage(caption):
            continue
        if not _alt_not_garbage(alt_text):
            continue
        if not _alt_word_count_ok(alt_text):
            continue
        if _contains_uncertainty(caption) or _contains_uncertainty(alt_text):
            continue
        if not _has_visual_detail(caption, min_words=9):
            continue
        if not _has_visual_detail(alt_text, min_words=10):
            continue
        if _caption_alt_too_similar(caption, alt_text):
            continue
        if _norm_text_strict(caption) == _norm_text_strict(alt_text):
            continue

        kw_list = _variant_keywords(
            kw_list=[],
            folder=folder,
            subject=subject,
            location=location,
            caption=caption,
            keywords_n=keywords_n,
            variant=v + 23,
            sequence_no=sequence_no,
        )
        if len(kw_list) != keywords_n:
            continue

        dup, _why = ledger.is_duplicate(
            series_key=series_key,
            caption=caption,
            alt_text=alt_text,
            keywords=kw_list,
            prefix_words=prefix_words,
        )
        if dup:
            continue

        ledger.add(
            series_key=series_key,
            caption=caption,
            alt_text=alt_text,
            keywords=kw_list,
            prefix_words=prefix_words,
        )
        return caption, ", ".join(kw_list), alt_text

    return None


def _resolve_duplicate_payload(
    *,
    ledger: "UniquenessLedger",
    series_key: str,
    folder: str,
    subject: str,
    location: str,
    keywords_n: int,
    prefix_words: int,
    sequence_no: int,
    base_seed: int,
    kw_list_seed: Sequence[str],
    max_scan: int = 1400,
) -> Optional[Tuple[str, str, List[str]]]:
    for i in range(max_scan):
        v = base_seed + 5000 + i * 13
        cap = _fallback_caption_candidate(
            folder=folder,
            subject=subject,
            location=location,
            variant=v,
            sequence_no=sequence_no + i,
        )
        alt = _fallback_alt_candidate(
            folder=folder,
            subject=subject,
            location=location,
            variant=v + 29,
            sequence_no=sequence_no + i,
        )
        alt = _trim_or_pad_alt(alt, min_words=10, max_words=18)

        if not _caption_not_garbage(cap):
            continue
        if not _alt_not_garbage(alt):
            continue
        if not _alt_word_count_ok(alt):
            continue
        if _caption_style_bad(cap):
            continue
        if _alt_style_bad(alt):
            continue
        if _caption_alt_too_similar(cap, alt):
            continue

        kws = _variant_keywords(
            kw_list=kw_list_seed,
            folder=folder,
            subject=subject,
            location=location,
            caption=cap,
            keywords_n=keywords_n,
            variant=v + 71,
            sequence_no=sequence_no + i,
        )
        if len(kws) != keywords_n:
            continue

        dup, _why = ledger.is_duplicate(
            series_key=series_key,
            caption=cap,
            alt_text=alt,
            keywords=kws,
            prefix_words=prefix_words,
        )
        if dup:
            continue

        return cap, alt, kws
    return None


def _fallback_keywords(
    folder: str,
    subject: str,
    location: str,
    caption: str,
    keywords_n: int,
) -> List[str]:
    def tokens(s: str) -> List[str]:
        s = (s or "").replace("_", " ").replace("-", " ")
        parts = re.split(r"[\s,;/|]+", s)
        out: List[str] = []
        for p in parts:
            kn = _normalize_keyword(p.strip())
            if not kn:
                continue
            out.append(kn)
        return out

    seed: List[str] = []
    seed += tokens(folder)
    seed += tokens(subject)
    seed += tokens(location)
    seed += _extract_phrase_keywords(folder, subject, location, caption)

    seen: Set[str] = set()
    out: List[str] = []
    for k in seed:
        kn = _normalize_keyword(k)
        if not kn or kn in seen:
            continue
        seen.add(kn)
        out.append(kn)

    # Add high precision terms from external keyword_terms DB when available.
    for kn in _precision_candidates(
        folder=folder,
        subject=subject,
        location=location,
        caption=caption,
        limit=max(20, keywords_n * 3),
    ):
        if len(out) >= keywords_n:
            break
        if kn in seen:
            continue
        seen.add(kn)
        out.append(kn)

    # If still too short, add generic but safe words
    safe_pool = _context_keyword_pool(folder, subject) + _context_tail_keywords(folder, subject)
    for k in safe_pool:
        if len(out) >= keywords_n:
            break
        kn = _normalize_keyword(k)
        if not kn:
            continue
        if kn not in seen:
            seen.add(kn)
            out.append(kn)

    return _clean_keywords_list(out)[:keywords_n]


def _extract_json_object(text: str) -> Optional[dict]:
    text = (text or "").strip()
    if not text:
        return None

    # Whole text JSON?
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    # Balanced brace scan
    s = text
    n = len(s)
    for i, ch in enumerate(s):
        if ch != "{":
            continue
        depth = 0
        for j in range(i, n):
            cj = s[j]
            if cj == "{":
                depth += 1
            elif cj == "}":
                depth -= 1
                if depth == 0:
                    block = s[i : j + 1]
                    try:
                        obj = json.loads(block)
                        if isinstance(obj, dict):
                            return obj
                    except Exception:
                        pass
                    try:
                        obj2 = ast.literal_eval(block)
                        if isinstance(obj2, dict):
                            return obj2
                    except Exception:
                        pass
                    break
    return None


@dataclass
class UniquenessLedger:
    caption_global: Set[str] = field(default_factory=set)
    alt_global: Set[str] = field(default_factory=set)

    caption_prefix_by_series: Dict[str, Set[str]] = field(default_factory=dict)
    alt_prefix_by_series: Dict[str, Set[str]] = field(default_factory=dict)

    kw_sig_by_series: Dict[str, Set[str]] = field(default_factory=dict)
    kw_sig_global_count: Dict[str, int] = field(default_factory=dict)

    def _series_set(self, d: Dict[str, Set[str]], series_key: str) -> Set[str]:
        if series_key not in d:
            d[series_key] = set()
        return d[series_key]

    def is_duplicate(
        self,
        *,
        series_key: str,
        caption: str,
        alt_text: str,
        keywords: Sequence[str],
        prefix_words: int,
    ) -> Tuple[bool, str]:
        cap_norm = _norm_text_strict(caption)
        alt_norm = _norm_text_strict(alt_text)

        if cap_norm and cap_norm in self.caption_global:
            return True, "caption global duplicate"
        if alt_norm and alt_norm in self.alt_global:
            return True, "alt_text global duplicate"

        cap_prefix = _first_words_key(caption, prefix_words)
        if cap_prefix and cap_prefix in self._series_set(self.caption_prefix_by_series, series_key):
            return True, "caption prefix duplicate in series"

        alt_prefix = _first_words_key(alt_text, prefix_words)
        if alt_prefix and alt_prefix in self._series_set(self.alt_prefix_by_series, series_key):
            return True, "alt_text prefix duplicate in series"

        # Keyword-signature repetition inside a series is advisory only.
        # We still track signatures for prompt guidance, but we do not hard-fail rows on this.
        # Similar subjects in park sets can naturally share keyword clusters.

        return False, ""

    def add(
        self,
        *,
        series_key: str,
        caption: str,
        alt_text: str,
        keywords: Sequence[str],
        prefix_words: int,
    ) -> None:
        cap_norm = _norm_text_strict(caption)
        alt_norm = _norm_text_strict(alt_text)

        if cap_norm:
            self.caption_global.add(cap_norm)
        if alt_norm:
            self.alt_global.add(alt_norm)

        cap_prefix = _first_words_key(caption, prefix_words)
        if cap_prefix:
            self._series_set(self.caption_prefix_by_series, series_key).add(cap_prefix)

        alt_prefix = _first_words_key(alt_text, prefix_words)
        if alt_prefix:
            self._series_set(self.alt_prefix_by_series, series_key).add(alt_prefix)

        if int(prefix_words) > 2:
            kw_sig = _kw_signature(keywords)
            if kw_sig:
                self._series_set(self.kw_sig_by_series, series_key).add(kw_sig)

        kw_sig_global = _kw_signature(keywords)
        if kw_sig_global:
            self.kw_sig_global_count[kw_sig_global] = (
                int(self.kw_sig_global_count.get(kw_sig_global, 0)) + 1
            )


def image_to_base64_jpeg(path: Path, max_side: int, jpeg_quality: int) -> str:
    # Keep image lifetime short to avoid cumulative native decoder pressure.
    with Image.open(path) as _src:
        img = _src.convert("RGB")
    img.thumbnail((max_side, max_side), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=jpeg_quality, optimize=False)
    out = base64.b64encode(buf.getvalue()).decode("ascii")
    buf.close()
    return out


def ollama_generate_json(
    *,
    endpoint: str,
    model: str,
    prompt: str,
    image_b64: str,
    timeout: int,
    options: Optional[dict],
) -> str:
    url = endpoint.rstrip("/")
    payload: dict = {
        "model": model,
        "prompt": prompt,
        "images": [image_b64],
        "stream": False,
        "keep_alive": "30m",
        "format": "json",
    }
    if options:
        payload["options"] = options

    r = requests.post(url, json=payload, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    return str(data.get("response") or "").strip()


def build_prompt(
    *,
    folder: str,
    subject: str,
    location: str,
    keywords_n: int,
    avoid_caption_prefixes: Sequence[str],
    avoid_alt_prefixes: Sequence[str],
    avoid_kw_sigs: Sequence[str],
    sequence_no: int = 0,
    series_size: int = 1,
) -> str:
    folder = (folder or "").strip()
    subject = (subject or "").strip()
    location = (location or "").strip()

    avoid_lines: List[str] = []
    if avoid_caption_prefixes:
        avoid_lines.append("Avoid starting the caption with any of these openings:")
        avoid_lines.append("; ".join(list(avoid_caption_prefixes)[-10:]))

    if avoid_alt_prefixes:
        avoid_lines.append("Avoid starting the alt_text with any of these openings:")
        avoid_lines.append("; ".join(list(avoid_alt_prefixes)[-10:]))

    if avoid_kw_sigs:
        avoid_lines.append("Avoid repeating these keyword signatures:")
        avoid_lines.append("; ".join(list(avoid_kw_sigs)[-6:]))

    avoid_block = "\n".join([x for x in avoid_lines if x]).strip()

    lines: List[str] = []
    lines.append("Return ONLY one JSON object. No markdown. No code fences. No commentary.")
    lines.append('Keys must be EXACTLY: "caption", "alt_text", "keywords".')
    lines.append("")
    lines.append("Hard rules (no hallucination):")
    lines.append("1) Describe ONLY what is clearly visible in the image.")
    lines.append("2) Do NOT guess species, brand, model, or exact location if not clearly visible.")
    lines.append("3) If unsure, use only conservative visible terms (for example: bird, aircraft, flower, building, tree, water, skyline).")
    lines.append("4) If location string is provided below, you MAY include it. If it is empty, do NOT invent one.")
    lines.append("5) Never use uncertainty words: maybe, possibly, likely, perhaps.")
    lines.append("")
    lines.append("Output requirements:")
    lines.append("caption: exactly one factual sentence, human readable, no templates, no fluff.")
    lines.append("alt_text: 10 to 18 words, factual, no templates, no fluff, and clearly different wording from caption.")
    lines.append(f"keywords: exactly {keywords_n} comma separated keywords, unique, relevant, no gear words.")
    lines.append("")
    lines.append("Quality rules:")
    lines.append("A) Caption and alt_text must mention at least two concrete visible details (subject + setting/background).")
    lines.append("B) Do not use these fluff words: beautiful, stunning, serene.")
    lines.append("C) Do not use these meta words: photography, photo, image, picture.")
    lines.append("D) Keywords must not contain filler words like this, frame, shows, captures, context.")
    lines.append("E) Do not use generic keyword fillers like area, depth, background, foreground, outdoors, travel, scenic.")
    lines.append("F) Vary sentence openings across a series; do not start every caption with A, An, or The.")
    lines.append("G) Avoid repetitive template phrases like 'X features Y that...' and 'open-terrain view of...'.")
    lines.append("H) Never output malformed punctuation such as ',.' or double commas.")
    lines.append("I) Do not force urban words (city, downtown, skyline, buildings, street) unless clearly visible.")
    lines.append("J) Sun in sky is not a street light; trees are not buildings.")
    lines.append("K) Do not add mountain, lake, forest, or river keywords unless clearly visible or explicit in context.")
    lines.append("L) Do not add country/state/city names unless present in provided location or clearly visible context.")
    lines.append("M) If context is Amsterdam, do not output river/lake unless explicitly evidenced; prefer canal only when actually supported.")
    lines.append("")
    lines.append("Context (assist only, do not copy blindly):")
    if folder:
        lines.append(f"folder: {folder}")
    if subject:
        lines.append(f"subject: {subject}")
    if location:
        lines.append(f"location: {location}")
    if sequence_no > 0:
        lines.append(f"sequence_no: {sequence_no}")
    if series_size > 1:
        lines.append(f"series_size: {series_size}")
    lines.append("")
    if series_size >= 8:
        lines.append("Series rule: this is part of a large related set, so keep sentence structure varied from nearby items.")
        lines.append("Rotate openings naturally (location-first, setting-first, subject-first) instead of repeating one pattern.")
        lines.append("")
    if avoid_block:
        lines.append("Uniqueness constraints:")
        lines.append(avoid_block)
        lines.append("")
    lines.append('Example JSON format only: {"caption":"...","alt_text":"...","keywords":"k1, k2, ..."}')
    lines.append("")
    lines.append("Now output the JSON object:")
    return "\n".join(lines)


def build_rewrite_prompt(
    *,
    folder: str,
    subject: str,
    location: str,
    keywords_n: int,
    draft_caption: str,
    draft_alt_text: str,
    draft_keywords: Sequence[str],
    quality_issues: Sequence[str],
    avoid_caption_prefixes: Sequence[str],
    avoid_alt_prefixes: Sequence[str],
    sequence_no: int = 0,
    series_size: int = 1,
) -> str:
    folder = (folder or "").strip()
    subject = (subject or "").strip()
    location = (location or "").strip()
    draft_kw = ", ".join([str(k).strip() for k in draft_keywords if str(k).strip()])
    issue_txt = "; ".join([str(x).strip() for x in quality_issues if str(x).strip()][:8]) or "quality issues detected"

    lines: List[str] = []
    lines.append("Rewrite the draft output to improve quality and keep it factual.")
    lines.append("Return ONLY one JSON object. No markdown, no comments.")
    lines.append('Keys must be EXACTLY: "caption", "alt_text", "keywords".')
    lines.append("")
    lines.append("Hard rules:")
    lines.append("1) Describe ONLY clearly visible content. No guessing.")
    lines.append("2) caption: one sentence, 8 to 24 words, natural language, no fluff.")
    lines.append("3) alt_text: one sentence, 10 to 18 words, clearly different wording from caption.")
    lines.append(f"4) keywords: exactly {keywords_n} comma-separated keywords, unique, relevant.")
    lines.append("5) Do not use uncertainty words (maybe, possibly, likely, perhaps).")
    lines.append("6) Avoid repetitive phrasing and avoid generic filler words.")
    lines.append("6b) Do not inject mountain/lake/forest/river keywords unless clearly visible or in context.")
    lines.append("6c) Do not inject country/state/city names unless present in provided location or context.")
    lines.append("6d) If context is Amsterdam, do not inject river/lake unless explicitly evidenced; use canal only when supported.")
    lines.append("7) Do not start every caption with A/An/The; vary opening style.")
    lines.append("8) Avoid 'features ... that ...' and malformed punctuation like ',.'.")
    lines.append("")
    if avoid_caption_prefixes:
        lines.append("Avoid these caption openings:")
        lines.append("; ".join(list(avoid_caption_prefixes)[-10:]))
    if avoid_alt_prefixes:
        lines.append("Avoid these alt_text openings:")
        lines.append("; ".join(list(avoid_alt_prefixes)[-10:]))
    if avoid_caption_prefixes or avoid_alt_prefixes:
        lines.append("")
    lines.append("Context:")
    if folder:
        lines.append(f"folder: {folder}")
    if subject:
        lines.append(f"subject: {subject}")
    if location:
        lines.append(f"location: {location}")
    if sequence_no > 0:
        lines.append(f"sequence_no: {sequence_no}")
    if series_size > 1:
        lines.append(f"series_size: {series_size}")
    lines.append("")
    lines.append(f"Detected issues: {issue_txt}")
    lines.append("Draft to improve (do not copy blindly):")
    lines.append(f'draft_caption: "{draft_caption}"')
    lines.append(f'draft_alt_text: "{draft_alt_text}"')
    lines.append(f'draft_keywords: "{draft_kw}"')
    lines.append("")
    lines.append('Output format example: {"caption":"...","alt_text":"...","keywords":"k1, k2, ..."}')
    lines.append("Now output improved JSON:")
    return "\n".join(lines)


def rewrite_weak_payload(
    *,
    endpoint: str,
    model: str,
    timeout: int,
    options: Optional[dict],
    image_b64: str,
    folder: str,
    subject: str,
    location: str,
    keywords_n: int,
    draft_caption: str,
    draft_alt_text: str,
    draft_keywords: Sequence[str],
    quality_issues: Sequence[str],
    avoid_caption_prefixes: Sequence[str],
    avoid_alt_prefixes: Sequence[str],
    sequence_no: int = 0,
    series_size: int = 1,
) -> Optional[Tuple[str, str, List[str]]]:
    prompt = build_rewrite_prompt(
        folder=folder,
        subject=subject,
        location=location,
        keywords_n=keywords_n,
        draft_caption=draft_caption,
        draft_alt_text=draft_alt_text,
        draft_keywords=draft_keywords,
        quality_issues=quality_issues,
        avoid_caption_prefixes=avoid_caption_prefixes,
        avoid_alt_prefixes=avoid_alt_prefixes,
        sequence_no=sequence_no,
        series_size=series_size,
    )
    opts = dict(options or {})
    t0 = float(opts.get("temperature", 0.25))
    opts["temperature"] = min(0.75, max(0.35, t0 + 0.15))
    if "num_predict" in opts:
        try:
            opts["num_predict"] = max(180, int(opts.get("num_predict", 180)))
        except Exception:
            opts["num_predict"] = 180
    else:
        opts["num_predict"] = 180

    try:
        text = ollama_generate_json(
            endpoint=endpoint,
            model=model,
            prompt=prompt,
            image_b64=image_b64,
            timeout=timeout,
            options=opts,
        )
    except requests.exceptions.RequestException:
        return None

    cap, alt, kws = parse_output(text)
    cap = _trim_caption(_sanitize_sentence(_deawkward_sentence(cap)), max_words=24)
    alt = _trim_or_pad_alt(_sanitize_sentence(_deawkward_sentence(alt)), min_words=10, max_words=18)
    kws = _clean_keywords_list(kws)
    return cap, alt, kws


def parse_output(text: str) -> Tuple[str, str, List[str]]:
    obj = _extract_json_object(text)
    if isinstance(obj, dict):
        # accept mild key variants but output strict
        norm: Dict[str, object] = {}
        for k, v in obj.items():
            kk = str(k).strip().lower().replace(" ", "").replace("_", "")
            norm[kk] = v

        caption = str(norm.get("caption") or "").strip()
        alt_text = str(norm.get("alttext") or norm.get("alt") or norm.get("alt_text") or "").strip()
        kw_raw = norm.get("keywords")

        if isinstance(kw_raw, list):
            kw_list = [str(x).strip() for x in kw_raw if str(x).strip()]
        else:
            kw_list = _split_keywords(str(kw_raw or ""))

        return _sanitize_sentence(_clean_text_output(caption)), _sanitize_sentence(_clean_text_output(alt_text)), kw_list

    # fallback tagged lines
    caption = ""
    alt_text = ""
    kw_list: List[str] = []
    for line in (text or "").splitlines():
        l = line.strip()
        if not l:
            continue
        low = l.lower()
        if low.startswith("caption:"):
            caption = l.split(":", 1)[1].strip()
            continue
        if low.startswith("alt_text:") or low.startswith("alt text:") or low.startswith("alt:"):
            alt_text = l.split(":", 1)[1].strip()
            continue
        if low.startswith("keywords:") or low.startswith("tags:"):
            kw_list = _split_keywords(l.split(":", 1)[1].strip())
            continue

    return _sanitize_sentence(_clean_text_output(caption)), _sanitize_sentence(_clean_text_output(alt_text)), kw_list


def db_columns(con: sqlite3.Connection, table: str) -> Set[str]:
    cur = con.execute(f"PRAGMA table_info({table})")
    return {str(r[1]) for r in cur.fetchall()}


def _parse_id_list(raw: str) -> List[int]:
    out: List[int] = []
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
    # stable dedupe
    seen: Set[int] = set()
    uniq: List[int] = []
    for v in out:
        if v in seen:
            continue
        seen.add(v)
        uniq.append(v)
    return uniq


def fetch_rows(
    con: sqlite3.Connection,
    table: str,
    id_col: str,
    path_col: str,
    fallback_path_col: str,
    file_col: str,
    folder_col: str,
    subject_col: str,
    location_col: str,
    caption_col: str,
    keywords_col: str,
    alt_col: str,
    status_col: str,
    want_status: str,
    overwrite: bool,
    limit: int,
    id_filter: Optional[Sequence[int]] = None,
) -> List[dict]:
    cols = [
        id_col,
        path_col,
        fallback_path_col,
        file_col,
        folder_col,
        subject_col,
        location_col,
        caption_col,
        keywords_col,
        alt_col,
        status_col,
    ]
    col_sql = ", ".join([f'"{c}"' for c in cols])
    where_parts = [f'COALESCE("{status_col}", "") = ?']
    params: List[object] = [want_status]
    if id_filter:
        ids = [int(x) for x in id_filter if int(x) > 0]
        if ids:
            where_parts.append(f'"{id_col}" IN ({",".join(["?"] * len(ids))})')
            params.extend(ids)
    sql = f'SELECT {col_sql} FROM "{table}" WHERE ' + " AND ".join(where_parts)
    if limit > 0:
        sql += " LIMIT ?"
        params.append(limit)

    cur = con.execute(sql, params)
    out: List[dict] = []
    for row in cur.fetchall():
        d = dict(zip(cols, row))
        if not overwrite:
            if (d.get(caption_col) or d.get(keywords_col) or d.get(alt_col)):
                continue
        out.append(d)
    return out


def prefill_ledger_from_db(
    *,
    con: sqlite3.Connection,
    table: str,
    file_col: str,
    folder_col: str,
    subject_col: str,
    caption_col: str,
    keywords_col: str,
    alt_col: str,
    ledger: UniquenessLedger,
    prefix_words: int,
) -> int:
    sql = (
        f'SELECT "{file_col}", "{folder_col}", "{subject_col}", "{caption_col}", "{keywords_col}", "{alt_col}" '
        f'FROM "{table}" '
        f'WHERE COALESCE("{caption_col}", "") <> "" '
        f'   OR COALESCE("{keywords_col}", "") <> "" '
        f'   OR COALESCE("{alt_col}", "") <> ""'
    )
    cur = con.execute(sql)
    count = 0
    for row in cur.fetchall():
        file_name = str(row[0] or "")
        folder = str(row[1] or "")
        subject = str(row[2] or "")
        caption = _sanitize_sentence(_clean_text_output(str(row[3] or "")))
        keywords_raw = str(row[4] or "")
        alt_text = _sanitize_sentence(_clean_text_output(str(row[5] or "")))
        kw_list = _split_keywords(keywords_raw)

        if not caption and not alt_text and not kw_list:
            continue

        series_key, _ = _detect_series_key(folder, subject, file_name)

        cap_norm = _norm_text_strict(caption)
        alt_norm = _norm_text_strict(alt_text)
        if cap_norm:
            ledger.caption_global.add(cap_norm)
        if alt_norm:
            ledger.alt_global.add(alt_norm)

        kw_sig = _kw_signature(kw_list)
        if kw_sig:
            ledger._series_set(ledger.kw_sig_by_series, series_key).add(kw_sig)
            ledger.kw_sig_global_count[kw_sig] = int(ledger.kw_sig_global_count.get(kw_sig, 0)) + 1

        count += 1
    return count


def update_row(
    con: sqlite3.Connection,
    table: str,
    id_col: str,
    rid: int,
    caption_col: str,
    keywords_col: str,
    alt_col: str,
    status_col: str,
    new_status: str,
    caption: str,
    keywords: str,
    alt_text: str,
) -> None:
    sql = (
        f'UPDATE "{table}" '
        f'SET "{caption_col}" = ?, "{keywords_col}" = ?, "{alt_col}" = ?, "{status_col}" = ? '
        f'WHERE "{id_col}" = ?'
    )
    con.execute(sql, (caption, keywords, alt_text, new_status, rid))
    con.commit()


def process_one(
    *,
    ledger: UniquenessLedger,
    series_key: str,
    file_name: str,
    sequence_no: int,
    series_size: int,
    folder: str,
    subject: str,
    location: str,
    image_path: Path,
    endpoint: str,
    model: str,
    timeout: int,
    options: Optional[dict],
    img_max_side: int,
    img_quality: int,
    keywords_n: int,
    prefix_words: int,
    series_large_threshold: int,
    max_tries: int,
    rewrite_weak: bool,
    rewrite_max_passes: int,
    quality_min_score: int,
) -> Tuple[bool, str, str, str]:
    if not image_path.exists():
        return False, "", "", f"missing file: {image_path}"

    location = _enrich_location(location, folder, subject)
    image_b64 = image_to_base64_jpeg(image_path, img_max_side, img_quality)
    last_reason = "not_started"
    base_seed = _stable_seed(folder, subject, location, file_name, str(image_path))
    prefix_words_eff = int(prefix_words)
    if series_size >= int(series_large_threshold) * 4:
        prefix_words_eff = 2
    elif series_size >= int(series_large_threshold) * 2:
        prefix_words_eff = 3
    elif series_size >= int(series_large_threshold):
        prefix_words_eff = max(3, int(prefix_words) - 3)
    dup_prefix_words = 0 if prefix_words_eff <= 0 else max(2, prefix_words_eff - 1)
    rewrite_passes = max(0, int(rewrite_max_passes))
    quality_floor = max(0, min(100, int(quality_min_score)))
    # Adaptive quality floor for larger related series:
    # keep quality gate active, but reduce false failures on near-duplicate scenic frames.
    if series_size >= int(series_large_threshold) * 4:
        quality_floor = max(76, quality_floor - 9)
    elif series_size >= int(series_large_threshold) * 2:
        quality_floor = max(78, quality_floor - 7)
    elif series_size >= int(series_large_threshold):
        quality_floor = max(79, quality_floor - 6)

    for attempt in range(1, max_tries + 1):
        avoid_window = 25
        if series_size >= int(series_large_threshold) * 4:
            avoid_window = 90
        elif series_size >= int(series_large_threshold) * 2:
            avoid_window = 55
        avoid_caps = sorted(list(ledger.caption_prefix_by_series.get(series_key, set())))[-avoid_window:]
        avoid_alts = sorted(list(ledger.alt_prefix_by_series.get(series_key, set())))[-avoid_window:]
        avoid_kws = sorted(list(ledger.kw_sig_by_series.get(series_key, set())))[-25:]

        prompt = build_prompt(
            folder=folder,
            subject=subject,
            location=location,
            keywords_n=keywords_n,
            avoid_caption_prefixes=avoid_caps,
            avoid_alt_prefixes=avoid_alts,
            avoid_kw_sigs=avoid_kws,
            sequence_no=sequence_no,
            series_size=series_size,
        )

        opts = dict(options or {})
        if attempt > 1:
            # small nudge for uniqueness only
            t0 = float(opts.get("temperature", 0.25))
            opts["temperature"] = min(0.6, t0 + 0.1 * (attempt - 1))

        try:
            text = ollama_generate_json(
                endpoint=endpoint,
                model=model,
                prompt=prompt,
                image_b64=image_b64,
                timeout=timeout,
                options=opts,
            )
        except requests.exceptions.RequestException as e:
            return False, "", "", f"{type(e).__name__}: {e}"

        caption, alt_text, kw_list = parse_output(text)
        caption = _sanitize_sentence(_deawkward_sentence(caption))
        caption = _trim_caption(caption, max_words=24)
        alt_text = _sanitize_sentence(_deawkward_sentence(alt_text))
        alt_text = _trim_or_pad_alt(alt_text, min_words=10, max_words=18)
        kw_list = _clean_keywords_list(kw_list)

        # Rewrite weak model output before deterministic fallbacks.
        initial_score, initial_issues = _payload_quality_score(
            caption=caption,
            alt_text=alt_text,
            kw_list=kw_list,
            keywords_n=keywords_n,
            folder=folder,
            subject=subject,
            location=location,
        )
        if rewrite_weak and rewrite_passes > 0 and initial_score < quality_floor:
            best_caption = caption
            best_alt = alt_text
            best_kw = kw_list
            best_score = initial_score
            best_issues = list(initial_issues)

            for rp in range(rewrite_passes):
                rewritten = rewrite_weak_payload(
                    endpoint=endpoint,
                    model=model,
                    timeout=timeout,
                    options=opts,
                    image_b64=image_b64,
                    folder=folder,
                    subject=subject,
                    location=location,
                    keywords_n=keywords_n,
                    draft_caption=best_caption,
                    draft_alt_text=best_alt,
                    draft_keywords=best_kw,
                    quality_issues=best_issues,
                    avoid_caption_prefixes=avoid_caps,
                    avoid_alt_prefixes=avoid_alts,
                    sequence_no=sequence_no + attempt + rp,
                    series_size=series_size,
                )
                if rewritten is None:
                    continue
                rc, ra, rk = rewritten
                r_score, r_issues = _payload_quality_score(
                    caption=rc,
                    alt_text=ra,
                    kw_list=rk,
                    keywords_n=keywords_n,
                    folder=folder,
                    subject=subject,
                    location=location,
                )
                if r_score >= best_score:
                    best_caption, best_alt, best_kw = rc, ra, rk
                    best_score = r_score
                    best_issues = list(r_issues)
                if r_score >= quality_floor:
                    break

            caption, alt_text, kw_list = best_caption, best_alt, best_kw

        # Repair weak model output instead of discarding the whole attempt.
        if (
            not _caption_not_garbage(caption)
            or _contains_uncertainty(caption)
            or not _has_visual_detail(caption, min_words=8)
            or _caption_style_bad(caption)
        ):
            caption = _fallback_caption_candidate(
                folder=folder,
                subject=subject,
                location=location,
                variant=base_seed + attempt * 7,
                sequence_no=sequence_no,
            )

        if (
            not _alt_not_garbage(alt_text)
            or not _alt_word_count_ok(alt_text)
            or _contains_uncertainty(alt_text)
            or not _has_visual_detail(alt_text, min_words=9)
            or _alt_style_bad(alt_text)
        ):
            alt_text = _fallback_alt_candidate(
                folder=folder,
                subject=subject,
                location=location,
                variant=base_seed + attempt * 11,
                sequence_no=sequence_no,
            )
            alt_text = _trim_or_pad_alt(alt_text, min_words=10, max_words=18)

        if _caption_alt_too_similar(caption, alt_text) or (
            _norm_text_strict(caption) and _norm_text_strict(caption) == _norm_text_strict(alt_text)
        ):
            alt_text = _fallback_alt_candidate(
                folder=folder,
                subject=subject,
                location=location,
                variant=base_seed + attempt * 17,
                sequence_no=sequence_no + 1,
            )
            alt_text = _trim_or_pad_alt(alt_text, min_words=10, max_words=18)

        if _caption_alt_too_similar(caption, alt_text):
            caption = _fallback_caption_candidate(
                folder=folder,
                subject=subject,
                location=location,
                variant=base_seed + attempt * 19,
                sequence_no=sequence_no + 2,
            )

        if not _caption_not_garbage(caption):
            last_reason = "caption quality check failed"
            continue
        if not _alt_not_garbage(alt_text):
            last_reason = "alt_text quality check failed"
            continue
        if not _alt_word_count_ok(alt_text):
            last_reason = f"alt_text word count out of range count={_word_count(alt_text)}"
            continue
        if _contains_uncertainty(caption) or _contains_uncertainty(alt_text):
            last_reason = "contains uncertainty wording"
            continue
        if not _has_visual_detail(caption, min_words=8):
            last_reason = "caption lacks concrete visual details"
            continue
        if not _has_visual_detail(alt_text, min_words=9):
            last_reason = "alt_text lacks concrete visual details"
            continue
        if _caption_style_bad(caption):
            last_reason = "caption style check failed"
            continue
        if _alt_style_bad(alt_text):
            last_reason = "alt_text style check failed"
            continue
        if _caption_alt_too_similar(caption, alt_text):
            last_reason = "caption and alt_text too similar"
            continue

        kw_list = _finalize_keywords(
            kw_list=kw_list,
            folder=folder,
            subject=subject,
            location=location,
            caption=caption,
            alt_text=alt_text,
            keywords_n=keywords_n,
        )

        # Strict quality score gate before uniqueness checks.
        score_now, issues_now = _payload_quality_score(
            caption=caption,
            alt_text=alt_text,
            kw_list=kw_list,
            keywords_n=keywords_n,
            folder=folder,
            subject=subject,
            location=location,
        )

        if score_now < quality_floor and rewrite_weak and rewrite_passes > 0:
            best_caption = caption
            best_alt = alt_text
            best_kw = kw_list
            best_score = score_now
            best_issues = list(issues_now)

            for rp in range(rewrite_passes):
                rewritten = rewrite_weak_payload(
                    endpoint=endpoint,
                    model=model,
                    timeout=timeout,
                    options=opts,
                    image_b64=image_b64,
                    folder=folder,
                    subject=subject,
                    location=location,
                    keywords_n=keywords_n,
                    draft_caption=best_caption,
                    draft_alt_text=best_alt,
                    draft_keywords=best_kw,
                    quality_issues=best_issues,
                    avoid_caption_prefixes=avoid_caps,
                    avoid_alt_prefixes=avoid_alts,
                    sequence_no=sequence_no + attempt + rp + 100,
                    series_size=series_size,
                )
                if rewritten is None:
                    continue
                rc, ra, rk = rewritten
                rk = _finalize_keywords(
                    kw_list=rk,
                    folder=folder,
                    subject=subject,
                    location=location,
                    caption=rc,
                    alt_text=ra,
                    keywords_n=keywords_n,
                )
                r_score, r_issues = _payload_quality_score(
                    caption=rc,
                    alt_text=ra,
                    kw_list=rk,
                    keywords_n=keywords_n,
                    folder=folder,
                    subject=subject,
                    location=location,
                )
                if r_score >= best_score:
                    best_caption, best_alt, best_kw = rc, ra, rk
                    best_score = r_score
                    best_issues = list(r_issues)
                if r_score >= quality_floor:
                    break

            caption, alt_text, kw_list = best_caption, best_alt, best_kw
            score_now, issues_now = best_score, best_issues

        kw_list = _soft_dedup_keyword_signature(
            ledger=ledger,
            series_key=series_key,
            kw_list=kw_list,
            folder=folder,
            subject=subject,
            location=location,
            caption=caption,
            keywords_n=keywords_n,
            base_seed=base_seed + attempt * 211,
            sequence_no=sequence_no,
        )

        if len(kw_list) != keywords_n:
            last_reason = f"keywords fallback failed count={len(kw_list)} expected={keywords_n}"
            continue
        if score_now < quality_floor:
            short_issues = ", ".join(issues_now[:3]) if issues_now else "low score"
            last_reason = f"quality score {score_now} < {quality_floor} ({short_issues})"
            continue

        dup, why = ledger.is_duplicate(
            series_key=series_key,
            caption=caption,
            alt_text=alt_text,
            keywords=kw_list,
            prefix_words=prefix_words_eff,
        )
        if dup and why == "keywords signature duplicate in series":
            kw_variant = _variant_keywords(
                kw_list=kw_list,
                folder=folder,
                subject=subject,
                location=location,
                caption=caption,
                keywords_n=keywords_n,
                variant=base_seed + attempt,
                sequence_no=sequence_no,
            )
            dup2, why2 = ledger.is_duplicate(
                series_key=series_key,
                caption=caption,
                alt_text=alt_text,
                keywords=kw_variant,
                prefix_words=prefix_words_eff,
            )
            if not dup2:
                kw_list = kw_variant
                dup = False
            else:
                why = why2

        if dup and "prefix duplicate in series" in why and series_size >= int(series_large_threshold):
            caption = _fallback_caption_candidate(
                folder=folder,
                subject=subject,
                location=location,
                variant=base_seed + attempt * 29,
                sequence_no=sequence_no + attempt,
            )
            alt_text = _fallback_alt_candidate(
                folder=folder,
                subject=subject,
                location=location,
                variant=base_seed + attempt * 37,
                sequence_no=sequence_no + attempt,
            )
            dup, why = ledger.is_duplicate(
                series_key=series_key,
                caption=caption,
                alt_text=alt_text,
                keywords=kw_list,
                prefix_words=dup_prefix_words,
            )

        if dup and why == "alt_text global duplicate":
            for j in range(120):
                alt_try = _fallback_alt_candidate(
                    folder=folder,
                    subject=subject,
                    location=location,
                    variant=base_seed + attempt * 43 + j * 11,
                    sequence_no=sequence_no + attempt + j,
                )
                alt_try = _trim_or_pad_alt(alt_try, min_words=10, max_words=18)
                if not _alt_not_garbage(alt_try):
                    continue
                if _alt_style_bad(alt_try):
                    continue
                if _caption_alt_too_similar(caption, alt_try):
                    continue
                dup3, why3 = ledger.is_duplicate(
                    series_key=series_key,
                    caption=caption,
                    alt_text=alt_try,
                    keywords=kw_list,
                    prefix_words=dup_prefix_words,
                )
                if not dup3:
                    alt_text = alt_try
                    dup = False
                    break
                why = why3

        if dup:
            resolved = _resolve_duplicate_payload(
                ledger=ledger,
                series_key=series_key,
                folder=folder,
                subject=subject,
                location=location,
                keywords_n=keywords_n,
                prefix_words=dup_prefix_words,
                sequence_no=sequence_no + attempt,
                base_seed=base_seed + attempt * 101,
                kw_list_seed=kw_list,
                max_scan=1800 if series_size >= int(series_large_threshold) else 800,
            )
            if resolved is not None:
                caption, alt_text, kw_list = resolved
                dup = False

        if dup:
            last_reason = why
            continue

        final_score, final_issues = _payload_quality_score(
            caption=caption,
            alt_text=alt_text,
            kw_list=kw_list,
            keywords_n=keywords_n,
            folder=folder,
            subject=subject,
            location=location,
        )
        if final_score < quality_floor:
            short_issues = ", ".join(final_issues[:3]) if final_issues else "low score"
            last_reason = f"post-dup quality score {final_score} < {quality_floor} ({short_issues})"
            continue

        ledger.add(
            series_key=series_key,
            caption=caption,
            alt_text=alt_text,
            keywords=kw_list,
            prefix_words=prefix_words_eff,
        )

        return True, caption, ", ".join(kw_list), alt_text

    fallback = _fallback_unique_payload(
        ledger=ledger,
        series_key=series_key,
        folder=folder,
        subject=subject,
        location=location,
        image_path=image_path,
        keywords_n=keywords_n,
        prefix_words=prefix_words_eff,
        sequence_no=sequence_no,
    )
    if fallback is not None:
        cap, kws, alt = fallback
        return True, cap, kws, alt

    # Emergency path for very large series: preserve exact uniqueness even if prefix uniqueness is saturated.
    for i in range(900):
        v = base_seed + 2000 + i
        cap = _fallback_caption_candidate(
            folder=folder,
            subject=subject,
            location=location,
            variant=v,
            sequence_no=sequence_no + i,
        )
        alt = _fallback_alt_candidate(
            folder=folder,
            subject=subject,
            location=location,
            variant=v + 31,
            sequence_no=sequence_no + i,
        )
        kws_list = _variant_keywords(
            kw_list=[],
            folder=folder,
            subject=subject,
            location=location,
            caption=cap,
            keywords_n=keywords_n,
            variant=v + 53,
            sequence_no=sequence_no + i,
        )
        if len(kws_list) != keywords_n:
            continue

        cap_norm = _norm_text_strict(cap)
        alt_norm = _norm_text_strict(alt)
        kw_sig = _kw_signature(kws_list)
        if not cap_norm or not alt_norm or not kw_sig:
            continue
        if cap_norm in ledger.caption_global or alt_norm in ledger.alt_global:
            continue
        if kw_sig in ledger._series_set(ledger.kw_sig_by_series, series_key):
            continue

        ledger.caption_global.add(cap_norm)
        ledger.alt_global.add(alt_norm)
        ledger._series_set(ledger.kw_sig_by_series, series_key).add(kw_sig)
        return True, cap, ", ".join(kws_list), alt

    return False, "", "", f"failed uniqueness/quality checks after retries last={last_reason}"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate website Caption + Keywords + alt_text via Ollama vision, using ollama_path.")

    # Ollama
    p.add_argument("--endpoint", default="http://127.0.0.1:11434/api/generate")
    p.add_argument("--model", required=True, help="Vision model, e.g. llama3.2-vision:11b or qwen2.5vl:7b-q4_K_M")
    p.add_argument("--timeout", type=int, default=240)
    p.add_argument("--ollama-opts", default="", help='JSON dict for options (example: {"num_ctx":2048,"num_predict":180,"temperature":0.25})')

    # Image encoding
    p.add_argument("--image-max-side", type=int, default=1024)
    p.add_argument("--image-quality", type=int, default=85)

    # Output rules
    p.add_argument("--keywords-n", type=int, default=15)
    p.add_argument("--prefix-words", type=int, default=8)
    p.add_argument("--series-large-threshold", type=int, default=8, help="Series size at or above this uses stricter anti-dup guards.")
    p.add_argument("--max-tries", type=int, default=4)
    p.add_argument("--rewrite-weak", action="store_true", help="Run a second model rewrite pass only when quality score is low.")
    p.add_argument("--rewrite-max-passes", type=int, default=1, help="Max rewrite passes when --rewrite-weak is enabled.")
    p.add_argument("--quality-min-score", type=int, default=84, help="Minimum payload quality score required before acceptance.")
    p.add_argument("--terms-db", default="", help="Optional SQLite DB with keyword_terms table.")
    p.add_argument("--terms-table", default="keyword_terms", help="Table name inside terms DB.")
    p.add_argument("--terms-min-precision", type=int, default=85, help="Minimum precision_weight to use from terms DB.")

    # DB
    p.add_argument("--db", default=r".\data\review.db")
    p.add_argument("--table", default="review_queue")

    p.add_argument("--id-col", default="id")
    p.add_argument("--path-col", default="ollama_path", help="Primary image path column (MUST be ollama_path).")
    p.add_argument("--fallback-path-col", default="Path", help="Fallback image path column if ollama_path is empty.")
    p.add_argument("--file-col", default="File_Name")

    p.add_argument("--folder-col", default="Folder")
    p.add_argument("--subject-col", default="Subject")
    p.add_argument("--location-col", default="Location")

    p.add_argument("--caption-col", default="Caption")
    p.add_argument("--keywords-col", default="Keywords")
    p.add_argument("--alt-col", default="alt_text")

    p.add_argument("--status-col", default="Review_Status")
    p.add_argument("--status-queued", default="Queued")
    p.add_argument("--status-done", default="Pending")

    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--id-list", default="", help="Optional comma-separated review_queue ids to process.")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-tqdm", action="store_true")

    return p.parse_args()


def main() -> int:
    global _PRECISION_TERMS
    args = parse_args()

    # force your requirement: use ollama_path as primary
    if args.path_col != "ollama_path":
        print('[ERROR] --path-col must be "ollama_path". This file is designed for that.', file=sys.stderr)
        return 2

    options: Optional[dict] = None
    if args.ollama_opts.strip():
        try:
            options = json.loads(args.ollama_opts)
        except Exception:
            print("[ERROR] --ollama-opts must be valid JSON", file=sys.stderr)
            return 2

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"[ERROR] DB not found: {db_path}", file=sys.stderr)
        return 2

    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row

    cols = db_columns(con, args.table)
    needed = {
        args.id_col,
        args.path_col,
        args.fallback_path_col,
        args.file_col,
        args.folder_col,
        args.subject_col,
        args.location_col,
        args.caption_col,
        args.keywords_col,
        args.alt_col,
        args.status_col,
    }
    missing = sorted([c for c in needed if c not in cols])
    if missing:
        print(f"[ERROR] Missing columns in {args.table}: {missing}", file=sys.stderr)
        return 2

    row_scope_ids = _parse_id_list(args.id_list)
    if row_scope_ids:
        print(f"[INFO] Row scope ids: {len(row_scope_ids)}")

    rows = fetch_rows(
        con=con,
        table=args.table,
        id_col=args.id_col,
        path_col=args.path_col,
        fallback_path_col=args.fallback_path_col,
        file_col=args.file_col,
        folder_col=args.folder_col,
        subject_col=args.subject_col,
        location_col=args.location_col,
        caption_col=args.caption_col,
        keywords_col=args.keywords_col,
        alt_col=args.alt_col,
        status_col=args.status_col,
        want_status=args.status_queued,
        overwrite=args.overwrite,
        limit=args.limit,
        id_filter=row_scope_ids,
    )

    if not rows:
        print("[OK] No rows to process.")
        return 0

    ledger = UniquenessLedger()
    _PRECISION_TERMS = []
    if args.terms_db.strip():
        _PRECISION_TERMS = load_precision_terms(
            db_path=args.terms_db.strip(),
            table=args.terms_table.strip() or "keyword_terms",
            min_precision=int(args.terms_min_precision),
        )
        if _PRECISION_TERMS:
            print(f"[INFO] Loaded precision terms: {len(_PRECISION_TERMS)} from {args.terms_db} (min_precision={args.terms_min_precision})")
        else:
            print(f"[WARN] No precision terms loaded from {args.terms_db} table={args.terms_table} min_precision={args.terms_min_precision}")

    prefilled = prefill_ledger_from_db(
        con=con,
        table=args.table,
        file_col=args.file_col,
        folder_col=args.folder_col,
        subject_col=args.subject_col,
        caption_col=args.caption_col,
        keywords_col=args.keywords_col,
        alt_col=args.alt_col,
        ledger=ledger,
        prefix_words=args.prefix_words,
    )
    print(f"[INFO] Prefilled ledger from DB rows: {prefilled}")

    series_counts: Dict[str, int] = {}
    for r in rows:
        file_name = str(r[args.file_col] or "")
        folder = str(r[args.folder_col] or "")
        subject = str(r[args.subject_col] or "")
        skey, _ = _detect_series_key(folder, subject, file_name)
        series_counts[skey] = series_counts.get(skey, 0) + 1

    bar = rows if args.no_tqdm else tqdm(rows, desc="Prefill (DB)", unit="img")

    ok_count = 0
    fail_count = 0

    try:
        for r in bar:
            rid = int(r[args.id_col])
            file_name = str(r[args.file_col] or "")

            primary_path = str(r[args.path_col] or "").strip()
            fallback_path = str(r[args.fallback_path_col] or "").strip()
            pth = primary_path if primary_path else fallback_path
            image_path = Path(pth) if pth else Path()

            folder = str(r[args.folder_col] or "")
            subject = str(r[args.subject_col] or "")
            location = str(r[args.location_col] or "")

            series_key, sequence_no = _detect_series_key(folder, subject, file_name)
            series_size = int(series_counts.get(series_key, 1))

            t0 = time.time()
            print(f"[DOING] id={rid} file={file_name} series_n={series_size} seq={sequence_no}")

            ok, cap, kws, alt = process_one(
                ledger=ledger,
                series_key=series_key,
                file_name=file_name,
                sequence_no=sequence_no,
                series_size=series_size,
                folder=folder,
                subject=subject,
                location=location,
                image_path=image_path,
                endpoint=args.endpoint,
                model=args.model,
                timeout=args.timeout,
                options=options,
                img_max_side=args.image_max_side,
                img_quality=args.image_quality,
                keywords_n=args.keywords_n,
                prefix_words=args.prefix_words,
                series_large_threshold=args.series_large_threshold,
                max_tries=args.max_tries,
                rewrite_weak=args.rewrite_weak,
                rewrite_max_passes=args.rewrite_max_passes,
                quality_min_score=args.quality_min_score,
            )

            dt = time.time() - t0

            if not ok:
                fail_count += 1
                print(f"[FAIL] id={rid} file={file_name} reason={alt} ({dt:.1f}s)")
                if hasattr(bar, "set_postfix_str"):
                    bar.set_postfix_str(f"ok={ok_count} fail={fail_count}")
                continue

            print(f"[OUT] id={rid}")
            print(f"[OUT] caption: {cap}")
            print(f"[OUT] alt_text: {alt}")
            print(f"[OUT] keywords: {kws}")

            if not args.dry_run:
                update_row(
                    con=con,
                    table=args.table,
                    id_col=args.id_col,
                    rid=rid,
                    caption_col=args.caption_col,
                    keywords_col=args.keywords_col,
                    alt_col=args.alt_col,
                    status_col=args.status_col,
                    new_status=args.status_done,
                    caption=cap,
                    keywords=kws,
                    alt_text=alt,
                )

            ok_count += 1
            print(f"[OK] id={rid} in {dt:.1f}s")
            if hasattr(bar, "set_postfix_str"):
                bar.set_postfix_str(f"ok={ok_count} fail={fail_count}")

    except KeyboardInterrupt:
        print("\n[WARN] Stopped by user (Ctrl+C). Exiting cleanly.")
        print(f"[INFO] Progress: ok={ok_count} fail={fail_count}")
        try:
            con.commit()
        except Exception:
            pass
        try:
            con.close()
        except Exception:
            pass
        return 0

    try:
        con.close()
    except Exception:
        pass

    print(f"[OK] Completed. Updated rows: {ok_count} (failures: {fail_count})")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
