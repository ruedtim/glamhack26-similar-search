"""Before/after comparison of two reference sets for the VMZ objects (no GPU needed).

For each VMZ object, the top-5 neighbours (SigLIP 2 + DINOv2, rank fusion) are computed once with the
OLD reference set (record ids in --before) and once with the full current one. Measured:
  - top-1 similarity (SigLIP 2): how close is the nearest comparable object? (coverage proxy)
  - type term confirmed: does a top-5 neighbour name contain the certain type term of the current name?
    (German term as substring, e.g. "Goldgewicht in geometrischer Form", or the head noun of its English
    machine translation, e.g. Korb -> "basket"). Synonyms count as misses: a lower bound.
  - «?» hypothesis confirmed: the same for the uncertain terms in the name.

Usage: python compare_refs.py --data DATA_DIR --before DATA_DIR/records_before_more.jsonl
"""
import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from models import load_embeddings
from suggest import rrf
from suggest_vmz import matches, name_terms, type_term


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--before", required=True)
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--hub-max", type=int, default=0,
                    help="hide reference objects in the top 5 of >= this many VMZ photos (as suggest_vmz.py; 0 = off)")
    a = ap.parse_args()
    data = Path(a.data)
    recs = [json.loads(l) for l in open(data / "records.jsonl", encoding="utf-8")]
    E = {m: load_embeddings(data, m, recs) for m in ["siglip2", "dinov2"]}
    tr = json.load(open(data / "vmz_vocab_en.json", encoding="utf-8"))
    cat = {}
    for l in open(data / "vmz_catalog.jsonl", encoding="utf-8"):
        c = json.loads(l)
        cat.setdefault(c["sig"], c)
    old_ids = {json.loads(l)["id"] for l in open(a.before, encoding="utf-8")}
    src = np.array([r["source"] for r in recs])
    own = np.array([r["source"] in ("uzh", "vmz") or "zurich" in (r.get("holder") or "").lower()
                    or "zürich" in (r.get("holder") or "").lower() for r in recs])
    q_idx = np.where(src == "vmz")[0]
    refs = {"before": np.where(~own & np.array([r["id"] in old_ids for r in recs]))[0],
            "after": np.where(~own)[0]}
    print({k: len(v) for k, v in refs.items()})

    res = {k: defaultdict(list) for k in refs}
    for name, ref in refs.items():
        cand = {}
        for i in q_idx:
            cand[i] = {}
            for m in E:
                s = E[m][ref] @ E[m][i]
                order = [o for o in np.argsort(-s)[:200] if s[o] < 0.995]
                cand[i][m] = ([ref[o] for o in order], {ref[o]: float(s[o]) for o in order})
        hubs = set()
        if a.hub_max:
            freq = Counter(j for i in q_idx for j in rrf([cand[i][m][0][:60] for m in E])[:5])
            hubs = {j for j, c in freq.items() if c >= a.hub_max}
        print(f"{name}: {len(hubs)} hubs hidden")
        for i in q_idx:
            ranks = [[j for j in cand[i][m][0] if j not in hubs][:60] for m in E]
            top1 = cand[i]["siglip2"][1][ranks[list(E).index("siglip2")][0]]
            top = rrf(ranks)[:a.k]
            names = [recs[j]["name"] for j in top]
            r = recs[i]
            cont = cat.get(r.get("cat_sig") or "", {}).get("continent") or "?"
            res[name]["top1"].append(top1)
            res[name]["cont"].append(cont)
            terms = name_terms(r["name"])
            tt = type_term(r["name"])
            if terms and terms[0][0] == tt and terms[0][1] == "" and tt in tr:
                res[name]["type"].append(matches(tt, tr[tt], names))
            for t, mark in terms:
                if mark == "?" and t in tr:
                    res[name]["hyp"].append(matches(t, tr[t], names))

    print(f"\n{'':34}{'before':>10}{'after':>10}")
    b, f = res["before"], res["after"]
    print(f"{'top-1 similarity, median':34}{np.median(b['top1']):10.3f}{np.median(f['top1']):10.3f}")
    print(f"{'top-1 similarity >= 0.85':34}{np.mean(np.array(b['top1']) >= 0.85):10.0%}{np.mean(np.array(f['top1']) >= 0.85):10.0%}")
    lab_t = f"type term in top-{a.k} names (n={len(b['type'])})"
    lab_h = f"«?» hypothesis in top-{a.k} names (n={len(b['hyp'])})"
    print(f"{lab_t:34}{np.mean(b['type']):10.0%}{np.mean(f['type']):10.0%}")
    print(f"{lab_h:34}{np.mean(b['hyp']):10.0%}{np.mean(f['hyp']):10.0%}")
    print("\ntop-1 similarity by continent (median, before -> after):")
    conts = defaultdict(lambda: ([], []))
    for (cb, sb), (cf, sf) in zip(zip(b["cont"], b["top1"]), zip(f["cont"], f["top1"])):
        conts[cb][0].append(sb)
        conts[cb][1].append(sf)
    for c, (x, y) in sorted(conts.items(), key=lambda kv: -len(kv[1][0])):
        print(f"  {c[:28]:28} n={len(x):4}  {np.median(x):.3f} -> {np.median(y):.3f}")


if __name__ == "__main__":
    main()
