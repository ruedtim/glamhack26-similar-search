"""Geographic layer: country (ISO code), world region and continent for VMZ and reference objects.

All lookup tables are built from the VMZ catalogue itself (no hand-made lists, except English region words):
  - country names (German and English, «Indonesien (Indonesia)») -> ISO code
  - region and place names («Sumatra», «Tibet», «Mindanao») -> ISO code (dominant country, >= 70 %)
  - ethnic groups («Dan», «Baule», «Senufo») -> ISO code (dominant country, >= 70 %)
  - ISO code -> world region and continent (VMZ labels: Westafrika, Ostasien, Melanesien …)
Reference objects are located from their culture / name / description text (n-gram lookup).
Proximity: 3 = same country, 2 = same world region, 1 = same continent, 0 = different or unknown.
"""
import json
import re
from collections import Counter, defaultdict

NO = {"", "none", "(ohne zuordnung)", "unbekannt"}
CONT_NORM = {"Amerika": "Amerikas"}
EN_REGION = {
    "west africa": "Westafrika", "western africa": "Westafrika", "central africa": "Zentralafrika",
    "east africa": "Ostafrika", "eastern africa": "Ostafrika", "southern africa": "Südliches Afrika",
    "north africa": "Nordafrika", "northern africa": "Nordafrika", "east asia": "Ostasien",
    "south asia": "Südasien", "southeast asia": "Südostasien", "south-east asia": "Südostasien",
    "central asia": "Zentralasien", "west asia": "Westasien", "near east": "Westasien", "middle east": "Westasien",
    "melanesia": "Melanesien", "polynesia": "Polynesien", "micronesia": "Mikronesien",
    "mesoamerica": "Mittelamerika", "central america": "Mittelamerika", "isthmian region": "Mittelamerika",
    "central andes": "Südamerika", "andes": "Südamerika", "south america": "Südamerika", "amazon": "Südamerika",
    "north america": "Nordamerika", "north american indian": "Nordamerika", "caribbean": "Karibik",
    "himalayas": "Südasien",
}
EN_CONTINENT = {"africa": "Afrika", "asia": "Asien", "oceania": "Ozeanien", "pacific": "Ozeanien",
                "americas": "Amerikas", "america": "Amerikas", "europe": "Europa"}
# demonyms in English museum data (Smithsonian, Cleveland) -> ISO code or world region
EN_DEMONYM_ISO = {
    "japanese": "JP", "chinese": "CN", "korean": "KR", "koreans": "KR", "indian": "IN", "indians": "IN",
    "persian": "IR", "persians": "IR", "iranian": "IR", "iranians": "IR", "egyptian": "EG", "egyptians": "EG",
    "syrian": "SY", "syrians": "SY", "tibetan": "CN", "tibetans": "CN", "nepalese": "NP", "newar": "NP",
    "thai": "TH", "vietnamese": "VN", "cambodian": "KH", "khmer": "KH", "javanese": "ID", "balinese": "ID",
    "indonesian": "ID", "turkish": "TR", "turks": "TR", "ottoman": "TR", "mughal": "IN", "iraqi": "IQ",
    "afghan": "AF", "mongol": "MN", "mongolian": "MN", "burmese": "MM", "sri lankan": "LK", "sinhalese": "LK",
    "japan": "JP", "filipino": "PH", "mexican": "MX", "peruvian": "PE", "nigerian": "NG", "ghanaian": "GH",
}
EN_DEMONYM_REGION = {
    "south asians": "Südasien", "himalayan peoples": "Südasien", "central asians": "Zentralasien",
    "east asians": "Ostasien", "southeast asians": "Südostasien", "west asians": "Westasien",
    "arabs": "Westasien", "arab": "Westasien", "near eastern": "Westasien", "sasanian": "Westasien",
    "native american": "Nordamerika", "native americans": "Nordamerika", "inuit": "Nordamerika",
    "yoruba": "Westafrika", "akan": "Westafrika",
}
INSTITUTION_CONTINENT = {"Museum Europäischer Kulturen": "Europa"}
STOP = re.compile(r"\b(peoples?|people|culture|style|dynasty|volk|empire|kingdom|region)\b", re.I)


def _norm(v):
    v = (v or "").strip()
    return "" if v.lower() in NO else v


def _names(v):
    """«Indonesien (Indonesia)» -> [indonesien, indonesia]; «Sumatra, Bidar Alam» -> [sumatra, bidar alam]"""
    out = []
    for part in re.split(r"[,;/()\[\]\n]| - ", v or ""):
        p = re.sub(r"[?\"„“”«»]|\bevtl\.?|\bOriginalkarte\b", " ", part)
        p = re.sub(r"\s+", " ", p).strip(" .-").lower()
        if len(p) >= 3 and not p.isdigit():
            out.append(p)
    return out


