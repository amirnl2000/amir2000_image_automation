from __future__ import annotations

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

import re
from collections import Counter, defaultdict
from typing import Any


SOURCE_NAME = "identifier_consensus_v1"

LOCATION_WORDS = {
    "amsterdam",
    "netherlands",
    "holland",
    "zandvoort",
    "israel",
    "galilee",
    "colorado",
    "sedona",
    "arizona",
    "usa",
    "hula",
    "noord",
    "waterleidingduinen",
}


def _ascii_clean(text: str) -> str:
    text = re.sub(r"[^A-Za-z0-9 ]+", " ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _title_subject(text: str) -> str:
    cleaned = _ascii_clean(text)
    small = {"and", "or", "on", "in", "at", "with", "by", "of", "the", "a", "an"}
    words = []
    for index, word in enumerate(cleaned.split()):
        lower = word.lower()
        if index > 0 and lower in small:
            words.append(lower)
        else:
            words.append(word[:1].upper() + word[1:])
    return " ".join(words)


def _remove_location(subject: str, location: str = "") -> str:
    words_to_remove = set(LOCATION_WORDS)

    for token in re.split(r"[^A-Za-z0-9]+", location or ""):
        if token:
            words_to_remove.add(token.lower())

    kept = [word for word in subject.split() if word.lower() not in words_to_remove]
    return _title_subject(" ".join(kept))


def _remove_forbidden(subject: str) -> str:
    forbidden = {
        "photo",
        "image",
        "picture",
        "shot",
        "macro",
        "photography",
        "canon",
        "eos",
        "lens",
    }

    kept = [word for word in subject.split() if word.lower() not in forbidden]
    return _title_subject(" ".join(kept))


def _normalize_subject(subject: str, *, location: str = "") -> str:
    subject = _remove_forbidden(subject)
    subject = _remove_location(subject, location)
    subject = _ascii_clean(subject)

    words = subject.split()

    if len(words) > 9:
        words = words[:9]

    subject = _title_subject(" ".join(words))

    if len(subject) > 75:
        subject = " ".join(subject.split()[:8])

    return subject


def _refine_bird_subject(subject: str, candidates: list[dict[str, Any]], *, location: str = "") -> str:
    lower = subject.lower()
    loc = (location or "").lower()

    if "parrot" not in lower and "parakeet" not in lower:
        return subject
    if "israel" not in loc:
        return subject

    evidence_blob = " ".join(
        " ".join(
            [
            str(candidate.get("subject", "")),
            str(candidate.get("label", "")),
            str(candidate.get("evidence", "")),
            " ".join(str(item) for item in candidate.get("alternatives", []) if item),
            ]
        )
        for candidate in candidates
    ).lower()

    has_green_parrot = "green" in evidence_blob and ("parrot" in evidence_blob or "parakeet" in evidence_blob)
    has_ringneck_traits = any(
        trait in evidence_blob
        for trait in ["red beak", "red bill", "eye ring", "ring neck", "ringneck", "rose ring"]
    )

    if has_green_parrot and has_ringneck_traits:
        return "Rose Ringed Parakeet"

    return subject


def _category_key(value: object) -> str:
    text = str(value or "").strip().lower()

    aliases = {
        "flora": "plant",
        "flower": "plant",
        "flowers": "plant",
        "fungus": "plant",
        "fungi": "plant",
        "mushroom": "plant",
        "bird": "animal",
        "mammal": "animal",
        "insect": "animal",
    }

    return aliases.get(text, text)


def _is_bioclip_candidate(candidate: dict[str, Any]) -> bool:
    return "bioclip" in str(candidate.get("source", "")).lower()


def _filter_cross_model_conflicts(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    vision_categories = {
        _category_key(candidate.get("category"))
        for candidate in candidates
        if not _is_bioclip_candidate(candidate)
        and _category_key(candidate.get("category")) not in {"", "unknown"}
    }

    if not vision_categories:
        return candidates

    filtered: list[dict[str, Any]] = []

    for candidate in candidates:
        if not _is_bioclip_candidate(candidate):
            filtered.append(candidate)
            continue

        category = _category_key(candidate.get("category"))
        confidence = int(candidate.get("confidence", 0) or 0)

        if category and category not in vision_categories and confidence < 80:
            continue

        filtered.append(candidate)

    return filtered or candidates


def build_subject_consensus(
    candidates: list[dict[str, Any]],
    *,
    user_subject: str = "",
    location: str = "",
    folder: str = "",
) -> dict[str, Any]:
    usable = [
        candidate
        for candidate in candidates
        if candidate.get("ok") and str(candidate.get("subject", "")).strip()
    ]

    if not usable:
        return {
            "ok": False,
            "subject": "",
            "confidence": 0,
            "category": "unknown",
            "mode": "no_usable_candidates",
            "source": SOURCE_NAME,
            "details": candidates,
            "error": "No usable identifier candidates.",
        }

    usable = _filter_cross_model_conflicts(usable)

    # Prefer high confidence specific results. BioCLIP often gives useful species signals,
    # but Ollama gives better action and context. Consensus combines both.
    by_subject: Counter[str] = Counter()
    best_by_subject: dict[str, dict[str, Any]] = {}

    for candidate in usable:
        subject = _normalize_subject(str(candidate.get("subject", "")), location=location)

        if not subject:
            continue

        confidence = int(candidate.get("confidence", 0) or 0)
        weight = 1

        if confidence >= 80:
            weight = 3
        elif confidence >= 60:
            weight = 2

        by_subject[subject] += weight

        if subject not in best_by_subject or confidence > int(best_by_subject[subject].get("confidence", 0) or 0):
            updated = dict(candidate)
            updated["subject"] = subject
            best_by_subject[subject] = updated

    if not by_subject:
        return {
            "ok": False,
            "subject": "",
            "confidence": 0,
            "category": "unknown",
            "mode": "empty_after_normalization",
            "source": SOURCE_NAME,
            "details": candidates,
            "error": "Candidates became empty after normalization.",
        }

    best_subject, best_weight = by_subject.most_common(1)[0]
    best_candidate = best_by_subject[best_subject]

    categories = Counter(str(candidate.get("category", "") or "unknown") for candidate in usable)
    top_category = categories.most_common(1)[0][0]

    # If user typed a useful visible object hint, merge only object words, never location.
    hinted = _subject_from_hint(user_subject, top_category)

    if hinted and _hint_matches_candidates(hinted, usable):
        # Keep the real action/context from the model where possible.
        best_subject = _merge_hint_with_subject(hinted, best_subject, top_category)

    best_subject = _refine_bird_subject(best_subject, usable, location=location)
    best_subject = _normalize_subject(best_subject, location=location)

    confidence_values = [int(candidate.get("confidence", 0) or 0) for candidate in usable]
    average_confidence = int(sum(confidence_values) / max(1, len(confidence_values)))

    consensus_bonus = min(20, best_weight * 3)
    final_confidence = max(int(best_candidate.get("confidence", 0) or 0), average_confidence)
    final_confidence = min(96, final_confidence + consensus_bonus)

    return {
        "ok": bool(best_subject),
        "subject": best_subject,
        "confidence": final_confidence,
        "category": top_category,
        "mode": "weighted_consensus",
        "source": SOURCE_NAME,
        "details": candidates,
        "votes": dict(by_subject),
        "error": "",
    }


def _subject_from_hint(user_subject: str, category: str) -> str:
    text = _normalize_subject(user_subject or "")

    if not text:
        return ""

    bad_only = {
        "bird",
        "birds",
        "animal",
        "animals",
        "nature",
        "natural",
        "landscape",
        "flower",
        "flowers",
        "object",
        "scene",
    }

    if text.lower() in bad_only:
        return ""

    return text


def _hint_matches_candidates(hint: str, candidates: list[dict[str, Any]]) -> bool:
    hint_words = {word.lower() for word in hint.split() if len(word) >= 3}

    if not hint_words:
        return False

    haystack = " ".join(
        [
            str(candidate.get("subject", "")) + " " +
            str(candidate.get("label", "")) + " " +
            str(candidate.get("category", "")) + " " +
            str(candidate.get("evidence", ""))
            for candidate in candidates
        ]
    ).lower()

    return any(word in haystack for word in hint_words)


def _merge_hint_with_subject(hint: str, subject: str, category: str) -> str:
    lower_hint = hint.lower()
    lower_subject = subject.lower()

    if lower_hint in lower_subject:
        return subject

    if category == "boat" and "sunset" in lower_hint and "boat" in lower_subject:
        if "fishing" in lower_subject:
            return "Fishing Boat at Sunset"
        return "Boat at Sunset"

    if category == "people" and ("canal" in lower_hint or "water" in lower_hint):
        return "Person Sitting by Canal"

    if category == "aircraft" and any(word in lower_hint for word in ["plane", "jet", "aircraft"]):
        return subject

    return subject
