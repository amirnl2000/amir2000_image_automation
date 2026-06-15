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

import base64
import json
import re
import time
import urllib.request
from pathlib import Path
from typing import Any

from PIL import Image


SOURCE_NAME = "ollama_real_identifier_v1"
OLLAMA_ENDPOINT = "http://127.0.0.1:11434/api/generate"


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


def _image_to_base64(image_path: Path, *, max_side: int = 1024, quality: int = 85) -> str:
    image = Image.open(image_path).convert("RGB")
    image.thumbnail((max_side, max_side))

    from io import BytesIO

    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=quality, optimize=True)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()

    if not text:
        return {}

    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except Exception:
        pass

    match = re.search(r"\{.*\}", text, flags=re.DOTALL)

    if not match:
        return {}

    try:
        value = json.loads(match.group(0))
        if isinstance(value, dict):
            return value
    except Exception:
        return {}

    return {}


def _ollama_generate(model: str, prompt: str, image_b64: str, *, timeout: int = 180) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "images": [image_b64],
        "stream": False,
        "options": {
            "temperature": 0.05,
            "num_ctx": 4096,
            "num_predict": 220,
        },
    }

    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        OLLAMA_ENDPOINT,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=timeout) as response:
        parsed = json.loads(response.read().decode("utf-8", errors="replace"))

    return str(parsed.get("response", "")).strip()


def identify_image_general(
    image_path: str | Path,
    *,
    user_subject: str = "",
    location: str = "",
    folder: str = "",
    model: str = "qwen2.5vl:7b",
    fallback_model: str = "llama3.2-vision:latest",
) -> dict[str, Any]:
    image_path = Path(image_path)

    hints = {
        "typed_subject_hint": user_subject,
        "location_hint": location,
        "folder_hint": folder,
    }

    prompt = f"""
You are identifying the visible main subject of a photography image for an SEO filename.

Use the image first.
Use the hints only as context, not as the answer.

Hints:
{json.dumps(hints, ensure_ascii=True)}

Important rules:
1. Identify the main visible subject as specifically as possible.
2. If it is a bird, mammal, insect, plant, fungus, aircraft, vehicle, boat, building, street scene, landscape, sky, or night scene, say that.
3. For birds and mammals, use the common species name only when visually supported. Otherwise use a safe group such as gull, goose, duck, raptor, horse, deer, dog.
4. For plants, use the common plant or genus only when visually supported. Otherwise use a visible plant part such as white spring blossoms, flowering branch, seed heads, leaves.
5. For aircraft, use airline or model only when visible or strongly supported. Otherwise use passenger jet, commercial aircraft, airplane, helicopter.
6. For cars and motorcycles, use make or model only when visible or strongly supported. Otherwise use classic car, sports car, motorcycle.
7. Do not include location in subject_line. Location is handled elsewhere.
8. Do not use the words photo, image, picture, shot, macro, photography, Canon, EOS, lens.
9. subject_line must use only A to Z, a to z, 0 to 9, and spaces. No punctuation.
10. Keep subject_line between 3 and 9 words.

Return JSON only:
{{
  "main_type": "bird|mammal|insect|plant|fungi|aircraft|vehicle|boat|building|street|landscape|sky|night|object|people|unknown",
  "common_name": "specific visible common name or safe group",
  "species_or_model": "species model airline make if supported else empty",
  "action_context": "short visible action or setting without location",
  "subject_line": "clean filename safe subject without location",
  "confidence": 0,
  "evidence": "short visible evidence",
  "alternatives": ["up to 3 safer alternatives"]
}}
""".strip()

    image_b64 = _image_to_base64(image_path)

    started = time.time()
    used_model = model
    raw_text = ""

    try:
        raw_text = _ollama_generate(model, prompt, image_b64)
    except Exception as first_error:
        try:
            used_model = fallback_model
            raw_text = _ollama_generate(fallback_model, prompt, image_b64)
        except Exception as second_error:
            return {
                "ok": False,
                "source": SOURCE_NAME,
                "image_path": str(image_path),
                "model": used_model,
                "label": "",
                "subject": "",
                "category": "",
                "confidence": 0,
                "evidence": "",
                "alternatives": [],
                "raw": raw_text,
                "elapsed_seconds": round(time.time() - started, 2),
                "error": f"{type(first_error).__name__}: {first_error}; fallback: {type(second_error).__name__}: {second_error}",
            }

    parsed = _extract_json(raw_text)

    main_type = _ascii_clean(str(parsed.get("main_type", ""))).lower()
    common_name = _ascii_clean(str(parsed.get("common_name", "")))
    subject = _title_subject(str(parsed.get("subject_line", "")))
    evidence = _ascii_clean(str(parsed.get("evidence", "")))

    try:
        confidence = int(float(parsed.get("confidence", 0)))
    except Exception:
        confidence = 0

    if not subject and common_name:
        subject = _title_subject(common_name)

    if not main_type:
        main_type = _guess_type_from_subject(subject, common_name)

    subject = _remove_bad_words(subject)

    return {
        "ok": bool(subject),
        "source": SOURCE_NAME,
        "image_path": str(image_path),
        "model": used_model,
        "label": common_name,
        "subject": subject,
        "category": main_type,
        "confidence": max(0, min(99, confidence)),
        "evidence": evidence,
        "alternatives": parsed.get("alternatives", []) if isinstance(parsed.get("alternatives", []), list) else [],
        "raw": raw_text,
        "elapsed_seconds": round(time.time() - started, 2),
        "error": "",
    }


def _guess_type_from_subject(subject: str, label: str) -> str:
    lower = f"{subject} {label}".lower()

    if any(word in lower for word in ["gull", "goose", "duck", "swan", "bird", "kite", "heron", "stork"]):
        return "bird"

    if any(word in lower for word in ["horse", "cow", "sheep", "dog", "cat", "deer", "lion", "monkey"]):
        return "mammal"

    if any(word in lower for word in ["bee", "fly", "wasp", "butterfly", "insect", "dragonfly"]):
        return "insect"

    if any(word in lower for word in ["blossom", "flower", "plant", "branch", "tree", "leaf"]):
        return "plant"

    if any(word in lower for word in ["mushroom", "fungus"]):
        return "fungi"

    if any(word in lower for word in ["aircraft", "airplane", "aeroplane", "jet", "plane", "helicopter"]):
        return "aircraft"

    if any(word in lower for word in ["car", "motorcycle", "bike", "vehicle"]):
        return "vehicle"

    if any(word in lower for word in ["boat", "ship", "vessel"]):
        return "boat"

    return "object"


def _remove_bad_words(subject: str) -> str:
    bad = {
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

    words = [word for word in subject.split() if word.lower() not in bad]
    return _title_subject(" ".join(words))
