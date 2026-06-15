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
from typing import Any


SOURCE_NAME = "vehicle_aircraft_rules_v1"


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


def refine_vehicle_aircraft(candidate: dict[str, Any], *, user_subject: str = "", folder: str = "") -> dict[str, Any]:
    subject = str(candidate.get("subject", "") or "")
    label = str(candidate.get("label", "") or "")
    category = str(candidate.get("category", "") or "")
    evidence = str(candidate.get("evidence", "") or "")
    lower = f"{subject} {label} {category} {evidence} {user_subject} {folder}".lower()

    if not lower.strip():
        return candidate

    refined = dict(candidate)

    if any(word in lower for word in ["aircraft", "airplane", "aeroplane", "jet", "plane", "landing", "takeoff", "runway"]):
        refined["category"] = "aircraft"

        if "klm" in lower:
            refined["subject"] = "KLM Passenger Jet"
        elif "easyjet" in lower or "easy jet" in lower:
            refined["subject"] = "EasyJet Passenger Jet"
        elif "transavia" in lower:
            refined["subject"] = "Transavia Passenger Jet"
        elif "landing" in lower or "final approach" in lower:
            refined["subject"] = "Passenger Jet Landing"
        elif "takeoff" in lower or "taking off" in lower:
            refined["subject"] = "Passenger Jet Taking Off"
        elif "runway" in lower:
            refined["subject"] = "Commercial Aircraft on Runway"
        else:
            refined["subject"] = "Passenger Jet in Flight"

        refined["source"] = f"{candidate.get('source', '')}+{SOURCE_NAME}"
        refined["confidence"] = max(int(candidate.get("confidence", 0) or 0), 65)
        return refined

    if any(word in lower for word in ["boat", "ship", "vessel", "fishing"]):
        refined["category"] = "boat"

        if "fishing" in lower:
            if "sunset" in lower or "sunrise" in lower:
                refined["subject"] = "Fishing Boat at Sunset"
            else:
                refined["subject"] = "Fishing Boat on Water"
        elif "sunset" in lower or "sunrise" in lower:
            refined["subject"] = "Boat at Sunset"
        else:
            refined["subject"] = "Boat on Water"

        refined["source"] = f"{candidate.get('source', '')}+{SOURCE_NAME}"
        refined["confidence"] = max(int(candidate.get("confidence", 0) or 0), 65)
        return refined

    if any(word in lower for word in ["car", "automobile", "vehicle", "motorcycle", "scooter"]):
        refined["category"] = "vehicle"

        if "classic" in lower or "old" in lower or "vintage" in lower:
            refined["subject"] = "Classic Car on Street"
        elif "motorcycle" in lower:
            refined["subject"] = "Motorcycle on Road"
        elif "scooter" in lower:
            refined["subject"] = "Scooter on Street"
        elif "car" in lower:
            refined["subject"] = "Car on Street"
        else:
            refined["subject"] = "Vehicle on Street"

        refined["source"] = f"{candidate.get('source', '')}+{SOURCE_NAME}"
        refined["confidence"] = max(int(candidate.get("confidence", 0) or 0), 60)
        return refined

    return refined
