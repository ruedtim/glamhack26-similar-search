"""Evaluate whether visual nearest neighbours carry useful object names, and render a results page.

Proxy task: for an object with a known (specific) name, do its nearest neighbours in OTHER
collections carry the same name? Names are compared on a crude English head noun
("Wooden Figure (rice god)" -> "figure", "Betel nut box" -> "box"), which undercounts
synonyms (kampilan vs. sword), so the numbers are a conservative lower bound.

Usage: python evaluate.py --data DATA_DIR --queries QUERY_DIR --html results.html
"""
import argparse
import base64
import io
import json
import random
import re
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image

from models import Embedder, pad_square

STOP_TAIL = {"fragment", "part", "model", "set", "pair", "piece", "object"}
DE_LABELS = [
    "Röhrenzither", "Zither", "Laute", "Harfe", "Trommel", "Flöte", "Panflöte", "Rassel", "Gong", "Glocke",
    "Maske", "Figur", "Ahnenfigur", "Gottheitsstatue", "Buddha-Figur", "Kraftfigur", "Puppe", "Amulett",
    "Schale", "Korb", "Gefäss", "Topf", "Krug", "Löffel", "Kalebasse", "Dose", "Betelnussdose", "Mörser",
    "Schild", "Speer", "Pfeil", "Bogen", "Schwert", "Dolch", "Messer", "Beil", "Keule",
    "Halskette", "Armreif", "Ohrschmuck", "Gürtel", "Hut", "Kopfbedeckung", "Textil", "Matte", "Sandale",
    "Kamm", "Fächer", "Pfeife", "Hocker", "Kopfstütze", "Spazierstock", "Bambusrohr", "Ruder", "Bootsmodell",
    "Netz", "Fischfalle", "Spindel", "Webgerät", "Lampe",
]


