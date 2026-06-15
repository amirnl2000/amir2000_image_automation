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

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

CJK_RE = re.compile(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]")
WORD_RE = re.compile(r"[a-z0-9]+")

GEAR_WORDS = {
    "canon",
    "eos",
    "camera",
    "lens",
    "mark",
    "alamy",
    "photographer",
    "photography",
    "iso",
    "aperture",
    "focal",
    "shutter",
    "copyright",
    "amir",
    "darzi",
}

META_WORDS = {
    "photo",
    "image",
    "picture",
    "photograph",
    "view",
    "scene",
    "object",
    "thing",
    "subject",
    "visible",
    "shows",
    "showing",
    "displaying",
}

STYLE_WORDS = {
    "soft",
    "hard",
    "clear",
    "clean",
    "minimal",
    "natural",
    "bright",
    "dark",
    "warm",
    "cool",
    "wide",
    "close",
    "distant",
    "calm",
    "quiet",
    "sharp",
    "blur",
    "blurred",
    "background",
    "foreground",
    "composition",
    "detail",
    "details",
    "texture",
    "pattern",
    "light",
    "lighting",
    "shadow",
    "silhouette",
    "color",
    "tones",
    "tone",
    "frame",
    "framed",
    "isolated",
}

FUNCTION_WORDS = {
    "a",
    "an",
    "and",
    "the",
    "of",
    "in",
    "on",
    "at",
    "by",
    "with",
    "to",
    "for",
    "from",
    "under",
    "above",
    "against",
    "through",
    "between",
    "near",
    "below",
    "over",
}
_DANGLING_SUBJECT_RELATION_RE = re.compile(
    r"\b(?:with|in|on|at|by|near|beside|against|of|and|the)\s*$",
    re.I,
)
_WEAK_KEYWORD_TAILS = {
    "texture",
    "textures",
    "pattern",
    "patterns",
    "contrast",
    "contrasts",
    "detail",
    "details",
    "marking",
    "markings",
    "background",
    "foreground",
    "surface",
    "surfaces",
    "light",
    "lighting",
}
_WEAK_KEYWORD_SINGLE = _WEAK_KEYWORD_TAILS | {
    "above",
    "across",
    "along",
    "area",
    "around",
    "bare",
    "black",
    "body",
    "bordered",
    "bordering",
    "both",
    "brown",
    "clear",
    "captured",
    "captures",
    "depicted",
    "depicts",
    "dry",
    "edge",
    "eight",
    "five",
    "four",
    "gray",
    "grey",
    "green",
    "grassy",
    "large",
    "left",
    "multiple",
    "nine",
    "numerous",
    "one",
    "pale",
    "blue",
    "red",
    "orange",
    "reflection",
    "reflections",
    "scene",
    "section",
    "serene",
    "several",
    "seven",
    "single",
    "six",
    "small",
    "some",
    "side",
    "surrounded",
    "surrounding",
    "tall",
    "ten",
    "three",
    "tranquil",
    "two",
    "under",
    "view",
    "white",
    "yellow",
    "shape",
    "form",
    "element",
    "elements",
}
_SAFE_LIGHT_KEYWORDS = {
    "low light",
    "bright light",
    "back light",
    "available light",
}
_WEAK_REFLECTION_HEADS = {
    "water",
    "surface",
    "pond",
    "lake",
    "river",
    "canal",
    "stream",
    "reflection",
    "scene",
    "view",
    "background",
    "foreground",
}

SAFE_STYLE_PHRASES: set[str] = set()

TOPIC_LOCATION_WORDS = {
    "animal",
    "animals",
    "bird",
    "birds",
    "flora",
    "flower",
    "flowers",
    "firework",
    "fireworks",
    "macro",
    "nature",
    "wildlife",
    "aviation",
    "aircraft",
    "vehicle",
    "vehicles",
    "water",
    "waterscape",
    "landscape",
    "architecture",
    "cityscape",
    "street",
    "night",
    "people",
}


