"""Overview page for the challenge owners: the most promising results on one page.

Reads the results of suggest_vmz.py (OUT/vmz_results.json) and writes docs/index.html with images in
docs/img/. The examples below are chosen by hand; all numbers (ranks, status, neighbours) come from the
results file, so the page stays correct after a re-run. Check the hand-written sentences after a re-run.

Usage: python make_overview.py --data DATA_DIR --results docs/review/vmz_results.json --out docs
"""
import argparse
import html
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

from PIL import Image

from feedback import FEEDBACK_CSS, feedback_html

REPO = "https://github.com/ruedtim/glamhack26-similar-search"
SITE = "https://ruedtim.github.io/glamhack26-similar-search/"
ZIP = REPO + "/releases/latest/download/glamhack26-similar-search-offline.zip"   # GitHub release asset (make_offline_zip.py)
GROUPS = [
    ("Ähnliche Objekte liefern den Fachbegriff",
     "Die visuell ähnlichsten Objekte aus anderen Sammlungen tragen oft schon den passenden Namen.",
     ["00145ad", "24472", "00276"]),
    ("Die «?»-Hypothese wird vom Foto gestützt",
     "Der unsichere Begriff gehört zu den 2 % der VMZ-Begriffe, die am besten zum Foto passen – "
     "oft tragen auch die ähnlichsten Objekte diesen Namen.",
     ["38285", "20428", "11948.026"]),
    ("«Figur»: generischer Name, konkreter Vorschlag",
     "271 Objekte heissen im Katalog nur «Figur». Ähnliche Objekte anderer Museen tragen oft eine präzise "
     "Typbezeichnung – ein Vorschlag zur Prüfung, kein Ersatz für die Fachperson.",
     ["10108", "12245", "o.Nr.3520"]),
    ("Gegenvorschlag, wo die Hypothese nicht passt",
     "Der Begriff im Namen passt kaum zum Foto, dafür andere Begriffe aus dem eigenen Katalog.",
     ["o.Nr.5388", "08413.002"]),
]


def rank(o, term):
    return next((t["rank"] for t in o["terms"] if t["term"] == term), None)


def quoted(names):
    return ", ".join(f"«{n}»" for n in names)


