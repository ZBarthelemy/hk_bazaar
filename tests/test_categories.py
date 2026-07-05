"""Category mapping tests."""

from hk_bazaar.utils.categories import map_category


def test_asiaxpat_electronics() -> None:
    raw, canonical = map_category("Electronics", platform="asia_xpat")
    assert canonical == "Electronics"


def test_title_inference() -> None:
    _, canonical = map_category(None, title="iPhone 14 Pro Max 256GB")
    assert canonical == "Electronics"


def test_furniture_slug() -> None:
    _, canonical = map_category("home-living-20/furniture-73", platform="carousell")
    assert "Furniture" in (canonical or "")