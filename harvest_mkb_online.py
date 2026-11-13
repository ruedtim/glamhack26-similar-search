"""Reference objects of the Museum der Kulturen Basel (MKB) with images, via the open IIIF interface of PARC.

Why not onlinecollection.mkb.ch: on 13.11.2026 its search service (cc/ccConnector.asmx/search) answered every
visitor with HTTP 403 (also an ordinary search in a browser; the page says «Der Dienst ist derzeit nicht
verfügbar»). That block is not worked around. The MKB itself links «PARC – Portal for African Research Collections»
(Universität Basel) for its African collection (mkb.ch > Sammlung > Links Teilsammlungen). PARC lists ~8,300
digitised MKB records with IIIF Presentation 3 manifests and IIIF images (media server of the UB Basel).

Steps (polite: one listing request at a time, at most 3 parallel workers, small delays, UA below):
  1. listing: the JSON search endpoint the PARC portal itself calls, filter institution = MKB, digitised = ja
     (cached in OUT/parc_listing.jsonl)
  2. per record: IIIF manifest -> object name, culture, place, country, inventory number, image service
  3. image: IIIF Image API, longest side 448 px, JPEG -> OUT/img/mkb_<inventory number>.jpg

Skipped (logged with reason in OUT/skipped.jsonl, not retried): index-card scans (image id *_kk*, the MKB shows
the Karteikarte where no photo exists), items of the MKB photo collection («(F)III …»: field photos, posters;
image id _f_* / *_pos / *_neg / *_dia) and films / books (PARC type), records without image, images shared by
several records (kept once), names that point to human remains. Hidden (sensitive) objects are not in PARC at all.
Not stored: descriptions, acquisition data, supplier/donor names (Einlieferer*in).

Rights: the MKB publishes the data of its online collection under CC BY 4.0 (credit «Museum der Kulturen Basel»),
but the PARC manifests of MKB records say «In Copyright» (rightsstatements.org InC). Each record therefore keeps
the PARC statement in "licence"/"rights" and the MKB statement in "licence_note". Update 13.11.2026: an MKB
employee approved publishing the images for this project (credit «Museum der Kulturen Basel»).

Usage: python harvest_mkb_online.py [--out data/mkb_online] [--limit 200] [--workers 3]
Output: OUT/records_mkb_online.jsonl (one JSON object per line, appended; reruns resume), OUT/img/, OUT/skipped.jsonl
"""
import argparse
import io
import json
import re
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from PIL import Image

UA = "glam-feasibility-test/0.1 (GLAMhack 2026 research prototype)"
SEARCH = "https://rdv-querybuilder-afrikaportal.ub-dd-prod.ub.k8s-001.unibas.ch/v2/rdv_query/es_proxy/afrikaportal-prod_k8s/"
MANIFEST = "https://es-iiif-service.ub-dd-prod.ub.k8s-001.unibas.ch/afrikaportal/{}/manifest/"
DETAIL = "https://www.parc-portal.org/de/detail/{}"
HOLDER = "Museum der Kulturen Basel"
CREDIT = "Museum der Kulturen Basel; via PARC – Portal for African Research Collections (Universität Basel)"
LICENCE_NOTE = ("MKB: Daten der Online-Sammlung unter CC BY 4.0 (Quellennachweis «Museum der Kulturen Basel»); "
                "PARC-IIIF-Manifest: In Copyright. Bilder vor Klärung mit dem MKB nicht veröffentlichen.")
SKIP_TYPES = {"Fotografie", "Film", "Buch", "Tondokument", "Audio", "Video", "Dokument", "Archivale"}
INDEX_CARD = re.compile(r"_kk\d*($|[_-])|karteikarte", re.I)  # _kk, _kk1, _kk-verso, _kk1-verso
PHOTO_COLL = re.compile(r"^_f_|_(pos|neg|dia)\d*$", re.I)  # MKB photo collection «(F)III …»: field photos, posters
HUMAN_REMAINS = re.compile(r"schädel|skelett|mumie|schrumpfkopf|kopftrophäe|menschen(haar|knochen|zahn|zähne)"
                           r"|human remains", re.I)