def notes(o, res):
    """Hand-written reading of each example; numbers and names are filled in from the results.
    Re-read the sentences after a re-run with a different reference set."""
    v = res["vocab"]
    nn = o["neighbour_names"]                       # top-12 neighbours, grouped by name
    nb = o["neighbours"][:5]                        # top-5 neighbours as shown on the card
    names5 = [n["name"].lower() for n in nb]
    inv = o["inv"]
    if inv in ("00273", "00276"):
        ww = [x for x in nn if "winnowing" in x["name"].lower()]
        n_ww = sum(x["count"] for x in ww)
        rest = [x["name"].split(" | ")[0] for x in nn if "winnowing" not in x["name"].lower()]
        rest = list(dict.fromkeys(rest))[:3]
        mkb = [m for m in o.get("mkb_europa", []) if "worfel" in m["title"].lower()]
        if n_ww:
            worf = (f"ist eine Worfel ({quoted(x['name'] for x in ww)})" if n_ww == 1 else
                    f"sind {n_ww} Worfeln ({quoted(x['name'] for x in ww)})")
            lead = f"Unter den 12 ähnlichsten Objekten {worf}, die übrigen heissen {quoted(rest)}."
        else:
            lead = f"Die 12 ähnlichsten Objekte heissen {quoted(rest)} – keine Worfel."
        return (f"{lead} Das Bild-Text-Modell kennt das seltene Wort «Worfel» nicht (Rang {rank(o, 'Worfel')})"
                + (f"; die MKB-Sammlung Europa kennt das Wort in {len(mkb)}+ Titeln ({quoted(m['title'] for m in mkb[:2])})."
                   if mkb else "."))
    if inv == "00145ad":
        gw = sum(x["count"] for x in nn if "goldgewicht" in x["name"].lower())
        return (f"{'Alle 12' if gw == 12 else f'{gw} der 12'} ähnlichsten Objekte sind Goldgewichte aus dem "
                f"Museum Rietberg: Wenn der Vergleichsbestand den Objekttyp enthält, sind die Treffer sehr genau.")
    supported = {"38285": ("Pfeife", r"pfeife|pipe"), "20428": ("Gürtelschnalle", r"schnalle|buckle"),
                 "11948.026": ("Pfeilspitze", r"pfeilspitze|arrowhead|arrow point")}
    if inv in supported:
        term, pat = supported[inv]
        hit = [n["name"] for n in nb if re.search(pat, n["name"], re.I)]
        k = len(hit)
        return (f"«{term}» steht auf Rang {rank(o, term)} von {v} ({label_of(rank(o, term), res)}); {k} der 5 "
                f"ähnlichsten Objekte {'heisst' if k == 1 else 'heissen'} {quoted(list(dict.fromkeys(hit))[:3])} – "
                f"Bild-Text-Abgleich und Vergleichsobjekte stimmen überein.")
    if inv == "11948.015":
        k = sum("pfeilspitze" in n for n in names5)
        hold = sorted({n["holder"].split(",")[0] for n in nb if "pfeilspitze" in n["name"].lower()})
        return (f"«Pfeilspitze» steht auf Rang {rank(o, 'Pfeilspitze')} von {v}; {k} der 5 ähnlichsten Objekte heissen "
                f"«Pfeilspitze …» ({', '.join(hold)}) – Bild-Text-Abgleich und Vergleichsobjekte stimmen überein.")
    if inv == "o.Nr.4211":
        k = sum("haarnadel" in n for n in names5)
        return (f"«Haarnadel» steht auf Rang {rank(o, 'Haarnadel')} von {v}"
                + (f"; {k} der 5 ähnlichsten Objekte {'ist eine Haarnadel' if k == 1 else 'sind Haarnadeln'} "
                   f"aus dem Museum Rietberg." if k else
                   f"; die ähnlichsten Objekte heissen {quoted(list(dict.fromkeys(n['name'] for n in nb))[:3])}."))
    if inv == "o.Nr.4101":
        n_h = sum(x["count"] for x in nn if re.search(r"harpoon|harpune", x["name"].lower()))
        top5 = Counter(re.sub(r"^[A-Z]\d+/?\d*\s+", "", n["name"]) for n in nb)
        rest = ", ".join(f"{c}× «{k}»" if c > 1 else f"«{k}»" for k, c in top5.most_common())
        return (f"«Harpune» steht auf Rang {rank(o, 'Harpune')} von {v}"
                + (f"; unter den 12 ähnlichsten Objekten {'ist eine' if n_h == 1 else f'sind {n_h}'} «Harpoon»" if n_h else "")
                + f". Die fünf ähnlichsten: {rest}.")
    if inv == "24472":   # group A: the neighbours name the textile type
        suz = next((n for n in nb if "suzani" in n["name"].lower()), None)
        nat = " und ".join("«" + m["term"] + "»" for m in o["native_matches"][:2])
        return (f"«Bettüberwurf» steht auf Rang {rank(o, 'Bettüberwurf')} von {v}."
                + (f" Das ähnlichste Objekt ist ein «{suz['name']}» ({suz['holder']})." if suz else "")
                + f" Der einheimische Name «susani» kommt im VMZ-Katalog bei weiteren Objekten vor – dort als {nat}.")
    fig = {"10108": (r"kraft|nkisi|nkondi|power", "Kraftfigur (nkisi)"),
           "15682": (r"ahnen|ancest|totok|hampatong", "Ahnenfigur"),
           "12245": (r"buddha|bodhisattva|sakyamuni|shakyamuni", "Buddha-Figur"),
           "o.Nr.3520": (r"puppe|doll", "Puppe")}
    if inv in fig:
        pat, label = fig[inv]
        hits = [x for x in nn if re.search(pat, x["name"], re.I)]
        k = sum(x["count"] for x in hits)
        where = ", ".join(v for v in (o.get("culture"), o.get("country")) if v and v != "(ohne Zuordnung)")
        terms = ", ".join(t["term"] for t in o["vmz_terms"][:3])
        named = quoted(x['name'].split(' | ')[0] for x in hits[:2])
        lead = (f"{k} der 12 ähnlichsten Objekte {'heisst' if k == 1 else 'heissen'} {named}" if k else
                "Unter den 12 ähnlichsten Objekten ist keines mit präziser Bezeichnung")
        return (f"Im Katalog nur «Figur»{f' ({where})' if where else ''}. {lead}; passende VMZ-Begriffe: {terms}. "
                f"Vorschlag zur Prüfung: «{label}».")
    if inv == "o.Nr.5388":
        arm = [t for t in o["en_terms"] if re.search(r"bracelet|bangle|wristlet|armlet|anklet", t)]
        ring = sum(x["count"] for x in nn if re.search(r"armring|armreif|bracelet|bangle", x["name"].lower()))
        return (f"«Ornament» nur Rang {rank(o, 'Ornament')} von {v}. Der Bild-Text-Abgleich nennt Armmanchette, "
                f"Armstulpe und Papuaarmband (VMZ-Begriffe)" + (f" sowie {quoted(arm)}" if arm else "")
                + (f"; unter den 12 ähnlichsten Objekten sind {ring}× «Armring» (Ethnologisches Museum Berlin), "
                   f"daneben Bambusbehälter und Mörser" if ring else
                   "; die ähnlichsten Objekte sind dagegen Bambusbehälter") + ". Armschmuck prüfen.")
    if inv == "08413.002":
        fin = sum("finial" in n["name"].lower() for n in o["neighbours"][:8])
        return (f"«Gefäss» nur Rang {rank(o, 'Gefäss')} von {v}. Der Bild-Text-Abgleich nennt Vogelkopf und Tierkopf"
                + (f"; unter den 8 ähnlichsten Objekten sind {fin} Stabaufsätze («Finial», Freer Gallery of Art)."
                   if fin else "; die ähnlichsten Objekte sind figürliche Anhänger und Köpfe."))
    if inv == "o.Nr.2607":
        bell = [t for t in o["en_terms"] if "bell" in t]
        rk = rank(o, 'Rassel')
        return (f"«Rassel» Rang {rk} von {v} ({label_of(rk, res)}). Unter den fünf passendsten VMZ-Begriffen sind "
                f"Messingglocke, Kuhglocke, Schelle und Glocke" + (f", englisch {quoted(bell[:2])}" if bell else "")
                + ": eher eine Glocke?")
    raise KeyError(inv)


