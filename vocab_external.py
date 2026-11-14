"""External controlled vocabularies for the term suggestions, as local term lists with URIs.

Sources (downloaded once into OUT/raw/, then read locally):
  - Getty AAT (Art & Architecture Thesaurus), SPARQL at vocab.getty.edu, ODC-By 1.0. The object hierarchies
    Furnishings and Equipment, Visual and Verbal Communication, Object Genres and Components, with English,
    German (AAT-Deutsch) and Dutch labels. Built Environment and Object Groupings are left out.
  - NMVW thesaurus (Nationaal Museum van Wereldculturen, now Wereldmuseum) on the Colonial Collections hub,
    CC0: the scheme «Objecttrefwoord» (object terms), Dutch labels, often English ones, skos:exactMatch to AAT.
  - GND subject headings (Sachbegriffe, Deutsche Nationalbibliothek), CC0: the full dump from data.dnb.de
    (lobid-gnd did not answer on 14.11.2026), plus the AAT <-> GND pairs in Wikidata (P1014 + P227, CC0).
  - Trachsler, «Systematik kulturhistorischer Sachgüter» (Verband der Museen der Schweiz, via KIM.ch): the
    trilingual export (de/fr/it, ~4,900 classes). The export states no licence, so the list stays local (data/,
    not in the repository); the pages only name the matching class with its notation and a link to xTree.
  - The MEK collection concept (Museum Europäischer Kulturen, 2022) is orientation only: its 74 subject groups
    (by context of use) are not published.

Everything is anchored on AAT concepts, because they have English labels for SigLIP 2 (no machine translation)
and the other vocabularies link to them: NMVW via its own exactMatch, GND via Wikidata (and a few owl:sameAs
in the GND). German terms (VMZ or MKB names) are matched on German labels of AAT, GND and Trachsler.

Usage: python vocab_external.py --out data/vocab              # ~3 min, ~60 MB downloads (cached)
       python vocab_external.py --out data/vocab --refresh    # download again
"""
import argparse
import bisect
import csv
import datetime
import gzip
import json
import re
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import requests

UA = {"User-Agent": "glamhack26-similar-search/0.1 (research prototype; vocabulary download)"}
AAT_SPARQL = "https://vocab.getty.edu/sparql.json"
AAT_HIER = {"300264551": "Furnishings and Equipment", "300264552": "Visual and Verbal Communication",
            "300185711": "Object Genres", "300241490": "Components"}
AAT_LANG = {"300388277": "en", "300388344": "de", "300388256": "nl"}
COMPONENTS = "300241490"                    # AAT hierarchy of object parts (Components)
NMVW_DUMP = "https://api.colonialcollections.nl/datasets/nmvw/thesaurus/download.trig.gz"
NMVW_OBJ = "https://hdl.handle.net/20.500.11840/conceptscheme2"           # «Objecttrefwoord»
GND_DUMP = "https://data.dnb.de/opendata/authorities-gnd-sachbegriff_lds.rdf.gz"
WD_SPARQL = "https://query.wikidata.org/sparql"
TRACHSLER = "https://downloads.kimnet.ch/Downloads/public/Trachsler/trachsler.txt"

SOURCES = {
    "aat": {"name": "Getty AAT", "licence": "ODC-By 1.0", "url": "https://www.getty.edu/research/tools/vocabularies/aat/",
            "credit": "Art & Architecture Thesaurus® (AAT), J. Paul Getty Trust, ODC-By 1.0"},
    "gnd": {"name": "GND", "licence": "CC0 1.0", "url": "https://www.dnb.de/gnd",
            "credit": "Gemeinsame Normdatei (GND), Deutsche Nationalbibliothek, CC0 1.0"},
    "nmvw": {"name": "NMVW-Thesaurus", "licence": "CC0 1.0", "url": "https://data.colonialcollections.nl/nmvw/thesaurus",
             "credit": "Thesaurus des Nationaal Museum van Wereldculturen (Wereldmuseum), CC0 1.0"},
    "trachsler": {"name": "Trachsler", "licence": "keine Angabe (nur Notation, Klassenname und Link)",
                  "url": "https://www.museums.ch/de/fachwelt/fachthemen/inventar-1159.html",
                  "credit": "W. Trachsler, Systematik kulturhistorischer Sachgüter (1981), Thesaurus Trachsler, "
                            "Verband der Museen der Schweiz / KIM.ch"},
    "wikidata": {"name": "Wikidata", "licence": "CC0 1.0", "url": "https://www.wikidata.org/",
                 "credit": "Wikidata (AAT- und GND-Kennungen, P1014/P227), CC0 1.0"},
}


def link(src, cid):
    """Human-readable page of a concept."""
    if src == "aat":
        return f"https://vocab.getty.edu/page/aat/{cid}"
    if src == "gnd":
        return f"https://d-nb.info/gnd/{cid}"
    if src == "nmvw":
        return f"https://hdl.handle.net/20.500.11840/{cid}"       # -> collectie.wereldmuseum.nl/thesaurus
    if src == "trachsler":
        return ("https://xtree-public.digicult-verbund.de/vocnet/?uriVocItem=http://digicult.vocnet.org/trachsler/"
                f"&startNode={cid}&lang=de&d=n")
    raise ValueError(src)


def uri(src, cid):
    """Identifier (URI) of a concept."""
    return {"aat": f"http://vocab.getty.edu/aat/{cid}", "gnd": f"https://d-nb.info/gnd/{cid}",
            "nmvw": f"https://hdl.handle.net/20.500.11840/{cid}",
            "trachsler": f"http://digicult.vocnet.org/trachsler/{cid}"}[src]


# ------------------------------------------------------------------------------------------------ downloads
def fetch(url, path, refresh=False, params=None, headers=None, timeout=600):
    if path.exists() and not refresh:
        return path
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, headers={**UA, **(headers or {})}, timeout=timeout, stream=True)
            r.raise_for_status()
            tmp = path.with_suffix(path.suffix + ".part")
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
            tmp.rename(path)
            print(f"  fetched {path.name} ({path.stat().st_size / 1e6:.1f} MB)")
            return path
        except requests.RequestException as e:          # the Getty endpoint sometimes drops long queries
            print(f"  {path.name}: {e} – retry {attempt + 1}")
            time.sleep(10 * (attempt + 1))
    raise SystemExit(f"could not download {url}")


