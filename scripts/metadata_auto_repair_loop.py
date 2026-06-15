from __future__ import annotations

import argparse
import os
import re
import sqlite3
import time
from pathlib import Path


PROJECT_ROOT = Path(os.environ.get("AMIR_PROJECT_ROOT", Path(__file__).resolve().parent.parent)).resolve()
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


BAD_PHRASES = {
    # Gear/camera leaks (matches brief's "camera/file/category words")
    "captured with",
    "photographed with",
    # Adjacent-word duplicates the structural zip check below may miss
    # because they involve a stopword or punctuation boundary.
    "showing showing",
    "showing sitting",
    "sitting showing",
    "working showing",
    "showing reflection",
    # Structural filler from deterministic metadata fallbacks.
    "a scene featuring",
    "blue sky color",
    "close texture and color fill",
    "flight wings",
    "grass and field texture fill",
    "image road with",
    "in the frame",
    "land wings",
    "lines surfaces and structure fill",
    "open space fill",
    "shape texture and color contrast fill",
    "sky color and open space",
    "sky alongside",
    "sits behind",
    "sit behind",
    "sits around",
    "sit around",
    "sits beyond",
    "sit beyond",
    "lies below",
    "lie below",
    "extends around",
    "extend around",
    "stands out on",
    "stand out on",
    "rippled water sit",
}

BAD_KEYWORDS = {
    # Camera/gear leaks
    "canon",
    "eos",
    "r5",
    "mark",
    "lens",
    "iso",
    "aperture",
    # File/format leaks
    "photo",
    "photograph",
    "image",
    "picture",
    "camera",
    "distinctive",
    "flight wings",
    "land wings",
    "markings light",
    "markings texture",
    "open space",
    "pattern texture",
    "reflection clearly",
    "sky color",
    "texture markings",
    "appear",
    "appears",
    "appearing",
    "together",
}

GEAR_WORDS = {
    "canon",
    "eos",
    "r5",
    "mark",
    "ii",
    "rf",
    "ef",
    "usm",
    "is",
    "lens",
    "camera",
    "iso",
    "aperture",
    "photography",
    "jpg",
    "jpeg",
    "png",
    "enslaved people s quarters",
    "glass ball creative series",
    "landscape frame",
    "portrait frame",
    "square frame",
    "mid light",
}

STOP_WORDS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "with",
    "in",
    "on",
    "by",
    "beside",
    "near",
    "of",
    "to",
    "at",
    "for",
    "from",
}

SURFACE_WORDS = {
    "dock",
    "pier",
    "road",
    "path",
    "street",
    "bridge",
    "bench",
    "branch",
    "branches",
}

WATER_WORDS = {
    "water",
    "canal",
    "river",
    "lake",
    "sea",
    "ocean",
    "pond",
    "reflection",
    "reflections",
}

VIEW_WORDS = {
    "side view",
    "front view",
    "wide view",
    "close view",
    "closer view",
    "distant view",
    "detail",
    "portrait",
}

GENERIC_SCENE_WORDS = {
    "scene",
    "view",
    "detail",
    "reflection",
    "reflections",
    "water",
    "canal",
    "mirror",
    "village",
    "natural",
    "light",
}

GENERIC_CATEGORY_WORDS = {
    "photography",
    "collection",
    "miscellaneous",
    "local detail",
    "natural light",
}

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

