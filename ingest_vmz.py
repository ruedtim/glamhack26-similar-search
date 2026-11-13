"""Import the GLAMhack sample of the Völkerkundemuseum UZH (VMZ) into the PoC data folder.

Inputs (from the challenge, internal – do not publish):
  - catalogue export (Excel, one row per object, column "Signatur_VMZ_c" = inventory number)
  - "Objektliste kompakt" PDFs: one page per object, page text = inventory number, one studio photo
    (the Windows PostScript driver splits each photo into horizontal bands; they are merged here)

Outputs in DATA_DIR:
  - vmz_catalog.jsonl     compact catalogue (all objects; used for vocabulary + text signals)
  - img/vmz/<sig>.jpg     photo per PDF page (longest side --max-side px)
  - records.jsonl         records with source "vmz" appended (earlier "vmz" records are replaced)

Usage: python ingest_vmz.py --xlsx X.xlsx --pdf A.pdf --pdf B.pdf --out DATA_DIR
       python ingest_vmz.py --xlsx X.xlsx --out DATA_DIR --catalog-only   # only rewrite vmz_catalog.jsonl
"""
import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

import openpyxl
import pymupdf
from PIL import Image

COLS = {  # catalogue column -> short field name
    "Signatur_VMZ_c": "sig", "Objektname_c": "name", "karte_Objektname_einheimisch": "native",
    "karte_Gebrauch": "use", "region_Kontinent": "continent", "region_Weltregion": "world_region",
    "Region_geographisch": "geo_region", "region_Ort": "place", "thema3_Ethnie": "ethnie",
    "thema4_Religion": "religion", "thema5_Sprache": "language", "karte_Eingangsbuch_c": "entry_book",
    "vmz_Kontrollhilfe_c": "control", "karte_Beschreibung_c": "descr", "karte_Material_c": "material",
    "karte_Herkunft_c": "provenance", "karte_Hersteller_c": "maker", "karte_Sammler_c": "collector",
    "erwerb_Art": "acq_type", "erwerb_Datum": "acq_date", "region_Landname": "country",
    "size_Bemerkung": "size_note", "size_Breite": "w", "size_Hoehe": "h", "size_Laenge": "l",
    "size_Tiefe": "d", "size_Durchmesser": "diam", "size_Gewicht_Gramm_n": "weight_g",
    "UnschaerfeVermerk_Kultur": "culture_note", "vmz_OriginalNr": "orig_nr", "karte_Ausstellungen_c": "exhibitions",
    "karte_Dokumentation_c": "documentation", "karte_Literatur_c": "literature", "type_Objekteinheit": "units",
    "region_LandAbk1_ISO": "iso", "region_LandAbk2_ISO": "iso2",
}
FLAGS = {"questionmark": "?", "quotation": "«»"}   # derived from the PDF file name


