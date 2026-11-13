"""All openly available images of one holding museum in «Mapping Philippine Material Culture» (open Omeka API).

Default: Museum der Kulturen Basel (MKB, Omeka collection 462, ~172 objects); --collection 275 = Pitt Rivers
Museum (~181 objects; the PRM's own online database needs an API key of its website and is not used).
For the MKB, only these objects have open image links: «Sammlung Europa» on data.bs.ch (73,733 records,
CC BY 4.0) has no images and is used as a text source (suggest_vmz.py); the MKB online collection has no
documented bulk interface.

Records get source "phil" (same database; holder = title of the collection); known ids are skipped.

Usage: python harvest_mkb.py --out DATA_DIR [--collection 462] [--stage FILE]
       (--stage: write the records there instead of appending them to records.jsonl)
"""
import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from harvest import PHIL, get_json, phil_collections, save_image
from harvest_extra import phil_item_record

MKB_COLLECTION = 462


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--collection", type=int, default=MKB_COLLECTION, help="Omeka collection id (462 MKB, 275 PRM)")
    ap.add_argument("--stage", help="write the new records to this file (append it to records.jsonl later)")
    a = ap.parse_args()
    data = Path(a.out)
    recs = [json.loads(l) for l in open(data / "records.jsonl", encoding="utf-8")]
    known = {r["id"] for r in recs}
    colls = phil_collections()
    items, page = [], 1
    while True:
        batch = get_json(f"{PHIL}/items", params={"collection": a.collection, "page": page}, delay=0.3) or []
        items += batch
        if len(batch) < 50:
            break
        page += 1
    todo = [it for it in items if f"phil_{it['id']}" not in known and it.get("files", {}).get("count", 0) > 0]
    print(f"collection {a.collection}: {len(items)} items, {len(items) - len(todo)} already known or without image")
    with ThreadPoolExecutor(3) as ex:
        new = [r for r in ex.map(lambda it: phil_item_record(it, colls, "phil"), todo) if r]

    def dl(r):
        r["img"] = f"img/{r['id']}.jpg"
        return r if save_image(r["image_url"], data / r["img"]) else None

    with ThreadPoolExecutor(3) as ex:
        added = [r for r in ex.map(dl, new) if r]
    target = Path(a.stage) if a.stage else data / "records.jsonl"
    with open(target, "a", encoding="utf-8") as f:
        for r in added:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"added {len(added)} objects -> {target}")


if __name__ == "__main__":
    main()