def fetch_aat(raw, refresh):
    """Trees (concept -> preferred parent) and en/de/nl labels of the AAT object hierarchies."""
    for h in AAT_HIER:
        q_tree = (f"SELECT ?c ?t ?p WHERE {{ ?c gvp:broaderPreferredExtended aat:{h} ; gvp:broaderPreferred ?p ; a ?t . "
                  "FILTER(?t IN (gvp:Concept, gvp:GuideTerm, gvp:HierarchyName)) }")
        q_lab = (f"SELECT ?c ?r ?lit ?lang ?pos WHERE {{ ?c gvp:broaderPreferredExtended aat:{h} . "
                 "VALUES ?r { xl:prefLabel xl:altLabel } ?c ?r ?t . ?t xl:literalForm ?lit ; dct:language ?lang . "
                 "VALUES ?lang { aat:300388277 aat:300388344 aat:300388256 } OPTIONAL { ?t gvp:termPOS ?pos } }")
        # the Getty preferred label: newer concepts have no language tag on their English term
        q_gvp = (f"SELECT ?c ?lit WHERE {{ ?c gvp:broaderPreferredExtended aat:{h} ; "
                 "gvp:prefLabelGVP/xl:literalForm ?lit }")
        fetch(AAT_SPARQL, raw / f"aat_tree_{h}.json", refresh, params={"query": q_tree})
        fetch(AAT_SPARQL, raw / f"aat_labels_{h}.json", refresh, params={"query": q_lab})
        fetch(AAT_SPARQL, raw / f"aat_gvp_{h}.json", refresh, params={"query": q_gvp})
    # labels of the hierarchy names themselves and of the facet (for paths)
    q_top = ("SELECT ?c ?lit WHERE { VALUES ?c { " + " ".join(f"aat:{h}" for h in AAT_HIER) +
             " aat:300264092 } ?c gvp:prefLabelGVP/xl:literalForm ?lit }")
    fetch(AAT_SPARQL, raw / "aat_top.json", refresh, params={"query": q_top})
    # Materials facet: German and English labels, to recognise materials in names («Figur; Ton», «Spitze, Stein»)
    q_mat = ("SELECT ?c ?r ?lit ?lang WHERE { ?c gvp:broaderPreferredExtended aat:300264091 . "
             "VALUES ?r { xl:prefLabel xl:altLabel } ?c ?r ?t . ?t xl:literalForm ?lit ; dct:language ?lang . "
             "VALUES ?lang { aat:300388277 aat:300388344 } }")
    fetch(AAT_SPARQL, raw / "aat_materials.json", refresh, params={"query": q_mat})


def fetch_all(raw, refresh=False):
    raw.mkdir(parents=True, exist_ok=True)
    fetch_aat(raw, refresh)
    fetch(NMVW_DUMP, raw / "nmvw_thesaurus.trig.gz", refresh)
    fetch(GND_DUMP, raw / "gnd_sachbegriff.rdf.gz", refresh)
    fetch(WD_SPARQL, raw / "wikidata_aat_gnd.csv", refresh, headers={"Accept": "text/csv"},
          params={"query": "SELECT ?i ?aat ?gnd WHERE { ?i wdt:P1014 ?aat ; wdt:P227 ?gnd }"})
    fetch(TRACHSLER, raw / "trachsler.txt", refresh)


# ------------------------------------------------------------------------------------------------ parsing
def sparql_rows(path):
    return json.load(open(path, encoding="utf-8"))["results"]["bindings"]


def tail(u):
    return u.rstrip("/").rsplit("/", 1)[-1].rsplit("#", 1)[-1]


def base(label):
    """'masks (costume)' -> 'masks'."""
    return re.sub(r"\s*[(<].*?[)>]", "", label or "").strip()


def parse_aat(raw):
    """AAT id -> {t: Concept|GuideTerm|HierarchyName, p: parent id, h: hierarchy id, en, en1 (singular), de, de_alt,
    nl}. Guide terms (<baskets by form>) are kept for the paths but are not candidates."""
    C = {}
    for h in AAT_HIER:
        for b in sparql_rows(raw / f"aat_tree_{h}.json"):
            c = tail(b["c"]["value"])
            C.setdefault(c, {"t": tail(b["t"]["value"]), "p": tail(b["p"]["value"]), "h": h})
        labs = defaultdict(lambda: defaultdict(list))
        for b in sparql_rows(raw / f"aat_labels_{h}.json"):
            c, lang = tail(b["c"]["value"]), AAT_LANG.get(tail(b["lang"]["value"]))
            pos = tail(b["pos"]["value"]) if "pos" in b else ""
            kind = "pref" if b["r"]["value"].endswith("prefLabel") else "alt"
            labs[c][(lang, kind)].append((b["lit"]["value"], pos))
        gvp = {tail(b["c"]["value"]): b["lit"]["value"] for b in sparql_rows(raw / f"aat_gvp_{h}.json")}
        for c, x in C.items():
            if x["h"] == h:
                labs[c]                                           # also concepts without any tagged label
        for c, L in labs.items():
            if c not in C:
                continue
            en = [x for x, _ in L[("en", "pref")]] or ([gvp[c]] if c in gvp else [])
            C[c]["en"] = en[0] if en else ""
            sing = [x for x, p in L[("en", "alt")] if p == "SingularNoun"]
            pb = base(C[c]["en"]).lower()
            pick = ""
            if L[("en", "pref")] and L[("en", "pref")][0][1] != "PluralNoun":
                pick = C[c]["en"]                                 # mass nouns etc. are their own singular
            for s in sing:                                        # the singular of the preferred term, not a synonym
                sb = base(s).lower()
                if not pick and sb and (pb.startswith(sb[:max(3, len(sb) - 1)]) or sb.startswith(pb[:max(3, len(pb) - 3)])):
                    pick = s
            C[c]["en1"] = pick or C[c]["en"]
            C[c]["en_alt"] = sorted({x for x, _ in L[("en", "alt")]} - {C[c]["en1"]})[:12]
            de = [x for x, _ in L[("de", "pref")]]
            C[c]["de"] = de[0] if de else ""
            C[c]["de_alt"] = sorted({x for x, _ in L[("de", "alt")]})[:12]
            nl = [x for x, _ in L[("nl", "pref")]]
            C[c]["nl"] = nl[0] if nl else ""
    for b in sparql_rows(raw / "aat_top.json"):
        c = tail(b["c"]["value"])
        C.setdefault(c, {"t": "HierarchyName", "p": "300264092", "h": c})["en"] = b["lit"]["value"]
    return C