def label_of(r, res):
    return {"sup": "gestützt", "pos": "möglich", "no": "nicht gestützt"}[status(r, res)]


def status(r, res):
    return "sup" if r <= res["sup"] else "pos" if r <= res["pos"] else "no"


def short_holder(h):
    h = re.sub(r"^The ", "", h or "")
    h = h.replace("Smithsonian – ", "Smithsonian, ")
    return h[:38]


def img(src, dst, side):
    if not dst.exists():
        im = Image.open(src).convert("RGB")
        im.thumbnail((side, side))
        im.save(dst, quality=85)
    return f"img/{dst.name}"


def fname(s):
    """ASCII-only file name / HTML id part; same as suggest_vmz.fname (the links into the list need the same ids)."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^\w.-]+", "_", s, flags=re.ASCII)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--results", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    data, out = Path(a.data), Path(a.out)
    (out / "img").mkdir(parents=True, exist_ok=True)
    res = json.load(open(a.results, encoding="utf-8"))
    objs = {o["inv"]: o for o in res["objects"]}
    st = res["stats"]
    esc = html.escape
    tn, hn = max(1, st.get("type_n", 0)), max(1, st.get("hyp_n", 0))
    n_ref = sum(res["ref"].values())
    n_mkb = sum('"source": "mkb"' in line for line in open(data / "records.jsonl", encoding="utf-8"))  # MKB list
    label = {"sup": "gestützt", "pos": "möglich", "no": "nicht gestützt"}
    g = res.get("groups", {})
    n_q = sum(v for k, v in g.items() if "?" in k)
    n_quote = sum(v for k, v in g.items() if "«" in k)
    grp_text = f"{n_q} mit «?», {n_quote} mit Anführungszeichen" + (f", {g['Figur']} nur «Figur» genannt" if g.get("Figur") else "")

    def pct(a, b):
        return f"{a / b:.0%}" if b else "–"
    better = st.get("geo_type_l2", 0) + st.get("geo_hyp_l2", 0) > st.get("geo_type_l1", 0) + st.get("geo_hyp_l1", 0)
    geo_word = "eine hilfreiche zweite Sicht" if better else "eine zusätzliche Sicht, kein besserer Namensgeber"
    fig = res.get("figures") or {}
    generic = re.compile(r"^(figure|figur|figurine|male figure|female figure|männliche figur|weibliche figur|statuette|"
                         r"statue|schnitzerei|seated figure|standing figure|sculpture|carving|figurine head)$", re.I)
    spec = [f"«{nm}» ({c})" for nm, c in fig.get("neighbour_names", []) if nm and not generic.match(nm.strip())][:6]
    vt = [f"«{t}» ({c})" for t, c in fig.get("vmz_terms", [])
          if not re.match(r"^(holz|bronze|messing|metall|stein|marmor|ton|porzellan)", t, re.I)][:6]
    fig_bullet = (f"<li><b>«Figur» lässt sich oft präzisieren.</b> Bei den {fig['n']} «Figur»-Objekten heissen die "
                  f"ähnlichsten Objekte am häufigsten {', '.join(spec)}; das Bild-Text-Modell schlägt aus dem "
                  f"VMZ-Vokabular vor allem {', '.join(vt)} vor (Materialbegriffe ausgenommen).</li>"
                  if fig.get("n") else "")

    def card(o):
        safe = fname(o["inv"])
        q = img(data / o["img"], out / "img" / f"q_{safe}.jpg", 420)
        chips = "".join(
            f'<span class="chip {status(t["rank"], res)}">{esc(t["term"])}{" " + t["mark"] if t["mark"] else ""}'
            f' <b>#{t["rank"]}</b> <i>{label[status(t["rank"], res)]}</i></span>'
            for t in o["terms"] if t["mark"] == "?")
        nbs = []
        for nb in o["neighbours"][:5]:
            if nb.get("publish_image") is False:        # rights: name + link only
                pic = '<span class="noimg">Bild nicht veröffentlicht</span>'
            else:
                t = img(data / nb["img"], out / "img" / ("r_" + fname(nb["id"]) + ".jpg"), 240)
                pic = f'<img src="{t}" alt="" loading="lazy">'
            nbs.append(f'<a class="nb" href="{esc(nb["url"])}" target="_blank" rel="noopener">'
                       f'{pic}<span class="nbn">{esc(nb["name"][:48])}</span>'
                       f'<span class="nbh">{esc(short_holder(nb["holder"]))}</span></a>')
        place = ", ".join(x for x in (o.get("culture"), o.get("country")) if x and x != "(ohne Zuordnung)")
        return f"""<article class="ex">
