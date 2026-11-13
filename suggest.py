"""Name suggestions for UZH objects: similar objects in OTHER collections + zero-shot terms.

For every object with source "uzh":
  - nearest neighbours from all other collections (SigLIP 2 and DINOv2 rankings merged with
    reciprocal rank fusion; objects held by the UZH itself are excluded)
  - the names of those neighbours, grouped (evidence with link + holding museum)
  - zero-shot terms (SigLIP 2 image<->text) from an English vocabulary (names in the reference set)
    and a German vocabulary (Rietberg titles + general object terms)
Writes a review page for curators. The suggestions are hints, the decision stays with the curator.

Usage: python suggest.py --data DATA_DIR --html uzh_review.html
"""
import argparse
import html
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from evaluate import DE_LABELS, clean, head, thumb_b64
from models import Embedder

DE_EXTRA = [
    "Hut", "Sonnenhut", "Flechthut", "Mütze", "Helm", "Tuch", "Taschentuch", "Stoff", "Gewebe", "Decke",
    "Schärpe", "Rock", "Hüfttuch", "Lendenschurz", "Jacke", "Hemd", "Tasche", "Beutel", "Axt", "Dechsel",
    "Haumesser", "Lanze", "Blasrohr", "Schöpfgefäss", "Schöpflöffel", "Schüssel", "Becher",
    "Kokosnussschale", "Behälter", "Kalkbehälter", "Haarnadel", "Anhänger", "Nasenflöte", "Maultrommel",
    "Webschwert", "Stössel", "Reisgefäss", "Werkzeug", "Geburtshilfe-Instrument", "Tonfigur",
]


def clean_de(name):
    s = re.sub(r"\(.*?\)|\[.*?\]", " ", name or "")
    s = s.split(",")[0]
    return re.sub(r"\s+", " ", s).strip()


def rrf(rank_lists, k=60):
    score = defaultdict(float)
    for ranks in rank_lists:
        for r, j in enumerate(ranks):
            score[j] += 1.0 / (k + r + 1)
    return sorted(score, key=lambda j: -score[j])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--html", required=True)
    ap.add_argument("--k", type=int, default=12)
    a = ap.parse_args()
    data = Path(a.data)
    recs = [json.loads(l) for l in open(data / "records.jsonl", encoding="utf-8")]
    E = {m: np.load(data / f"emb_{m}.npy") for m in ["siglip2", "dinov2"]}
    assert all(len(v) == len(recs) for v in E.values()), "re-run embed.py after harvesting"
    src = np.array([r["source"] for r in recs])
    at_uzh = np.array(["zurich" in (r.get("holder") or "").lower() for r in recs])
    q_idx = np.where(src == "uzh")[0]
    ref = np.where((src != "uzh") & ~at_uzh)[0]
    print(f"queries (UZH): {len(q_idx)}; reference: {len(ref)} {dict(Counter(src[ref]))}")

    # vocabularies for zero-shot naming
    en_counts = Counter(clean(recs[j]["name"]) for j in ref if recs[j]["source"] in ("phil", "cma"))
    en_vocab = sorted(n for n, c in en_counts.items() if c >= 2 and len(n) > 2)
    de_vocab = sorted(set(DE_LABELS + DE_EXTRA +
                          [clean_de(recs[j]["name"]) for j in ref if recs[j]["source"] == "mrz"]) - {""})
    emb = Embedder("siglip2")
    T_en = emb.texts([f"a photo of a {v}, an ethnographic museum object" for v in en_vocab])
    # template tested on the UZH hats/cloths: "{v}, ein ethnografisches Museumsobjekt" puts "Hut" at
    # rank 1 (template "ein Foto von einem Museumsobjekt: {v}" only reached rank 12-67)
    T_de = emb.texts([f"{v}, ein ethnografisches Museumsobjekt" for v in de_vocab])
    print(f"zero-shot vocabularies: EN {len(en_vocab)}, DE {len(de_vocab)}")
    # hubness correction: some terms (often long, descriptive titles) are similar to *all* images.
    # Subtract each term's mean similarity over the reference images so the image itself decides.
    bias_en = (E["siglip2"][ref] @ T_en.T).mean(0)
    bias_de = (E["siglip2"][ref] @ T_de.T).mean(0)

    hits, out = 0, []
    for i in q_idx:
        ranks = []
        for m in E:
            s = E[m][ref] @ E[m][i]
            order = np.argsort(-s)
            order = [ref[o] for o in order if s[o] < 0.995][:60]      # drop exact duplicates
            ranks.append(order)
        top = rrf(ranks)[:a.k]
        # names of the neighbours, grouped by cleaned name (shown with the first original spelling)
        groups, shown = Counter(), {}
        for j in top:
            key = clean(recs[j]["name"]) or recs[j]["name"].lower()
            groups[key] += 1
            shown.setdefault(key, recs[j]["name"])
        knn_names = [(shown[k], c) for k, c in groups.most_common(6)]
        hits += head(recs[i]["name"]) in {head(recs[j]["name"]) for j in top[:5]}
        s_en = T_en @ E["siglip2"][i] - bias_en
        s_de = T_de @ E["siglip2"][i] - bias_de
        zs_en = [(en_vocab[t], float(s_en[t])) for t in np.argsort(-s_en)[:5]]
        zs_de = [(de_vocab[t], float(s_de[t])) for t in np.argsort(-s_de)[:5]]
        out.append((i, top, knn_names, zs_en, zs_de))
        r = recs[i]
        print(f"\n{r['inv']:>7} | {r['name']}")
        print("   neighbours:", "; ".join(f"{n} ×{c}" for n, c in knn_names))
        print("   zero-shot EN:", ", ".join(n for n, _ in zs_en))
        print("   zero-shot DE:", ", ".join(n for n, _ in zs_de))
    print(f"\nsanity: current head noun among the names of the top-5 neighbours for {hits}/{len(q_idx)} objects")

    # ------------------------------------------------------------------ review page
    def card(j):
        r = recs[j]
        return (f'<a class="c" href="{html.escape(r["url"])}" target="_blank" rel="noopener">'
                f'<img src="{thumb_b64(data / r["img"])}" alt="">'
                f'<b>{html.escape(r["name"][:70])}</b>'
                f'<small>{html.escape((r.get("holder") or "")[:45])}'
                f'{" · " + html.escape(r["culture"][:30]) if r.get("culture") else ""}</small></a>')

    def chips(items, fmt):
        return "".join(f'<span class="chip">{fmt(x)}</span>' for x in items)

    blocks = []
    for i, top, knn_names, zs_en, zs_de in out:
        r = recs[i]
        logbook = html.escape(re.sub(r"\s+", " ", r.get("desc") or "")[:260])
        blocks.append(f"""<section><div class="row"><div class="q">
<img src="{thumb_b64(data / r['img'], 200)}" alt="">
<b>{html.escape(r['name'])}</b><small>Inv.-Nr. {html.escape(r['inv'])} · <a href="{html.escape(r['url'])}" target="_blank" rel="noopener">Datensatz</a></small>
<small class="log">{logbook}…</small></div>
<div class="sug">
<h3>Namen der ähnlichsten Objekte (andere Sammlungen)</h3><div>{chips(knn_names, lambda x: f"{html.escape(x[0])} <i>×{x[1]}</i>")}</div>
<h3>Begriffsvorschläge zero-shot (EN)</h3><div>{chips(zs_en, lambda x: html.escape(x[0]))}</div>
<h3>Begriffsvorschläge zero-shot (DE)</h3><div>{chips(zs_de, lambda x: html.escape(x[0]))}</div>
<h3>Ähnlichste Objekte</h3><div class="grid">{"".join(card(j) for j in top[:8])}</div>
</div></div></section>""")

    page = f"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>UZH Namensvorschläge</title>
