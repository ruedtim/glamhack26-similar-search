"""Second list for the switch VMZ ↔ MKB: every object of the Museum der Kulturen Basel (MKB) with an image
(7,310 objects of the African collection, via PARC) as the starting point, with the visually most similar objects
in the OTHER collections – including the 1,019 VMZ objects of the GLAMhack sample – and terms from the VMZ
vocabulary.

Same method as suggest_vmz.py: SigLIP 2 (so400m) + DINOv2 × 0.25 (weighted rank fusion), hub filter, the
machine-translated VMZ vocabulary with hubness correction; every term of the current MKB name gets its rank
(top 2 % = supported, top 10 % = possible). The hub threshold scales with the number of query photos
(VMZ list: top 5 of ≥ 10 of 748 photos).

The page holds all objects as JSON and shows 50 at a time: search, filters and paging run in the browser, so the
page stays fast and also works opened from disk. Thumbnails are shared with the VMZ list (OUT/img/r_<id>.jpg).
Writes OUT/mkb.html next to the VMZ list OUT/index.html (suggest_vmz.py), which links to it.

Usage: GPU_SHARE=0.5 python suggest_mkb.py --data DATA_DIR --out docs/review --text-model siglip2_so400m
"""
import argparse
import html
import json
from collections import Counter
from pathlib import Path

import numpy as np

from evaluate import clean
from models import Embedder, load_embeddings
from suggest import clean_de
from suggest_vmz import (EN_TEMPLATE, LIST_CSS, POS_SHARE, SUP_SHARE, can_publish, fname, name_terms, switch_html,
                         thumb, translate, type_term, wrrf)

GERMAN = ("mrz", "md", "vmz")          # sources with German object names (grouped without the English head noun)
SOURCES = {"phil": "Mapping Philippine Material Culture", "mrz": "Museum Rietberg", "cma": "Cleveland Museum of Art",
           "si": "Smithsonian", "md": "museum-digital", "prm": "Pitt Rivers Museum", "vmz": "VMZ (GLAMhack-Stichprobe)",
           "uzh": "VMZ (via Mapping Philippine Material Culture)"}
RIGHTS = ("Fotos der MKB-Objekte: © Museum der Kulturen Basel, via PARC – Portal for African Research Collections "
          "(Universität Basel); die Veröffentlichung für dieses Projekt hat das MKB genehmigt. Fotos der VMZ-Objekte: "
          "© Völkerkundemuseum der Universität Zürich. Weitere Vergleichsbilder: Cleveland Museum of Art und "
          "Smithsonian (CC0), Museum Rietberg (CC BY-SA), via museum-digital: Staatliche Museen zu Berlin "
          "(CC BY-NC-SA) und Übersee-Museum Bremen (CC BY-SA), Mapping Philippine Material Culture (© die besitzenden "
          "Museen) – Miniaturen nur zum Vergleich, mit Link zur Quelle. Pitt Rivers Museum: nur Name und Link, die "
          "Bilder werden aus Rechtegründen nicht gezeigt.")
