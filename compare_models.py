"""Compare image models for the VMZ similar search on the same 748 objects and the full reference set.

Neighbour search (per model and weighted fusions, hub filter as in suggest_vmz.py):
  - type term of the current name among the top-5 neighbour names, «?» hypotheses among them
  - median similarity of the nearest neighbour (per model, not comparable across models)
Term ranking (SigLIP 2 variants only): rank of the certain type term among the VMZ vocabulary
(MT-translated terms, same template and hubness correction as suggest_vmz.py), and of the «?» hypotheses.

Usage: GPU_SHARE=0.5 python compare_models.py --data DATA_DIR --models siglip2,siglip2_so400m,dinov2
"""
import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np

from models import Embedder, load_embeddings
from suggest_vmz import EN_TEMPLATE, matches, name_terms, type_term, wrrf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--models", default="siglip2,siglip2_so400m,dinov2")
    ap.add_argument("--hub-max", type=int, default=10)
    a = ap.parse_args()
    data = Path(a.data)
    names = a.models.split(",")
    recs = [json.loads(l) for l in open(data / "records.jsonl", encoding="utf-8")]
    E = {m: load_embeddings(data, m, recs) for m in names}
    tr = json.load(open(data / "vmz_vocab_en.json", encoding="utf-8"))
    src = np.array([r["source"] for r in recs])
    own = np.array([r["source"] in ("uzh", "vmz") or "zürich" in (r.get("holder") or "").lower()
                    or "zurich" in (r.get("holder") or "").lower() for r in recs])
    flags = np.array([r.get("flag") or "" for r in recs])
    q, ref = np.where((src == "vmz") & (flags != "Figur"))[0], np.where(~own)[0]   # the «?»/quotes sample
    print(f"{len(q)} VMZ objects, {len(ref)} reference objects, models: {names}")

    cand, top1 = {}, {m: [] for m in names}
    for i in q:
        cand[i] = {}
        for m in names:
            s = E[m][ref] @ E[m][i]
            order = [o for o in np.argsort(-s)[:200] if s[o] < 0.995]
            cand[i][m] = [ref[o] for o in order]
            top1[m].append(float(s[order[0]]))

    def neighbours(weights):
        ms = list(weights)
        w = [weights[m] for m in ms]
        freq = Counter(j for i in q for j in wrrf([cand[i][m][:60] for m in ms], w)[:5])
        hubs = {j for j, c in freq.items() if c >= a.hub_max}
        t_hit, h_hit = [], []
        for i in q:
            top = wrrf([[j for j in cand[i][m] if j not in hubs][:60] for m in ms], w)[:5]
            nm = [recs[j]["name"] for j in top]
            terms, tt = name_terms(recs[i]["name"]), type_term(recs[i]["name"])
            if terms and terms[0][0] == tt and terms[0][1] == "" and tt in tr:
                t_hit.append(matches(tt, tr[tt], nm))
            for t, mark in terms:
                if mark == "?" and t in tr:
                    h_hit.append(matches(t, tr[t], nm))
        return np.mean(t_hit), np.mean(h_hit), len(t_hit), len(h_hit)

    configs = [(m, {m: 1.0}) for m in names]
    sig = [m for m in names if m.startswith("siglip2")]
    if "dinov2" in names:
        configs += [(f"{m} + dinov2×0.25", {m: 1.0, "dinov2": 0.25}) for m in sig]
    if len(sig) > 1:
        configs.append((" + ".join(sig), {m: 1.0 for m in sig}))
    print("\nneighbour search (top-5 names)          type term   «?» hypothesis   median top-1 sim")
    for label, w in configs:
        t, h, nt, nh = neighbours(w)
        sim = f"{np.median(top1[label]):.3f}" if label in top1 else ""
        print(f"  {label:38} {t:8.1%}   {h:10.1%}       {sim}   (n={nt}/{nh})")

    # term ranking (zero-shot) per SigLIP 2 variant
    cat = [json.loads(l) for l in open(data / "vmz_catalog.jsonl", encoding="utf-8")]
    counts = Counter(type_term(c["name"]) for c in cat)
    vocab = sorted(t for t, n in counts.items() if n >= 3 and len(t) >= 3 and t[0].isupper())
    pos = {t: k for k, t in enumerate(vocab)}
    sup = round(0.02 * len(vocab))
    print(f"\nterm ranking ({len(vocab)} VMZ terms, supported = rank <= {sup})   type: median rank / supported   «?»: supported")
    for m in sig:
        emb = Embedder(m)
        T = emb.texts([EN_TEMPLATE.format(tr[v]) for v in vocab])
        allimg = E[m][np.concatenate([ref, q])]
        b = 0.5 * (allimg @ T.T).mean(0)
        ranks, hyp_sup, hyp_n = [], 0, 0
        for i in q:
            s = T @ E[m][i] - b
            terms, tt = name_terms(recs[i]["name"]), type_term(recs[i]["name"])
            if terms and terms[0][0] == tt and terms[0][1] == "" and tt in pos:
                ranks.append(1 + int((s > s[pos[tt]]).sum()))
            for t, mark in terms:
                if mark == "?" and t in pos:
                    hyp_n += 1
                    hyp_sup += 1 + int((s > s[pos[t]]).sum()) <= sup
        print(f"  {m:38} {int(np.median(ranks)):6} / {np.mean(np.array(ranks) <= sup):5.1%}   "
              f"{hyp_sup / max(1, hyp_n):10.1%}   (n={len(ranks)}/{hyp_n}, hypotheses in vocabulary only)")


if __name__ == "__main__":
    main()
