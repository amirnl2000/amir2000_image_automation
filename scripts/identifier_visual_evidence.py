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
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps


# Force UTF-8 output on Windows consoles and subprocess pipes.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")



DEFAULT_ENDPOINT = "http://127.0.0.1:11434/api/generate"
DEFAULT_MODEL = "qwen2.5vl:7b"

IMAGE_SUFFIXES = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".tif",
    ".tiff",
}

AIRCRAFT_REGISTRATION_PATTERNS = [
    r"\bPH[- ]?[A-Z]{3}\b",
    r"\bG[- ]?[A-Z]{4}\b",
    r"\bD[- ]?[A-Z]{4}\b",
    r"\bOO[- ]?[A-Z]{3}\b",
    r"\bF[- ]?[A-Z]{4}\b",
    r"\bEI[- ]?[A-Z0-9]{3,5}\b",
    r"\bN[0-9]{1,5}[A-Z]{0,2}\b",
    r"\b[A-Z]{1,2}[- ][A-Z0-9]{3,5}\b",
]


def _safe_text(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _safe_list(value: Any) -> list[str]:
    if value is None:
        return []

    if isinstance(value, list):
        items = value
    else:
        items = [value]

    cleaned: list[str] = []

    for item in items:
        text = _safe_text(item)

        if not text:
            continue

        if len(text) > 80:
            continue

        if text.lower() in {"unknown", "none", "n/a", "not visible", "unreadable"}:
            continue

        cleaned.append(text)

    return cleaned


def _extract_json(text: str) -> dict[str, Any]:
    raw = text.strip()

    raw = re.sub(r"^```(?:json)?", "", raw, flags=re.IGNORECASE).strip()
    raw = re.sub(r"```$", "", raw).strip()

    start = raw.find("{")
    end = raw.rfind("}")

    if start >= 0 and end > start:
        raw = raw[start:end + 1]

    try:
        data = json.loads(raw)

        if isinstance(data, dict):
            return data
    except Exception:
        pass

    return {
        "main_subject": "",
        "category": "unknown",
        "visible_text": [],
        "logo_or_brand": [],
        "airline": [],
        "aircraft_registration": [],
        "aircraft_type": [],
        "vehicle_make": [],
        "vehicle_model": [],
        "vehicle_type": [],
        "boat_name": [],
        "sign_text": [],
        "confidence": 0,
        "evidence": "",
        "parse_error": raw[:500],
    }


def _image_to_base64(image: Image.Image, max_side: int = 1400, quality: int = 86) -> str:
    image = image.convert("RGB")

    width, height = image.size
    scale = max_side / max(width, height)

    if scale != 1:
        new_size = (
            max(1, int(width * scale)),
            max(1, int(height * scale)),
        )
        image = image.resize(new_size, Image.Resampling.LANCZOS)

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality, optimize=True)

    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _make_crop(image: Image.Image, box: tuple[int, int, int, int], max_side: int) -> Image.Image:
    crop = image.crop(box)

    width, height = crop.size
    scale = max_side / max(width, height)

    if scale > 1:
        crop = crop.resize(
            (
                max(1, int(width * scale)),
                max(1, int(height * scale)),
            ),
            Image.Resampling.LANCZOS,
        )

    return crop


def build_zoom_crops(image_path: Path, max_crops: int = 12, max_side: int = 1400) -> list[tuple[str, Image.Image]]:
    image = Image.open(image_path)
    image = ImageOps.exif_transpose(image).convert("RGB")

    width, height = image.size

    crops: list[tuple[str, tuple[int, int, int, int]]] = []

    crops.append(("full", (0, 0, width, height)))

    crops.extend(
        [
            ("center_70", (int(width * 0.15), int(height * 0.15), int(width * 0.85), int(height * 0.85))),
            ("center_45", (int(width * 0.275), int(height * 0.275), int(width * 0.725), int(height * 0.725))),
            ("left_center", (0, int(height * 0.20), int(width * 0.55), int(height * 0.80))),
            ("right_center", (int(width * 0.45), int(height * 0.20), width, int(height * 0.80))),
            ("top_center", (int(width * 0.15), 0, int(width * 0.85), int(height * 0.50))),
            ("bottom_center", (int(width * 0.15), int(height * 0.50), int(width * 0.85), height)),
            ("top_left", (0, 0, int(width * 0.55), int(height * 0.55))),
            ("top_right", (int(width * 0.45), 0, width, int(height * 0.55))),
            ("bottom_left", (0, int(height * 0.45), int(width * 0.55), height)),
            ("bottom_right", (int(width * 0.45), int(height * 0.45), width, height)),
            ("middle_strip", (0, int(height * 0.33), width, int(height * 0.67))),
            ("lower_strip", (0, int(height * 0.55), width, height)),
        ]
    )

    output: list[tuple[str, Image.Image]] = []

    for crop_name, box in crops[:max_crops]:
        output.append(
            (
                crop_name,
                _make_crop(image, box, max_side=max_side),
            )
        )

    return output