PAGE_CSS = """
.q{width:180px} #list{scroll-margin-top:64px} .c.vmz{border-color:var(--acc2);border-width:2px}
.pager{display:flex;gap:10px;align-items:center;justify-content:center;margin:18px 0;font-size:13px}
.pager button,.bar button{font:inherit;padding:6px 12px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg);cursor:pointer}
.pager button:disabled,.bar button:disabled{opacity:.4;cursor:default}
.bar select{max-width:190px} .pages{display:inline-flex;gap:6px;align-items:center;white-space:nowrap}
.legend{display:inline-block;width:12px;height:12px;border:2px solid var(--acc2);border-radius:3px;vertical-align:-2px}
@media (max-width:600px){.q{width:100%}}
"""
SCRIPT = r"""
const D = JSON.parse(document.getElementById('data').textContent);
const R = D.ref, O = D.obj, TR = D.tr, N = 50;
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const st = k => k <= D.sup ? 'sup' : k <= D.pos ? 'pos' : 'no';
const TXT = O.map(o => [o[0], o[1], o[2], o[3], ...o[9], ...o[10].map(x => x[0])].join(' ').toLowerCase());
const $ = id => document.getElementById(id);
const list = $('list'), q = $('q'), fl = $('flag'), ns = $('ns'), cnt = $('count'), pager = $('pager');
let F = [], page = 0;

function card(n) {
  const r = R[n[0]];
  const pic = r[4] ? `<img src="${r[4]}" alt="" loading="lazy">`
                   : '<div class="noimg">Bild nicht veröffentlicht – Link zur Quelle</div>';
  const out = r[5] ? '' : ' target="_blank" rel="noopener"';
  return `<a class="c${r[5] ? ' vmz' : ''}" href="${esc(r[3])}"${out}>${pic}<b>${esc(r[0])}</b>` +
         `<small>${esc(r[1])}${r[2] ? ' · ' + esc(r[2]) : ''}${n[1] ? ' · ' + (n[1] / 100).toFixed(2) : ''}</small></a>`;
}
function section(i) {
  const o = O[i];
  const names = o[8].map(([t, m, k]) =>
    `<span class="chip ${st(k)}" title="Rang im VMZ-Vokabular (${D.vocab} Begriffe)">${esc(t)}${m ? ' ' + m : ''}` +
    ` <i>#${k} · ${esc(TR[t] || '')}</i></span>`).join('') || '<small>–</small>';
  const terms = o[9].map(t => `<span class="chip">${esc(t)} <i>${esc(TR[t] || '')}</i></span>`).join('');
  const knn = o[10].map(([nm, k]) => `<span class="chip">${esc(nm)} <i>×${k}</i></span>`).join('');
  return `<section id="o-${o[12]}"><div class="row"><div class="q">` +
    `<a href="${esc(o[4])}" target="_blank" rel="noopener"><img src="${o[5]}" alt="" loading="lazy"></a>` +
    `<b class="name">${esc(o[1] || '–')}</b>${o[2] ? `<small>${esc(o[2])}</small>` : ''}` +
    `<small>Inv.-Nr. <b>${esc(o[0])}</b> · <a href="${esc(o[4])}" target="_blank" rel="noopener">PARC</a></small>` +
    `${o[3] ? `<small><span class="k">Kultur, Herkunft:</span> ${esc(o[3])}</small>` : ''}</div>` +
    `<div class="sug"><h3>Begriffe im aktuellen Namen – Rang im VMZ-Vokabular</h3><div>${names}</div>` +
    `<h3>Passende Begriffe aus dem VMZ-Vokabular (Bild ↔ Text)</h3><div>${terms}</div>` +
    `<h3>Namen der ähnlichsten Objekte (andere Sammlungen)</h3><div>${knn}</div>` +
    `<h3>Ähnlichste Objekte</h3><div class="grid">${o[11].map(card).join('')}</div></div></div></section>`;
}
function render() {
  const pages = Math.max(1, Math.ceil(F.length / N));
  page = Math.min(Math.max(page, 0), pages - 1);
  list.innerHTML = F.slice(page * N, page * N + N).map(section).join('') || '<p>Keine Objekte gefunden.</p>';
  cnt.textContent = `${F.length} von ${O.length} · Seite ${page + 1}/${pages}`;
  pager.innerHTML = `<button data-p="${page - 1}"${page ? '' : ' disabled'}>‹ zurück</button>` +
    `<span>Seite ${page + 1} von ${pages}</span>` +
    `<button data-p="${page + 1}"${page < pages - 1 ? '' : ' disabled'}>weiter ›</button>`;
  $('prev').disabled = !page; $('next').disabled = page >= pages - 1;
}
function apply() {
  const s = q.value.trim().toLowerCase(), f = fl.value, h = ns.value;
  F = [];
  for (let i = 0; i < O.length; i++) {
    if (s && !TXT[i].includes(s)) continue;
    if (f === 'vmz' ? !O[i][11].some(n => R[n[0]][5]) : f && O[i][6] !== f) continue;
    if (h && O[i][7] !== h) continue;
    F.push(i);
  }
  page = 0; render();
}
function go(p) { page = p; render(); list.scrollIntoView(); }
[q, fl, ns].forEach(el => el.addEventListener('input', apply));
pager.addEventListener('click', e => { const b = e.target.closest('button'); if (b && !b.disabled) go(+b.dataset.p); });
$('prev').addEventListener('click', () => go(page - 1));
$('next').addEventListener('click', () => go(page + 1));
apply();
const hash = decodeURIComponent(location.hash.slice(1));
const hit = O.findIndex(o => 'o-' + o[12] === hash);
if (hit >= 0) { page = Math.floor(F.indexOf(hit) / N); render(); $(hash).scrollIntoView(); }
"""


