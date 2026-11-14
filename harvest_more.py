"""Extend the reference set with more open collections (CC0, documented open endpoints only).

  - Cleveland Museum of Art Open Access API: Indian and Southeast Asian Art (incl. Tibet, Nepal),
    Oceania, all of African Art and Art of the Americas, Islamic Art, and random samples of Korean,
    Chinese, Japanese Art and Textiles
  - Smithsonian Open Access, bulk metadata on the AWS Registry of Open Data (only media marked CC0):
    Freer|Sackler (fsg, Asian art), National Museum of African Art (nmafa),
    National Museum of the American Indian (nmai)
  Not used: NMNH Anthropology (the open dump has no CC0 images), Rietberg «Kamerun» (open data has no
  image links; photos only on the website).

Appends new records to DATA_DIR/records.jsonl (known ids are skipped) and downloads the images
(max 448 px). Polite: 4 parallel requests per source.

Usage: python harvest_more.py --out DATA_DIR
"""
import argparse
import json
import random
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from harvest import CMA, get_json, plain, save_image, sess

SI = "https://smithsonian-open-access.s3-us-west-2.amazonaws.com/metadata/edan"
SI_UNITS = {"fsg": "Smithsonian – Freer Gallery of Art and Arthur M. Sackler Gallery",
            "nmafa": "Smithsonian – National Museum of African Art",
            "nmai": "Smithsonian – National Museum of the American Indian"}
CMA_PLAN = [  # department, max. number of objects (None = all)
    ("Indian and Southeast Asian Art", None), ("Oceania", None), ("African Art", None),
    ("Art of the Americas", None), ("Islamic Art", None), ("Korean Art", 400), ("Chinese Art", 1000),
    ("Japanese Art", 700), ("Textiles", 700)]


def cma_department(dept, n_max, rng):
    rows, skip = [], 0
    while True:
        d = get_json(CMA, params={"department": dept, "has_image": 1, "cc0": 1, "limit": 1000, "skip": skip})
        if not d or not d.get("data"):
            break
        rows += d["data"]
        skip += 1000
        if skip >= d["info"]["total"]:
            break
    if n_max and len(rows) > n_max:
        rows = rng.sample(rows, n_max)
    out = []
    for a in rows:
        web = (a.get("images") or {}).get("web") or {}
        if not web.get("url"):
            continue
        out.append(dict(source="cma", id=f"cma_{a['id']}", name=a.get("title") or "", title=a.get("title") or "",
                        culture="; ".join(a.get("culture") or []), holder="Cleveland Museum of Art",
                        desc=f"{a.get('type') or ''} | {dept}", url=a.get("url"), image_url=web["url"],
                        licence="CC0"))
    print(f"[cma] {dept}: {len(out)} of {len(rows)}")
    return out


def si_unit(unit):
    idx = sess().get(f"{SI}/{unit}/index.txt", timeout=60).text.split()

    def fetch(u):
        for _ in range(3):
            try:
                r = sess().get(u, timeout=60)
                if r.status_code == 200:
                    # UTF-8, but the files declare no charset: r.text would decode them as Latin-1 (mojibake)
                    return r.content.decode("utf-8", errors="replace")
            except Exception:
                pass
        return ""

    out = []
    with ThreadPoolExecutor(4) as ex:
        for txt in ex.map(fetch, idx):
            for line in txt.splitlines():
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                c = r.get("content", {})
                dn, ix, ft = c.get("descriptiveNonRepeating", {}), c.get("indexedStructured", {}), c.get("freetext", {})
                media = (dn.get("online_media") or {}).get("media") or []
                img = next((m for m in media if m.get("type") == "Images"
                            and (m.get("usage") or {}).get("access") == "CC0"), None)
                if not img or not img.get("content"):
                    continue
                title = plain((dn.get("title") or {}).get("content"))
                culture = "; ".join(ix.get("culture", [])[:2]) or "; ".join(ix.get("place", [])[:2])
                otype = "; ".join(ix.get("object_type", [])[:2])
                out.append(dict(source="si", id="si_" + re.sub(r"[^\w.-]+", "_", r.get("id", "")), name=title,
                                title=title, culture=culture, holder=SI_UNITS[unit], desc=otype,
                                url=dn.get("record_link") or "", image_url=img["content"] + "&max=448",
                                licence="CC0"))
    print(f"[si] {unit}: {len(out)} records with CC0 images ({len(idx)} metadata files)")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=2026)
    a = ap.parse_args()
    data = Path(a.out)
    rng = random.Random(a.seed)
    recs = [json.loads(l) for l in open(data / "records.jsonl", encoding="utf-8")]
    known = {r["id"] for r in recs}

    cand = []
    for dept, n in CMA_PLAN:
        cand += cma_department(dept, n, rng)
    for unit in SI_UNITS:
        cand += si_unit(unit)
    new, seen = [], set(known)
    for r in cand:
        if r["id"] not in seen and r["name"]:
            seen.add(r["id"])
            new.append(r)
    print(f"new candidates: {len(new)}")

    def dl(r):
        r["img"] = f"img/{r['id']}.jpg"
        return r if save_image(r["image_url"], data / r["img"]) else None

    added = []
    for src in ("cma", "si"):            # one host at a time, 4 parallel requests
        with ThreadPoolExecutor(4) as ex:
            added += [r for r in ex.map(dl, [r for r in new if r["source"] == src]) if r]
        print(f"[{src}] images downloaded: {sum(r['source'] == src for r in added)}")
    with open(data / "records.jsonl", "a", encoding="utf-8") as f:
        for r in added:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"added {len(added)} -> total {len(recs) + len(added)}")


if __name__ == "__main__":
    main()
