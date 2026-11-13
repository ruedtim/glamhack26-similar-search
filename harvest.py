"""Harvest a small reference set (images + object names) from open museum APIs.

Only documented, openly usable endpoints are used:
  - Mapping Philippine Material Culture (Omeka Classic REST API)  -> listed in the challenge
  - The Met Collection API (CC0, public-domain objects only) -- OFF by default (--with-met):
    in Nov 2026 its /search endpoint returned nothing for this script; not worked around.
  - Cleveland Museum of Art Open Access API (CC0 only)

Usage:
  python harvest.py --out DATA_DIR [--phil-pages 14] [--met-aaoa 500] ...

Writes DATA_DIR/records.jsonl and DATA_DIR/img/<source>_<id>.jpg (max 448 px).
"""
import argparse
import io
import json
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from PIL import Image

UA = "glam-feasibility-test/0.1 (GLAMhack 2026 research prototype)"
random.seed(42)
_local = threading.local()


def sess():
    if not hasattr(_local, "s"):
        _local.s = requests.Session()
        _local.s.headers["User-Agent"] = UA
    return _local.s


def get_json(url, delay=0.0, tries=3, **kw):
    for i in range(tries):
        try:
            r = sess().get(url, timeout=30, **kw)
            if r.status_code == 200:
                time.sleep(delay)
                return r.json()
            if r.status_code in (403, 404):
                return None
        except requests.RequestException:
            pass
        time.sleep(1.5 * (i + 1))
    return None


def save_image(url, path, max_side=448):
    if path.exists():
        return True
    try:
        r = sess().get(url, timeout=40)
        if r.status_code != 200:
            return False
        im = Image.open(io.BytesIO(r.content)).convert("RGB")
        im.thumbnail((max_side, max_side))
        im.save(path, "JPEG", quality=88)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- Philippines (Omeka)
PHIL = "https://philippinestudies.uk/mapping/api"


def phil_collections():
    """Omeka collection id -> collection title (in this database a collection = holding museum)."""
    names, page = {}, 1
    while True:
        data = get_json(f"{PHIL}/collections?page={page}", delay=0.3) or []
        for c in data:
            et = {e["element"]["name"]: e["text"] for e in c.get("element_texts", [])}
            names[c["id"]] = (et.get("Title") or "").strip()
        if len(data) < 50:
            return names
        page += 1


