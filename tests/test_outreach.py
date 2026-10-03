"""Outreach qualification and bidding tests."""

from hk_bazaar.database.models import Listing, Platform
from hk_bazaar.outreach.bidding import calculate_proposed_bid, render_offer_message, round_bid
from hk_bazaar.outreach.catalog import match_listing_to_catalog
from hk_bazaar.outreach.qualification import has_urgency_signals, qualify_listing


def test_round_bid_fifty_and_hundred() -> None:
    assert round_bid(2280) == 2300
    assert round_bid(4780) == 4800
    assert round_bid(6175) == 6200


def test_proposed_bid_is_10pct_below_ask() -> None:
    assert calculate_proposed_bid(2400, discount=0.90) == 2150
    assert calculate_proposed_bid(5200, discount=0.90) == 4700
    assert calculate_proposed_bid(3800, discount=0.90) == 3400
    assert calculate_proposed_bid(100, discount=0.90) == 90
    assert calculate_proposed_bid(28, discount=0.90) == 25


def test_match_iphone_13_catalog() -> None:
    match = match_listing_to_catalog("iPhone 13 128GB urgent sale")
    assert match is not None
    assert match.sku == "iphone_13_128gb"


def test_qualify_at_buy_target() -> None:
    listing = Listing(
        platform=Platform.CAROUSELL,
        external_id="o-1",
        title="iPhone 13 128GB",
        url="https://carousell.com.hk/p/test",
        price=2400.0,
    )
    deal = qualify_listing(listing)
    assert deal is not None
    assert deal.buy_target == 2400.0


def test_qualify_with_urgency_slightly_above_target() -> None:
    listing = Listing(
        platform=Platform.ASIA_XPAT,
        external_id="o-2",
        title="IKEA KALLAX shelf — urgent moving sale",
        url="https://asiaxpat.com/1",
        price=230.0,
    )
    deal = qualify_listing(listing)
    assert deal is not None
    assert deal.match.sku == "ikea_kallax_bundle"


def test_does_not_qualify_above_buy_target_without_urgency() -> None:
    listing = Listing(
        platform=Platform.CAROUSELL,
        external_id="o-3",
        title="iPhone 13 128GB",
        url="https://carousell.com.hk/p/test2",
        price=3200.0,
    )
    assert qualify_listing(listing) is None


def test_excellent_reference_alone_does_not_qualify() -> None:
    """Price at excellent reference but above buy_target should NOT qualify."""
    listing = Listing(
        platform=Platform.CAROUSELL,
        external_id="o-4",
        title="iPhone 13 128GB like new",
        description="Brand new condition",
        url="https://carousell.com.hk/p/test3",
        price=3400.0,
    )
    assert qualify_listing(listing) is None


def test_urgency_detection() -> None:
    assert has_urgency_signals("Moving sale sofa must go")
    assert has_urgency_signals("急售 iPhone")


def test_sony_tv_does_not_match_ps5() -> None:
    titles = [
        'Sony Bravia 52" TV',
        "Sony 5.1ch Surround Sound System Speaker Set",
        "Sony Bravia 40\" Full HD TV + Sony 600W 5.1 Cinema Surround Sound System",
    ]
    for title in titles:
        assert match_listing_to_catalog(title) is None, f"False PS5 match: {title}"


def test_ps5_still_matches() -> None:
    match = match_listing_to_catalog("PS5 Slim disc edition with 2 controllers")
    assert match is not None
    assert match.sku == "ps5_slim"


def test_message_is_english_then_cantonese_and_skips_description() -> None:
    listing = Listing(
        platform=Platform.ASIA_XPAT,
        external_id="o-msg",
        title="iPhone 13 128GB",
        url="https://hongkong.asiaxpat.com/classifieds/o-msg",
        price=2400.0,
        district=None,
        location_raw="Bought from Apple Store HK, in good shape.",
    )
    deal = qualify_listing(listing)
    assert deal is not None
    message = render_offer_message(deal, 2150, template_name="offer_default.txt.j2")
    english, cantonese = message.split("你好！", 1)
    assert "iPhone 13 128GB" in english
    assert "HKD 2150" in english
    assert "Bought from Apple Store" not in message
    assert "我對你個" in cantonese
    assert "HKD 2150" in cantonese

    listing.district = "Kwun Tong"
    deal = qualify_listing(listing)
    assert deal is not None
    placed = render_offer_message(deal, 2150, template_name="offer_default.txt.j2")
    assert "in Kwun Tong" in placed
    assert "喺 Kwun Tong 交收" in placed

    pro_max = Listing(
        platform=Platform.CAROUSELL,
        external_id="o-max",
        title="iPhone 15 Pro Max 256 GB HK$5,200Like new",
        url="https://www.carousell.com.hk/p/o-max",
        price=5200.0,
    )
    max_deal = qualify_listing(pro_max)
    assert max_deal is not None
    named = render_offer_message(max_deal, 4700, template_name="offer_carousell.txt.j2")
    assert "iPhone 15 Pro Max 256 GB" in named
    assert "HK$5,200Like new" not in named
    assert "你好！" in named


def test_platform_templates() -> None:
    from hk_bazaar.outreach.platform_outreach import template_for_platform

    assert template_for_platform("carousell") == "offer_carousell.txt.j2"
    assert template_for_platform("facebook_marketplace") == "offer_facebook.txt.j2"
    assert template_for_platform("asia_xpat") == "offer_default.txt.j2"


def test_clear_outreach_queue(db_session) -> None:
    from hk_bazaar.database.models import Listing, OutreachAttempt, OutreachStatus, Platform
    from hk_bazaar.database.outreach_crud import clear_outreach_queue, outreach_already_queued

    listing = Listing(
        platform=Platform.CAROUSELL,
        external_id="clear-test",
        title="iPhone 13 128GB",
        url="https://carousell.com.hk/p/clear-test",
        price=2800.0,
    )
    db_session.add(listing)
    db_session.flush()

    attempt = OutreachAttempt(
        listing_id=listing.id,
        platform=listing.platform,
        sku="iphone_13_128gb",
        listing_price=2800.0,
        buy_target=2400.0,
        proposed_bid=2300.0,
        message="test",
        listing_url=listing.url,
        listing_title=listing.title,
        status=OutreachStatus.DRY_RUN,
    )
    db_session.add(attempt)
    db_session.commit()

    assert outreach_already_queued(db_session, listing.id)
    cancelled = clear_outreach_queue(db_session)
    db_session.commit()
    assert cancelled == 1
    assert attempt.status == OutreachStatus.CANCELLED
    assert not outreach_already_queued(db_session, listing.id)