def call_ollama_vision(
    image: Image.Image,
    crop_name: str,
    model: str,
    endpoint: str,
    subject_hint: str = "",
    location_hint: str = "",
    timeout: int = 180,
) -> dict[str, Any]:
    prompt = f"""
You are a precise visual evidence extractor for photography metadata.

Inspect this image crop carefully.
Crop name: {crop_name}
User subject hint: {subject_hint}
Location hint: {location_hint}

Return strict JSON only.

Fields:
{{
  "main_subject": "",
  "category": "aircraft | vehicle | boat | train | building | sign | person | plant | bird | mammal | insect | landscape | cityscape | architecture | waterway | object | unknown",
  "visible_text": [],
  "logo_or_brand": [],
  "airline": [],
  "aircraft_registration": [],
  "aircraft_type": [],
  "vehicle_make": [],
  "vehicle_model": [],
  "vehicle_type": [],
  "boat_name": [],
  "sign_text": [],
  "confidence": 0,
  "evidence": ""
}}

Rules:
1. Read visible text only if it is clearly readable.
2. For aircraft, look for airline livery, tail logo, registration number, aircraft type, engine or fuselage text.
3. For vehicles, look for make, model, type, license text only if readable.
4. For boats, look for boat name or readable markings only if readable.
5. For buildings and urban scenes, look for readable signs, shop names, station names, street signs, or landmark text.
6. Never invent registration numbers, model names, airlines, brands, or signs.
7. If the exact species, model, airline, or sign is uncertain, leave the specific field empty and use a safe main_subject.
8. confidence is 0 to 100 based only on visible evidence.
""".strip()

    payload = {
        "model": model,
        "prompt": prompt,
        "images": [
            _image_to_base64(image),
        ],
        "stream": False,
        "options": {
            "temperature": 0,
            "num_ctx": 3072,
            "num_predict": 500,
        },
    }

    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
        },
        method="POST",
    )

    start = time.time()

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))

        raw_response = data.get("response", "")
        parsed = _extract_json(raw_response)

        parsed["crop_name"] = crop_name
        parsed["source"] = "identifier_visual_evidence_v1"
        parsed["model"] = model
        parsed["elapsed_seconds"] = round(time.time() - start, 2)
        parsed["raw"] = raw_response

        return parsed

    except Exception as exc:
        return {
            "crop_name": crop_name,
            "source": "identifier_visual_evidence_v1",
            "model": model,
            "elapsed_seconds": round(time.time() - start, 2),
            "main_subject": "",
            "category": "unknown",
            "visible_text": [],
            "logo_or_brand": [],
            "airline": [],
            "aircraft_registration": [],
            "aircraft_type": [],
            "vehicle_make": [],
            "vehicle_model": [],
            "vehicle_type": [],
            "boat_name": [],
            "sign_text": [],
            "confidence": 0,
            "evidence": "",
            "error": f"{type(exc).__name__}: {exc}",
        }


def find_registration_candidates(text_values: list[str]) -> list[str]:
    joined = " ".join(text_values).upper()
    found: list[str] = []

    for pattern in AIRCRAFT_REGISTRATION_PATTERNS:
        for match in re.findall(pattern, joined, flags=re.IGNORECASE):
            value = _safe_text(match).upper().replace(" ", "-")

            if value not in found:
                found.append(value)

    return found


def _most_common(values: list[str], limit: int = 8) -> list[dict[str, Any]]:
    counter = Counter(values)

    return [
        {
            "value": value,
            "count": count,
        }
        for value, count in counter.most_common(limit)
    ]