def candidates(Q, Rm, k=200, chunk=512):
    """Positions (in Rm) and similarities of the k most similar reference images per query, best first."""
    idx, sim = [], []
    for s in range(0, len(Q), chunk):
        S = Q[s:s + chunk] @ Rm.T
        part = np.argpartition(-S, k, axis=1)[:, :k]
        ps = np.take_along_axis(S, part, 1)
        order = np.argsort(-ps, axis=1)
        idx.append(np.take_along_axis(part, order, 1))
        sim.append(np.take_along_axis(ps, order, 1))
    return np.vstack(idx), np.vstack(sim)


def mean_sim(X, T, chunk=4096):
    """Mean similarity of each text (row of T) over all images X, in chunks."""
    return sum((X[s:s + chunk] @ T.T).sum(0) for s in range(0, len(X), chunk)) / len(X)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--k", type=int, default=8, help="neighbours shown per object")
    ap.add_argument("--min-count", type=int, default=3, help="min. frequency of a term in the VMZ catalogue")
    ap.add_argument("--text-model", default="siglip2_so400m")
    ap.add_argument("--dino-weight", type=float, default=0.25)
    ap.add_argument("--hub-share", type=float, default=10 / 748,
                    help="hide reference objects in the top 5 of at least this share of the MKB photos")
    ap.add_argument("--home", default="../index.html", help="link back to the overview page, relative to OUT")
    a = ap.parse_args()
    data, out = Path(a.data), Path(a.out)
    (out / "img").mkdir(parents=True, exist_ok=True)
    esc = html.escape

    recs = [json.loads(line) for line in open(data / "records.jsonl", encoding="utf-8")]
    md_cache = data / "md_detail_cache.json"                  # places / peoples of museum-digital objects
    if md_cache.exists():
        places = json.load(open(md_cache, encoding="utf-8"))
        for r in recs:
            if r["source"] == "md" and r["id"] in places and not r.get("culture"):
                r["culture"] = "; ".join(places[r["id"]][0] + places[r["id"]][1])
    src = np.array([r["source"] for r in recs])
    is_mkb = np.array([r["source"] == "mkb" or "Kulturen Basel" in (r.get("holder") or "") for r in recs])
    q_idx = np.where(src == "mkb")[0]
    ref = np.where(~is_mkb)[0]                 # all other collections, including the VMZ objects
    print(f"queries (MKB): {len(q_idx)}; reference: {len(ref)} {dict(Counter(src[ref]))}")
    E = {m: load_embeddings(data, m, recs) for m in [a.text_model, "dinov2"]}
    weights = [1.0 if m == a.text_model else a.dino_weight for m in E]

    # ------------------------------------------------------------ neighbours (exact duplicates ≥ 0.995 dropped)
    cand, sims = {}, {}
    for m in E:
        idx, sim = candidates(E[m][q_idx], E[m][ref])
        cand[m] = [[ref[o] for o, s in zip(io, si) if s < 0.995] for io, si in zip(idx, sim)]
        if m == a.text_model:
            sims = [{ref[o]: float(s) for o, s in zip(io, si)} for io, si in zip(idx, sim)]
    hub_max = max(10, round(a.hub_share * len(q_idx)))
    freq = Counter(j for qi in range(len(q_idx)) for j in wrrf([cand[m][qi][:60] for m in E], weights)[:5])
    hubs = {j for j, c in freq.items() if c >= hub_max}
    print(f"hidden hubs (top 5 of >= {hub_max} photos): {len(hubs)}: "
          + "; ".join(sorted({recs[j]['name'][:28] for j in hubs})[:10]))

    # ------------------------------------------------------------ terms: VMZ vocabulary, ranks of the name terms
    cat = [json.loads(line) for line in open(data / "vmz_catalog.jsonl", encoding="utf-8")]
    tcount = Counter(type_term(c["name"]) for c in cat)
    de_vocab = sorted(t for t, n in tcount.items() if n >= a.min_count and len(t) >= 3 and t[0].isupper())
    terms_q = [name_terms(recs[i]["name"]) for i in q_idx]
    hyp_vocab = sorted({t for ts in terms_q for t, _ in ts})
    tr = translate(de_vocab + hyp_vocab, data / "vmz_vocab_en.json")
    emb = Embedder(a.text_model)
    T_de = emb.texts([EN_TEMPLATE.format(tr[v]) for v in de_vocab])
    T_h = emb.texts([EN_TEMPLATE.format(tr[v]) for v in hyp_vocab])
    allimg = E[a.text_model][np.concatenate([ref, q_idx])]
    b_de, b_h = 0.5 * mean_sim(allimg, T_de), 0.5 * mean_sim(allimg, T_h)
    S_de = E[a.text_model][q_idx] @ T_de.T - b_de
    S_h = E[a.text_model][q_idx] @ T_h.T - b_h
    de_pos, h_pos = {t: k for k, t in enumerate(de_vocab)}, {t: k for k, t in enumerate(hyp_vocab)}
    sup, pos = round(SUP_SHARE * len(de_vocab)), round(POS_SHARE * len(de_vocab))
    status = lambda k: "sup" if k <= sup else "pos" if k <= pos else "no"   # noqa: E731

    # ------------------------------------------------------------ per object
    done = set(p.name for p in (out / "img").glob("*.jpg"))
    ref_ix, ref_rows = {}, []

    def ref_row(j):
        if j not in ref_ix:
            r = recs[j]
            url = f"index.html#o-{fname(r['inv'])}" if r["source"] == "vmz" else (r.get("url") or "")
            img = (thumb(data / r["img"], out / "img" / f"r_{fname(r['id'])}.jpg", 150, done)
                   if can_publish(r) and r.get("img") else "")
            ref_ix[j] = len(ref_rows)
            ref_rows.append([r["name"][:70], (r.get("holder") or "")[:45], (r.get("culture") or "")[:30], url, img,
                             int(r["source"] == "vmz")])
        return ref_ix[j]

    objs, used, stats = [], set(), Counter(type_ranks=[])
    for qi, i in enumerate(q_idx):
        r = recs[i]
        top = wrrf([[j for j in cand[m][qi] if j not in hubs][:60] for m in E], weights)[:a.k]
        groups, shown = Counter(), {}
        for j in top:
            nm = recs[j]["name"]
            key = (clean_de(nm).lower() if recs[j]["source"] in GERMAN else clean(nm)) or nm.lower()
            groups[key] += 1
            shown.setdefault(key, nm)
        s_de = S_de[qi]
        zs = [de_vocab[t] for t in np.argsort(-s_de)[:6]]
        chips = []
        for t, mark in terms_q[qi]:
            v = S_h[qi, h_pos[t]]
            chips.append([t, mark, 1 + int((s_de > v).sum()) - (1 if t in de_pos and s_de[de_pos[t]] > v else 0)])
        tt = type_term(r["name"])
        certain = bool(chips) and chips[0][0] == tt and not chips[0][1]
        nstate = status(chips[0][2]) if chips else "na"
        if certain:
            stats["type_n"] += 1
            stats["type_" + status(chips[0][2])] += 1
            stats["type_ranks"] += [chips[0][2]]
        stats["with_vmz"] += any(recs[j]["source"] == "vmz" for j in top)
        group = "?" if any(m == "?" for _, m, _ in chips) or "?" in r["name"] else \
            "Figur" if r["name"].strip().lower() == "figur" else ""
        title = (r.get("title") or "").strip()
        used.update(zs + [c[0] for c in chips])
        objs.append([r["inv"], r["name"], title if title.lower() != r["name"].strip().lower() else "",
                     (r.get("culture") or "")[:90], r.get("url") or "",
                     thumb(data / r["img"], out / "img" / f"r_{fname(r['id'])}.jpg", 150, done),
                     group, nstate, chips, zs, [[shown[k], c] for k, c in groups.most_common(5)],
                     [[ref_row(j), round(100 * sims[qi].get(j, 0))] for j in top], fname(r["id"])])

    # ------------------------------------------------------------ page
    n, tn = len(objs), max(1, stats["type_n"])
    n_vmz = int((src == "vmz").sum())
    refmix = ", ".join(f"{SOURCES.get(k, k)}: {v}" for k, v in Counter(src[ref]).most_common())
    payload = {"ref": ref_rows, "obj": objs, "tr": {t: tr.get(t, "") for t in sorted(used)},
               "sup": sup, "pos": pos, "vocab": len(de_vocab)}
    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    home = esc(a.home) if a.home else ""
    med = int(np.median(stats["type_ranks"])) if stats["type_ranks"] else "–"
    page = f"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>MKB-Objekte im Vergleich</title>
