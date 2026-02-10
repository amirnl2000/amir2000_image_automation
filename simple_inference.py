import os
import sys
import torch
import numpy as np
from PIL import Image
import torch.nn as nn

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
