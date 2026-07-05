"""Price and JSON-LD parser tests."""

from hk_bazaar.scrapers.parsers import extract_json_ld_products, parse_price


def test_parse_price_hkd() -> None:
    assert parse_price("HKD 1,200") == (1200.0, "HKD 1,200")


def test_parse_price_k_suffix() -> None:
    assert parse_price("$1.2k")[0] == 1200.0


def test_parse_price_free() -> None:
    assert parse_price("Free") == (0.0, "Free")
    assert parse_price("免費")[0] == 0.0


def test_parse_price_negotiable() -> None:
    price, display = parse_price("Negotiable / 面議")
    assert price is None
    assert display is not None


def test_extract_json_ld() -> None:
    html = """
    <script type="application/ld+json">
    {"@type": "Product", "name": "Chair", "offers": {"price": 99}}
    </script>
    """
    products = extract_json_ld_products(html)
    assert len(products) == 1
    assert products[0]["name"] == "Chair"