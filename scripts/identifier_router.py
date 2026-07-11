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

import argparse
import base64
import io
import json
import os
import re
import sys
import subprocess
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any


# Force UTF-8 output on Windows consoles and subprocess pipes.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}

CATEGORY_MENU_LEAK = "aircraft | vehicle | boat | train"

AIRLINE_ALIASES = [
    ("airHaifa", ["airhaifa", "air haifa"]),
    ("airBaltic", ["airbaltic", "air baltic"]),
    ("TUS Air", ["tus air"]),
    ("Aegean Airlines", ["aegean airlines", "aegean"]),
    ("Cyprus Airways", ["cyprus airways"]),
    ("Austrian Airlines", ["austrian airlines", "austrian"]),
    ("Arkia", ["arkia"]),
    ("Lauda Europe", ["lauda europe", "lauda"]),
    ("World2Fly", ["world2fly", "world 2 fly"]),
    ("Singapore Airlines Cargo", ["singapore airlines cargo"]),
    ("Singapore Airlines", ["singapore airlines"]),
    ("Transavia", ["transavia"]),
    ("KLM", ["klm"]),
    ("EasyJet", ["easyjet", "easy jet"]),
    ("Air Canada", ["air canada"]),
    ("Air France", ["air france", "airfrance"]),
    ("British Airways", ["british airways"]),
    ("Lufthansa", ["lufthansa"]),
    ("Ryanair", ["ryanair"]),
    ("Wizz Air", ["wizz air", "wizzair"]),
    ("TUI", ["tui"]),
    ("Emirates", ["emirates"]),
    ("Qatar Airways", ["qatar airways"]),
    ("Turkish Airlines", ["turkish airlines"]),
    ("DHL", ["dhl"]),
    ("UPS", ["ups"]),
]


def log(message: str) -> None:
    print(message, flush=True)


