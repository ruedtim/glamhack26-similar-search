# Similar Search – feasibility PoC for «To Be Renamed!» (GLAMhack 2026, project 321)

**Results (German):** [overview of the most promising results](https://ruedtim.github.io/glamhack26-similar-search/),
[all 1,019 VMZ objects with suggestions](https://ruedtim.github.io/glamhack26-similar-search/review/index.html)
([Excel](https://ruedtim.github.io/glamhack26-similar-search/review/vmz_suggestions.xlsx)) and, behind the switch
«VMZ | MKB», [all 7,310 MKB objects](https://ruedtim.github.io/glamhack26-similar-search/review/mkb.html) compared
with the other collections.

**Offline copy:** [download the ZIP](https://github.com/ruedtim/glamhack26-similar-search/releases/latest/download/glamhack26-similar-search-offline.zip)
(69 MB, attached to the latest [release](https://github.com/ruedtim/glamhack26-similar-search/releases)). Unpack it
and double-click `START.html`. It works in any current browser, without a web server or internet.
`make_offline_zip.py` builds it from `docs/`.

The raw challenge data (VMZ catalogue export as Excel, «Objektliste» PDFs) is **not** in this repository.

Question from the challenge: *Can image similarity searches help identify comparable objects in other
collections?* The idea is that comparable objects in other collections supply better object names
(e.g. «Bambusgitarre» → «Röhrenzither», «Figur» → «Gottheitsstatue»).

## Bottom line

**Feasible as a research aid that shows a curator evidence. Not as automatic renaming.**

- In the proxy test, image similarity puts the correct name among the 5 nearest neighbours in about
  55–68 % of cases. The prerequisite is that the name occurs in the reference set at all. Chance is about 2–3 %.
- Zero-shot naming against a fixed vocabulary (SigLIP 2, image↔term) is stronger than taking names
  from neighbours: Top-1 53 %, Top-5 78 %. The museum's own German vocabulary can serve as the term list.
- On the real slide objects: the «Figur auf Sockel» works well (neighbours: Chinese deity and tomb figures,
  including a «Daoist Immortal»; zero-shot: «Gottheitsstatue»). The «Bambusgitarre/Valiha» fails as a
  ~120 px thumbnail: the models see a bamboo stick. The British Museum tube zither only ranks 37th.
- The strongest single signal for the valiha is not the image but the text: «Eingangsbuch:
  Bambusguitarre (Valiha)». So the method should be **multimodal**: image + old inventory entries /
  emic names + region.
- **Real sample (1,019 VMZ objects with «?», quotation marks or only «Figur»):** once the reference set is
  embedded, the suggestions for all objects take about 1.5 min at half GPU load. They give useful evidence for
  many objects:
  - 31 % of the 475 «?» hypotheses are clearly supported by the photo (among the top 2 % of 2,434 VMZ terms;
    by chance 2 %), another 29 % are possible;
  - more specific terms from the museum's own vocabulary, and neighbours that already carry the right name
    (10 of the 12 nearest neighbours of a «Goldgewicht» are gold weights);
  - for objects named only «Figur», specific proposals such as «Kraftfigur, nkisi», «Sakyamuni Buddha» or «Puppe».
- German terms have to be machine-translated to English before SigLIP 2 ranks them well. Ethnographic
  collections with German type names help naming more than large art-museum sets. The coverage of the
  reference set is the main limit.

## Current state (14.11.2026)

**Query objects:** 1,019 VMZ objects with a photo: 510 with «?» and 242 with quotation marks (4 have both),
from the two «Objektliste» PDFs, plus 271 objects named only «Figur» (separate photos).

**Per object, the list shows** (`suggest_vmz.py`):
- the visually most similar objects in other collections, with name, museum and link. Models: SigLIP 2 so400m
  and DINOv2, weighted rank fusion (DINOv2 × 0.25). 21 «hub» objects, which would be among the top 5 for ≥ 10
  photos, are hidden;
- a second row «Ähnlich und aus derselben Region» (geographic layer, `geo.py`; 464 objects have one);
- terms from the VMZ's own vocabulary (2,434 type terms from the catalogue names, machine-translated to
  English), ranked against the photo;
- the rank of every term in the current name («?» hypothesis check): rank ≤ 49 (top 2 %) = supported,
  ≤ 243 (top 10 %) = possible. Calibration on the certain type terms of the current names (n = 370):
  37 % supported, 34 % possible, median rank 95;
- catalogue objects with the same native name, and objects with the same designation in the MKB
  «Sammlung Europa» (text only; 263 VMZ objects have matches);
- non-sensitive catalogue fields (see «Publication rules»).

**MKB list (switch «VMZ | MKB» in both lists):** `suggest_mkb.py` takes all 7,310 MKB objects with an image
(African collection, via PARC) as the starting point. Per object it shows the 8 most similar objects in the other
collections (21,164 objects, including the 1,019 VMZ objects, which link to their entry in the VMZ list), the
ranks of the terms in the current MKB name, and the best terms from the VMZ vocabulary. Models, vocabulary and
thresholds are the same as in the VMZ list; the hub threshold scales with the number of photos (top 5 of ≥ 98
photos; 6 objects hidden).
- The photo supports the type term of the current MKB name for 54 % of the 7,283 objects with a certain name
  (possible: 26 %, median rank 39; VMZ list, certain type terms: 37 %). Possible reasons: the MKB photos are
  larger, and the names are mostly common type terms («Löffel», «Maske», «Armring»).
- 1,754 MKB objects have a VMZ object among their 8 nearest neighbours (filter «mit ähnlichem VMZ-Objekt»).
- The page holds all objects as JSON (4.7 MB) and shows 50 at a time. Search, filters (only «?», only «Figur»,
  with a VMZ neighbour; name supported / possible / not supported) and paging run in the browser, also offline.

**Reference set: 27,610 objects from other collections**

| Source | Objects | Route | Images on the public pages |
|---|---|---|---|
| Cleveland Museum of Art | 7,977 | Open Access API, CC0 | yes |
| Museum der Kulturen Basel (MKB), African collection | 7,310 | open IIIF interface of PARC – Portal for African Research Collections (Universität Basel) | yes. PARC marks them «In Copyright»; an MKB employee approved publication for this project on 13.11.2026 (credit «Museum der Kulturen Basel») |
| Smithsonian: Freer\|Sackler, National Museum of African Art, National Museum of the American Indian | 4,840 | bulk metadata on the AWS Registry of Open Data, CC0 media only | yes |
| museum-digital: Ethnologisches Museum and Museum Europäischer Kulturen (Berlin), Übersee-Museum Bremen | 3,171 | open JSON API, searched with the 300 most frequent VMZ type terms | yes (CC BY-NC-SA, CC BY-SA) |
| Mapping Philippine Material Culture | 1,944 | Omeka REST API (10,481 objects from 97 collections); includes 172 MKB and 167 PRM objects | yes, as comparison thumbnails with link (rights stay with the holding museums), except PRM |
| Pitt Rivers Museum (PRM), Oxford | 1,475 | the PRM's public research microsites (Lower Gallery, Arms and Armour, Body Arts, Southern Sudan) | **no.** The images are used for the similarity computation only (non-commercial research use). Online publication needs a PRM licence, so the pages show name, museum and link |
| Museum Rietberg: Hans Himmelheber archive | 893 | Open Data Zürich (also on opendata.swiss), CC BY-SA | yes |

Text layer without images: MKB «Sammlung Europa» on data.bs.ch (73,733 records, CC BY 4.0).

**Checked, not used:**
- PRM Collections Online: its API key sits in the website code, so it is not used.
- MKB online collection (onlinecollection.mkb.ch): its search answered HTTP 403 on 13.11.2026, also in a
  browser. Not worked around.
- Yukon «Searching for our heritage»: Cloudflare bot protection (HTTP 403). Only through cooperation.
- Amutat (Alutiiq Museum): technically easy, but Indigenous heritage: ask first (CARE principles).
- NMNH Anthropology: its open dump has no CC0 images. The Met: `/search` returned no results for automated access.
- Museum Rietberg «Kamerun» (no image links), «Patolu» and «Drenowatz» (narrow topics).

**Publication rules** (the public pages: `suggest_vmz.py --public`, `make_overview.py`):
- Public: the VMZ photos and non-sensitive catalogue fields: dimensions, acquisition type and year, original
  number, exhibitions, literature, documentation, maker, continent/world region/place/country, religion,
  language, attribution note, number of units. Descriptions only for acquisitions before 1980. They can quote
  the object description from the accession register («Eingangsbuch: Körbe … aus Palmblattfasern …»), but
  sentences about persons, purchase/gift, collections, values or years from 1980 on are removed («[gekürzt]»).
- Not public: the fields collector, provenance, accession register and internal check notes; supplier/donor
  names; the raw Excel and the «Objektliste» PDFs.
- Reference images: thumbnails with link and credit, MKB with consent, PRM never (see the table).

## Development log (13–14.11.2026)

How the PoC grew during the hackathon. Numbers are as measured at each step; the current state is
described above.

### Proxy evaluation

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

### Dry run with 17 real UZH objects

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

### Real GLAMhack sample: 748 VMZ objects with «?» or quotation marks

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
- **neighbours** in the reference set (then 3,163 objects from other collections);
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
- `docs/index.html`: overview of the most promising examples (until 14.11.2026 also as a PDF), made with
  `make_overview.py`.
- `docs/review/`: all objects, with search and filters, plus `vmz_suggestions.xlsx` (one row per object for
  curators) and `vmz_results.json`.
- Both are published via GitHub Pages. At this step they contained no catalogue excerpts; the
  non-sensitive fields came later (see «Second search layer» below and «Publication rules» above).
- Running `suggest_vmz.py` without `--public` writes an internal variant with accession register,
  collector and provenance (e.g. to `vmz_review/`, gitignored).

### Extended reference set: +12,317 CC0 objects

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
  ≥ 10 VMZ photos; that hid 31 objects at this step (21 in the final run).
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
  art-museum data. The next steps followed this.

### German type names from museum-digital

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

### Second search layer, more catalogue data, MKB and PRM

**Models: SigLIP 2 leads, DINOv2 only as a minor voice.** Measured on the 748 VMZ objects (top-5 neighbour
names, hub filter, 18,651 reference objects):

| Neighbour search | type term confirmed | «?» hypothesis confirmed |
|---|---|---|
| SigLIP 2 only | 22.1 % | 16.2 % |
| DINOv2 only | 14.1 % | 9.3 % |
| rank fusion 1 : 1 (before) | 20.4 % | 14.1 % |
| **weighted fusion, DINOv2 × 0.25 (now)** | **22.6 %** | **16.0 %** |

DINOv2 judges shape and texture only. SigLIP 2 was trained on image–text pairs and so finds objects «of
the same kind», which is what naming needs. A third model is less promising than a larger SigLIP 2 variant
(tested in the next section: so400m is better).

**Geographic layer (`geo.py`).**
- Country, world region and continent come from the VMZ catalogue (world region and ISO code).
- For the reference objects they come from their culture, name and description texts. The lookup tables
  are built from the VMZ catalogue itself: country names (German/English), region and place names, and
  ethnic groups → country/world region. Only the English demonyms («Japanese», «South Asians») are
  hand-made.
- Located share: Philippines database 100 %, Cleveland 97 %, Rietberg 87 %, Smithsonian 83 %.
  museum-digital has places only in the object records; `enrich_md_places.py` fetches them into a cache.
  The cache was still incomplete for this measurement; in the final run it covers all 3,171 objects.
- The list shows a second row per object: «Ähnlich und aus derselben Region» (the visually most similar
  objects among 200 per model, same world region or country).
- Result: 446 objects have ≥ 5 regional neighbours. Their names confirm the type term less often than the
  purely visual neighbours: 18 % vs 24 % (n = 280); «?» hypotheses 8 % vs 16 % (n = 223). Final run:
  464 objects; 23 % vs 23 % (n = 284) and 9 % vs 13 % (n = 229).
- So the layer is an additional view (comparison pieces from the same cultural context), not a better
  source of names.

**More catalogue fields on the public list.**
- Shown in a fold-out block per object: the fields listed under «Publication rules».
- The description is shown only for acquisitions before 1980. Sentences about persons, purchase/gift,
  collections, values or years from 1980 on are removed automatically («[gekürzt]»).
- Not published: collector, provenance, accession register and internal check notes.
- `ingest_vmz.py --catalog-only` rewrites the catalogue with all columns.

**Museum der Kulturen Basel.**
- All 172 MKB objects in the Philippines database are in the reference set (`harvest_mkb.py`).
- The MKB «Sammlung Europa» on data.bs.ch has 73,733 records (CC BY 4.0) but no images. It is used as a
  **text layer**: same designation in the MKB (short name, title, origin, inventory number; no supplier
  names). 263 VMZ objects get matches.
  - Example «„Schnabelgeiss“, mit Traggestell» (09947): three MKB Schnabelgeiss objects, among them
    «Schnabelgeiss für Neujahrsumzug» (Poland). This supports the VMZ use «[Kostüm für Altjahr/Silvester?]».
  - Another one is **«SVZ 9299», a mask from Ottenbach (ZH)**. The VMZ catalogue lists 09299
    «Schnabelgeiss» from the Knonauer Amt, so this may be the same object (to be checked).
- The MKB online collection (onlinecollection.mkb.ch) is CC BY 4.0. On 13.11.2026 its search service
  answered 403, also interactively in the browser, and this was not worked around. The MKB images came via
  PARC instead (next section).

**Pitt Rivers Museum.**
- The PRM objects of the Philippines database are in (`harvest_mkb.py --collection 275`; 167 in the final
  reference set).
- The PRM's own database (Collections Online) only works with a key embedded in its website and is not used.
  The PRM's public research microsites turned out to be a legitimate route (next section).

### Larger model, «Figur» objects, MKB and PRM images

**SigLIP 2 so400m instead of base.** `compare_models.py` compares the models on the 748 «?»/quotes objects
against 18,825 reference objects:

| | type term among top-5 neighbour names | «?» hypothesis among them | term ranking: median rank of the certain type term (of 2,434) |
|---|---|---|---|
| SigLIP 2 base + DINOv2 × 0.25 | 22.6 % | 15.8 % | 155 |
| **SigLIP 2 so400m + DINOv2 × 0.25 (now)** | **23.9 %** | **17.3 %** | **96** |
| SigLIP 2 so400m alone | 23.9 % | 16.8 % | – |
| DINOv2 alone | 14.3 % | 9.3 % | – |

- so400m (google/siglip2-so400m-patch14-224, 4.5 GB) is better on almost every measure, most clearly in
  the term ranking. The neighbour gain is small (within noise).
- Embedding ~20,000 images took 25 min at half GPU load.
- `embed.py --models siglip2_so400m`, `suggest_vmz.py --text-model siglip2_so400m`. Embeddings are matched
  to records by id (`ids_<model>.json`).

**271 objects named only «Figur»** (`data/VMZ_figure`, photos named by inventory number; imported with
`ingest_vmz.py --images data/VMZ_figure --flag Figur`). This is the core case of the challenge.
- The list has a filter «nur Figur».
- Calibration figures are still computed on the «?»/quotes sample only, and so is the hub filter (similar
  figures are expected to share neighbours).
- Typical suggestions: neighbours named «Männliche/Weibliche Kraftfigur, nkisi» for Kongo figures,
  «Sakyamuni Buddha» / «Bodhisattva» for Javanese bronzes, «Puppe» for a Japanese costume doll. VMZ terms
  such as Wächterfigur, Hochzeitsfigur, Votivfigur and Götterfigur also come up.

**Museum der Kulturen Basel, 7,310 objects with images** (`harvest_mkb_online.py`).
- Source: the open IIIF interface of PARC – Portal for African Research Collections (Universität Basel),
  which the MKB links for its African collection.
- The MKB online collection's search answered 403 on 13.11.2026 and was not worked around.
- Index-card scans, photo-collection items, films and books are skipped.
- No supplier names are stored.
- PARC marks the images «In Copyright». Publication for this project was approved by an MKB employee on
  13.11.2026 (credit «Museum der Kulturen Basel»).

**Pitt Rivers Museum, 1,475 objects with images** (`harvest_prm.py`).
- Source: the PRM's own public research microsites (Lower Gallery, Arms and Armour, Body Arts, Southern
  Sudan).
- Collections Online is not used, because its API key sits in the website code.
- Objects with human remains or secret/sacred contexts are skipped (84).
- The PRM allows non-commercial research use. Online publication needs a PRM licence, so **PRM objects
  appear on the public pages only as text cards (name, museum, link)**. The 173 previously published
  thumbnails of PRM/MKB objects (from the Philippines database) were removed from `docs/`; they remain in
  older commits.
- `merge_staged.py --no-publish-images` merges staged harvests. `suggest_vmz.can_publish` decides per
  holder.

Final run: 1,019 VMZ objects (506 «?», 238 quotes, 4 both, 271 «Figur») against **27,610 reference objects**
(Cleveland 7,977, MKB 7,310, Smithsonian 4,840, museum-digital 3,171, Philippines database 1,944,
PRM 1,475, Rietberg 893).

### Offline copy and navigation (14.11.2026)

- The list of all objects links back to the overview (at the top and in the sticky filter bar). The overview
  links each example to its entry in the list.
- All links name `index.html` explicitly: opened from disk, a link to `review/` shows a folder listing.
- `make_offline_zip.py` builds the ZIP with `START.html` and `LIESMICH.txt`. Before zipping it checks that every
  local link, image and anchor exists, that nothing is loaded from the internet, and that all file names are
  ASCII (Windows does not always unpack other names correctly; five thumbnails of «Stü …» objects were
  renamed for this). The ZIP is attached to the GitHub release `offline-2026-11-14`; the overview and this
  README link the latest release's ZIP.
- The Rietberg licence is corrected to CC BY-SA (Open Data Zürich). The harvester had recorded CC BY, and
  this was in `vmz_results.json`; the pages already said CC BY-SA.

### MKB list and switch, no PDF (14.11.2026)

- A switch «VMZ | MKB» in the sticky bar of both lists leads to the new MKB list with all 7,310 MKB objects
  (see «Current state»). `suggest_mkb.py` shares the list CSS (`LIST_CSS`) and the switch (`switch_html`) with
  `suggest_vmz.py`; it takes about 70 s at half GPU load.
- The PDF export of the overview was removed, online and in the ZIP. `make_overview.py` no longer prints a PDF.
- The ZIP grows to 69 MB (18,586 files). `make_offline_zip.py` now also checks the image paths and anchors inside
  the data embedded in the MKB list.

## Run

```bash
uv venv --python 3.12 venv && uv pip install --python venv/bin/python torch transformers pillow numpy requests pymupdf sentencepiece protobuf openpyxl

# 1. early proof of concept: Philippines database, Cleveland sample, 17 UZH objects
venv/bin/python harvest.py --out data            # ~4 min, ~30 MB images (672 Phil + 500 CMA)
venv/bin/python harvest_extra.py --out data      # ~4 min: 17 UZH objects, +1,100 Phil, 932 Rietberg
GPU_SHARE=0.5 venv/bin/python embed.py --data data --queries queries   # incremental; queries/q_*.png
venv/bin/python evaluate.py --data data --queries queries --html results.html
GPU_SHARE=0.5 venv/bin/python suggest.py --data data --html uzh_review.html

# 2. reference set for the VMZ sample
venv/bin/python harvest_more.py --out data      # Cleveland departments, Smithsonian (CC0)
venv/bin/python harvest_md.py --out data        # German type names: museum-digital (EM Berlin, Übersee-Museum, MEK)
venv/bin/python enrich_md_places.py --data data # places of the museum-digital objects (cache, resumable; slow API)
venv/bin/python harvest_mkb.py --out data       # MKB objects of the Philippines database
venv/bin/python harvest_mkb.py --out data --collection 275                # PRM objects of the Philippines database
venv/bin/python harvest_mkb_online.py --out data/mkb_online   # MKB via PARC (IIIF), staged; see its docstring
venv/bin/python harvest_prm.py --out data/prm   # PRM research microsites, staged; see its docstring
venv/bin/python merge_staged.py --data data --staged data/mkb_online --records records_mkb_online.jsonl
venv/bin/python merge_staged.py --data data --staged data/prm --records records_prm.jsonl --no-publish-images
curl -o data/mkb_europa.json "https://data.bs.ch/api/explore/v2.1/catalog/datasets/100148/exports/json?select=inventarnummer,kurzbezeichnung,titel,datierung,material_technik,herkunft"

# 3. the VMZ sample (internal files from the challenge, gitignored)
venv/bin/python ingest_vmz.py --xlsx VMZ_Sammlungsobjekte_20261112_fuerGlamhack_.xlsx \
  --pdf VMZ_objects-with-questionmark.pdf --pdf VMZ_objects-with-quotation-marks.pdf --out data   # ~30 s
venv/bin/python ingest_vmz.py --xlsx VMZ_Sammlungsobjekte_20261112_fuerGlamhack_.xlsx --out data --images data/VMZ_figure --flag Figur

# 4. embeddings (incremental), pages, offline ZIP
GPU_SHARE=0.5 venv/bin/python embed.py --data data --queries queries --models siglip2,dinov2,siglip2_so400m
GPU_SHARE=0.5 venv/bin/python suggest_vmz.py --data data --public --out docs/review --text-model siglip2_so400m   # ~1.5 min
GPU_SHARE=0.5 venv/bin/python suggest_mkb.py --data data --out docs/review --text-model siglip2_so400m   # MKB list
venv/bin/python make_overview.py --data data --results docs/review/vmz_results.json --out docs
venv/bin/python make_offline_zip.py             # -> dist/glamhack26-similar-search-offline.zip (gitignored; upload to a release)

# 5. comparisons
venv/bin/python compare_refs.py --data data --before data/records_before_more.jsonl   # old vs. new reference set
GPU_SHARE=0.5 venv/bin/python compare_models.py --data data --models siglip2,siglip2_so400m,dinov2
```

`GPU_SHARE=0.5` throttles the GPU to ~50 % load with a duty cycle (a pause after each batch, half the
CPU threads). It's quieter and takes about twice as long. `embed.py` only computes vectors for new objects.

`evaluate.py` was evaluated on the first reference set (1,172 objects), not on the extended one.

`results.html` and `uzh_review.html` are generated locally and not published (images © the respective museums).

- `harvest.py` – fetches images + names only from open, documented APIs (politely: max. 3–6 parallel requests).
- `models.py` – SigLIP 2 base and so400m (multilingual image–text) and DINOv2 base (visual only). Pads images
  to a square instead of cropping them, so long objects stay complete.
- `embed.py` – embeddings for the reference set and the query images (M2 Max/MPS: ~12 s per 1,000 images with
  the base models).
- `evaluate.py` – proxy metrics, zero-shot with German terms, and `results.html` with neighbours.
- `ingest_vmz.py` – imports the VMZ catalogue (Excel), the photos from the «Objektliste» PDFs and the «Figur» photos.
- `suggest_vmz.py` – suggestions for the VMZ objects: neighbours, VMZ vocabulary (via MT), hypothesis
  ranks, native names, geographic layer, MKB text layer; writes the list page, Excel and JSON.
- `harvest_more.py` – more reference objects (Cleveland departments, Smithsonian Freer|Sackler, NMAfA, NMAI; CC0).
- `harvest_md.py` – reference objects with German type names from museum-digital (open JSON API).
- `enrich_md_places.py` – places/peoples of the museum-digital objects for the geographic layer (cache only).
- `harvest_mkb.py` – all objects of one holding museum in the Philippines database (MKB, PRM).
- `geo.py` – geographic layer: country / world region / continent from the VMZ catalogue and reference texts.
- `harvest_mkb_online.py`, `harvest_prm.py` – MKB (via PARC) and Pitt Rivers Museum harvests (staged).
- `merge_staged.py` – merges staged harvests; `compare_models.py` – compares the image models.
- `compare_refs.py` – compares two reference sets on the VMZ objects (coverage and name confirmation).
- `suggest_mkb.py` – the MKB list (`docs/review/mkb.html`): all MKB objects as starting point, neighbours in
  the other collections including the VMZ objects, terms from the VMZ vocabulary.
- `make_overview.py` – the overview page for the challenge owners (`docs/index.html`).
- `make_offline_zip.py` – the offline copy of `docs/` as a ZIP, with link check.

The query images `q_uzh25744_figur_auf_sockel.png` and `q_uzh00001_bambusgitarre.png` are crops from
the challenge slides. `data/` and `venv/` are not in the repository; rebuild them with the commands above.

## Recommendation for the hackathon

1. **Reference set:** the PoC uses the Philippines database, CC0 sources, museum-digital, the MKB's African
   collection (via PARC), the PRM microsites and Rietberg open data. Most useful next: the MKB's other
   collections with images, an image licence (and an export) from the PRM, an export from the Rietberg, and
   more from museum-digital (the Ethnologisches Museum Berlin alone has ~77,000 objects there).
2. **Per object with a generic name:** show the top-k similar objects (with link and holding museum),
   plus SigLIP 2 zero-shot term suggestions from the UZH's own German vocabulary. The curator decides.
3. **Add text signals:** search the accession register / emic names («Valiha») in other databases. The
   geographic layer already shows similar objects from the same region as a second row; it adds context
   rather than better names.
4. **Image quality:** use full-resolution images, several views if possible, and for long objects
   also query rotated versions. DINOv2 gains clearly from rotation, SigLIP 2 does not.
5. **Ethics:** reference databases also contain outdated or colonial terms. Mark suggestions instead of
   adopting them, and respect communities' data sovereignty (Yukon, Alutiiq).