<style>
{LIST_CSS}{PAGE_CSS}</style></head><body>
{f'<nav class="top"><a href="{home}">← Zur Übersicht</a></nav>' if home else ''}
<h1>Alle MKB-Objekte im Vergleich mit anderen Sammlungen (PoC)</h1>
<div class="lead"><p>{n} Objekte des Museums der Kulturen Basel mit Foto (Afrika-Sammlung, via PARC – Portal for
African Research Collections, Universität Basel) als Ausgangspunkt: je die ähnlichsten Objekte in den anderen
Sammlungen – darunter die {n_vmz} VMZ-Objekte der GLAMhack-Stichprobe (<span class="legend"></span> grün umrandet,
Link zum Eintrag in der VMZ-Liste) – und passende Begriffe aus dem VMZ-Vokabular.
Vergleichsbestand: {len(ref)} Objekte ({refmix}). Bildähnlichkeit: SigLIP 2 + DINOv2 (gewichtete Rangfusion,
DINOv2 mit Gewicht {a.dino_weight}); Begriffe: SigLIP 2 Bild ↔ Text gegen {len(de_vocab)} Typbegriffe aus den
Objektnamen des VMZ-Katalogs, vorher maschinell ins Englische übersetzt (grau: die Übersetzung).</p>
<p><small>Rang = Platz des Begriffs unter allen {len(de_vocab)} VMZ-Begriffen für dieses Foto:
<span class="chip sup">≤ {sup}: vom Bild gestützt</span><span class="chip pos">≤ {pos}: möglich</span><span class="chip">&gt; {pos}: nicht gestützt</span>
Den Typbegriff des aktuellen MKB-Namens stützt das Foto bei {stats['type_sup'] / tn:.0%} der {stats['type_n']} Objekte
mit eindeutigem Namen, möglich bei {stats['type_pos'] / tn:.0%} (Median-Rang {med}). «Nicht gestützt» heisst nicht
«falsch»: Seltene Fachwörter und Begriffe, die das VMZ-Vokabular nicht kennt, landen oft dort.
Bei {stats['with_vmz']} Objekten ist unter den {a.k} ähnlichsten mindestens ein VMZ-Objekt (Filter «mit ähnlichem
VMZ-Objekt»). Zahl auf den Karten = Bildähnlichkeit (SigLIP 2, höher = ähnlicher). Ausgeblendet sind {len(hubs)}
Vergleichsobjekte, die bei {hub_max} oder mehr Fotos unter den Top 5 wären («Hubs»).
Vorschläge sind Hinweise – entscheiden muss die Fachperson. {RIGHTS}</small></p></div>
<div class="bar">{f'<a class="home" href="{home}" title="Zur Übersicht">← Übersicht</a>' if home else ''}{switch_html("mkb", n_vmz, n)}
<input id="q" type="search" placeholder="Suche: Inventarnummer, Name, Begriff, Kultur …" aria-label="Suche">
<select id="flag" aria-label="Gruppe"><option value="">alle Objekte</option><option value="?">nur «?» im Namen</option><option value="Figur">nur «Figur»</option><option value="vmz">mit ähnlichem VMZ-Objekt</option></select>
<select id="ns" aria-label="Name"><option value="">alle Namen</option><option value="sup">Name vom Foto gestützt</option><option value="pos">Name möglich</option><option value="no">Name nicht gestützt</option></select>
<span class="pages"><button id="prev" title="vorherige Seite">‹</button><small id="count"></small><button id="next" title="nächste Seite">›</button></span></div>
<div id="list"></div>
<nav class="pager" id="pager"></nav>
<script id="data" type="application/json">{data_json}</script>
<script>{SCRIPT}</script></body></html>"""
    (out / "mkb.html").write_text(page, encoding="utf-8")
    print(f"wrote {out / 'mkb.html'} ({len(page.encode()) / 1e6:.1f} MB, {n} objects, {len(ref_rows)} neighbours; "
          f"type term supported {stats['type_sup'] / tn:.0%}, possible {stats['type_pos'] / tn:.0%}, median rank {med}; "
          f"{stats['with_vmz']} with a VMZ neighbour)")


if __name__ == "__main__":
    main()