PERMANENT = {"no image", "index card", "photo collection", "type", "duplicate image", "human remains",
             "no manifest canvas"}
_local = threading.local()
_lock = threading.Lock()


def sess():
    if not hasattr(_local, "s"):
        _local.s = requests.Session()
        _local.s.headers["User-Agent"] = UA
    return _local.s


def request(method, url, tries=4, delay=0.2, **kw):
    """GET/POST with retries; 404 -> None at once, 403/429/5xx -> back off. Returns the response or None."""
    for i in range(tries):
        try:
            r = sess().request(method, url, timeout=40, **kw)
            if r.status_code == 200:
                time.sleep(delay)
                return r
            if r.status_code == 404:
                return None
        except requests.RequestException:
            pass
        time.sleep(2.0 * (i + 1))
    return None


def listing(out, page=10000):
    """All digitised MKB records in PARC (search snippets), cached. One request of up to 10,000 rows (~5 MB, ~12 s):
    paging with smaller pages is not stable on this backend (all scores equal; 100er pages gave 6,620 of 8,287)."""
    cache = out / "parc_listing.jsonl"
    if cache.exists():
        return [json.loads(l) for l in open(cache, encoding="utf-8")]
    rows, start, total = {}, 0, None
    while total is None or start < total:
        body = {"query_params": {"size": page, "sort": [{"field": "_score", "order": "desc"}], "start": start,
                                 "source": []},
                "match_all": True,
                "facets": {"fct_institution": {"field": "fct_institution.keyword", "values": [{"id": HOLDER}],
                                               "operator": "OR", "order": "count", "facet_type": "basic", "size": 10},
                           "hidden_digitized": {"field": "hidden_digitized.keyword", "values": [{"id": "ja"}],
                                                "operator": "OR", "order": "count", "facet_type": "basic", "size": 10}},
                "lang": "de", "open_facets": {}, "viewer": "List"}
        r = request("POST", SEARCH, json=body, delay=0.5)
        if r is None:
            raise SystemExit(f"PARC search failed at start={start} – stop (nothing worked around)")
        d = r.json()
        total = d["hits"]
        for s in d["snippets"]:
            rows.setdefault(s["id"], s)
        print(f"  listing {min(start + page, total)}/{total}", flush=True)
        start += page
    if len(rows) < total:
        print(f"  warning: {len(rows)} unique records for {total} hits (paging order not stable?)")
    with open(cache, "w", encoding="utf-8") as f:
        for s in rows.values():
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    return list(rows.values())


def image_id(url):
    """https://media.ub.unibas.ch/mkb-010/iii-20870_kk1/iiif -> iii-20870_kk1"""
    parts = [p for p in (url or "").split("/") if p]
    return parts[-2] if len(parts) >= 2 and parts[-1] == "iiif" else (parts[-1] if parts else "")


def triage(snips, done_ids, skipped_ids):
    """Split the listing into candidates and permanent skips (without any further request)."""
    todo, skips = [], []
    seen_img = {image_id(s.get("preview_image")) for s in snips if s["id"] in done_ids}
    for s in snips:
        pid = s["id"]
        if pid in done_ids or pid in skipped_ids:
            continue
        img = image_id(s.get("preview_image"))
        reason = ("no image" if not img else
                  "index card" if INDEX_CARD.search(img) else
                  "photo collection" if PHOTO_COLL.search(img) else
                  "type" if s.get("fct_mediatype") in SKIP_TYPES else
                  "human remains" if HUMAN_REMAINS.search(s.get("title") or "") else
                  "duplicate image" if img in seen_img else None)
        if img:
            seen_img.add(img)
        if reason:
            skips.append({"parc_id": pid, "reason": reason, "type": s.get("fct_mediatype"), "img": img})
        else:
            todo.append(s)
    return todo, skips


