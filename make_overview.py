"""Overview page for the challenge owners: the most promising results on one page (+ PDF via Chrome).

Reads the results of suggest_vmz.py (OUT/vmz_results.json) and writes docs/index.html with images in
docs/img/. The examples below are chosen by hand; all numbers (ranks, status, neighbours) come from the
results file, so the page stays correct after a re-run. Check the hand-written sentences after a re-run.

Usage: python make_overview.py --data DATA_DIR --results docs/review/vmz_results.json --out docs
"""
import argparse
import html
import json
import re
from collections import Counter
from pathlib import Path

from PIL import Image

REPO = "https://github.com/ruedtim/glamhack26-similar-search"
GROUPS = [
    ("Ähnliche Objekte liefern den Fachbegriff",
     "Die visuell ähnlichsten Objekte aus anderen Sammlungen tragen oft schon den passenden Namen.",
     ["00273", "00145ad"]),
    ("Die «?»-Hypothese wird vom Foto gestützt",
     "Der unsichere Begriff gehört zu den 2 % der VMZ-Begriffe, die am besten zum Foto passen – "
     "oft tragen auch die ähnlichsten Objekte diesen Namen.",
     ["o.Nr.4211", "o.Nr.4101", "24472"]),
    ("Gegenvorschlag, wo die Hypothese nicht passt",
     "Der Begriff im Namen passt kaum zum Foto, dafür andere Begriffe aus dem eigenen Katalog.",
     ["o.Nr.5388", "08413.002", "o.Nr.2607"]),
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
    if inv == "00273":
        ww = [x for x in nn if "winnowing" in x["name"].lower()]
        n_ww = sum(x["count"] for x in ww)
        rest = [x["name"].split(" | ")[0] for x in nn if "winnowing" not in x["name"].lower()]
        rest = list(dict.fromkeys(rest))[:3]
        worf = (f"ist eine Worfel ({quoted(x['name'] for x in ww)})" if n_ww == 1 else
                f"sind {n_ww} Worfeln ({quoted(x['name'] for x in ww)})")
        return (f"Unter den 12 ähnlichsten Objekten {worf}, die übrigen heissen {quoted(rest)}. Das Bild-Text-Modell "
                f"kennt das seltene Wort «Worfel» nicht (Rang {rank(o, 'Worfel')}) – den Begriff liefert nur der "
                f"Vergleich mit anderen Sammlungen.")
    if inv == "00145ad":
        gw = sum(x["count"] for x in nn if "goldgewicht" in x["name"].lower())
        return (f"{'Alle 12' if gw == 12 else f'{gw} der 12'} ähnlichsten Objekte sind Goldgewichte aus dem "
                f"Museum Rietberg: Wenn der Vergleichsbestand den Objekttyp enthält, sind die Treffer sehr genau.")
    if inv == "o.Nr.4211":
        k = sum("haarnadel" in n for n in names5)
        return (f"«Haarnadel» steht auf Rang {rank(o, 'Haarnadel')} von {v}; {k} der 5 ähnlichsten Objekte sind "
                f"Haarnadeln aus dem Museum Rietberg.")
    if inv == "o.Nr.4101":
        first = nb[0]
        lead = (f"das ähnlichste Objekt ist eine «{first['name']}» ({first['holder'].replace('The ', '')})"
                if "harpoon" in first["name"].lower() else "unter den ähnlichsten Objekten ist eine Harpune")
        others = Counter(re.sub(r"^[A-Z]\d+/?\d*\s+", "", n["name"]) for n in nb[1:])
        rest = ", ".join(f"{c}× «{k}»" if c > 1 else f"«{k}»" for k, c in others.most_common())
        return f"«Harpune» steht auf Rang {rank(o, 'Harpune')} von {v}; {lead}, dazu {rest}."
    if inv == "24472":
        suz = next((n for n in nb if "suzani" in n["name"].lower()), None)
        nat = " und ".join("«" + m["term"] + "»" for m in o["native_matches"][:2])
        return (f"«Bettüberwurf» steht auf Rang {rank(o, 'Bettüberwurf')} von {v}."
                + (f" Das ähnlichste Objekt ist ein «{suz['name']}» ({suz['holder']})." if suz else "")
                + f" Der einheimische Name «susani» kommt im VMZ-Katalog bei weiteren Objekten vor – dort als {nat}.")
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
        return (f"«Rassel» nur Rang {rank(o, 'Rassel')} von {v}. Unter den fünf passendsten VMZ-Begriffen sind "
                f"Messingglocke, Kuhglocke, Schelle und Glocke" + (f", englisch {quoted(bell[:2])}" if bell else "")
                + ": eher eine Glocke?")
    raise KeyError(inv)


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
    label = {"sup": "gestützt", "pos": "möglich", "no": "nicht gestützt"}

    def card(o):
        safe = re.sub(r"[^\w.-]+", "_", o["inv"])
        q = img(data / o["img"], out / "img" / f"q_{safe}.jpg", 420)
        chips = "".join(
            f'<span class="chip {status(t["rank"], res)}">{esc(t["term"])}{" " + t["mark"] if t["mark"] else ""}'
            f' <b>#{t["rank"]}</b> <i>{label[status(t["rank"], res)]}</i></span>'
            for t in o["terms"] if t["mark"] == "?")
        nbs = []
        for nb in o["neighbours"][:5]:
            t = img(data / nb["img"], out / "img" / ("r_" + re.sub(r"[^\w.-]+", "_", nb["id"]) + ".jpg"), 240)
            nbs.append(f'<a class="nb" href="{esc(nb["url"])}" target="_blank" rel="noopener">'
                       f'<img src="{t}" alt="" loading="lazy"><span class="nbn">{esc(nb["name"][:48])}</span>'
                       f'<span class="nbh">{esc(short_holder(nb["holder"]))}</span></a>')
        place = ", ".join(x for x in (o.get("culture"), o.get("country")) if x and x != "(ohne Zuordnung)")
        return f"""<article class="ex">
<figure class="q"><img src="{q}" alt="Foto des Objekts {esc(o['inv'])}"><figcaption>Inv.-Nr. {esc(o['inv'])}{' · ' + esc(place[:70]) if place else ''}</figcaption></figure>
<div class="body"><h4>{esc(o['name'])}</h4>
<div class="chips">{chips}</div>
<p>{esc(notes(o, res))}</p>
<p class="lab">Ähnlichste Objekte in anderen Sammlungen</p>
<div class="nbs">{''.join(nbs)}</div></div></article>"""

    groups = "".join(
        f'<section class="grp"><h3>{esc(t)}</h3><p class="gl">{esc(d)}</p>{"".join(card(objs[s]) for s in sigs)}</section>'
        for t, d, sigs in GROUPS)
    refmix = {"phil": "Mapping Philippine Material Culture", "mrz": "Museum Rietberg",
              "cma": "Cleveland Museum of Art", "si": "Smithsonian", "md": "museum-digital (Berlin, Bremen)"}
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
.q figcaption{{font-size:12px;color:var(--mut);margin-top:6px}}
.body p{{margin:6px 0}} .lab{{font-size:12px;color:var(--mut);font-weight:600;margin-top:10px!important}}
.chips{{display:flex;flex-wrap:wrap;gap:6px}}
.chip{{background:var(--chip);border-radius:999px;padding:2px 10px;font-size:13px}} .chip.sup{{background:var(--sup)}} .chip.pos{{background:var(--pos)}}
.chip i{{font-style:normal;color:var(--mut)}}
.nbs{{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px}}
.nb{{display:flex;flex-direction:column;gap:2px;text-decoration:none;color:inherit;font-size:12px;line-height:1.3}}
.nb img{{width:100%;aspect-ratio:1;object-fit:contain;background:#fff;border:1px solid var(--line);border-radius:6px}}
.nbn{{font-weight:600}} .nbh{{color:var(--mut)}}
ul.learn li{{margin:6px 0}} .links{{display:flex;flex-wrap:wrap;gap:10px;margin:8px 0}}
.links a{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px 14px;color:inherit;text-decoration:none;font-weight:600}}
.links a:hover{{border-color:var(--acc)}}
footer{{color:var(--mut);font-size:13px;border-top:1px solid var(--line);margin-top:40px;padding-top:14px}}
a{{color:var(--acc)}}
@media (max-width:640px){{.ex{{grid-template-columns:1fr}} .q img{{max-width:280px}} .nbs{{grid-template-columns:repeat(3,minmax(0,1fr))}}}}
@media print{{@page{{size:A4;margin:12mm 13mm}} :root{{--bg:#fff;--card:#fff;--chip:#efece4;--sup:#d5ebd7;--pos:#f2e7c9;--fg:#1c1b19;--mut:#5d5b55;--line:#dedad0;--acc:#8a3b12}}
 body{{font-size:9.5pt;line-height:1.4}} main{{padding:0;max-width:none}} .links{{display:none}}
 h1{{font-size:22pt}} .lead{{font-size:11pt}} h2{{font-size:14pt;margin:16px 0 6px}} h3{{font-size:12pt;margin:0 0 2px}} h4{{font-size:10.5pt;margin:0 0 4px}}
 .figs{{grid-template-columns:repeat(4,1fr);gap:8px;margin:14px 0 4px}} .fig{{padding:8px 10px}} .fig b{{font-size:18pt}} .fig span{{font-size:8.5pt}}
 .ex{{grid-template-columns:32mm 1fr;padding:8px 10px;gap:10px;margin:6px 0}} .q figcaption{{font-size:7.5pt}}
 .chip{{font-size:8.5pt;padding:1px 8px}} .nb{{font-size:7pt;line-height:1.25}} .nbs{{grid-template-columns:repeat(5,21mm);gap:5px}}
 .nbn{{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}}
 .nbh{{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}}
 .ex{{grid-template-columns:28mm 1fr}} .body p{{margin:3px 0}} .lab{{margin-top:5px!important}} ol.steps li{{margin:3px 0}}
 .grp{{break-before:page}} section.grp:first-of-type{{break-before:auto}} h2.learnh{{break-before:page}}}}
</style></head><body><main>
<p class="kicker">GLAMhack 2026 · Challenge «To Be Renamed!» · Völkerkundemuseum der Universität Zürich</p>
<h1>Bildähnlichkeit als Hilfe beim Umbenennen</h1>
<p class="lead">Für {res['n']} Objekte, deren Namen ein «?» oder Anführungszeichen enthalten, haben wir die Fotos mit
{n_ref} Objekten aus anderen Sammlungen und mit {res['vocab']} Begriffen aus dem eigenen Katalog verglichen.
Erste Resultate, Stand 13. November 2026.</p>
<div class="figs">
<div class="fig"><b>{res['n']}</b><span>Objekte mit Foto aus der Challenge-Stichprobe</span></div>
<div class="fig"><b>{n_ref}</b><span>Vergleichsobjekte aus anderen Sammlungen</span></div>
<div class="fig"><b>{st.get('hyp_sup', 0) / hn:.0%}</b><span>der {st.get('hyp_n', 0)} «?»-Hypothesen vom Foto klar gestützt</span></div>
<div class="fig"><b>≈ 2 Min.</b><span>Rechenzeit für alle Objekte auf einem Laptop</span></div>
</div>
<div class="links"><a href="review/">Alle {res['n']} Objekte durchsehen</a><a href="review/vmz_suggestions.xlsx">Vorschläge als Excel</a><a href="uebersicht.pdf">Diese Übersicht als PDF</a><a href="{REPO}">Code und Methode</a></div>

<h2>So funktioniert es</h2>
<ol class="steps">
<li><b>Ähnliche Objekte finden.</b> Zwei Bildmodelle (SigLIP 2, DINOv2) suchen zu jedem Foto die ähnlichsten Objekte in anderen Sammlungen – mit deren Namen, Museum und Link.</li>
<li><b>Eigene Begriffe vorschlagen.</b> Ein Bild-Text-Modell ordnet alle {res['vocab']} Typbegriffe aus den Objektnamen des VMZ-Katalogs nach ihrer Passung zum Foto. Dafür werden die Begriffe maschinell ins Englische übersetzt, weil das Modell Englisch viel besser versteht. Ebenso mit den englischen Objektnamen der Vergleichssammlungen.</li>
<li><b>«?»-Hypothesen prüfen.</b> Jeder Begriff im aktuellen Namen bekommt seinen Rang unter allen Begriffen: Top 2 % (Rang ≤ {res['sup']}) = vom Foto gestützt, Top 10 % (≤ {res['pos']}) = möglich.</li>
</ol>

<h2>Vielversprechende Beispiele</h2>
{groups}

<h2 class="learnh">Was wir gelernt haben</h2>
<ul class="learn">
<li><b>Ähnliche Objekte sind der stärkste Hinweis</b> – sofern der Vergleichsbestand den Objekttyp enthält. Sie zeigen auch, wie andere Museen ein Objekt benennen.</li>
<li><b>«Gestützt» ist ein starkes Indiz</b> (zufällig nur 2 %), <b>«nicht gestützt» nur ein schwaches</b>: Auch sichere Begriffe aus den aktuellen Namen sind nur bei {st.get('type_sup', 0) / tn:.0%} gestützt, besonders seltene Fachwörter fallen durch.</li>
<li><b>Deutsche Fachbegriffe müssen übersetzt werden.</b> Mit Übersetzung landet der richtige Typbegriff im Mittel auf Rang {st.get('type_ranks') or '–'} statt 809 (von {res['vocab']}). Seltene Wörter wie «Worfel» kennt aber auch die Übersetzung nicht.</li>
<li><b>Anführungszeichen markieren meist Bildtitel</b> («Bild: „Abendmahl“»). Dort trägt die Methode nur Technikbegriffe bei (Malerei auf Reispapier, Blockdruck).</li>
<li><b>Ethnografische Sammlungen mit deutschen Typbezeichnungen bringen am meisten.</b> Vergleichsbestand: {esc(sources)}. 12317 zusätzliche CC0-Objekte aus Cleveland und Smithsonian machen die ähnlichsten Objekte deutlich näher (Asien 0.781 → 0.805, Amerika 0.823 → 0.850), die Namen der Nachbarn bestätigen den Typbegriff aber kaum häufiger (14 % → 16 %): Kunstmuseen benennen mit Titeln statt Objekttypen. Nur 3171 Objekte via museum-digital (Ethnologisches Museum Berlin, Übersee-Museum Bremen, Museum Europäischer Kulturen) heben die Bestätigung dagegen auf 20 % («?»-Hypothesen 8 % → 11 % → 14 %).</li>
</ul>

<h2>Wie weiter</h2>
<ul class="learn">
<li>Fachpersonen prüfen die Vorschläge in der <a href="review/">Gesamtliste</a> (Filter nach «?» / Anführungszeichen und nach Hypothesen-Status).</li>
<li>Vergleichsbestand gezielt um ethnografische Sammlungen mit Typbezeichnungen ausbauen: mehr aus museum-digital (das Ethnologische Museum Berlin hat dort rund 77000 Objekte), Exporte von MKB Basel, Museum Rietberg, Pitt Rivers Museum.</li>
<li>Text einbeziehen: Eingangsbuch-Einträge und einheimische Namen sind oft der stärkste Einzelhinweis.</li>
</ul>

<footer><p>Vorschläge sind Hinweise, keine Entscheidungen – entscheiden muss die Fachperson. Vergleichsbestände enthalten auch veraltete oder koloniale Bezeichnungen.</p>
<p>Fotos der VMZ-Objekte: © Völkerkundemuseum der Universität Zürich. Vergleichsbilder als Miniaturen mit Link zur Quelle: Cleveland Museum of Art und Smithsonian (CC0), Museum Rietberg (CC BY-SA), via museum-digital: Ethnologisches Museum, Staatliche Museen zu Berlin (CC BY-NC-SA) und Übersee-Museum Bremen (CC BY-SA), Mapping Philippine Material Culture (© die besitzenden Museen). Code: <a href="{REPO}">{REPO.replace('https://', '')}</a>.</p></footer>
</main></body></html>"""
    (out / "index.html").write_text(page, encoding="utf-8")
    print("wrote", out / "index.html", "with", sum(len(s) for _, _, s in GROUPS), "examples")


if __name__ == "__main__":
    main()
