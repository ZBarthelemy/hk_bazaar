"""Hong Kong district and region normalization."""

from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz, process

HK_REGIONS = ("Hong Kong Island", "Kowloon", "New Territories", "Outlying Islands")


@dataclass(frozen=True)
class DistrictInfo:
    name: str
    region: str
    aliases: tuple[str, ...] = ()


# Official 18 districts + common expat/local aliases (Traditional + English)
DISTRICTS: list[DistrictInfo] = [
    DistrictInfo("Central and Western", "Hong Kong Island", ("central", "mid-levels", "sheung wan", "sai ying pun", "kennedy town", "堅尼地城", "中環", "上環")),
    DistrictInfo("Wan Chai", "Hong Kong Island", ("wan chai", "causeway bay", "happy valley", "灣仔", "銅鑼灣", "跑馬地", "bay view mansion")),
    DistrictInfo("Eastern", "Hong Kong Island", ("quarry bay", "north point", "chai wan", "taikoo", "鰂魚涌", "北角", "柴灣", "太古")),
    DistrictInfo("Southern", "Hong Kong Island", ("aberdeen", "stanley", "repulse bay", "pokfulam", "薄扶林", "赤柱", "香港仔")),
    DistrictInfo("Yau Tsim Mong", "Kowloon", ("tsim sha tsui", "tst", "mong kok", "jordan", "yau ma tei", "尖沙咀", "旺角", "佐敦", "油麻地")),
    DistrictInfo("Sham Shui Po", "Kowloon", ("sham shui po", "cheung sha wan", "深水埗", "長沙灣")),
    DistrictInfo("Kowloon City", "Kowloon", ("kowloon city", "kowloon tong", "hung hom", "ho man tin", "wong tai sin", "黃大仙", "九龍塘", "紅磡", "何文田")),
    DistrictInfo("Wong Tai Sin", "Kowloon", ("wong tai sin", "黃大仙")),
    DistrictInfo("Kwun Tong", "Kowloon", ("kwun tong", "觀塘")),
    DistrictInfo("Kwai Tsing", "New Territories", ("kwai chung", "tsing yi", "葵涌", "青衣")),
    DistrictInfo("Tsuen Wan", "New Territories", ("tsuen wan", "荃灣")),
    DistrictInfo("Tuen Mun", "New Territories", ("tuen mun", "屯門")),
    DistrictInfo("Yuen Long", "New Territories", ("yuen long", "元朗")),
    DistrictInfo("North", "New Territories", ("sheung shui", "fanling", "上水", "粉嶺")),
    DistrictInfo("Tai Po", "New Territories", ("tai po", "大埔")),
    DistrictInfo("Sha Tin", "New Territories", ("sha tin", "ma on shan", "沙田", "馬鞍山")),
    DistrictInfo("Sai Kung", "New Territories", ("sai kung", "tseung kwan o", "西貢", "將軍澳")),
    DistrictInfo("Islands", "Outlying Islands", ("lantau", "tung chung", "discovery bay", "大嶼山", "東涌")),
    # Common neighbourhood names not matching a single district
    DistrictInfo("Yau Yat Chuen", "Kowloon", ("yau yat chuen", "又一村")),
    DistrictInfo("Pok Fu Lam", "Hong Kong Island", ("pok fu lam", "pokfulam")),
]

_ALIAS_TO_DISTRICT: dict[str, DistrictInfo] = {}
for d in DISTRICTS:
    _ALIAS_TO_DISTRICT[d.name.lower()] = d
    for alias in d.aliases:
        _ALIAS_TO_DISTRICT[alias.lower()] = d

CHOICES = list(_ALIAS_TO_DISTRICT.keys())


def normalize_location(text: str | None) -> tuple[str | None, str | None, str | None]:
    """
    Map free-text location to (location_raw, district, region).

    Uses fuzzy matching for English/Chinese neighbourhood names found in listing text.
    """
    if not text or not text.strip():
        return None, None, None

    raw = text.strip()
    lower = raw.lower()

    # Direct substring match first (fast path)
    for alias, info in sorted(_ALIAS_TO_DISTRICT.items(), key=lambda x: -len(x[0])):
        if alias in lower:
            return raw, info.name, info.region

    # Fuzzy match on comma-separated tokens
    tokens = [t.strip() for t in raw.replace("，", ",").split(",") if t.strip()]
    for token in tokens:
        match = process.extractOne(token.lower(), CHOICES, scorer=fuzz.partial_ratio)
        if match and match[1] >= 85:
            info = _ALIAS_TO_DISTRICT[match[0]]
            return raw, info.name, info.region

    # Whole-string fuzzy
    match = process.extractOne(lower, CHOICES, scorer=fuzz.partial_ratio)
    if match and match[1] >= 80:
        info = _ALIAS_TO_DISTRICT[match[0]]
        return raw, info.name, info.region

    return raw, None, None


def extract_location_from_text(*texts: str | None) -> tuple[str | None, str | None, str | None]:
    """Scan title + description for pickup/location hints."""
    combined = " ".join(t for t in texts if t)
    return normalize_location(combined)