TRIPLE = re.compile(r'^<([^>]+)> <([^>]+)> (<[^>]+>|"((?:[^"\\]|\\.)*)"(?:@([\w-]+)|\^\^<[^>]+>)?) \.$')


def parse_nmvw(raw):
    """NMVW «Objecttrefwoord» concepts: id -> {nl, nl_alt, en, aat, p, n (notation)}."""
    C = defaultdict(lambda: defaultdict(list))
    for line in gzip.open(raw / "nmvw_thesaurus.trig.gz", "rt", encoding="utf-8"):
        m = TRIPLE.match(line.strip())
        if not m:
            continue
        s, p, o, lit, lang = m.groups()
        key = p.rsplit("#", 1)[-1]
        if key not in ("prefLabel", "altLabel", "exactMatch", "broader", "notation", "inScheme"):
            continue
        if lit is not None:
            o = json.loads('"' + lit + '"')
            if key == "altLabel" and lang == "en":
                key = "en"
        else:
            o = o[1:-1]
        C[tail(s)][key].append(o)
    out = {}
    for c, d in C.items():
        if NMVW_OBJ not in d.get("inScheme", []):
            continue
        out[c] = {"nl": (d.get("prefLabel") or [""])[0], "nl_alt": d.get("altLabel", [])[:12],
                  "en": d.get("en", [])[:12], "p": tail((d.get("broader") or [""])[0]),
                  "aat": [tail(x) for x in d.get("exactMatch", []) if "vocab.getty.edu/aat/" in x],
                  "n": (d.get("notation") or [""])[0]}
    return out


def parse_gnd(raw):
    """GND subject headings in the narrow sense (SubjectHeadingSensoStricto): id -> {de, alt, b, c, wd, aat}."""
    ns = {"rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#", "gndo": "https://d-nb.info/standards/elementset/gnd#",
          "owl": "http://www.w3.org/2002/07/owl#"}
    R = "{%s}" % ns["rdf"]
    out = {}
    for _, el in ET.iterparse(gzip.open(raw / "gnd_sachbegriff.rdf.gz"), events=("end",)):
        about = el.get(R + "about", "")
        if el.tag != R + "Description" or not about.startswith("https://d-nb.info/gnd/") or about.endswith("/about"):
            continue
        types = {tail(x.get(R + "resource")) for x in el.findall("rdf:type", ns)}
        if "SubjectHeadingSensoStricto" in types:
            same = [x.get(R + "resource") or "" for x in el.findall("owl:sameAs", ns)]
            out[tail(about)] = {
                "de": next((x.text for x in el.findall("gndo:preferredNameForTheSubjectHeading", ns)), ""),
                "alt": [x.text for x in el.findall("gndo:variantNameForTheSubjectHeading", ns)][:12],
                "b": [tail(x.get(R + "resource")) for t in ("broaderTermGeneral", "broaderTermGeneric",
                                                             "broaderTermPartitive")
                      for x in el.findall("gndo:" + t, ns)],
                "c": [tail(x.get(R + "resource")) for x in el.findall("gndo:gndSubjectCategory", ns)],
                "wd": next((tail(s) for s in same if "wikidata.org" in s), ""),
                "aat": [tail(s) for s in same if "vocab.getty.edu/aat/" in s]}
        el.clear()
    return out


def parse_materials(raw):
    """AAT Materials facet: id -> {de: preferred German label, de_alt, en}."""
    out = defaultdict(lambda: {"de": "", "de_alt": [], "en": ""})
    for b in sparql_rows(raw / "aat_materials.json"):
        c, lang = tail(b["c"]["value"]), AAT_LANG.get(tail(b["lang"]["value"]))
        pref = b["r"]["value"].endswith("prefLabel")
        x = out[c]
        if lang == "de":
            if pref:
                x["de"] = b["lit"]["value"]
            else:
                x["de_alt"].append(b["lit"]["value"])
        elif lang == "en" and pref:
            x["en"] = b["lit"]["value"]
    return dict(out)


def parse_trachsler(raw):
    rows = csv.DictReader(open(raw / "trachsler.txt", encoding="utf-8-sig", newline=""), delimiter="\t")
    return {r["id"]: {"n": r["notation"], "p": r["parent_id"], "de": r["de"], "fr": r["fr"], "it": r["it"]}
            for r in rows if r["id"]}


def build(raw):
    aat, nmvw, gnd, tra = parse_aat(raw), parse_nmvw(raw), parse_gnd(raw), parse_trachsler(raw)
    wd = [(r["aat"], r["gnd"]) for r in csv.DictReader(open(raw / "wikidata_aat_gnd.csv", encoding="utf-8"))]
    # cross-links on the AAT concepts
    for c, d in nmvw.items():
        for a in d["aat"]:
            if a in aat:
                aat[a].setdefault("nmvw", []).append(c)
    pairs = set(wd) | {(a, g) for g, d in gnd.items() for a in d["aat"]}
    for a, g in sorted(pairs):
        if a in aat and g in gnd:
            aat[a].setdefault("gnd", []).append(g)
    return {"built": datetime.date.today().isoformat(), "sources": SOURCES, "aat": aat, "nmvw": nmvw, "gnd": gnd,
            "trachsler": tra, "materials": parse_materials(raw)}


# ------------------------------------------------------------------------------------------------ use
def norm_de(s):
    """German label for matching: lower case, no qualifier, Swiss «ss» for «ß» (the VMZ writes «Gefäss»)."""
    s = base(s).lower().replace("ß", "ss")
    return re.sub(r"\s+", " ", s).strip(" .-")


DE_SUFFIX = ("", "e", "n", "en", "er", "s", "es", "r", "nen")      # German plural / inflection endings
# materials whose translation goes wrong (Ton -> sound) or is missing in the VMZ translation cache
DE_MATERIAL = {"ton": "clay", "leder": "leather", "lack": "lacquer", "fell": "fur"}


def umlaut(w):
    """Umlaut plural stem: 'korb' -> 'körb' (Körbe), 'hut' -> 'hüt', 'kamm' -> 'kämm', 'baum' -> 'bäum'."""
    m = re.search(r"(au|a|o|u)([^aeiouäöü]*)$", w)
    if not m:
        return w
    rep = {"au": "äu", "a": "ä", "o": "ö", "u": "ü"}[m.group(1)]
    return w[:m.start()] + rep + m.group(2)


def sing_en(w):
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("es") and w[:-2].endswith(("sh", "ch", "x", "ss")):
        return w[:-2]
    if w.endswith("s") and not w.endswith(("ss", "us", "is")) and len(w) > 3:
        return w[:-1]
    return w


