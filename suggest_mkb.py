"""Second list for the switch VMZ ↔ MKB: every object of the Museum der Kulturen Basel (MKB) with an image
(7,310 objects of the African collection, via PARC) as the starting point, with the visually most similar objects
in the OTHER collections – including the 1,019 VMZ objects of the GLAMhack sample – and concepts from external
controlled vocabularies (Getty AAT, GND, NMVW thesaurus, Trachsler; vocab_external.py).

Same method as suggest_vmz.py: SigLIP 2 (so400m) + DINOv2 × 0.25 (weighted rank fusion), hub filter; the concepts
are ranked against the photo with hubness correction (vocab_external.Suggester), every term of the current MKB name
gets its concept and the photo's support (top 2 % = supported, top 10 % = possible). The hub threshold scales with
the number of query photos (VMZ list: top 5 of ≥ 10 of 748 photos).

The page holds all objects as JSON and shows 50 at a time: search, filters and paging run in the browser, so the
page stays fast and also works opened from disk. Thumbnails are shared with the VMZ list (OUT/img/r_<id>.jpg).
Writes OUT/mkb.html next to the VMZ list OUT/index.html (suggest_vmz.py), which links to it.

Usage: GPU_SHARE=0.5 python suggest_mkb.py --data DATA_DIR --out docs/review --text-model siglip2_so400m
       (--vocab DATA_DIR/vocab: vocab_external.py --out DATA_DIR/vocab first)
"""
import argparse
import html
import json
from collections import Counter
from pathlib import Path

import numpy as np

from evaluate import clean
from feedback import FEEDBACK_CSS, FORM, TIP, feedback_html
from models import load_embeddings
from suggest import clean_de
from suggest_vmz import LIST_CSS, can_publish, fname, name_terms, switch_html, thumb, translate, type_term, wrrf
from vocab_external import VOCAB_CREDIT, VOCAB_CSS, Suggester, TextCache, Vocab

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
.q{width:180px} #list{scroll-margin-top:64px}
.pager{display:flex;gap:10px;align-items:center;justify-content:center;margin:18px 0;font-size:13px}
.pager button,.bar button{font:inherit;padding:6px 12px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg);cursor:pointer}
.pager button:disabled,.bar button:disabled{opacity:.4;cursor:default}
.bar select{max-width:170px} .pages{display:inline-flex;gap:6px;align-items:center;white-space:nowrap}
@media (max-width:600px){.q{width:100%}}
"""
SCRIPT = r"""
const D = JSON.parse(document.getElementById('data').textContent);
const R = D.ref, O = D.obj, C = D.C, T = D.T, N = 50;
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const lab = c => [c.d || '', c.e || ''].join(' ');
const TXT = O.map(o => [o[0], o[1], o[2], o[3], ...o[8].map(x => x.t + (x.c !== undefined ? ' ' + lab(C[x.c]) : '')),
                        ...o[9].map(c => lab(C[c])), ...o[10].map(x => x[0])].join(' ').toLowerCase());
// controlled vocabularies (vocab_external.py): links and chips, as card_html / name_term_html in Python
const LINK = {aat: id => `https://vocab.getty.edu/page/aat/${id}`, gnd: id => `https://d-nb.info/gnd/${id}`,
  nmvw: id => `https://hdl.handle.net/20.500.11840/${id}`,
  tra: id => `https://xtree-public.digicult-verbund.de/vocnet/?uriVocItem=http://digicult.vocnet.org/trachsler/&startNode=${id}&lang=de&d=n`};
