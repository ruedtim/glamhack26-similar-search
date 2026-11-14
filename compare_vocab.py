"""Term suggestions from external controlled vocabularies vs the VMZ's own vocabulary: evaluation and prototype.

Same zero-shot method as the lists (suggest_vmz.py, suggest_mkb.py): SigLIP 2 image <-> English text with the
prompt EN_TEMPLATE, minus half of each text's mean similarity over all images (hubness correction). Run over
  - «VMZ»: the type terms of the VMZ catalogue (>= 3 objects), machine-translated – what the lists showed so far;
  - «AAT alle»: the AAT concepts of the object hierarchies (vocab_external.py), with their English AAT labels;
  - «AAT NMVW»: only the AAT concepts the NMVW thesaurus uses;
  - «ethno»: the AAT concepts that the NMVW thesaurus uses, AAT-Deutsch translates or the GND links, plus the NMVW
    object terms without AAT match (English NMVW label);
  - «de»: only the AAT concepts with a German label (AAT-Deutsch or the linked GND heading).
The photo is always compared with the English label; the pages show the German label where there is one.
Evaluated on the certain type terms of the current names (VMZ: the «?»/quotation-mark sample; MKB: all objects
with a certain name): is the concept of the name among the first k suggestions – the same concept («gleich») or
also a narrower one («oder enger»)? Where does it rank? Plus the «?» hypotheses of the VMZ sample and the
Trachsler classes. --html writes a prototype page for a sample of objects (thumbnails of the published lists,
embedded, so the single file opens anywhere).

Usage: GPU_SHARE=0.5 python compare_vocab.py --data DATA_DIR --vocab DATA_DIR/vocab --text-model siglip2_so400m \
           --mt-cache DATA_DIR/vmz_vocab_en.json --json metrics.json --html dist/vocab-prototype/index.html
"""
import argparse
import base64
import html
import json
import re
from collections import Counter
from pathlib import Path

import numpy as np

from models import load_embeddings
from suggest_vmz import EN_TEMPLATE, LIST_CSS, fname, name_terms, translate, type_term
from vocab_external import VOCAB_CSS, Suggester, TextCache, Vocab, card_html, card_links, material_html, mean_sim

KS = (1, 3, 5, 8)
PROTO_CSS = """
table.ev{border-collapse:collapse;font-size:13px;margin:8px 0 14px;max-width:100%;display:block;overflow-x:auto}
table.ev td,table.ev th{border-bottom:1px solid var(--line);padding:4px 8px;text-align:right;vertical-align:top}
table.ev td:first-child,table.ev th:first-child,table.ev td.l,table.ev th.l{text-align:left}
table.ev th{color:var(--mut);font-weight:600}
details.old{font-size:12px;color:var(--mut);margin-top:10px} details.old summary{cursor:pointer}
.lead h2{font-size:18px;margin:18px 0 6px}
"""


