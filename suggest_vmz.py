"""Name suggestions for the GLAMhack sample of the Völkerkundemuseum UZH (VMZ): objects whose names
contain «?» or quotation marks, and objects named only «Figur» (imported with ingest_vmz.py).

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
Without --public the page is internal (accession register, collector, provenance; do not publish).
--public writes the published variant (docs/review), with a link back to the overview page (--home).

Usage: GPU_SHARE=0.5 python suggest_vmz.py --data DATA_DIR --out vmz_review --home ""          # internal
       GPU_SHARE=0.5 python suggest_vmz.py --data DATA_DIR --public --out docs/review --text-model siglip2_so400m
"""
import argparse
import html
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import openpyxl
from PIL import Image

from evaluate import clean
from models import Embedder, load_embeddings
from geo import Geo, proximity
from suggest import clean_de, rrf

QUOTES = "\"„“”«»‚‘’`´"
SEP = r"[();:,/\[\]]| oder | mit | für | aus | von | und | - "
EN_TEMPLATE = "a photo of a {}, an ethnographic museum object"
SUP_SHARE, POS_SHARE = 0.02, 0.10     # rank thresholds: top 2 % = supported, top 10 % = possible
RIGHTS_PUBLIC = ("Fotos der VMZ-Objekte: © Völkerkundemuseum der Universität Zürich. Vergleichsbilder: Cleveland "
                 "Museum of Art und Smithsonian (CC0), Museum Rietberg (CC BY-SA), via museum-digital: "
                 "Ethnologisches Museum, Staatliche Museen zu Berlin (CC BY-NC-SA) und Übersee-Museum Bremen "
                 "(CC BY-SA), Mapping Philippine Material Culture (© die besitzenden Museen) – Miniaturen nur zum "
                 "Vergleich, mit Link zur Quelle. Museum der Kulturen Basel (auch via PARC, Universität Basel): "
                 "Bilder mit Einverständnis des MKB, Quellennachweis «Museum der Kulturen Basel». Pitt Rivers "
                 "Museum: nur Name und Link, die Bilder werden aus Rechtegründen nicht gezeigt. "
                 "Texttreffer: Museum der Kulturen Basel, Sammlung Europa (data.bs.ch, CC BY 4.0).")
CATALOG_PUBLIC = ("Katalogdaten ohne Sammler, Herkunft, Eingangsbuch und interne Notizen; Beschreibungen nur für "
                  "Erwerbungen vor 1980 und ohne Sätze zu Personen, Erwerb oder Wert.")
MT_MODEL = "Helsinki-NLP/opus-mt-de-en"
MT_FRAME = "Ethnografische Sammlung: Maske, Trommel, {}"   # context makes single-word MT much better


