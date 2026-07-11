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
    keep_upper = {"KLM", "TUI", "SAS", "LOT", "ANA", "JAL", "DHL", "UPS", "ATR"}
    small = {"and", "or", "on", "in", "at", "with", "by", "of", "the", "a", "an"}
    words = []
    for index, word in enumerate(cleaned.split()):
        upper = word.upper()
        lower = word.lower()
        if upper in keep_upper:
            words.append(upper)
        elif re.search(r"[a-z][A-Z]", word):
            words.append(word)
        elif index > 0 and lower in small:
            words.append(lower)
        else:
            words.append(word[:1].upper() + word[1:])
    return " ".join(words)


def _format_registration(prefix: str, suffix: str = "") -> str:
    prefix = re.sub(r"[^A-Z0-9]+", "", str(prefix or "").upper())
    suffix = re.sub(r"[^A-Z0-9]+", "", str(suffix or "").upper())
    if not prefix:
        return ""
    if suffix:
        return f"{prefix}-{suffix}"
    return prefix


def _aircraft_registration(text: str) -> str:
    value = str(text or "").upper()
    patterns = [
        r"\b(PH|OO|EI|EC|LN|SE|OY|TF|HB|CS|SP|TC|YU|9H|A6|JA|HL|VH|ZK|LX|OK|OM|OE|RA|VP|VQ|XA|PT|PR|PP|LV|CC|ZS|4X)[-\s]?([A-Z0-9]{3,5})\b",
        r"\b(G|D|F|C)[-\s]([A-Z]{3,5})\b",
        r"\b(N[0-9][0-9A-Z]{2,5})\b",
        r"\b(B)[-\s]([0-9A-Z]{4,5})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, value)
        if not match:
            continue
        if len(match.groups()) == 1:
            return _format_registration(match.group(1))
        return _format_registration(match.group(1), match.group(2))
    return ""


def _aircraft_model(text: str) -> str:
    value = str(text or "")
    patterns = [
        (r"\bBoeing\s+(7[0-9]7(?:[-\s]?[0-9A-Z]{2,4})?)\b", "Boeing"),
        (r"\b(7[0-9]7[-\s]?[0-9A-Z]{2,4})\b", "Boeing"),
        (r"\bAirbus\s+(A[0-9]{3}(?:[-\s]?[0-9A-Z]{2,4})?)\b", "Airbus"),
        (r"\b(A[0-9]{3}(?:[-\s]?[0-9A-Z]{2,4})?)\b", "Airbus"),
        (r"\bEmbraer\s+((?:E|ERJ)[-\s]?[0-9]{3,4})\b", "Embraer"),
        (r"\bATR\s+([0-9]{2}(?:[-\s]?[0-9]{3})?)\b", "ATR"),
        (r"\bBombardier\s+([A-Z]{2,4}[-\s]?[0-9]{3,4})\b", "Bombardier"),
        (r"\bCessna\s+([0-9]{3,4}[A-Z]?)\b", "Cessna"),
    ]
    for pattern, maker in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if match:
            model = re.sub(r"\s+", "-", match.group(1).upper().replace(" ", "-"))
            return f"{maker} {model}"
    return ""


def _airline_name(text: str) -> str:
    value = str(text or "")
    airline_names = [
        "airHaifa",
        "airBaltic",
        "Transavia",
        "KLM",
        "EasyJet",
        "easyJet",
        "Tus Air",
        "TUS Air",
        "Aegean Airlines",
        "Aegean",
        "Cyprus Airways",
        "Austrian Airlines",
        "Arkia",
        "Lauda Europe",
        "World2Fly",
        "WORLD2FLY",
        "Singapore Airlines Cargo",
        "Singapore Airlines",
        "Air Canada",
        "Air France",
        "British Airways",
        "Lufthansa",
        "Ryanair",
        "Wizz Air",
        "TUI",
        "SAS",
        "LOT",
        "Emirates",
        "Qatar Airways",
        "Turkish Airlines",
        "Delta Air Lines",
        "United Airlines",
        "American Airlines",
        "DHL",
        "UPS",
    ]
    for name in airline_names:
        if re.search(rf"\b{re.escape(name)}\b", value, flags=re.IGNORECASE):
            return _title_subject(name)
    match = re.search(
        r"\b([A-Za-z][A-Za-z0-9]+(?:\s+[A-Za-z][A-Za-z0-9]+){0,2}\s+(?:Airlines?|Airways|Cargo))\b",
        value,
        flags=re.IGNORECASE,
    )
    if match:
        return _title_subject(match.group(1))
    return ""


def _aircraft_state(text: str) -> str:
    value = str(text or "").lower()
    if "landing gear down" in value:
        return "Landing Gear Down"
    if "final approach" in value or "on approach" in value or "approach" in value or "landing" in value:
        return "Landing"
    if "taking off" in value or "takeoff" in value or "take off" in value:
        return "Taking Off"
    if "taxiing" in value or "taxiway" in value:
        return "Taxiing"
    if "runway" in value:
        return "On Runway"
    if "in flight" in value or "flying" in value:
        return "In Flight"
    return ""


def _aircraft_subject(text: str) -> str:
    airline = _airline_name(text)
    model = _aircraft_model(text)
    registration = _aircraft_registration(text)
    state = _aircraft_state(text)
    parts = [part for part in [airline, model, registration] if part]

    if len(parts) < 2 and state:
        parts.append(state)

    if len(parts) < 2:
        return ""

    subject = _title_subject(" ".join(parts))

    if model and "-" in model:
        subject = re.sub(rf"\b{re.escape(model.replace('-', ' '))}\b", model, subject, flags=re.IGNORECASE)

    if registration and "-" in registration:
        subject = re.sub(
            rf"\b{re.escape(registration.replace('-', ' '))}\b",
            registration,
            subject,
            flags=re.IGNORECASE,
        )

    return subject


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

        specific_aircraft = _aircraft_subject(f"{subject} {label} {category} {evidence} {user_subject} {folder}")

        if specific_aircraft:
            refined["subject"] = specific_aircraft
        elif "klm" in lower:
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