CATEGORY_CONTEXT = {
    "people creative collection": "outdoor people scene",
    "cityscape photography": "urban scene",
    "nature landscape photography": "nature scene",
    "macro photography": "macro detail",
    "architecture photography": "architectural detail",
    "night photography": "night scene",
    "water photography": "water detail",
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
_ACTION_GROUPS = {
    "airborne": {
        "fly",
        "flies",
        "flying",
        "flight",
        "soar",
        "soars",
        "soaring",
        "glide",
        "glides",
        "gliding",
    },
    "waterborne": {
        "swim",
        "swims",
        "swimming",
        "float",
        "floats",
        "floating",
        "drift",
        "drifts",
        "drifting",
    },
    "grounded": {
        "stand",
        "stands",
        "standing",
        "sit",
        "sits",
        "sitting",
        "walk",
        "walks",
        "walking",
        "run",
        "runs",
        "running",
        "rest",
        "rests",
        "resting",
        "graze",
        "grazes",
        "grazing",
        "forage",
        "forages",
        "foraging",
        "perch",
        "perches",
        "perched",
    },
}


def now_stamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def clean_spaces(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r",\s*\.", ".", text)
    return text


def strip_dangling_subject_relation(value: str) -> str:
    text = clean_spaces(value).strip(" ,.;:")

    for _ in range(3):
        updated = _DANGLING_SUBJECT_RELATION_RE.sub("", text).strip(" ,.;:")
        if updated == text:
            break
        text = updated

    return clean_spaces(text)


def weak_keyword_phrase(value: str) -> bool:
    words = re.findall(r"[a-z0-9]+", str(value or "").lower())

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


def _action_groups(value: str) -> set[str]:
    words = set(re.findall(r"[a-z0-9]+", str(value or "").lower()))
    return {
        group
        for group, group_words in _ACTION_GROUPS.items()
        if words & group_words
    }


def caption_alt_action_conflict(caption: str, alt: str) -> bool:
    caption_groups = _action_groups(caption)
    alt_groups = _action_groups(alt)

    if not caption_groups or not alt_groups:
        return False

    if caption_groups & alt_groups:
        return False

    if len(caption_groups) > 1 or len(alt_groups) > 1:
        return False

    return True


COUNTRY_SUFFIXES = (
    "Netherlands",
    "Israel",
    "Finland",
    "Belgium",
    "Germany",
    "France",
    "Italy",
    "Spain",
    "Portugal",
    "Greece",
    "Cyprus",
    "Scotland",
    "England",
    "Wales",
    "Ireland",
    "Norway",
    "Sweden",
    "Denmark",
)


def format_place_punctuation(value: str) -> str:
    text = clean_spaces(value)

    for country in COUNTRY_SUFFIXES:
        text = re.sub(
            rf"\b([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){{0,3}})\s+{re.escape(country)}\b",
            rf"\1, {country}",
            text,
        )

    return clean_spaces(text)


def humanize(value: str) -> str:
    text = str(value or "")
    text = text.replace("_", " ").replace("-", " ")
    text = re.sub(r"\bCanon\b.*$", "", text, flags=re.I)
    text = re.sub(r"\b20\d{2}\b.*$", "", text)
    text = re.sub(r"\.(jpg|jpeg|png|webp)$", "", text, flags=re.I)
    text = re.sub(r"[^A-Za-z0-9\s]", " ", text)
    text = clean_spaces(text)
    text = strip_dangling_subject_relation(text)

    words = []

    for word in text.split():
        low = word.lower()

        if low in GEAR_WORDS:
            continue

        words.append(word)

    return clean_spaces(" ".join(words))


def title_phrase(value: str) -> str:
    text = humanize(value)

    return " ".join(word[:1].upper() + word[1:].lower() for word in text.split())


def sentence_phrase(value: str) -> str:
    text = humanize(value).lower()

    if not text:
        return ""

    return text[:1].upper() + text[1:]


def lower_phrase(value: str) -> str:
    return humanize(value).lower()


def phrase_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def looks_like_file_id(value: str) -> bool:
    for word in phrase_key(value).split():
        if len(word) < 6:
            continue

        has_digit = any(ch.isdigit() for ch in word)
        has_alpha = any(ch.isalpha() for ch in word)

        if not has_digit or not has_alpha:
            continue

        if re.fullmatch(r"(?:\d+[a-z]+[a-z0-9]*\d+|[a-z]+\d{3,}[a-z0-9]*)", word):
            return True

    return False


def collapse_repeated_terms(value: str) -> str:
    words = clean_spaces(value).split()
    out = []

    for word in words:
        low = word.lower().strip(".,;:")

        if out and low == out[-1].lower().strip(".,;:"):
            continue

        out.append(word)

    text = " ".join(out)
    text = re.sub(r"\b(reflections?)\s+reflections?\b", r"\1", text, flags=re.I)
    text = re.sub(r"\b(showing)\s+\1\b", r"\1", text, flags=re.I)
    return format_place_punctuation(text)


def is_bad_phrase(value: str) -> bool:
    text = phrase_key(value)

    if not text:
        return True

    if looks_like_file_id(text):
        return True

    if text in BAD_KEYWORDS:
        return True

    if text in GENERIC_CATEGORY_WORDS:
        return True

    if re.search(r"\b(?:photography|collection|gallery|category)\b", text):
        return True

    if text in BAD_PHRASES:
        return True

    # Word-bounded substring check so a legit phrase containing a
    # short bad-phrase as a substring is not false-matched.
    for bad in BAD_PHRASES:
        if re.search(rf"\b{re.escape(bad)}\b", text):
            return True

    words = text.split()

    if weak_keyword_phrase(text):
        return True

    if len(words) < 2:
        return True

    if len(words) == 1 and words[0] in BAD_KEYWORDS:
        return True

    if len(words) > 6:
        return True

    if all(word in STOP_WORDS for word in words):
        return True

    if any(word in GEAR_WORDS for word in words):
        return True

    return False


def valid_location(value: str) -> str:
    text = title_phrase(value)
    low = text.lower()

    if not text:
        return ""

    if "photography" in low or "collection" in low:
        return ""

    if low in {"nature", "cityscape", "macro", "people", "miscellaneous"}:
        return ""

    if set(phrase_key(low).split()) and set(phrase_key(low).split()) <= TOPIC_LOCATION_WORDS:
        return ""

    return text


def category_context(folder: str) -> str:
    low = phrase_key(folder)

    if low in CATEGORY_CONTEXT:
        return CATEGORY_CONTEXT[low]

    text = humanize(folder).lower()
    text = re.sub(r"\bphotography\b", "", text)
    text = re.sub(r"\bcollection\b", "", text)
    text = clean_spaces(text)

    if not text:
        return "photography scene"

    return text


def split_phrases(value: str) -> list[str]:
    parts = []

    for chunk in str(value or "").split(","):
        chunk = humanize(chunk).lower()
        chunk = clean_spaces(chunk)

        if not chunk:
            continue

        parts.append(chunk)

    return parts


def dedupe(items: list[str]) -> list[str]:
    out = []
    seen = set()

    for item in items:
        item = clean_spaces(item)
        key = phrase_key(item)

        if not key:
            continue

        if key in seen:
            continue

        seen.add(key)
        out.append(item)

    return out


def get_value(row: sqlite3.Row, name: str) -> str:
    names = {key.lower(): key for key in row.keys()}
    real = names.get(name.lower())

    if not real:
        return ""

    return str(row[real] or "").strip()


def extract_context(row: sqlite3.Row) -> list[str]:
    subject = humanize(get_value(row, "Subject")).lower()
    location = valid_location(get_value(row, "Location")).lower()
    location_words = set(phrase_key(location).split())

    raw_parts = []

    for col in ["Keywords", "Caption", "alt_text"]:
        raw_parts.extend(split_phrases(get_value(row, col)))

    cleaned = []

    for part in raw_parts:
        key = phrase_key(part)

        if not key:
            continue

        if location_words:
            words = [word for word in key.split() if word not in location_words]

            if words != key.split():
                part = " ".join(words)
                key = phrase_key(part)

                if not key:
                    continue

        if is_bad_phrase(part):
            continue

        if subject and key == phrase_key(subject):
            continue

        if location and key == phrase_key(location):
            continue

        subject_words = set(content_words(subject))
        part_words = set(content_words(part))

        if subject_words and part_words:
            overlap = len(subject_words & part_words) / max(1, len(part_words))

            if overlap >= 0.50:
                continue

        cleaned.append(part)

    def score(item: str) -> tuple[int, int]:
        key = phrase_key(item)
        words = key.split()

        value = 0

        if any(word in key for word in SURFACE_WORDS):
            value += 30

        if any(word in key for word in WATER_WORDS):
            value += 30

        if any(view in key for view in VIEW_WORDS):
            value += 20

        if 2 <= len(words) <= 4:
            value += 15

        if len(words) == 1:
            value -= 10

        return (-value, len(words))

    return dedupe(sorted(cleaned, key=score))


def has_word(phrase: str, words: set[str]) -> bool:
    key = phrase_key(phrase)

    return any(word in key.split() for word in words)


def content_words(value: str) -> list[str]:
    return [
        word
        for word in phrase_key(value).split()
        if word not in STOP_WORDS and word not in GENERIC_SCENE_WORDS and word not in BAD_KEYWORDS
    ]


def too_close_context(context: str, subject: str) -> bool:
    context_words = set(content_words(context))
    subject_words = set(content_words(subject))

    if not context_words or not subject_words:
        return False

    if context_words <= subject_words or subject_words <= context_words:
        return True

    overlap = len(context_words & subject_words) / max(1, len(context_words | subject_words))
    return overlap >= 0.67


def article_for_surface(surface: str) -> str:
    text = clean_spaces(surface)

    if not text:
        return ""

    if text.startswith(("a ", "an ", "the ")):
        return text

    if text in {"road", "path", "street", "bridge", "bench", "dock", "pier"}:
        return f"a {text}"

    if text.startswith(("wooden dock", "wooden pier", "wooden bridge", "wooden bench")):
        return f"a {text}"

    return text


def split_subject_structure(subject_title: str) -> tuple[str, str, str]:
    subject = clean_spaces(title_phrase(subject_title))

    if not subject:
        return "", "", ""

    match = re.search(r"\bReflection\s+Of\s+(.+)$", subject, flags=re.I)

    if match:
        tail = clean_spaces(match.group(1)).strip(" ,.;:")

        if tail:
            return tail, "reflection_of", "water"

    for relation in [" in ", " on ", " with ", " beside ", " near ", " against "]:
        if relation.lower() in subject.lower():
            pattern = re.compile(re.escape(relation), flags=re.I)
            parts = pattern.split(subject, maxsplit=1)

            if len(parts) == 2:
                left = clean_spaces(parts[0]).strip(" ,.;:")
                right = clean_spaces(parts[1]).strip(" ,.;:")

                if left and right:
                    return left, relation.strip().lower(), right

    return subject, "", ""


def apply_location(text: str, location: str) -> str:
    text = clean_spaces(text)
    location = clean_spaces(location)

    if location and location.lower() not in text.lower():
        return f"{text} in {location}"

    return text


def structured_subject_sentence(subject_title: str, location: str, *, alt: bool = False, variant: int = 0) -> str:
    left, relation, right = split_subject_structure(subject_title)

    if not left:
        return ""

    left_start = sentence_phrase(left)
    left_mid = lower_phrase(left)
    right_start = sentence_phrase(right)
    right_mid = lower_phrase(right)

    if relation == "reflection_of":
        forms = [
            (
                f"{left_start} reflected in water",
                f"Water reflection with {left_mid}",
            ),
            (
                f"Water reflection with {left_mid}",
                f"{left_start} reflected in the water",
            ),
            (
                f"{left_start} in a water reflection",
                f"Reflection of {left_mid} on the water",
            ),
        ]
        caption, alt_text = forms[max(0, int(variant or 0)) % len(forms)]

        return apply_location(alt_text if alt else caption, location)

    if relation == "in" and right:
        forms = [
            (
                f"{left_start} in the {right_mid}",
                f"{left_start} surrounded by {right_mid}",
            ),
            (
                f"{left_start} among {right_mid}",
                f"{left_start} in the {right_mid}",
            ),
            (
                f"{left_start} among {right_mid}",
                f"{left_start} within {right_mid}",
            ),
        ]
        caption, alt_text = forms[max(0, int(variant or 0)) % len(forms)]
        return apply_location(alt_text if alt else caption, location)

    if relation in {"beside", "near"} and right:
        forms = [
            (
                f"{left_start} {relation} {right_mid}",
                f"{right_start} {relation} {left_mid}",
            ),
            (
                f"{left_start} {relation} {right_mid}",
                f"{left_start} {relation} {right_mid}",
            ),
        ]
        caption, alt_text = forms[max(0, int(variant or 0)) % len(forms)]
        return apply_location(alt_text if alt else caption, location)

    if relation == "on" and right:
        if alt:
            return apply_location(f"{left_start} on {right_mid}", location)

        return apply_location(f"{left_start} on {right_mid}", location)

    if relation == "with" and right:
        forms = [
            (
                f"{left_start} with {right_mid}",
                f"{right_start} beside {left_mid}",
            ),
            (
                f"{left_start} with {right_mid}",
                f"{right_start} beside {left_mid}",
            ),
            (
                f"{right_start} with {left_mid}",
                f"{left_start} with {right_mid}",
            ),
        ]
        caption, alt_text = forms[max(0, int(variant or 0)) % len(forms)]
        return apply_location(alt_text if alt else caption, location)

    if relation == "against" and right:
        if alt:
            return apply_location(f"{left_start} near {right_mid}", location)

        return apply_location(f"{left_start} against {right_mid}", location)

    return ""


def find_first_context(contexts: list[str], words: set[str], subject: str = "") -> str:
    for item in contexts:
        if subject and too_close_context(item, subject):
            continue

        if has_word(item, words):
            return item

    return ""


def find_view_context(contexts: list[str]) -> str:
    for item in contexts:
        key = phrase_key(item)

        for view in VIEW_WORDS:
            if view in key:
                return view

    return ""


def choose_subject_phrase(subject_title: str, contexts: list[str]) -> str:
    subject_key = phrase_key(subject_title)
    subject_words = set(subject_key.split())
    generic_count = len(subject_words & GENERIC_SCENE_WORDS)

    if subject_key and generic_count <= max(1, len(subject_words) // 2):
        return subject_title

    for context in contexts:
        key = phrase_key(context)
        words = set(key.split())

        if not key or key == subject_key:
            continue

        if words and len(words - GENERIC_SCENE_WORDS) >= 1:
            return title_phrase(context)

    return subject_title


def alt_from_caption(caption: str) -> str:
    text = clean_spaces(str(caption or "")).rstrip(".")

    if not text or is_bad_caption(text):
        return ""

    def finish_alt(value: str) -> str:
        value = clean_spaces(value).strip(" .")
        if not value:
            return ""
        return value[:1].upper() + value[1:] + "."

    text = re.sub(r"\b(?:featuring|showing)\b", "with", text, flags=re.I)
    text = re.sub(r"^(?:a|an|the)\s+", "", text, flags=re.I)

    def clean_alt_part(value: str) -> str:
        value = clean_spaces(value).strip(" ,")
        value = re.sub(
            r"\b(?:fly|flies|flying|swim|swims|swimming|stand|stands|standing|sit|sits|sitting|"
            r"graze|grazes|grazing|walk|walks|walking|run|runs|running|ride|rides|riding|"
            r"sail|sails|sailing|float|floats|floating|rest|rests|resting|perch|perches|"
            r"perched|feed|feeds|feeding|bloom|blooms|blooming|grow|grows|growing)\s*$",
            "",
            value,
            flags=re.I,
        )
        return clean_spaces(value).strip(" ,")

    parts = [
        clean_alt_part(part)
        for part in re.split(
            r"\b(?:and|with|under|beside|near|against|through|across|around|below|above|over|along|in|on)\b",
            text,
            flags=re.I,
        )
        if clean_alt_part(part)
    ]

    if len(parts) >= 2 and all(len(part.split()) <= 6 for part in parts[:4]):
        if len(parts) == 2:
            alt = f"{parts[0]} and {parts[1]} appear together."
        else:
            alt = f"{', '.join(parts[:-1])}, and {parts[-1]} appear together."
        return finish_alt(alt)

    return finish_alt(f"{text} appears in the photograph.")


def build_caption(row: sqlite3.Row, group_index: int) -> str:
    subject_title = title_phrase(get_value(row, "Subject")) or "Outdoor Scene"
    contexts = extract_context(row)
    subject_title = choose_subject_phrase(subject_title, contexts)
    subject = subject_title.lower()
    subject_sentence = sentence_phrase(subject_title)

    location = valid_location(get_value(row, "Location"))
    relation = split_subject_structure(subject_title)[1]

    try:
        variant = max(0, int(float(get_value(row, "series_position") or 0)) - 1)
    except Exception:
        variant = max(0, int(group_index or 0))

    if relation:
        structured = structured_subject_sentence(subject_title, location, alt=False, variant=variant)

        if structured:
            caption = collapse_repeated_terms(structured)
            return apply_series_descriptor(caption, row, fallback=variant + 1)

    base = subject_sentence
    surface = find_first_context(contexts, SURFACE_WORDS, subject)
    water = find_first_context(contexts, WATER_WORDS, subject)
    view = find_view_context(contexts)

    parts = []

    if surface:
        parts.append(f"on {article_for_surface(surface)}")

    if water and phrase_key(water) != phrase_key(surface):
        if "reflection" in phrase_key(water):
            parts.append(f"with {water}")
        else:
            parts.append(f"beside {water}")

    if not parts:
        for ctx in contexts:
            if phrase_key(ctx) != phrase_key(subject):
                if too_close_context(ctx, subject):
                    continue

                parts.append(f"with {ctx}")
                break

    relation = " ".join(parts)

    if view and view not in phrase_key(subject):
        base = f"{sentence_phrase(view)} of {subject}"
    elif not relation:
        structured = structured_subject_sentence(subject_title, location, alt=False, variant=group_index)

        if structured:
            caption = structured
            caption = collapse_repeated_terms(caption)
            return apply_series_descriptor(caption, row, fallback=group_index + 1)

    if relation.startswith("with ") and " with " in f" {subject.lower()} ":
        relation = "and " + relation[5:]

    if relation:
        caption = f"{base} {relation}"
    else:
        caption = base

    if location:
        caption = f"{caption} in {location}"

    caption = collapse_repeated_terms(caption)
    caption = clean_spaces(caption).rstrip(".") + "."

    caption = caption.replace(" with with ", " with ")
    caption = caption.replace(" beside beside ", " beside ")
    caption = caption.replace(" on on ", " on ")

    return apply_series_descriptor(caption, row, fallback=group_index + 1)


def build_alt(row: sqlite3.Row, caption: str) -> str:
    location = valid_location(get_value(row, "Location"))
    subject_title = title_phrase(get_value(row, "Subject")) or "Outdoor Scene"
    contexts = extract_context(row)
    subject_title = choose_subject_phrase(subject_title, contexts)
    subject_sentence = sentence_phrase(subject_title)
    alt = subject_sentence
    relation = split_subject_structure(subject_title)[1]

    try:
        variant = max(0, int(float(get_value(row, "series_position") or 1)) - 1)
    except Exception:
        variant = 0

    caption_alt = alt_from_caption(caption)
    if caption_alt:
        return apply_series_descriptor(caption_alt, row, fallback=variant + 1)

    if relation:
        structured = structured_subject_sentence(subject_title, location, alt=True, variant=variant)

        if structured:
            alt = collapse_repeated_terms(structured)
            return apply_series_descriptor(alt, row, fallback=variant + 1)

    surface = find_first_context(contexts, SURFACE_WORDS, subject_sentence)
    water = find_first_context(contexts, WATER_WORDS, subject_sentence)
    view = find_view_context(contexts)

    parts = []

    if surface:
        parts.append(f"on {article_for_surface(surface)}")

    if water and phrase_key(water) != phrase_key(surface):
        parts.append(f"beside {water}")

    if not parts and contexts:
        for ctx in contexts:
            if too_close_context(ctx, subject_sentence):
                continue

            parts.append(f"with {ctx}")
            break

    if view and "close" not in phrase_key(view) and view not in phrase_key(subject_sentence):
        alt = f"{sentence_phrase(view)} of {subject_sentence.lower()}"
    elif not parts:
        structured = structured_subject_sentence(subject_title, location, alt=True, variant=variant)

        if structured:
            alt = structured
            alt = collapse_repeated_terms(alt)
            return apply_series_descriptor(alt, row, fallback=variant + 1)
    else:
        alt = subject_sentence

    if parts and parts[0].startswith("with ") and " with " in f" {subject_sentence.lower()} ":
        parts[0] = "and " + parts[0][5:]

    if parts:
        alt = f"{alt} {' '.join(parts)}"

    if location:
        alt = f"{alt} in {location}"

    alt = collapse_repeated_terms(alt)
    alt = clean_spaces(alt).rstrip(".") + "."

    if phrase_key(alt) == phrase_key(caption):
        alt = alt.replace(" in Amsterdam Netherlands.", " in Amsterdam.")
        alt = alt.replace(" Netherlands.", ".")
        alt = clean_spaces(alt).rstrip(".") + "."

    return apply_series_descriptor(alt, row, fallback=variant + 1)


def int_value(row: sqlite3.Row, name: str, default: int = 0) -> int:
    try:
        return int(float(get_value(row, name) or default))
    except Exception:
        return default


def series_position_value(row: sqlite3.Row, fallback: int = 1) -> int:
    value = int_value(row, "series_position", 0)
    if value > 0:
        return value

    name = get_value(row, "File_Name") or get_value(row, "Original_File_Name")
    match = re.search(r"_(\d{3,5})(?:\.[A-Za-z0-9]+)?$", str(name or ""))
    if match:
        try:
            return max(1, int(match.group(1)))
        except Exception:
            pass

    return max(1, int(fallback or 1))


def series_count_value(row: sqlite3.Row) -> int:
    value = int_value(row, "series_count", 0)
    if value > 1:
        return value

    name = get_value(row, "File_Name")
    if re.search(r"_(\d{3,5})(?:\.[A-Za-z0-9]+)?$", str(name or "")):
        return max(2, value)

    return max(1, value or 1)


def series_descriptor(row: sqlite3.Row, fallback: int = 1) -> str:
    return ""


def apply_series_descriptor(text: str, row: sqlite3.Row, fallback: int = 1) -> str:
    text = clean_spaces(str(text or "")).rstrip(".")
    descriptor = series_descriptor(row, fallback=fallback)

    if not text or not descriptor:
        return clean_spaces(text).rstrip(".") + "." if text else ""

    key = phrase_key(text)
    descriptor_key = phrase_key(descriptor)
    if descriptor_key and descriptor_key not in key:
        article = "an" if descriptor[0].lower() in {"a", "e", "i", "o", "u"} else "a"
        if descriptor.startswith("primary"):
            text = f"{text} from the {descriptor}"
        else:
            text = f"{text} from {article} {descriptor}"

    return clean_spaces(text).rstrip(".") + "."


def visual_keyword_items(row: sqlite3.Row) -> list[str]:
    items: list[str] = []
    variant = phrase_key(get_value(row, "visual_variant")).replace(" ", "-")
    width = int_value(row, "Width", 0)
    height = int_value(row, "Height", 0)
    series_count = series_count_value(row)
    series_position = series_position_value(row)

    if "low-light" in variant:
        items.append("low light")
    elif "bright-light" in variant or "high-light" in variant:
        items.append("bright light")

    if series_count > 1:
        descriptor = series_descriptor(row, fallback=series_position)
        if descriptor:
            items.append(descriptor)

    return items


def text_keyword_items(*values: str) -> list[str]:
    items: list[str] = []
    action_tail_words = {
        "fly",
        "flies",
        "flying",
        "swim",
        "swims",
        "swimming",
        "stand",
        "stands",
        "standing",
        "sit",
        "sits",
        "sitting",
        "graze",
        "grazes",
        "grazing",
        "walk",
        "walks",
        "walking",
        "run",
        "runs",
        "running",
        "ride",
        "rides",
        "riding",
        "sail",
        "sails",
        "sailing",
        "float",
        "floats",
        "floating",
        "rest",
        "rests",
        "resting",
        "perch",
        "perches",
        "perched",
        "feed",
        "feeds",
        "feeding",
        "appear",
        "appears",
        "appearing",
        "shape",
        "shapes",
        "define",
        "defines",
        "bloom",
        "blooms",
        "blooming",
        "grow",
        "grows",
        "growing",
    }
    action_keyword_map = {
        "fly": "in flight",
        "flies": "in flight",
        "flying": "in flight",
        "swim": "swimming",
        "swims": "swimming",
        "swimming": "swimming",
        "graze": "grazing",
        "grazes": "grazing",
        "grazing": "grazing",
        "ride": "riding",
        "rides": "riding",
        "riding": "riding",
        "walk": "walking",
        "walks": "walking",
        "walking": "walking",
        "sail": "sailing",
        "sails": "sailing",
        "sailing": "sailing",
        "bloom": "blooming",
        "blooms": "blooming",
        "blooming": "blooming",
        "perch": "perched",
        "perches": "perched",
        "perched": "perched",
    }

    for value in values:
        segments = re.split(
            r"\b(?:and|with|under|beside|near|against|through|across|around|below|above|over|along|in|on)\b|[,.;:/]+",
            str(value or ""),
            flags=re.I,
        )

        for segment in segments:
            words = content_words(segment)

            if words and words[-1] in action_keyword_map and len(words) >= 2:
                action_phrase = action_keyword_map[words[-1]]
                subject_phrase = " ".join(words[:-1][-4:])
                if subject_phrase:
                    items.append(subject_phrase)
                if action_phrase == "in flight":
                    items.append(f"{subject_phrase} in flight")
                    items.append(f"flying {subject_phrase}")
                else:
                    items.append(f"{action_phrase} {subject_phrase}")

            while words and words[-1] in action_tail_words:
                words.pop()

            for size in [3, 2]:
                for index in range(0, max(0, len(words) - size + 1)):
                    item = " ".join(words[index:index + size])
                    if item and not is_bad_phrase(item):
                        items.append(item)

    return dedupe(items)


def rotate_series_items(items: list[str], row: sqlite3.Row) -> list[str]:
    series_count = int_value(row, "series_count", 1)
    series_position = max(1, int_value(row, "series_position", 1))

    if series_count <= 1 or series_position <= 1 or len(items) <= 4:
        return items

    head = items[:1]
    tail = items[1:]
    shift = (series_position - 1) % len(tail)
    return head + tail[shift:] + tail[:shift]


def prune_nested_keyword_items(items: list[str], min_count: int = 6) -> list[str]:
    keyed = [(item, phrase_key(item)) for item in dedupe(items) if phrase_key(item)]
    kept: list[str] = []
    removed = 0
    keep_nested_tails = {
        "sky",
        "water",
        "grass",
        "field",
        "tree",
        "trees",
        "flower",
        "flowers",
        "plumage",
        "wings",
    }

    for item, key in keyed:
        words = key.split()
        is_nested_fragment = (
            len(words) <= 2
            and not (len(words) == 2 and words[-1] in keep_nested_tails)
            and any(
                other_key != key
                and len(other_key.split()) > len(words)
                and re.search(rf"\b{re.escape(key)}\b", other_key)
                for _other_item, other_key in keyed
            )
        )

        if is_nested_fragment and len(keyed) - removed - 1 >= min_count:
            removed += 1
            continue

        kept.append(item)

    return kept


def build_keywords(row: sqlite3.Row) -> str:
    subject = humanize(get_value(row, "Subject")).lower()
    contexts = extract_context(row)
    caption = get_value(row, "Caption")
    alt_text = get_value(row, "alt_text")
    text_items = text_keyword_items(caption, alt_text)

    items = []
    subject_items = []
    subject_item_keys = set()

    if subject:
        subject_items = [subject]

        words = content_words(subject)
        raw_words = [
            word
            for word in phrase_key(subject).split()
            if word not in STOP_WORDS
            and word not in BAD_KEYWORDS
            and not looks_like_file_id(word)
        ]

        for size in [4, 3, 2]:
            for index in range(0, max(0, len(raw_words) - size + 1)):
                subject_items.append(" ".join(raw_words[index:index + size]))

        for size in [3, 2]:
            for index in range(0, max(0, len(words) - size + 1)):
                subject_items.append(" ".join(words[index:index + size]))

        subject_items.extend(raw_words)
        subject_items.extend(words)
        subject_items = dedupe(subject_items)
    items.extend(visual_keyword_items(row))
    items.extend(contexts)
    items.extend(text_items)

    if subject:
        subject_item_keys = {phrase_key(item) for item in subject_items}

    clean_items = []

    def add_item(item: str, allow_nested: bool = False) -> None:
        item = clean_spaces(item.lower())
        key = phrase_key(item)

        if not key:
            return

        if key in BAD_KEYWORDS:
            return

        if weak_keyword_phrase(key):
            return

        if any(word in BAD_KEYWORDS for word in key.split()):
            return

        if is_bad_phrase(item):
            if not allow_nested or len(key.split()) != 1 or looks_like_file_id(key):
                return

        if key in BAD_KEYWORDS:
            return

        if len(key.split()) > 5:
            return

        if not allow_nested:
            for existing in clean_items:
                existing_key = phrase_key(existing)

                if key in existing_key or existing_key in key:
                    return

        clean_items.append(item)

    for item in items:
        add_item(item)

    target_count = 8

    if len(dedupe(clean_items)) < target_count:
        for item in text_items:
            add_item(item, allow_nested=True)

    if len(dedupe(clean_items)) < target_count:
        for item in subject_items:
            add_item(item, allow_nested=phrase_key(item) in subject_item_keys)

    clean_items = prune_nested_keyword_items(clean_items, min_count=6)
    clean_items = rotate_series_items(dedupe(clean_items), row)

    return ", ".join(clean_items[:14])


def is_bad_caption(value: str) -> bool:
    text = phrase_key(value)
    all_words = text.split()
    content = [word for word in all_words if word not in STOP_WORDS]

    if len(all_words) < 6 or len(content) < 3:
        return True

    # Word-bounded match prevents false hits like 'landscape frame'
    # matching 'landscape framed' or 'view of' matching 'close-up view of'.
    for bad in BAD_PHRASES:
        if re.search(rf"\b{re.escape(bad)}\b", text):
            return True

    if re.search(r"\b(?:photography|collection|gallery|category)\b", text):
        return True

    for left, right in zip(content, content[1:]):
        if left == right:
            return True

    return False


def is_bad_keywords(value: str) -> bool:
    parts = split_phrases(value)

    if len(parts) < 6:
        return True

    for part in parts:
        key = phrase_key(part)
        words = key.split()

        if not key or looks_like_file_id(key):
            return True

        if any(word in GEAR_WORDS for word in words):
            return True

        if weak_keyword_phrase(key):
            return True

        if len(words) == 1:
            if words[0] in BAD_KEYWORDS:
                return True
            continue

        if is_bad_phrase(part):
            return True

    return False


def repair_rows(db_path: Path, table: str, status_col: str, statuses: list[str]) -> dict:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    try:
        cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        col_lower = {col.lower(): col for col in cols}

        required = ["caption", "alt_text", "keywords"]

        for col in required:
            if col not in col_lower:
                raise RuntimeError(f"Missing required column: {col}")

        id_col = col_lower.get("id", "id")
        caption_col = col_lower["caption"]
        alt_col = col_lower["alt_text"]
        keywords_col = col_lower["keywords"]

        where = ""

        params = []

        if status_col in cols and statuses:
            placeholders = ",".join("?" for _ in statuses)
            where = f"WHERE {status_col} IN ({placeholders})"
            params.extend(statuses)

        rows = conn.execute(
            f"SELECT * FROM {table} {where} ORDER BY {id_col}",
            params,
        ).fetchall()

        groups = {}
        updated = 0
        unchanged = 0
        repaired_bad = 0

        for row in rows:
            group_key = (
                phrase_key(get_value(row, "Subject")),
                phrase_key(get_value(row, "Location")),
                phrase_key(get_value(row, "Folder")),
            )

            group_index = groups.get(group_key, 0)
            groups[group_key] = group_index + 1

            old_caption = get_value(row, caption_col)
            old_alt = get_value(row, alt_col)
            old_keywords = get_value(row, keywords_col)

            old_is_bad = (
                is_bad_caption(old_caption)
                or is_bad_caption(old_alt)
                or is_bad_keywords(old_keywords)
                or phrase_key(old_caption) == phrase_key(old_alt)
                or caption_alt_action_conflict(old_caption, old_alt)
            )

            if not old_is_bad:
                unchanged += 1
                continue

            if old_is_bad:
                repaired_bad += 1

            new_caption = old_caption.strip()
            new_alt = old_alt.strip()
            new_keywords = old_keywords.strip()

            def current_metadata_row() -> dict:
                data = dict(row)
                data[caption_col] = new_caption
                data[alt_col] = new_alt
                data[keywords_col] = new_keywords
                return data

            if is_bad_caption(new_caption):
                new_caption = build_caption(row, group_index)

            if (
                is_bad_caption(new_alt)
                or (phrase_key(new_caption) and phrase_key(new_caption) == phrase_key(new_alt))
                or caption_alt_action_conflict(new_caption, new_alt)
            ):
                new_alt = build_alt(row, new_caption)

            if is_bad_keywords(new_keywords):
                new_keywords = build_keywords(current_metadata_row())

            if (
                phrase_key(new_caption)
                and phrase_key(new_caption) == phrase_key(new_alt)
            ) or caption_alt_action_conflict(new_caption, new_alt):
                new_alt = build_alt(row, new_caption)

            generated_is_bad = (
                is_bad_caption(new_caption)
                or is_bad_caption(new_alt)
                or is_bad_keywords(new_keywords)
                or phrase_key(new_caption) == phrase_key(new_alt)
                or caption_alt_action_conflict(new_caption, new_alt)
            )

            if generated_is_bad:
                if is_bad_caption(new_caption):
                    new_caption = build_caption(row, group_index)
                if (
                    is_bad_caption(new_alt)
                    or phrase_key(new_caption) == phrase_key(new_alt)
                    or caption_alt_action_conflict(new_caption, new_alt)
                ):
                    new_alt = build_alt(row, new_caption)
                if is_bad_keywords(new_keywords):
                    new_keywords = build_keywords(current_metadata_row())

            generated_is_bad = (
                is_bad_caption(new_caption)
                or is_bad_caption(new_alt)
                or is_bad_keywords(new_keywords)
                or phrase_key(new_caption) == phrase_key(new_alt)
                or caption_alt_action_conflict(new_caption, new_alt)
            )

            if (
                old_caption.strip() == new_caption.strip()
                and old_alt.strip() == new_alt.strip()
                and old_keywords.strip() == new_keywords.strip()
            ):
                unchanged += 1
                continue

            conn.execute(
                f"""
                UPDATE {table}
                SET {caption_col} = ?,
                    {alt_col} = ?,
                    {keywords_col} = ?
                WHERE {id_col} = ?
                """,
                [
                    new_caption,
                    new_alt,
                    new_keywords,
                    row[id_col],
                ],
            )

            updated += 1

            if generated_is_bad and status_col in cols:
                conn.execute(
                    f"UPDATE {table} SET {status_col} = ? WHERE {id_col} = ?",
                    ["Metadata_Needs_Work", row[id_col]],
                )

        conn.commit()

        return {
            "rows_checked": len(rows),
            "rows_updated": updated,
            "rows_unchanged": unchanged,
            "rows_repaired_bad": repaired_bad,
        }

    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument("--db", default=str(PROJECT_ROOT / "data" / "review.db"))
    parser.add_argument("--table", default="review_queue")
    parser.add_argument("--status-col", default="Review_Status")
    parser.add_argument("--statuses", default="Pending,Queued")

    args = parser.parse_args()

    db_path = Path(args.db)
    statuses = [item.strip() for item in args.statuses.split(",") if item.strip()]

    log_path = LOG_DIR / f"metadata_auto_repair_loop_{now_stamp()}.txt"

    result = repair_rows(
        db_path=db_path,
        table=args.table,
        status_col=args.status_col,
        statuses=statuses,
    )

    lines = [
        "== Metadata auto repair loop ==",
        f"DB: {db_path}",
        f"Table: {args.table}",
        f"Statuses: {', '.join(statuses)}",
        "",
    ]

    for key, value in result.items():
        lines.append(f"{key}: {value}")

    log_path.write_text("\n".join(lines), encoding="utf-8")

    print("[AUTO-REPAIR] metadata compiler complete")
    print(f"[AUTO-REPAIR] rows_checked={result['rows_checked']} updated={result['rows_updated']} repaired_bad={result['rows_repaired_bad']}")
    print(f"[AUTO-REPAIR] report={log_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
