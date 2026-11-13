"""Reference objects from the Pitt Rivers Museum (PRM), University of Oxford, from the PRM's own public research
microsites (static HTML pages linked from https://www.prm.ox.ac.uk/collections-research-sites).

Why only the microsites (checked 13.11.2026):
  - PRM Collections Online is a React app on an internal API whose key sits in the website code. Using that key
    would be unauthorised access, so this script does not touch Collections Online at all.
  - No documented PRM / Oxford GLAM API, open-data dump or IIIF collection exists. Europeana has no PRM data
    provider, the UK Museum Data Service lists the PRM without object records, Wikidata has 85 PRM items (4 with
    images) and Wikimedia Commons only a few dozen single-object photos.

Sites used (no login, no key; artefacts only, photographs of people are not harvested):
  lgweb          «Selected Objects from the Lower Gallery» ('What's Upstairs?' project 2004-05), all continents
  weapons        «Arms and Armour at the Pitt Rivers Museum» (~200 highlights), all continents
  bodyarts       «Pitt Rivers Museum Body Arts» (2011, themed sections), all continents
  southernsudan  «Southern Sudan Photo and Object Collections at the PRM» (~1,300 artefacts)

Rights (PRM Collections Online terms, https://www.prm.ox.ac.uk/collections-online-terms-and-conditions):
non-commercial educational and research use; credit "© Pitt Rivers Museum, University of Oxford" plus the accession
number. Publishing the images online or in print needs a PRM licence (photographic.services@prm.ox.ac.uk), so do
not copy these images into docs/ without that permission. The licence text is stored in every record.

Sensitive material: the PRM counts every artefact incorporating human skin, bone, hair, teeth or nails as ancestral
human remains and shows no images of them online. Objects whose name, materials or description mention human
material, human remains or secret/sacred/restricted contexts are skipped (listed in skipped_prm.jsonl, no image).
Also skipped: "no image" placeholders, composite pictures of several objects or photographs (Body Arts) and images
identical to an earlier record's (one group photo for several objects).

Output: OUT/records_prm.jsonl (one record per line, source "prm"; "site" names the microsite) and
OUT/img/prm_<accession>.jpg (longest side 448 px). Pages are cached in OUT/cache/ and known ids are skipped, so the
script can be re-run and resumed; --recheck re-validates existing records after a filter change (cached pages).
Polite: global spacing of --delay seconds between requests, at most --workers (<= 3) at a time.

Usage: data/prm/venv/bin/python harvest_prm.py [--out data/prm] [--sites lgweb,weapons,bodyarts,southernsudan]
                                               [--limit N] [--delay 0.8] [--workers 2] [--recheck]
"""
import argparse
import hashlib
import html
import io
import json
import re
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, unquote

import requests
from PIL import Image

UA = "glam-feasibility-test/0.1 (GLAMhack 2026 research prototype)"
HOLDER = "Pitt Rivers Museum, University of Oxford"
LICENCE = ("© Pitt Rivers Museum, University of Oxford – non-commercial educational/research use only, credit with "
           "accession number; online or print publication needs a PRM licence "
           "(https://www.prm.ox.ac.uk/collections-online-terms-and-conditions)")
LG = "https://web.prm.ox.ac.uk/LGweb/"
WP = "https://web.prm.ox.ac.uk/weapons/index.php/"
SS = "https://southernsudan.prm.ox.ac.uk/"
BA = "https://web.prm.ox.ac.uk/bodyarts/"

