"""Model helpers: image/text embeddings with SigLIP 2 (multilingual image-text) and DINOv2 (visual only).

GPU_SHARE (env var, 0 < x <= 1, default 1): throttles the load via a duty cycle. After each batch the
process pauses so the GPU is busy only ~GPU_SHARE of the time (less heat and fan noise). With
GPU_SHARE < 1, the CPU threads are halved as well.
"""
import os
import time

import numpy as np
import torch
from PIL import Image
from transformers import AutoImageProcessor, AutoModel, AutoProcessor

MODELS = {
    "siglip2": "google/siglip2-base-patch16-224",
    "dinov2": "facebook/dinov2-base",
}
DEV = "mps" if torch.backends.mps.is_available() else "cpu"
GPU_SHARE = min(1.0, max(0.05, float(os.environ.get("GPU_SHARE", "1.0"))))
if GPU_SHARE < 1.0:
    torch.set_num_threads(max(1, (os.cpu_count() or 2) // 2))


def _throttle(t0):
    """Pause after a batch so that busy time / total time ~= GPU_SHARE."""
    if GPU_SHARE >= 1.0:
        return
    if DEV == "mps":
        torch.mps.synchronize()          # MPS runs asynchronously: measure the real GPU time
    busy = time.perf_counter() - t0
    time.sleep(busy * (1.0 / GPU_SHARE - 1.0))


def pad_square(im: Image.Image) -> Image.Image:
    """Pad to a square with the median border colour (keeps tall/thin objects intact, no center crop)."""
    im = im.convert("RGB")
    w, h = im.size
    if w == h:
        return im
    a = np.asarray(im)
    border = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
    fill = tuple(int(v) for v in np.median(border, axis=0))
    s = max(w, h)
    out = Image.new("RGB", (s, s), fill)
    out.paste(im, ((s - w) // 2, (s - h) // 2))
    return out


class Embedder:
    def __init__(self, name):
        self.name = name
        mid = MODELS[name]
        self.model = AutoModel.from_pretrained(mid).eval().to(DEV)
        if name == "siglip2":
            self.proc = AutoProcessor.from_pretrained(mid)
        else:
            # no resize+center-crop: we pad to square ourselves and resize to 224
            self.proc = AutoImageProcessor.from_pretrained(
                mid, do_center_crop=False, size={"height": 224, "width": 224})

    @torch.no_grad()
    def images(self, paths, bs=16):
        out = []
        for i in range(0, len(paths), bs):
            t0 = time.perf_counter()
            ims = [pad_square(Image.open(p)) for p in paths[i:i + bs]]
            inp = self.proc(images=ims, return_tensors="pt").to(DEV)
            if self.name == "siglip2":
                f = self.model.get_image_features(**inp)
                if not torch.is_tensor(f):
                    f = f.pooler_output
            else:
                h = self.model(**inp).last_hidden_state
                f = torch.cat([h[:, 0], h[:, 1:].mean(1)], dim=1)  # CLS + mean patch token
            out.append(torch.nn.functional.normalize(f.float(), dim=-1).cpu().numpy())
            _throttle(t0)
        return np.concatenate(out)

    @torch.no_grad()
    def texts(self, texts, bs=32):
        assert self.name == "siglip2", "text embeddings only for SigLIP 2"
        out = []
        for i in range(0, len(texts), bs):
            t0 = time.perf_counter()
            inp = self.proc(text=texts[i:i + bs], padding="max_length", max_length=64,
                            truncation=True, return_tensors="pt").to(DEV)
            f = self.model.get_text_features(**inp)
            if not torch.is_tensor(f):
                f = f.pooler_output
            out.append(torch.nn.functional.normalize(f.float(), dim=-1).cpu().numpy())
            _throttle(t0)
        return np.concatenate(out)

    def logit_params(self):
        m = self.model
        return float(m.logit_scale.exp()), float(m.logit_bias)
