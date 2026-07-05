"""Facebook Marketplace card parsing tests."""

from hk_bazaar.scrapers.facebook import parse_facebook_card


def test_parse_card_with_price_title_location() -> None:
    listing = parse_facebook_card(
        external_id="123",
        url="https://www.facebook.com/marketplace/item/123",
        text="HK$26,000\n2007 GSXR 600\nHong Kong",
    )
    assert listing.price == 26_000.0
    assert listing.price_display == "HK$26,000"
    assert listing.title == "2007 GSXR 600"
    assert listing.location_raw == "Hong Kong"


def test_parse_card_skips_just_listed_badge() -> None:
    listing = parse_facebook_card(
        external_id="456",
        url="https://www.facebook.com/marketplace/item/456",
        text="Just listed\nHK$4,000\nMacbook pro + Macbo\nHong Kong",
    )
    assert listing.price == 4_000.0
    assert listing.title == "Macbook pro + Macbo"
    assert listing.location_raw == "Hong Kong"


def test_parse_card_ignores_adjacent_ui_noise() -> None:
    listing = parse_facebook_card(
        external_id="789",
        url="https://www.facebook.com/marketplace/item/789",
        text="HK$300\nSofa\nFind Apartments Studio Share",
    )
    assert listing.price == 300.0
    assert listing.title == "Sofa"
    assert listing.location_raw is None


def test_parse_card_from_spans() -> None:
    listing = parse_facebook_card(
        external_id="abc",
        url="https://www.facebook.com/marketplace/item/abc",
        text="",
        spans=["Just listed", "HK$99", "Ptcg", "Hong Kong"],
    )
    assert listing.price == 99.0
    assert listing.title == "Ptcg"
    assert listing.location_raw == "Hong Kong"


def test_parse_card_dedupes_repeated_spans() -> None:
    listing = parse_facebook_card(
        external_id="ghi",
        url="https://www.facebook.com/marketplace/item/ghi",
        text="",
        spans=[
            "HK$8,000", "HK$8,000", "HK$8,000",
            "2001 YAMAHA DRAGSTER 400", "2001 YAMAHA DRAGSTER 400",
            "Hong Kong", "Hong Kong",
        ],
    )
    assert listing.price == 8_000.0
    assert listing.title == "2001 YAMAHA DRAGSTER 400"
    assert listing.location_raw == "Hong Kong"


def test_parse_card_truncated_location() -> None:
    listing = parse_facebook_card(
        external_id="def",
        url="https://www.facebook.com/marketplace/item/def",
        text="Just listed\nHK$7,000\nYamaha force\nHong K",
    )
    assert listing.price == 7_000.0
    assert listing.title == "Yamaha force"
    assert listing.location_raw == "Hong K"