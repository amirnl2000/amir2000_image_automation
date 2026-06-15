from __future__ import annotations

import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps


def _project_root_is_valid(path: Path) -> bool:
    return (
        (path / "main_set.py").exists()
        or (path / "data" / "review.db").exists()
        or (path / "data" / "location_list.json").exists()
        or (path / "data" / "external_vocab").exists()
    )


def _find_project_root() -> Path:
    here = Path(__file__).resolve()
    candidates: list[Path] = []

    for env_name in ["AMIR_PROJECT_ROOT", "PROJECT_ROOT"]:
        value = os.getenv(env_name, "").strip()

        if value:
            candidates.append(Path(value))

    data_dir = os.getenv("DATA_DIR", "").strip()

    if data_dir:
        candidates.append(Path(data_dir).parent)

    try:
        import amir2000_config as cfg  # type: ignore

        paths = getattr(cfg, "PATHS", {})

        if isinstance(paths, dict):
            cfg_data = str(paths.get("DATA_DIR") or "").strip()

            if cfg_data:
                candidates.append(Path(cfg_data).parent)
    except Exception:
        pass

    try:
        exe_dir = Path(sys.executable).resolve().parent
        candidates.extend([exe_dir, exe_dir.parent])
    except Exception:
        pass

    try:
        cwd = Path.cwd().resolve()
        candidates.extend([cwd, cwd.parent])
    except Exception:
        pass

    for candidate in candidates:
        try:
            if _project_root_is_valid(candidate):
                return candidate.resolve()
        except Exception:
            continue

    for parent in [here.parent, *here.parents]:
        if _project_root_is_valid(parent):
            return parent

    return here.parents[1]


PROJECT_ROOT = _find_project_root()
DATA_ROOT = PROJECT_ROOT / "data"
GEONAMES_CITIES = DATA_ROOT / "external_vocab" / "geonames" / "cities500.txt"
REF_CACHE = DATA_ROOT / "identifier_reference_cache" / "inaturalist"
MODEL_ROOT = DATA_ROOT / "models"
SOURCE_NAME = "inat_reference_bioclip_v1"
COUNTRY_ALIAS_TO_NAME = {
    "usa": "United States",
    "united states": "United States",
    "netherlands": "Netherlands",
    "israel": "Israel",
    "canada": "Canada",
    "germany": "Germany",
    "belgium": "Belgium",
    "france": "France",
    "norway": "Norway",
    "ireland": "Ireland",
    "denmark": "Denmark",
    "sweden": "Sweden",
    "finland": "Finland",
    "portugal": "Portugal",
    "cyprus": "Cyprus",
    "hungary": "Hungary",
    "luxembourg": "Luxembourg",
    "italy": "Italy",
    "poland": "Poland",
}
COUNTRY_INAT_PLACE_IDS = {
    "Belgium": 7008,
    "Canada": 6712,
    "Cyprus": 10289,
    "Denmark": 8051,
    "Finland": 7020,
    "France": 6753,
    "Germany": 7207,
    "Hungary": 7399,
    "Ireland": 6718,
    "Israel": 6815,
    "Italy": 6973,
    "Luxembourg": 8147,
    "Netherlands": 7506,
    "Norway": 7016,
    "Poland": 7800,
    "Portugal": 7122,
    "Sweden": 7599,
    "United States": 1,
}
DEFAULT_FALLBACK_COUNTRIES = [
    "Netherlands",
    "United States",
    "Israel",
    "Canada",
    "Germany",
]
LOCATION_CATEGORY_TOKENS = {
    "photography",
    "collection",
    "category",
    "creative",
    "closeups",
    "miscellaneous",
}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}
_ORIGINAL_PATH_INDEX_CACHE: dict[str, str] | None = None


