"""Add to an existing DATA_DIR (incremental, only new records are fetched):

  - UZH objects: the 17 objects of the Ethnographic Museum UZH in «Mapping Philippine Material
    Culture» (Omeka collection 439) -> source "uzh" (these are the test queries)
  - Museum Rietberg, objects from the Hans Himmelheber archive (Open Data Zürich, also on opendata.swiss, CC BY-SA;
    German titles + English keywords + photo links) -> source "mrz"
  - more random pages of «Mapping Philippine Material Culture» -> source "phil"

Usage: python harvest_extra.py --out DATA_DIR [--phil-pages 26] [--rietberg 932]
"""
import argparse
import csv
import io
import json
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from harvest import PHIL, get_json, phil_collections, phil_holder, save_image, sess

UZH_COLLECTION = 439
RIETBERG_CSV = ("https://data.stadt-zuerich.ch/dataset/mrz_himmelheber_objekte/download/"
                "mrz_himmelheber_objekte.csv")


def phil_item_record(it, colls, source):
    et = {e["element"]["name"]: e["text"] for e in it.get("element_texts", [])}
    files = get_json(f"{PHIL}/files?item={it['id']}", delay=0.25) or []
    imgs = [f for f in files if (f.get("mime_type") or "").startswith("image/")]
    if not imgs:
        return None
    return {
        "source": source,
        "id": f"{source}_{it['id']}",
        "name": (et.get("Title") or "").strip(),
        "title": (et.get("Title") or "").strip(),
        "inv": (et.get("Identifier") or "").strip(),
        "culture": (et.get("Origin") or et.get("Spatial Coverage") or "").strip(),
        "holder": phil_holder(it, et, colls),
        "desc": (et.get("Description") or "")[:700],
        "url": f"https://philippinestudies.uk/mapping/items/show/{it['id']}",
        "image_url": imgs[0]["file_urls"].get("fullsize") or imgs[0]["file_urls"].get("original"),
        "licence": (et.get("Rights") or "unknown (rights of holding museum)").strip()[:120],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--phil-pages", type=int, default=26)
    ap.add_argument("--rietberg", type=int, default=932)
    a = ap.parse_args()
    out = Path(a.out)
    recs = [json.loads(l) for l in open(out / "records.jsonl", encoding="utf-8")]
    known = {r["id"] for r in recs}
    colls = phil_collections()
    new = []

    # 1) UZH objects (queries)
    uzh_items = get_json(f"{PHIL}/items", params={"collection": UZH_COLLECTION}) or []
    with ThreadPoolExecutor(3) as ex:
        new += [r for r in ex.map(lambda it: phil_item_record(it, colls, "uzh"), uzh_items) if r]
    print(f"[uzh] {len(new)} objects")

    # 2) more random Phil pages (other museums), skipping known items and the UZH collection
    first = sess().get(f"{PHIL}/items?page=1", timeout=30)
    last_page = (int(first.headers.get("Omeka-Total-Results", "0")) + 49) // 50
    rnd = random.Random(2026)
    pages = sorted(rnd.sample(range(1, last_page + 1), a.phil_pages))
    items = []
    for p in pages:
        for it in get_json(f"{PHIL}/items?page={p}", delay=0.3) or []:
            if (it.get("files", {}).get("count", 0) > 0 and f"phil_{it['id']}" not in known
                    and (it.get("collection") or {}).get("id") != UZH_COLLECTION):
                items.append(it)
    with ThreadPoolExecutor(3) as ex:
        extra = [r for r in ex.map(lambda it: phil_item_record(it, colls, "phil"), items) if r]
    print(f"[phil] +{len(extra)} objects from pages {pages}")
    new += extra

    # 3) Museum Rietberg (Open Data Zürich, CC BY-SA)
    rows = list(csv.DictReader(io.StringIO(sess().get(RIETBERG_CSV, timeout=60).content.decode("utf-8"))))
    rows = [r for r in rows if r["Link_to_Foto"].startswith("http") and f"mrz_{r['Inv_Nr']}" not in known]
    rows = rnd.sample(rows, min(a.rietberg, len(rows)))
    for r in rows:
        new.append({
            "source": "mrz",
            "id": f"mrz_{r['Inv_Nr']}",
            "name": r["Titel"].strip(),
            "title": r["Titel"].strip(),
            "inv": r["Inv_Nr"],
            "culture": r.get("Stil_Kultur_NEU") or r.get("Kultur_ALT") or "",
            "holder": "Museum Rietberg",
            "desc": f"Schlagworte: {r.get('Schlagworte', '')}; Material: {r.get('Material', '')}",
            "url": f"https://rietberg.ch/sammlungen/{r['Inv_Nr'].lower().replace('.', '-')}",
            "image_url": r["Link_to_Foto"],
            "licence": "CC BY-SA (Museum Rietberg, Open Data Zürich)",
        })
    print(f"[mrz] {len(rows)} objects")

    def dl(r):
        p = out / "img" / f"{r['id'].replace('/', '_')}.jpg"
        if save_image(r["image_url"], p):
            r["img"] = str(p.relative_to(out))
            return r
        return None

    with ThreadPoolExecutor(6) as ex:
        new = [r for r in ex.map(dl, new) if r]
    with open(out / "records.jsonl", "a", encoding="utf-8") as f:
        for r in new:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    by = {}
    for r in recs + new:
        by[r["source"]] = by.get(r["source"], 0) + 1
    print("added", len(new), "-> total", len(recs) + len(new), by)


if __name__ == "__main__":
    main()