def md_values(canvas):
    """IIIF metadata -> {German label: German value}."""
    out = {}
    for m in canvas.get("metadata") or []:
        if not isinstance(m, dict):
            continue
        lab, val = m.get("label") or {}, m.get("value") or {}
        lab = (lab.get("de") or lab.get("en") or [""])[0] if isinstance(lab, dict) else str(lab)
        val = (val.get("de") or val.get("en") or val.get("none") or []) if isinstance(val, dict) else [str(val)]
        out[lab] = " ".join(v.strip() for v in val if isinstance(v, str) and v.strip())
    return out


def clean(v):
    v = (v or "").strip()
    return "" if v.lower() in ("", "-", "(not assigned)", "unbekannt", "none") else v


def inv_slug(inv):
    return re.sub(r"[^A-Za-z0-9]+", "_", inv).strip("_")


def inv_from_image(img):
    """MKB image files are named after the inventory number: iii-1039_depot01 -> III 1039, iii-21131b_… -> III 21131b."""
    m = re.match(r"([ivx]+)-(\d+(?:\.\d+)?[a-z]?)(?=_|$)", img or "", re.I)
    return f"{m.group(1).upper()} {m.group(2)}" if m else ""


def save_image(url, path, max_side=448):
    r = request("GET", url, delay=0.1)
    if r is None:
        return False
    try:
        im = Image.open(io.BytesIO(r.content)).convert("RGB")
        if min(im.size) < 32:
            return False
        im.thumbnail((max_side, max_side))
        im.save(path, "JPEG", quality=88)
        return True
    except Exception:
        return False


def harvest_one(s, out, used_ids):
    """Manifest + image for one PARC record -> (record, None) or (None, skip dict) or (None, None) on error."""
    pid = s["id"]
    r = request("GET", MANIFEST.format(pid))
    if r is None:
        return None, None
    try:
        m = r.json()
    except ValueError:
        return None, None
    if not isinstance(m, dict):
        return None, None
    canvases = [c for c in m.get("items") or [] if isinstance(c, dict)
                and not INDEX_CARD.search((c.get("id") or "").rsplit("/", 1)[-1])]
    if not canvases:
        return None, {"parc_id": pid, "reason": "no manifest canvas"}
    c = canvases[0]
    md = md_values(c)
    try:
        service = c["items"][0]["items"][0]["body"]["service"][0]["id"].rstrip("/")
    except (KeyError, IndexError, TypeError, AttributeError):
        try:
            service = (c["thumbnail"][0]["service"][0]["id"] or "").rstrip("/")
        except (KeyError, IndexError, TypeError, AttributeError):
            service = ""
    if not service:
        return None, {"parc_id": pid, "reason": "no manifest canvas"}
    inv = clean(md.get("Inventarnummer")) or inv_from_image(service.rsplit("/", 1)[-1]) or pid
    if inv.startswith("(F)"):
        return None, {"parc_id": pid, "reason": "photo collection"}
    name = clean(md.get("Objekt Bezeichnung")) or clean(s.get("title"))
    title = clean(s.get("title")) or name
    geo = []
    for k in ("Kultur", "Ort", "Land", "Subkontinent"):
        v = clean(md.get(k))
        if v and v not in geo:
            geo.append(v)
    with _lock:
        rid = f"mkb_{inv_slug(inv)}"
        if rid in used_ids:
            rid = f"{rid}_{pid.split('_')[-1]}"
        used_ids.add(rid)
    rec = {"source": "mkb", "id": rid, "name": name, "title": title, "inv": inv, "culture": ", ".join(geo),
           "holder": HOLDER, "desc": "", "url": DETAIL.format(pid),
           "image_url": f"{service}/full/!448,448/0/default.jpg",
           "licence": "InC (PARC)", "rights": m.get("rights") or "", "licence_note": LICENCE_NOTE,
           "credit": CREDIT, "parc_id": pid, "img": f"img/{rid}.jpg"}
    if not save_image(rec["image_url"], out / rec["img"]):
        with _lock:
            used_ids.discard(rid)
        return None, None
    return rec, None


