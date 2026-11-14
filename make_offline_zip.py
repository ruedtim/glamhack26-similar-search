"""Offline copy of the published pages as one ZIP: unpack it, double-click START.html. No web server, no internet.

Copies docs/ (overview, the VMZ and MKB lists, Excel, JSON, thumbnails) into one folder, adds START.html (opens
the overview) and LIESMICH.txt, checks the copy and zips it. The check fails the build if
  - a local link or image does not point to an existing file, or an anchor (#o-…) does not exist. Opened from disk,
    a browser shows a folder listing for "review/" instead of review/index.html, so links to folders count as errors;
  - a page loads anything from the internet (scripts, styles, images, fonts). Links to museum pages are fine;
  - a file name is not ASCII, or two names differ only in case (Windows / macOS would mix them up).

Usage: python make_offline_zip.py [--docs docs] [--out dist/glamhack26-similar-search-offline.zip]
       python make_offline_zip.py --check UNPACKED_FOLDER      # check an unpacked copy only
"""
import argparse
import datetime
import json
import re
import shutil
import sys
import tempfile
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

SITE = "https://ruedtim.github.io/glamhack26-similar-search/"
STORED = {".jpg", ".jpeg", ".png", ".pdf", ".xlsx", ".zip"}      # already compressed

START = """<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="0; url=index.html">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bildähnlichkeit als Hilfe beim Umbenennen</title>
<style>body{font:16px/1.5 system-ui,sans-serif;margin:40px 16px;background:#fafaf8;color:#1d1d1b}
@media (prefers-color-scheme: dark){body{background:#191917;color:#ecebe6}} a{color:inherit}</style></head>
<body><p>Die Übersicht öffnet sich gleich. Falls nicht: <a href="index.html">Übersicht öffnen</a>
· <a href="review/index.html">VMZ-Objekte</a> · <a href="review/mkb.html">MKB-Objekte</a></p></body></html>
"""

README = """Bildähnlichkeit als Hilfe beim Umbenennen – Offline-Version
GLAMhack 2026 · Challenge «To Be Renamed!» · Völkerkundemuseum der Universität Zürich
Stand {date}, gleicher Inhalt wie {site}

ÖFFNEN
1. Die ZIP-Datei zuerst entpacken.
   Windows: Rechtsklick auf die ZIP-Datei > «Alle extrahieren …».
            (Ein Doppelklick zeigt den Inhalt nur an. Wird die Seite von dort geöffnet, fehlen die Bilder.)
   Mac:     Doppelklick auf die ZIP-Datei.
2. Im entpackten Ordner START.html doppelklicken. Die Übersicht öffnet sich im Browser.

INHALT
  START.html                    öffnet die Übersicht
  index.html                    Übersicht mit den vielversprechendsten Beispielen
  review/index.html             alle {n} VMZ-Objekte mit Vorschlägen, Suche und Filtern
  review/mkb.html               alle {n_mkb} MKB-Objekte mit ähnlichen Objekten und Begriffen
  review/vmz_suggestions.xlsx   die Vorschläge als Tabelle (eine Zeile pro Objekt)
  review/vmz_results.json       alle Resultate, maschinenlesbar

Läuft ohne Installation und ohne Internet in jedem aktuellen Browser (Chrome, Edge, Firefox, Safari).
Internet braucht es nur für die Links zu den Objektseiten der anderen Museen und für den Knopf «Feedback»
oben rechts: Er öffnet auf GitHub ein Formular für eine Rückmeldung (ein GitHub-Konto ist nötig).
Auf Smartphones und Tablets besser die Online-Version öffnen.

RECHTE
Fotos der VMZ-Objekte: © Völkerkundemuseum der Universität Zürich. Fotos der MKB-Objekte: © Museum der
Kulturen Basel (Veröffentlichung für dieses Projekt vom MKB genehmigt). Die übrigen Vergleichsbilder gehören den
jeweiligen Museen (Lizenzen in der Fusszeile der Übersicht). Pitt Rivers Museum: nur Name und Link,
die Bilder werden aus Rechtegründen nicht gezeigt.
"""


class Refs(HTMLParser):
    """Links, embedded resources and ids of one page."""

    def __init__(self):
        super().__init__()
        self.refs, self.ids = [], set()

    def handle_starttag(self, tag, attrs):
        for k, v in attrs:
            if k == "id" and v:
                self.ids.add(v)
            elif k in ("href", "src", "srcset", "poster", "data") and v:
                self.refs.append((tag, k, v))