def topk(s, k):
    p = np.argpartition(-s, k)[:k]
    return p[np.argsort(-s[p])]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--vocab", required=True, help="folder with vocab_external.json (vocab_external.py)")
    ap.add_argument("--text-model", default="siglip2_so400m")
    ap.add_argument("--mt-cache", help="translation cache of the VMZ terms (default DATA_DIR/vmz_vocab_en.json)")
    ap.add_argument("--min-count", type=int, default=3, help="min. frequency of a term in the VMZ catalogue")
    ap.add_argument("--json", help="write the metrics to this file")
    ap.add_argument("--html", help="prototype page for a sample of objects (e.g. dist/vocab-prototype/index.html)")
    ap.add_argument("--thumbs", default="docs/review/img", help="thumbnails of the published lists")
    ap.add_argument("--variant", default="ethno", help="candidate set of the prototype: ethno, de, all, nmvw")
    a = ap.parse_args()
    data, vdir = Path(a.data), Path(a.vocab)

    recs = [json.loads(line) for line in open(data / "records.jsonl", encoding="utf-8")]
    E = load_embeddings(data, a.text_model, recs)
    src = np.array([r["source"] for r in recs])
    v = Vocab(vdir / "vocab_external.json")
    cat = [json.loads(line) for line in open(data / "vmz_catalog.jsonl", encoding="utf-8")]
    tcount = Counter(type_term(c["name"]) for c in cat)
    de_vocab = sorted(t for t, n in tcount.items() if n >= a.min_count and len(t) >= 3 and t[0].isupper())
    de_pos = {t: k for k, t in enumerate(de_vocab)}
    q_vmz, q_mkb = np.where(src == "vmz")[0], np.where(src == "mkb")[0]
    terms = {i: name_terms(recs[i]["name"]) for i in np.concatenate([q_vmz, q_mkb])}
    tr = translate(de_vocab + sorted({t for ts in terms.values() for t, _ in ts}),
                   Path(a.mt_cache) if a.mt_cache else data / "vmz_vocab_en.json")
    texts = TextCache(a.text_model, vdir)

    # ------------------------------------------------------------ candidates, text embeddings, hubness correction
    sug = Suggester(v, texts, E, tr, vdir, variant=a.variant)
    cand, T, b = sug.cand, sug.T, sug.b
    T_de = texts([EN_TEMPLATE.format(tr[t]) for t in de_vocab], "vmz")
    b_de = 0.5 * mean_sim(E, T_de)
    print(f"external candidates: {len(cand)} (NMVW without AAT {sum(v.is_nmvw(c) for c in cand)}); "
          f"VMZ terms: {len(de_vocab)}")
    variants = {"AAT alle": np.array([sug.pos[c] for c in v.candidates("all")]),
                "AAT NMVW": np.array([sug.pos[c] for c in v.candidates("nmvw")]),
                "ethno": np.array([sug.pos[c] for c in v.candidates("ethno")]),
                "de": np.array([sug.pos[c] for c in v.candidates("de")])}
    vpos = {m: {cand[c]: k for k, c in enumerate(sub)} for m, sub in variants.items()}

    def certain(i):
        tt = type_term(recs[i]["name"])
        ts = terms[i]
        return tt if ts and ts[0][0] == tt and ts[0][1] == "" else None

    sets = {"VMZ": [i for i in q_vmz if recs[i].get("flag") != "Figur" and certain(i)],
            "MKB": [i for i in q_mkb if certain(i)]}
    res = {}
    for sname, idx in sets.items():
        st = {m: Counter(ranks=[]) for m in ["VMZ"] + list(variants)}
        st_route, tra_st = Counter(), Counter()
        for s0 in range(0, len(idx), 1000):
            chunk = idx[s0:s0 + 1000]
            X = E[chunk]
            S, S_de, S_tra = X @ T.T - b, X @ T_de.T - b_de, X @ sug.T_tra.T - sug.b_tra
            for qi, i in enumerate(chunk):
                tt = certain(i)
                o = st["VMZ"]                       # before: rank of the type term among the VMZ terms
                o["n"] += 1
                if tt in de_pos:
                    s = S_de[qi]
                    rk = 1 + int((s > s[de_pos[tt]]).sum())
                    o["mapped"] += 1
                    o["ranks"].append(rk)
                    o["sup"] += rk <= round(0.02 * len(de_vocab))
                    o["pos"] += rk <= round(0.10 * len(de_vocab))
                    for k in KS:
                        o[f"strict@{k}"] += rk <= k
                        o[f"narrow@{k}"] += rk <= k
                ids, route = v.match_de(tt, tr.get(tt))     # now: the concepts of the type term
                st_route[route or "none"] += 1
                for m, sub in variants.items():
                    o = st[m]
                    o["n"] += 1
                    tix = [vpos[m][c] for c in ids if c in vpos[m]]
                    if not tix:
                        continue
                    s = S[qi, sub]
                    o["mapped"] += 1
                    o["route_" + route] += 1
                    rk = 1 + int((s > s[tix].max()).sum())
                    o["ranks"].append(rk)
                    o["sup"] += rk <= round(0.02 * len(sub))
                    o["pos"] += rk <= round(0.10 * len(sub))
                    top = [cand[sub[j]] for j in topk(s, max(KS))]
                    for k in KS:
                        o[f"strict@{k}"] += any(c in ids for c in top[:k])
                        o[f"narrow@{k}"] += any(v.is_within(c, t) for c in top[:k] for t in ids)
                        if route == "exact":
                            o[f"exact_strict@{k}"] += any(c in ids for c in top[:k])
                # Trachsler: the classes whose title names the type term (score >= 3) are the target
                sc = v.trachsler_scores(tt)
                gold = [t for t, x in sc.items() if x >= 3]
                if gold:
                    tra_st["n"] += 1
                    top = [sug.tra_ids[j] for j in topk(S_tra[qi], 5)]
                    for k in (1, 3, 5):
                        tra_st[f"hit@{k}"] += any(v.trachsler_within(t, g) for t in top[:k] for g in gold)
        res[sname] = {m: {k: (int(np.median(x)) if k == "ranks" and x else x) for k, x in o.items()}
                      for m, o in st.items()}
        res[sname]["routes"] = dict(st_route)
        res[sname]["trachsler"] = dict(tra_st)

    # ------------------------------------------------------------ «?» hypotheses (VMZ sample)
    hyp = {m: Counter() for m in variants}
    calib = [i for i in q_vmz if recs[i].get("flag") != "Figur"]
    S = E[calib] @ T.T - b
    for qi, i in enumerate(calib):
        for t, mark in terms[i]:
            if mark != "?":
                continue
            ids, route = v.match_de(t, tr.get(t))
            for m, sub in variants.items():
                o = hyp[m]
                o["n"] += 1
                tix = [vpos[m][c] for c in ids if c in vpos[m]]
                if not tix:
                    continue
                s = S[qi, sub]
                rk = 1 + int((s > s[tix].max()).sum())
                o["mapped"] += 1
                o["sup"] += rk <= round(0.02 * len(sub))
                o["pos"] += rk <= round(0.10 * len(sub))
                o["top50"] += rk <= 50
    res["hypotheses"] = {m: dict(o) for m, o in hyp.items()}
    res["sizes"] = {m: len(s) for m, s in variants.items()} | {"VMZ": len(de_vocab), "Trachsler": len(sug.tra_ids)}

    # ------------------------------------------------------------ report
    for sname in sets:
        print(f"\n== {sname}: {len(sets[sname])} objects with a certain type term; routes {res[sname]['routes']}")
        print(f"{'vocabulary':10} {'size':>6} {'mapped':>7} {'median':>6} {'top2%':>6} {'top10%':>6}  "
              + "  ".join(f"@{k} same/narrow" for k in KS))
        for m in ["VMZ"] + list(variants):
            o = res[sname][m]
            n = o["n"]
            print(f"{m:10} {res['sizes'][m]:6} {o.get('mapped', 0) / n:7.0%} {o['ranks'] or '–':>6} "
                  f"{o.get('sup', 0) / n:6.0%} {o.get('pos', 0) / n:6.0%}  "
                  + "  ".join(f"{o.get(f'strict@{k}', 0) / n:5.0%}/{o.get(f'narrow@{k}', 0) / n:5.0%}" for k in KS))
        t = res[sname]["trachsler"]
        if t.get("n"):
            print(f"Trachsler (n={t['n']} with a class naming the type term): photo top-1 {t['hit@1'] / t['n']:.0%}, "
                  f"top-3 {t['hit@3'] / t['n']:.0%}, top-5 {t['hit@5'] / t['n']:.0%} (photo only, no word match)")
    print("\n«?» hypotheses (VMZ):", {m: {k: (f"{x / o['n']:.0%}" if k != "n" else x) for k, x in o.items()}
                                     for m, o in res["hypotheses"].items()})
    if a.json:
        json.dump(res, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if a.html:
        prototype(a, recs, E, v, sug, tr, terms, de_vocab, de_pos, T_de, b_de, res, sets)


def sample(recs, q_vmz, q_mkb):
    """Objects for the prototype: the examples of the README and the overview, objects named only «Figur», every
    60th VMZ object, MKB objects of frequent types and every 700th."""
    pick, seen = [], set()

    def add(i):
        if i not in seen:
            seen.add(i)
            pick.append(i)

    for pat in [r"Korb \(Worfel", r"Pfeilspitze", r"Harpune", r"Mahākāla", r"Penisbinde", r"Mörser", r"^Ornament",
                r"^Rassel", r"^Goldgewicht", r"Bettüberwurf", r"Perlhuhn", r"Bauchaufschlitzer", r"Schnabelgeiss",
                r"Abendmahl"]:
        for i in q_vmz:
            if re.search(pat, recs[i]["name"]):
                add(i)
                break
    for i in [i for i in q_vmz if recs[i].get("flag") == "Figur"][::45]:
        add(i)
    for i in q_vmz[::60]:
        add(i)
    for pat in [r"^Maske$", r"^Kopfstütze$", r"^Löffel$", r"^Trommel$", r"^Figur$", r"^Armring$", r"^Hocker$",
                r"^Kamm$", r"^Korb$", r"^Schale$"]:
        for i in q_mkb:
            if re.search(pat, recs[i]["name"]):
                add(i)
                break
    for i in q_mkb[::700]:
        add(i)
    return pick


def prototype(a, recs, E, v, sug, tr, terms, de_vocab, de_pos, T_de, b_de, res, sets):
    esc = html.escape
    out = Path(a.html)
    out.parent.mkdir(parents=True, exist_ok=True)
    src = np.array([r["source"] for r in recs])
    rows = []
    for i in sample(recs, np.where(src == "vmz")[0], np.where(src == "mkb")[0]):
        r = recs[i]
        sugg, named = sug.analyse(E[i], terms[i], k=6)
        chips = []
        for x in named:
            pre = f'<span class="arr">{esc(x["term"])}{" " + x["mark"] if x["mark"] else ""} →</span> '
            if x["material"]:
                chips.append(material_html(x, esc, pre))
            elif x["card"]:
                note = ('<span class="tag" title="nur das Wortende hat ein Konzept">Oberbegriff</span>'
                        if x["route"] == "head" else "")
                chips.append(card_html(x["card"], esc, cls=x["status"] if x["status"] != "no" else "", pre=pre,
                                       note=note, title=f"Rang {x['rank']} von {sug.n} Konzepten für dieses Foto"))
            else:
                links = card_links({"gnd": x["gnd"], "tra": x["tra"]}, esc)
                chips.append(f'<span class="chip vc">{pre}<span class="tag">kein Konzept gefunden</span>'
                             + (f'<span class="src">{links}</span>' if links else "") + "</span>")
        s_de = E[i] @ T_de.T - b_de
        old = ", ".join(f"{esc(de_vocab[j])} <i>({esc(tr.get(de_vocab[j], ''))})</i>" for j in topk(s_de, 8))
        old_ranks = ", ".join(f"{esc(t)}{' ' + m if m else ''} #{1 + int((s_de > s_de[de_pos[t]]).sum())}"
                              if t in de_pos else f"{esc(t)} (nicht im VMZ-Vokabular)" for t, m in terms[i])
        is_vmz = r["source"] == "vmz"
        thumb = Path(a.thumbs) / (f"q_{fname(r['inv'])}.jpg" if is_vmz else f"r_{fname(r['id'])}.jpg")
        img = ("data:image/jpeg;base64," + base64.b64encode(thumb.read_bytes()).decode()) if thumb.exists() else ""
        rows.append(f"""<section><div class="row"><div class="q">
<img src="{img}" alt="" loading="lazy"><b class="name">{esc(r['name'] or '–')}</b>
<small>{'VMZ' if is_vmz else 'MKB'} · Inv.-Nr. <b>{esc(r['inv'])}</b>{' · ' + esc(r['flag']) if r.get('flag') else ''}</small>
<small>{esc((r.get('culture') or '')[:80])}</small></div>
<div class="sug"><h3>Begriffe im aktuellen Namen – in kontrollierten Vokabularen</h3><div>{''.join(chips) or '<small>–</small>'}</div>
<h3>Vorschläge aus kontrollierten Vokabularen (Bild ↔ Text)</h3><div>{''.join(card_html(c, esc) for c in sugg)}</div>
<details class="old"><summary>Zum Vergleich: bisherige Anzeige (VMZ-Vokabular)</summary>
<p>Ränge im VMZ-Vokabular: {old_ranks or '–'}</p><p>Passende VMZ-Begriffe: {old}</p></details>
</div></div></section>""")

    # ------------------------------------------------------------ evaluation and sources
    def pct(x, n):
        return f"{x / n:.0%}" if n else "–"

    names = {"VMZ": f"bisher: VMZ-Vokabular ({res['sizes']['VMZ']:,} Begriffe, übersetzt)",
             "AAT alle": f"AAT, alle Objektkonzepte ({res['sizes']['AAT alle']:,})",
             "AAT NMVW": f"AAT, vom NMVW-Thesaurus verwendet ({res['sizes']['AAT NMVW']:,})",
             "ethno": f"AAT (NMVW, AAT-Deutsch, GND) + NMVW ({res['sizes']['ethno']:,})",
             "de": f"AAT mit deutscher Bezeichnung (AAT-Deutsch, GND) ({res['sizes']['de']:,})"}
    ev = []
    for sname, label in (("VMZ", f"VMZ-Stichprobe «?»/Anführungszeichen, sicherer Typbegriff (n = {len(sets['VMZ'])})"),
                         ("MKB", f"MKB-Objekte mit sicherem Typbegriff (n = {len(sets['MKB'])})")):
        ev.append(f'<tr><th class="l" colspan="9">{esc(label)}</th></tr>')
        for m in ["VMZ", "AAT alle", "AAT NMVW", "ethno", "de"]:
            o = res[sname][m]
            n = o["n"]
            ev.append(f"<tr><td>{esc(names[m])}</td><td>{pct(o.get('mapped', 0), n)}</td>"
                      + "".join(f"<td>{pct(o.get(f'strict@{k}', 0), n)}</td>" for k in (1, 5, 8))
                      + "".join(f"<td>{pct(o.get(f'narrow@{k}', 0), n)}</td>" for k in (1, 5, 8))
                      + f"<td>{o['ranks'] or '–'}</td></tr>")
    ev_html = ('<table class="ev"><tr><th class="l">Vokabular (Begriffe)</th><th>Konzept des Namens vorhanden</th>'
               '<th>gleiches Konzept: Top 1</th><th>Top 5</th><th>Top 8</th><th>gleich oder enger: Top 1</th>'
               '<th>Top 5</th><th>Top 8</th><th>Median-Rang</th></tr>' + "".join(ev) + "</table>")
    S = v.sources
    n_aat = sum(1 for x in v.aat.values() if x["t"] == "Concept")
    n_de = sum(1 for x in v.aat.values() if x["t"] == "Concept" and x.get("de"))
    n_gnd_aat = sum(1 for x in v.aat.values() if x.get("gnd"))
    n_nmvw_aat = sum(1 for x in v.nmvw.values() if x["aat"])
    n_nmvw_en = sum(1 for x in v.nmvw.values() if x["en"])
    n_nmvw_only = sum(v.is_nmvw(c) for c in sug.cand)
    src_html = f"""<table class="ev"><tr><th class="l">Vokabular</th><th class="l">Zugang, Lizenz</th><th class="l">Sprachen, Umfang</th><th class="l">Rolle im Prototyp</th></tr>
<tr><td class="l"><a href="{S['aat']['url']}">Getty AAT</a></td><td class="l">SPARQL (vocab.getty.edu), {S['aat']['licence']}</td><td class="l">{n_aat:,} Objektkonzepte (Furnishings and Equipment, Visual and Verbal Communication, Object Genres, Components); englisch, deutsch (AAT-Deutsch) bei {n_de:,}, niederländisch</td><td class="l">Rückgrat: die englischen Bezeichnungen werden direkt mit dem Foto verglichen, ohne maschinelle Übersetzung</td></tr>
<tr><td class="l"><a href="{S['nmvw']['url']}">NMVW-Thesaurus</a></td><td class="l">Colonial Collections Hub: Download (TriG) und SPARQL, {S['nmvw']['licence']}</td><td class="l">{len(v.nmvw):,} Objektbegriffe («Objecttrefwoord»), niederländisch, englisch bei {n_nmvw_en:,}; {n_nmvw_aat:,} mit skos:exactMatch auf das AAT</td><td class="l">wählt die in einem ethnografischen Museum gebrauchten AAT-Konzepte aus; dazu {n_nmvw_only:,} eigene Begriffe ohne AAT-Entsprechung</td></tr>
<tr><td class="l"><a href="{S['gnd']['url']}">GND</a></td><td class="l">Gesamtabzug der DNB (lobid-gnd antwortete am 14.11.2026 nicht), {S['gnd']['licence']}; Paare AAT ↔ GND aus Wikidata (CC0)</td><td class="l">{len(v.gnd):,} Sachschlagwörter, deutsch; {n_gnd_aat:,} AAT-Konzepte über Wikidata verknüpft</td><td class="l">deutsche Bezeichnung und Normdaten-Link; findet die Begriffe des aktuellen Namens</td></tr>
<tr><td class="l"><a href="{S['trachsler']['url']}">Trachsler</a></td><td class="l">Export des VMS über KIM.ch, Browser xTree; <b>keine Lizenzangabe</b></td><td class="l">{len(v.tra):,} Klassen, deutsch, französisch, italienisch; Funktionsgruppen der Schweizer Kulturgeschichte</td><td class="l">Funktionsgruppe: Klassen, deren Titel den Begriff nennt; das Foto wählt unter ihnen. Nur Notation, Name und Link</td></tr>
<tr><td class="l"><a href="https://www.smb.museum/fileadmin/website/Museen_und_Sammlungen/Museum_Europaeischer_Kulturen/02_Sammeln_und_Forschen/MEK_Sammlungskonzept_EN.pdf">MEK-Sammlungskonzept</a></td><td class="l">PDF (Stand 2022)</td><td class="l">nennt 74 Sachgruppen nach Gebrauchskontext, veröffentlicht sie aber nicht</td><td class="l">nur Orientierung: ordnet nach Thema/Gebrauch (wie Trachsler), Material, «Kulturlandschaft» und Sammlung</td></tr></table>"""
    tra = {s: res[s]["trachsler"] for s in sets}
    tra_txt = ("Trachsler: Klassen, deren Titel den Begriff nennt; nennen ihn mehrere (8 Korbklassen), wählt das Foto. Ganz "
               "ohne Wortsuche, nur nach dem Foto, wäre eine solche Klasse bloss in " + ", ".join(
                   f"{pct(t.get('hit@5', 0), t.get('n', 0))} ({s}, n = {t.get('n', 0)})" for s, t in tra.items())
               + " der Fälle unter den ersten 5 – darum keine Trachsler-Vorschläge allein aus dem Bild.")
    hyp = res["hypotheses"][a.variant]
    page = f"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Prototyp kontrollierte Vokabulare</title>
<style>
{LIST_CSS}{VOCAB_CSS}{PROTO_CSS}</style></head><body>
<h1>Prototyp: Begriffe aus kontrollierten Vokabularen statt Ränge im VMZ-Vokabular</h1>
<div class="lead"><p>{len(rows)} Objekte (VMZ-Stichprobe und MKB). Statt der Ränge im VMZ-eigenen Vokabular zeigen die
beiden Abschnitte Begriffe aus externen kontrollierten Vokabularen, je mit Bezeichnung, Quelle und Link. Gleiche
Methode wie bisher: SigLIP 2 (so400m) vergleicht das Foto mit «a photo of a …, an ethnographic museum object», mit
Hubness-Korrektur. Kandidaten: {esc(names[a.variant])}.</p>
<p><small>Farbe bei den Begriffen im Namen: <span class="chip sup">unter den ersten 2 % ({sug.sup}) für das Foto</span>
<span class="chip pos">unter den ersten 10 % ({sug.possible})</span> (Rang im Tooltip). Mehrdeutige Wörter (Trommel:
Membranofon oder Säulentrommel): zuerst die deutschen Vorzugsbezeichnungen, Bedeutungen aus dem NMVW-Thesaurus und ganze Objekte vor
Teilen; unter den übrigen entscheidet das Foto. «Oberbegriff»: nur das Wortende hat ein Konzept (Holzmaske → Maske).
«Material»: Werkstoff im Namen (Ton, Stein), aus der Material-Facette des AAT. Bezeichnung deutsch aus AAT-Deutsch oder
der GND, sonst englisch («engl.»). Links: AAT → Getty, GND → DNB, NMVW → Wereldmuseum, Trachsler → xTree
(Klassenpfad im Tooltip).</small></p>
<h2>Evaluation: trifft ein Vorschlag das Konzept des aktuellen Namens?</h2>
<p><small>Sicherer Typbegriff = erster Begriff des Namens ohne «?» (Korb in «Korb (Worfel?)»). Sein Konzept: alle AAT- und
NMVW-Konzepte mit dieser deutschen Bezeichnung (AAT, GND) oder der englischen Übersetzung, sonst das Wortende. «Gleich» =
das Konzept ist unter den ersten k Vorschlägen; «gleich oder enger» zählt auch speziellere Konzepte (Schwinge für Korb).
Fehlt das Konzept im Vokabular, zählt das als kein Treffer.</small></p>
{ev_html}
<p><small>«?»-Hypothesen der VMZ-Stichprobe (n = {hyp.get('n', 0)}): Konzept vorhanden {pct(hyp.get('mapped', 0), hyp.get('n', 0))};
unter den ersten 2 % {pct(hyp.get('sup', 0), hyp.get('n', 0))}, unter den ersten 10 % {pct(hyp.get('pos', 0), hyp.get('n', 0))}
(bisher im VMZ-Vokabular: 31 % und 60 %). {esc(tra_txt)}</small></p>
<h2>Vokabulare</h2>{src_html}
</div>
{''.join(rows)}
<p><small>{esc(' · '.join(x['credit'] for x in S.values()))}. Fotos: © Völkerkundemuseum der Universität Zürich bzw.
Museum der Kulturen Basel. Prototyp, nicht veröffentlicht.</small></p>
</body></html>"""
    out.write_text(page, encoding="utf-8")
    print(f"wrote {out} ({len(rows)} objects, {out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