# PRM: human remains = skeletal remains and all artefacts incorporating human skin, bone, hair, teeth and nails.
SENSITIVE = [
    # human material (not depictions such as "human figure"); also catalogue-index order "Hair, Human"
    ("human material", r"\bhuman[\s-]+(hair|bones?|skin|teeth|tooth|nails?|finger-?nails?|remains|skulls?|crani\w*"
                       r"|tissue|ashes|fat|blood|jaws?|mandibles?|vertebra\w*|femurs?|tibia\w*|ribs?|scalps?|skeletons?)\b"
                       r"|\b(hair|bones?|teeth|tooth|skin|nails?)\s*,?\s*human\b"),
    ("human remains", r"\b(skulls?|crani(um|a|al)|scalps?|tsantsas?|shrunken heads?|trophy heads?|head trophy"
                      r"|mummif\w*|mumm(y|ies)|toi moko|mokomokai|skeletal remains|relics?|reliquar\w*|ancestral remains"
                      r"|(bones?|teeth|hair|skin|skulls?) of (an? |the |his |her |their )?(enemy|enemies|victims?|dead"
                      r"|deceased|ancestors?|relatives?|wife|husband|warriors?|slain))\b"),
    ("secret/sacred/restricted", r"\b(secret|sacred|restricted|tjurunga|churinga|tjuringa|bull-?roarers?"
                                 r"|medicine bundles?|false faces?|kachinas?|katchinas?|katsinas?|katcinas?)\b"),
]
WEAPON_THEMES = ["A Place in History", "Defining Gender", "Form and Function", "Sacred Weapons", "The Art of War",
                 "The Beautiful Warrior", "Warrior Elites"]
REGIONS = {"africa": "Africa", "americas": "Americas", "the-americas": "Americas", "asia": "Asia", "europe": "Europe",
           "oceania": "Oceania"}


def sensitive_reason(*texts):
    blob = " ".join(t for t in texts if t)
    # weapon descriptions: "effective at smashing a skull" is about use, not about human remains in the object
    blob = re.sub(r"(?i)\b(smash|crack|crush|split|break|fractur|cav|pierc|penetrat)\w*\s+(in\s+)?"
                  r"((an?|the|his|her|their|its)\s+)?(\w+'s\s+)?skulls?\b", " ", blob)
    for reason, rx in SENSITIVE:
        m = re.search(rx, blob, re.I)
        if m:
            return f"{reason} ({m.group(0)})"
    return None