def fname(s):
    """ASCII-only file name / HTML id part (inventory number, record id): the offline ZIP has to unpack on
    Windows too, which does not always decode non-ASCII names in ZIPs. Same as make_overview.fname."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^\w.-]+", "_", s, flags=re.ASCII)


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


PUBLIC_FIELDS = [("native", "Einheimischer Name"), ("use", "Gebrauch"), ("material", "Material"),
                 ("descr", "Beschreibung"), ("maker", "Hersteller"), ("ethnie", "Ethnie"),
                 ("culture_note", "Unschärfevermerk Kultur"), ("religion", "Religion"), ("language", "Sprache"),
                 ("continent", "Kontinent"), ("world_region", "Weltregion"), ("geo_region", "Region"),
                 ("place", "Ort"), ("country", "Land"), ("dims", "Masse (Katalog)"), ("orig_nr", "Original-Nr."),
                 ("units", "Objekteinheit"), ("acq_type", "Erwerbsart"), ("acq_date", "Erwerbsdatum"),
                 ("exhibitions", "Ausstellungen"), ("literature", "Literatur"), ("documentation", "Dokumentation")]
INTERNAL_FIELDS = [("entry_book", "Eingangsbuch"), ("provenance", "Herkunft"), ("collector", "Sammler"),
                   ("control", "Kontrollhilfe")]
# sentences of the description that are about persons, acquisition, collections or value -> not public
REDACT = re.compile(r"CHF|SFr|Franken|\bFr\.\s*\d|\bWert\b|\bHerrn?\b|\bFrau\b|\bDr\.|\bProf\.|katalogisiert|"
                    r"\bBrief|gesammelt|erworben|geschenkt|Geschenk|Schenkung|vermacht|Nachlass|Sammler|Sammlung|"
                    r"gekauft|\bKauf|verkauft|Händler|\b(19[89]\d|20\d\d)\b", re.I)   # years >= 1980: recent notes


def sing(w):
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("es") and w[:-2].endswith(("sh", "ch", "x", "ss")):
        return w[:-2]
    if w.endswith("s") and not w.endswith(("ss", "us")) and len(w) > 3:
        return w[:-1]
    return w


def matches(term, en, names):
    """Does one of the neighbour names contain the German term or the head noun of its translation?"""
    head = sing((re.findall(r"[a-z]+", (en or "").lower()) or [""])[-1])
    for nm in names:
        low = nm.lower()
        if len(term) >= 4 and term.lower() in low:
            return True
        if head and len(head) >= 3 and head in {sing(w) for w in re.findall(r"[a-zà-ÿ]+", low)}:
            return True
    return False


NO_PUBLIC_IMAGES = re.compile(r"Pitt Rivers")       # PRM: online publication needs a PRM licence
PUBLIC_OK = re.compile(r"Kulturen Basel")             # MKB: publication approved by the MKB (13.11.2026)


def can_publish(r):
    """May the image of this reference object be shown on the public pages?"""
    holder = r.get("holder") or ""
    if PUBLIC_OK.search(holder):
        return True
    return r.get("publish_image", True) is not False and not NO_PUBLIC_IMAGES.search(holder)


def wrrf(rank_lists, weights, k=60):
    """Weighted reciprocal rank fusion."""
    score = defaultdict(float)
    for ranks, w in zip(rank_lists, weights):
        for r, j in enumerate(ranks):
            score[j] += w / (k + r + 1)
    return sorted(score, key=lambda j: -score[j])


class MkbText:
    """Text layer: the same designation in the MKB «Sammlung Europa» (data.bs.ch, CC BY 4.0, no images).
    Only short name, title, origin and inventory number are used (no supplier names)."""

    def __init__(self, path, max_hits=40):
        self.recs = json.load(open(path, encoding="utf-8"))
        self.max_hits = max_hits
        index = defaultdict(set)
        for k, r in enumerate(self.recs):
            for w in re.findall(r"[\wÀ-ÿ-]+", f"{r.get('kurzbezeichnung') or ''} {r.get('titel') or ''}".lower()):
                if len(w) >= 3:
                    index[w].add(k)
        self.index = index
        self.cache = {}

    def hits(self, term):
        t = term.lower()
        if t not in self.cache:
            ids = set()
            for w, ks in self.index.items():
                if t in w:
                    ids |= ks
            self.cache[t] = ids
        return self.cache[t]

    def matches(self, terms, n=4):
        """Records whose short name/title contain one of the terms; only specific terms (<= max_hits)."""
        out, seen = [], set()
        scored = sorted(((len(self.hits(t)), t) for t in terms if len(t) >= 4), key=lambda x: x[0])
        for cnt, t in scored:
            if not 0 < cnt <= self.max_hits:
                continue
            for k in sorted(self.hits(t)):
                if k not in seen and len(out) < n:
                    seen.add(k)
                    r = self.recs[k]
                    out.append({"term": t, "count": cnt, "inv": r.get("inventarnummer") or "",
                                "type": r.get("kurzbezeichnung") or "", "title": r.get("titel") or "",
                                "origin": ", ".join(r.get("herkunft") or [])})
        return out


def catalog_fields(c, public):
    """Catalogue fields to show as (label, value). Public: without collector, provenance, accession register and
    internal notes; the description only for acquisitions before 1980 and without sentences about persons,
    acquisition, collections or value (marked «[gekürzt]»)."""
    dims = "; ".join(f"{lab} {c[k]}" for k, lab in (("h", "H"), ("w", "B"), ("l", "L"), ("d", "T"), ("diam", "Ø"))
                     if c.get(k))
    if c.get("weight_g"):
        dims += ("; " if dims else "") + f"{c['weight_g']} g"
    if c.get("size_note"):
        dims += (" – " if dims else "") + c["size_note"]
    vals = dict(c, dims=dims)
    if public:
        m = re.search(r"1[89]\d\d|20\d\d", c.get("acq_date") or "")
        year = int(m.group()) if m else None
        sents = [x for x in re.split(r"(?<=[.!?])\s+|\n+", c.get("descr") or "") if x.strip()]
        keep = [x for x in sents if not REDACT.search(x)]
        vals["descr"] = "" if not year or year >= 1980 or not keep else \
            " ".join(keep) + (" [gekürzt]" if len(keep) < len(sents) else "")
    return [(k, lab, vals[k]) for k, lab in PUBLIC_FIELDS + ([] if public else INTERNAL_FIELDS) if vals.get(k)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--k", type=int, default=12)
    ap.add_argument("--min-count", type=int, default=3, help="min. frequency of a term in the VMZ catalogue")
    ap.add_argument("--records", help="records file (default DATA_DIR/records.jsonl); an older, shorter "
                                      "records file uses the first rows of the embeddings")
    ap.add_argument("--text-model", default="siglip2", help="SigLIP 2 variant for neighbours and terms "
                                                             "(siglip2 = base, siglip2_so400m = large)")
    ap.add_argument("--dino-weight", type=float, default=0.25,
                    help="weight of DINOv2 in the rank fusion (SigLIP 2 = 1); 0.25 was best for naming, 1.0 clearly worse")
    ap.add_argument("--hub-max", type=int, default=10,
                    help="hide reference objects that are among the top 5 of at least this many VMZ photos")
    ap.add_argument("--public", action="store_true",
                    help="published variant: no accession register, collector, provenance; filtered descriptions")
    ap.add_argument("--home", default="../index.html",
                    help="link back to the overview page, relative to OUT ('' = no link)")
    a = ap.parse_args()
    data, out = Path(a.data), Path(a.out)
    (out / "img").mkdir(parents=True, exist_ok=True)

    recs = [json.loads(l) for l in open(a.records or data / "records.jsonl", encoding="utf-8")]
    md_cache = data / "md_detail_cache.json"                  # places / peoples of museum-digital objects
    if md_cache.exists():
        places = json.load(open(md_cache, encoding="utf-8"))
        for r in recs:
            if r["source"] == "md" and r["id"] in places and not r.get("culture"):
                r["culture"] = "; ".join(places[r["id"]][0] + places[r["id"]][1])
    E = {m: load_embeddings(data, m, recs) for m in [a.text_model, "dinov2"]}
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
    emb = Embedder(a.text_model)
    T_de = emb.texts([EN_TEMPLATE.format(tr[v]) for v in de_vocab])
    T_en = emb.texts([EN_TEMPLATE.format(v) for v in en_vocab])
    T_h = emb.texts([EN_TEMPLATE.format(tr[v]) for v in hyp_vocab])
    sup, pos = round(SUP_SHARE * len(de_vocab)), round(POS_SHARE * len(de_vocab))
    print(f"vocabularies: VMZ-DE {len(de_vocab)} terms (>= {a.min_count} objects), EN {len(en_vocab)}, "
          f"terms in current names {len(hyp_vocab)}")
    # hubness correction: subtract half of each term's mean similarity over all images (reference + VMZ);
    # 0.5 was the better compromise between specific and generic terms in the VMZ test
    allimg = E[a.text_model][np.concatenate([ref, q_idx])]
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
    fig_terms, fig_en, fig_nb = Counter(), Counter(), Counter()     # summary for the objects named only «Figur»
    top1_sims = []
    # neighbour candidates per photo and model (exact duplicates dropped)
    cand = {}
    for i in q_idx:
        cand[i] = {}
        for m in E:
            s = E[m][ref] @ E[m][i]
            order = [o for o in np.argsort(-s)[:200] if s[o] < 0.995]
            cand[i][m] = ([ref[o] for o in order], {ref[o]: float(s[o]) for o in order})
    mkb = MkbText(data / "mkb_europa.json") if (data / "mkb_europa.json").exists() else None
    # geographic layer: country / world region / continent from the catalogue and the reference metadata
    g = Geo(data / "vmz_catalog.jsonl")
    ref_geo = {j: g.ref(recs[j]) for j in ref}
    # hubs: reference objects that land in the top 5 of very many VMZ photos (e.g. small glass fragments
    # of the Freer Gallery) carry no information about a single object -> hidden
    weights = [1.0 if m == a.text_model else a.dino_weight for m in E]
    # measured on the mixed «?»/quotes sample only: in the «Figur» group, figure-type neighbours are expected
    hub_q = [i for i in q_idx if recs[i].get("flag") != "Figur"]
    freq = Counter(j for i in hub_q for j in wrrf([cand[i][m][0][:60] for m in E], weights)[:5])
    hubs = {j for j, c in freq.items() if c >= a.hub_max}
    stats["hubs"], stats["hub_max"] = len(hubs), a.hub_max
    print(f"hidden hubs (top 5 of >= {a.hub_max} photos): {len(hubs)}: "
          + "; ".join(sorted({recs[j]['name'][:28] for j in hubs})[:10]))

    for i in q_idx:
        r = recs[i]
        e = E[a.text_model][i]
        ranks = [[j for j in cand[i][m][0] if j not in hubs][:60] for m in E]
        sims = cand[i][a.text_model][1]
        top1_sims.append(sims[ranks[list(E).index(a.text_model)][0]])
        top = wrrf(ranks, weights)[:a.k]
        # second layer: the visually most similar objects (deeper candidate list) from the same world region
        c = by_sig.get(r.get("cat_sig") or "", {})
        q_geo = g.vmz(c) if c else g.full()
        top_geo = []
        if q_geo["region"] or q_geo["iso"]:
            deep = wrrf([[j for j in cand[i][m][0] if j not in hubs] for m in E], weights)
            top_geo = [j for j in deep if proximity(q_geo, ref_geo[j]) >= 2][:a.k]
        geo_sims = {j: cand[i][a.text_model][1].get(j) for j in top_geo}
        groups, shown = Counter(), {}
        for j in top:
            nm = recs[j]["name"]
            key = (clean_de(nm).lower() if recs[j]["source"] in ("mrz", "md", "mkb") else clean(nm)) or nm.lower()
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

        mkb_hits = mkb.matches([t for t, _ in terms_q[i]]) if mkb else []
        stats["mkb_objects"] += bool(mkb_hits)
        nat = []
        for n in natives(c.get("native")):
            for t, k in nat_idx.get(n, Counter()).most_common(3):
                nat.append((n, t, k))

        # proxy statistics: is the type term of the current name (if certain) among the top VMZ terms?
        tt = type_term(r["name"])
        certain = bool(terms_q[i]) and terms_q[i][0][0] == tt and terms_q[i][0][1] == ""
        calib = r.get("flag") != "Figur"          # calibration only on the «?» / quotation-mark sample
        if r.get("flag") == "Figur":
            fig_terms.update(zs_de[:3])
            fig_en.update(zs_en[:2])
            fig_nb.update(clean_de(recs[j]["name"]) if recs[j]["source"] in ("mrz", "md", "mkb") else clean(recs[j]["name"])
                          for j in top[:5])
        if tt in de_pos and certain and calib:
            rk = 1 + int((s_de > s_de[de_pos[tt]]).sum())
            stats["type_n"] += 1
            stats["type_top8"] += rk <= 8
            stats["type_sup"] += rk <= sup
            stats["type_pos"] += sup < rk <= pos
            stats["type_ranks"] += [rk]
        if len(top_geo) >= 5 and calib:   # does the geographic layer confirm names more often than the visual one?
            n1, n2 = [recs[j]["name"] for j in top[:5]], [recs[j]["name"] for j in top_geo[:5]]
            if tt in tr and certain:
                stats["geo_type_n"] += 1
                stats["geo_type_l1"] += matches(tt, tr[tt], n1)
                stats["geo_type_l2"] += matches(tt, tr[tt], n2)
            for t, mark in terms_q[i]:
                if mark == "?" and t in tr:
                    stats["geo_hyp_n"] += 1
                    stats["geo_hyp_l1"] += matches(t, tr[t], n1)
                    stats["geo_hyp_l2"] += matches(t, tr[t], n2)
        stats["geo_with_region"] += calib and bool(q_geo["region"] or q_geo["iso"])
        stats["geo_with_layer"] += calib and len(top_geo) >= 5
        for t, mark, rank in term_ranks:
            if mark == "?":
                stats["hyp_n"] += 1
                stats["hyp_sup"] += rank <= sup
                stats["hyp_pos"] += sup < rank <= pos
        rows.append(dict(i=i, top=top, sims=sims, knn=knn_names, de=zs_de, en=zs_en, terms=term_ranks, nat=nat,
                         cat=c, catalog=catalog_fields(c, a.public) if c else [], geo=q_geo, top_geo=top_geo,
                         geo_sims=geo_sims, geo_level={j: proximity(q_geo, ref_geo[j]) for j in top_geo},
                         mkb=mkb_hits))
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
    print(f"geographic layer: region known for {stats['geo_with_region']} objects, >= 5 regional neighbours for "
          f"{stats['geo_with_layer']}; type term in top-5 names {stats['geo_type_l1']} visual vs {stats['geo_type_l2']} "
          f"regional (n={stats['geo_type_n']}); «?» hypotheses {stats['geo_hyp_l1']} vs {stats['geo_hyp_l2']} "
          f"(n={stats['geo_hyp_n']})")
    if fig_terms:
        print("«Figur» objects – most frequent VMZ terms (top 3 each):", fig_terms.most_common(15))
        print("«Figur» objects – most frequent neighbour names (top 5 each):", fig_nb.most_common(12))
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
           "groups": dict(Counter(recs[i].get("flag") or "-" for i in q_idx)),
           "figures": {"n": sum(recs[i].get("flag") == "Figur" for i in q_idx),
                       "vmz_terms": fig_terms.most_common(25), "en_terms": fig_en.most_common(15),
                       "neighbour_names": fig_nb.most_common(25)},
           "objects": []}
    for x, s1 in zip(rows, top1_sims):
        r = recs[x["i"]]
        res["objects"].append({
            "inv": r["inv"], "name": r["name"], "flag": r["flag"], "match": r["match"], "img": r["img"],
            "culture": r.get("culture", ""), "country": x["cat"].get("country", ""),
            "native": x["cat"].get("native", ""), "top1": round(s1, 3),
            "catalog": {lab: v for _, lab, v in x["catalog"]},
            "terms": [{"term": t, "mark": m, "rank": k, "en": tr.get(t, "")} for t, m, k in x["terms"]],
            "vmz_terms": [{"term": t, "en": tr.get(t, "")} for t in x["de"]], "en_terms": x["en"],
            "neighbour_names": [{"name": nm, "count": k} for nm, k in x["knn"]],
            "native_matches": [{"native": nn, "term": t, "count": k} for nn, t, k in x["nat"]],
            "neighbours": [{"id": recs[j]["id"], "name": recs[j]["name"], "holder": recs[j].get("holder", ""),
                            "publish_image": can_publish(recs[j]),
                            "culture": recs[j].get("culture", ""), "url": recs[j]["url"], "img": recs[j]["img"],
                            "licence": recs[j].get("licence", ""), "sim": round(x["sims"].get(j, 0), 3)}
                           for j in x["top"][:8]],
            "geo": x["geo"], "mkb_europa": x["mkb"],
            "neighbours_geo": [{"id": recs[j]["id"], "name": recs[j]["name"], "holder": recs[j].get("holder", ""),
                                "culture": recs[j].get("culture", ""), "url": recs[j]["url"], "img": recs[j]["img"],
                                "licence": recs[j].get("licence", ""), "sim": round(x["geo_sims"].get(j) or 0, 3),
                                "proximity": x["geo_level"][j]} for j in x["top_geo"][:8]]})
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
        safe = fname(r["inv"])
        qimg = thumb(data / r["img"], out / "img" / f"q_{safe}.jpg", 320, done)
        def card(j, sim, badge=""):
            rj = recs[j]
            if a.public and not can_publish(rj):                   # rights: name + link only, no image
                pic = '<div class="noimg">Bild nicht veröffentlicht – Link zur Quelle</div>'
            else:
                t = thumb(data / rj["img"], out / "img" / ("r_" + fname(rj["id"]) + ".jpg"), 150, done)
                pic = f'<img src="{t}" alt="" loading="lazy">'
            return (f'<a class="c" href="{esc(rj["url"])}" target="_blank" rel="noopener">'
                    f'{pic}<b>{esc(rj["name"][:70])}</b>'
                    f'<small>{esc((rj.get("holder") or "")[:45])}{" · " + esc(rj["culture"][:30]) if rj.get("culture") else ""}'
                    f'{f" · {sim:.2f}" if sim else ""}</small>{f"<small class=geo>{badge}</small>" if badge else ""}</a>')

        cards = [card(j, x["sims"].get(j)) for j in x["top"][:8]]
        mkb_block = ("<h3>Gleiche Bezeichnung in der MKB-Sammlung Europa (Text, ohne Bild)</h3><div>"
                     + "".join(f'<span class="chip">{esc(m["type"])} «{esc(m["title"][:60])}» <i>{esc(m["origin"][:50])}'
                               f' · {esc(m["inv"])}</i></span>' for m in x["mkb"]) + "</div>") if x["mkb"] else ""
        geo_lab = x["geo"]["region"] or x["geo"]["iso"]
        if x["top_geo"]:
            gcards = "".join(card(j, x["geo_sims"].get(j), "gleiches Land" if x["geo_level"][j] == 3 else "gleiche Region")
                             for j in x["top_geo"][:8])
            geo_block = (f'<h3>Ähnlich und aus derselben Region ({esc(geo_lab)})</h3>'
                         f'<div class="grid">{gcards}</div>')
        elif geo_lab:
            geo_block = (f'<h3>Ähnlich und aus derselben Region ({esc(geo_lab)})</h3><small>Unter den je 200 visuell '
                         f'ähnlichsten Objekten keines aus dieser Region.</small>')
        else:
            geo_block = '<h3>Ähnlich und aus derselben Region</h3><small>Keine Herkunftsregion im Katalog.</small>'

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
        more = [(lab, v) for k, lab, v in x["catalog"] if k not in ("native", "ethnie", "geo_region", "country",
                                                                     "use", "material")]
        if more:
            meta_html += (f'<details class="cat"><summary>Weitere Katalogdaten ({len(more)})</summary><dl>'
                          + "".join(f"<dt>{esc(lab)}</dt><dd>{esc(v)}</dd>" for lab, v in more) + "</dl></details>")
        log = "" if a.public else re.sub(r"\s+", " ", r.get("desc") or "")
        note = (f'<small class="warn">Teilobjekt: Katalogdaten vom Hauptobjekt {esc(r["cat_sig"])}</small>'
                if r.get("match") == "main object" else
                '<small class="warn">nicht im Katalog gefunden</small>' if r.get("match") == "none" else "")
        nat = "".join(f'<span class="chip">{esc(t)} <i>×{k} ({esc(nn)})</i></span>' for nn, t, k in x["nat"][:4])
        text = " ".join([r["inv"], r["name"], " ".join(v for _, _, v in x["catalog"]),
                         " ".join(x["de"]), " ".join(x["en"]), " ".join(nm for nm, _ in x["knn"])]).lower()
        blocks.append(f"""<section id="o-{safe}" data-flag="{esc(r['flag'])}" data-hyp="{hyp_state}" data-text="{esc(text)}">
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
{mkb_block}
<h3>Ähnlichste Objekte</h3><div class="grid">{''.join(cards)}</div>
{geo_block}
</div></div></section>""")

    tn, hn = max(1, stats["type_n"]), max(1, stats["hyp_n"])
    refmix = ", ".join(f"{ {'phil': 'Mapping Philippine Material Culture', 'mrz': 'Museum Rietberg', 'cma': 'Cleveland Museum of Art', 'si': 'Smithsonian', 'md': 'museum-digital', 'mkb': 'Museum der Kulturen Basel (PARC)', 'prm': 'Pitt Rivers Museum'}.get(k, k)}: {v}"
                       for k, v in Counter(src[ref]).items())
    home = esc(a.home) if a.home else ""
    home_nav = f'<nav class="top"><a href="{home}">← Zur Übersicht</a></nav>' if home else ""
    home_bar = f'<a class="home" href="{home}" title="Zur Übersicht">← Übersicht</a>' if home else ""
    page = f"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>VMZ Namensvorschläge</title>
<style>
:root{{--bg:#fafaf8;--fg:#1d1d1b;--mut:#6b6b66;--card:#fff;--line:#e3e2dc;--chip:#f0eee6;--sup:#d7ecd9;--pos:#f3ead0;--no:#f0eee6;--warn:#9a5b00;--acc2:#2f6b3a}}
@media (prefers-color-scheme: dark){{:root:not([data-theme="light"]){{--bg:#191917;--fg:#ecebe6;--mut:#a3a29b;--card:#242422;--line:#3a3935;--chip:#33322e;--sup:#24402a;--pos:#463d22;--no:#33322e;--warn:#e0a24a;--acc2:#8fd19e}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,sans-serif;margin:0 auto;max-width:1240px;padding:16px}}
h1{{font-size:24px;margin:8px 0}} h3{{font-size:13px;color:var(--mut);margin:12px 0 6px;font-weight:600}}
.bar{{position:sticky;top:0;background:var(--bg);padding:10px 0;border-bottom:1px solid var(--line);display:flex;gap:8px;flex-wrap:wrap;align-items:center;z-index:2}}
.bar input,.bar select{{font:inherit;padding:6px 10px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg)}}
.bar input{{flex:1;min-width:200px}}
section{{border-bottom:1px solid var(--line);padding:14px 0}}
section{{scroll-margin-top:64px}} section:target{{background:var(--chip)}}   /* links from the overview land below the sticky bar */
.row{{display:flex;gap:20px;align-items:flex-start;flex-wrap:wrap}} .q{{width:260px;display:flex;flex-direction:column;gap:4px}}
.sug{{flex:1;min-width:280px}} .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(104px,1fr));gap:8px}}
.c{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:6px;text-decoration:none;color:inherit;display:flex;flex-direction:column;gap:3px}}
.c img,.q img{{width:100%;aspect-ratio:1;object-fit:contain;background:#fff;border-radius:4px}}
.chip{{display:inline-block;background:var(--chip);border-radius:999px;padding:2px 10px;margin:0 6px 6px 0;font-size:13px}}
.chip.sup{{background:var(--sup)}} .chip.pos{{background:var(--pos)}} .chip i{{color:var(--mut);font-style:normal}}
b{{font-size:13px}} .name{{font-size:15px}} small{{font-size:11px;color:var(--mut)}} .k{{font-weight:600}} .log{{font-style:italic}}
.warn{{color:var(--warn)}} a{{color:inherit}} .lead{{max-width:900px}} .lead small{{font-size:13px}}
details.cat{{font-size:11px;color:var(--mut)}} details.cat summary{{cursor:pointer;font-weight:600;margin:4px 0}}
details.cat dl{{display:grid;grid-template-columns:auto 1fr;gap:2px 8px;margin:4px 0}} details.cat dt{{font-weight:600}}
details.cat dd{{margin:0;color:var(--fg);white-space:pre-line}}
.c small.geo{{color:var(--acc2);font-weight:600}}
.noimg{{width:100%;aspect-ratio:1;display:flex;align-items:center;justify-content:center;text-align:center;font-size:10px;
color:var(--mut);background:var(--chip);border-radius:4px;padding:6px}}
nav.top{{font-size:13px;margin:4px 0 0}} nav.top a{{color:var(--mut);text-decoration:none}} nav.top a:hover{{color:var(--fg)}}
.bar a.home{{white-space:nowrap;font-weight:600;text-decoration:none;padding:6px 10px;border:1px solid var(--line);border-radius:8px;background:var(--card)}}
@media (max-width:600px){{.q{{width:100%}}}}
</style></head><body>
{home_nav}
<h1>Namensvorschläge für VMZ-Objekte mit unsicheren oder generischen Namen (PoC)</h1>
<div class="lead"><p>{n} Objekte aus der GLAMhack-Stichprobe des Völkerkundemuseums der Universität Zürich:
{sum(1 for x in rows if '?' in (recs[x['i']].get('flag') or ''))} mit «?», {sum(1 for x in rows if '«' in (recs[x['i']].get('flag') or ''))} mit Anführungszeichen,
{sum(1 for x in rows if recs[x['i']].get('flag') == 'Figur')} nur «Figur» genannt.
Vergleichsbestand: {len(ref)} Objekte anderer Sammlungen ({refmix}). Bildähnlichkeit: SigLIP 2 + DINOv2 (gewichtete Rangfusion, DINOv2 mit Gewicht {a.dino_weight});
Begriffe: SigLIP 2 Bild ↔ Text gegen {len(de_vocab)} Typbegriffe aus den Objektnamen des VMZ-Katalogs (≥ {a.min_count} Objekte),
vorher maschinell ins Englische übersetzt (grau: die Übersetzung, mit der gerechnet wurde).</p>
<p><small>Rang = Platz des Begriffs unter allen {len(de_vocab)} VMZ-Begriffen für dieses Foto:
<span class="chip sup">≤ {sup}: vom Bild gestützt</span><span class="chip pos">≤ {pos}: möglich</span><span class="chip">&gt; {pos}: nicht gestützt</span>
Kalibrierung an den sicheren Typbegriffen der aktuellen Namen (n={stats['type_n']}): {stats['type_sup'] / tn:.0%} gestützt, {stats['type_pos'] / tn:.0%} möglich,
Median-Rang {int(np.median(stats['type_ranks'])) if stats['type_ranks'] else '–'}. «Gestützt» ist also ein starkes Indiz (zufällig: 2 %),
«nicht gestützt» nur ein schwaches – auch richtige Begriffe landen oft dort, besonders seltene Fachwörter oder falsch übersetzte.
Von {stats['hyp_n']} «?»-Hypothesen sind {stats['hyp_sup'] / hn:.0%} gestützt, {stats['hyp_pos'] / hn:.0%} möglich.
Zweite Suchschicht: Unter den je 200 visuell ähnlichsten Objekten werden zusätzlich die aus derselben Weltregion
bzw. demselben Land gezeigt (Herkunft aus dem VMZ-Katalog und den Angaben der Vergleichssammlungen); verfügbar bei
{stats['geo_with_layer']} von {n} Objekten. Die Namen bestätigen dort den Typbegriff in
{stats['geo_type_l2'] / max(1, stats['geo_type_n']):.0%} statt {stats['geo_type_l1'] / max(1, stats['geo_type_n']):.0%} der Fälle,
die «?»-Hypothese in {stats['geo_hyp_l2'] / max(1, stats['geo_hyp_n']):.0%} statt {stats['geo_hyp_l1'] / max(1, stats['geo_hyp_n']):.0%}.
Zahl auf den Karten = Bildähnlichkeit (SigLIP 2, höher = ähnlicher). Ausgeblendet sind {stats['hubs']} Vergleichsobjekte,
die bei {stats['hub_max']} oder mehr Fotos unter den Top 5 wären («Hubs», z. B. kleine Glasfragmente).
Vorschläge sind Hinweise – entscheiden muss die Fachperson.
{RIGHTS_PUBLIC + ' ' + CATALOG_PUBLIC if a.public else 'Bilder und Katalogdaten: intern, nicht veröffentlichen.'}</small></p></div>
<div class="bar">{home_bar}<input id="q" type="search" placeholder="Suche: Inventarnummer, Name, Begriff, Region …" aria-label="Suche">
<select id="flag" aria-label="Markierung"><option value="">alle Gruppen</option><option value="?">nur «?»</option><option value="«»">nur Anführungszeichen</option><option value="Figur">nur «Figur» (generischer Name)</option></select>
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
               "Ähnlichste Objekte (Name | Museum | Link)", "Ähnlichkeit Top-1 (SigLIP 2)",
               "Herkunftsregion", "Ähnlich und aus derselben Region (Name | Museum | Link)",
               "MKB-Sammlung Europa (Text): gleiche Bezeichnung"]
              + [lab for _, lab in PUBLIC_FIELDS + ([] if a.public else INTERNAL_FIELDS)])
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
                   round(s1, 3), x["geo"]["region"] or x["geo"]["iso"],
                   "\n".join(f"{recs[j]['name'][:60]} | {recs[j].get('holder', '')[:40]} | {recs[j]['url']}"
                             for j in x["top_geo"][:5]),
                   "\n".join(f"{m['type']} «{m['title']}» | {m['origin']} | {m['inv']}" for m in x["mkb"])]
                  + [dict((lab, v) for _, lab, v in x["catalog"]).get(lab, "")
                     for _, lab in PUBLIC_FIELDS + ([] if a.public else INTERNAL_FIELDS)])
    for col, w in zip("ABCDEFGHIJKLMN", [12, 40, 8, 10, 18, 18, 14, 40, 50, 40, 50, 30, 80, 10]):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "C2"
    wb.save(out / "vmz_suggestions.xlsx")
    print(f"\nwrote {out / 'index.html'} ({len(list((out / 'img').glob('*.jpg')))} thumbnails) "
          f"and {out / 'vmz_suggestions.xlsx'}")


if __name__ == "__main__":
    main()
