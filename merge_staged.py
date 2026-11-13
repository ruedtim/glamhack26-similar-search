"""Merge records + images staged by a separate harvester (e.g. data/mkb_online, data/prm) into the data folder.

Copies the images (nothing is deleted), appends records whose id is not yet in records.jsonl, and marks them
with "publish_image": false when their images may be used for the similarity computation but not shown
publicly (PRM: online publication needs a PRM licence). The public pages then show these objects only with name,
museum and link. (MKB images were approved for publication by the MKB on 13.11.2026; suggest_vmz.can_publish.)

Usage: python merge_staged.py --data DATA_DIR --staged data/mkb_online --records records_mkb_online.jsonl --no-publish-images
"""
import argparse
import json
import shutil
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--staged", required=True, help="folder with the staged records file and img/")
    ap.add_argument("--records", required=True, help="name of the records file inside --staged")
    ap.add_argument("--no-publish-images", action="store_true")
    a = ap.parse_args()
    data, staged = Path(a.data), Path(a.staged)
    known = {json.loads(l)["id"] for l in open(data / "records.jsonl", encoding="utf-8")}
    added, missing_img = [], 0
    for line in open(staged / a.records, encoding="utf-8"):
        r = json.loads(line)
        if r["id"] in known or not r.get("img"):
            continue
        src = staged / r["img"]
        if not src.exists():
            missing_img += 1
            continue
        dst = data / "img" / src.name
        if not dst.exists():
            shutil.copy2(src, dst)
        r["img"] = f"img/{src.name}"
        if a.no_publish_images:
            r["publish_image"] = False
        known.add(r["id"])
        added.append(r)
    with open(data / "records.jsonl", "a", encoding="utf-8") as f:
        for r in added:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"merged {len(added)} records from {staged / a.records} (images missing: {missing_img}); "
          f"publish_image={'false' if a.no_publish_images else 'unchanged'}")


if __name__ == "__main__":
    main()