def analyze_image_visual_evidence(
    image_path: str | Path,
    model: str = DEFAULT_MODEL,
    endpoint: str = DEFAULT_ENDPOINT,
    subject_hint: str = "",
    location_hint: str = "",
    max_crops: int = 12,
) -> dict[str, Any]:
    path = Path(image_path)

    start = time.time()
    crop_results: list[dict[str, Any]] = []

    crops = build_zoom_crops(path, max_crops=max_crops)

    for index, (crop_name, crop_image) in enumerate(crops, start=1):
        print(f"[EVIDENCE] {path.name} crop {index}/{len(crops)}: {crop_name}", flush=True)

        result = call_ollama_vision(
            image=crop_image,
            crop_name=crop_name,
            model=model,
            endpoint=endpoint,
            subject_hint=subject_hint,
            location_hint=location_hint,
        )

        crop_results.append(result)

    visible_text: list[str] = []
    signs: list[str] = []
    brands: list[str] = []
    airlines: list[str] = []
    aircraft_regs: list[str] = []
    aircraft_types: list[str] = []
    vehicle_makes: list[str] = []
    vehicle_models: list[str] = []
    vehicle_types: list[str] = []
    boat_names: list[str] = []
    subjects: list[str] = []
    categories: list[str] = []
    evidence_lines: list[str] = []

    for result in crop_results:
        visible_text.extend(_safe_list(result.get("visible_text")))
        signs.extend(_safe_list(result.get("sign_text")))
        brands.extend(_safe_list(result.get("logo_or_brand")))
        airlines.extend(_safe_list(result.get("airline")))
        aircraft_regs.extend(_safe_list(result.get("aircraft_registration")))
        aircraft_types.extend(_safe_list(result.get("aircraft_type")))
        vehicle_makes.extend(_safe_list(result.get("vehicle_make")))
        vehicle_models.extend(_safe_list(result.get("vehicle_model")))
        vehicle_types.extend(_safe_list(result.get("vehicle_type")))
        boat_names.extend(_safe_list(result.get("boat_name")))

        subject = _safe_text(result.get("main_subject"))
        category = _safe_text(result.get("category")).lower()
        evidence = _safe_text(result.get("evidence"))

        if subject:
            subjects.append(subject)

        if category and category != "unknown":
            categories.append(category)

        if evidence:
            evidence_lines.append(evidence)

    aircraft_regs.extend(find_registration_candidates(visible_text + signs + brands + airlines))

    subject_votes = _most_common(subjects)
    category_votes = _most_common(categories)

    best_subject = subject_votes[0]["value"] if subject_votes else ""
    best_category = category_votes[0]["value"] if category_votes else "unknown"

    final_subject = best_subject

    if airlines and aircraft_types:
        final_subject = f"{_most_common(airlines)[0]['value']} {_most_common(aircraft_types)[0]['value']}"
    elif airlines and best_category == "aircraft":
        final_subject = f"{_most_common(airlines)[0]['value']} Aircraft"
    elif aircraft_regs and best_category == "aircraft":
        final_subject = f"Aircraft {aircraft_regs[0]}"
    elif vehicle_makes and vehicle_types:
        final_subject = f"{_most_common(vehicle_makes)[0]['value']} {_most_common(vehicle_types)[0]['value']}"
    elif vehicle_types:
        final_subject = _most_common(vehicle_types)[0]["value"]
    elif boat_names:
        final_subject = f"Boat {boat_names[0]}"

    return {
        "ok": True,
        "image_path": str(path),
        "image_name": path.name,
        "final_subject": final_subject,
        "best_subject": best_subject,
        "best_category": best_category,
        "visible_text": _most_common(visible_text),
        "sign_text": _most_common(signs),
        "logo_or_brand": _most_common(brands),
        "airline": _most_common(airlines),
        "aircraft_registration": _most_common(aircraft_regs),
        "aircraft_type": _most_common(aircraft_types),
        "vehicle_make": _most_common(vehicle_makes),
        "vehicle_model": _most_common(vehicle_models),
        "vehicle_type": _most_common(vehicle_types),
        "boat_name": _most_common(boat_names),
        "subject_votes": subject_votes,
        "category_votes": category_votes,
        "evidence": evidence_lines[:12],
        "crop_results": crop_results,
        "elapsed_seconds": round(time.time() - start, 2),
        "source": "identifier_visual_evidence_v1",
    }


def list_images(folder: Path, limit: int = 0) -> list[Path]:
    paths = [
        path
        for path in sorted(folder.iterdir())
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    ]

    if limit > 0:
        return paths[:limit]

    return paths


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default="")
    parser.add_argument("--folder", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--max-crops", type=int, default=12)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--subject-hint", default="")
    parser.add_argument("--location", default="")

    args = parser.parse_args()

    targets: list[Path] = []

    if args.image:
        targets = [Path(args.image)]
    elif args.folder:
        targets = list_images(Path(args.folder), limit=args.limit)
    else:
        raise SystemExit("[ERROR] Provide --image or --folder")

    if not targets:
        raise SystemExit("[ERROR] No images found")

    all_results = []

    for index, path in enumerate(targets, start=1):
        print("")
        print(f"== Visual evidence {index}/{len(targets)}: {path.name} ==")

        result = analyze_image_visual_evidence(
            image_path=path,
            model=args.model,
            endpoint=args.endpoint,
            subject_hint=args.subject_hint,
            location_hint=args.location,
            max_crops=args.max_crops,
        )

        all_results.append(result)

        print("")
        print("== Evidence summary ==")
        print(f"final_subject: {result['final_subject']}")
        print(f"category:      {result['best_category']}")
        print(f"airline:       {result['airline']}")
        print(f"aircraft_reg:  {result['aircraft_registration']}")
        print(f"aircraft_type: {result['aircraft_type']}")
        print(f"brand:         {result['logo_or_brand']}")
        print(f"vehicle_make:  {result['vehicle_make']}")
        print(f"vehicle_type:  {result['vehicle_type']}")
        print(f"sign_text:     {result['sign_text']}")
        print(f"visible_text:  {result['visible_text']}")

    print("")
    print("== JSON result ==")
    print(json.dumps(all_results, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
