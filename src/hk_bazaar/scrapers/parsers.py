"""Shared HTML/JSON parsing helpers."""

from __future__ import annotations

import html
import json
import re
from typing import Any

from selectolax.parser import HTMLParser

# Handles: HKD 1,200 | $1.2k | Free | 免費 | Negotiable | 面議 | 1,200元
_PRICE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bfree\b|免費", re.I), "free"),
    (re.compile(r"negotiable|obo|ono|面議|可議", re.I), "negotiable"),
    (
        re.compile(
            r"(?:HK\$|HKD|\$|港幣|元)?\s*"
            r"(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*"
            r"([kK千萬])?",
            re.I,
        ),
        "amount",
    ),
]


def parse_price(text: str | None) -> tuple[float | None, str | None]:
    """Parse HKD price from display text. Returns (numeric_hkd, original_display)."""
    if not text or not str(text).strip():
        return None, None

    raw = html.unescape(str(text)).strip()
    normalized = raw.replace("，", ",")

    for pattern, kind in _PRICE_PATTERNS:
        match = pattern.search(normalized)
        if not match:
            continue
        if kind == "free":
            return 0.0, raw
        if kind == "negotiable":
            return None, raw
        amount_str = match.group(1).replace(",", "")
        amount = float(amount_str)
        suffix = match.group(2)
        if suffix:
            s = suffix.lower()
            if s in {"k", "千"}:
                amount *= 1_000
            elif s in {"萬", "万"}:
                amount *= 10_000
        return amount, raw

    return None, raw


def extract_json_ld_products(html_text: str) -> list[dict[str, Any]]:
    """Extract schema.org Product objects from JSON-LD script tags."""
    tree = HTMLParser(html_text)
    products: list[dict[str, Any]] = []
    for node in tree.css('script[type="application/ld+json"]'):
        if not node.text():
            continue
        try:
            data = json.loads(node.text())
        except json.JSONDecodeError:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, dict) and item.get("@type") == "Product":
                products.append(item)
    return products


def absolutize_url(base: str, path: str | None) -> str | None:
    if not path:
        return None
    if path.startswith("http"):
        return path
    return base.rstrip("/") + "/" + path.lstrip("/")


def clean_text(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = html.unescape(text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or None