def prune(recs, skipped, out, rec_file, skip_file):
    """Apply the current skip rules to records of earlier runs (rules may have grown): drop record + image."""
    keep, drop, renamed = [], [], 0
    used = {r["id"] for r in recs}
    for r in recs:
        img = r["image_url"].split("/full/")[0].rsplit("/", 1)[-1]
        if r["inv"] == r["parc_id"] and inv_from_image(img):  # earlier runs: no «Inventarnummer» in the manifest
            rid = f"mkb_{inv_slug(inv_from_image(img))}"
            rid = rid if rid not in used else f"{rid}_{r['parc_id'].split('_')[-1]}"
            if rid not in used and (out / r["img"]).exists():
                (out / r["img"]).rename(out / f"img/{rid}.jpg")
                used.discard(r["id"])
                used.add(rid)
                r.update(id=rid, inv=inv_from_image(img), img=f"img/{rid}.jpg")
                renamed += 1
        reason = ("index card" if INDEX_CARD.search(img) else
                  "photo collection" if PHOTO_COLL.search(img) or r["inv"].startswith("(F)") else
                  "human remains" if HUMAN_REMAINS.search(f"{r['name']} {r['title']}") else None)
        if reason:
            drop.append({"parc_id": r["parc_id"], "reason": reason, "img": img})
            (out / r["img"]).unlink(missing_ok=True)
        else:
            keep.append(r)
    if drop or renamed:
        with open(rec_file, "w", encoding="utf-8") as f:
            for r in keep:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        with open(skip_file, "a", encoding="utf-8") as f:
            for x in drop:
                f.write(json.dumps(x, ensure_ascii=False) + "\n")
        print(f"earlier runs: pruned {len(drop)} records {dict(Counter(x['reason'] for x in drop))}, "
              f"{renamed} inventory numbers taken from the image file name")
    return keep, skipped + drop


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/mkb_online")
    ap.add_argument("--limit", type=int, default=0, help="process at most N new candidates (0 = all)")
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()
    out = Path(a.out)
    (out / "img").mkdir(parents=True, exist_ok=True)
    rec_file, skip_file = out / "records_mkb_online.jsonl", out / "skipped.jsonl"
    recs = [json.loads(l) for l in open(rec_file, encoding="utf-8")] if rec_file.exists() else []
    skipped = [json.loads(l) for l in open(skip_file, encoding="utf-8")] if skip_file.exists() else []
    recs, skipped = prune(recs, skipped, out, rec_file, skip_file)
    done_ids = {r["parc_id"] for r in recs}
    used_ids = {r["id"] for r in recs}
    skipped_ids = {x["parc_id"] for x in skipped if x["reason"] in PERMANENT}

    t0 = time.time()
    snips = listing(out)
    todo, skips = triage(snips, done_ids, skipped_ids)
    with open(skip_file, "a", encoding="utf-8") as f:
        for x in skips:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    print(f"PARC: {len(snips)} digitised MKB records; already done {len(done_ids)}, skipped now "
          f"{dict(Counter(x['reason'] for x in skips))}; candidates {len(todo)}", flush=True)
    if a.limit:
        todo = todo[:a.limit]

    stats, t1 = Counter(), time.time()

    def work(s):
        try:
            rec, skip = harvest_one(s, out, used_ids)
        except Exception as e:  # one odd record must not stop the run; it is retried on the next run
            print(f"  error {s['id']}: {type(e).__name__}: {e}", flush=True)
            rec, skip = None, None
        with _lock:
            if rec:
                with open(rec_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                stats["added"] += 1
            elif skip:
                with open(skip_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(skip, ensure_ascii=False) + "\n")
                stats[skip["reason"]] += 1
            else:
                stats["error (retry on rerun)"] += 1
            n = sum(stats.values())
            if n % 100 == 0:
                el = time.time() - t1
                print(f"  {n}/{len(todo)} {dict(stats)} – {el / n:.2f} s/object", flush=True)

    with ThreadPoolExecutor(a.workers) as ex:
        list(ex.map(work, todo))
    el = time.time() - t1
    n = max(1, sum(stats.values()))
    print(f"done: {dict(stats)} in {el:.0f} s ({el / n:.2f} s/object, {a.workers} workers; "
          f"total incl. listing {time.time() - t0:.0f} s) -> {rec_file} ({len(done_ids) + stats['added']} records)")


if __name__ == "__main__":
    main()
