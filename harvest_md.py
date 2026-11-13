"""Reference objects with GERMAN object names from museum-digital (open JSON API, robots.txt allows /json/).

Ethnographic institutions on museum-digital:
  - Ethnologisches Museum, Staatliche Museen zu Berlin (global.museum-digital.org, instnr 583, ~77,000
    objects; images and metadata CC BY-NC-SA)
  - Übersee-Museum Bremen (nat.museum-digital.de, instnr 940 – German names there; images CC BY-SA)
  - Museum Europäischer Kulturen, Staatliche Museen zu Berlin (instnr 590, ~13,000 objects, CC BY-NC-SA):
    European folk culture, for the European objects of the VMZ (e.g. «Schnabelgeiss»)

Query terms: the most frequent type terms of the WHOLE VMZ catalogue (not the terms of the sample objects),
at most --per-term objects per term and institution. Appends records with source "md" to records.jsonl
and downloads the 500 px previews (resized to 448 px). Polite: 2 parallel searches, 3 parallel images.

Usage: python harvest_md.py --out DATA_DIR [--terms 300] [--per-term 12]
"""
import argparse
import json
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from harvest import get_json, save_image
from suggest_vmz import type_term

SOURCES = [  # instance, institution number, holder, licence of the images (checked on a sample)
    ("https://global.museum-digital.org", 583, "Ethnologisches Museum, Staatliche Museen zu Berlin", "CC BY-NC-SA"),
    ("https://nat.museum-digital.de", 940, "Übersee-Museum Bremen", "CC BY-SA"),
    ("https://global.museum-digital.org", 590, "Museum Europäischer Kulturen, Staatliche Museen zu Berlin",
     "CC BY-NC-SA"),
]
CACHE = {}


def search(base, inst, term):
    """First result page (24 objects). No results -> HTTP 404 or an error object -> []. Cached."""
    key = f"{base}|{inst}|{term}"
    if key not in CACHE:
        time.sleep(0.2)
        rows = get_json(f"{base}/json/objects", params={"s": term, "instnr": inst})
        CACHE[key] = [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
    return CACHE[key]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--terms", type=int, default=300)
    ap.add_argument("--per-term", type=int, default=12)
    a = ap.parse_args()
    data = Path(a.out)
    cat = [json.loads(l) for l in open(data / "vmz_catalog.jsonl", encoding="utf-8")]
    counts = Counter(type_term(c["name"]) for c in cat)
    terms = [t for t, _ in counts.most_common() if len(t) >= 3 and t[0].isupper()][:a.terms]
    print(f"{len(terms)} query terms, e.g. {terms[:12]}")
    recs = [json.loads(l) for l in open(data / "records.jsonl", encoding="utf-8")]
    known = {r["id"] for r in recs}
    cache_file = data / "md_search_cache.json"
    if cache_file.exists():
        CACHE.update(json.load(open(cache_file, encoding="utf-8")))

    new = {}
    for base, inst, holder, lic in SOURCES:
        host = base.split("//")[1].split(".")[0]
        with ThreadPoolExecutor(2) as ex:
            results = list(ex.map(lambda t: (t, search(base, inst, t)), terms))
        n0 = len(new)
        for term, rows in results:
            for r in [r for r in rows if r.get("image")][:a.per_term]:
                rid = f"md_{host}_{r['objekt_id']}"
                if rid in known or rid in new:
                    continue
                name = re.sub(r"^[A-Z]\d{3,}(/\d+)?[a-z]?\s+", "", r.get("objekt_name") or "").strip()  # "D13188 Korb"
                new[rid] = dict(source="md", id=rid, name=name, title=name, inv=r.get("objekt_inventarnr") or "",
                                culture="", holder=holder, desc=f"museum-digital, Suche «{term}»",
                                url=f"{base}/object/{r['objekt_id']}",
                                image_url=f"{base}/{r['image'].replace('200w_', '500w_')}", licence=lic)
        print(f"[md] {holder}: {len(new) - n0} objects with image from {len(terms)} searches")
        json.dump(CACHE, open(cache_file, "w", encoding="utf-8"), ensure_ascii=False)

    def dl(r):
        r["img"] = f"img/{r['id']}.jpg"
        return r if save_image(r["image_url"], data / r["img"]) else None

    with ThreadPoolExecutor(3) as ex:
        added = [r for r in ex.map(dl, new.values()) if r]
    with open(data / "records.jsonl", "a", encoding="utf-8") as f:
        for r in added:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"added {len(added)} -> total {len(recs) + len(added)}")


if __name__ == "__main__":
    main()