def normalize(value: Any) -> str:
    text = str(value or "")
    text = text.replace("_", " ").replace("-", " ")
    text = re.sub(r"[^A-Za-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def strip_dangling_subject_relation(value: Any) -> str:
    text = str(value or "").replace("_", " ").replace("-", " ")
    text = re.sub(r"\s+", " ", text).strip(" ,.;:")

    for _ in range(3):
        updated = _DANGLING_SUBJECT_RELATION_RE.sub("", text).strip(" ,.;:")
        if updated == text:
            break
        text = updated

    return re.sub(r"\s+", " ", text).strip()


def weak_keyword_phrase(value: Any) -> bool:
    words = WORD_RE.findall(normalize(value))

    if not words:
        return True

    key = " ".join(words)
    if key in _SAFE_LIGHT_KEYWORDS:
        return False

    if len(words) == 1:
        return words[0] in _WEAK_KEYWORD_SINGLE

    if any(word in {"texture", "textures", "pattern", "patterns"} for word in words):
        return True

    if len(words) <= 2 and words[0] in {"body", "area", "section", "part", "edge", "side"}:
        return True

    if len(words) <= 2 and words[0] in {"some", "several", "numerous", "many", "few", "both", "single", "multiple"}:
        return True

    if words[-1] in _WEAK_KEYWORD_TAILS:
        return True

    if len(words) <= 2 and words[-1] in {"reflection", "reflections"} and words[0] in _WEAK_REFLECTION_HEADS:
        return True

    return False


def canonical_keyword(value: Any) -> str:
    text = normalize(value)

    equivalents = {
        "clear composition": "clean composition",
        "balanced composition": "clean composition",
        "simple composition": "clean composition",
        "visible detail": "visible subject detail",
        "subject detail": "visible subject detail",
        "clear subject detail": "visible subject detail",
        "natural background": "soft background",
        "soft natural background": "soft background",
        "blurred background": "soft background",
    }

    return equivalents.get(text, text)


def title_text(value: Any) -> str:
    text = str(value or "")
    text = text.replace("_", " ").replace("-", " ")
    text = re.sub(r"[^A-Za-z0-9 '&/]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    if not text:
        return "Photographic Detail"

    small = {"a", "an", "and", "the", "of", "in", "on", "at", "by", "with", "to", "for"}
    out: list[str] = []

    for index, token in enumerate(text.split()):
        lower = token.lower()
        upper = token.upper()

        if upper in {"USA", "UK", "EU", "KLM", "DHL", "UPS", "NASA"}:
            out.append(upper)
        elif index > 0 and lower in small:
            out.append(lower)
        elif any(ch.isdigit() for ch in token) and len(token) <= 8:
            out.append(upper)
        else:
            out.append(token[:1].upper() + token[1:].lower())

    return " ".join(out)


def tokens(value: Any) -> list[str]:
    return WORD_RE.findall(normalize(value))


def token_set(value: Any) -> set[str]:
    return {item for item in tokens(value) if len(item) >= 3}


def stem(token: str) -> str:
    token = token.lower()

    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"

    if len(token) > 4 and token.endswith("es"):
        return token[:-2]

    if len(token) > 3 and token.endswith("s"):
        return token[:-1]

    return token


def stem_set(value: Any) -> set[str]:
    return {stem(item) for item in token_set(value)}


def has_cjk(value: Any) -> bool:
    return bool(CJK_RE.search(str(value or "")))


def is_fake_location(value: Any) -> bool:
    text = normalize(value)

    if not text:
        return True

    if any(word in text for word in ["photography", "collection", "gallery", "category"]):
        return True

    toks = set(text.split())

    if toks and toks <= TOPIC_LOCATION_WORDS:
        return True

    return False


def clean_subject(value: Any) -> str:
    text = title_text(value)
    text = re.sub(
        r"\b(Canon|EOS|Mark|II|III|IV|R5|RF|EF|Photography)\b",
        " ",
        text,
        flags=re.I,
    )
    text = re.sub(r"\b\d{3,4}\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = strip_dangling_subject_relation(text)

    return text or "Photographic Detail"


def clean_location(value: Any) -> str:
    if is_fake_location(value):
        return ""

    return title_text(value)


def sentence_is_bad(value: Any) -> bool:
    raw = str(value or "").strip()
    low = normalize(raw)

    if not low:
        return True

    if has_cjk(raw):
        return True

    broken = [
        " in with ",
        " with with ",
        " showing showing ",
        " of of ",
        " .",
        " ,",
        " in in ",
        " on on ",
    ]

    padded = f" {low} "

    if any(item in padded for item in broken):
        return True

    if len(low.split()) < 7:
        return True

    return False


def collapse_repetition(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"\s+", " ", text).strip()

    for _ in range(4):
        new_text = re.sub(
            r"\b([A-Za-z0-9]+(?:\s+[A-Za-z0-9]+){0,5})\s+\1\b",
            r"\1",
            text,
            flags=re.I,
        )

        if new_text == text:
            break

        text = new_text

    return text.strip()


def generic_caption(subject: str, location: str, variant: int) -> str:
    return ""


def generic_alt(subject: str, location: str, variant: int) -> str:
    return ""


def content_words(value: Any) -> set[str]:
    found = stem_set(value)
    ignored = {stem(w) for w in FUNCTION_WORDS | STYLE_WORDS | META_WORDS | GEAR_WORDS}

    return {
        item
        for item in found
        if item not in ignored
    }


def load_vocab(db_path: Path) -> set[str]:
    vocab_db = db_path.with_name("revamp_knowledge.db")

    if not vocab_db.exists():
        return set()

    vocab: set[str] = set()

    try:
        conn = sqlite3.connect(str(vocab_db))
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }

        for table, column in [
            ("revamp_candidate_terms", "normalized"),
            ("mysql_terms", "normalized"),
            ("external_terms", "normalized"),
        ]:
            if table not in tables:
                continue

            for row in conn.execute(f"SELECT {column} FROM {table} WHERE {column} IS NOT NULL"):
                text = normalize(row[0])

                if text:
                    vocab.add(text)

        conn.close()
    except Exception:
        return set()

    return vocab


def phrase_allowed(phrase: str, trusted: set[str], vocab: set[str]) -> bool:
    value = normalize(phrase)

    if not value:
        return False

    if has_cjk(value):
        return False

    if weak_keyword_phrase(value):
        return False

    phrase_tokens = stem_set(value)

    if phrase_tokens & {stem(w) for w in GEAR_WORDS}:
        return False

    important = content_words(value)

    if not important:
        return value in SAFE_STYLE_PHRASES

    if important <= trusted:
        return True

    if value in vocab and important & trusted:
        return True

    return False


def remove_fragments(items: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()

    for item in items:
        value = normalize(item)

        if not value or value in seen:
            continue

        seen.add(value)
        unique.append(value)

    result: list[str] = []

    for item in unique:
        item_words = set(item.split())

        if len(item_words) == 1 and any(
            item in other.split()
            and item != other
            for other in unique
        ):
            continue

        if len(item_words) <= 2:
            inside = any(
                item_words <= set(other.split())
                and item != other
                and len(other.split()) >= 3
                for other in unique
            )

            if inside:
                continue

        result.append(item)

    return result


def build_keywords(row: sqlite3.Row, subject: str, location: str, vocab: set[str]) -> str:
    trusted_text = " ".join(
        str(row[key] or "")
        for key in ["Caption", "alt_text"]
        if key in row.keys()
    )
    trusted = stem_set(trusted_text)

    raw: list[str] = []
    raw.extend(item.strip() for item in str(row["Keywords"] or "").split(",") if item.strip())

    cleaned: list[str] = []
    seen: set[str] = set()

    for item in raw:
        value = canonical_keyword(item)

        if not value or value in seen:
            continue

        if not phrase_allowed(value, trusted, vocab):
            continue

        seen.add(value)
        cleaned.append(value)

    cleaned = remove_fragments(cleaned)

    if len(cleaned) < 5:
        return ""

    return ", ".join(cleaned[:8])


def build_evidence_json(row: sqlite3.Row, subject: str, location: str, caption: str, alt_text: str, keywords: str) -> dict[str, Any]:
    return {
        "id": row["id"],
        "subject": subject,
        "location": location,
        "source_fields": {
            "Subject": row["Subject"],
            "Location": row["Location"],
            "Folder": row["Folder"],
            "File_Name": row["File_Name"],
            "Original_File_Name": row["Original_File_Name"],
        },
        "cleaned_metadata": {
            "Caption": caption,
            "alt_text": alt_text,
            "Keywords": keywords,
        },
    }


def clean_pending_review_metadata(db_path: str | Path) -> int:
    db_path = Path(db_path)

    if not db_path.exists():
        print(f"[WARN] Evidence metadata cleanup skipped: DB not found: {db_path}")
        return 0

    vocab = load_vocab(db_path)
    evidence_dir = db_path.parent / "metadata_evidence_json" / time.strftime("run_%Y%m%d_%H%M%S")
    evidence_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    try:
        cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(review_queue)")
        }
        required = {
            "id",
            "Subject",
            "Location",
            "Folder",
            "File_Name",
            "Original_File_Name",
            "Caption",
            "alt_text",
            "Keywords",
            "Review_Status",
        }

        if not required <= cols:
            print(f"[WARN] Evidence metadata cleanup skipped: missing columns {sorted(required - cols)}")
            return 0

        rows = conn.execute(
            """
            SELECT
                id,
                Subject,
                Location,
                Folder,
                File_Name,
                Original_File_Name,
                Caption,
                alt_text,
                Keywords,
                Review_Status
            FROM review_queue
            WHERE COALESCE(Review_Status, '') IN ('', 'Queued', 'Pending')
            ORDER BY id
            """
        ).fetchall()

        updated = 0

        for index, row in enumerate(rows):
            # Generic skip: if the prefill produced non-empty Caption,
            # alt_text, AND Keywords for this row, trust it. The brief
            # forbids inventing metadata from Subject/Location/Folder/
            # File_Name, and that is exactly what the rewrites below do
            # (build_keywords pulls from subject/location/vocab; the
            # generic_caption/generic_alt fallbacks pull from subject/
            # location). The prefill's own validator already gates for
            # empty/garbage output, so we only act as a safety net for
            # rows the prefill could not populate at all.
            existing_caption = str(row["Caption"] or "").strip()
            existing_alt = str(row["alt_text"] or "").strip()
            existing_keywords = str(row["Keywords"] or "").strip()
            if existing_caption and existing_alt and existing_keywords:
                continue

            subject = clean_subject(row["Subject"])
            location = clean_location(row["Location"])

            caption = collapse_repetition(row["Caption"])
            alt_text = collapse_repetition(row["alt_text"])

            if sentence_is_bad(caption):
                caption = generic_caption(subject, location, index)

            if sentence_is_bad(alt_text):
                alt_text = generic_alt(subject, location, index)

            if normalize(caption) == normalize(alt_text):
                alt_text = generic_alt(subject, location, index + 1)

            keywords = build_keywords(row, subject, location, vocab)

            conn.execute(
                """
                UPDATE review_queue
                SET Caption = ?, alt_text = ?, Keywords = ?, Review_Status = 'Pending'
                WHERE id = ?
                """,
                (
                    caption,
                    alt_text,
                    keywords,
                    row["id"],
                ),
            )
            updated += 1

            evidence = build_evidence_json(row, subject, location, caption, alt_text, keywords)
            (evidence_dir / f"row_{row['id']}.json").write_text(
                json.dumps(evidence, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        conn.commit()

        latest = evidence_dir.parent / "latest.txt"
        latest.write_text(str(evidence_dir), encoding="utf-8")

        if updated:
            print(f"[OK] Evidence metadata cleanup updated {updated} pending row(s). JSON: {evidence_dir}")
        else:
            print("[INFO] Evidence metadata cleanup found no pending rows.")

        return updated
    finally:
        conn.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(Path.cwd() / "data" / "review.db"))
    args = parser.parse_args()
    clean_pending_review_metadata(args.db)

# AMIR_PREFILL_EVIDENCE_BUILDER_V2_START
# Generic deterministic metadata builder for immediate prefill fallback.
# No per topic rules. No per subject rules.

import re as _amir_pf2_re
from pathlib import Path as _amir_pf2_Path
from typing import Any as _amir_pf2_Any

_AMIR_PF2_CJK_RE = _amir_pf2_re.compile(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]")
_AMIR_PF2_WORD_RE = _amir_pf2_re.compile(r"[a-z0-9]+")

_AMIR_PF2_GEAR_WORDS = {
    "canon",
    "eos",
    "r5",
    "mark",
    "rf",
    "ef",
    "lens",
    "camera",
    "iso",
    "aperture",
    "focal",
    "shutter",
    "photography",
    "photographer",
    "photo",
    "jpg",
    "jpeg",
    "png",
    "webp",
    "amir",
    "darzi",
    "alamy",
}

_AMIR_PF2_FUNCTION_WORDS = {
    "a",
    "an",
    "and",
    "the",
    "of",
    "in",
    "on",
    "at",
    "by",
    "with",
    "to",
    "for",
    "from",
    "under",
    "above",
    "against",
    "through",
    "between",
    "near",
    "below",
    "over",
}

_AMIR_PF2_ERROR_WORDS = {
    "weak",
    "length",
    "slug",
    "like",
    "count",
    "reason",
    "fallback",
    "caption",
    "alt",
    "keyword",
    "keywords",
}

_AMIR_PF2_STYLE_KEYWORDS: list[str] = []
_AMIR_PF2_TOPIC_LOCATION_WORDS = {
    "animal",
    "animals",
    "bird",
    "birds",
    "flora",
    "flower",
    "flowers",
    "firework",
    "fireworks",
    "macro",
    "nature",
    "wildlife",
    "aviation",
    "aircraft",
    "vehicle",
    "vehicles",
    "water",
    "waterscape",
    "landscape",
    "architecture",
    "cityscape",
    "street",
    "night",
    "people",
}


def _amir_pf2_normalize(value: _amir_pf2_Any) -> str:
    text = str(value or "")
    text = text.replace("_", " ").replace("-", " ")
    text = _amir_pf2_re.sub(r"[^A-Za-z0-9\s]", " ", text)
    text = _amir_pf2_re.sub(r"\s+", " ", text).strip().lower()
    return text


def _amir_pf2_has_cjk(value: _amir_pf2_Any) -> bool:
    return bool(_AMIR_PF2_CJK_RE.search(str(value or "")))


def _amir_pf2_tokens(value: _amir_pf2_Any) -> list[str]:
    return _AMIR_PF2_WORD_RE.findall(_amir_pf2_normalize(value))


def _amir_pf2_title(value: _amir_pf2_Any) -> str:
    text = str(value or "")
    text = text.replace("_", " ").replace("-", " ")
    text = _amir_pf2_re.sub(r"[^A-Za-z0-9 '&/]", " ", text)
    text = _amir_pf2_re.sub(r"\s+", " ", text).strip()

    if not text:
        return ""

    small = {"a", "an", "and", "the", "of", "in", "on", "at", "by", "with", "to", "for"}
    out = []

    for index, token in enumerate(text.split()):
        lower = token.lower()
        upper = token.upper()

        if upper in {"USA", "UK", "EU", "KLM", "DHL", "UPS", "NASA"}:
            out.append(upper)
        elif index > 0 and lower in small:
            out.append(lower)
        elif any(ch.isdigit() for ch in token) and len(token) <= 8:
            out.append(upper)
        else:
            out.append(token[:1].upper() + token[1:].lower())

    return " ".join(out)


def _amir_pf2_clean_subject(value: _amir_pf2_Any) -> str:
    text = _amir_pf2_title(value)
    text = _amir_pf2_re.sub(
        r"\b(Canon|EOS|Mark|II|III|IV|R5|RF|EF|Photography|Photo|JPG|JPEG|PNG|WEBP)\b",
        " ",
        text,
        flags=_amir_pf2_re.I,
    )
    text = _amir_pf2_re.sub(r"\b\d{3,4}\b", " ", text)
    text = _amir_pf2_re.sub(r"\s+", " ", text).strip()
    text = strip_dangling_subject_relation(text)
    return text or "Photographic Detail"


def _amir_pf2_subject_from_filename(file_name: str) -> str:
    stem = _amir_pf2_Path(str(file_name or "")).stem
    stem = stem.replace("_", " ").replace("-", " ")
    stem = _amir_pf2_re.split(
        r"\bCanon\b|\bEOS\b|\bR5\b|\bMark\b|\bPhotography\b|\bPhoto\b|\b\d{4}\b",
        stem,
        maxsplit=1,
        flags=_amir_pf2_re.I,
    )[0]
    stem = _amir_pf2_re.sub(r"\b\d{3,4}\b", " ", stem)
    stem = _amir_pf2_re.sub(r"\s+", " ", stem).strip()
    return _amir_pf2_clean_subject(stem)


def _amir_pf2_clean_location(value: _amir_pf2_Any) -> str:
    text = _amir_pf2_normalize(value)

    if not text:
        return ""

    if any(word in text for word in ["photography", "collection", "gallery", "category"]):
        return ""

    toks = set(text.split())

    if toks and toks <= _AMIR_PF2_TOPIC_LOCATION_WORDS:
        return ""

    return _amir_pf2_title(value)


_AMIR_PF2_UNSUPPORTED_CONTEXT_PHRASES = {
    "field hospitals",
    "track and field",
    "field houses",
    "grass track",
    "grass skiing",
}


def _amir_pf2_contains_unsupported_context_phrase(value: _amir_pf2_Any) -> bool:
    low = _amir_pf2_normalize(value)
    return any(phrase in low for phrase in _AMIR_PF2_UNSUPPORTED_CONTEXT_PHRASES)


def _amir_pf2_sentence_bad(value: _amir_pf2_Any) -> bool:
    raw = str(value or "").strip()
    low = _amir_pf2_normalize(raw)

    if not low:
        return True

    if _amir_pf2_has_cjk(raw):
        return True

    if _amir_pf2_contains_unsupported_context_phrase(raw):
        return True

    if set(_amir_pf2_tokens(low)) & _AMIR_PF2_ERROR_WORDS:
        if "captured" not in low and "photographed" not in low and "shown" not in low:
            return True

    broken = [
        " in with ",
        " with with ",
        " showing showing ",
        " of of ",
        " in in ",
        " on on ",
        " .",
        " ,",
    ]
    padded = f" {low} "

    if any(item in padded for item in broken):
        return True

    if len(low.split()) < 7:
        return True

    return False


def _amir_pf2_collapse_repetition(value: _amir_pf2_Any) -> str:
    text = str(value or "")
    text = _amir_pf2_re.sub(r"\s+", " ", text).strip()

    for _ in range(4):
        updated = _amir_pf2_re.sub(
            r"\b([A-Za-z0-9]+(?:\s+[A-Za-z0-9]+){0,5})\s+\1\b",
            r"\1",
            text,
            flags=_amir_pf2_re.I,
        )

        if updated == text:
            break

        text = updated

    return text.strip()


def _amir_pf2_place_clause(subject: str, location: str) -> str:
    if location and _amir_pf2_normalize(location) not in _amir_pf2_normalize(subject):
        return f" in {location}"

    return ""


def _amir_pf2_caption(subject: str, location: str, variant: int) -> str:
    return ""


def _amir_pf2_alt(subject: str, location: str, variant: int) -> str:
    return ""


def _amir_pf2_keyword_key(value: _amir_pf2_Any) -> str:
    text = _amir_pf2_normalize(value)
    equivalents = {
        "clear composition": "clean composition",
        "balanced composition": "clean composition",
        "simple composition": "clean composition",
        "visible detail": "visible subject detail",
        "subject detail": "visible subject detail",
        "clear subject detail": "visible subject detail",
        "natural background": "soft background",
        "soft natural background": "soft background",
        "blurred background": "soft background",
    }
    text = equivalents.get(text, text)
    words = [tok for tok in text.split() if tok not in _AMIR_PF2_FUNCTION_WORDS]
    return " ".join(words) if words else text


def _amir_pf2_subject_phrases(subject: str) -> list[str]:
    toks = [
        tok
        for tok in _amir_pf2_tokens(subject)
        if tok not in _AMIR_PF2_GEAR_WORDS
        and tok not in _AMIR_PF2_FUNCTION_WORDS
        and not tok.isdigit()
    ]
    out = []

    if subject and _amir_pf2_normalize(subject):
        out.append(_amir_pf2_normalize(subject))

    for size in [3, 2]:
        for index in range(0, max(0, len(toks) - size + 1)):
            phrase = " ".join(toks[index:index + size])

            if phrase and phrase not in out:
                out.append(phrase)

    return out


def _amir_pf2_keyword_allowed(value: str, trusted_words: set[str]) -> bool:
    text = _amir_pf2_keyword_key(value)

    if not text:
        return False

    if _amir_pf2_contains_unsupported_context_phrase(text):
        return False

    if _amir_pf2_has_cjk(text):
        return False

    if weak_keyword_phrase(text):
        return False

    toks = set(_amir_pf2_tokens(text))

    if not toks:
        return False

    if toks & _AMIR_PF2_GEAR_WORDS:
        return False

    if toks & _AMIR_PF2_ERROR_WORDS:
        return False

    if any(tok.isdigit() for tok in toks):
        return False

    if text in _AMIR_PF2_STYLE_KEYWORDS:
        return True

    useful = {
        tok
        for tok in toks
        if tok not in _AMIR_PF2_FUNCTION_WORDS
        and tok not in _AMIR_PF2_GEAR_WORDS
    }

    if not useful:
        return False

    trusted_hits = useful & trusted_words
    if len(useful) > 1:
        return len(trusted_hits) >= min(2, len(useful))

    return bool(trusted_hits)


def _amir_pf2_keywords(context: dict[str, _amir_pf2_Any], subject: str, location: str, model_keywords: _amir_pf2_Any) -> str:
    trusted_text = str(model_keywords or "")
    trusted_words = {
        tok
        for tok in _amir_pf2_tokens(trusted_text)
        if tok not in _AMIR_PF2_GEAR_WORDS
        and tok not in _AMIR_PF2_FUNCTION_WORDS
        and not tok.isdigit()
    }

    raw = []
    raw.extend(
        item.strip()
        for item in str(model_keywords or "").split(",")
        if item.strip()
    )

    cleaned = []
    seen = set()

    for item in raw:
        key = _amir_pf2_keyword_key(item)

        if not key or key in seen:
            continue

        if not _amir_pf2_keyword_allowed(key, trusted_words):
            continue

        seen.add(key)
        cleaned.append(key)

    final = []
    final_seen = set()

    for item in cleaned:
        item_words = set(item.split())

        if len(item_words) <= 2:
            inside = any(
                item_words <= set(other.split())
                and item != other
                and len(other.split()) >= 3
                for other in cleaned
            )

            if inside:
                continue

        if item not in final_seen:
            final_seen.add(item)
            final.append(item)

    if len(final) < 5:
        return ""

    return ", ".join(final[:8])


def _amir_pf2_clean_file_subject(file_name: str) -> str:
    return _amir_pf2_normalize(_amir_pf2_subject_from_filename(file_name))


def build_metadata_from_context(
    context: dict[str, _amir_pf2_Any],
    model_caption: _amir_pf2_Any = "",
    model_alt_text: _amir_pf2_Any = "",
    model_keywords: _amir_pf2_Any = "",
    variant: int = 0,
) -> dict[str, str]:
    local_context = dict(context or {})
    local_context["file_name_clean"] = _amir_pf2_clean_file_subject(str(local_context.get("file_name") or ""))
    local_context["original_file_name_clean"] = _amir_pf2_clean_file_subject(str(local_context.get("original_file_name") or ""))

    subject = (
        local_context.get("final_subject")
        or local_context.get("subject")
        or local_context.get("ai_suggested_subject")
        or local_context.get("identifier_subject")
        or ""
    )

    subject = _amir_pf2_clean_subject(subject)
    location = _amir_pf2_clean_location(local_context.get("location") or "")

    caption = _amir_pf2_collapse_repetition(model_caption)
    alt_text = _amir_pf2_collapse_repetition(model_alt_text)

    if _amir_pf2_sentence_bad(caption):
        caption = ""

    if _amir_pf2_sentence_bad(alt_text):
        alt_text = ""

    keywords = _amir_pf2_keywords(local_context, subject, location, model_keywords)

    if len([item for item in keywords.split(",") if item.strip()]) < 5:
        keywords = ""

    return {
        "caption": caption,
        "alt_text": alt_text,
        "keywords": keywords,
        "subject": subject,
        "location": location,
    }
# AMIR_PREFILL_EVIDENCE_BUILDER_V2_END

# AMIR_HINT_KEYWORDS_METADATA_SOFT_EVIDENCE_V1_START
# Optional hint keywords for metadata.
# Empty = skipped.
# Positive hints are allowed only when supported by existing evidence.
# Negative hints remove matching unsafe terms.

import json as _amir_meta_hint_json
import os as _amir_meta_hint_os
import re as _amir_meta_hint_re
from pathlib import Path as _amir_meta_hint_Path


_AMIR_META_HINT_FUNCTION_WORDS = {
    "a",
    "an",
    "and",
    "the",
    "of",
    "in",
    "on",
    "at",
    "by",
    "with",
    "to",
    "for",
    "from",
    "no",
    "not",
    "without",
    "exclude",
    "avoid",
}

_AMIR_META_HINT_GEAR_WORDS = {
    "canon",
    "eos",
    "r5",
    "mark",
    "rf",
    "ef",
    "lens",
    "camera",
    "photography",
    "photo",
    "jpg",
    "jpeg",
    "png",
    "webp",
}

_AMIR_META_HINT_HIGH_RISK_EQUIV = {
    "person": {"person", "people", "human", "man", "woman", "boy", "girl", "pedestrian", "worker", "workers"},
    "people": {"person", "people", "human", "man", "woman", "boy", "girl", "pedestrian", "worker", "workers"},
    "human": {"person", "people", "human", "man", "woman", "boy", "girl", "pedestrian", "worker", "workers"},
}


def _amir_meta_hint_norm(value):
    text = str(value or "")
    text = text.replace("_", " ").replace("-", " ").lower()
    text = _amir_meta_hint_re.sub(r"[^a-z0-9,\s]", " ", text)
    text = _amir_meta_hint_re.sub(r"\s+", " ", text).strip()
    return text


def _amir_meta_hint_tokens(value):
    return [
        token
        for token in _amir_meta_hint_re.findall(r"[a-z0-9]+", _amir_meta_hint_norm(value))
        if len(token) >= 2
    ]


def _amir_meta_hint_parse(value):
    raw = str(value or "")
    parts = [
        item.strip()
        for item in _amir_meta_hint_re.split(r"[,;|]", raw)
        if item.strip()
    ]

    positive = []
    negative = []

    for part in parts:
        low = _amir_meta_hint_norm(part)

        if not low:
            continue

        is_negative = False

        for prefix in ["no ", "not ", "without ", "exclude ", "avoid "]:
            if low.startswith(prefix):
                is_negative = True
                low = low[len(prefix):].strip()
                break

        words = [
            token
            for token in _amir_meta_hint_tokens(low)
            if token not in _AMIR_META_HINT_FUNCTION_WORDS
            and token not in _AMIR_META_HINT_GEAR_WORDS
            and not token.isdigit()
        ]

        if not words:
            continue

        phrase = " ".join(words)

        if is_negative:
            negative.append(phrase)
        else:
            positive.append(phrase)

    return positive, negative


def _amir_meta_hint_get_from_file(context):
    path = str(_amir_meta_hint_os.environ.get("AMIR_HINT_KEYWORDS_FILE") or "").strip()

    if not path:
        return ""

    hint_path = _amir_meta_hint_Path(path)

    if not hint_path.exists():
        return ""

    try:
        payload = _amir_meta_hint_json.loads(hint_path.read_text(encoding="utf-8"))
    except Exception:
        return ""

    items = payload.get("items", [])

    if not isinstance(items, list):
        return ""

    subject = _amir_meta_hint_norm(
        context.get("subject")
        or context.get("final_subject")
        or context.get("ai_suggested_subject")
        or context.get("identifier_subject")
        or ""
    )
    location = _amir_meta_hint_norm(context.get("location") or "")
    folder = _amir_meta_hint_norm(context.get("folder") or "")

    best_hint = ""
    best_score = 0

    for item in items:
        if not isinstance(item, dict):
            continue

        item_subject = _amir_meta_hint_norm(item.get("subject") or "")
        item_location = _amir_meta_hint_norm(item.get("location") or "")
        item_folder = _amir_meta_hint_norm(item.get("folder") or "")

        score = 0

        if subject and item_subject and subject == item_subject:
            score += 4
        elif subject and item_subject and (subject in item_subject or item_subject in subject):
            score += 2

        if location and item_location and location == item_location:
            score += 2

        if folder and item_folder and folder == item_folder:
            score += 1

        if score > best_score:
            best_score = score
            best_hint = str(item.get("hint_keywords") or "")

    if best_score >= 2:
        return best_hint

    return ""


def _amir_meta_hint_get(context):
    direct = str(
        context.get("hint_keywords")
        or context.get("Hint_Keywords")
        or context.get("hints")
        or ""
    ).strip()

    if direct:
        return direct

    file_hint = _amir_meta_hint_get_from_file(context)

    if file_hint:
        return file_hint

    return str(_amir_meta_hint_os.environ.get("AMIR_CURRENT_HINT_KEYWORDS") or "").strip()


def _amir_meta_hint_supported(phrase, evidence):
    phrase_tokens = {
        token
        for token in _amir_meta_hint_tokens(phrase)
        if token not in _AMIR_META_HINT_FUNCTION_WORDS
        and token not in _AMIR_META_HINT_GEAR_WORDS
        and not token.isdigit()
    }

    if not phrase_tokens:
        return False

    evidence_tokens = set(_amir_meta_hint_tokens(evidence))

    return phrase_tokens <= evidence_tokens


def _amir_meta_hint_blocked_by_negative(keyword, negative):
    keyword_tokens = set(_amir_meta_hint_tokens(keyword))

    if not keyword_tokens:
        return True

    for term in negative:
        term_tokens = set(_amir_meta_hint_tokens(term))
        expanded = set(term_tokens)

        for token in list(term_tokens):
            expanded.update(_AMIR_META_HINT_HIGH_RISK_EQUIV.get(token, set()))

        if keyword_tokens & expanded:
            return True

    return False


def _amir_meta_hint_keyword_key(value):
    return _amir_meta_hint_norm(value)


def _amir_meta_hint_apply_to_keywords(context, result, hint_text):
    positive, negative = _amir_meta_hint_parse(hint_text)

    keywords = [
        item.strip()
        for item in str(result.get("keywords") or "").split(",")
        if item.strip()
    ]

    caption = str(result.get("caption") or "")
    alt_text = str(result.get("alt_text") or "")

    evidence = " ".join(
        str(value or "")
        for value in [
            caption,
            alt_text,
            result.get("keywords"),
        ]
    )

    cleaned = []
    seen = set()

    for keyword in keywords:
        key = _amir_meta_hint_keyword_key(keyword)

        if not key or key in seen:
            continue

        if negative and _amir_meta_hint_blocked_by_negative(key, negative):
            continue

        seen.add(key)
        cleaned.append(key)

    for phrase in positive:
        key = _amir_meta_hint_keyword_key(phrase)

        if not key or key in seen:
            continue

        if negative and _amir_meta_hint_blocked_by_negative(key, negative):
            continue

        if _amir_meta_hint_supported(key, evidence):
            seen.add(key)
            cleaned.append(key)

    if len(cleaned) < 5:
        result["keywords"] = ""
    else:
        result["keywords"] = ", ".join(cleaned[:8])
    return result


try:
    _amir_original_build_metadata_from_context_with_hints
except NameError:
    _amir_original_build_metadata_from_context_with_hints = build_metadata_from_context


def build_metadata_from_context(
    context,
    model_caption="",
    model_alt_text="",
    model_keywords="",
    variant=0,
):
    result = _amir_original_build_metadata_from_context_with_hints(
        context=context,
        model_caption=model_caption,
        model_alt_text=model_alt_text,
        model_keywords=model_keywords,
        variant=variant,
    )

    try:
        hint_text = _amir_meta_hint_get(context or {})

        if hint_text:
            result = _amir_meta_hint_apply_to_keywords(context or {}, dict(result), hint_text)
    except Exception as exc:
        try:
            print(f"[WARN] Hint keyword metadata filter failed: {exc}")
        except Exception:
            pass

    return result
# AMIR_HINT_KEYWORDS_METADATA_SOFT_EVIDENCE_V1_END