def norm_en(s):
    words = base(s).lower().replace("-", " ").split()
    return " ".join(words[:-1] + [sing_en(words[-1])]) if words else ""


class Vocab:
    """The external vocabularies of vocab_external.json with indices for matching and display.

    Concept keys: AAT ids ('300194498') and, for object terms of the NMVW thesaurus without an AAT match, NMVW ids
    ('termmaster10049010')."""

    def __init__(self, path):
        d = json.load(open(path, encoding="utf-8"))
        self.built, self.sources = d["built"], d["sources"]
        self.aat, self.nmvw, self.gnd, self.tra = d["aat"], d["nmvw"], d["gnd"], d["trachsler"]
        self.mat = d.get("materials", {})
        self.de_mat, self.en_mat = {}, {}
        for c, x in self.mat.items():
            for lab in x["de_alt"] + [x["de"]]:           # the preferred label wins
                if lab:
                    self.de_mat[norm_de(lab)] = c
            if x["en"]:
                self.en_mat.setdefault(norm_en(x["en"]), c)
        self.de_aat, self.de_gnd, self.en_aat = defaultdict(set), defaultdict(set), defaultdict(set)
        self.en_pref = defaultdict(set)             # preferred / singular English labels only (display route)
        for c, x in self.aat.items():
            if x["t"] != "Concept":
                continue
            for lab in [x.get("de", "")] + x.get("de_alt", []):
                if lab:
                    self.de_aat[norm_de(lab)].add(c)
            for lab in [x.get("en", ""), x.get("en1", "")] + x.get("en_alt", []):
                if lab:
                    self.en_aat[norm_en(lab)].add(c)
            for lab in (x.get("en", ""), x.get("en1", "")):
                if lab:
                    self.en_pref[norm_en(lab)].add(c)
        for g, x in self.gnd.items():
            for lab in [x["de"]] + x["alt"]:
                if lab:
                    self.de_gnd[norm_de(lab)].add(g)
        self.gnd2aat = defaultdict(set)
        for c, x in self.aat.items():
            for g in x.get("gnd", []):
                self.gnd2aat[g].add(c)
        # preferred German names only, for the heads of compounds («Holzmaske» -> Maske): alternative labels are too
        # loose there («Binde» is an AAT synonym of «Damenbinde»)
        self.de_pref = defaultdict(set)
        for c, x in self.aat.items():
            if x["t"] == "Concept" and x.get("de"):
                self.de_pref[norm_de(x["de"])].add(c)
        for g, cs in self.gnd2aat.items():
            self.de_pref[norm_de(self.gnd[g]["de"])] |= cs
        # NMVW object terms without an AAT match, by their English labels («twin sculptures»)
        self.en_nmvw = defaultdict(set)
        for n, x in self.nmvw.items():
            if not x["aat"]:
                for lab in x["en"]:
                    self.en_nmvw[norm_en(lab)].add(n)
        # GND heading with exactly the German AAT label, where Wikidata has no pair (e.g. «Pfeilspitze»); only headings
        # without a qualifier, since «Verbindung <Privatrecht>» or «Onager <Motiv>» are other concepts
        self.gnd_label = {}
        for c, x in self.aat.items():
            if x["t"] == "Concept" and x.get("de") and not x.get("gnd"):
                gs = [g for g in self.de_gnd.get(norm_de(x["de"]), ())
                      if norm_de(self.gnd[g]["de"]) == norm_de(x["de"]) and "<" not in self.gnd[g]["de"]]
                if len(gs) == 1:
                    self.gnd_label[c] = gs[0]
        # NMVW object terms without an AAT match: nearest broader NMVW term that has one (for the hierarchy)
        self.nmvw_anc = {}
        for n, x in self.nmvw.items():
            if x["aat"]:
                continue
            p, k = x["p"], 0
            while p in self.nmvw and k < 20:
                hit = [a for a in self.nmvw[p]["aat"] if a in self.aat]
                if hit:
                    self.nmvw_anc[n] = hit[0]
                    break
                p, k = self.nmvw[p]["p"], k + 1
        # Trachsler: a class names object types in its title and lists examples in brackets
        # («6.212.212.0 Schlagtrommeln (Kesseltrommeln, Kesselpauken, …)») -> word index for both parts
        self.tra_main, self.tra_ex = defaultdict(set), defaultdict(set)
        for t, x in self.tra.items():
            main, _, ex = x["de"].partition("(")
            for part, idx in ((main, self.tra_main), (ex, self.tra_ex)):
                for w in re.findall(r"[A-Za-zÄÖÜäöüß]{3,}", part):
                    idx[w.lower().replace("ß", "ss")].add(t)
        # reversed words, sorted: words ending in a given noun (heads of compounds) by binary search
        self.tra_rev = sorted((w[::-1], w, part) for part, idx in (("main", self.tra_main), ("ex", self.tra_ex))
                              for w in idx)
        self.tra_keys = [r[0] for r in self.tra_rev]

    # -------------------------------------------------------------- matching German terms
    def _lookup(self, k, en=None, head=False):
        if head:
            return set(self.de_pref.get(k, ()))
        ids = set(self.de_aat.get(k, ())) | {a for g in self.de_gnd.get(k, ()) for a in self.gnd2aat.get(g, ())}
        if en:
            ids |= self.en_aat.get(norm_en(en), set()) | self.en_nmvw.get(norm_en(en), set())
        return ids

    def match_de(self, term, en=None):
        """AAT concepts for a German term (VMZ or MKB name). Union of: German AAT label, GND label -> Wikidata -> AAT,
        and the English translation `en` on English AAT labels (all senses: «Trommel» -> drums (membranophones) and
        drums (column components); the photo decides). Without a match, the head of a compound or the first word of
        a phrase is tried («Holzmaske» -> Maske, «Mundorgel Sheng» -> Mundorgel).
        Returns (aat ids, route) with route 'exact', 'head' or ''."""
        k = norm_de(term)
        ids = self._lookup(k, en)
        if ids:
            return sorted(ids), "exact"
        words = [w for w in re.split(r"[\s-]+", k) if w]
        tries = ([words[0], words[-1]] if " " in k else [words[-1]] if "-" in k else []) + \
                [k[i:] for i in range(1, max(1, len(k) - 3))]               # compound heads, longest first
        for h in tries:
            if len(h) >= 4 and h != k:
                ids = self._lookup(h, head=True)
                if ids:
                    return sorted(ids), "head"
        return [], ""

    def material(self, term, en=None):
        """AAT material concept for a German word of a name («Ton», «Stein», «Holz»): German AAT label, else the
        English translation (AAT-Deutsch has few materials). None if it is no material."""
        k = norm_de(term)
        en = DE_MATERIAL.get(k, en)           # «Ton» is translated as «sound», «Leder» not at all
        return self.de_mat.get(k) or (self.en_mat.get(norm_en(en)) if en else None)

    def _prefer(self, ids):
        """Among several senses: those the NMVW thesaurus uses, and whole objects before parts (Components)."""
        used = [c for c in ids if self.is_nmvw(c) or self.aat[c].get("nmvw")] or ids
        return [c for c in used if self.is_nmvw(c) or self.aat[c]["h"] != COMPONENTS] or used

    def senses(self, term, en=None):
        """The concepts a German name term most likely means, for display: the preferred labels of AAT-Deutsch first,
        else all other routes together (GND via Wikidata – one wrong pair would decide alone, «Schale» -> Kylix –,
        German synonyms, the English translation), else the head of a compound; within a step the senses the NMVW
        thesaurus uses and whole objects before parts. The photo picks among the rest (Suggester.analyse).
        match_de() keeps all senses, for the evaluation. Returns (ids, route)."""
        k = norm_de(term)
        aat_pref = {c for c in self.de_pref.get(k, ()) if self.aat[c].get("de") and norm_de(self.aat[c]["de"]) == k}
        if any(self.aat[c]["h"] != COMPONENTS for c in aat_pref):     # AAT-Deutsch first, if it names a whole object
            return self._prefer(sorted(aat_pref)), "exact"
        german = self._lookup(k) | aat_pref                # GND (Wikidata), German synonyms
        mt = (self.en_pref.get(norm_en(en), set()) | self.en_nmvw.get(norm_en(en), set())) if en else set()
        if german or mt:                                   # translation: preferred English labels only
            ids = sorted(german | mt)
            if aat_pref:     # AAT-Deutsch names only a part («Gefäß (Blankwaffe)»; vessels have no German label):
                used = [c for c in ids if self.is_nmvw(c) or self.aat[c].get("nmvw")]    # the photo decides
                return used or ids, "exact"
            return self._prefer(ids), "exact" if german else "mt"
        ids, route = self.match_de(term, en)
        return (self._prefer(ids), route) if ids else ([], "")

    def gnd_de(self, term):
        """GND headings with this German name (preferred or variant): the preferred name without qualifier first;
        motif headings («Maske <Motiv>») are left out, they are subjects of images, not object types."""
        k = norm_de(term)
        gs = [g for g in self.de_gnd.get(k, ()) if "<Motiv>" not in self.gnd[g]["de"]]
        return sorted(gs, key=lambda g: (norm_de(self.gnd[g]["de"]) != k, "<" in self.gnd[g]["de"], g))

    def trachsler_de(self, *terms, k=3):
        """Trachsler classes for German nouns, best score first, then the most specific class."""
        hits = self.trachsler_scores(*terms)
        return sorted(hits, key=lambda i: (-hits[i], -len(self.tra[i]["n"].replace(".", ""))))[:k] if hits else []

    def trachsler_scores(self, *terms):
        """Score of the Trachsler classes for German nouns: the word in the title 4, as head of a compound in the
        title 3, among the examples 2 / 1 («Trommel» -> «Schlagtrommeln (…)», «Korb» -> «… (Standkörbe, Kratten)»);
        also plurals and umlaut plurals."""
        hits = Counter()
        for term in terms:
            t = norm_de(term)
            if len(t) < 3 or " " in t:
                continue
            for f in {t, umlaut(t)}:
                for s in DE_SUFFIX:
                    fs = f + s
                    r = fs[::-1]
                    j = bisect.bisect_left(self.tra_keys, r)
                    while j < len(self.tra_keys) and self.tra_keys[j].startswith(r):
                        _, w, part = self.tra_rev[j]
                        j += 1
                        if w != fs and len(f) < 4:
                            continue
                        score = (4 if w == fs else 3) if part == "main" else (2 if w == fs else 1)
                        for i in (self.tra_main if part == "main" else self.tra_ex)[w]:
                            hits[i] = max(hits[i], score)
        return hits

    def trachsler_within(self, t, g):
        """Is Trachsler class t the class g or below it? (decimal notation: children append digits)"""
        return self.tra[t]["n"].replace(".", "").startswith(self.tra[g]["n"].replace(".", ""))

    def trachsler_path(self, t):
        """'6 Brauchtum › 6.130 Fasnacht, Maskenlaufen › 6.130.2 Fasnachtsmasken, «Larven»' (top, parent, class)."""
        chain, p = [], t
        while p in self.tra and len(chain) < 12:
            chain.append(p)
            p = self.tra[p]["p"]
        chain = chain[::-1]
        pick = [chain[0]] + ([chain[-2]] if len(chain) > 2 else []) + ([chain[-1]] if len(chain) > 1 else [])
        return " › ".join(f"{self.tra[x]['n']} {base(self.tra[x]['de'])}" for x in pick)

    # -------------------------------------------------------------- display
    def is_nmvw(self, c):
        return c.startswith("termmaster")

    def label_de(self, c):
        if self.is_nmvw(c):
            return ""
        x = self.aat[c]
        if x.get("de"):
            return x["de"]
        g = x.get("gnd", []) or ([self.gnd_label[c]] if c in self.gnd_label else [])
        return self.gnd[g[0]]["de"] if g else ""

    def label_en(self, c):
        if self.is_nmvw(c):
            return (self.nmvw[c]["en"] or [self.nmvw[c]["nl"]])[0]
        return self.aat[c].get("en", "")

    def concept(self, c):
        """Display data of a concept: labels, the AAT concept and its equivalents in GND and NMVW (Trachsler: see
        Suggester.card, the photo picks the class)."""
        if self.is_nmvw(c):
            x = self.nmvw[c]
            anc = self.nmvw_anc.get(c)
            return {"key": c, "de": "", "en": self.label_en(c), "nl": x["nl"], "aat": None, "broader_aat": anc,
                    "broader": self.label_en(anc) if anc else "", "gnd": [], "nmvw": [(c, x["nl"])]}
        x = self.aat[c]
        gnd = x.get("gnd", []) or ([self.gnd_label[c]] if c in self.gnd_label else [])
        return {"key": c, "de": self.label_de(c), "en": x.get("en", ""), "nl": x.get("nl", ""), "aat": c,
                "path": self.path(c), "gnd": [(g, self.gnd[g]["de"]) for g in gnd[:2]],
                "nmvw": [(n, self.nmvw[n]["nl"]) for n in x.get("nmvw", [])[:2]]}

    def path(self, c, n=3):
        """The nearest broader concepts (no guide terms), e.g. ['containers', 'baskets']."""
        out, p = [], self.aat.get(c, {}).get("p")
        while p in self.aat and self.aat[p]["t"] != "HierarchyName" and len(out) < n:
            if self.aat[p]["t"] == "Concept":
                out.append(self.aat[p].get("en", ""))
            p = self.aat[p]["p"]
        return out[::-1]

    def is_within(self, c, target):
        """Is concept c the AAT target or a narrower (more specific) concept of it? NMVW terms without an AAT
        match count via their nearest broader term that has one."""
        if self.is_nmvw(c):
            c = self.nmvw_anc.get(c)
        seen = 0
        while c in self.aat and seen < 30:
            if c == target:
                return True
            c, seen = self.aat[c]["p"], seen + 1
        return False

    # -------------------------------------------------------------- zero-shot candidates
    def candidates(self, variant="ethno"):
        """Concepts to rank against a photo.
        ethno = the AAT concepts that the NMVW thesaurus uses, AAT-Deutsch translates or the GND links (the ones in
                use in an ethnographic museum or in German-speaking collections), plus the NMVW object terms with an
                English label but no AAT match («tweelingbeelden» – twin sculptures): the suggestions on the pages;
        de    = only the AAT concepts with a German label (AAT-Deutsch or the linked GND heading), for comparison;
        all   = every AAT concept of the four object hierarchies;
        nmvw  = the AAT concepts the NMVW thesaurus uses."""
        C = [c for c, x in self.aat.items() if x["t"] == "Concept" and x.get("en")]
        if variant == "de":
            return sorted(c for c in C if self.label_de(c))
        if variant == "all":
            return sorted(C)
        if variant == "nmvw":
            return sorted(c for c in C if self.aat[c].get("nmvw"))
        if variant == "ethno":
            out = [c for c in C if self.aat[c].get("nmvw") or self.aat[c].get("de") or self.aat[c].get("gnd")]
            return sorted(out) + sorted(n for n, x in self.nmvw.items() if not x["aat"] and x["en"])
        raise ValueError(variant)

    def prompt_label(self, c, qualifier=True):
        """English label for the SigLIP 2 prompt: the singular AAT term ('basket (container)'); NMVW: first English label."""
        if self.is_nmvw(c):
            lab = norm_en(self.nmvw[c]["en"][0]) if self.nmvw[c]["en"] else self.nmvw[c]["nl"]
            q = re.search(r"\(.*?\)", self.nmvw[c]["en"][0]) if self.nmvw[c]["en"] else None
            return lab + (f" {q.group(0)}" if q and qualifier else "")
        lab = self.aat[c].get("en1") or self.aat[c]["en"]
        return lab if qualifier else base(lab)


