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

WORD_RE = re.compile(r"[a-z0-9]+")

META_LABELS = {
    "text",
    "visible text",
    "written text",
    "writing",
    "letter",
    "letters",
    "word",
    "words",
    "label",
    "labels",
    "caption",
    "object",
    "thing",
    "scene",
    "view",
    "detail",
    "details",
    "background",
    "foreground",
    "unknown",
    "image",
    "photo",
    "photograph",
    "picture",
}

SOURCE_DENY_PARTS = {
    "ocr",
    "visible_text",
    "visible text",
    "text_db",
    "readable_text",
    "untrusted",
}

GEAR_WORDS = {
    "canon",
    "eos",
    "r5",
    "mark",
    "rf",
    "ef",
    "lens",
    "iso",
    "aperture",
    "photography",
}


def normalize(value: Any) -> str:
    text = str(value or "")
    text = text.replace("_", " ").replace("-", " ").lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)

    return re.sub(r"\s+", " ", text).strip()


def tokens(value: Any) -> list[str]:
    return WORD_RE.findall(normalize(value))


def stem(token: str) -> str:
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"

    if len(token) > 4 and token.endswith("es"):
        return token[:-2]

    if len(token) > 3 and token.endswith("s"):
        return token[:-1]

    return token


def stems(value: Any) -> list[str]:
    return [
        stem(item)
        for item in tokens(value)
        if item not in GEAR_WORDS
    ]


def title_text(value: Any) -> str:
    text = str(value or "")
    text = text.replace("_", " ").replace("-", " ")
    text = re.sub(r"[^A-Za-z0-9 '&/]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    if not text:
        return ""

    small = {"a", "an", "and", "the", "of", "in", "on", "at", "by", "with", "to", "for"}
    out: list[str] = []

    for index, token in enumerate(text.split()):
        lower = token.lower()
        upper = token.upper()

        if index > 0 and lower in small:
            out.append(lower)
        elif any(ch.isdigit() for ch in token) and len(token) <= 8:
            out.append(upper)
        else:
            out.append(token[:1].upper() + token[1:].lower())

    return " ".join(out)


def row_source_trusted(row: dict[str, Any]) -> bool:
    source = normalize(row.get("source", ""))

    return not any(part in source for part in SOURCE_DENY_PARTS)


def candidate_text(row: dict[str, Any]) -> str:
    return str(row.get("subject") or row.get("label") or "").strip()


def candidate_ok(row: dict[str, Any]) -> bool:
    if not isinstance(row, dict):
        return False

    if not row_source_trusted(row):
        return False

    label = normalize(candidate_text(row))

    if not label or label in META_LABELS:
        return False

    label_tokens = tokens(label)

    if not label_tokens:
        return False

    if all(item in GEAR_WORDS for item in label_tokens):
        return False

    useful = [
        item
        for item in label_tokens
        if item not in GEAR_WORDS
    ]

    if not useful:
        return False

    if len(useful) == 1 and useful[0] in {"unknown", "subject", "object", "scene"}:
        return False

    return True


def family_key(value: Any) -> str:
    items = stems(value)

    if not items:
        return ""

    if len(items) >= 2:
        return " ".join(items[-2:])

    return items[0]


def similarity(a: Any, b: Any) -> float:
    left = set(stems(a))
    right = set(stems(b))

    if not left or not right:
        return 0.0

    return len(left & right) / max(1, len(left | right))


def resolve_subject_from_rows(rows: list[dict[str, Any]], original: Any = None) -> dict[str, Any] | None:
    accepted = [
        row
        for row in rows or []
        if row.get("accepted") and candidate_ok(row)
    ]

    if not accepted:
        return None

    labels = [
        candidate_text(row)
        for row in accepted
        if candidate_text(row)
    ]

    if not labels:
        return None

    normalized_counts = Counter(
        normalize(label)
        for label in labels
        if normalize(label)
    )
    top_norm, top_count = normalized_counts.most_common(1)[0]

    if top_count / max(1, len(labels)) >= 0.50:
        best = max(
            [
                label
                for label in labels
                if normalize(label) == top_norm
            ],
            key=lambda item: (len(tokens(item)), len(str(item))),
        )
        confidence = max(
            int(row.get("confidence") or row.get("score") or 0)
            for row in accepted
        )

        return {
            "subject": title_text(best),
            "confidence": confidence,
            "category": "evidence_consensus",
            "mode": "exact_or_majority_consensus",
        }

    clusters: dict[str, list[str]] = defaultdict(list)

    for label in labels:
        key = family_key(label)

        if key:
            clusters[key].append(label)

    if clusters:
        _best_key, members = max(
            clusters.items(),
            key=lambda item: (
                len(item[1]),
                max(len(tokens(value)) for value in item[1]),
            ),
        )
        support = len(members) / max(1, len(labels))

        if support >= 0.50:
            best = max(
                members,
                key=lambda item: (len(tokens(item)), len(str(item))),
            )
            confidence = max(
                int(row.get("confidence") or row.get("score") or 0)
                for row in accepted
                if candidate_text(row) in members
            )

            return {
                "subject": title_text(best),
                "confidence": confidence,
                "category": "evidence_consensus",
                "mode": "stem_cluster_consensus",
            }

    pair_scores = []

    for index, left in enumerate(labels):
        for right in labels[index + 1:]:
            pair_scores.append(similarity(left, right))

    if pair_scores and sum(pair_scores) / len(pair_scores) >= 0.35:
        best = max(
            labels,
            key=lambda item: (len(tokens(item)), len(str(item))),
        )
        confidence = max(
            int(row.get("confidence") or row.get("score") or 0)
            for row in accepted
        )

        return {
            "subject": title_text(best),
            "confidence": confidence,
            "category": "evidence_consensus",
            "mode": "similarity_consensus",
        }

    return None