def _clean_text(value: Any) -> str:
    text = str(value or "").replace("_", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _norm(value: Any) -> str:
    text = _clean_text(value).lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _title(value: Any) -> str:
    text = _clean_text(value)
    small = {"and", "or", "of", "the", "a", "an", "in", "on", "with", "by"}
    words = []

    for index, word in enumerate(re.findall(r"[A-Za-z0-9']+", text)):
        lower = word.lower()
        if index > 0 and lower in small:
            words.append(lower)
        else:
            words.append(word[:1].upper() + word[1:].lower())

    return " ".join(words).strip()


def _path_key(path: Path) -> str:
    try:
        return str(path.resolve()).lower()
    except Exception:
        return str(path).lower()


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []

    for path in paths:
        if not path:
            continue

        key = _path_key(path)

        if key in seen:
            continue

        seen.add(key)
        out.append(path)

    return out


def _path_text(value: Any) -> str:
    return str(value or "").strip().strip("\"'")


def _filename_lookup_keys(name: str | Path) -> list[str]:
    base = os.path.basename(str(name or "")).strip()

    if not base:
        return []

    variants = {base}
    deprefixed = re.sub(r"^\d+[_-]+", "", base)

    if deprefixed:
        variants.add(deprefixed)

    keys: set[str] = set()

    for variant in variants:
        variant = variant.strip()

        if not variant:
            continue

        stem = Path(variant).stem
        lower_variant = variant.lower()
        lower_stem = stem.lower()
        keys.add(lower_variant)
        keys.add(lower_stem)
        keys.add(re.sub(r"\s+", "_", lower_variant))
        keys.add(re.sub(r"\s+", "_", lower_stem))

        match = re.match(r"^(.+?)_\d{8,}_\d+$", stem)

        if match:
            keys.add(match.group(1).lower())

    return [key for key in keys if key]


def _config_paths() -> dict[str, str]:
    try:
        import amir2000_config as cfg  # type: ignore

        paths = getattr(cfg, "PATHS", {})

        if isinstance(paths, dict):
            return {str(k): str(v) for k, v in paths.items() if v}
    except Exception:
        pass

    return {}


def _candidate_original_roots() -> list[Path]:
    cfg_paths = _config_paths()
    roots: list[Path] = [PROJECT_ROOT / "incoming"]

    for key in [
        "INCOMING_DIR",
        "BASE_PICK_DIR",
        "STAGED_DIR",
        "REJECTED_DIR",
        "LEGACY_BASE_PICK_DIR",
    ]:
        value = _path_text(cfg_paths.get(key))

        if value:
            roots.append(Path(value))

    base_pick = _path_text(cfg_paths.get("BASE_PICK_DIR"))
    base = Path(base_pick) if base_pick else Path.home() / "Desktop" / "xxx" / "_images_to_be_uploaded"
    roots.extend([base, base / "staged", base / "rejected", base / "_unstaged_restore"])
    extra = os.getenv("AMIR_IDENTIFIER_ORIGINAL_IMAGE_ROOTS", "").strip()

    if extra:
        roots.extend(Path(part) for part in extra.split(";") if _path_text(part))

    return _dedupe_paths(roots)


def _is_prepared_image_path(path: Path) -> bool:
    parts = {part.lower() for part in path.parts}
    return "ollama_tmp" in parts or "metadata_quality_vision_tmp" in parts


def _index_original_image_path(path: Path, index: dict[str, str]) -> None:
    if not path.is_file() or path.suffix.lower() not in IMAGE_EXTS:
        return

    path_str = str(path)

    for key in _filename_lookup_keys(path.name):
        index.setdefault(key, path_str)


def _original_image_path_index() -> dict[str, str]:
    global _ORIGINAL_PATH_INDEX_CACHE

    if _ORIGINAL_PATH_INDEX_CACHE is not None:
        return _ORIGINAL_PATH_INDEX_CACHE

    index: dict[str, str] = {}

    for root in _candidate_original_roots():
        try:
            if not root.exists() or not root.is_dir():
                continue

            for child in root.rglob("*"):
                try:
                    _index_original_image_path(child, index)
                except Exception:
                    continue
        except Exception:
            continue

    _ORIGINAL_PATH_INDEX_CACHE = index
    return index


def _resolve_original_image_path(path: Path) -> Path:
    if not _is_prepared_image_path(path):
        return path

    index = _original_image_path_index()

    for key in _filename_lookup_keys(path.name):
        found = index.get(key)

        if found and os.path.exists(found):
            return Path(found)

    return path


def _resolve_original_image_paths(paths: list[Path]) -> list[Path]:
    resolved = [_resolve_original_image_path(path) for path in paths]
    return resolved or paths


def _http_json(url: str, *, timeout: int = 30) -> dict[str, Any] | list[Any]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Amir2000ImageAutomation/1.0 local identifier",
            "Accept": "application/json",
        },
    )

    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def _venv_python_path() -> Path | None:
    for raw in [
        os.getenv("AMIR_PYTHON", ""),
        str(PROJECT_ROOT / ".venv313" / "Scripts" / "python.exe"),
        str(PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"),
    ]:
        value = str(raw or "").strip()

        if value and Path(value).exists():
            return Path(value)

    return None


def _delegate_reference_identifier_to_venv(payload: dict[str, Any]) -> dict[str, Any] | None:
    if not getattr(sys, "frozen", False):
        return None

    if os.getenv("AMIR_IDENTIFIER_INAT_DELEGATED", "") == "1":
        return None

    py = _venv_python_path()

    if py is None:
        return None

    tmp_path = None

    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            suffix=".json",
            prefix="amir_identifier_reference_",
            delete=False,
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False)
            tmp_path = handle.name

        code = r"""
import json
import sys
from scripts.identifier_biology_inaturalist import identify_biology_reference_set

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    payload = json.load(handle)

result = identify_biology_reference_set(
    payload.get("image_paths") or [],
    location=payload.get("location") or "",
    folder=payload.get("folder") or "",
    subject_hint=payload.get("subject_hint") or "",
    visual_text=payload.get("visual_text") or "",
    max_samples=int(payload.get("max_samples") or 6),
)
print(json.dumps(result, ensure_ascii=False))
"""
        env = os.environ.copy()
        env["AMIR_IDENTIFIER_INAT_DELEGATED"] = "1"
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONPATH"] = str(PROJECT_ROOT) + (
            os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
        )
        timeout = int(os.getenv("AMIR_IDENTIFIER_INAT_DELEGATE_TIMEOUT", "900") or "900")
        result = subprocess.run(
            [str(py), "-u", "-c", code, tmp_path],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

        if result.returncode != 0:
            return {
                "ok": False,
                "subject": "",
                "confidence": 0,
                "error": f"Reference delegate failed rc={result.returncode}: {(result.stderr or result.stdout or '').strip()[:500]}",
                "source": SOURCE_NAME,
            }

        text = (result.stdout or "").strip()
        start = text.find("{")
        end = text.rfind("}")

        if start < 0 or end < start:
            return {
                "ok": False,
                "subject": "",
                "confidence": 0,
                "error": f"Reference delegate returned no JSON: {text[:500]}",
                "source": SOURCE_NAME,
            }

        loaded = json.loads(text[start : end + 1])

        if isinstance(loaded, dict):
            loaded["delegated_to_venv"] = True
            return loaded
    except Exception as exc:
        return {
            "ok": False,
            "subject": "",
            "confidence": 0,
            "error": f"Reference delegate exception: {type(exc).__name__}: {exc}",
            "source": SOURCE_NAME,
        }
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    return None


def _resolve_location_geonames(location: str) -> tuple[float, float] | None:
    location_key = _norm(location)

    if not location_key or not GEONAMES_CITIES.exists():
        return None

    wanted = set(location_key.split())
    country_hint = "nl" if "netherlands" in wanted or "holland" in wanted else ""
    best: tuple[int, float, float] | None = None

    try:
        with GEONAMES_CITIES.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 15:
                    continue

                name = _norm(parts[1])
                alternates = _norm(parts[3])
                country = parts[8].lower()

                if country_hint and country != country_hint:
                    continue

                names = set(name.split()) | set(alternates.split())
                hits = len(wanted & names)

                if hits <= 0:
                    continue

                try:
                    lat = float(parts[4])
                    lng = float(parts[5])
                    population = int(parts[14] or 0)
                except Exception:
                    continue

                score = hits * 1000000 + min(population, 999999)

                if best is None or score > best[0]:
                    best = (score, lat, lng)
    except Exception:
        return None

    if best is None:
        return None

    return best[1], best[2]


def _resolve_location_online(location: str) -> tuple[float, float] | None:
    query = urllib.parse.urlencode({"format": "json", "limit": "1", "q": location})
    url = f"https://nominatim.openstreetmap.org/search?{query}"

    try:
        data = _http_json(url, timeout=20)
    except Exception:
        return None

    if not isinstance(data, list) or not data:
        return None

    first = data[0]

    try:
        return float(first["lat"]), float(first["lon"])
    except Exception:
        return None


def _has_country_hint(tokens: set[str]) -> bool:
    for alias in COUNTRY_ALIAS_TO_NAME:
        if all(part in tokens for part in alias.split()):
            return True
    return False


def _location_hint_is_category_like(location: str) -> bool:
    tokens = set(_norm(location).split())

    if not tokens:
        return False

    if _has_country_hint(tokens):
        return False

    return bool(tokens & LOCATION_CATEGORY_TOKENS)


@lru_cache(maxsize=256)
def resolve_location(location: str) -> tuple[float, float] | None:
    location = _clean_text(location)

    if not location:
        return None

    if _location_hint_is_category_like(location):
        return None

    direct = _resolve_location_geonames(location)

    if direct is not None:
        return direct

    if os.getenv("AMIR_IDENTIFIER_INAT_ONLINE_GEOCODE", "1").strip() == "0":
        return None

    return _resolve_location_online(location)


def _infer_month(image_paths: list[str | Path]) -> int:
    months: list[int] = []

    for raw_path in image_paths[:8]:
        path = Path(raw_path)

        try:
            with Image.open(path) as image:
                exif = image.getexif()
                value = exif.get(36867) or exif.get(306)

            if value:
                match = re.search(r":(\d{2}):", str(value))
                if match:
                    month = int(match.group(1))
                    if 1 <= month <= 12:
                        months.append(month)
                        continue
        except Exception:
            pass

        try:
            months.append(time.localtime(path.stat().st_mtime).tm_mon)
        except Exception:
            pass

    if not months:
        return time.localtime().tm_mon

    return max(set(months), key=months.count)


def _infer_iconic_taxa(text: str) -> list[str]:
    value = _norm(text)
    taxa: list[str] = []

    checks = [
        ("Plantae", {"plant", "plants", "flower", "flowers", "blossom", "blossoms", "tree", "trees", "leaf", "leaves", "stalk", "stalks", "stem", "stems", "spike", "spikes"}),
        ("Aves", {"bird", "birds", "avian", "goose", "geese", "duck", "ducks", "swan", "swans", "gull", "gulls", "heron", "herons", "raptor", "raptors", "pigeon", "pigeons"}),
        ("Insecta", {"insect", "insects", "butterfly", "butterflies", "bee", "bees", "wasp", "wasps", "fly", "flies", "dragonfly", "dragonflies", "beetle", "beetles", "moth", "moths"}),
        ("Fungi", {"fungus", "fungi", "mushroom", "mushrooms", "lichen", "lichens"}),
        ("Mammalia", {"mammal", "mammals", "animal", "animals", "deer", "fox", "foxes", "rabbit", "rabbits", "hare", "hares", "horse", "horses", "cow", "cows", "sheep", "dog", "dogs", "cat", "cats"}),
    ]
    tokens = set(value.split())

    for taxon, words in checks:
        if tokens & words:
            taxa.append(taxon)

    return taxa[:2]


def _taxon_items_from_species_counts(data: Any, iconic: str, seen: set[int], *, place: str = "") -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []

    results: list[dict[str, Any]] = []

    for item in data.get("results") or []:
        taxon = item.get("taxon") if isinstance(item, dict) else {}

        if not isinstance(taxon, dict):
            continue

        taxon_id = int(taxon.get("id") or 0)

        if not taxon_id or taxon_id in seen:
            continue

        photo = taxon.get("default_photo") or {}
        photo_url = ""

        if isinstance(photo, dict):
            photo_url = str(photo.get("medium_url") or photo.get("square_url") or photo.get("url") or "")

        common = _clean_text(taxon.get("preferred_common_name") or taxon.get("english_common_name") or "")
        scientific = _clean_text(taxon.get("name") or "")

        if not photo_url or not (common or scientific):
            continue

        seen.add(taxon_id)
        results.append(
            {
                "taxon_id": taxon_id,
                "common": common,
                "scientific": scientific,
                "count": int(item.get("count") or 0),
                "photo_url": photo_url,
                "iconic_taxon": iconic,
                "place": place,
            }
        )

    return results


def _species_counts(lat: float, lng: float, month: int, iconic_taxa: list[str]) -> list[dict[str, Any]]:
    per_page = int(os.getenv("AMIR_IDENTIFIER_INAT_PER_PAGE", "80") or "80")
    radius = float(os.getenv("AMIR_IDENTIFIER_INAT_RADIUS_KM", "25") or "25")
    results: list[dict[str, Any]] = []
    seen: set[int] = set()

    for iconic in iconic_taxa:
        query = urllib.parse.urlencode(
            {
                "lat": f"{lat:.6f}",
                "lng": f"{lng:.6f}",
                "radius": str(radius),
                "month": str(month),
                "iconic_taxa": iconic,
                "per_page": str(per_page),
            }
        )
        url = f"https://api.inaturalist.org/v1/observations/species_counts?{query}"

        try:
            data = _http_json(url, timeout=30)
        except Exception:
            continue

        results.extend(_taxon_items_from_species_counts(data, iconic, seen, place="nearby"))

    return results


@lru_cache(maxsize=512)
def _inat_place_id(place_name: str) -> int:
    place_name = _clean_text(place_name)

    if not place_name:
        return 0

    known_id = COUNTRY_INAT_PLACE_IDS.get(place_name)

    if known_id:
        return known_id

    query = urllib.parse.urlencode({"q": place_name})
    url = f"https://api.inaturalist.org/v1/places/autocomplete?{query}"

    try:
        data = _http_json(url, timeout=20)
    except Exception:
        return 0

    if not isinstance(data, dict):
        return 0

    for item in data.get("results") or []:
        if not isinstance(item, dict):
            continue

        display = _norm(item.get("display_name"))
        wanted = _norm(place_name)

        if display == wanted:
            try:
                return int(item.get("id") or 0)
            except Exception:
                return 0

    for item in data.get("results") or []:
        if isinstance(item, dict):
            try:
                return int(item.get("id") or 0)
            except Exception:
                return 0

    return 0


def _known_country_candidates() -> list[str]:
    configured = os.getenv("AMIR_IDENTIFIER_INAT_FALLBACK_COUNTRIES", "").strip()

    if configured:
        return [_clean_text(part) for part in configured.split(";") if _clean_text(part)]

    path = DATA_ROOT / "location_list.json"

    limit = int(os.getenv("AMIR_IDENTIFIER_INAT_FALLBACK_COUNTRY_LIMIT", "5") or "5")

    if not path.exists():
        return DEFAULT_FALLBACK_COUNTRIES[:max(1, limit)]

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return DEFAULT_FALLBACK_COUNTRIES[:max(1, limit)]

    if not isinstance(data, list):
        return DEFAULT_FALLBACK_COUNTRIES[:max(1, limit)]

    counts: Counter[str] = Counter()

    for raw in data:
        value = _norm(raw)
        tokens = set(value.split())

        for token, country in COUNTRY_ALIAS_TO_NAME.items():
            token_parts = token.split()

            if all(part in tokens for part in token_parts):
                counts[country] += 1

    countries = [country for country, _count in counts.most_common(max(1, limit))]
    return countries or DEFAULT_FALLBACK_COUNTRIES[:max(1, limit)]


def _species_counts_for_places(month: int, iconic_taxa: list[str]) -> list[dict[str, Any]]:
    per_page = int(os.getenv("AMIR_IDENTIFIER_INAT_FALLBACK_PER_PAGE", os.getenv("AMIR_IDENTIFIER_INAT_PER_PAGE", "80")) or "80")
    results: list[dict[str, Any]] = []
    seen: set[int] = set()

    for place_name in _known_country_candidates():
        place_id = _inat_place_id(place_name)

        if not place_id:
            continue

        for iconic in iconic_taxa:
            query = urllib.parse.urlencode(
                {
                    "place_id": str(place_id),
                    "month": str(month),
                    "iconic_taxa": iconic,
                    "per_page": str(per_page),
                }
            )
            url = f"https://api.inaturalist.org/v1/observations/species_counts?{query}"

            try:
                data = _http_json(url, timeout=30)
            except Exception:
                continue

            results.extend(_taxon_items_from_species_counts(data, iconic, seen, place=place_name))

    return results


@lru_cache(maxsize=1)
def _load_bioclip():
    import open_clip
    import torch

    os.environ.setdefault("HF_HOME", str(MODEL_ROOT / "huggingface_cache"))
    os.environ.setdefault("TRANSFORMERS_CACHE", str(MODEL_ROOT / "transformers_cache"))
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

    model, _preprocess_train, preprocess_val = open_clip.create_model_and_transforms(
        "hf-hub:imageomics/bioclip-2"
    )
    model.eval()
    return model, preprocess_val, torch


def _image_embedding(image: Image.Image):
    model, preprocess, torch = _load_bioclip()
    tensor = preprocess(image.convert("RGB")).unsqueeze(0)

    with torch.no_grad():
        features = model.encode_image(tensor)
        features = features / features.norm(dim=-1, keepdim=True)

    return features[0]


def _load_local_image(path: str | Path) -> Image.Image:
    with Image.open(path) as image:
        return ImageOps.exif_transpose(image).convert("RGB")


def _reference_image_path(item: dict[str, Any]) -> Path:
    key = f"{item.get('taxon_id')}_{item.get('photo_url')}"
    digest = hashlib.sha1(key.encode("utf-8", errors="replace")).hexdigest()[:20]
    return REF_CACHE / f"{digest}.jpg"


def _reference_embedding(item: dict[str, Any]):
    path = _reference_image_path(item)

    try:
        if not path.exists():
            REF_CACHE.mkdir(parents=True, exist_ok=True)
            request = urllib.request.Request(
                str(item.get("photo_url") or ""),
                headers={"User-Agent": "Amir2000ImageAutomation/1.0 local identifier"},
            )
            with urllib.request.urlopen(request, timeout=20) as response:
                data = response.read()
            path.write_bytes(data)

        with Image.open(path) as image:
            return _image_embedding(ImageOps.exif_transpose(image).convert("RGB"))
    except Exception:
        return None


def identify_biology_reference_set(
    image_paths: list[str | Path],
    *,
    location: str = "",
    folder: str = "",
    subject_hint: str = "",
    visual_text: str = "",
    max_samples: int = 6,
) -> dict[str, Any]:
    if os.getenv("AMIR_IDENTIFIER_INAT_REFERENCE_ENABLE", "1").strip() == "0":
        return {"ok": False, "subject": "", "confidence": 0, "error": "Reference identifier disabled.", "source": SOURCE_NAME}

    delegated = _delegate_reference_identifier_to_venv(
        {
            "image_paths": [str(path) for path in image_paths or []],
            "location": location,
            "folder": folder,
            "subject_hint": subject_hint,
            "visual_text": visual_text,
            "max_samples": max_samples,
        }
    )

    if delegated is not None:
        return delegated

    paths = [Path(path) for path in image_paths if Path(path).exists()]

    if not paths:
        return {"ok": False, "subject": "", "confidence": 0, "error": "No image paths.", "source": SOURCE_NAME}

    reference_paths = _resolve_original_image_paths(paths)
    recovered_original_count = sum(
        1
        for original, incoming in zip(reference_paths, paths)
        if _path_key(original) != _path_key(incoming)
    )
    context = " ".join([subject_hint, folder, visual_text])
    iconic_taxa = _infer_iconic_taxa(context)

    if not iconic_taxa:
        return {"ok": False, "subject": "", "confidence": 0, "error": "No biological trigger.", "source": SOURCE_NAME}

    month = _infer_month(reference_paths)
    samples = reference_paths[:max_samples] if len(reference_paths) <= max_samples else [reference_paths[round(i * (len(reference_paths) - 1) / (max_samples - 1))] for i in range(max_samples)]
    coords = resolve_location(location)

    if coords is not None:
        lat, lng = coords
        candidates = _species_counts(lat, lng, month, iconic_taxa)
        candidate_mode = "nearby_reference_image_similarity"
        coords_payload: dict[str, float] | None = {"lat": lat, "lng": lng}
        fallback_countries: list[str] = []
    else:
        fallback_countries = _known_country_candidates()
        candidates = _species_counts_for_places(month, iconic_taxa)
        candidate_mode = "fallback_country_reference_image_similarity"
        coords_payload = None

    if not candidates:
        return {
            "ok": False,
            "subject": "",
            "confidence": 0,
            "error": "No reference candidates.",
            "source": SOURCE_NAME,
            "mode": candidate_mode,
            "coords": coords_payload,
            "month": month,
            "iconic_taxa": iconic_taxa,
            "recovered_original_count": recovered_original_count,
            "fallback_countries": fallback_countries,
        }

    query_embeddings = []
    embed_errors: list[str] = []

    for path in samples:
        try:
            query_embeddings.append(_image_embedding(_load_local_image(path)))
        except Exception as exc:
            if len(embed_errors) < 3:
                embed_errors.append(f"{Path(path).name}: {type(exc).__name__}: {exc}")
            continue

    if not query_embeddings:
        return {
            "ok": False,
            "subject": "",
            "confidence": 0,
            "error": "Could not embed selected images."
            + (f" {' | '.join(embed_errors)}" if embed_errors else ""),
            "source": SOURCE_NAME,
            "mode": candidate_mode,
            "coords": coords_payload,
            "month": month,
            "iconic_taxa": iconic_taxa,
            "recovered_original_count": recovered_original_count,
            "fallback_countries": fallback_countries,
        }

    scored = []

    for item in candidates:
        ref_embedding = _reference_embedding(item)

        if ref_embedding is None:
            continue

        similarities = [float((query * ref_embedding).sum().item()) for query in query_embeddings]
        average = sum(similarities) / max(1, len(similarities))
        minimum = min(similarities)
        scored.append((average, minimum, int(item.get("count") or 0), item, similarities))

    if not scored:
        return {"ok": False, "subject": "", "confidence": 0, "error": "No reference embeddings.", "source": SOURCE_NAME}

    scored.sort(key=lambda row: (row[0], row[1], row[2]), reverse=True)
    best = scored[0]
    second_average = scored[1][0] if len(scored) > 1 else 0.0
    margin = best[0] - second_average

    min_average = float(os.getenv("AMIR_IDENTIFIER_INAT_MIN_AVG", "0.84") or "0.84")
    min_minimum = float(os.getenv("AMIR_IDENTIFIER_INAT_MIN_MIN", "0.82") or "0.82")
    min_margin = float(os.getenv("AMIR_IDENTIFIER_INAT_MIN_MARGIN", "0.03") or "0.03")

    if best[0] < min_average or best[1] < min_minimum or margin < min_margin:
        return {
            "ok": False,
            "subject": "",
            "confidence": 0,
            "error": "No reference candidate cleared similarity thresholds.",
            "source": SOURCE_NAME,
            "mode": candidate_mode,
            "top_candidates": _format_top(scored),
            "coords": coords_payload,
            "month": month,
            "iconic_taxa": iconic_taxa,
            "recovered_original_count": recovered_original_count,
            "fallback_countries": fallback_countries,
        }

    item = best[3]
    subject = _title(item.get("common") or item.get("scientific") or "")
    confidence = max(70, min(96, int(round((best[0] - 0.75) * 360 + margin * 300))))

    return {
        "ok": bool(subject),
        "subject": subject,
        "confidence": confidence,
        "category": "biology_reference",
        "source": SOURCE_NAME,
        "mode": candidate_mode,
        "average_similarity": best[0],
        "minimum_similarity": best[1],
        "margin": margin,
        "scientific": item.get("scientific") or "",
        "taxon_id": item.get("taxon_id"),
        "observation_count": item.get("count"),
        "top_candidates": _format_top(scored),
        "sample_count": len(samples),
        "selected_count": len(paths),
        "coords": coords_payload,
        "month": month,
        "iconic_taxa": iconic_taxa,
        "recovered_original_count": recovered_original_count,
        "fallback_countries": fallback_countries,
        "error": "",
    }


def _format_top(scored: list[tuple[float, float, int, dict[str, Any], list[float]]]) -> list[dict[str, Any]]:
    out = []

    for average, minimum, count, item, similarities in scored[:10]:
        out.append(
            {
                "subject": _title(item.get("common") or item.get("scientific") or ""),
                "scientific": item.get("scientific") or "",
                "average_similarity": round(average, 4),
                "minimum_similarity": round(minimum, 4),
                "observation_count": count,
                "similarities": [round(value, 4) for value in similarities],
            }
        )

    return out