def translate_phrases(phrases, cache_path, model="Helsinki-NLP/opus-mt-de-en"):
    """German phrases -> English (cached; CPU, 4 threads). For the Trachsler class titles, which are phrases
    («Vorratsbehältnisse aus Korbgeflecht»), so no context frame as for the single VMZ terms."""
    cache_path = Path(cache_path)
    tr = json.load(open(cache_path, encoding="utf-8")) if cache_path.exists() else {}
    todo = sorted({p for p in phrases if p and p not in tr})
    if todo:
        import torch
        from transformers import MarianMTModel, MarianTokenizer
        torch.set_num_threads(4)
        tok = MarianTokenizer.from_pretrained(model)
        mt = MarianMTModel.from_pretrained(model).eval()
        for k in range(0, len(todo), 48):
            xs = todo[k:k + 48]
            with torch.no_grad():
                b = tok(xs, return_tensors="pt", padding=True, truncation=True, max_length=96)
                out = tok.batch_decode(mt.generate(**b, num_beams=4, max_new_tokens=64), skip_special_tokens=True)
            tr.update(zip(xs, (o.strip(" .") for o in out)))
        json.dump(tr, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
        print(f"translated {len(todo)} phrases")
    return tr


def trachsler_text(x, n_ex=2):
    """Class title plus the first examples: 'Schlagtrommeln (Kesseltrommeln, Kesselpauken)'."""
    main, _, ex = x["de"].partition("(")
    exs = [e.strip(' )"') for e in re.split(r"[,;]", ex) if e.strip(' )"') and "vgl" not in e][:n_ex]
    return main.strip(" ,") + (f" ({', '.join(exs)})" if exs else "")


EN_TEMPLATE = "a photo of a {}, an ethnographic museum object"        # the prompt of suggest_vmz.py
SUP_SHARE, POS_SHARE = 0.02, 0.10      # top 2 % of the candidates = supported by the photo, top 10 % = possible


def mean_sim(X, T, chunk=4096):
    """Mean similarity of each text (row of T) over all images X, in chunks."""
    return sum((X[s:s + chunk] @ T.T).sum(0) for s in range(0, len(X), chunk)) / len(X)


class TextCache:
    """SigLIP 2 text embeddings, cached per model in FOLDER/text_<model>.npy (+ .json with the texts). Only texts
    not yet in the cache are embedded; the model is loaded when first needed."""

    def __init__(self, model, folder, emb=None):
        """emb: an Embedder of `model` that is already loaded (the lists have one), else loaded when needed."""
        self.model, self.folder, self.emb = model, Path(folder), emb
        self.f_vec, self.f_txt = self.folder / f"text_{model}.npy", self.folder / f"text_{model}.json"
        self.texts = json.load(open(self.f_txt, encoding="utf-8")) if self.f_txt.exists() else []
        self.vecs = np.load(self.f_vec) if self.texts else None
        self.pos = {t: k for k, t in enumerate(self.texts)}

    def add(self, texts, vecs):
        new = [(t, k) for k, t in enumerate(texts) if t not in self.pos]
        for t, _ in new:
            self.pos[t] = len(self.texts)
            self.texts.append(t)
        if new:
            V = vecs[[k for _, k in new]]
            self.vecs = V if self.vecs is None else np.vstack([self.vecs, V])
            np.save(self.f_vec, self.vecs)
            json.dump(self.texts, open(self.f_txt, "w", encoding="utf-8"), ensure_ascii=False)

    def __call__(self, texts, tag=""):
        todo = list(dict.fromkeys(t for t in texts if t not in self.pos))
        if todo:
            if self.emb is None:
                from models import Embedder            # torch only when something is missing
                self.emb = Embedder(self.model)
            self.add(todo, self.emb.texts(todo))
            print(f"embedded {len(todo)} new texts ({tag})")
        return self.vecs[[self.pos[t] for t in texts]]


class Suggester:
    """Zero-shot suggestions from the external vocabularies for a photo, the same method as for the VMZ vocabulary.

    All candidates (AAT object concepts and NMVW terms without AAT match) are embedded once; `texts(list, tag)` returns
    (cached) SigLIP 2 text embeddings. Suggestions and ranks use the candidate set `variant` («ethno»). The photo is
    compared with the English label, which SigLIP 2 understands far better; the pages show the German label where
    AAT-Deutsch or the GND has one, else the English one. Hubness correction: minus half of each text's mean similarity over `images` (all
    photos). `mt`: German -> English (the translation cache of the VMZ terms), one route from a German name term to an
    AAT concept."""

    def __init__(self, v, texts, images, mt, cache_dir, variant="ethno", template=EN_TEMPLATE):
        self.v, self.mt = v, mt
        nmvw_only = sorted(n for n, x in v.nmvw.items() if not x["aat"] and x["en"])
        self.cand = v.candidates("all") + nmvw_only
        self.pos = {c: k for k, c in enumerate(self.cand)}
        self.T = texts([template.format(v.prompt_label(c)) for c in self.cand], "ext")
        self.b = 0.5 * mean_sim(images, self.T)
        self.sub = np.array([self.pos[c] for c in v.candidates(variant)])
        self.n = len(self.sub)
        self.sup, self.possible = round(SUP_SHARE * self.n), round(POS_SHARE * self.n)
        self.tra_ids = sorted(v.tra)
        self.tra_pos = {t: k for k, t in enumerate(self.tra_ids)}
        tra_en = translate_phrases([trachsler_text(v.tra[t]) for t in self.tra_ids], Path(cache_dir) / "trachsler_en.json")
        self.T_tra = texts([template.format(tra_en[trachsler_text(v.tra[t])]) for t in self.tra_ids], "trachsler")
        self.b_tra = 0.5 * mean_sim(images, self.T_tra)

    def status(self, rank):
        return "sup" if rank <= self.sup else "pos" if rank <= self.possible else "no"

    def trachsler(self, labels, s_tra):
        """Trachsler class for German labels: the classes whose title names them (else their examples); the photo
        picks among them («Korb» on a carrying basket -> 5.200.02 Essenstragkörbe)."""
        sc = self.v.trachsler_scores(*[x for x in labels if x])
        cands = [t for t in sc if sc[t] >= 3] or [t for t in sc if sc[t] >= 1]
        return max(cands, key=lambda t: s_tra[self.tra_pos[t]]) if cands else None

    def card(self, c, s_tra, gnd=None, tra_labels=None):
        """JSON-ready display data of a concept: the German label and where it comes from (de_src: 'aat' = AAT-Deutsch,
        'gnd' = GND heading; '' = none, the pages then show the English label), the English label, AAT id, GND/NMVW
        [id, label], Trachsler [id, notation, path], broader concepts ('up')."""
        v = self.v
        d = v.concept(c)
        g = gnd if gnd else d["gnd"][:1]
        de, de_src = d["de"], ("aat" if v.aat.get(c, {}).get("de") else "gnd") if d["de"] else ""
        if not de and g:
            de, de_src = g[0][1], "gnd"
        if tra_labels is None:
            tra_labels = [de] + v.aat.get(c, {}).get("de_alt", [])[:3] if de else []
        t = self.trachsler(tra_labels, s_tra) if tra_labels else None
        return {"key": c, "de": de, "de_src": de_src, "en": d["en"], "aat": d["aat"],
                "gnd": list(g[0]) if g else None, "nmvw": list(d["nmvw"][0]) if d["nmvw"] else None,
                "tra": [t, v.tra[t]["n"], v.trachsler_path(t)] if t else None,
                "up": " › ".join(d.get("path") or ([d["broader"]] if d.get("broader") else []))}

    def analyse(self, e, terms, k=6):
        """For one photo (image embedding e) and the terms of its current name [(term, mark)]:
        the k best concepts, and per name term its concept (the photo picks among the senses), the concept's rank
        among the candidates and status (sup/pos/no), its GND heading; route 'head' = only the end of the word
        («Holzmaske» -> Maske)."""
        v = self.v
        s, s_tra = e @ self.T.T - self.b, e @ self.T_tra.T - self.b_tra
        ss = s[self.sub]
        top = np.argpartition(-ss, k)[:k]
        top = top[np.argsort(-ss[top])]
        sugg = [self.card(self.cand[self.sub[j]], s_tra) for j in top]
        named = []
        for n_t, (t, mark) in enumerate(terms):
            gnd = [[g, v.gnd[g]["de"]] for g in v.gnd_de(t)[:1]]
            item = {"term": t, "mark": mark, "route": "", "gnd": gnd[0] if gnd else None,
                    "rank": None, "status": "na", "card": None, "tra": None, "material": None}
            # a material, not a type: «Figur; Ton», «Spitze, Stein». Hypotheses («Behälter (Mörser?)») mostly name
            # types, so for them only a German AAT material label counts, not the translation (Mörser -> mortar)
            mat = (v.material(t, self.mt.get(t)) if not mark else v.material(t)) if n_t else None
            if mat:
                item["material"] = [mat, v.mat[mat]["de"] or t, v.mat[mat]["en"]]
                named.append(item)
                continue
            ids, route = v.senses(t, self.mt.get(t))
            ids = [c for c in ids if c in self.pos]
            item["route"] = route
            best = max(ids, key=lambda c: s[self.pos[c]]) if ids else None
            rank = 1 + int((ss > s[self.pos[best]]).sum()) if ids else None
            # found only through the English translation (homonyms: «Hund» -> dog, a woodworking clamp): shown
            # only when the photo supports it
            if ids and (route != "mt" or self.status(rank) == "sup"):
                item.update(rank=rank, status=self.status(rank),
                            card=self.card(best, s_tra, gnd=gnd or None, tra_labels=[t]))
            else:
                tra = self.trachsler([t], s_tra)
                item["tra"] = [tra, v.tra[tra]["n"], v.trachsler_path(tra)] if tra else None
            named.append(item)
        return sugg, named


def card_links(card, esc):
    """HTML links of a concept card: AAT · GND · NMVW · Trachsler n.nnn (titles name the concept in each)."""
    def a(url, text, title):
        return f'<a href="{esc(url)}" target="_blank" rel="noopener" title="{esc(title)}">{esc(text)}</a>'
    out = []
    if card.get("aat"):
        out.append(a(link("aat", card["aat"]), "AAT", f"Getty AAT {card['aat']}: {card['en']}"
                     + (f" (unter: {card['up']})" if card.get("up") else "")))
    if card.get("gnd"):
        out.append(a(link("gnd", card["gnd"][0]), "GND", f"GND {card['gnd'][0]}: {card['gnd'][1]}"))
    if card.get("nmvw"):
        out.append(a(link("nmvw", card["nmvw"][0]), "NMVW", f"NMVW-Thesaurus: {card['nmvw'][1]}"
                     + (f" (ohne AAT-Entsprechung, breiter: {card['up']})" if not card.get("aat") and card.get("up") else "")))
    if card.get("tra"):
        out.append(a(link("trachsler", card["tra"][0]), f"Trachsler {card['tra'][1]}", card["tra"][2]))
    return " · ".join(out)


def card_text(card):
    """Plain text of a concept for the Excel file: 'Korb (AAT 300194498, GND 4165298-8, NMVW termmaster…, Trachsler
    5.200.02)'; English labels marked «engl.»."""
    ids = ([f"AAT {card['aat']}"] if card.get("aat") else []) + ([f"GND {card['gnd'][0]}"] if card.get("gnd") else []) \
        + ([f"NMVW {card['nmvw'][0]}"] if card.get("nmvw") else []) \
        + ([f"Trachsler {card['tra'][1]}"] if card.get("tra") else [])
    return f"{card['de'] or card['en'] + ' (engl.)'} ({', '.join(ids)})"


def material_html(item, esc, pre=""):
    """Chip for a material in the name («Ton» -> Material: Ton, AAT)."""
    c, de, en = item["material"]
    a = (f'<a href="{esc(link("aat", c))}" target="_blank" rel="noopener" title="Getty AAT {c}: {esc(en)}">AAT</a>')
    return (f'<span class="chip vc">{pre}<span class="tag">Material</span> <span class="lab">{esc(de)}</span>'
            f'<span class="src">{a}</span></span>')


def card_html(card, esc, cls="", pre="", note="", title=""):
    """A chip: the German label (AAT-Deutsch or GND), else the English one marked «engl.»; then the source links
    (the English AAT label is also in the tooltip of the AAT link)."""
    if not card.get("de"):
        note = ('<span class="tag" title="keine deutsche Bezeichnung in AAT-Deutsch oder der GND">engl.</span>'
                + note)
    links = card_links(card, esc)
    return (f'<span class="chip vc {cls}"' + (f' title="{esc(title)}"' if title else "") + f'>{pre}'
            f'<span class="lab">{esc(card["de"] or card["en"])}</span>' + note
            + (f'<span class="src">{links}</span>' if links else "") + "</span>")


def name_term_html(x, esc, n_cand):
    """Chip for a term of the current name (an item of Suggester.analyse): its concept, coloured by the photo's
    support (rank in the tooltip), or a material, or «kein Konzept gefunden» with the GND heading / Trachsler class."""
    pre = f'<span class="arr">{esc(x["term"])}{" " + x["mark"] if x["mark"] else ""} →</span> '
    if x["material"]:
        return material_html(x, esc, pre)
    if x["card"]:
        note = ('<span class="tag" title="nur das Wortende hat ein Konzept">Oberbegriff</span>'
                if x["route"] == "head" else "")
        return card_html(x["card"], esc, cls=x["status"] if x["status"] in ("sup", "pos") else "", pre=pre, note=note,
                         title=f"Rang {x['rank']} von {n_cand} Konzepten für dieses Foto")
    links = card_links({"gnd": x["gnd"], "tra": x["tra"]}, esc)
    return (f'<span class="chip vc">{pre}<span class="tag">kein Konzept gefunden</span>'
            + (f'<span class="src">{links}</span>' if links else "") + "</span>")


VOCAB_CREDIT = ("Begriffe: Art & Architecture Thesaurus® (AAT) des J. Paul Getty Trust (ODC-By 1.0), mit AAT-Deutsch; "
                "Gemeinsame Normdatei (GND) der Deutschen Nationalbibliothek (CC0); Thesaurus des Nationaal Museum van "
                "Wereldculturen, heute Wereldmuseum (CC0); Thesaurus Trachsler des Verbands der Museen der Schweiz "
                "(nur Notation, Klassenname und Link); Paare AAT–GND aus Wikidata (CC0).")
VOCAB_CSS = """.vc .src{font-size:11px;color:var(--mut);margin-left:6px} .vc .src a{color:var(--mut)}
.vc .src a:hover{color:var(--fg)} .vc .arr{color:var(--mut)} .vc .lab{font-weight:600}
.vc .tag{display:inline-block;font-size:11px;border:1px solid var(--line);border-radius:6px;padding:0 6px;margin-left:6px;color:var(--mut)}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="folder for raw downloads (OUT/raw) and vocab_external.json")
    ap.add_argument("--refresh", action="store_true", help="download the sources again")
    a = ap.parse_args()
    out = Path(a.out)
    fetch_all(out / "raw", a.refresh)
    v = build(out / "raw")
    json.dump(v, open(out / "vocab_external.json", "w", encoding="utf-8"), ensure_ascii=False)
    aat = v["aat"]
    conc = [c for c, x in aat.items() if x["t"] == "Concept"]
    print(f"AAT: {len(conc)} concepts in {len(AAT_HIER)} hierarchies, German label {sum(bool(aat[c].get('de')) for c in conc)}, "
          f"linked NMVW {sum(bool(aat[c].get('nmvw')) for c in conc)}, GND {sum(bool(aat[c].get('gnd')) for c in conc)}")
    for h, name in AAT_HIER.items():
        print(f"  {name}: {sum(aat[c]['h'] == h for c in conc)}")
    nm = v["nmvw"]
    print(f"NMVW object terms: {len(nm)}, with AAT match {sum(bool(x['aat']) for x in nm.values())}, "
          f"with English label {sum(bool(x['en']) for x in nm.values())}")
    print(f"GND subject headings: {len(v['gnd'])}; Trachsler classes: {len(v['trachsler'])}")
    print(f"wrote {out / 'vocab_external.json'} ({(out / 'vocab_external.json').stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
