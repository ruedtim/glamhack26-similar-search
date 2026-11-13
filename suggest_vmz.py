"""Name suggestions for the GLAMhack sample of the Völkerkundemuseum UZH (VMZ): objects whose names
contain «?» or quotation marks (imported with ingest_vmz.py).

Per object:
  - visually similar objects in OTHER collections (SigLIP 2 + DINOv2, reciprocal rank fusion) + their names
  - terms from the museum's own vocabulary (type terms of all object names in the VMZ catalogue),
    ranked by SigLIP 2 image<->text similarity (zero-shot). The German terms are machine-translated to
    English first (opus-mt-de-en, CPU): SigLIP 2 ranks the English text far better (median rank of the
    certain type term 139 instead of 809 of 2,434). Plus English terms = names in the reference set.
  - every term in the current name gets its rank in that vocabulary, e.g. "Korb (Worfel?)" ->
    Korb #3, Worfel #400: does the photo support the hypothesis?
  - text signal: other catalogue objects with the same native name, and what they are called
Writes OUT/index.html (+ thumbnails in OUT/img) and OUT/vmz_suggestions.xlsx.
Internal material: photos and catalogue are not public.

Usage: GPU_SHARE=0.5 python suggest_vmz.py --data DATA_DIR --out vmz_review
"""
import argparse
import html
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import openpyxl
from PIL import Image

from evaluate import clean
from models import Embedder
from suggest import clean_de, rrf

QUOTES = "\"„“”«»‚‘’`´"
SEP = r"[();:,/\[\]]| oder | mit | für | aus | von | und | - "
EN_TEMPLATE = "a photo of a {}, an ethnographic museum object"
SUP_SHARE, POS_SHARE = 0.02, 0.10     # rank thresholds: top 2 % = supported, top 10 % = possible
RIGHTS_PUBLIC = ("Fotos der VMZ-Objekte: © Völkerkundemuseum der Universität Zürich. Vergleichsbilder: Cleveland "
                 "Museum of Art und Smithsonian (CC0), Museum Rietberg (CC BY-SA), Mapping Philippine Material "
                 "Culture (© die besitzenden Museen) – Miniaturen nur zum Vergleich, mit Link zur Quelle.")
MT_MODEL = "Helsinki-NLP/opus-mt-de-en"
MT_FRAME = "Ethnografische Sammlung: Maske, Trommel, {}"   # context makes single-word MT much better


