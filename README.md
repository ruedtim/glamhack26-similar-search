# Similar Search – feasibility PoC for «To Be Renamed!» (GLAMhack 2026, project 321)

**Results (German):** [overview of the most promising results](https://ruedtim.github.io/glamhack26-similar-search/)
([PDF](https://ruedtim.github.io/glamhack26-similar-search/uebersicht.pdf)) and
[all 748 objects with suggestions](https://ruedtim.github.io/glamhack26-similar-search/review/)
([Excel](https://ruedtim.github.io/glamhack26-similar-search/review/vmz_suggestions.xlsx)).

The raw challenge data (VMZ catalogue export as Excel, «Objektliste» PDFs) is **not** in this repository.

Question from the challenge: *Can image similarity searches help identify comparable objects in other
collections?* The idea is that comparable objects in other collections supply better object names
(e.g. «Bambusgitarre» → «Röhrenzither», «Figur» → «Gottheitsstatue»).

## Bottom line

**Feasible as a research aid that shows a curator evidence. Not as automatic renaming.**

- In this proxy test, image similarity puts the correct name among the 5 nearest neighbours in about
  55–68 % of cases. The prerequisite is that the name occurs in the reference set at all. Chance is about 2–3 %.
- Zero-shot naming against a fixed vocabulary (SigLIP 2, image↔term) is stronger than taking names
  from neighbours: Top-1 53 %, Top-5 78 %. The museum's own German vocabulary can serve as the term list.
- On the real slide objects: the «Figur auf Sockel» works well (neighbours: Chinese deity and tomb figures,
  including a «Daoist Immortal»; zero-shot: «Gottheitsstatue»). The «Bambusgitarre/Valiha» fails as a
  ~120 px thumbnail: the models see a bamboo stick. The British Museum tube zither only ranks 37th.
- The strongest single signal for the valiha is not the image but the text: «Eingangsbuch:
  Bambusguitarre (Valiha)». So the method should be **multimodal**: image + old inventory entries /
  emic names + region.
- **Real sample (748 VMZ objects with «?» or quotation marks, see below):** the pipeline runs end to end
  in ~2 min at half GPU load. It gives useful evidence for many objects: supported or unsupported «?»
  hypotheses, more specific terms from the museum's own vocabulary, and convincing neighbours (winnowing
  trays for «Korb (Worfel?)»). German terms have to be machine-translated to English before SigLIP 2
  ranks them well. The coverage of the reference set is the main limit.

## Proxy evaluation

487 objects from «Mapping Philippine Material Culture» with known names act as queries. Their nearest
neighbours come only from *other* museums (other holder in the Phil database), or only from the
Cleveland Museum of Art. Names are compared on the English head noun («Wooden Figure» → figure).
Synonyms (kampilan vs. sword) count as wrong, so the values are a lower bound.

| Model | Setting | Name present in reference set | P@1 | Hit@5 | Chance P@1 |
|---|---|---|---|---|---|
| SigLIP 2 | Phil → Phil (other museum) | 80 % | 33 % | 54 % | 1.8 % |
| DINOv2 | Phil → Phil (other museum) | 80 % | 30 % | 57 % | 1.8 % |
| SigLIP 2 | Phil → Cleveland | 46 % | 47 % | 68 % | 3.1 % |
| DINOv2 | Phil → Cleveland | 46 % | 47 % | 68 % | 3.1 % |

P@1/Hit@5 are computed over queries whose name occurs in the reference set. Phil → Cleveland is
dominated by «figure» (81 figures at CMA), so it is optimistic. Coverage is the real bottleneck:
anything missing from the reference set cannot be found.

## Data access of the comparison databases (as of 13.11.2026, only landing pages checked)

| Database | Technical | Assessment |
|---|---|---|
| Mapping Philippine Material Culture | Omeka REST API, open, JSON + images; 10,481 objects from 97 collections (incl. MKB Basel, British Museum, Penn, Field Museum) | **Usable immediately.** Image rights stay with the holding museum |
| Museum Rietberg | Website with MuseumPlus integration; **open data on opendata.swiss** (e.g. 932 Himmelheber objects with German titles + photo links, CC BY) | Partly usable immediately, ask for an export for the rest |
| Pitt Rivers Museum | React app on an internal API that needs a key from the web frontend | Not used. Ask for an export |
| Museum der Kulturen Basel | «CollectionConnection» (TMS) with an internal backend; **«Sammlung Europa» as open data** (data.bs.ch, CC BY) | Ask for an export. Partly covered via the Phil database |
| Yukon «Searching for our heritage» | Cloudflare bot protection (HTTP 403) | Only through cooperation |
| Amutat (Alutiiq Museum) | CollectiveAccess, 387 objects, images directly as JPG | Technically easy, but Indigenous heritage: ask first (CARE principles) |
| Extra: Cleveland Museum of Art | Open Access API, CC0 | Usable immediately |
| Extra: Smithsonian Open Access | Bulk JSON metadata on the AWS Registry of Open Data; images via ids.si.edu, CC0 | Freer\|Sackler (Asia) and National Museum of African Art usable. The NMNH Anthropology dump contains no CC0 images |
| Museum Rietberg, further open data | «Kamerun» (CC0, but no image links), «Patolu» (Indian textiles) and «Drenowatz» (Chinese painting), both with image ZIPs (CC BY-SA) | Kamerun images only on the website: ask. Patolu/Drenowatz not used (narrow topics) |
| Extra: The Met | `/search` returned no results for automated access | Not pursued further |

## Dry run with 17 real UZH objects (13.11.2026)

The real UZH sample is not public. But «Mapping Philippine Material Culture» has 17 UZH objects
(Omeka collection 439) with photo, inventory number and accession register note. Reference set:
3,163 objects from other collections (1,770 Phil from other museums, 893 Museum Rietberg/Himmelheber
open data with German titles, 500 Cleveland). Result page: `uzh_review.html`.

- **Object type recognised:** 15 of 17 via the neighbours, 16 of 17 with English zero-shot added
  («Hatchet» → «axe-adze, axe»). Fails: «Lario» (childbirth implement made of clay), because
  there is nothing comparable in the reference set.
- **More specific candidate names** for a curator to check: Hat → «Sun hat», «Woven bamboo hat, domed»;
  Axe → «Head axe», «Axe-adze», «Igorot axe»; piña handkerchiefs → «Alampay (Fichu, Pañuelo)»,
  «Man's Head Kerchief», «Manila Shawl»; Coconut Shell Tabó → «Coconut container».
- **German zero-shot depends heavily on the prompt template.** «ein Foto von einem Museumsobjekt: Hut» puts
  «Hut» only at rank 12–67. «Hut, ein ethnografisches Museumsobjekt» puts it at rank 1 (all 3 hats).
  The same goes for «Taschentuch» and «Kokosnussschale». «Axt» stays weak in German (rank ~15), but English works well.
- **Vocabulary:** the long Rietberg titles («Stoffband für einen Hüftrock …») add noise.
  For the real use, use the UZH's own short object terms as the vocabulary. Long, descriptive terms
  pull matches towards themselves (hubness): `suggest.py` therefore subtracts each term's mean similarity.

Caveat: these 17 objects already carry fairly specific English names (recorded in 2014). The test
checks object type and more specific alternatives, not renaming of German generic names.

## Real GLAMhack sample: 748 VMZ objects with «?» or quotation marks (13.11.2026)

Data from the challenge (the raw files are not in this repository):
- the catalogue export of the Völkerkundemuseum: 62,597 objects with 39 fields (name, native name, use,
  region, ethnic group, accession register, description, material …);
- two «Objektliste kompakt» PDFs with one studio photo per object: 524 pages for names with «?» and 244
  for names with quotation marks.

The PostScript print splits each photo into bands, which are merged again. Objects that appear in both
PDFs are merged too. That leaves **748 objects with a photo** (16 pages have none):
- 639 match the catalogue exactly;
- 107 are sub-objects (`05072b`, `00853.001`) that are only catalogued under the main number;
- 2 have no match.

Per object, `suggest_vmz.py` computes:
- **neighbours** in the reference set (3,163 objects from other collections), as before;
- **the museum's own vocabulary**: 2,434 type terms from the catalogue names that occur at least 3 times
  («Korb (Worfel?)» → «Korb», «Figur; Ton» → «Figur»), ranked against the photo with SigLIP 2;
- **hypothesis check**: every term in the current name gets its rank in that vocabulary
  («Korb (Worfel?)» → Korb #5, Worfel #397);
- **catalogue text signal**: other objects with the same native name. Only 50 of the 748 objects have
  one; 37 of them get matches (e.g. «susani» → Tuch, Stickerei).

Findings:
- **The German terms have to be machine-translated first.** Test case: the certain type term of the
  current name, e.g. «Korb» in «Korb (Worfel?)» (n = 370). As German text it reaches a median rank of
  only 809 of 2,434.
  - Method: the vocabulary is translated with opus-mt-de-en on the CPU (~45 s), inside the context
    «Ethnografische Sammlung: Maske, Trommel, {Begriff}».
  - After translation the median rank is 139: 16 % in the top 8, 34 % in the top 2 % (rank ≤ 49),
    28 % in the top 10 %.
  - Translation errors stay visible («Bauchaufschlitzer» → ventilator), so the page shows the
    translation that was used.
- **Calibration:** «supported» (top 2 %) is strong evidence, since a random term lands there 2 % of the
  time. «Not supported» is weak evidence: 38 % of the certain terms end up there too. Of the 475 «?»
  hypotheses, 31 % are supported and 29 % possible. That is about as often as for the certain terms, so
  the photos rarely contradict the curators' guesses.
- **Examples:**

  | Current name | Result |
  |---|---|
  | «Spitze, Stein (Pfeilspitze ?)» | Pfeilspitze #3; suggestions «Obsidian-Spitze», «Pfeilkopf» |
  | «Speerspitze / Harpune?» | Harpune #10; neighbours Ifugao spear, harpoon |
  | «Statue: Dharmapāla (Mahākāla?)» | Mahākāla #1 |
  | «Gürtel [Penisbinde?]» | Penisbinde #2 |
  | «Behälter (Mörser?)» | supported for 3 of 4 objects |
  | «Ornament ?» | #1106; arm cuff / bracelet terms instead |
  | «Rassel?» (o.Nr.2607) | #568; bell terms instead («Messingglocke», «Kuhglocke», «Schelle») |

- **Neighbours beat zero-shot for rare words.** For «Korb (Worfel?)» the translator doesn't know
  «Worfel» (rank #397). But the visual neighbours include «Winnowing-Tray» ×2 and «Winnowing basket»
  (British Museum, via the Phil database), which is exactly a Worfel. For «Goldgewicht», 11 of
  12 neighbours are Baule gold weights from the Rietberg.
- **What the quotation marks mark:**
  - Mostly titles of pictures («Bild: „Abendmahl“»): here the method only adds technique terms
    («Malerei auf Reispapier», «Blockdruck»).
  - Colloquial names («Dolch („Bauchaufschlitzer“)»): here it adds type terms («Kurzschwert»,
    «Golok», «keris»).
- **Coverage is still the bottleneck.** The reference set is small and regionally skewed (Philippines,
  Côte d'Ivoire, a Cleveland sample). Many VMZ objects (India, Tibet, Oceania, the Americas) have no
  comparable object. The neighbours then only match by shape (spoons for paddles).

Outputs:
- `docs/index.html`: overview of the most promising examples (also as `docs/uebersicht.pdf`), made with
  `make_overview.py`.
- `docs/review/`: all objects, with search and filters for «?»/quotation marks and hypothesis status, plus
  `vmz_suggestions.xlsx` (one row per object for curators) and `vmz_results.json`.
- Both are published via GitHub Pages. They contain no accession register or description excerpts.
- Running `suggest_vmz.py` without `--public` writes an internal variant with those excerpts to
  `vmz_review/` (gitignored).

## Extended reference set: +12,317 CC0 objects (13.11.2026, afternoon)

`harvest_more.py` adds two CC0 sources:
- **Cleveland**: 7,477 objects from the departments Indian and Southeast Asian Art (incl. Tibet and
  Nepal), Oceania, African Art, Art of the Americas and Islamic Art, plus samples of Korean, Chinese and
  Japanese Art and Textiles.
- **Smithsonian** (bulk metadata on the AWS Registry of Open Data, only media marked CC0): 4,840 objects
  from Freer|Sackler, the National Museum of African Art and the National Museum of the American Indian.

Not used:
- NMNH Anthropology, whose open dump has no CC0 images;
- Rietberg «Kamerun», whose open data has no image links.

The reference set grows from 3,163 to 15,480 objects. `compare_refs.py` runs the same 748 VMZ objects
against the old and the new set (top-5 neighbours, rank fusion):

| | old set | new set |
|---|---|---|
| similarity of the nearest neighbour (median) | 0.813 | 0.828 |
| nearest neighbour ≥ 0.85 | 24 % | 33 % |
| type term of the current name among the top-5 neighbour names (n = 447) | 15 % | 16 % |
| «?» hypothesis among the top-5 neighbour names (n = 475) | 10 % | 11 % |

Median similarity of the nearest neighbour by region: Asia 0.781 → 0.805 (n = 366), Americas
0.823 → 0.850, Africa 0.829 → 0.839.

- **Closer neighbours, but hardly better names.** 54 % of the top-5 neighbours now come from the new
  sources. Art museums often name objects with titles rather than object types («Page from the
  Prasnapradipa…», «Boy Bringing Wealth»), so the name matching barely changes. The name metric is a
  lower bound: synonyms count as misses.
- **Hubs:** some reference objects land in the top 5 for a great many photos (e.g. a Freer Gallery
  «Glass fragment» 158 times). `suggest_vmz.py` hides reference objects that are among the top 5 for
  ≥ 10 VMZ photos; that hides 31 objects.
  - The name metrics stay the same with this filter: 15.7 % and 10.7 %.
  - Also tested, not used: CSLS (subtracting each reference object's mean similarity to its 10 nearest
    VMZ photos). It reduces the hubs, but confirms fewer «?» hypotheses (10.5 % → 7.4 %).
- **Individual examples get much better:**
  - «Bettüberwurf (?)» → most similar object «Suzani: Divan Cover» (Cleveland);
  - «Gefäss(?), Perlhuhn» → 3 staff finials («Finial», Freer Gallery);
  - «Speerspitze / Harpune?» → «Harpoon» moves to rank 1.
- **Zero-shot shifts a little** (the hubness correction uses all images): median rank of the certain
  type term 157 instead of 139; 34 % supported, 27 % possible; «?» hypotheses 32 % supported, 29 % possible.
- **Conclusion:** ethnographic collections with object-type names would help most (exports from MKB,
  Rietberg, Pitt Rivers, or German-language collections on museum-digital), more than further
  art-museum data.

The published pages (`docs/`) use the extended set and the hub filter (see the museum-digital section below for the
current numbers).

## German type names from museum-digital (13.11.2026, evening)

`harvest_md.py` uses the open JSON API of museum-digital (robots.txt allows `/json/`). It searches the
**300 most frequent type terms of the whole VMZ catalogue**, not the terms of the 748 sample objects, and
keeps at most 12 objects per term and institution:

| Institution | Objects | Licence of the images |
|---|---|---|
| Ethnologisches Museum, Staatliche Museen zu Berlin | 1,557 | CC BY-NC-SA |
| Übersee-Museum Bremen (German names via `nat.museum-digital.de`) | 665 | CC BY-SA |
| Museum Europäischer Kulturen, Staatliche Museen zu Berlin | 949 | CC BY-NC-SA |

The licences were checked on samples of 6–12 objects per institution. The Ethnologisches Museum has about
77,000 objects on museum-digital, so this is only a small, targeted extract.

Effect on the 748 VMZ objects (top-5 neighbours, hub filter as on the published pages):

| | original (3,163) | + Cleveland/Smithsonian (15,480) | + museum-digital (18,651) |
|---|---|---|---|
| type term of the current name among the neighbour names (n = 447) | 14 % | 16 % | **20 %** |
| «?» hypothesis among the neighbour names (n = 475) | 8 % | 11 % | **14 %** |
| nearest neighbour ≥ 0.85 | 21 % | 32 % | 38 % |

- **What the gain shows:** 3,171 objects with German type names do more for the names than 12,317
  art-museum objects. Examples:
  - «Ornament ?» gets 3× «Armring» as neighbours;
  - «Speerspitze / Harpune?» gets «Pfeil» and «Speer» next to the British Museum «Harpoon»;
  - baskets get «Korbschale» and «Tablett».
- **Caveats:**
  - The search terms come from the VMZ catalogue, so the extract leans towards object types the VMZ
    has.
  - German names can be matched directly, while English names only match via the MT head noun.
- **Not every example improves.** For «Korb (Worfel?)» more ordinary baskets push the British Museum
  winnowing trays down: 1 instead of 3 among the 12 nearest.
- **The «Schnabelgeiss» (09947)** gets no comparable European custom figures. museum-digital has nothing
  under Schnabelgeiß, Habergeiß or Klapperbock. The closest functional match remains a Bamana
  hobbyhorse head (Cleveland).

## Run

```bash
uv venv --python 3.12 venv && uv pip install --python venv/bin/python torch transformers pillow numpy requests pymupdf sentencepiece protobuf openpyxl
venv/bin/python harvest.py --out data            # ~4 min, ~30 MB images (672 Phil + 500 CMA)
venv/bin/python harvest_extra.py --out data      # ~4 min: 17 UZH objects, +1,100 Phil, 932 Rietberg
GPU_SHARE=0.5 venv/bin/python embed.py --data data --queries queries   # incremental; queries/q_*.png
venv/bin/python evaluate.py --data data --queries queries --html results.html
GPU_SHARE=0.5 venv/bin/python suggest.py --data data --html uzh_review.html
# real VMZ sample (internal files from the challenge, gitignored)
venv/bin/python ingest_vmz.py --xlsx VMZ_Sammlungsobjekte_20261112_fuerGlamhack_.xlsx \
  --pdf VMZ_objects-with-questionmark.pdf --pdf VMZ_objects-with-quotation-marks.pdf --out data   # ~30 s
venv/bin/python harvest_more.py --out data      # more reference objects: Cleveland departments, Smithsonian (CC0)
venv/bin/python harvest_md.py --out data        # German type names: museum-digital (EM Berlin, Übersee-Museum, MEK)
GPU_SHARE=0.5 venv/bin/python embed.py --data data --queries queries                            # incremental
GPU_SHARE=0.5 venv/bin/python suggest_vmz.py --data data --public --out docs/review   # ~40 s (+ opus-mt-de-en on the first run)
venv/bin/python make_overview.py --data data --results docs/review/vmz_results.json --out docs
venv/bin/python compare_refs.py --data data --before data/records_before_more.jsonl   # old vs. new reference set
```

`GPU_SHARE=0.5` throttles the GPU to ~50 % load with a duty cycle (a pause after each batch, half the
CPU threads). It's quieter and takes about twice as long. `embed.py` only computes vectors for new objects.

`evaluate.py` was evaluated on the first reference set (1,172 objects), not yet on the extended one.

`results.html` and `uzh_review.html` are generated locally and not published (images © the respective museums).

- `harvest.py` – fetches images + names only from open, documented APIs (politely: max. 3–6 parallel requests).
- `models.py` – SigLIP 2 base (multilingual image–text) and DINOv2 base (visual only). Pads images
  to a square instead of cropping them, so long objects stay complete.
- `embed.py` – embeddings for the reference set and the query images (M2 Max/MPS: ~12 s per 1,000 images).
- `evaluate.py` – proxy metrics, zero-shot with German terms, and `results.html` with neighbours.
- `ingest_vmz.py` – imports the VMZ catalogue (Excel) and the photos from the «Objektliste» PDFs.
- `suggest_vmz.py` – suggestions for the VMZ objects: neighbours, VMZ vocabulary (via MT), hypothesis
  ranks, native names; writes the review page, Excel and JSON.
- `harvest_more.py` – more reference objects (Cleveland departments, Smithsonian Freer|Sackler, NMAfA, NMAI; CC0).
- `harvest_md.py` – reference objects with German type names from museum-digital (open JSON API).
- `compare_refs.py` – compares two reference sets on the VMZ objects (coverage and name confirmation).
- `make_overview.py` – the overview page for the challenge owners (`docs/index.html`).

The query images `q_uzh25744_figur_auf_sockel.png` and `q_uzh00001_bambusgitarre.png` are crops from
the challenge slides. `data/` and `venv/` are not in the repository; rebuild them with the commands above.

## Recommendation for the hackathon

1. **Reference set:** Phil database (API) + CC0 sources. At the hackathon, ask Rietberg, MKB and PRM directly for exports.
2. **Per object with a generic name:** show the top-k similar objects (with link and holding museum),
   plus SigLIP 2 zero-shot term suggestions from the UZH's own German vocabulary. The curator decides.
3. **Add text signals:** search the accession register / emic names («Valiha») and the region
   in other databases. Filter by region/culture to cut false neighbours.
4. **Image quality:** use full-resolution images, several views if possible, and for long objects
   also query rotated versions. DINOv2 gains clearly from rotation, SigLIP 2 does not.
5. **Ethics:** reference databases also contain outdated or colonial terms. Mark suggestions instead of
   adopting them, and respect communities' data sovereignty (Yukon, Alutiiq).