def phil_items(n_pages):
    first = sess().get(f"{PHIL}/items?page=1", timeout=30)
    total = int(first.headers.get("Omeka-Total-Results", "0"))
    last_page = max(1, (total + 49) // 50)
    pages = sorted(random.sample(range(1, last_page + 1), min(n_pages, last_page)))
    print(f"[phil] total={total}, sampling pages {pages}")
    items = []
    for p in pages:
        data = get_json(f"{PHIL}/items?page={p}", delay=0.3) or []
        items += [it for it in data if it.get("files", {}).get("count", 0) > 0]
    return items


def phil_holder(it, et, colls):
    cid = (it.get("collection") or {}).get("id")
    return (et.get("Location") or "").strip() or colls.get(cid, "")


def phil_records(n_pages):
    items = phil_items(n_pages)
    colls = phil_collections()

    def one(it):
        et = {e["element"]["name"]: e["text"] for e in it.get("element_texts", [])}
        files = get_json(f"{PHIL}/files?item={it['id']}", delay=0.25) or []
        imgs = [f for f in files if (f.get("mime_type") or "").startswith("image/")]
        if not imgs:
            return None
        return {
            "source": "phil",
            "id": f"phil_{it['id']}",
            "name": (et.get("Title") or "").strip(),
            "title": (et.get("Title") or "").strip(),
            "culture": (et.get("Spatial Coverage") or et.get("Coverage") or "").strip(),
            "holder": phil_holder(it, et, colls),
            "desc": (et.get("Description") or "")[:300],
            "url": f"https://philippinestudies.uk/mapping/items/show/{it['id']}",
            "image_url": imgs[0]["file_urls"].get("fullsize") or imgs[0]["file_urls"].get("original"),
            "licence": "unknown (rights of holding museum)",
        }

    with ThreadPoolExecutor(3) as ex:
        return [r for r in ex.map(one, items) if r]


# ---------------------------------------------------------------- The Met
MET = "https://collectionapi.metmuseum.org/public/collection/v1"


def met_ids(dept, q="*", n=None):
    d = get_json(f"{MET}/search", params={"departmentId": dept, "hasImages": "true", "q": q}) or {}
    ids = d.get("objectIDs") or []
    if n is not None and len(ids) > n:
        ids = random.sample(ids, n)
    print(f"[met] dept={dept} q={q!r}: {d.get('total')} hits -> {len(ids)}")
    return ids


def met_records(id_groups):
    ids = list(dict.fromkeys(i for g in id_groups for i in g))

    def one(oid):
        o = get_json(f"{MET}/objects/{oid}", delay=0.05)
        if not o or not o.get("isPublicDomain") or not o.get("primaryImageSmall"):
            return None
        return {
            "source": "met",
            "id": f"met_{oid}",
            "name": o.get("objectName") or "",
            "title": o.get("title") or "",
            "culture": ", ".join(x for x in [o.get("culture"), o.get("country")] if x),
            "holder": "The Met",
            "desc": o.get("classification") or "",
            "url": o.get("objectURL"),
            "image_url": o["primaryImageSmall"],
            "licence": "CC0",
        }

    with ThreadPoolExecutor(6) as ex:
        return [r for r in ex.map(one, ids) if r]


# ---------------------------------------------------------------- Cleveland
CMA = "https://openaccess-api.clevelandart.org/api/artworks/"


def cma_records(dept, limit, q=None):
    params = {"department": dept, "has_image": 1, "cc0": 1, "limit": limit}
    if q:
        params["q"] = q
    d = get_json(CMA, params=params) or {"data": []}
    out = []
    for a in d["data"]:
        web = (a.get("images") or {}).get("web") or {}
        if not web.get("url"):
            continue
        out.append({
            "source": "cma",
            "id": f"cma_{a['id']}",
            "name": a.get("title") or "",
            "title": a.get("title") or "",
            "culture": "; ".join(a.get("culture") or []),
            "holder": "Cleveland Museum of Art",
            "desc": a.get("type") or "",
            "url": a.get("url"),
            "image_url": web["url"],
            "licence": "CC0",
        })
    print(f"[cma] {dept} q={q!r}: {len(out)}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--phil-pages", type=int, default=14)
    ap.add_argument("--with-met", action="store_true")
    ap.add_argument("--met-aaoa", type=int, default=500)
    ap.add_argument("--met-instruments", type=int, default=300)
    ap.add_argument("--met-asian-figures", type=int, default=250)
    ap.add_argument("--cma-limit", type=int, default=250)
    ap.add_argument("--enrich-only", action="store_true",
                    help="only fill in the holding museum of existing Phil records (no image downloads)")
    a = ap.parse_args()
    out = Path(a.out)
    (out / "img").mkdir(parents=True, exist_ok=True)

    if a.enrich_only:
        recs = [json.loads(l) for l in open(out / "records.jsonl", encoding="utf-8")]
        colls = phil_collections()
        by_id = {}
        for it in phil_items(a.phil_pages):     # same seed -> same pages as the original harvest
            et = {e["element"]["name"]: e["text"] for e in it.get("element_texts", [])}
            by_id[f"phil_{it['id']}"] = phil_holder(it, et, colls)
        n = 0
        for r in recs:
            if r["id"] in by_id and by_id[r["id"]]:
                r["holder"], n = by_id[r["id"]], n + 1
        with open(out / "records.jsonl", "w", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"enriched {n} records; {len(colls)} collections")
        return

    recs = []
    recs += phil_records(a.phil_pages)
    if a.with_met:
        recs += met_records([
            met_ids(5, n=a.met_aaoa),                       # Arts of Africa, Oceania, Americas
            met_ids(18, n=a.met_instruments),               # Musical instruments (random)
            met_ids(18, q="zither"), met_ids(18, q="valiha"),  # make sure tube zithers exist
            met_ids(6, q="deity", n=a.met_asian_figures // 2),  # Asian Art figures
            met_ids(6, q="figure", n=a.met_asian_figures // 2),
        ])
    recs += cma_records("African Art", a.cma_limit)
    recs += cma_records("Art of the Americas", a.cma_limit // 2)
    recs += cma_records("Chinese Art", a.cma_limit // 2, q="figure")

    def dl(r):
        p = out / "img" / f"{r['id']}.jpg"
        ok = save_image(r["image_url"], p)
        if ok:
            r["img"] = str(p.relative_to(out))
        return r if ok else None

    with ThreadPoolExecutor(6) as ex:
        recs = [r for r in ex.map(dl, recs) if r]

    with open(out / "records.jsonl", "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    by = {}
    for r in recs:
        by[r["source"]] = by.get(r["source"], 0) + 1
    print("saved", len(recs), by)


if __name__ == "__main__":
    main()