const A = (url, text, title) => `<a href="${esc(url)}" target="_blank" rel="noopener" title="${esc(title)}">${esc(text)}</a>`;
function links(c) {
  const l = [];
  if (c.a) l.push(A(LINK.aat(c.a), 'AAT', `Getty AAT ${c.a}: ${c.e}` + (c.u ? ` (unter: ${c.u})` : '')));
  if (c.g) l.push(A(LINK.gnd(c.g[0]), 'GND', `GND ${c.g[0]}: ${c.g[1]}`));
  if (c.n) l.push(A(LINK.nmvw(c.n[0]), 'NMVW', `NMVW-Thesaurus: ${c.n[1]}` + (!c.a && c.u ? ` (ohne AAT-Entsprechung, breiter: ${c.u})` : '')));
  if (c.t !== undefined) { const t = T[c.t]; l.push(A(LINK.tra(t[0]), `Trachsler ${t[1]}`, t[2])); }
  return l.join(' · ');
}
function vchip(c, cls = '', pre = '', note = '', title = '') {
  if (!c.d) note = '<span class="tag" title="keine deutsche Bezeichnung in AAT-Deutsch oder der GND">engl.</span>' + note;
  const l = links(c);
  return `<span class="chip vc ${cls}"${title ? ` title="${esc(title)}"` : ''}>${pre}<span class="lab">${esc(c.d || c.e)}</span>` +
         `${note}${l ? `<span class="src">${l}</span>` : ''}</span>`;
}
function nchip(x) {
  const pre = `<span class="arr">${esc(x.t)}${x.m ? ' ' + x.m : ''} →</span> `;
  if (x.mat) return `<span class="chip vc">${pre}<span class="tag">Material</span> <span class="lab">${esc(x.mat[1])}</span>` +
    `<span class="src">${A(LINK.aat(x.mat[0]), 'AAT', `Getty AAT ${x.mat[0]}: ${x.mat[2]}`)}</span></span>`;
  if (x.c !== undefined) return vchip(C[x.c], x.s === 'sup' || x.s === 'pos' ? x.s : '', pre,
    x.r === 'head' ? '<span class="tag" title="nur das Wortende hat ein Konzept">Oberbegriff</span>' : '',
    `Rang ${x.k} von ${D.vocab} Konzepten für dieses Foto`);
  const l = links({g: x.g, t: x.x});
  return `<span class="chip vc">${pre}<span class="tag">kein Konzept gefunden</span>${l ? `<span class="src">${l}</span>` : ''}</span>`;
}
const $ = id => document.getElementById(id);
const list = $('list'), q = $('q'), fl = $('flag'), ns = $('ns'), cnt = $('count'), pager = $('pager');
let F = [], page = 0;