def clean(name):
    s = (name or "").lower()
    s = re.sub(r"\(.*?\)|\[.*?\]|\".*?\"|“.*?”", " ", s)
    s = re.split(r"[,:;/]| - | – ", s)[0]
    s = s.split(" of ")[0].split(" with ")[0].split(" for ")[0]
    s = re.sub(r"[^a-zà-ÿ\- ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def head(name):
    ws = clean(name).split()
    while ws and ws[-1] in STOP_TAIL and len(ws) > 1:
        ws = ws[:-1]
    if not ws:
        return ""
    w = ws[-1]
    if w.endswith("ies") and len(w) > 4:
        w = w[:-3] + "y"
    elif w.endswith("s") and not w.endswith(("ss", "us")) and len(w) > 3:
        w = w[:-1]
    return w


def thumb_b64(path, side=120):
    im = pad_square(Image.open(path))
    im.thumbnail((side, side))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def knn_eval(E, recs, heads, q_idx, cand_mask_fn, k=10):
    """P@1, Hit@5, Vote@10 and random baseline for queries q_idx.

    'covered' = queries whose name occurs at all among the candidates (only those can be found);
    the *_cov metrics are computed on that subset.
    """
    rows = []
    for i in q_idx:
        cand = np.where(cand_mask_fn(i))[0]
        if len(cand) < k:
            continue
        sims = E[cand] @ E[i]
        keep = sims < 0.995                       # drop exact duplicate images
        cand, sims = cand[keep], sims[keep]
        top = cand[np.argsort(-sims)[:k]]
        th = [heads[j] for j in top]
        h = heads[i]
        same = np.array([heads[j] == h for j in cand])
        rows.append((th[0] == h, h in th[:5],
                     any(th) and Counter(x for x in th if x).most_common(1)[0][0] == h,
                     same.mean(), same.any()))
    R = np.array(rows, dtype=float)
    cov = R[:, 4] > 0
    return {"n": len(R), "coverage": float(cov.mean()),
            "P@1": float(R[:, 0].mean()), "Hit@5": float(R[:, 1].mean()), "Vote@10": float(R[:, 2].mean()),
            "random_P@1": float(R[:, 3].mean()),
            "P@1_cov": float(R[cov, 0].mean()), "Hit@5_cov": float(R[cov, 1].mean()),
            "Vote@10_cov": float(R[cov, 2].mean()), "random_P@1_cov": float(R[cov, 3].mean())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--queries", required=True)
    ap.add_argument("--html", required=True)
    a = ap.parse_args()
    data, qdir = Path(a.data), Path(a.queries)
    recs = [json.loads(l) for l in open(data / "records.jsonl", encoding="utf-8")]
    qnames = json.load(open(qdir / "ids.json"))
    heads = [head(r["name"]) for r in recs]
    src = np.array([r["source"] for r in recs])
    holder = np.array([r.get("holder", "") for r in recs])
    has_head = np.array([bool(h) for h in heads])

    # queries for the proxy task: Philippine objects whose head noun occurs >= 3 times
    hc = Counter(h for h, s in zip(heads, src) if s == "phil" and h)
    q_idx = [i for i, (h, s) in enumerate(zip(heads, src)) if s == "phil" and hc[h] >= 3]
    print(f"records: {len(recs)} {dict(Counter(src))}; proxy queries: {len(q_idx)}; "
          f"distinct head nouns among them: {len({heads[i] for i in q_idx})}")
    print("most frequent head nouns:", hc.most_common(15))

    results, embs, qembs = {}, {}, {}
    for m in ["siglip2", "dinov2"]:
        E = np.load(data / f"emb_{m}.npy")
        embs[m] = E
        qembs[m] = np.load(qdir / f"emb_{m}.npy")
        results[m] = {
            "Phil → Phil (other museum)": knn_eval(
                E, recs, heads, q_idx, lambda i: (src == "phil") & (holder != holder[i]) & has_head),
            "Phil → Cleveland (andere Sammlung)": knn_eval(
                E, recs, heads, q_idx, lambda i: (src != "phil") & has_head),
        }

    # zero-shot naming (SigLIP 2 image-text) on the same proxy queries, vocabulary = frequent head nouns
    emb = Embedder("siglip2")
    vocab = sorted(h for h, c in hc.items() if c >= 3)
    T = emb.texts([f"a photo of a {v}, an ethnographic museum object" for v in vocab])
    S = embs["siglip2"][q_idx] @ T.T
    top = np.argsort(-S, axis=1)
    gold = [vocab.index(heads[i]) for i in q_idx]
    zs = {"n": len(q_idx), "vocab": len(vocab),
          "Top1": float(np.mean([t[0] == g for t, g in zip(top, gold)])),
          "Top5": float(np.mean([g in t[:5] for t, g in zip(top, gold)])),
          "majority_baseline": hc.most_common(1)[0][1] / sum(hc[v] for v in vocab)}
    results["siglip2_zero_shot"] = zs

    # German zero-shot labels for the two slide queries
    Tde = emb.texts([f"ein Foto von einem Museumsobjekt: {l}" for l in DE_LABELS])
    zs_de = {}
    for qi, qn in enumerate(qnames):
        s = qembs["siglip2"][qi] @ Tde.T
        zs_de[qn] = [(DE_LABELS[j], float(s[j])) for j in np.argsort(-s)[:6]]

    print(json.dumps(results, indent=1, ensure_ascii=False))
    print(json.dumps(zs_de, indent=1, ensure_ascii=False))
    json.dump({"metrics": results, "zero_shot_de": zs_de}, open(Path(a.html).with_suffix(".json"), "w"),
              ensure_ascii=False, indent=1)

    # ------------------------------------------------------------------ HTML
    def card(j, sim):
        r = recs[j]
        return (f'<a class="c" href="{r["url"]}" target="_blank" rel="noopener">'
                f'<img src="{thumb_b64(data / r["img"])}" alt="">'
                f'<b>{r["name"][:60]}</b><small>{r.get("holder", "")} · {r["source"]} · {sim:.2f}</small></a>')

    parts = []
    for qi, qn in enumerate(qnames):
        parts.append(f'<section><h2>Abfrage: {qn}</h2><div class="row"><div class="q">'
                     f'<img src="{thumb_b64(qdir / qn, 160)}" alt=""><small>Thumbnail aus den Challenge-Folien</small></div>'
                     f'<div><p class="zs">SigLIP 2 zero-shot (deutsche Begriffe): '
                     + ", ".join(f"{l} <span>{s:.3f}</span>" for l, s in zs_de[qn]) + "</p>")
        for m in ["siglip2", "dinov2"]:
            s = embs[m] @ qembs[m][qi]
            top = np.argsort(-s)[:8]
            parts.append(f'<h3>{m}: nächste Nachbarn</h3><div class="grid">' + "".join(card(j, s[j]) for j in top) + "</div>")
        parts.append("</div></div></section>")

    random.seed(7)
    demo = random.sample(q_idx, 8)
    parts.append("<section><h2>Stichprobe: Objekte aus «Mapping Philippine Material Culture» als Abfrage "
                 "(Nachbarn nur aus Cleveland Museum of Art, SigLIP 2)</h2>")
    E = embs["siglip2"]
    other = np.where(src != "phil")[0]
    for i in demo:
        s = E[other] @ E[i]
        top = other[np.argsort(-s)[:6]]
        votes = Counter(heads[j] for j in other[np.argsort(-s)[:10]] if heads[j]).most_common(3)
        parts.append(f'<div class="row"><div class="q"><img src="{thumb_b64(data / recs[i]["img"], 160)}" alt="">'
                     f'<b>{recs[i]["name"][:60]}</b><small>{recs[i].get("holder", "")}</small>'
                     f'<small>Vorschlag (Top-10-Vote): {", ".join(f"{h} ×{c}" for h, c in votes)}</small></div>'
                     '<div class="grid">' + "".join(card(j, E[j] @ E[i]) for j in top) + "</div></div>")
    parts.append("</section>")

    rows = []
    for m in ["siglip2", "dinov2"]:
        for setting, r in results[m].items():
            rows.append(f"<tr><td>{m}</td><td>{setting}</td><td>{r['n']}</td><td>{r['coverage']:.0%}</td>"
                        f"<td>{r['P@1_cov']:.0%}</td><td>{r['Hit@5_cov']:.0%}</td><td>{r['Vote@10_cov']:.0%}</td>"
                        f"<td>{r['random_P@1_cov']:.1%}</td></tr>")
    table = ("<table><tr><th>Modell</th><th>Setting</th><th>n</th><th>Name im Referenzbestand vorhanden</th>"
             "<th>P@1</th><th>Hit@5</th><th>Vote@10</th><th>Zufall P@1</th></tr>" + "".join(rows) + "</table>"
             "<p><small>P@1/Hit@5/Vote@10 nur über Abfragen, deren Name im Referenzbestand überhaupt vorkommt.</small></p>"
             f"<p>Zero-shot SigLIP 2 (Vokabular {zs['vocab']} Kopfnomen): Top-1 {zs['Top1']:.0%}, "
             f"Top-5 {zs['Top5']:.0%} (Mehrheitsklasse {zs['majority_baseline']:.0%}).</p>")

    html = f"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Similar Search PoC</title>
<style>
:root{{--bg:#fafaf8;--fg:#1d1d1b;--mut:#6b6b66;--card:#fff;--line:#e3e2dc;--acc:#b0306a}}
@media (prefers-color-scheme: dark){{:root{{--bg:#191917;--fg:#ecebe6;--mut:#a3a29b;--card:#242422;--line:#3a3935;--acc:#e07aa8}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,sans-serif;margin:0 auto;max-width:1200px;padding:16px}}
h1{{font-size:24px}} h2{{font-size:18px;margin-top:32px;border-top:1px solid var(--line);padding-top:16px}} h3{{font-size:14px;color:var(--mut);margin:12px 0 6px}}
.row{{display:flex;gap:16px;align-items:flex-start;margin:12px 0;flex-wrap:wrap}} .q{{width:170px;display:flex;flex-direction:column;gap:4px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:8px;flex:1;min-width:260px}}
.c{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:6px;text-decoration:none;color:inherit;display:flex;flex-direction:column;gap:3px}}
.c img,.q img{{width:100%;aspect-ratio:1;object-fit:contain;background:#fff;border-radius:4px}}
b{{font-size:13px;font-weight:600}} small{{font-size:11px;color:var(--mut)}} .zs span{{color:var(--mut);font-size:12px}}
table{{border-collapse:collapse;font-size:14px}} td,th{{border-bottom:1px solid var(--line);padding:4px 10px;text-align:left}}
</style></head><body>
<h1>Similar Search – Machbarkeits-PoC (GLAMhack 2026, «To Be Renamed!»)</h1>
<p>Referenzbestand: {len(recs)} Objekte ({", ".join(f"{k}: {v}" for k, v in Counter(src).items())}). Modelle: SigLIP 2 base (multilingual Bild-Text), DINOv2 base (rein visuell).</p>
<h2>Kennzahlen (Proxy-Aufgabe)</h2>{table}
{"".join(parts)}
</body></html>"""
    Path(a.html).write_text(html, encoding="utf-8")
    print("wrote", a.html)


if __name__ == "__main__":
    main()
