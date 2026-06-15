
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

# AMIR STRICT LOCAL TIMM LOADER START
def _amir_install_strict_local_timm_loader() -> None:
    """
    Production scoring rule:
    - NIMA scoring must run.
    - No live Hugging Face download during a batch.
    - timm inception_resnet_v2 weights must load from local project cache.
    - If local weights are missing, fail hard.
    """
    import os
    import sys
    from pathlib import Path

    project_root = Path(__file__).resolve().parent

    candidates = []

    override = os.environ.get("AMIR_TIMM_INCEPTION_RESNET_V2_WEIGHTS", "").strip()
    if override:
        candidates.append(Path(override))

    cache_root = project_root / ".cache" / "huggingface" / "hub" / "models--timm--inception_resnet_v2.tf_in1k"
    candidates.extend(cache_root.glob("snapshots/*/pytorch_model.bin"))
    candidates.extend(cache_root.glob("snapshots/*/model.safetensors"))

    valid = [
        path
        for path in candidates
        if path.exists() and path.is_file() and path.stat().st_size > 200 * 1024 * 1024
    ]

    if not valid:
        raise RuntimeError(
            "[STRICT SCORING] Missing local timm inception_resnet_v2 weights. "
            "Expected pytorch_model.bin or model.safetensors under "
            ".cache\\huggingface\\hub\\models--timm--inception_resnet_v2.tf_in1k\\snapshots\\..."
        )

    checkpoint_path = sorted(valid, key=lambda p: p.stat().st_size, reverse=True)[0]

    import torch
    import timm.models._hub as timm_hub
    import timm.models._builder as timm_builder

    original_hub_loader = getattr(timm_hub, "load_state_dict_from_hf", None)

    def _amir_load_state_dict_from_hf(*args, **kwargs):
        model_id = str(args[0] if args else kwargs.get("model_id", ""))

        if "inception_resnet_v2.tf_in1k" in model_id:
            print(
                f"[STRICT SCORING] Loading local timm checkpoint: {checkpoint_path}",
                file=sys.stderr,
            )

            if checkpoint_path.suffix.lower() == ".safetensors":
                from safetensors.torch import load_file
                return load_file(str(checkpoint_path), device="cpu")

            try:
                return torch.load(
                    str(checkpoint_path),
                    map_location="cpu",
                    weights_only=True,
                )
            except TypeError:
                return torch.load(
                    str(checkpoint_path),
                    map_location="cpu",
                )

        if original_hub_loader is None:
            raise RuntimeError(
                f"[STRICT SCORING] No Hugging Face loader available for {model_id}"
            )

        return original_hub_loader(*args, **kwargs)

    timm_hub.load_state_dict_from_hf = _amir_load_state_dict_from_hf
    timm_builder.load_state_dict_from_hf = _amir_load_state_dict_from_hf


_amir_install_strict_local_timm_loader()
# AMIR STRICT LOCAL TIMM LOADER END


import os
import sys
import torch
import numpy as np
from PIL import Image
import torch.nn as nn

# OpenAI CLIP still imports "packaging" via pkg_resources in some builds.
# Bridge that import so the scorer keeps working across newer setuptools.
try:
    import packaging  # type: ignore
    from packaging import version as _packaging_version  # type: ignore
    import pkg_resources  # type: ignore
    if not hasattr(packaging, "version"):
        packaging.version = _packaging_version  # type: ignore[attr-defined]
    if not hasattr(pkg_resources, "packaging"):
        pkg_resources.packaging = packaging  # type: ignore[attr-defined]
except Exception:
    pass

def resource_path(rel_path: str) -> str:
    """
    Works in:
      - normal python
      - PyInstaller onefile (sys._MEIPASS)
      - PyInstaller onedir (next to exe)
    """
    if getattr(sys, "frozen", False):
        candidates = [os.path.join(os.path.dirname(sys.executable), rel_path)]
        mei = getattr(sys, "_MEIPASS", None)
        if mei:
            candidates.append(os.path.join(mei, rel_path))
        for p in candidates:
            if os.path.exists(p):
                return p
        return candidates[0]
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), rel_path)

# Robust CLIP import (handles odd packaging edge cases)
try:
    import clip  # OpenAI CLIP should provide clip.load
    if not hasattr(clip, "load"):
        # Some environments expose load at clip.clip.load
        from clip.clip import load as _load  # type: ignore
        clip.load = _load  # type: ignore[attr-defined]
except Exception as e:
    raise RuntimeError(
        "CLIP import failed or wrong 'clip' package is installed.\n"
        "Fix in venv:\n"
        "  python -m pip uninstall -y clip\n"
        "  python -m pip install git+https://github.com/openai/CLIP.git"
    ) from e

def normalized(a: np.ndarray, axis: int = -1, order: int = 2) -> np.ndarray:
    l2 = np.atleast_1d(np.linalg.norm(a, order, axis))
    l2[l2 == 0] = 1
    return a / np.expand_dims(l2, axis)

class MLP(nn.Module):
    def __init__(self, input_size: int):
        super().__init__()
        self.layers = nn.Sequential(
            nn.Linear(input_size, 1024),
            nn.Dropout(0.2),
            nn.Linear(1024, 128),
            nn.Dropout(0.2),
            nn.Linear(128, 64),
            nn.Dropout(0.1),
            nn.Linear(64, 16),
            nn.Linear(16, 1),
        )

    def forward(self, x):
        return self.layers(x)

_DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
_CLIP_MODEL = None
_PREPROCESS = None
_MLP_MODEL = None

def _init_models():
    global _CLIP_MODEL, _PREPROCESS, _MLP_MODEL

    if _CLIP_MODEL is not None and _PREPROCESS is not None and _MLP_MODEL is not None:
        return

    weights_path = resource_path("sac+logos+ava1-l14-linearMSE.pth")

    mlp = MLP(768)
    mlp.load_state_dict(torch.load(weights_path, map_location=_DEVICE))
    mlp.to(_DEVICE)
    mlp.eval()

    clip_model, preprocess = clip.load("ViT-L/14", device=_DEVICE)

    _Mlp = mlp
    _CLIP = clip_model
    _PRE = preprocess

    _MLP_MODEL = _Mlp
    _CLIP_MODEL = _CLIP
    _PREPROCESS = _PRE

def get_image_aesthetic_score(img_path: str) -> float:
    _init_models()

    pil_image = Image.open(img_path).convert("RGB")
    image = _PREPROCESS(pil_image).unsqueeze(0).to(_DEVICE)

    with torch.no_grad():
        feats = _CLIP_MODEL.encode_image(image)

    im_emb_arr = normalized(feats.detach().float().cpu().numpy())
    x = torch.from_numpy(im_emb_arr).float().to(_DEVICE)

    with torch.no_grad():
        pred = _MLP_MODEL(x).squeeze()

    return float(pred.item())

if __name__ == "__main__":
    test_path = "test.jpg"
    if os.path.isfile(test_path):
        print(f"Aesthetic Score: {get_image_aesthetic_score(test_path):.2f}")
    else:
        print("No test.jpg found.")