function card(n) {
  const r = R[n[0]];
  const pic = r[4] ? `<img src="${r[4]}" alt="" loading="lazy">`
                   : '<div class="noimg">Bild nicht veröffentlicht – Link zur Quelle</div>';
  const out = r[5] ? '' : ' target="_blank" rel="noopener"';
  return `<a class="c" href="${esc(r[3])}"${out}>${pic}<b>${esc(r[0])}</b>` +
         `<small>${esc(r[1])}${r[2] ? ' · ' + esc(r[2]) : ''}${n[1] ? ' · ' + (n[1] / 100).toFixed(2) : ''}</small></a>`;
}
function section(i) {
  const o = O[i];
  const names = o[8].map(nchip).join('') || '<small>–</small>';
  const terms = o[9].map(c => vchip(C[c])).join('');
  const knn = o[10].map(([nm, k]) => `<span class="chip">${esc(nm)} <i>×${k}</i></span>`).join('');
  return `<section id="o-${o[12]}"><div class="row"><div class="q">` +
    `<a href="${esc(o[4])}" target="_blank" rel="noopener"><img src="${o[5]}" alt="" loading="lazy"></a>` +
    `<b class="name">${esc(o[1] || '–')}</b>${o[2] ? `<small>${esc(o[2])}</small>` : ''}` +
    `<small>Inv.-Nr. <b>${esc(o[0])}</b> · <a href="${esc(o[4])}" target="_blank" rel="noopener">PARC</a></small>` +
    `<small><a class="ppfb-link" href="${esc(FB)}" data-ppfb="${esc(JSON.stringify({inv: o[0], title: o[1] || ''}))}"` +
    ` target="_blank" rel="noopener" title="${esc(TIP)}">Rückmeldung zu diesem Objekt</a></small>` +
    `${o[3] ? `<small><span class="k">Kultur, Herkunft:</span> ${esc(o[3])}</small>` : ''}</div>` +
    `<div class="sug"><h3>Begriffe im aktuellen Namen – in kontrollierten Vokabularen</h3><div>${names}</div>` +
    `<h3>Vorschläge aus kontrollierten Vokabularen (Bild ↔ Text)</h3><div>${terms}</div>` +
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--k", type=int, default=8, help="neighbours shown per object")
    ap.add_argument("--vocab", help="folder of vocab_external.py (vocab_external.json, text embedding cache; "
                                    "default DATA_DIR/vocab)")
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

    # ------------------------------------------------------------ terms: external controlled vocabularies
    terms_q = [name_terms(recs[i]["name"]) for i in q_idx]
    hyp_vocab = sorted({t for ts in terms_q for t, _ in ts})
    tr = translate(hyp_vocab, data / "vmz_vocab_en.json")       # one route from a German name term to the AAT
    allimg = E[a.text_model][np.concatenate([ref, q_idx])]
    vdir = Path(a.vocab) if a.vocab else data / "vocab"
    voc = Vocab(vdir / "vocab_external.json")
    sug = Suggester(voc, TextCache(a.text_model, vdir), allimg, tr, vdir)
    cards, card_ix, tra_rows, tra_ix = [], {}, [], {}

    def tra_ref(t):
        if t[0] not in tra_ix:
            tra_ix[t[0]] = len(tra_rows)
            tra_rows.append(t)
        return tra_ix[t[0]]

    def card_ref(c):
        """Index of a concept in the page's table (short keys: d = German, e = English label, a = AAT id, g = GND,
        n = NMVW [id, label], t = Trachsler class (index into its own table), u = broader concepts)."""
        row = {"d": c["de"], "e": c["en"], "a": c["aat"], "g": c["gnd"], "n": c["nmvw"],
               "t": tra_ref(c["tra"]) if c["tra"] else None, "u": c["up"]}
        row = {k: v for k, v in row.items() if v is not None and v != ""}
        key = json.dumps(row, ensure_ascii=False, sort_keys=True)
        if key not in card_ix:
            card_ix[key] = len(cards)
            cards.append(row)
        return card_ix[key]

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

    objs, stats = [], Counter(type_ranks=[])
    for qi, i in enumerate(q_idx):
        r = recs[i]
        top = wrrf([[j for j in cand[m][qi] if j not in hubs][:60] for m in E], weights)[:a.k]
        groups, shown = Counter(), {}
        for j in top:
            nm = recs[j]["name"]
            key = (clean_de(nm).lower() if recs[j]["source"] in GERMAN else clean(nm)) or nm.lower()
            groups[key] += 1
            shown.setdefault(key, nm)
        sugg, named = sug.analyse(E[a.text_model][i], terms_q[qi], k=6)
        names = []
        for x in named:                      # t, m: term and mark; c: concept, s/k/r: status, rank, route;
            y = {"t": x["term"], "m": x["mark"]}                    # mat: material; g, x: GND / Trachsler without concept
            if x["card"]:
                y.update(c=card_ref(x["card"]), s=x["status"], k=x["rank"], r=x["route"])
            elif x["material"]:
                y["mat"] = x["material"]
            else:
                y.update(g=x["gnd"], x=tra_ref(x["tra"]) if x["tra"] else None)
            names.append({k: v for k, v in y.items() if v is not None and v != ""})
        tt = type_term(r["name"])
        certain = bool(named) and named[0]["term"] == tt and not named[0]["mark"]
        nstate = named[0]["status"] if named else "na"
        if certain:                          # is the concept of the certain type term among the 6 suggestions?
            stats["type_n"] += 1
            ids = voc.match_de(tt, tr.get(tt))[0]
            stats["type_same"] += any(x["key"] in ids for x in sugg)
            stats["type_hit"] += any(voc.is_within(x["key"], t) for x in sugg for t in ids)
            if named[0]["rank"]:
                stats["type_mapped"] += 1
                stats["type_" + named[0]["status"]] += 1
                stats["type_ranks"] += [named[0]["rank"]]
        stats["with_vmz"] += any(recs[j]["source"] == "vmz" for j in top)
        group = "?" if any(x["mark"] == "?" for x in named) or "?" in r["name"] else \
            "Figur" if r["name"].strip().lower() == "figur" else ""
        title = (r.get("title") or "").strip()
        objs.append([r["inv"], r["name"], title if title.lower() != r["name"].strip().lower() else "",
                     (r.get("culture") or "")[:90], r.get("url") or "",
                     thumb(data / r["img"], out / "img" / f"r_{fname(r['id'])}.jpg", 150, done),
                     group, nstate, names, [card_ref(x) for x in sugg], [[shown[k], c] for k, c in groups.most_common(5)],
                     [[ref_row(j), round(100 * sims[qi].get(j, 0))] for j in top], fname(r["id"])])

    # ------------------------------------------------------------ page
    n, tn = len(objs), max(1, stats["type_n"])
    n_vmz = int((src == "vmz").sum())
    refmix = ", ".join(f"{SOURCES.get(k, k)}: {v}" for k, v in Counter(src[ref]).most_common())
    payload = {"ref": ref_rows, "obj": objs, "C": cards, "T": tra_rows, "vocab": sug.n}
    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    home = esc(a.home) if a.home else ""
    med = int(np.median(stats["type_ranks"])) if stats["type_ranks"] else "–"
    page = f"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>MKB-Objekte im Vergleich</title>
<style>
{LIST_CSS}{PAGE_CSS}{VOCAB_CSS}{FEEDBACK_CSS}</style></head><body>
{feedback_html("../")}
{f'<nav class="top"><a href="{home}">← Zur Übersicht</a></nav>' if home else ''}
<h1>Alle MKB-Objekte im Vergleich mit anderen Sammlungen (PoC)</h1>
<div class="lead"><p>{n} Objekte des Museums der Kulturen Basel mit Foto (Afrika-Sammlung, via PARC – Portal for
African Research Collections, Universität Basel) als Ausgangspunkt: je die ähnlichsten Objekte in den anderen
Sammlungen – darunter die {n_vmz} VMZ-Objekte der GLAMhack-Stichprobe (mit Link zum Eintrag
in der VMZ-Liste) – und Begriffe aus kontrollierten Vokabularen.
Vergleichsbestand: {len(ref)} Objekte ({refmix}). Bildähnlichkeit: SigLIP 2 + DINOv2 (gewichtete Rangfusion,
DINOv2 mit Gewicht {a.dino_weight}). Begriffe aus kontrollierten Vokabularen: Getty AAT (mit AAT-Deutsch), GND,
Thesaurus des NMVW (heute Wereldmuseum) und Trachsler; SigLIP 2 vergleicht das Foto mit den englischen Bezeichnungen
von {sug.n} Konzepten, angezeigt wird die deutsche Bezeichnung (AAT-Deutsch oder GND), sonst die englische («engl.»),
mit Links zu den Normdaten.</p>
<p><small>Farbe bei den Begriffen im Namen: <span class="chip sup">unter den ersten 2 % ({sug.sup}) für das Foto: vom Bild gestützt</span><span class="chip pos">unter den ersten 10 % ({sug.possible}): möglich</span><span class="chip">sonst nicht gestützt</span>
(Rang im Tooltip). Mehrdeutige Wörter: zuerst die Vorzugsbezeichnungen von AAT-Deutsch, Bedeutungen aus dem
NMVW-Thesaurus und ganze Objekte vor Teilen; unter den übrigen wählt das Foto. «Oberbegriff»: nur das Wortende hat ein
Konzept; «Material»: Werkstoff im Namen. Von den {stats['type_n']} Objekten mit eindeutigem Namen hat der Typbegriff bei
{stats['type_mapped'] / tn:.0%} ein Konzept; unter den 6 Vorschlägen ist das gleiche bei {stats['type_same'] / tn:.0%}, das
gleiche oder ein engeres bei {stats['type_hit'] / tn:.0%}; das Foto stützt es bei {stats['type_sup'] / tn:.0%}, möglich bei
{stats['type_pos'] / tn:.0%} (Median-Rang {med} von {sug.n}). «Nicht gestützt» heisst nicht «falsch».
Bei {stats['with_vmz']} Objekten ist unter den {a.k} ähnlichsten mindestens ein VMZ-Objekt (Filter «mit ähnlichem
VMZ-Objekt»). Zahl auf den Karten = Bildähnlichkeit (SigLIP 2, höher = ähnlicher). Ausgeblendet sind {len(hubs)}
Vergleichsobjekte, die bei {hub_max} oder mehr Fotos unter den Top 5 wären («Hubs»).
Vorschläge sind Hinweise – entscheiden muss die Fachperson. {RIGHTS} {VOCAB_CREDIT}</small></p></div>
<div class="bar">{f'<a class="home" href="{home}" title="Zur Übersicht">← Übersicht</a>' if home else ''}{switch_html("mkb", n_vmz, n)}
<input id="q" type="search" placeholder="Suche: Inventarnummer, Name, Begriff, Kultur …" aria-label="Suche">
<select id="flag" aria-label="Gruppe"><option value="">alle Objekte</option><option value="?">nur «?» im Namen</option><option value="Figur">nur «Figur»</option><option value="vmz">mit ähnlichem VMZ-Objekt</option></select>
<select id="ns" aria-label="Name"><option value="">alle Namen</option><option value="sup">Name vom Foto gestützt</option><option value="pos">Name möglich</option><option value="no">Name nicht gestützt</option></select>
<span class="pages"><button id="prev" title="vorherige Seite">‹</button><small id="count"></small><button id="next" title="nächste Seite">›</button></span></div>
<div id="list"></div>
<nav class="pager" id="pager"></nav>
<script id="data" type="application/json">{data_json}</script>
<script>const FB = {json.dumps(FORM)}, TIP = {json.dumps(TIP, ensure_ascii=False)};{SCRIPT}</script></body></html>"""
    (out / "mkb.html").write_text(page, encoding="utf-8")
    print(f"wrote {out / 'mkb.html'} ({len(page.encode()) / 1e6:.1f} MB, {n} objects, {len(ref_rows)} neighbours; "
          f"type term: concept {stats['type_mapped'] / tn:.0%}, among the 6 suggestions same {stats['type_same'] / tn:.0%}, "
          f"same or narrower {stats['type_hit'] / tn:.0%}; supported {stats['type_sup'] / tn:.0%}, "
          f"possible {stats['type_pos'] / tn:.0%}, median rank {med} of {sug.n}; "
          f"{stats['with_vmz']} with a VMZ neighbour)")


if __name__ == "__main__":
    main()