def translate(terms, cache_path):
    """German term -> English (cached). Runs on the CPU with 4 threads, the GPU stays free."""
    tr = json.load(open(cache_path, encoding="utf-8")) if cache_path.exists() else {}
    todo = sorted({t for t in terms if t not in tr})
    if todo:
        import torch
        from transformers import MarianMTModel, MarianTokenizer
        torch.set_num_threads(4)
        tok = MarianTokenizer.from_pretrained(MT_MODEL)
        mt = MarianMTModel.from_pretrained(MT_MODEL).eval()
        for k in range(0, len(todo), 64):
            xs = todo[k:k + 64]
            with torch.no_grad():
                b = tok([MT_FRAME.format(x) for x in xs], return_tensors="pt", padding=True)
                out = tok.batch_decode(mt.generate(**b, num_beams=4, max_new_tokens=32), skip_special_tokens=True)
            for x, o in zip(xs, out):
                o = re.sub(r"^.*?:\s*", "", o)                          # "Ethnographic collection:"
                parts = [q.strip() for q in o.split(",")]
                tr[x] = (", ".join(parts[2:]) if len(parts) > 2 else parts[-1]).strip(" .") or x
        json.dump(tr, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
        print(f"translated {len(todo)} terms")
    return tr


def norm_term(seg):
    s = seg.translate({ord(c): " " for c in QUOTES + "?!*"})
    s = re.sub(r"\d+|\.\.\.", " ", s)
    return re.sub(r"\s+", " ", s).strip(" .-+&'")


def type_term(name):
    """Type term of a catalogue name: 'Korb (Worfel?)' -> 'Korb', 'Bild: „Abendmahl“' -> 'Bild'."""
    s = re.sub(r"\(.*?\)|\[.*?\]", " ", name or "")
    return norm_term(re.split(SEP, s)[0])


def name_terms(name):
    """Terms in a name with marks: 'Korb (Worfel?)' -> [['Korb', ''], ['Worfel', '?']];
    'Geldanhänger: “Blumengeld”' -> [['Geldanhänger', ''], ['Blumengeld', '«»']]."""
    out, prev = [], None
    for p in re.split(r"(\?|" + SEP + ")", name or ""):
        if not p or not p.strip():
            continue
        if p.strip() == "?":
            if prev is not None:
                prev[1] = "?"
            continue
        if re.fullmatch(SEP, p):
            continue
        t = norm_term(p)
        if len(t) >= 3 and t[0].isupper() and t not in {x[0] for x in out}:
            prev = [t, "«»" if any(c in p for c in QUOTES) else ""]
            out.append(prev)
        else:
            prev = None
    return out


def natives(s):
    parts = re.split(r"[,;/\n]| oder | bzw\. ", s or "")
    return [x for x in (re.sub(r"[^\w\s-]", " ", p).strip().lower() for p in parts) if len(x) >= 3]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--k", type=int, default=12)
    ap.add_argument("--min-count", type=int, default=3, help="min. frequency of a term in the VMZ catalogue")
    ap.add_argument("--records", help="records file (default DATA_DIR/records.jsonl); an older, shorter "
                                      "records file uses the first rows of the embeddings")
    ap.add_argument("--public", action="store_true",
                    help="page without accession register / description excerpts (for publication)")
    a = ap.parse_args()
    data, out = Path(a.data), Path(a.out)
    (out / "img").mkdir(parents=True, exist_ok=True)

    recs = [json.loads(l) for l in open(a.records or data / "records.jsonl", encoding="utf-8")]
    E = {m: np.load(data / f"emb_{m}.npy") for m in ["siglip2", "dinov2"]}
    if any(len(v) != len(recs) for v in E.values()):
        ids = json.load(open(data / "ids.json"))
        assert ids[:len(recs)] == [r["id"] for r in recs], "re-run embed.py after harvesting / ingest_vmz.py"
        E = {m: v[:len(recs)] for m, v in E.items()}
    cat = [json.loads(l) for l in open(data / "vmz_catalog.jsonl", encoding="utf-8")]
    by_sig = {}
    for c in cat:
        by_sig.setdefault(c["sig"], c)
    src = np.array([r["source"] for r in recs])
    own = np.array([r["source"] in ("uzh", "vmz") or "zurich" in (r.get("holder") or "").lower()
                    or "zürich" in (r.get("holder") or "").lower() for r in recs])
    q_idx = np.where(src == "vmz")[0]
    ref = np.where(~own)[0]
    print(f"queries (VMZ): {len(q_idx)}; reference: {len(ref)} {dict(Counter(src[ref]))}")

    # ---------------------------------------------------------------- vocabularies
    tcount = Counter(type_term(c["name"]) for c in cat)
    de_vocab = sorted(t for t, n in tcount.items() if n >= a.min_count and len(t) >= 3 and t[0].isupper())
    en_counts = Counter(clean(recs[j]["name"]) for j in ref if recs[j]["source"] in ("phil", "cma", "si"))
    en_vocab = sorted(n for n, c in en_counts.items() if c >= 2 and len(n) > 2)
    terms_q = {i: name_terms(recs[i]["name"]) for i in q_idx}
    hyp_vocab = sorted({t for ts in terms_q.values() for t, _ in ts})
    tr = translate(de_vocab + hyp_vocab, data / "vmz_vocab_en.json")
    emb = Embedder("siglip2")
    T_de = emb.texts([EN_TEMPLATE.format(tr[v]) for v in de_vocab])
    T_en = emb.texts([EN_TEMPLATE.format(v) for v in en_vocab])
    T_h = emb.texts([EN_TEMPLATE.format(tr[v]) for v in hyp_vocab])
    sup, pos = round(SUP_SHARE * len(de_vocab)), round(POS_SHARE * len(de_vocab))
    print(f"vocabularies: VMZ-DE {len(de_vocab)} terms (>= {a.min_count} objects), EN {len(en_vocab)}, "
          f"terms in current names {len(hyp_vocab)}")
    # hubness correction: subtract half of each term's mean similarity over all images (reference + VMZ);
    # 0.5 was the better compromise between specific and generic terms in the VMZ test
    allimg = E["siglip2"][np.concatenate([ref, q_idx])]
    b_de, b_en, b_h = (0.5 * (allimg @ T.T).mean(0) for T in (T_de, T_en, T_h))
    de_pos = {t: k for k, t in enumerate(de_vocab)}
    h_pos = {t: k for k, t in enumerate(hyp_vocab)}

    # ---------------------------------------------------------------- native-name index (catalogue)
    nat_idx = defaultdict(Counter)
    for c in cat:
        if "?" in c["name"] or any(q in c["name"] for q in QUOTES):
            continue
        t = type_term(c["name"])
        for n in natives(c.get("native")):
            if t:
                nat_idx[n][t] += 1

    # ---------------------------------------------------------------- per object
    rows, stats = [], Counter(type_ranks=[])
    top1_sims = []
    for i in q_idx:
        r = recs[i]
        e = E["siglip2"][i]
        ranks, sims = [], {}
        for m in E:
            s = E[m][ref] @ E[m][i]
            order = [o for o in np.argsort(-s) if s[o] < 0.995][:60]
            ranks.append([ref[o] for o in order])
            if m == "siglip2":
                sims = {ref[o]: float(s[o]) for o in order}
                top1_sims.append(float(s[order[0]]))
        top = rrf(ranks)[:a.k]
        groups, shown = Counter(), {}
        for j in top:
            nm = recs[j]["name"]
            key = (clean_de(nm).lower() if recs[j]["source"] == "mrz" else clean(nm)) or nm.lower()
            groups[key] += 1
            shown.setdefault(key, nm)
        knn_names = [(shown[k], c) for k, c in groups.most_common(6)]

        s_de = T_de @ e - b_de
        order_de = np.argsort(-s_de)
        zs_de = [de_vocab[t] for t in order_de[:8]]
        s_en = T_en @ e - b_en
        zs_en = [en_vocab[t] for t in np.argsort(-s_en)[:5]]
        s_h = T_h @ e - b_h
        term_ranks = []
        for t, mark in terms_q[i]:
            v = s_h[h_pos[t]]
            rank = 1 + int((s_de > v).sum()) - (1 if t in de_pos and s_de[de_pos[t]] > v else 0)
            term_ranks.append((t, mark, rank))

        c = by_sig.get(r.get("cat_sig") or "", {})
        nat = []
        for n in natives(c.get("native")):
            for t, k in nat_idx.get(n, Counter()).most_common(3):
                nat.append((n, t, k))

        # proxy statistics: is the type term of the current name (if certain) among the top VMZ terms?
        tt = type_term(r["name"])
        certain = bool(terms_q[i]) and terms_q[i][0][0] == tt and terms_q[i][0][1] == ""
        if tt in de_pos and certain:
            rk = 1 + int((s_de > s_de[de_pos[tt]]).sum())
            stats["type_n"] += 1
            stats["type_top8"] += rk <= 8
            stats["type_sup"] += rk <= sup
            stats["type_pos"] += sup < rk <= pos
            stats["type_ranks"] += [rk]
        for t, mark, rank in term_ranks:
            if mark == "?":
                stats["hyp_n"] += 1
                stats["hyp_sup"] += rank <= sup
                stats["hyp_pos"] += sup < rank <= pos
        rows.append(dict(i=i, top=top, sims=sims, knn=knn_names, de=zs_de, en=zs_en, terms=term_ranks, nat=nat,
                         cat=c))
    n = len(q_idx)
    print(f"\nnearest neighbour (SigLIP 2 cosine) median {np.median(top1_sims):.3f}, "
          f"p10 {np.percentile(top1_sims, 10):.3f}, p90 {np.percentile(top1_sims, 90):.3f}")
    if stats["type_n"]:
        tn = stats["type_n"]
        print(f"type term of the current name (certain part, in vocabulary): n={tn}, top-8 {stats['type_top8'] / tn:.0%}, "
              f"rank <= {sup}: {stats['type_sup'] / tn:.0%}, {sup + 1}-{pos}: {stats['type_pos'] / tn:.0%}, "
              f"median rank {int(np.median(stats['type_ranks']))} of {len(de_vocab)}")
    if stats["hyp_n"]:
        hn = stats["hyp_n"]
        print(f"«?» hypotheses: n={hn}, rank <= {sup}: {stats['hyp_sup'] / hn:.0%}, "
              f"{sup + 1}-{pos}: {stats['hyp_pos'] / hn:.0%}")
    print(f"objects with native name: {sum(bool(natives(x['cat'].get('native'))) for x in rows)}, "
          f"with catalogue matches for it: {sum(bool(x['nat']) for x in rows)}")

    for x in rows[:: max(1, n // 30)]:
        r = recs[x["i"]]
        print(f"\n{r['inv']:>11} {r['flag']:2} | {r['name'][:70]}")
        print("     terms:", ", ".join(f"{t}{m and ' ' + m} #{k} ({tr[t]})" for t, m, k in x["terms"]))
        print("     VMZ-DE:", ", ".join(f"{t} ({tr[t]})" for t in x["de"][:5]), "| EN:", ", ".join(x["en"][:3]))
        print("     neighbours:", "; ".join(f"{a_} ×{b}" for a_, b in x["knn"][:4]))
        if x["nat"]:
            print("     same native name:", "; ".join(f"{a_} → {t} ×{k}" for a_, t, k in x["nat"][:3]))

    # machine-readable results (used by make_overview.py)
    res = {"n": n, "ref": {str(k): int(v) for k, v in Counter(src[ref]).items()}, "vocab": len(de_vocab),
           "sup": sup, "pos": pos,
           "stats": {k: (v if not isinstance(v, list) else int(np.median(v)) if v else None)
                     for k, v in stats.items()},
           "objects": []}
    for x, s1 in zip(rows, top1_sims):
        r = recs[x["i"]]
        res["objects"].append({
            "inv": r["inv"], "name": r["name"], "flag": r["flag"], "match": r["match"], "img": r["img"],
            "culture": r.get("culture", ""), "country": x["cat"].get("country", ""),
            "native": x["cat"].get("native", ""), "top1": round(s1, 3),
            "terms": [{"term": t, "mark": m, "rank": k, "en": tr.get(t, "")} for t, m, k in x["terms"]],
            "vmz_terms": [{"term": t, "en": tr.get(t, "")} for t in x["de"]], "en_terms": x["en"],
            "neighbour_names": [{"name": nm, "count": k} for nm, k in x["knn"]],
            "native_matches": [{"native": nn, "term": t, "count": k} for nn, t, k in x["nat"]],
            "neighbours": [{"id": recs[j]["id"], "name": recs[j]["name"], "holder": recs[j].get("holder", ""),
                            "culture": recs[j].get("culture", ""), "url": recs[j]["url"], "img": recs[j]["img"],
                            "licence": recs[j].get("licence", ""), "sim": round(x["sims"].get(j, 0), 3)}
                           for j in x["top"][:8]]})
    json.dump(res, open(out / "vmz_results.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    write_outputs(a, out, recs, data, rows, stats, n, ref, src, de_vocab, top1_sims, tr, sup, pos)


def thumb(src_path, dst, side, cache):
    if dst.name not in cache:
        im = Image.open(src_path).convert("RGB")
        im.thumbnail((side, side))
        im.save(dst, quality=80)
        cache.add(dst.name)
    return f"img/{dst.name}"


def write_outputs(a, out, recs, data, rows, stats, n, ref, src, de_vocab, top1_sims, tr, sup, pos):
    esc = html.escape
    done = set(p.name for p in (out / "img").glob("*.jpg"))

    def status(rank):
        return "sup" if rank <= sup else "pos" if rank <= pos else "no"

    blocks = []
    for x in rows:
        r = recs[x["i"]]
        c = x["cat"]
        safe = re.sub(r"[^\w.-]+", "_", r["inv"])
        qimg = thumb(data / r["img"], out / "img" / f"q_{safe}.jpg", 320, done)
        cards = []
        for j in x["top"][:8]:
            rj = recs[j]
            t = thumb(data / rj["img"], out / "img" / ("r_" + re.sub(r"[^\w.-]+", "_", rj["id"]) + ".jpg"), 150, done)
            sim = x["sims"].get(j)
            cards.append(
                f'<a class="c" href="{esc(rj["url"])}" target="_blank" rel="noopener">'
                f'<img src="{t}" alt="" loading="lazy"><b>{esc(rj["name"][:70])}</b>'
                f'<small>{esc((rj.get("holder") or "")[:45])}{" · " + esc(rj["culture"][:30]) if rj.get("culture") else ""}'
                f'{f" · {sim:.2f}" if sim else ""}</small></a>')
        hyp = [t for t in x["terms"] if t[1] == "?"]
        hyp_state = ("na" if not hyp else "sup" if any(k <= sup for _, _, k in hyp)
                     else "pos" if any(k <= pos for _, _, k in hyp) else "no")
        term_chips = "".join(
            f'<span class="chip {status(k)}" title="Rang im VMZ-Vokabular ({len(de_vocab)} Begriffe)">'
            f'{esc(t)}{" " + m if m else ""} <i>#{k} · {esc(tr.get(t, ""))}</i></span>' for t, m, k in x["terms"])
        meta = [("Einheimisch", c.get("native")), ("Ethnie", c.get("ethnie")),
                ("Region", ", ".join(v for v in (c.get("geo_region"), c.get("country")) if v)),
                ("Gebrauch", c.get("use")), ("Material", c.get("material"))]
        meta_html = "".join(f"<small><span class=k>{k}:</span> {esc(v[:120])}</small>" for k, v in meta if v)
        log = "" if a.public else re.sub(r"\s+", " ", r.get("desc") or "")
        note = (f'<small class="warn">Teilobjekt: Katalogdaten vom Hauptobjekt {esc(r["cat_sig"])}</small>'
                if r.get("match") == "main object" else
                '<small class="warn">nicht im Katalog gefunden</small>' if r.get("match") == "none" else "")
        nat = "".join(f'<span class="chip">{esc(t)} <i>×{k} ({esc(nn)})</i></span>' for nn, t, k in x["nat"][:4])
        text = " ".join([r["inv"], r["name"], c.get("native", ""), c.get("ethnie", ""), c.get("country", ""),
                         " ".join(x["de"]), " ".join(x["en"]), " ".join(nm for nm, _ in x["knn"])]).lower()
        blocks.append(f"""<section data-flag="{esc(r['flag'])}" data-hyp="{hyp_state}" data-text="{esc(text)}">
<div class="row"><div class="q"><img src="{qimg}" alt="" loading="lazy">
<b class="name">{esc(r['name'] or '–')}</b>
<small>Inv.-Nr. <b>{esc(r['inv'])}</b> · {esc(r['image_url'].replace('VMZ_objects-with-', '').replace('.pdf', ''))}</small>
{note}{meta_html}<small class="log">{esc(log[:240])}{'…' if len(log) > 240 else ''}</small></div>
<div class="sug">
<h3>Begriffe im aktuellen Namen – Rang im VMZ-Vokabular</h3><div>{term_chips or '<small>–</small>'}</div>
<h3>Passende Begriffe aus dem VMZ-Vokabular (Bild ↔ Text)</h3><div>{''.join(f'<span class="chip">{esc(t)} <i>{esc(tr.get(t, ""))}</i></span>' for t in x['de'])}</div>
<h3>Englische Begriffe (Namen in den Vergleichssammlungen)</h3><div>{''.join(f'<span class="chip">{esc(t)}</span>' for t in x['en'])}</div>
<h3>Namen der ähnlichsten Objekte (andere Sammlungen)</h3><div>{''.join(f'<span class="chip">{esc(nm)} <i>×{k}</i></span>' for nm, k in x['knn'])}</div>
{f'<h3>Gleicher einheimischer Name im VMZ-Katalog</h3><div>{nat}</div>' if nat else ''}
<h3>Ähnlichste Objekte</h3><div class="grid">{''.join(cards)}</div>
</div></div></section>""")

    tn, hn = max(1, stats["type_n"]), max(1, stats["hyp_n"])
    refmix = ", ".join(f"{ {'phil': 'Mapping Philippine Material Culture', 'mrz': 'Museum Rietberg', 'cma': 'Cleveland Museum of Art', 'si': 'Smithsonian'}.get(k, k)}: {v}"
                       for k, v in Counter(src[ref]).items())
    page = f"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>VMZ Namensvorschläge</title>
<style>
:root{{--bg:#fafaf8;--fg:#1d1d1b;--mut:#6b6b66;--card:#fff;--line:#e3e2dc;--chip:#f0eee6;--sup:#d7ecd9;--pos:#f3ead0;--no:#f0eee6;--warn:#9a5b00}}
@media (prefers-color-scheme: dark){{:root:not([data-theme="light"]){{--bg:#191917;--fg:#ecebe6;--mut:#a3a29b;--card:#242422;--line:#3a3935;--chip:#33322e;--sup:#24402a;--pos:#463d22;--no:#33322e;--warn:#e0a24a}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,sans-serif;margin:0 auto;max-width:1240px;padding:16px}}
h1{{font-size:24px;margin:8px 0}} h3{{font-size:13px;color:var(--mut);margin:12px 0 6px;font-weight:600}}
.bar{{position:sticky;top:0;background:var(--bg);padding:10px 0;border-bottom:1px solid var(--line);display:flex;gap:8px;flex-wrap:wrap;align-items:center;z-index:2}}
.bar input,.bar select{{font:inherit;padding:6px 10px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg)}}
.bar input{{flex:1;min-width:200px}}
section{{border-bottom:1px solid var(--line);padding:14px 0}}
.row{{display:flex;gap:20px;align-items:flex-start;flex-wrap:wrap}} .q{{width:260px;display:flex;flex-direction:column;gap:4px}}
.sug{{flex:1;min-width:280px}} .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(104px,1fr));gap:8px}}
.c{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:6px;text-decoration:none;color:inherit;display:flex;flex-direction:column;gap:3px}}
.c img,.q img{{width:100%;aspect-ratio:1;object-fit:contain;background:#fff;border-radius:4px}}
.chip{{display:inline-block;background:var(--chip);border-radius:999px;padding:2px 10px;margin:0 6px 6px 0;font-size:13px}}
.chip.sup{{background:var(--sup)}} .chip.pos{{background:var(--pos)}} .chip i{{color:var(--mut);font-style:normal}}
b{{font-size:13px}} .name{{font-size:15px}} small{{font-size:11px;color:var(--mut)}} .k{{font-weight:600}} .log{{font-style:italic}}
.warn{{color:var(--warn)}} a{{color:inherit}} .lead{{max-width:900px}} .lead small{{font-size:13px}}
@media (max-width:600px){{.q{{width:100%}}}}
</style></head><body>
<h1>Namensvorschläge für VMZ-Objekte mit «?» oder Anführungszeichen (PoC)</h1>
<div class="lead"><p>{n} Objekte aus der GLAMhack-Stichprobe des Völkerkundemuseums der Universität Zürich.
Vergleichsbestand: {len(ref)} Objekte anderer Sammlungen ({refmix}). Bildähnlichkeit: SigLIP 2 + DINOv2 (Rangfusion);
Begriffe: SigLIP 2 Bild ↔ Text gegen {len(de_vocab)} Typbegriffe aus den Objektnamen des VMZ-Katalogs (≥ {a.min_count} Objekte),
vorher maschinell ins Englische übersetzt (grau: die Übersetzung, mit der gerechnet wurde).</p>
<p><small>Rang = Platz des Begriffs unter allen {len(de_vocab)} VMZ-Begriffen für dieses Foto:
<span class="chip sup">≤ {sup}: vom Bild gestützt</span><span class="chip pos">≤ {pos}: möglich</span><span class="chip">&gt; {pos}: nicht gestützt</span>
Kalibrierung an den sicheren Typbegriffen der aktuellen Namen (n={stats['type_n']}): {stats['type_sup'] / tn:.0%} gestützt, {stats['type_pos'] / tn:.0%} möglich,
Median-Rang {int(np.median(stats['type_ranks'])) if stats['type_ranks'] else '–'}. «Gestützt» ist also ein starkes Indiz (zufällig: 2 %),
«nicht gestützt» nur ein schwaches – auch richtige Begriffe landen oft dort, besonders seltene Fachwörter oder falsch übersetzte.
Von {stats['hyp_n']} «?»-Hypothesen sind {stats['hyp_sup'] / hn:.0%} gestützt, {stats['hyp_pos'] / hn:.0%} möglich.
Zahl auf den Karten = Bildähnlichkeit (SigLIP 2, höher = ähnlicher).
Vorschläge sind Hinweise – entscheiden muss die Fachperson.
{RIGHTS_PUBLIC if a.public else 'Bilder und Katalogdaten: intern, nicht veröffentlichen.'}</small></p></div>
<div class="bar"><input id="q" type="search" placeholder="Suche: Inventarnummer, Name, Begriff, Region …" aria-label="Suche">
<select id="flag" aria-label="Markierung"><option value="">«?» und Anführungszeichen</option><option value="?">nur «?»</option><option value="«»">nur Anführungszeichen</option></select>
<select id="hyp" aria-label="Hypothese"><option value="">alle Hypothesen</option><option value="sup">«?»-Hypothese gestützt</option><option value="pos">«?»-Hypothese möglich</option><option value="no">«?»-Hypothese nicht gestützt</option></select>
<small id="count"></small></div>
{''.join(blocks)}
<script>
const secs=[...document.querySelectorAll('section')], q=document.getElementById('q'), f=document.getElementById('flag'), h=document.getElementById('hyp'), cnt=document.getElementById('count');
function upd(){{const s=q.value.trim().toLowerCase(); let k=0;
 for(const e of secs){{const ok=(!s||e.dataset.text.includes(s)||e.dataset.text.split(' ').some(w=>w===s))&&(!f.value||e.dataset.flag.includes(f.value[0]))&&(!h.value||e.dataset.hyp===h.value);
  e.hidden=!ok; k+=ok;}} cnt.textContent=k+' von '+secs.length+' Objekten';}}
[q,f,h].forEach(el=>el.addEventListener('input',upd)); upd();
</script></body></html>"""
    (out / "index.html").write_text(page, encoding="utf-8")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Vorschläge"
    ws.append(["Inventarnummer", "Objektname (aktuell)", "Markierung", "Katalog", "Einheimischer Name", "Ethnie",
               "Land", f"Begriffe im Namen (Rang von {len(de_vocab)}; ≤{sup} gestützt, ≤{pos} möglich)",
               "VMZ-Begriffe (Bild↔Text, mit MT-Übersetzung)", "Englische Begriffe",
               "Namen ähnlicher Objekte", "Gleicher einheimischer Name im Katalog",
               "Ähnlichste Objekte (Name | Museum | Link)", "Ähnlichkeit Top-1 (SigLIP 2)"])
    for x, s1 in zip(rows, top1_sims):
        r, c = recs[x["i"]], x["cat"]
        ws.append([r["inv"], r["name"], r["flag"], r["match"] if r["match"] != "exact" else "",
                   c.get("native", ""), c.get("ethnie", ""), c.get("country", ""),
                   "; ".join(f"{t}{m and ' ' + m} #{k} ({tr.get(t, '')})" for t, m, k in x["terms"]),
                   "; ".join(f"{t} ({tr.get(t, '')})" for t in x["de"]), "; ".join(x["en"]),
                   "; ".join(f"{nm} ×{k}" for nm, k in x["knn"]),
                   "; ".join(f"{t} ×{k} ({nn})" for nn, t, k in x["nat"]),
                   "\n".join(f"{recs[j]['name'][:60]} | {recs[j].get('holder', '')[:40]} | {recs[j]['url']}"
                             for j in x["top"][:5]),
                   round(s1, 3)])
    for col, w in zip("ABCDEFGHIJKLMN", [12, 40, 8, 10, 18, 18, 14, 40, 50, 40, 50, 30, 80, 10]):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "C2"
    wb.save(out / "vmz_suggestions.xlsx")
    print(f"\nwrote {out / 'index.html'} ({len(list((out / 'img').glob('*.jpg')))} thumbnails) "
          f"and {out / 'vmz_suggestions.xlsx'}")


if __name__ == "__main__":
    main()