<figure class="q"><img src="{q}" alt="Foto des Objekts {esc(o['inv'])}"><figcaption>Inv.-Nr. {esc(o['inv'])}{' · ' + esc(place[:70]) if place else ''}<a class="more" href="review/index.html#o-{safe}">Ganzer Eintrag in der Gesamtliste →</a></figcaption></figure>
<div class="body"><h4>{esc(o['name'])}</h4>
<div class="chips">{chips}</div>
<p>{esc(notes(o, res))}</p>
<p class="lab">Ähnlichste Objekte in anderen Sammlungen</p>
<div class="nbs">{''.join(nbs)}</div></div></article>"""

    groups = "".join(   # heading + first card stay together (no orphaned heading at a page end)
        f'<section class="grp"><div class="keep"><h3>{esc(t)}</h3><p class="gl">{esc(d)}</p>{card(objs[sigs[0]])}</div>'
        f'{"".join(card(objs[s]) for s in sigs[1:])}</section>'
        for t, d, sigs in GROUPS)
    refmix = {"phil": "Mapping Philippine Material Culture", "mrz": "Museum Rietberg",
              "cma": "Cleveland Museum of Art", "si": "Smithsonian", "md": "museum-digital (Berlin, Bremen)",
              "mkb": "Museum der Kulturen Basel (PARC)", "prm": "Pitt Rivers Museum"}
    sources = ", ".join(f"{refmix.get(k, k)} ({v})" for k, v in sorted(res["ref"].items(), key=lambda kv: -kv[1]))
    page = f"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bildähnlichkeit fürs Umbenennen</title>
<meta name="description" content="GLAMhack 2026, «To Be Renamed!»: erste Resultate der Bildähnlichkeitssuche für Objekte des Völkerkundemuseums der Universität Zürich.">
<style>
:root{{--bg:#fbfaf7;--fg:#1c1b19;--mut:#66645e;--line:#e4e1d8;--card:#fff;--chip:#efece4;--sup:#d5ebd7;--pos:#f2e7c9;--acc:#8a3b12}}
@media (prefers-color-scheme: dark){{:root:not([data-theme="light"]){{--bg:#181816;--fg:#ecebe6;--mut:#a3a199;--line:#38372f;--card:#22211e;--chip:#32312b;--sup:#22412a;--pos:#463c20;--acc:#e7a072}}}}
:root[data-theme="dark"]{{--bg:#181816;--fg:#ecebe6;--mut:#a3a199;--line:#38372f;--card:#22211e;--chip:#32312b;--sup:#22412a;--pos:#463c20;--acc:#e7a072}}
*{{box-sizing:border-box}}
body{{background:var(--bg);color:var(--fg);font:16px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;margin:0}}
main{{max-width:1040px;margin:0 auto;padding:32px 16px 48px}}
.kicker{{color:var(--acc);font-size:13px;font-weight:600;letter-spacing:.02em;margin:0 0 6px}}
h1{{font-size:clamp(28px,4vw,40px);line-height:1.15;margin:0 0 14px;letter-spacing:-.01em}}
h2{{font-size:22px;margin:40px 0 12px}} h3{{font-size:19px;margin:28px 0 2px}} h4{{font-size:17px;margin:0 0 8px}}
.lead{{font-size:18px;max-width:780px;margin:0}} .gl{{color:var(--mut);margin:0 0 12px}}
.figs{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin:28px 0 8px}}
.fig{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}}
.fig b{{display:block;font-size:30px;line-height:1.1;font-variant-numeric:tabular-nums}} .fig span{{color:var(--mut);font-size:14px}}
ol.steps{{padding-left:20px;max-width:820px}} ol.steps li{{margin:6px 0}}
.ex{{display:grid;grid-template-columns:210px 1fr;gap:20px;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;margin:12px 0;break-inside:avoid}}
.q{{margin:0}} .q img{{width:100%;aspect-ratio:1;object-fit:contain;background:#fff;border-radius:8px}}
.q figcaption{{font-size:12px;color:var(--mut);margin-top:6px}} .q .more{{display:block;margin-top:4px}} .prt{{display:none}}
.body p{{margin:6px 0}} .lab{{font-size:12px;color:var(--mut);font-weight:600;margin-top:10px!important}}
.chips{{display:flex;flex-wrap:wrap;gap:6px}}
.chip{{background:var(--chip);border-radius:999px;padding:2px 10px;font-size:13px}} .chip.sup{{background:var(--sup)}} .chip.pos{{background:var(--pos)}}
.chip i{{font-style:normal;color:var(--mut)}}
.nbs{{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px}}
.nb{{display:flex;flex-direction:column;gap:2px;text-decoration:none;color:inherit;font-size:12px;line-height:1.3}}
.nb img{{width:100%;aspect-ratio:1;object-fit:contain;background:#fff;border:1px solid var(--line);border-radius:6px}}
.nbn{{font-weight:600}} .nbh{{color:var(--mut)}}
.noimg{{width:100%;aspect-ratio:1;display:flex;align-items:center;justify-content:center;text-align:center;font-size:11px;color:var(--mut);background:var(--chip);border:1px solid var(--line);border-radius:6px;padding:6px}}
ul.learn li{{margin:6px 0}} .links{{display:flex;flex-wrap:wrap;gap:10px;margin:8px 0}}
.links a{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px 14px;color:inherit;text-decoration:none;font-weight:600}}
.links a:hover{{border-color:var(--acc)}}
footer{{color:var(--mut);font-size:13px;border-top:1px solid var(--line);margin-top:40px;padding-top:14px}}
a{{color:var(--acc)}}
@media (max-width:640px){{.ex{{grid-template-columns:1fr}} .q img{{max-width:280px}} .nbs{{grid-template-columns:repeat(3,minmax(0,1fr))}}}}
@media print{{@page{{size:A4;margin:12mm 13mm}} :root{{--bg:#fff;--card:#fff;--chip:#efece4;--sup:#d5ebd7;--pos:#f2e7c9;--fg:#1c1b19;--mut:#5d5b55;--line:#dedad0;--acc:#8a3b12}}
 body{{font-size:9.5pt;line-height:1.4}} main{{padding:0;max-width:none}} .links,.q .more{{display:none}} .prt{{display:inline}} .scr{{display:none}}
 h1{{font-size:20pt;margin:0 0 8px}} .lead{{font-size:10pt}} h2{{font-size:13pt;margin:12px 0 4px}} h3{{font-size:11.5pt;margin:0 0 2px}} h4{{font-size:10.5pt;margin:0 0 4px}}
 .figs{{grid-template-columns:repeat(4,1fr);gap:8px;margin:10px 0 2px}} .fig{{padding:6px 10px}} .fig b{{font-size:16pt}} .fig span{{font-size:8pt}}
 ol.steps{{font-size:8.8pt;margin:4px 0}} .gl{{margin:0 0 6px}}
 .ex{{grid-template-columns:32mm 1fr;padding:8px 10px;gap:10px;margin:6px 0}} .q figcaption{{font-size:7.5pt}}
 .chip{{font-size:8.5pt;padding:1px 8px}} .nb{{font-size:7pt;line-height:1.25}} .nbs{{grid-template-columns:repeat(5,21mm);gap:5px}}
 .nbn{{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}}
 .nbh{{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}}
 .ex{{grid-template-columns:28mm 1fr}} .body p{{margin:3px 0}} .lab{{margin-top:5px!important}} ol.steps li{{margin:3px 0}}
 .keep{{break-inside:avoid}} h2.learnh{{break-before:page}}}}
{FEEDBACK_CSS}</style></head><body>{feedback_html("")}<main>
<p class="kicker">GLAMhack 2026 · Challenge «To Be Renamed!» · Völkerkundemuseum der Universität Zürich</p>
<h1>Bildähnlichkeit als Hilfe beim Umbenennen</h1>
<p class="lead">Für {res['n']} Objekte mit unsicheren oder generischen Namen ({grp_text}) haben wir die Fotos mit
{n_ref} Objekten aus anderen Sammlungen und mit {res['vocab']} Begriffen aus dem eigenen Katalog verglichen.
<span class="scr">Erste Resultate, Stand 13. November 2026.</span><span class="prt">Stand 13.11.2026 · <a href="{SITE}">{SITE.removeprefix('https://').rstrip('/')}</a></span></p>
<div class="figs">
<div class="fig"><b>{res['n']}</b><span>Objekte mit Foto aus den Challenge-Daten</span></div>
<div class="fig"><b>{n_ref}</b><span>Vergleichsobjekte aus anderen Sammlungen</span></div>
<div class="fig"><b>{st.get('hyp_sup', 0) / hn:.0%}</b><span>der {st.get('hyp_n', 0)} «?»-Hypothesen vom Foto klar gestützt</span></div>
<div class="fig"><b>≈ 2 Min.</b><span>Rechenzeit für alle Vorschläge auf einem Laptop</span></div>
</div>
<div class="links"><a href="review/index.html">Alle {res['n']} VMZ-Objekte durchsehen</a>{f'<a href="review/mkb.html">Alle {n_mkb} MKB-Objekte</a>' if n_mkb else ''}<a href="review/vmz_suggestions.xlsx">Vorschläge als Excel</a><a href="{ZIP}">Offline-Version (ZIP)</a><a href="{REPO}">Code und Methode</a></div>

<h2>So funktioniert es</h2>
<ol class="steps">
<li><b>Ähnliche Objekte finden.</b> Zwei Bildmodelle (SigLIP 2, DINOv2) suchen zu jedem Foto die ähnlichsten Objekte in anderen Sammlungen – mit deren Namen, Museum und Link.</li>
<li><b>Eigene Begriffe vorschlagen.</b> Ein Bild-Text-Modell ordnet alle {res['vocab']} Typbegriffe aus den Objektnamen des VMZ-Katalogs nach ihrer Passung zum Foto. Dafür werden die Begriffe maschinell ins Englische übersetzt, weil das Modell Englisch viel besser versteht. Ebenso mit den englischen Objektnamen der Vergleichssammlungen.</li>
<li><b>«?»-Hypothesen prüfen.</b> Jeder Begriff im aktuellen Namen bekommt seinen Rang unter allen Begriffen: Top 2 % (Rang ≤ {res['sup']}) = vom Foto gestützt, Top 10 % (≤ {res['pos']}) = möglich.</li>
<li><b>Geografische Nähe als zweite Schicht.</b> Unter den visuell ähnlichsten Objekten werden zusätzlich die aus derselben Weltregion bzw. demselben Land gezeigt. Die Herkunft stammt aus dem VMZ-Katalog und aus den Angaben der anderen Museen (Länder, Regionen, Ethnien – zugeordnet über den VMZ-Katalog selbst).</li>
</ol>

<h2>Vielversprechende Beispiele</h2>
{groups}

<h2 class="learnh">Was wir gelernt haben</h2>
<ul class="learn">
<li><b>Ähnliche Objekte sind der stärkste Hinweis</b> – sofern der Vergleichsbestand den Objekttyp enthält. Sie zeigen auch, wie andere Museen ein Objekt benennen.</li>
<li><b>«Gestützt» ist ein starkes Indiz</b> (zufällig nur 2 %), <b>«nicht gestützt» nur ein schwaches</b>: Auch sichere Begriffe aus den aktuellen Namen sind nur bei {st.get('type_sup', 0) / tn:.0%} gestützt, besonders seltene Fachwörter fallen durch.</li>
<li><b>Deutsche Fachbegriffe müssen übersetzt werden.</b> Mit Übersetzung landet der richtige Typbegriff im Mittel auf Rang {st.get('type_ranks') or '–'} statt 809 (von {res['vocab']}). Seltene Wörter wie «Worfel» kennt aber auch die Übersetzung nicht.</li>
<li><b>Geografische Nähe ist {geo_word}.</b> Bei {st.get('geo_with_layer', 0)} Objekten gibt es mindestens fünf visuell ähnliche Objekte aus derselben Weltregion. Deren Namen bestätigen den Typbegriff in {pct(st.get('geo_type_l2', 0), st.get('geo_type_n', 0))} der Fälle (rein visuell: {pct(st.get('geo_type_l1', 0), st.get('geo_type_n', 0))}), die «?»-Hypothese in {pct(st.get('geo_hyp_l2', 0), st.get('geo_hyp_n', 0))} (rein visuell: {pct(st.get('geo_hyp_l1', 0), st.get('geo_hyp_n', 0))}). Die regionale Liste zeigt dafür Vergleichsstücke aus demselben kulturellen Umfeld.</li>
{fig_bullet}
<li><b>Anführungszeichen markieren meist Bildtitel</b> («Bild: „Abendmahl“»). Dort trägt die Methode nur Technikbegriffe bei (Malerei auf Reispapier, Blockdruck).</li>
<li><b>Ethnografische Sammlungen mit deutschen Typbezeichnungen bringen am meisten.</b> Vergleichsbestand: {esc(sources)}. 12317 zusätzliche CC0-Objekte aus Cleveland und Smithsonian machen die ähnlichsten Objekte deutlich näher (Asien 0.781 → 0.805, Amerika 0.823 → 0.850), die Namen der Nachbarn bestätigen den Typbegriff aber kaum häufiger (14 % → 16 %): Kunstmuseen benennen mit Titeln statt Objekttypen. Nur 3171 Objekte via museum-digital (Ethnologisches Museum Berlin, Übersee-Museum Bremen, Museum Europäischer Kulturen) heben die Bestätigung dagegen auf 20 % («?»-Hypothesen 8 % → 11 % → 14 %).</li>
</ul>

<h2>Wie weiter</h2>
<ul class="learn">
<li>Fachpersonen prüfen die Vorschläge in der <a href="review/index.html">Gesamtliste</a> (Filter nach «?», Anführungszeichen und «Figur» sowie nach Hypothesen-Status).</li>
<li>Vergleichsbestand gezielt um ethnografische Sammlungen mit Typbezeichnungen ausbauen: mehr aus museum-digital (das Ethnologische Museum Berlin hat dort rund 77000 Objekte), vom Museum der Kulturen Basel auch die Bestände ausserhalb Afrikas mit Bildern (bisher: Afrika via PARC und die Philippinen; Europa nur als Text), Exporte des Museums Rietberg.</li>
<li>Beim Pitt Rivers Museum eine Bildlizenz anfragen: Seine Bilder fliessen in die Ähnlichkeitssuche ein, dürfen online aber nicht gezeigt werden.</li>
<li>Text einbeziehen: Eingangsbuch-Einträge und einheimische Namen sind oft der stärkste Einzelhinweis.</li>
</ul>

<footer><p>Vorschläge sind Hinweise, keine Entscheidungen – entscheiden muss die Fachperson. Vergleichsbestände enthalten auch veraltete oder koloniale Bezeichnungen.</p>
<p>Fotos der VMZ-Objekte: © Völkerkundemuseum der Universität Zürich. Vergleichsbilder als Miniaturen mit Link zur Quelle: Cleveland Museum of Art und Smithsonian (CC0), Museum Rietberg (CC BY-SA), via museum-digital: Ethnologisches Museum, Staatliche Museen zu Berlin (CC BY-NC-SA) und Übersee-Museum Bremen (CC BY-SA), Mapping Philippine Material Culture (© die besitzenden Museen). Museum der Kulturen Basel (auch via PARC, Universität Basel): Bilder mit Einverständnis des MKB, Quellennachweis «Museum der Kulturen Basel». Pitt Rivers Museum: nur Name und Link, Bilder aus Rechtegründen nicht gezeigt. Code: <a href="{REPO}">{REPO.replace('https://', '')}</a>.</p></footer>
</main></body></html>"""
    (out / "index.html").write_text(page, encoding="utf-8")
    print("wrote", out / "index.html", "with", sum(len(s) for _, _, s in GROUPS), "examples")


if __name__ == "__main__":
    main()
