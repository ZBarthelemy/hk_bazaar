"""Canonical category taxonomy and platform-specific mappers."""

from __future__ import annotations

from rapidfuzz import fuzz, process

# Top-level taxonomy for HK second-hand market
CANONICAL_CATEGORIES: dict[str, list[str]] = {
    "Electronics": [
        "electronics", "mobile", "phone", "laptop", "computer", "camera", "tv", "audio",
        "電子", "手機", "電腦", "相機",
    ],
    "Furniture": [
        "furniture", "sofa", "table", "chair", "bed", "wardrobe", "desk", "ikea",
        "傢俬", "梳化", "床", "書枱",
    ],
    "Home & Living": [
        "home goods", "home-living", "decor", "kitchen", "appliance", "lighting", "rug",
        "家居", "廚房", "燈",
    ],
    "Fashion & Accessories": [
        "clothing", "fashion", "shoes", "bag", "watch", "jewellery", "accessories",
        "服飾", "手袋", "鞋",
    ],
    "Vehicles & Parts": [
        "car", "vehicle", "motor", "bike", "bicycle", "scooter", "parts",
        "汽車", "單車", "電單車",
    ],
    "Sports & Outdoors": [
        "sports", "outdoors", "fitness", "gym", "camping", "hiking",
        "運動", "健身",
    ],
    "Books & Media": [
        "books", "media", "dvd", "vinyl", "game", "console",
        "書", "遊戲",
    ],
    "Baby & Kids": [
        "baby", "kids", "toys", "stroller", "children",
        "嬰兒", "玩具",
    ],
    "Services": [
        "service", "repair", "moving", "tutor", "cleaning",
        "服務", "搬屋",
    ],
    "Other": ["other", "misc", "free", "其他"],
}

# Flat alias -> canonical path
_ALIAS_MAP: dict[str, str] = {}
for top, aliases in CANONICAL_CATEGORIES.items():
    _ALIAS_MAP[top.lower()] = top
    for alias in aliases:
        _ALIAS_MAP[alias.lower()] = top

# asiaXPAT site categories (2026)
ASIAXPAT_CATEGORY_MAP: dict[str, str] = {
    "electronics": "Electronics",
    "furniture": "Furniture",
    "home goods": "Home & Living",
    "clothing": "Fashion & Accessories",
    "books & media": "Books & Media",
    "toys & games": "Baby & Kids",
    "appliances": "Home & Living",
    "sports & outdoors": "Sports & Outdoors",
    "other": "Other",
}

# Carousell slug fragments -> canonical
CAROUSELL_SLUG_MAP: dict[str, str] = {
    "electronics": "Electronics",
    "mobile-phones": "Electronics > Mobile Phones",
    "computers-tablets": "Electronics > Computers",
    "furniture": "Furniture",
    "home-living": "Home & Living",
    "fashion": "Fashion & Accessories",
    "cars": "Vehicles & Parts",
    "property": "Other",
    "services": "Services",
    "hobbies-games": "Books & Media",
    "baby-kids": "Baby & Kids",
    "sports": "Sports & Outdoors",
}


def map_category(
    raw: str | None,
    *,
    platform: str | None = None,
    title: str | None = None,
) -> tuple[str | None, str | None]:
    """
    Return (category_raw, canonical_category).

    Falls back to title keyword matching when raw category is missing.
    """
    category_raw = raw.strip() if raw else None

    if platform == "asia_xpat" and category_raw:
        key = category_raw.lower()
        if key in ASIAXPAT_CATEGORY_MAP:
            return category_raw, ASIAXPAT_CATEGORY_MAP[key]

    if platform == "carousell" and category_raw:
        lower = category_raw.lower()
        for slug, canonical in CAROUSELL_SLUG_MAP.items():
            if slug in lower:
                return category_raw, canonical

    if category_raw:
        key = category_raw.lower()
        if key in _ALIAS_MAP:
            return category_raw, _ALIAS_MAP[key]
        match = process.extractOne(key, list(_ALIAS_MAP.keys()), scorer=fuzz.partial_ratio)
        if match and match[1] >= 80:
            return category_raw, _ALIAS_MAP[match[0]]

    # Title-based inference
    if title:
        lower_title = title.lower()
        for top, aliases in CANONICAL_CATEGORIES.items():
            for alias in aliases:
                if alias in lower_title:
                    return category_raw, top

    return category_raw, category_raw or "Other"