def _dominant(counter_map, min_share, min_count):
    out = {}
    for name, c in counter_map.items():
        iso, n = c.most_common(1)[0]
        if n >= min_count and n / sum(c.values()) >= min_share:
            out[name] = iso
    return out


class Geo:
    def __init__(self, catalog_path):
        iso_reg, iso_cont = defaultdict(Counter), defaultdict(Counter)
        reg_cont = defaultdict(Counter)
        country, region, ethnie = defaultdict(Counter), defaultdict(Counter), defaultdict(Counter)
        for line in open(catalog_path, encoding="utf-8"):
            c = json.loads(line)
            iso = _norm(c.get("iso")).upper()
            reg, cont = _norm(c.get("world_region")), CONT_NORM.get(_norm(c.get("continent")), _norm(c.get("continent")))
            if reg and cont:
                reg_cont[reg][cont] += 1
            if not iso:
                continue
            if reg:
                iso_reg[iso][reg] += 1
            if cont:
                iso_cont[iso][cont] += 1
            for n in _names(c.get("country")):
                country[n][iso] += 1
            for n in _names(c.get("geo_region")) + _names(c.get("place")):
                region[n][iso] += 1
            for n in _names(c.get("ethnie")):
                ethnie[n][iso] += 1
        # fallbacks for names that are not dominated by one country but by one world region (e.g. Dan: CI/LR)
        def to_region(table):
            out = defaultdict(Counter)
            for name, c in table.items():
                for iso, n in c.items():
                    reg = iso_reg[iso].most_common(1)[0][0] if iso_reg.get(iso) else ""
                    if reg:
                        out[name][reg] += n
            return out
        self.region_region = _dominant(to_region(region), 0.7, 3)
        self.ethnie_region = _dominant(to_region(ethnie), 0.7, 3)
        self.iso_region = {k: v.most_common(1)[0][0] for k, v in iso_reg.items()}
        self.iso_cont = {k: v.most_common(1)[0][0] for k, v in iso_cont.items()}
        self.region_cont = {k: v.most_common(1)[0][0] for k, v in reg_cont.items()}
        self.country = _dominant(country, 0.7, 1)
        self.region = _dominant(region, 0.7, 3)
        self.ethnie = _dominant(ethnie, 0.7, 3)

    def full(self, iso="", region="", cont=""):
        region = region or self.iso_region.get(iso, "")
        cont = cont or self.iso_cont.get(iso, "") or self.region_cont.get(region, "")
        return {"iso": iso, "region": region, "continent": cont}

    def vmz(self, c):
        cont = CONT_NORM.get(_norm(c.get("continent")), _norm(c.get("continent")))
        return self.full(_norm(c.get("iso")).upper(), _norm(c.get("world_region")), cont)

    def _lookup(self, text, tables):
        words = re.findall(r"[\wÀ-ÿ'-]+", STOP.sub(" ", text).lower())
        grams = [" ".join(words[i:i + n]) for n in (4, 3, 2, 1) for i in range(len(words) - n + 1)]
        for table in tables:
            for g in grams:                                  # longest n-grams first
                if g in table:
                    return table[g]
        return ""

    def ref(self, r):
        if r["source"] == "phil":
            return self.full("PH")
        text = " ; ".join(x for x in (r.get("culture"), r.get("name"), r.get("title"),
                                      r.get("desc") if r["source"] in ("cma", "si") else "") if x)
        order = ([self.ethnie, self.country, self.region] if r["source"] == "mrz"   # Rietberg: ethnic groups
                 else [self.country, self.region, self.ethnie])
        iso = self._lookup(text, order + [EN_DEMONYM_ISO])
        if iso:
            return self.full(iso)
        reg = self._lookup(text, [EN_REGION, EN_DEMONYM_REGION, self.ethnie_region, self.region_region])
        cont = self._lookup(text, [EN_CONTINENT]) or next(
            (v for k, v in INSTITUTION_CONTINENT.items() if k in (r.get("holder") or "")), "")
        return self.full("", reg, cont)


def proximity(a, b):
    if a["iso"] and a["iso"] == b["iso"]:
        return 3
    if a["region"] and a["region"] == b["region"]:
        return 2
    if a["continent"] and a["continent"] == b["continent"]:
        return 1
    return 0
