"""Fetch place and people names of the museum-digital records (for the geographic layer).

The object list of museum-digital has no places; the object record (/json/object/<id>) has events with place
names (+ coordinates) and people / ethnic groups. Only writes DATA_DIR/md_detail_cache.json (resumable);
suggest_vmz.py uses it as "culture" of the "md" records. records.jsonl is not touched. Polite: 3 parallel.

Usage: python enrich_md_places.py --data DATA_DIR
"""
import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from harvest import get_json


def places_people(o):
    places, people = [], []
    for e in o.get("object_events") or []:
        p = e.get("place") if isinstance(e.get("place"), dict) else {}
        if p.get("place_name"):
            places.append(p["place_name"])
        q = e.get("people") if isinstance(e.get("people"), dict) else {}
        if q.get("people_name"):
            people.append(q["people_name"])
    for p in o.get("object_relation_places") or []:
        if isinstance(p, dict) and p.get("place_name"):
            places.append(p["place_name"])
    return list(dict.fromkeys(places)), list(dict.fromkeys(people))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    a = ap.parse_args()
    data = Path(a.data)
    recs = [json.loads(l) for l in open(data / "records.jsonl", encoding="utf-8")]
    cache_file = data / "md_detail_cache.json"
    cache = json.load(open(cache_file, encoding="utf-8")) if cache_file.exists() else {}
    todo = [r for r in recs if r["source"] == "md" and r["id"] not in cache]

    def fetch(r):
        base, oid = r["url"].rsplit("/object/", 1)
        time.sleep(0.2)
        o = get_json(f"{base}/json/object/{oid}") or {}
        return r["id"], places_people(o) if isinstance(o, dict) else ([], [])

    with ThreadPoolExecutor(3) as ex:
        for k, (rid, val) in enumerate(ex.map(fetch, todo), 1):
            cache[rid] = val
            if k % 500 == 0:
                json.dump(cache, open(cache_file, "w", encoding="utf-8"), ensure_ascii=False)
                print(f"  {k}/{len(todo)}", flush=True)
    json.dump(cache, open(cache_file, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"cached place/people data for {len(cache)} md objects (suggest_vmz.py reads the cache)")

if __name__ == "__main__":
    main()