def check(root):
    root = root.resolve()
    files = sorted(p for p in root.rglob("*") if p.is_file())
    rels = [p.relative_to(root).as_posix() for p in files]
    problems = [f"non-ASCII file name: {r}" for r in rels if not r.isascii()]
    seen = {}
    for r in rels:
        seen.setdefault(r.lower(), []).append(r)
    problems += [f"names differ only in case: {v}" for v in seen.values() if len(v) > 1]
    pages = {}
    for p in files:
        if p.suffix == ".html":
            text = p.read_text(encoding="utf-8")
            parser = Refs()
            parser.feed(text)
            pages[p] = parser
            parser.text = text
            if re.search(r"""@import|url\(\s*['"]?(https?:)?//""", text):
                problems.append(f"{p.relative_to(root)}: CSS loads from the internet")
    n_links = 0
    for page, parser in pages.items():
        rel = page.relative_to(root).as_posix()
        for tag, attr, v in parser.refs:
            u = urlsplit(v)
            if u.scheme in ("http", "https") or v.startswith("//"):
                if (tag, attr) != ("a", "href"):
                    problems.append(f"{rel}: <{tag} {attr}> loads from the internet: {v[:80]}")
                continue
            if u.scheme:                                  # mailto:, data: …
                continue
            n_links += 1
            target = (page.parent / unquote(u.path)).resolve() if u.path else page
            if root not in target.parents and target != root:
                problems.append(f"{rel}: points outside the folder: {v}")
            elif u.path.endswith("/") or target.is_dir():
                problems.append(f"{rel}: link to a folder (offline this opens a folder listing): {v}")
            elif not target.exists():
                problems.append(f"{rel}: missing file: {v}")
            elif u.fragment and target in pages and unquote(u.fragment) not in pages[target].ids:
                problems.append(f"{rel}: missing anchor: {v}")
    # paths inside embedded JSON (the MKB list renders its cards in the browser)
    for page, parser in pages.items():
        rel = page.relative_to(root).as_posix()
        for m in re.finditer(r'"((?:\.\./)?img/[\w.-]+\.(?:jpe?g|png))"', parser.text):
            n_links += 1
            if not (page.parent / m.group(1)).is_file():
                problems.append(f"{rel}: missing image in page data: {m.group(1)}")
        for m in re.finditer(r'"((?:\.\./)?[\w/-]*index\.html)#(o-[\w.-]+)"', parser.text):
            n_links += 1
            target = (page.parent / m.group(1)).resolve()
            if target not in pages or m.group(2) not in pages[target].ids:
                problems.append(f"{rel}: missing anchor in page data: {m.group(1)}#{m.group(2)}")
    return problems, len(files), n_links


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", default="docs")
    ap.add_argument("--out", default="dist/glamhack26-similar-search-offline.zip")
    ap.add_argument("--check", help="only check an unpacked folder")
    a = ap.parse_args()
    if a.check:
        problems, n_files, n_links = check(Path(a.check))
        print(f"{n_files} files, {n_links} local links checked")
        print("\n".join(problems[:40]) or "ok: no problems")
        sys.exit(1 if problems else 0)

    docs, out = Path(a.docs), Path(a.out)
    top = out.stem
    res = json.load(open(docs / "review" / "vmz_results.json", encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / top
        shutil.copytree(docs, stage, ignore=shutil.ignore_patterns(".*"))      # no .nojekyll / .DS_Store
        (stage / "START.html").write_text(START, encoding="utf-8")
        mkb = re.search(r'<script id="data" type="application/json">(.*?)</script>',
                        (docs / "review" / "mkb.html").read_text(encoding="utf-8"), re.S)
        n_mkb = len(json.loads(mkb.group(1))["obj"]) if mkb else 0
        readme = README.format(date=datetime.date.today().strftime("%d.%m.%Y"), site=SITE, n=res["n"], n_mkb=n_mkb)
        (stage / "LIESMICH.txt").write_bytes(("﻿" + readme).replace("\n", "\r\n").encode("utf-8"))  # Notepad
        problems, n_files, n_links = check(stage)
        if problems:
            print("\n".join(problems[:40]))
            sys.exit(f"{len(problems)} problems – ZIP not written")
        out.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for p in sorted(stage.rglob("*")):
                if p.is_file():
                    z.write(p, f"{top}/{p.relative_to(stage).as_posix()}",
                            compress_type=zipfile.ZIP_STORED if p.suffix.lower() in STORED else zipfile.ZIP_DEFLATED)
    print(f"wrote {out} ({out.stat().st_size / 1e6:.0f} MB, {n_files} files, {n_links} local links checked)")


if __name__ == "__main__":
    main()