def clean_text(value: Any) -> str:
    if value is None:
        return ""

    text = str(value)
    text = text.replace("\u00a0", " ")
    text = text.replace("_", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip().strip('"').strip("'")


def collect_images(folder: Path) -> list[Path]:
    if not folder.exists():
        raise SystemExit(f"[ERROR] Folder does not exist: {folder}")

    images = [
        path
        for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTS
    ]

    return sorted(images, key=lambda path: path.name.lower())


def choose_samples(paths: list[Path], max_samples: int) -> list[Path]:
    if max_samples <= 0 or len(paths) <= max_samples:
        return paths

    if max_samples == 1:
        return [paths[0]]

    last_index = len(paths) - 1
    indexes = {
        round(index * last_index / (max_samples - 1))
        for index in range(max_samples)
    }

    return [paths[index] for index in sorted(indexes)]


def list_values(items: Any) -> list[tuple[str, int]]:
    values: list[tuple[str, int]] = []

    if not items:
        return values

    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                value = clean_text(item.get("value", ""))
                count = item.get("count", 1)
            else:
                value = clean_text(item)
                count = 1

            try:
                count_int = int(count)
            except Exception:
                count_int = 1

            if value:
                values.append((value, max(1, count_int)))

    return values


def gather_context(item: dict[str, Any]) -> list[str]:
    context: list[str] = []

    for key in [
        "visible_text",
        "logo_or_brand",
        "airline",
        "aircraft_registration",
        "aircraft_type",
        "vehicle_make",
        "vehicle_model",
        "vehicle_type",
        "sign_text",
        "boat_name",
    ]:
        for value, count in list_values(item.get(key)):
            context.extend([value] * count)

    for evidence in item.get("evidence", []) or []:
        text = clean_text(evidence)
        if text:
            context.append(text)

    return context


def normalize_airline(value: Any, context_values: list[str]) -> str:
    text = clean_text(value)
    if not text:
        return ""

    upper = text.upper()
    context = " ".join(context_values).upper()
    haystack = clean_text(f"{text} {' '.join(context_values)}").lower()
    haystack_words = re.sub(r"[^a-z0-9]+", " ", haystack).strip()
    haystack_compact = re.sub(r"[^a-z0-9]+", "", haystack)

    if "CHINA SOUTHERN" in upper or "CHINA SOUTHERN" in context or "\u4e2d\u56fd\u5357\u65b9" in text:
        if "CARGO" in context:
            return "China Southern Cargo"
        return "China Southern Airlines"

    for display, aliases in AIRLINE_ALIASES:
        for alias in aliases:
            alias_words = re.sub(r"[^a-z0-9]+", " ", alias.lower()).strip()
            alias_compact = re.sub(r"[^a-z0-9]+", "", alias.lower())
            if alias_words and re.search(rf"(?<![a-z0-9]){re.escape(alias_words)}(?![a-z0-9])", haystack_words):
                return display
            if alias_compact and alias_compact in haystack_compact:
                return display

    if "AIRFRANCE" in upper or "AIR FRANCE" in upper:
        return "Air France"

    if "AIR CANADA" in upper:
        return "Air Canada"

    if upper == "CANADA" and "AIR CANADA" in context:
        return "Air Canada"

    if upper == "KLM" or upper.startswith("KLM "):
        return "KLM"

    if upper == "LM" and "KLM" in context:
        return ""

    if "VUELING" in upper or "UELING" in upper:
        return "Vueling"

    if "ELING.COM" in upper or "UELING.COM" in context or "ELING.COM" in context:
        return "Vueling"

    if upper in {"DOTS", "DOTTED PATTERN", "ING.COM", "PLANELY MCPLANE FACE", "PLANEY MCPLANE FACE"}:
        return ""

    return ""


def normalize_registration(value: Any) -> str:
    text = clean_text(value).upper()
    if not text:
        return ""

    text = text.replace(" ", "-")
    text = re.sub(r"[^A-Z0-9-]", "", text)
    text = re.sub(r"-+", "-", text).strip("-")

    reject = {
        "LE-MANS",
        "NA-SOUTH",
        "P-KLM",
        "LM-KLM",
        "XU",
        "PH",
        "PH-",
        "802",
        "R-450",
        "GAIRL",
    }

    if text in reject:
        return ""

    match = re.fullmatch(r"((?:[A-Z]{1,2}|4X))-([A-Z0-9]{3,5})", text)
    if not match:
        return ""

    prefix = match.group(1)
    suffix = match.group(2)

    if prefix in {"LE", "NA", "LM"}:
        return ""

    if suffix in {"KLM", "SOUTH"}:
        return ""

    return f"{prefix}-{suffix}"


def normalize_aircraft_type(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""

    upper = text.upper()
    upper = upper.replace("_", " ")

    if "777F" in upper:
        return "Boeing 777F"

    if "787-8" in upper or "787 8" in upper:
        return "Boeing 787-8"

    if "787" in upper or "DREAMLINER" in upper:
        return "Boeing 787"

    if "A321NEO" in upper or "A321 NEO" in upper or "A321-NEO" in upper:
        return "Airbus A321NEO"

    if "A321" in upper:
        return "Airbus A321"

    if "A320NEO" in upper or "A320 NEO" in upper or "A320-NEO" in upper:
        return "Airbus A320NEO"

    if "A320" in upper:
        return "Airbus A320"

    if "A319" in upper:
        return "Airbus A319"

    if "A330" in upper:
        return "Airbus A330"

    if "ERJ-190" in upper or "E190" in upper:
        return "Embraer E190"

    if "ERJ-175" in upper or "E175" in upper:
        return "Embraer E175"

    if "ERJ-170" in upper or "E170" in upper:
        return "Embraer E170"

    if "EMBRAER" in upper:
        return "Embraer"

    match = re.search(r"\bATR\s*[- ]?\s*(72|42)(?:[- ]?\s*(600|500|300))?\b", upper)
    if match:
        family = match.group(1)
        variant = match.group(2)
        if variant:
            return f"ATR {family}-{variant}"
        return f"ATR {family}"

    return ""


def merge_counter(
    items: Any,
    normalizer,
    context_values: list[str] | None = None,
) -> Counter:
    counter: Counter = Counter()

    for value, count in list_values(items):
        if context_values is None:
            normalized = normalizer(value)
        else:
            normalized = normalizer(value, context_values)

        if normalized:
            counter[normalized] += count

    return counter


def choose_aircraft_type(counter: Counter) -> str:
    if not counter:
        return ""

    specificity = {
        "Boeing 777F": 100,
        "Boeing 787-8": 100,
        "Airbus A320": 95,
        "Airbus A319": 92,
        "Airbus A330": 92,
        "Embraer E190": 95,
        "Embraer E175": 90,
        "Embraer E170": 90,
        "Boeing 787": 80,
        "Embraer": 40,
    }

    best = sorted(
        counter.items(),
        key=lambda item: (item[1], specificity.get(item[0], 0), item[0]),
        reverse=True,
    )[0]

    return best[0]


def finalize_aircraft(item: dict[str, Any]) -> dict[str, Any]:
    context_values = gather_context(item)

    airline_counter = Counter()
    for key in ["airline", "logo_or_brand", "visible_text"]:
        airline_counter.update(
            merge_counter(
                item.get(key),
                normalize_airline,
                context_values,
            )
        )

    reg_counter = Counter()
    for key in ["aircraft_registration", "visible_text"]:
        reg_counter.update(
            merge_counter(
                item.get(key),
                normalize_registration,
            )
        )

    type_counter = Counter()
    for key in ["aircraft_type", "vehicle_model", "visible_text"]:
        type_counter.update(
            merge_counter(
                item.get(key),
                normalize_aircraft_type,
            )
        )

    airline = airline_counter.most_common(1)[0][0] if airline_counter else ""
    registration = reg_counter.most_common(1)[0][0] if reg_counter else ""
    aircraft_type = choose_aircraft_type(type_counter)

    parts = [part for part in [airline, aircraft_type, registration] if part]
    final_subject = " ".join(parts).strip()

    if not final_subject:
        final_subject = clean_text(item.get("final_subject")) or "Aircraft"

    confidence = 50

    if airline:
        confidence += 15

    if aircraft_type:
        confidence += 15

    if registration:
        confidence += 20

    if airline_counter and airline_counter.most_common(1)[0][1] >= 4:
        confidence += 5

    if reg_counter and reg_counter.most_common(1)[0][1] >= 4:
        confidence += 5

    if type_counter and type_counter.most_common(1)[0][1] >= 3:
        confidence += 5

    confidence = min(99, confidence)

    return {
        "image_name": clean_text(item.get("image_name")),
        "route": "aircraft",
        "category": "aircraft",
        "subject": final_subject,
        "confidence": confidence,
        "airline": airline,
        "aircraft_type": aircraft_type,
        "aircraft_registration": registration,
        "raw_final_subject": clean_text(item.get("final_subject")),
        "raw_airline_votes": dict(airline_counter),
        "raw_type_votes": dict(type_counter),
        "raw_registration_votes": dict(reg_counter),
    }


def normalize_router_confidence(
    value: Any,
    route: str,
    subject: str,
    category: str,
    evidence: str = "",
) -> int:
    """
    Normalize router confidence without making the light routes pretend to be perfect.
    """
    try:
        confidence = int(float(value))
    except (TypeError, ValueError):
        confidence = 50

    route_text = clean_text(route).lower()
    subject_text = clean_text(subject).lower()
    category_text = clean_text(category).lower()
    evidence_text = clean_text(evidence).lower()

    weak_subjects = {
        "",
        "unknown",
        "unknown scene",
        "object",
        "scene",
        "image",
        "photo",
        "picture",
        "landscape | cityscape | architecture | waterway | object | unknown",
    }

    if route_text == "scene":
        if subject_text in weak_subjects:
            return 20

        if confidence <= 1 and evidence_text:
            return 50

        if confidence > 60:
            return 60

        return max(confidence, 50)

    if route_text in {"vehicle", "boat", "visual", "visual_evidence"}:
        if category_text in {"vehicle", "boat"}:
            return max(confidence, 80)

    return max(1, min(confidence, 99))


def clean_router_subject(subject: str, category: str) -> str:
    """
    Clean router subjects without inventing new facts.
    """
    text = clean_text(subject)
    category_text = clean_text(category).lower()

    text = re.sub(r"\s+", " ", text).strip()

    if category_text == "vehicle":
        text = re.sub(r"\bSCANIA\b", "Scania", text)
        text = re.sub(r"\bSCAIA\b", "Scania", text)
        text = re.sub(r"\bTruck vehicle\b", "truck", text, flags=re.IGNORECASE)
        text = re.sub(r"\btruck truck\b", "truck", text, flags=re.IGNORECASE)
        return text.strip()

    if category_text == "boat":
        text = re.sub(r"^boat\s+", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"\bSMOKE BOAT\b", "Smoke Boat", text, flags=re.IGNORECASE)
        text = re.sub(r"\bSMOKEBOAT\b", "Smoke Boat", text, flags=re.IGNORECASE)
        return text.strip()

    return text

def normalize_scene_category(category: str, subject: str, evidence: str = "") -> str:
    """
    Convert scene category output into one safe category.
    Specific visual evidence wins over the model's generic category.
    """
    category_text = clean_text(category).lower()
    subject_text = clean_text(subject).lower()
    evidence_text = clean_text(evidence).lower()
    combined = f"{category_text} {subject_text} {evidence_text}"

    if any(word in combined for word in ["canal", "waterway", "waterfront", "harbor", "harbour", "reflection in the water"]):
        return "waterway"

    if any(word in combined for word in ["street market", "market stalls", "street", "urban", "city", "people", "bicycles"]):
        return "cityscape"

    if any(word in combined for word in ["gothic", "window", "facade", "brick", "building", "church", "tower", "architecture"]):
        return "architecture"

    if any(word in combined for word in ["mountain", "lake", "field", "fields", "forest", "rural", "landscape", "sky"]):
        return "landscape"

    allowed = {
        "landscape",
        "cityscape",
        "architecture",
        "waterway",
        "object",
        "unknown",
    }

    if category_text in allowed:
        return category_text

    return "unknown"

def finalize_visual_item(item: dict[str, Any]) -> dict[str, Any]:
    category = clean_text(item.get("best_category")) or clean_text(item.get("category"))
    best_subject = clean_text(item.get("best_subject"))
    raw_subject = clean_text(item.get("final_subject"))

    if CATEGORY_MENU_LEAK in category:
        category = best_subject or "visual"

    category_lower = category.lower()

    if "vehicle" in category_lower or "truck" in category_lower or "car" in category_lower:
        category = "vehicle"
    elif "boat" in category_lower or "ship" in category_lower:
        category = "boat"

    subject = clean_router_subject(raw_subject, category)

    output_route = "visual_evidence"

    if category == "vehicle":
        output_route = "vehicle"
    elif category == "boat":
        output_route = "boat"

    confidence = normalize_router_confidence(
        80 if subject else 50,
        output_route,
        subject,
        category,
    )

    return {
        "image_name": clean_text(item.get("image_name")),
        "route": output_route,
        "category": category,
        "subject": subject,
        "confidence": confidence,
        "raw_final_subject": raw_subject,
    }

def extract_json_from_output(output: str) -> Any:
    marker = "== JSON result =="
    if marker in output:
        json_part = output.split(marker, 1)[1].strip()
    else:
        json_part = output.strip()

    decoder = json.JSONDecoder()

    for start_index, char in enumerate(json_part):
        if char not in "[{":
            continue

        try:
            value, _ = decoder.raw_decode(json_part[start_index:])
            return value
        except json.JSONDecodeError:
            continue

    raise ValueError("Could not parse JSON from child process output.")


def run_module_json(module_name: str, args: list[str]) -> Any:
    env = os.environ.copy()

    old_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(PROJECT_ROOT) if not old_pythonpath else f"{PROJECT_ROOT}{os.pathsep}{old_pythonpath}"

    env.setdefault("HF_HOME", str(PROJECT_ROOT / "data" / "models" / "huggingface_cache"))
    env.setdefault("TRANSFORMERS_CACHE", str(PROJECT_ROOT / "data" / "models" / "transformers_cache"))
    env.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

    command = [sys.executable, "-m", module_name] + args

    log("")
    log(f"[ROUTER] running: {' '.join(command)}")
    log("")

    process = subprocess.Popen(
        command,
        cwd=str(PROJECT_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    output_parts: list[str] = []

    assert process.stdout is not None

    for line in process.stdout:
        output_parts.append(line)
        print(line, end="", flush=True)

    return_code = process.wait()
    output = "".join(output_parts)

    if return_code != 0:
        raise SystemExit(f"[ERROR] Child module failed: {module_name}")

    return extract_json_from_output(output)


def image_to_base64(path: Path, max_side: int) -> str:
    from PIL import Image

    with Image.open(path) as image:
        image = image.convert("RGB")
        image.thumbnail((max_side, max_side))

        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=82, optimize=True)

    return base64.b64encode(buffer.getvalue()).decode("ascii")


def parse_llm_json(text: str) -> dict[str, Any]:
    text = text.strip()
    text = re.sub(r"^```json\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    first = text.find("{")
    last = text.rfind("}")

    if first == -1 or last == -1 or last <= first:
        return {}

    try:
        return json.loads(text[first:last + 1])
    except Exception:
        return {}


def ollama_json(
    image_path: Path,
    prompt: str,
    model: str,
    max_side: int,
    timeout: int = 180,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "prompt": prompt,
        "images": [image_to_base64(image_path, max_side)],
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_ctx": 2048,
            "num_predict": 220,
        },
    }

    request = urllib.request.Request(
        "http://127.0.0.1:11434/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8", errors="replace"))

    return parse_llm_json(data.get("response", ""))


def fast_scene_route(
    paths: list[Path],
    subject_hint: str,
    location: str,
    model: str,
    max_side: int,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []

    prompt = f"""
Return strict JSON only.

You identify the visible subject for a photography metadata workflow.

Rules:
1. Use only what is visible in the image.
2. Do not include the location in the subject unless visible readable text proves it.
3. Do not use the words photo image picture shot macro hdr.
4. Subject must be English ASCII.
5. Prefer specific scene nouns:
   canal reflection
   church tower
   brick facade
   street market
   mountain reflection
   coastal town buildings
   gothic window
   waterfront buildings
   forest trail
   lake reflection
6. Do not identify tiny incidental animals or vehicles as the main subject.
7. If unsure, use a safe descriptive subject.

Context hint from Amir:
{subject_hint}

Location hint for context only, do not copy into subject:
{location}

Return JSON:
{{
  "route": "scene",
  "category": "landscape | cityscape | architecture | waterway | object | unknown",
  "subject": "short clean subject",
  "confidence": 0,
  "evidence": "short reason"
}}
""".strip()

    for index, path in enumerate(paths, start=1):
        log(f"[ROUTER] scene probe {index}/{len(paths)}: {path.name}")

        result = ollama_json(
            image_path=path,
            prompt=prompt,
            model=model,
            max_side=max_side,
        )

        subject = clean_text(result.get("subject")) or "Unknown Scene"
        category = clean_text(result.get("category")) or "unknown"
        evidence = clean_text(result.get("evidence"))

        category = normalize_scene_category(
            category=category,
            subject=subject,
            evidence=evidence,
        )

        confidence = normalize_router_confidence(
            result.get("confidence", 50),
            "scene",
            subject,
            category,
            evidence,
        )

        results.append(
            {
                "image_name": path.name,
                "route": "scene",
                "category": category,
                "subject": subject,
                "confidence": confidence,
                "evidence": evidence,
            }
        )

    unique_subjects = {
        item["subject"].lower()
        for item in results
        if item.get("subject")
    }

    mode = "single_subject" if len(unique_subjects) == 1 else "per_image"

    return {
        "ok": True,
        "route": "scene",
        "mode": mode,
        "mixed_set": mode == "per_image",
        "results": results,
    }


def choose_route(subject_hint: str, folder: Path, explicit_route: str) -> str:
    if explicit_route != "auto":
        return explicit_route

    text = f"{subject_hint} {folder.name}".lower()

    aircraft_words = [
        "aircraft",
        "airplane",
        "aeroplane",
        "plane",
        "airline",
        "registration",
        "boeing",
        "airbus",
        "embraer",
        "aviation",
        "schiphol",
    ]

    visual_words = [
        "truck",
        "car",
        "motorcycle",
        "vehicle",
        "boat",
        "ship",
        "train",
        "tram",
        "bus",
        "sign",
        "logo",
        "text",
        "license",
        "licence",
        "plate",
        "brand",
    ]

    biology_words = [
        "bird",
        "gull",
        "duck",
        "goose",
        "plant",
        "flower",
        "blossom",
        "tree",
        "insect",
        "butterfly",
        "bee",
        "mammal",
        "animal",
        "wildlife",
    ]

    scene_words = [
        "landscape",
        "cityscape",
        "architecture",
        "urban",
        "canal",
        "waterway",
        "street",
        "building",
        "facade",
        "church",
        "town",
        "mountain",
        "lake",
        "forest",
    ]

    if any(word in text for word in aircraft_words):
        return "aircraft"

    if any(word in text for word in visual_words):
        return "visual"

    if any(word in text for word in biology_words):
        return "biology"

    if any(word in text for word in scene_words):
        return "scene"

    return "scene"


def summarize_router_result(result: dict[str, Any]) -> None:
    log("")
    log("== Router summary ==")
    log(f"route:     {result.get('route')}")
    log(f"mode:      {result.get('mode')}")
    log(f"mixed set: {result.get('mixed_set')}")

    rows = result.get("results", [])

    if not rows:
        log("[WARN] No router result rows.")
        return

    log("")

    for row in rows:
        image_name = row.get("image_name", "")
        subject = row.get("subject", "")
        confidence = row.get("confidence", "")
        log(f"{image_name} | {subject} | confidence {confidence}")



def apply_subject_seed_policy(result: dict[str, Any]) -> dict[str, Any]:
    top_route = clean_text(result.get("route")).lower()
    rows = result.get("results", [])

    if not isinstance(rows, list):
        return result

    hard_seed_routes = {"aircraft", "vehicle", "boat"}

    for row in rows:
        if not isinstance(row, dict):
            continue

        subject = clean_text(row.get("subject"))
        row_route = clean_text(row.get("route")).lower() or top_route
        category = clean_text(row.get("category")).lower()

        try:
            confidence = int(row.get("confidence", 0) or 0)
        except Exception:
            confidence = 0

        if row_route == "visual_evidence":
            if category == "vehicle":
                row_route = "vehicle"
            elif category == "boat":
                row_route = "boat"

        if row_route == "scene" and confidence < 50:
            confidence = 50
            row["confidence"] = confidence

        row["subject_seed"] = ""
        row["subject_seed_mode"] = "none"
        row["subject_seed_confidence"] = confidence
        row["subject_seed_reason"] = "No safe subject seed."

        if not subject:
            continue

        if subject.lower() in {"unknown", "unknown scene"}:
            continue

        if CATEGORY_MENU_LEAK in subject:
            continue

        if row_route in hard_seed_routes and confidence >= 75:
            row["subject_seed"] = subject
            row["subject_seed_mode"] = "hard"
            row["subject_seed_reason"] = "Specific object route with enough visual evidence."
            continue

        if row_route == "biology" and confidence >= 60:
            row["subject_seed"] = subject
            row["subject_seed_mode"] = "soft"
            row["subject_seed_reason"] = "Biology route subject should be used as a hint only."
            continue

        if row_route == "scene" and confidence >= 50:
            row["subject_seed"] = subject
            row["subject_seed_mode"] = "soft"
            row["subject_seed_reason"] = "Scene route subject should be used as a descriptive hint only."
            continue

        if confidence >= 50:
            row["subject_seed"] = subject
            row["subject_seed_mode"] = "review"
            row["subject_seed_reason"] = "Subject exists but route is not strong enough for automatic use."

    return result


def trusted_aircraft_subject_hint(subject_hint: str) -> str:
    subject = clean_text(subject_hint)
    if not subject:
        return ""

    low = subject.lower()
    if low in {"aircraft", "aviation", "airplane", "aeroplane", "plane"}:
        return ""

    words = [
        word.lower()
        for word in re.findall(r"[A-Za-z0-9]+", subject)
        if len(word) >= 2
    ]
    if len(words) < 2:
        return ""

    has_aircraft_model = bool(
        re.search(
            r"\b(?:boeing|airbus|embraer|atr|bombardier|cessna|a\d{3}|7\d{2}|e\d{3})\b",
            subject,
            flags=re.IGNORECASE,
        )
    )
    has_registration = bool(
        re.search(
            r"\b(?:PH|OO|EI|EC|LN|SE|OY|TF|HB|CS|SP|TC|YU|9H|A6|JA|HL|VH|ZK|LX|OK|OM|OE|RA|VP|VQ|XA|PT|PR|PP|LV|CC|ZS|4X|G|D|F|C|B|N)[-\s]?[A-Z0-9]{3,5}\b",
            subject,
            flags=re.IGNORECASE,
        )
    )

    if not has_aircraft_model and not has_registration:
        return ""

    return subject


def aircraft_type_from_subject_hint(subject: str) -> str:
    normalized = normalize_aircraft_type(subject)
    if normalized:
        return normalized

    match = re.search(r"\bBoeing\s+(7[0-9]{2})(?:[-\s]+([0-9]{1,4}))?\b", subject, flags=re.IGNORECASE)
    if match:
        if match.group(2):
            return f"Boeing {match.group(1)}-{match.group(2)}"
        return f"Boeing {match.group(1)}"

    match = re.search(r"\b(7[0-9]{2})(?:[-\s]+([0-9]{1,4}))?\b", subject, flags=re.IGNORECASE)
    if match:
        if match.group(2):
            return f"Boeing {match.group(1)}-{match.group(2)}"
        return f"Boeing {match.group(1)}"

    return ""


def aircraft_registration_from_subject_hint(subject: str) -> str:
    match = re.search(
        r"\b((?:PH|OO|EI|EC|LN|SE|OY|TF|HB|CS|SP|TC|YU|9H|A6|JA|HL|VH|ZK|LX|OK|OM|OE|RA|VP|VQ|XA|PT|PR|PP|LV|CC|ZS|4X|G|D|F|C|B)[-\s]?[A-Z0-9]{3,5}|N[0-9][0-9A-Z]{2,5})\b",
        subject,
        flags=re.IGNORECASE,
    )
    if not match:
        return ""

    return normalize_registration(match.group(1))


def aircraft_airline_from_subject_hint(subject: str) -> str:
    match = re.search(
        r"\b(?:Boeing|Airbus|Embraer|ATR|Bombardier|Cessna|A\d{3}|7\d{2}|E\d{3})\b",
        subject,
        flags=re.IGNORECASE,
    )
    if not match:
        return ""

    return clean_text(subject[:match.start()]).strip(" -_,.;:")


def aircraft_subject_hint_result(args: argparse.Namespace, sample_paths: list[Path], subject: str) -> dict[str, Any]:
    aircraft_type = aircraft_type_from_subject_hint(subject)
    registration = aircraft_registration_from_subject_hint(subject)
    airline = aircraft_airline_from_subject_hint(subject)

    results = [
        {
            "image_name": path.name,
            "route": "aircraft",
            "category": "aircraft",
            "subject": subject,
            "confidence": 99,
            "airline": airline,
            "aircraft_type": aircraft_type,
            "aircraft_registration": registration,
            "raw_final_subject": subject,
            "source": "trusted_aviation_subject_hint",
        }
        for path in sample_paths
    ]

    return {
        "ok": True,
        "route": "aircraft",
        "mode": "single_subject",
        "mixed_set": False,
        "results": results,
        "raw_count": len(results),
        "source": "trusted_aviation_subject_hint",
    }


def run_aircraft_route(args: argparse.Namespace, sample_paths: list[Path]) -> dict[str, Any]:
    trusted_subject = trusted_aircraft_subject_hint(args.subject_hint)
    if trusted_subject:
        log("[ROUTER] aviation subject hint trusted; skipping visual aircraft identification.")
        return aircraft_subject_hint_result(args, sample_paths, trusted_subject)

    visual_args = [
        "--folder",
        str(args.folder),
        "--subject-hint",
        args.subject_hint,
        "--limit",
        str(len(sample_paths)),
        "--max-crops",
        str(args.max_crops),
    ]

    if args.location:
        visual_args.extend(["--location", args.location])

    raw = run_module_json("scripts.identifier_visual_evidence", visual_args)

    if not isinstance(raw, list):
        raise SystemExit("[ERROR] Expected list result from visual evidence.")

    finalized = [finalize_aircraft(item) for item in raw]

    unique_subjects = {
        item["subject"].lower()
        for item in finalized
        if item.get("subject")
    }

    registrations = {
        item["aircraft_registration"]
        for item in finalized
        if item.get("aircraft_registration")
    }

    airlines = {
        item["airline"]
        for item in finalized
        if item.get("airline")
    }

    mixed_set = len(unique_subjects) > 1 or len(registrations) > 1 or len(airlines) > 1

    return {
        "ok": True,
        "route": "aircraft",
        "mode": "per_image" if mixed_set else "single_subject",
        "mixed_set": mixed_set,
        "results": finalized,
        "raw_count": len(raw),
    }


def run_visual_route(args: argparse.Namespace, sample_paths: list[Path]) -> dict[str, Any]:
    visual_args = [
        "--folder",
        str(args.folder),
        "--subject-hint",
        args.subject_hint,
        "--limit",
        str(len(sample_paths)),
        "--max-crops",
        str(args.max_crops),
    ]

    if args.location:
        visual_args.extend(["--location", args.location])

    raw = run_module_json("scripts.identifier_visual_evidence", visual_args)

    if not isinstance(raw, list):
        raise SystemExit("[ERROR] Expected list result from visual evidence.")

    finalized = [finalize_visual_item(item) for item in raw]

    unique_subjects = {
        item["subject"].lower()
        for item in finalized
        if item.get("subject")
    }

    mixed_set = len(unique_subjects) > 1

    return {
        "ok": True,
        "route": "visual",
        "mode": "per_image" if mixed_set else "single_subject",
        "mixed_set": mixed_set,
        "results": finalized,
        "raw_count": len(raw),
    }


def _biology_core_subject(subject: str) -> str:
    text = clean_text(subject).lower()
    if not text or text in {"bird", "birds", "bird in natural setting"}:
        return ""
    if any(word in text for word in ["parakeet", "parrot"]):
        return "parakeet"
    if any(word in text for word in ["dove", "pigeon"]):
        return "dove_pigeon"
    if any(word in text for word in ["raven", "crow"]):
        return "crow_raven"
    text = re.sub(r"\b(?:perched|perch|flying|flight|on|in|at|over|natural|setting|rail)\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _biology_per_image_results(raw: dict[str, Any]) -> list[dict[str, Any]]:
    details = raw.get("details")
    if not isinstance(details, list):
        return []

    best_visual_by_image: dict[str, dict[str, Any]] = {}
    best_species_by_image: dict[str, dict[str, Any]] = {}
    for item in details:
        if not isinstance(item, dict) or not item.get("ok"):
            continue
        image_path = clean_text(item.get("image_path"))
        subject = clean_text(item.get("subject"))
        if not image_path or not subject:
            continue
        confidence = int(item.get("confidence", 0) or 0)
        is_bioclip = "bioclip" in str(item.get("source", "")).lower()
        if is_bioclip:
            generic_species = {
                "animal",
                "bird",
                "birds",
                "bird in natural setting",
                "parakeet",
                "parrot",
                "dove",
                "pigeon",
            }
            if confidence >= 85 and subject.lower() not in generic_species:
                current = best_species_by_image.get(image_path)
                if current is None or confidence > int(current.get("confidence", 0) or 0):
                    best_species_by_image[image_path] = item
            continue

        current = best_visual_by_image.get(image_path)
        if current is None or confidence > int(current.get("confidence", 0) or 0):
            best_visual_by_image[image_path] = item

    results = []
    for image_path, visual_item in sorted(best_visual_by_image.items()):
        species_item = best_species_by_image.get(image_path)
        item = visual_item
        if species_item:
            visual_subject = clean_text(visual_item.get("subject"))
            species_subject = clean_text(species_item.get("subject"))
            visual_core = _biology_core_subject(visual_subject)
            species_core = _biology_core_subject(species_subject)
            generic_biology_tokens = {
                "animal", "bird", "birds", "parakeet", "parrot", "dove", "pigeon",
                "crow", "raven", "duck", "goose", "swan", "heron", "stork", "raptor",
                "mammal", "horse", "cow", "sheep", "goat", "deer", "dog", "cat",
                "rabbit", "fox", "monkey", "lion", "insect", "butterfly", "fly",
                "bee", "bumblebee", "wasp", "dragonfly", "damselfly", "beetle",
                "spider", "flower", "flowers", "blossom", "blossoms", "branch",
                "plant", "mushroom", "fungus", "lichen", "moss",
            }
            visual_tokens = set(re.findall(r"[a-z]+", visual_subject.lower()))
            generic_visual = bool(visual_tokens & generic_biology_tokens)
            if visual_core in {"parakeet", "dove_pigeon", "crow_raven"} or visual_core == species_core or generic_visual:
                item = species_item
        results.append(
            {
                "image_name": Path(image_path).name,
                "route": "biology",
                "category": clean_text(visual_item.get("category") or raw.get("category")),
                "subject": clean_text(item.get("subject")),
                "confidence": int(item.get("confidence", 0) or 0),
            }
        )
    return results


def run_biology_route(args: argparse.Namespace, sample_paths: list[Path]) -> dict[str, Any]:
    biology_args = [
        "--folder",
        str(args.folder),
        "--subject-hint",
        args.subject_hint,
        "--max-samples",
        str(len(sample_paths)),
    ]

    if args.location:
        biology_args.extend(["--location", args.location])

    raw = run_module_json("scripts.identifier_biology_runner", biology_args)

    if not isinstance(raw, dict):
        raise SystemExit("[ERROR] Expected dict result from biology route.")

    per_image = _biology_per_image_results(raw)
    core_subjects = {
        core
        for core in (_biology_core_subject(item.get("subject", "")) for item in per_image)
        if core
    }
    mixed_set = len(core_subjects) > 1

    if mixed_set and per_image:
        return {
            "ok": True,
            "route": "biology",
            "mode": "per_image",
            "mixed_set": True,
            "results": per_image,
            "raw": raw,
        }

    return {
        "ok": True,
        "route": "biology",
        "mode": "single_subject",
        "mixed_set": False,
        "results": [
            {
                "image_name": "",
                "route": "biology",
                "category": clean_text(raw.get("category")),
                "subject": clean_text(raw.get("subject")),
                "confidence": raw.get("confidence", 0),
            }
        ],
        "raw": raw,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()

    parser.add_argument("--folder", required=True)
    parser.add_argument("--subject-hint", default="")
    parser.add_argument("--location", default="")
    parser.add_argument(
        "--route",
        default="auto",
        choices=["auto", "aircraft", "visual", "biology", "scene"],
    )
    parser.add_argument("--max-samples", type=int, default=6)
    parser.add_argument("--max-crops", type=int, default=10)
    parser.add_argument("--ollama-model", default="qwen2.5vl:7b")
    parser.add_argument("--fast-image-max-side", type=int, default=768)
    parser.add_argument("--json-out", default="")
    parser.add_argument("--print-json", action="store_true")

    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    args.folder = Path(args.folder)

    images = collect_images(args.folder)
    if not images:
        raise SystemExit(f"[ERROR] No images found in folder: {args.folder}")

    sample_paths = choose_samples(images, args.max_samples)
    route = choose_route(args.subject_hint, args.folder, args.route)

    log("== Identifier router ==")
    log(f"folder:        {args.folder}")
    log(f"images:        {len(images)}")
    log(f"samples:       {len(sample_paths)}")
    log(f"subject hint:  {args.subject_hint}")
    log(f"location hint: {args.location}")
    log(f"route:         {route}")

    if route == "aircraft":
        result = run_aircraft_route(args, sample_paths)
    elif route == "visual":
        result = run_visual_route(args, sample_paths)
    elif route == "biology":
        result = run_biology_route(args, sample_paths)
    else:
        result = fast_scene_route(
            paths=sample_paths,
            subject_hint=args.subject_hint,
            location=args.location,
            model=args.ollama_model,
            max_side=args.fast_image_max_side,
        )

    result = apply_subject_seed_policy(result)

    summarize_router_result(result)

    if args.json_out:
        output_path = Path(args.json_out)
    else:
        output_path = PROJECT_ROOT / "data" / "identifier_router_last.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    log("")
    log(f"[OK] Router JSON saved: {output_path}")

    if args.print_json:
        log("")
        log("== Router JSON ==")
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