def clean(s):
    s = html.unescape(re.sub(r"(?s)<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s.replace("\xa0", " ")).strip()


def text_lines(fragment):
    """Visible text lines; tags are removed on the whole fragment first (old pages break tags across lines)."""
    frag = re.sub(r"(?is)<(script|style)\b.*?</\1>|<!--.*?-->", " ", fragment)
    frag = re.sub(r"\s+", " ", frag)  # source line breaks are not text breaks ("Ireland or Northern\n Ireland")
    frag = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h\d|td|tr|span|a)>|<(p|div|li|tr|td|h\d)\b[^>]*>", "\n", frag)
    frag = re.sub(r"(?s)<[^>]*>", " ", frag)
    lines = (re.sub(r"\s+", " ", html.unescape(x).replace("\xa0", " ")).strip() for x in frag.split("\n"))
    return [ln for ln in lines if ln]


def decode(content):
    m = re.search(rb"""(?i)<meta[^>]+charset=["']?([\w-]+)""", content[:4000])
    enc = m.group(1).decode() if m else "utf-8"
    try:
        return content.decode(enc)
    except (LookupError, UnicodeDecodeError):
        return content.decode("cp1252", "replace")


def img_hash(path):
    return hashlib.md5(path.read_bytes()).hexdigest() if path.exists() else None


def sanitise(acc):
    return re.sub(r"[^0-9A-Za-z]+", "_", acc).strip("_")


class Fetcher:
    """One shared session; at least `delay` seconds between the starts of any two requests; pages are cached."""

    def __init__(self, cache, delay):
        self.cache, self.delay = cache, delay
        self.lock, self.last, self.requests = threading.Lock(), 0.0, 0
        self.s = requests.Session()
        self.s.headers["User-Agent"] = UA

    def _get(self, url):
        for i in range(3):
            with self.lock:
                wait = self.last + self.delay - time.time()
                if wait > 0:
                    time.sleep(wait)
                self.last = time.time()
                self.requests += 1
            try:
                r = self.s.get(url, timeout=40)
                if r.status_code == 200:
                    return r.content
                if r.status_code in (403, 404, 410):
                    return None
            except requests.RequestException:
                pass
            time.sleep(4 * (i + 1))
        return None

    def page(self, url):
        f = self.cache / (hashlib.sha1(url.encode()).hexdigest() + ".html")
        if f.exists():
            return f.read_text(encoding="utf-8")
        content = self._get(url)
        if content is None:
            return None
        t = decode(content)
        f.write_text(t, encoding="utf-8")
        return t

    def image(self, url, path, max_side=448):
        if path.exists():
            return True
        content = self._get(url)
        if not content:
            return False
        try:
            im = Image.open(io.BytesIO(content)).convert("RGB")
        except Exception:
            return False
        if min(im.size) < 80:
            return False
        im.thumbnail((max_side, max_side))
        im.save(path, "JPEG", quality=88)
        return True


def record(site, acc, name, title, culture, url, image_url):
    rid = "prm_" + sanitise(acc)
    return {"source": "prm", "id": rid, "name": name, "title": title, "inv": acc, "culture": culture,
            "holder": HOLDER, "desc": "", "url": url, "image_url": image_url, "licence": LICENCE,
            "img": f"img/{rid}.jpg", "site": site}


# ------------------------------------------------------------------ Lower Gallery selection (LGweb)
def lgweb_list(fx):
    t = fx.page(LG + "index.htm") or ""
    cats = sorted(set(re.findall(r'(?i)href\s*=\s*"?(\w+/\w+1\.htm)', t)))
    urls = []
    for c in cats:
        ct = fx.page(LG + c) or ""
        for href in re.findall(r'(?i)href\s*=\s*"?(\d{4}_[\w]+\.htm)', ct):
            u = urljoin(LG + c, href)
            if u not in urls:
                urls.append(u)
    return urls


def lgweb_object(fx, url):
    t = fx.page(url)
    if not t:
        return None, "page not found"
    m = re.search(r"(?i)<title>\s*([^<]+?)\s+-\s+Pitt Rivers Museum", t)
    acc = clean(m.group(1)) if m else ""
    im = re.search(r'(?i)<img[^>]+src="(\.\./images/[^"]+\.jpe?g)"[^>]*>', t)
    if not acc or not im:
        return None, "no accession number or image"
    alt = re.search(r'(?i)alt="([^"]*)"', im.group(0))
    alt = clean(alt.group(1)) if alt else ""
    lines = text_lines(t[t.find("<body"):] if "<body" in t else t)
    i0 = next((i for i, ln in enumerate(lines) if ln in REGIONS.values()), None)
    region = lines[i0] if i0 is not None else ""
    name = lines[i0 + 1] if i0 is not None and i0 + 1 < len(lines) else alt.split(",")[0]
    place = ""
    if i0 is not None and i0 + 2 < len(lines) and not re.match(
            r"(?i)(collected|given|made|purchased|donated|bequeathed|found|field|transferred|lent|exchanged|"
            r"main gallery)", lines[i0 + 2]):
        place = lines[i0 + 2]
    # sensitivity check on ALL visible text of the page (navigation/footer of this site hold no such words);
    # the description sits between "Previous Object"/"Previous Image" and "View database record"
    reason = sensitive_reason(alt, *lines)
    if reason:
        return {"acc": acc, "name": name}, reason
    culture = ", ".join(x for x in (place, region) if x)
    return record("lgweb", acc, name, alt or name, culture, url, urljoin(url, im.group(1))), None


# ------------------------------------------------------------------ Arms and Armour (weapons)
def weapons_list(fx):
    """Type tours + region galleries; the same object appears under several URLs -> dedupe by accession number."""
    t = fx.page(WP + "tour-by-object-type/index.html") or ""
    types = sorted(set(re.findall(r'href="([a-z-]+/index\.html)"', t)))
    regions = ["africa", "asia", "europe", "oceania", "the-americas"]
    pages = [WP + "tour-by-object-type/" + x for x in types] + [WP + f"tour-by-region/{r}/index.html" for r in regions]
    urls, seen = [], set()
    for p in pages:
        pt = fx.page(p) or ""
        for href, alt in re.findall(r'(?is)<a href="([^"]+)"[^>]*class="jg_catelem_photo">\s*<img[^>]+alt="([^"]*)"', pt):
            u = urljoin(p, href)
            m = re.search(r"\(([^()]*\d[^()]*)\)\s*$", html.unescape(alt))
            key = m.group(1).strip() if m else u
            if key not in seen and u not in urls:
                seen.add(key)
                urls.append(u)
    return urls


def weapons_object(fx, url):
    t = fx.page(url)
    if not t:
        return None, "page not found"
    im = re.search(r'(?is)<img[^>]+src="([^"]+joomgallery/details/[^"]+)"[^>]*id="jg_photo_big"[^>]*>', t) or \
        re.search(r'(?is)<img[^>]+id="jg_photo_big"[^>]*src="([^"]+)"[^>]*>', t)
    if not im:
        return None, "no image"
    alt = re.search(r'(?i)alt="([^"]*)"', im.group(0))
    alt = clean(alt.group(1)) if alt else ""
    m = re.match(r"(.+?)\s*\(([^()]*\d[^()]*)\)\s*$", alt)
    if not m:
        return None, f"no accession number in «{alt}»"
    title, acc = m.group(1).strip(), m.group(2).strip()
    i = t.find("Image information")
    seg = t[i:t.find("Privacy policy", i)] if i > 0 else ""
    lines = [ln for ln in text_lines(seg) if ln not in WEAPON_THEMES and not re.fullmatch(r"[\d\s]+", ln)
             and ln not in ("Image information", "-->")]
    place = lines[0] if lines and len(lines[0]) < 60 else ""
    desc = " ".join(lines[1:] if place else lines)
    reason = sensitive_reason(title, desc)
    if reason:
        return {"acc": acc, "name": title}, reason
    rg = re.search(r"tour-by-region/[^/]+/([a-z-]+)/[^/]+/index\.html", url)  # .../oceania/africa/<item>/
    region = REGIONS.get(rg.group(1), "") if rg else ""
    culture = ", ".join(x for x in (place, region) if x)
    return record("weapons", acc, title, title, culture, url, urljoin(url, im.group(1))), None


# ------------------------------------------------------------------ Body Arts (themed sections, all continents)
def bodyarts_list(fx):
    t = fx.page(BA + "index.html") or ""
    sections = []
    for grp, sec in re.findall(r'href="index\.php/([a-z-]+)/([a-z-]+)\.html"', t):
        if grp != sec and grp not in ("multimedia", "resources") and (grp, sec) not in sections:
            sections.append((grp, sec))
    urls = []
    for grp, sec in sections:
        base = BA + f"index.php/{grp}/{sec}.html"
        st = fx.page(base) or ""
        for href in re.findall(rf'href="({re.escape(sec)}/\d+-[^"]+\.html)"', st):
            u = urljoin(base, href)
            if u not in urls:
                urls.append(u)
    return urls


def bodyarts_object(fx, url):
    t = fx.page(url)
    if not t:
        return None, "page not found"
    m = re.search(r"(?is)<title>[^<|]*\|\s*([^<]+)</title>", t)
    title = clean(m.group(1)) if m else ""
    acc_rx = r"\b\d{4}\.\d+(?:\.\d+)*(?:\s*\.\d+)*"
    im = next((x for x in re.finditer(r'(?is)<img[^>]+>', t)
               if "images/stories/" in x.group(0) and re.search(acc_rx, x.group(0))), None)
    if not title or not im:
        return None, "no accession number or image"
    src = re.search(r'(?i)src="([^"]+)"', im.group(0)).group(1)
    attrs = [clean(v) for v in re.findall(r'(?i)\b(?:alt|title)="([^"]*)"', im.group(0))]
    caption = next((v for v in attrs if re.search(acc_rx, v)), "")
    acc = re.search(acc_rx, caption or im.group(0)).group(0).strip()
    lines = text_lines(t[t.find("<body"):] if "<body" in t else t)
    # article = last occurrence of the title up to the "Blank module"/"Related Articles" box
    i0 = max((i for i, ln in enumerate(lines) if ln == title), default=None)
    if i0 is None:
        return None, "article text not found"
    j1 = next((j for j in range(i0 + 1, len(lines)) if lines[j] in ("Blank module", "Related Articles")), len(lines))
    article = lines[i0 + 1:j1]
    reason = sensitive_reason(title, caption, *article)  # the whole article text, not only the caption
    if reason:
        return {"acc": acc, "name": title}, reason
    # many pages show several objects ("Left: … Right: …") or photographs of people -> not a single-object image
    if (re.search(r"(?i)\[(b|br)\]|\b(left|right|top|bottom|middle|centre|center)\s*:", caption)
            or len(re.findall(acc_rx, caption)) > 1 or re.search(r"(?i)photograph|\bphoto\b", caption)):
        return {"acc": acc, "name": title}, "composite image or photograph, not a single object"
    place = article[0] if article and not re.search(acc_rx, article[0]) and len(article[0]) < 120 else ""
    return record("bodyarts", acc, title, title, place, url, urljoin(url, src)), None


# ------------------------------------------------------------------ Southern Sudan (artefacts only)
def ss_url(path):
    """Static S3 site: a literal '+' in a file name must be sent as %2B ('+' would be read as a space -> 403)."""
    return SS + path.replace("+", "%2B")


def ss_list(fx):
    """Artefact sections of the cultural-group and region listings (each page shows photographs first, then
    artefacts; both sections share the 20-per-page offsets)."""
    groups = re.findall(r'href="/?culturalgroup/([^/"%]+)/', fx.page(SS + "cultural_group.php.html") or "")
    regions = re.findall(r'href="search/r/([^/"%]+)/index\.html"', fx.page(SS + "sudan_map.php.html") or "")
    entries = [("group", g, f"culturalgroup/{g}/index.html") for g in sorted(set(groups))]
    entries += [("r", r, f"search/r/{r}/index.html") for r in sorted(set(regions))]
    urls = []
    for key, val, first_path in entries:
        first = fx.page(ss_url(first_path))
        if not first:
            continue
        m = re.search(r"Displaying (\d+) from the Sudan artifacts collection", first)
        n = int(m.group(1)) if m else 0
        pages = [first] + [fx.page(ss_url(f"quick_search.php-{key}={val}&offset={k}.html")) for k in range(20, n, 20)]
        for pt in pages:
            if not pt or "Sudan artifacts collection" not in pt:
                continue
            art = pt[pt.find("Sudan artifacts collection"):]
            for href in re.findall(r'href="(?:\.\./)*details/([^"/]+)/index\.html"', art):
                u = ss_url(f"details/{href}/index.html")
                if u not in urls:
                    urls.append(u)
    return urls


_SS_GROUPS = None
NOT_ETHNONYMS = {"or", "and", "of", "the", "european", "turkish", "arab", "southern", "northern", "sudan", "uganda",
                 "congo", "ethiopia", "kenya", "people", "group"}


def ss_groups(fx):
    """Cultural-group names of the Southern Sudan site (cached listing page)."""
    global _SS_GROUPS
    if _SS_GROUPS is None:
        t = fx.page(SS + "cultural_group.php.html") or ""
        _SS_GROUPS = {unquote(g).replace("+", " ") for g in re.findall(r'href="/?culturalgroup/([^/"%]+)/', t)}
    return _SS_GROUPS


def strip_ethnonyms(title, group_field, groups):
    """'Acholi or Lango fringe apron' -> 'fringe apron', 'Anuak spoon' (group 'Anywaa [Anuak]') -> 'spoon',
    'Bow harp, Acholi?' -> 'Bow harp'. Returns the title unchanged if too little would remain."""
    toks = set(groups) | set(re.findall(r"[A-Z][A-Za-z'-]+", group_field or ""))
    toks = {t for t in toks if t.lower() not in NOT_ETHNONYMS}
    if not toks:
        return title
    alts = "|".join(re.escape(t) for t in sorted(toks, key=len, reverse=True))
    one = rf"\??(?:(?:northern|southern|eastern|western|central)\s+)?(?:{alts})\??"  # "Southern Larim waist …"
    name = re.sub(rf"^{one}(?:\s*(?:,|or|and|/)\s*{one})*\s+(?=\S)", "", title, flags=re.I)
    name = re.sub(rf",?\s*{one}\s*$", "", name, flags=re.I)
    return name if len(name) >= 3 else title


def ss_object(fx, url):
    t = fx.page(url)
    if not t:
        return None, "page not found"
    fields = {clean(k).rstrip(":"): clean(v) for k, v in re.findall(
        r'(?is)<div class="InfoHeading"[^>]*>(.*?)</div>\s*<div class="FieldInfo"[^>]*>(.*?)</div>', t)}
    acc = fields.get("Accession Number") or unquote(url.split("/details/")[1].split("/")[0])
    h1 = re.search(r"(?is)<div id=\"MidImage\">\s*<h1>(.*?)</h1>", t)
    title = clean(h1.group(1)) if h1 else ""
    im = re.search(r'(?i)<div id="MidImage">.*?<img src="([^"]+/images/midsize/[^"]+)"', t, re.S)
    if not im or "nophoto" in im.group(1).lower():  # images/midsize/nophoto.gif = "This record has no image"
        return None, "no image"
    if "Photographer" in fields or "Materials" not in fields and "Dimensions" not in fields:
        return None, "photograph, not an artefact"
    reason = sensitive_reason(title, *fields.values())  # all catalogue fields, incl. materials and description
    if reason:
        return {"acc": acc, "name": title}, reason
    group = fields.get("Cultural Group", "")
    name = strip_ethnonyms(title, group, ss_groups(fx))
    name = name[:1].upper() + name[1:]
    region = re.sub(r"\]\s*\[", ", ", fields.get("Region", "")).replace("[", "").replace("]", "").strip(" ,")
    culture = ", ".join(x for x in (group, region, fields.get("Country", "")) if x)
    return record("southernsudan", acc, name, title, culture, url, urljoin(url, im.group(1))), None


SITES = {"lgweb": (lgweb_list, lgweb_object), "weapons": (weapons_list, weapons_object),
         "bodyarts": (bodyarts_list, bodyarts_object), "southernsudan": (ss_list, ss_object)}


def main():
    ap = argparse.ArgumentParser(description=" ".join(__doc__.split("\n\n")[0].split()))
    ap.add_argument("--out", default="data/prm")
    ap.add_argument("--sites", default="lgweb,weapons,bodyarts,southernsudan")
    ap.add_argument("--limit", type=int, default=0, help="max new records per site (0 = all)")
    ap.add_argument("--delay", type=float, default=0.8, help="seconds between the starts of two requests")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--recheck", action="store_true",
                    help="first re-validate existing records with the current parser/filter (cached pages), drop "
                         "the ones that fail and delete their images")
    a = ap.parse_args()
    out = Path(a.out)
    (out / "img").mkdir(parents=True, exist_ok=True)
    (out / "cache").mkdir(exist_ok=True)
    fx = Fetcher(out / "cache", a.delay)
    rec_file, skip_file = out / "records_prm.jsonl", out / "skipped_prm.jsonl"
    sites = [s.strip() for s in a.sites.split(",") if s.strip()]
    # skip list: entries of the sites run now are rebuilt (re-evaluated from the cache), others are kept
    old_skips = [ln for ln in open(skip_file, encoding="utf-8") if ln.strip()] if skip_file.exists() else []
    skip_file.write_text("".join(ln for ln in old_skips if json.loads(ln)["site"] not in sites), encoding="utf-8")
    write_lock = threading.Lock()

    def log_skip(site, u, rec, reason):
        with open(skip_file, "a", encoding="utf-8") as f:
            f.write(json.dumps({"site": site, "url": u, "inv": (rec or {}).get("acc") or (rec or {}).get("inv", ""),
                                "name": (rec or {}).get("name", ""), "reason": reason}, ensure_ascii=False) + "\n")

    known, known_img = set(), set()
    if rec_file.exists():
        recs = [json.loads(ln) for ln in open(rec_file, encoding="utf-8") if ln.strip()]
        if a.recheck:
            keep, seen_img = [], set()
            for r in recs:
                new, reason = SITES[r["site"]][1](fx, r["url"])
                h = img_hash(out / r["img"])
                if not reason and h and h in seen_img:
                    reason = "same image as another record (group photo)"
                if reason:
                    (out / r["img"]).unlink(missing_ok=True)
                    log_skip(r["site"], r["url"], r, "recheck: " + reason)
                else:
                    keep.append(new)
                    seen_img.add(h)
            print(f"recheck: kept {len(keep)} of {len(recs)} records", flush=True)
            with open(rec_file, "w", encoding="utf-8") as f:
                f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in keep)
            recs = keep
        known = {r["id"] for r in recs}
        known_img.update(img_hash(out / r["img"]) for r in recs)
    t_all = time.time()
    for site in sites:
        list_fn, obj_fn = SITES[site]
        t0, r0 = time.time(), fx.requests
        urls = list_fn(fx)
        print(f"[{site}] {len(urls)} object pages listed ({fx.requests - r0} requests, {time.time() - t0:.0f} s)",
              flush=True)
        stats, added = Counter(), []

        def one(u):
            if a.limit and len(added) >= a.limit:
                return
            try:
                rec, reason = obj_fn(fx, u)
            except Exception as e:  # one odd page must not stop the run
                rec, reason = None, f"parse error ({type(e).__name__})"
            if rec and not reason:
                if rec["id"] in known:
                    stats["already known"] += 1
                    return
                if not fx.image(rec["image_url"], out / rec["img"]):
                    reason = "image download failed"
                else:
                    with write_lock:  # several objects shown in one group photo -> keep the first only
                        h = img_hash(out / rec["img"])
                        dup_img = h in known_img
                        known_img.add(h)
                    if dup_img:
                        (out / rec["img"]).unlink(missing_ok=True)
                        reason = "same image as another record (group photo)"
            with write_lock:
                if reason:
                    stats["skipped: " + reason.split(" (")[0]] += 1
                    log_skip(site, u, rec, reason)
                elif rec["id"] not in known and not (a.limit and len(added) >= a.limit):
                    known.add(rec["id"])
                    added.append(rec)
                    with open(rec_file, "a", encoding="utf-8") as f:
                        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        with ThreadPoolExecutor(max(1, min(a.workers, 3))) as ex:
            list(ex.map(one, urls))
        print(f"[{site}] +{len(added)} records, {dict(stats)}; {fx.requests - r0} requests, "
              f"{time.time() - t0:.0f} s", flush=True)
    # one skip entry per page (a page dropped by --recheck is re-evaluated by its site run and logged again)
    last = {}
    for ln in open(skip_file, encoding="utf-8"):
        if ln.strip():
            s = json.loads(ln)
            last[(s["site"], s["url"])] = ln
    skip_file.write_text("".join(last.values()), encoding="utf-8")
    n = sum(1 for _ in open(rec_file, encoding="utf-8")) if rec_file.exists() else 0
    print(f"total {n} records in {rec_file}; {fx.requests} requests in {time.time() - t_all:.0f} s")


if __name__ == "__main__":
    main()