<style>
:root{{--bg:#fafaf8;--fg:#1d1d1b;--mut:#6b6b66;--card:#fff;--line:#e3e2dc;--chip:#f0eee6}}
@media (prefers-color-scheme: dark){{:root{{--bg:#191917;--fg:#ecebe6;--mut:#a3a29b;--card:#242422;--line:#3a3935;--chip:#33322e}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,sans-serif;margin:0 auto;max-width:1200px;padding:16px}}
h1{{font-size:24px}} h3{{font-size:13px;color:var(--mut);margin:12px 0 6px;font-weight:600}}
section{{border-top:1px solid var(--line);padding:12px 0}}
.row{{display:flex;gap:20px;align-items:flex-start;flex-wrap:wrap}} .q{{width:220px;display:flex;flex-direction:column;gap:4px}}
.sug{{flex:1;min-width:280px}} .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:8px}}
.c{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:6px;text-decoration:none;color:inherit;display:flex;flex-direction:column;gap:3px}}
.c img,.q img{{width:100%;aspect-ratio:1;object-fit:contain;background:#fff;border-radius:4px}}
.chip{{display:inline-block;background:var(--chip);border-radius:999px;padding:2px 10px;margin:0 6px 6px 0;font-size:13px}}
.chip i{{color:var(--mut);font-style:normal}} b{{font-size:13px}} small{{font-size:11px;color:var(--mut)}} .log{{font-style:italic}}
a{{color:inherit}}
</style></head><body>
<h1>Namensvorschläge für UZH-Objekte (PoC)</h1>
<p>{len(q_idx)} Objekte des Völkerkundemuseums der UZH aus «Mapping Philippine Material Culture» (Sammlung 439).
Referenzbestand: {len(ref)} Objekte anderer Sammlungen ({", ".join(f"{k}: {v}" for k, v in Counter(src[ref]).items())}).
Ähnlichkeit: SigLIP 2 + DINOv2, Rangfusion. Vorschläge sind Hinweise, entscheiden muss die Fachperson.
Bilder © jeweilige Museen – nur zur internen Prüfung.</p>
{"".join(blocks)}
</body></html>"""
    Path(a.html).write_text(page, encoding="utf-8")
    print("wrote", a.html)


if __name__ == "__main__":
    main()
