"""Embed all harvested images (and the query images) with each model, incrementally.

Existing vectors (DATA_DIR/emb_<model>.npy + ids.json) are reused; only new records get computed.
Throttle the GPU load with the env var GPU_SHARE, e.g. GPU_SHARE=0.5 (see models.py).

Usage: GPU_SHARE=0.5 python embed.py --data DATA_DIR --queries QUERY_DIR
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np

from models import GPU_SHARE, MODELS, Embedder


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--queries", required=True)
    ap.add_argument("--models", default=",".join(MODELS))
    a = ap.parse_args()
    data, qdir = Path(a.data), Path(a.queries)
    recs = [json.loads(l) for l in open(data / "records.jsonl", encoding="utf-8")]
    ids = [r["id"] for r in recs]
    old_ids = json.load(open(data / "ids.json")) if (data / "ids.json").exists() else []
    qpaths = sorted(qdir.glob("q_*.png"))
    print(f"GPU_SHARE={GPU_SHARE}")

    for name in a.models.split(","):
        t = time.time()
        path = data / f"emb_{name}.npy"
        old = np.load(path) if path.exists() else None
        pos = {i: k for k, i in enumerate(old_ids)} if old is not None and len(old) == len(old_ids) else {}
        missing = [k for k, i in enumerate(ids) if i not in pos]
        e = Embedder(name)
        new = e.images([data / recs[k]["img"] for k in missing]) if missing else None
        dim = (new if new is not None else old).shape[1]
        out = np.zeros((len(recs), dim), dtype=np.float32)
        for k, i in enumerate(ids):
            if i in pos:
                out[k] = old[pos[i]]
        if missing:
            out[missing] = new
        np.save(path, out)
        if qpaths:
            np.save(qdir / f"emb_{name}.npy", e.images(qpaths))
        print(f"{name}: {len(missing)} new + {len(recs) - len(missing)} reused, "
              f"{len(qpaths)} queries in {time.time() - t:.0f}s")
    json.dump(ids, open(data / "ids.json", "w"))
    json.dump([p.name for p in qpaths], open(qdir / "ids.json", "w"))


if __name__ == "__main__":
    main()