def norm(v):
    if v is None:
        return ""
    s = str(v).replace("\r", "\n")
    s = re.sub(r"[ \t]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()


def read_catalogue(xlsx):
    wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    rows = wb.worksheets[0].iter_rows(values_only=True)
    hdr = list(next(rows))
    idx = {COLS[h]: k for k, h in enumerate(hdr) if h in COLS}
    out = []
    for r in rows:
        rec = {f: norm(r[k]) for f, k in idx.items()}
        if rec["sig"]:
            out.append(rec)
    return out


def photo_rects(page):
    """Rectangles of the photos on a page: image bands that touch and share their extent are merged;
    the museum logo in the page header is ignored."""
    rects = [r for img in page.get_images(full=True) for r in page.get_image_rects(img[0]) if r.y1 > 60]
    par = list(range(len(rects)))

    def find(i):
        while par[i] != i:
            par[i] = par[par[i]]
            i = par[i]
        return i

    for i, a in enumerate(rects):
        for j in range(i + 1, len(rects)):
            b = rects[j]
            vert = abs(a.x0 - b.x0) < 2 and abs(a.x1 - b.x1) < 2 and min(abs(a.y1 - b.y0), abs(b.y1 - a.y0)) < 2
            hori = abs(a.y0 - b.y0) < 2 and abs(a.y1 - b.y1) < 2 and min(abs(a.x1 - b.x0), abs(b.x1 - a.x0)) < 2
            if vert or hori:
                par[find(i)] = find(j)
    groups = defaultdict(list)
    for i, r in enumerate(rects):
        groups[find(i)].append(r)
    out = []
    for g in groups.values():
        u = pymupdf.Rect(g[0])
        for r in g[1:]:
            u |= r
        out.append(u)
    return sorted(out, key=lambda r: (round(r.y0), r.x0))


def match(sig, cat):
    """Exact inventory number, else the main object (sub-objects like 05072b or 00853.001 are often
    only catalogued under 05072 / 00853)."""
    if sig in cat:
        return sig, "exact"
    s = sig
    for pat in (r"\.\d+$", r"[a-z]+$", r"\.\d+$", r"[a-z]+$"):
        s2 = re.sub(pat, "", s)
        if s2 != s:
            s = s2
            if s in cat:
                return s, "main object"
    return None, "none"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", required=True)
    ap.add_argument("--pdf", action="append", default=[])
    ap.add_argument("--catalog-only", action="store_true", help="only rewrite vmz_catalog.jsonl")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-side", type=int, default=448)
    a = ap.parse_args()
    data = Path(a.out)
    (data / "img" / "vmz").mkdir(parents=True, exist_ok=True)

    cat_rows = read_catalogue(a.xlsx)
    with open(data / "vmz_catalog.jsonl", "w", encoding="utf-8") as f:
        for r in cat_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    cat = {}
    for r in cat_rows:
        cat.setdefault(r["sig"], r)          # 37 duplicate numbers: keep the first row
    print(f"catalogue: {len(cat_rows)} rows, {len(cat)} inventory numbers")
    if a.catalog_only:
        return

    objs = {}                                # sig -> record (objects on two PDFs are merged)
    no_photo = []
    for pdf in a.pdf:
        flag = next((v for k, v in FLAGS.items() if k in Path(pdf).name.lower()), "")
        doc = pymupdf.open(pdf)
        for page in doc:
            lines = [l.strip() for l in page.get_text("text").splitlines() if l.strip()]
            sig = lines[0] if lines else f"page{page.number + 1}"
            rects = photo_rects(page)
            if sig in objs:
                objs[sig]["flag"] = "".join(sorted(set(objs[sig]["flag"] + flag)))
                continue
            if not rects:
                no_photo.append(sig)
                continue
            r = rects[0] if len(rects) == 1 else pymupdf.Rect(rects[0]).include_rect(rects[-1])
            z = a.max_side / max(r.width, r.height)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), clip=r)
            im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            fn = "img/vmz/" + re.sub(r"[^\w.-]+", "_", sig) + ".jpg"
            im.save(data / fn, quality=90)
            msig, how = match(sig, cat)
            c = cat.get(msig, {})
            desc = " | ".join(x for x in (c.get("entry_book"), c.get("descr")) if x)
            objs[sig] = dict(
                source="vmz", id=f"vmz:{sig}", name=c.get("name", ""), title=c.get("name", ""), inv=sig,
                culture=c.get("ethnie") or c.get("geo_region") or c.get("world_region", ""),
                holder="Völkerkundemuseum der Universität Zürich", desc=desc[:700], url="",
                image_url=f"{Path(pdf).name}#page={page.number + 1}", licence="intern (GLAMhack-Stichprobe)",
                img=fn, flag=flag, cat_sig=msig or "", match=how, n_photos=len(rects))
    print(f"PDF pages with photo: {len(objs)}; without photo: {len(no_photo)}")
    print("catalogue match:", {h: sum(o["match"] == h for o in objs.values()) for h in ("exact", "main object", "none")})

    recs = [json.loads(l) for l in open(data / "records.jsonl", encoding="utf-8")]
    kept = [r for r in recs if r["source"] != "vmz"]
    with open(data / "records.jsonl", "w", encoding="utf-8") as f:
        for r in kept + list(objs.values()):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"records.jsonl: {len(kept)} existing + {len(objs)} vmz")


if __name__ == "__main__":
    main()
