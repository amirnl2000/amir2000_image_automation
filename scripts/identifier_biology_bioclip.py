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

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_ROOT = PROJECT_ROOT / "data" / "models"

SOURCE_NAME = "bioclip2_zero_shot_v1"

BIOLOGY_LABELS: list[str] = [
    # Birds common in the Netherlands and user archive.
    "herring gull",
    "lesser black backed gull",
    "great black backed gull",
    "black headed gull",
    "common gull",
    "gull",
    "Egyptian goose",
    "greylag goose",
    "Canada goose",
    "barnacle goose",
    "mallard duck",
    "duck",
    "mute swan",
    "great cormorant",
    "grey heron",
    "white stork",
    "black winged kite",
    "red kite",
    "common buzzard",
    "kestrel",
    "raptor",
    "pigeon",
    "crow",
    "magpie",
    "rose-ringed parakeet",
    "alexandrine parakeet",
    "monk parakeet",
    "parakeet",
    "parrot",
    "songbird",
    "bird",

    # Mammals.
    "horse",
    "cow",
    "sheep",
    "goat",
    "deer",
    "dog",
    "cat",
    "rabbit",
    "fox",
    "monkey",
    "lion",
    "mammal",

    # Insects and spiders.
    "European peacock butterfly",
    "butterfly",
    "hoverfly",
    "syrphid fly",
    "honey bee",
    "bumblebee",
    "wasp",
    "dragonfly",
    "damselfly",
    "beetle",
    "greenbottle blow fly",
    "blow fly",
    "fly",
    "spider",
    "insect",

    # Plants and fungi.
    "Prunus blossoms",
    "cherry blossoms",
    "blackthorn blossoms",
    "white spring blossoms",
    "flowering branch",
    "blossoms on branches",
    "crocus blossoms",
    "tulip",
    "daffodil",
    "flower",
    "mushroom",
    "mushroom gills",
    "red fungus",
    "bracket fungus",
    "lichen",
    "moss",
    "fungus",
    "plant",
]


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


@lru_cache(maxsize=1)
def _load_bioclip() -> tuple[Any, Any, Any, str]:
    import torch
    import open_clip

    os.environ.setdefault("HF_HOME", str(MODEL_ROOT / "huggingface_cache"))
    os.environ.setdefault("TRANSFORMERS_CACHE", str(MODEL_ROOT / "transformers_cache"))
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

    requested_device = os.environ.get("IDENTIFIER_BIOCLIP_DEVICE", "cpu").strip().lower()

    if requested_device == "cuda" and torch.cuda.is_available():
        device = "cuda"
    else:
        device = "cpu"

    model, _preprocess_train, preprocess_val = open_clip.create_model_and_transforms(
        "hf-hub:imageomics/bioclip-2"
    )
    tokenizer = open_clip.get_tokenizer("hf-hub:imageomics/bioclip-2")

    model = model.to(device)
    model.eval()

    return model, preprocess_val, tokenizer, device


def identify_image_biology(image_path: str | Path, *, top_k: int = 5) -> dict[str, Any]:
    import torch

    image_path = Path(image_path)

    try:
        model, preprocess_val, tokenizer, device = _load_bioclip()

        image = Image.open(image_path).convert("RGB")
        image_tensor = preprocess_val(image).unsqueeze(0).to(device)

        prompts = [f"a photo of {label}" for label in BIOLOGY_LABELS]
        text_tokens = tokenizer(prompts).to(device)

        with torch.no_grad():
            image_features = model.encode_image(image_tensor)
            text_features = model.encode_text(text_tokens)

            image_features = image_features / image_features.norm(dim=-1, keepdim=True)
            text_features = text_features / text_features.norm(dim=-1, keepdim=True)

            logits = 100.0 * image_features @ text_features.T
            probs = logits.softmax(dim=-1)[0].detach().cpu()

        ranked = sorted(
            [
                {
                    "label": BIOLOGY_LABELS[index],
                    "score": float(probs[index].item()),
                }
                for index in range(len(BIOLOGY_LABELS))
            ],
            key=lambda item: item["score"],
            reverse=True,
        )[:top_k]

        top = ranked[0]
        second_score = ranked[1]["score"] if len(ranked) > 1 else 0.0
        gap = max(0.0, top["score"] - second_score)

        confidence = int(max(0, min(96, (top["score"] * 120.0) + (gap * 280.0))))

        label = str(top["label"])
        category = _category_for_label(label)

        return {
            "ok": True,
            "source": SOURCE_NAME,
            "image_path": str(image_path),
            "label": label,
            "subject": _subject_for_label(label),
            "category": category,
            "confidence": confidence,
            "score": float(top["score"]),
            "gap": float(gap),
            "top_candidates": ranked,
            "device": device,
            "error": "",
        }

    except Exception as exc:
        return {
            "ok": False,
            "source": SOURCE_NAME,
            "image_path": str(image_path),
            "label": "",
            "subject": "",
            "category": "",
            "confidence": 0,
            "score": 0.0,
            "gap": 0.0,
            "top_candidates": [],
            "device": "",
            "error": f"{type(exc).__name__}: {exc}",
        }


def _category_for_label(label: str) -> str:
    lower = label.lower()

    if any(word in lower for word in ["gull", "goose", "duck", "swan", "cormorant", "heron", "stork", "kite", "buzzard", "kestrel", "raptor", "pigeon", "crow", "magpie", "songbird", "bird"]):
        return "bird"

    if any(word in lower for word in ["horse", "cow", "sheep", "goat", "deer", "dog", "cat", "rabbit", "fox", "monkey", "lion", "mammal"]):
        return "mammal"

    if any(word in lower for word in ["butterfly", "hoverfly", "syrphid", "bee", "wasp", "dragonfly", "damselfly", "beetle", "fly", "spider", "insect"]):
        return "insect"

    if any(word in lower for word in ["blossom", "branch", "crocus", "tulip", "daffodil", "flower", "plant"]):
        return "plant"

    if any(word in lower for word in ["mushroom", "fungus", "lichen", "moss"]):
        return "fungi"

    return "biology"


def _subject_for_label(label: str) -> str:
    lower = label.lower()

    if lower in {"gull", "bird"}:
        return "Gull in Coastal Surf" if lower == "gull" else "Bird in Natural Setting"

    if "gull" in lower:
        return f"{_title_subject(label)} in Coastal Surf"

    if "goose" in lower:
        return f"{_title_subject(label)} by Water"

    if lower in {"horse", "cow", "sheep", "goat", "deer"}:
        return _title_subject(label)

    if "butterfly" in lower:
        return f"{_title_subject(label)} on Blossoms"

    if any(word in lower for word in ["bee", "hoverfly", "wasp", "fly", "beetle"]):
        return f"{_title_subject(label)} on Flowers"

    if "prunus" in lower:
        return "White Prunus Blossoms on Branches"

    if "cherry" in lower:
        return "White Cherry Blossoms on Branches"

    if "blackthorn" in lower:
        return "White Blackthorn Blossoms on Branches"

    if "spring blossoms" in lower or "flowering branch" in lower or "blossoms on branches" in lower:
        return "White Spring Blossoms on Branches"

    if "mushroom" in lower:
        return "Mushroom Gills and Stems in Woodland"

    if "fungus" in lower:
        return "Fungus Growing on Wood"

    return _title_subject(label)
