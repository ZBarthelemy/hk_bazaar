"""Bluebook catalog and valuation tests."""

from hk_bazaar.analyzers.bluebook import get_reference_price, load_catalog, value_from_match
from hk_bazaar.analyzers.product_matcher import match_product
from hk_bazaar.database.models import Listing, Platform


def test_catalog_has_ten_skus() -> None:
    assert len(load_catalog()) == 10


def test_match_iphone_13() -> None:
    match = match_product("iPhone 13 128GB 平賣")
    assert match is not None
    assert match.sku == "iphone_13_128gb"


def test_match_ikea_kallax() -> None:
    match = match_product("IKEA KALLAX shelf — urgent moving sale")
    assert match is not None
    assert match.sku == "ikea_kallax_bundle"


def test_value_iphone_13_below_reference() -> None:
    match = match_product("iPhone 13 128GB")
    assert match is not None
    valuation = value_from_match(match, listing_price=2500.0)
    assert valuation is not None
    assert valuation.verdict in {"strong_buy", "good_buy"}
    assert valuation.delta_hkd > 0


def test_value_listing_integration() -> None:
    listing = Listing(
        platform=Platform.CAROUSELL,
        external_id="t-001",
        title="iPhone 13 128GB 平賣",
        url="https://example.com",
        price=2800.0,
    )
    from hk_bazaar.analyzers.bluebook import value_listing

    valuation = value_listing(listing)
    assert valuation is not None
    assert valuation.sku == "iphone_13_128gb"
    assert get_reference_price("iphone_13_128gb", "good") == 3000.0